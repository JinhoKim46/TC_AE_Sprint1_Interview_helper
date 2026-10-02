"""The one gateway for chat-model calls.

Why one gateway: every call must be logged (cost, tokens, latency) and must use the same
retry/timeout/error rules. If modules called the SDK directly, cost tracking would leak.

Provider-agnostic: OpenRouter, OpenAI, Ollama and vLLM all speak the OpenAI chat API, so the
only provider-specific values are `base_url` and the API key in `Settings`.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from interview_app.config import Settings

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
    def __init__(self, settings: Settings, recorder: Recorder | None = None, sdk: Any = None):
        self.settings = settings
        self.recorder = recorder or (lambda _record: None)
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
        record = CallRecord(
            role=role,
            model=response.model or model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            # OpenRouter reports the real charged cost here; other providers don't.
            cost_usd=float(getattr(usage, "cost", 0.0) or 0.0),
            latency_s=time.perf_counter() - start,
        )
        self.recorder(record)
        text = response.choices[0].message.content or ""
        return ChatResult(text=text, model=record.model, record=record)

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
