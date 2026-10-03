"""The one gateway for chat-model calls (and text-to-speech).

Why one gateway: every call must be logged (cost, tokens, latency) and must use the same
retry/timeout/error rules. If modules called the SDK directly, cost tracking would leak.

Provider-agnostic: OpenRouter, OpenAI, Ollama and vLLM all speak the OpenAI chat API, so the
only provider-specific values are `base_url` and the API key in `Settings`.
"""

import json
import logging
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from interview_app.config import Settings
from interview_app.llm.pricing import PriceCatalog

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class CallRecord:
    """What one call cost. Passed to the `recorder`, which usually writes an LLMCall row."""

    role: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    ok: bool = True
    error: str | None = None


@dataclass
class ChatResult:
    text: str
    model: str  # the model that actually answered (OpenRouter may resolve aliases)
    record: CallRecord
    finish_reason: str | None = None  # "length" = the reply was cut off at max_tokens


@dataclass
class SpeechResult:
    """Audio from the text-to-speech endpoint, exactly as the provider sent it."""

    audio: bytes
    content_type: str  # e.g. "audio/pcm;rate=24000;channels=1"
    record: CallRecord
    generation_id: str | None = None  # OpenRouter's X-Generation-Id, for looking the call up later


_PCM_RATE = re.compile(r"rate=(\d+)")
_PCM_CHANNELS = re.compile(r"channels=(\d+)")


def pcm_format(content_type: str) -> tuple[int, int] | None:
    """`audio/pcm;rate=24000;channels=1` -> (24000, 1). None for any other audio type.

    The sample rate travels only in the Content-Type header, so it is the one source of truth for it."""
    if not content_type.lower().startswith("audio/pcm"):
        return None
    rate = _PCM_RATE.search(content_type)
    channels = _PCM_CHANNELS.search(content_type)
    # Gemini TTS documents 24 kHz mono, so those are the fallbacks if a parameter is missing.
    return (int(rate.group(1)) if rate else 24000, int(channels.group(1)) if channels else 1)


def pcm_seconds(audio: bytes, content_type: str) -> float:
    """Duration of 16-bit PCM audio (2 bytes per sample per channel); 0.0 for other formats."""
    fmt = pcm_format(content_type)
    if fmt is None:
        return 0.0
    rate, channels = fmt
    return len(audio) / (rate * channels * 2)


class LLMError(Exception):
    """A model call failed after retries, or its output could not be used."""


Recorder = Callable[[CallRecord], None]


def _strip_code_fence(text: str) -> str:
    # Many models wrap JSON in ```json ... ``` even when told not to.
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        recorder: Recorder | None = None,
        sdk: Any = None,
        *,
        pricing: PriceCatalog | None = None,
    ):
        self.settings = settings
        self.recorder = recorder or (lambda _record: None)
        # Only used when the provider doesn't report the charged cost itself (see _cost).
        self.pricing = pricing
        # The SDK already retries 429/5xx with exponential backoff; we only set how often.
        self.sdk = sdk or OpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key.get_secret_value() or "missing-key",
            timeout=settings.request_timeout_s,
            max_retries=settings.max_retries,
        )

    def chat(
        self,
        role: str,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        response_format: dict | None = None,
    ) -> ChatResult:
        """Send one chat request. `role` names the app role (interviewer, judge...) for the call log.

        Settings left as None are not sent, so the provider's default applies. That matters because
        some models reject parameters they don't support (e.g. temperature on reasoning models).
        """
        request: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            request["temperature"] = temperature
        if max_tokens is not None:
            request["max_tokens"] = max_tokens
        if response_format is not None:
            request["response_format"] = response_format
        if reasoning_effort is not None:
            # OpenRouter's unified reasoning control (low / medium / high), not an OpenAI SDK field.
            request["extra_body"] = {"reasoning": {"effort": reasoning_effort}}

        start = time.perf_counter()
        try:
            response = self.sdk.chat.completions.create(**request)
        except Exception as e:
            record = CallRecord(role, model, latency_s=time.perf_counter() - start, ok=False, error=repr(e))
            self.recorder(record)
            log.warning("LLM call failed: role=%s model=%s error=%r", role, model, e)
            raise LLMError(f"The {role} model call failed. Please try again.") from e

        usage = response.usage
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        # Some providers answer HTTP 200 with no choices (e.g. a moderation block). It may still be
        # billed, so it is recorded with its cost, but as a failure.
        choices = getattr(response, "choices", None) or []
        record = CallRecord(
            role=role,
            model=getattr(response, "model", None) or model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=self._cost(usage, model, prompt_tokens, completion_tokens),
            latency_s=time.perf_counter() - start,
            ok=bool(choices),
            error=None if choices else "empty response (no choices)",
        )
        self.recorder(record)
        if not choices:
            log.warning("LLM call returned no choices: role=%s model=%s", role, model)
            raise LLMError(f"The {role} model returned an empty response. Please try again.")
        choice = choices[0]
        text = choice.message.content or ""
        finish_reason = getattr(choice, "finish_reason", None)
        return ChatResult(text=text, model=record.model, record=record, finish_reason=finish_reason)

    def _cost(self, usage: Any, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        # OpenRouter reports the real charged cost in `usage.cost`; prefer it whenever present.
        cost = getattr(usage, "cost", None)
        if cost is not None:
            return float(cost)
        # Other providers (OpenAI, Ollama, vLLM) don't, so estimate from the price list.
        # Look up the requested id: it matches the catalog, while the reply's model may be a dated build.
        if self.pricing is not None:
            estimate = self.pricing.estimate_cost(model, prompt_tokens, completion_tokens)
            if estimate is not None:
                return estimate
        return 0.0  # unknown; 0 keeps cost sums working

    def chat_json(
        self, role: str, messages: list[dict], schema: type[T], *, model: str, **settings
    ) -> tuple[T, ChatResult]:
        """Ask for JSON matching `schema` (a pydantic model) and return the validated object.

        If the reply doesn't validate, show the model its own reply plus the error and ask once
        more. One repair attempt fixes most slips; more attempts mostly burn money.
        """
        response_format = {
            "type": "json_schema",
            # strict=False: strict mode needs a schema subset (every field required, no defaults)
            # that ordinary pydantic models don't follow. We validate with pydantic instead.
            "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema(), "strict": False},
        }
        attempt_messages = list(messages)
        for attempt in range(2):
            result = self.chat(
                role, attempt_messages, model=model, response_format=response_format, **settings
            )
            try:
                return schema.model_validate_json(_strip_code_fence(result.text)), result
            except (ValidationError, json.JSONDecodeError, ValueError) as e:
                # A reply cut off at max_tokens would be cut off again by a repair attempt (which is
                # longer still), so asking twice only doubles the cost.
                if result.finish_reason == "length":
                    raise LLMError(f"The {role} model ran out of output tokens (raise max_tokens).") from e
                if attempt == 1:
                    raise LLMError(f"The {role} model returned output in the wrong format.") from e
                attempt_messages = [
                    *messages,
                    {"role": "assistant", "content": result.text},
                    {
                        "role": "user",
                        "content": "Your previous reply was not valid JSON for the required schema. "
                        f"Error: {str(e)[:500]}\nReply with only the corrected JSON object.",
                    },
                ]
        raise AssertionError("unreachable")

    def speech(self, role: str, text: str, *, model: str, voice: str) -> SpeechResult:
        """Text-to-speech via OpenRouter's OpenAI-compatible `/audio/speech`, recorded like a chat call.

        `with_raw_response` because the body is raw audio bytes and the format (sample rate) is only in the
        Content-Type header. `response_format="pcm"`: the Gemini TTS model accepts nothing else.
        """
        start = time.perf_counter()
        try:
            raw = self.sdk.audio.speech.with_raw_response.create(
                model=model, input=text, voice=voice, response_format="pcm"
            )
            audio = raw.content
        except Exception as e:
            record = CallRecord(role, model, latency_s=time.perf_counter() - start, ok=False, error=repr(e))
            self.recorder(record)
            log.warning("Speech call failed: role=%s model=%s error=%r", role, model, e)
            raise LLMError("The voice could not be generated.") from e
        content_type = raw.headers.get("content-type", "")
        generation_id = raw.headers.get("x-generation-id")
        prompt_tokens, completion_tokens = self._speech_tokens(text, audio, content_type)
        estimate = (
            self.pricing.estimate_cost(model, prompt_tokens, completion_tokens) if self.pricing else None
        )
        ok = bool(audio)
        record = CallRecord(
            role=role,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=estimate or 0.0,
            latency_s=time.perf_counter() - start,
            ok=ok,
            error=None if ok else "empty audio",
        )
        self.recorder(record)
        log.info(
            "Speech call: role=%s model=%s bytes=%d est_cost=%.6f generation=%s",
            role,
            model,
            len(audio),
            record.cost_usd,
            generation_id,
        )
        if not ok:
            raise LLMError("The voice model returned no audio.")
        return SpeechResult(audio, content_type, record, generation_id)

    def _speech_tokens(self, text: str, audio: bytes, content_type: str) -> tuple[int, int]:
        """ESTIMATED token counts for a speech call: the response reports no usage at all.

        Input: about 4 characters per token (the usual rule of thumb for English). Output: Gemini bills
        audio as tokens per second of audio, so seconds (from the PCM length) x `tts.audio_tokens_per_second`.
        Priced with the catalog, this gives an estimate, not the charged amount (OpenRouter's activity page
        has the real cost under the logged generation id).
        """
        prompt_tokens = math.ceil(len(text) / 4)
        seconds = pcm_seconds(audio, content_type)
        completion_tokens = math.ceil(seconds * self.settings.tts.audio_tokens_per_second)
        return prompt_tokens, completion_tokens
