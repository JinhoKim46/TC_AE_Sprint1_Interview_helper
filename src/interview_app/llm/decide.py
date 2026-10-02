"""The one gateway for Jev decision-model calls (OpenRouter Decisions API).

Why a decision model: for live scoring and the injection guard we need a *number* (a probability
or a level), fast and cheap, not prose. Jev returns calibrated probabilities directly, so there is
no text to parse and no "please answer in JSON" fragility. The model judges; our code applies
thresholds (none live in this module on purpose).

The API is not OpenAI-compatible, so it is called with plain httpx. Like `client.py`, every call is
recorded (tokens, cost, latency) and uses the same retry/timeout/error rules.

Request (POST `settings.openrouter_decisions_url`, header `Authorization: Bearer <key>`):

    {"model": "typesafe/jev-1.13-20260917",
     "state": {...any JSON the questions read...},
     "questions": {"<name>": {"type": "noul" | "score" | "choice", "instructions": "...", "criteria": ...}}}

`criteria` per type: noul -> {"true": "...", "false": "..."}; score -> list of level descriptions,
lowest first; choice -> {label: description}. Several questions may share one request (cheaper and
faster than one request each), which is how live scoring asks A1/A3/A6 together.

Response, observed 2026-10-02 (one request with all three types):

    {"model": "typesafe/jev-1.13-20260917",
     "answers": {
       "spec": {"type": "score", "score": 3.48,
                "legend": {"0": "Entirely generic.", ..., "4": "Quantified results plus ..."},
                "probabilities": {"0": 0, "1": 0, "2": 0, "3": 0.52, "4": 0.48},
                "confidence": 0.6},
       "cat":  {"type": "choice", "choice": "technical",
                "probabilities": {"people": 0, "technical": 1, "not_addressed": 0},
                "confidence": 1},
       "inj":  {"type": "noul", "noul": 0.01}},
     "usage": {"input_tokens": 521, "output_tokens": 70, "cost": 2.1882e-05},
     "id": "gen-dec-...", "provider": "TypeSafe"}

API quirk worth knowing: the score answer's `score` is **0-based** (it is the probability-weighted
level *index*: 0.52*3 + 0.48*4 = 3.48). The rubric numbers its levels from 1, so `ScoreAnswer.score`
= API score + 1 (here 4.48 on a 1..5 scale). `probabilities[i]` is the probability of level i+1.

Errors come back as a non-2xx status with `{"error": {"message": ..., "code": ...}}`; e.g. an unknown
question type gives 400 "Invalid discriminator value. Expected 'noul' | 'choice' | 'score'".
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from interview_app.config import Settings
from interview_app.llm.client import CallRecord, LLMError, Recorder

log = logging.getLogger(__name__)

# Rate limits and server hiccups are worth retrying; other 4xx errors mean our request is wrong,
# and sending it again would fail the same way.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


# ---------------------------------------------------------------- questions


class NoulQuestion(BaseModel):
    """A yes/no question. Jev returns the probability that the "true" criterion holds."""

    type: Literal["noul"] = "noul"
    instructions: str
    criteria_true: str
    criteria_false: str

    def to_api(self) -> dict:
        # The API requires exactly the keys "true" and "false".
        return {
            "type": "noul",
            "instructions": self.instructions,
            "criteria": {"true": self.criteria_true, "false": self.criteria_false},
        }


class ScoreQuestion(BaseModel):
    """An ordinal question. `levels` describe the levels in order, lowest first (rubric level 1 first)."""

    type: Literal["score"] = "score"
    instructions: str
    levels: list[str] = Field(min_length=2)

    def to_api(self) -> dict:
        return {"type": "score", "instructions": self.instructions, "criteria": list(self.levels)}


class ChoiceQuestion(BaseModel):
    """Pick one label. Include a no-match option (e.g. `not_addressed`) so Jev is never forced to guess."""

    type: Literal["choice"] = "choice"
    instructions: str
    options: dict[str, str] = Field(min_length=2)

    def to_api(self) -> dict:
        return {"type": "choice", "instructions": self.instructions, "criteria": dict(self.options)}


Question = NoulQuestion | ScoreQuestion | ChoiceQuestion


# ---------------------------------------------------------------- answers


class NoulAnswer(BaseModel):
    p_true: float = Field(ge=0, le=1)


class ScoreAnswer(BaseModel):
    score: float  # probability-weighted level on the rubric's 1..n scale (see module docstring)
    probabilities: list[float]  # probabilities[i] = P(level i+1)
    confidence: float | None = None  # Jev's own confidence; reported, not required

    @property
    def most_likely_level(self) -> int:
        """The single most probable level (1-based). Can differ from round(score) on split votes."""
        return max(range(len(self.probabilities)), key=self.probabilities.__getitem__) + 1


class ChoiceAnswer(BaseModel):
    choice: str
    probabilities: dict[str, float]
    confidence: float | None = None


Answer = NoulAnswer | ScoreAnswer | ChoiceAnswer


@dataclass
class DecisionResult:
    answers: dict[str, Answer]
    model: str  # the model that actually answered
    record: CallRecord


def _parse_answer(name: str, question: Question, raw: Any) -> Answer:
    """Turn one raw answer into its typed model. Raises ValueError/ValidationError if unusable."""
    if not isinstance(raw, dict):
        raise ValueError(f"answer {name!r} is not an object")
    if raw.get("type") != question.type:
        raise ValueError(f"answer {name!r} has type {raw.get('type')!r}, expected {question.type!r}")

    if isinstance(question, NoulQuestion):
        return NoulAnswer(p_true=raw["noul"])

    if isinstance(question, ScoreQuestion):
        # Keys are level indexes as strings ("0".."n-1"); turn them into a plain ordered list.
        by_index = {int(k): float(v) for k, v in raw["probabilities"].items()}
        probabilities = [by_index.get(i, 0.0) for i in range(len(question.levels))]
        if "score" in raw:
            # Prefer the API's score: it is computed from unrounded probabilities.
            score = float(raw["score"]) + 1  # 0-based level index -> 1-based rubric level
        else:
            total = sum(probabilities) or 1.0
            score = sum((i + 1) * p for i, p in enumerate(probabilities)) / total
        return ScoreAnswer(score=score, probabilities=probabilities, confidence=raw.get("confidence"))

    choice = raw["choice"]
    if choice not in question.options:
        raise ValueError(f"answer {name!r} chose unknown option {choice!r}")
    return ChoiceAnswer(
        choice=choice,
        probabilities={k: float(v) for k, v in raw["probabilities"].items()},
        confidence=raw.get("confidence"),
    )


# ---------------------------------------------------------------- client


class DecisionClient:
    # Waits between retries are backoff_base_s * 2**attempt (0.5 s, 1 s, 2 s, ...). Tests set it to 0.
    backoff_base_s: float = 0.5

    def __init__(
        self, settings: Settings, recorder: Recorder | None = None, http: httpx.Client | None = None
    ):
        self.settings = settings
        self.recorder = recorder or (lambda _record: None)
        # Injecting the httpx.Client lets tests swap in a MockTransport instead of the network.
        self.http = http or httpx.Client(timeout=settings.request_timeout_s)

    def decide(
        self,
        role: str,
        state: dict,
        questions: dict[str, Question],
        *,
        model: str | None = None,
    ) -> DecisionResult:
        """Ask one or more questions about `state` in a single request.

        `role` names the app role (guard, live_score...) for the call log. Raises LLMError if the
        call fails after retries or any question lacks a usable answer of the right type.
        """
        if not questions:
            raise ValueError("decide() needs at least one question")
        model = model or self.settings.models.jev
        payload = {
            "model": model,
            "state": state,
            "questions": {name: q.to_api() for name, q in questions.items()},
        }

        start = time.perf_counter()
        try:
            body = self._post_with_retries(payload)
        except Exception as e:
            record = CallRecord(role, model, latency_s=time.perf_counter() - start, ok=False, error=repr(e))
            self.recorder(record)
            log.warning("Jev call failed: role=%s model=%s error=%r", role, model, e)
            raise LLMError(f"The {role} decision model call failed. Please try again.") from e

        usage = body.get("usage") or {}
        record = CallRecord(
            role=role,
            model=body.get("model") or model,
            prompt_tokens=int(usage.get("input_tokens") or 0),
            completion_tokens=int(usage.get("output_tokens") or 0),
            cost_usd=float(usage.get("cost") or 0.0),
            latency_s=time.perf_counter() - start,
        )

        try:
            raw_answers = body.get("answers") or {}
            answers = {name: _parse_answer(name, q, raw_answers.get(name)) for name, q in questions.items()}
        except (KeyError, TypeError, ValueError, ValidationError) as e:
            # The call was billed, so log it with its cost, but mark it failed.
            record.ok, record.error = False, f"bad answers: {e!r}"
            self.recorder(record)
            log.warning("Jev returned unusable answers: role=%s error=%r", role, e)
            raise LLMError(f"The {role} decision model returned an unusable answer.") from e

        self.recorder(record)
        return DecisionResult(answers=answers, model=record.model, record=record)

    def _post_with_retries(self, payload: dict) -> dict:
        """POST the payload; retry network errors and 429/5xx with exponential backoff."""
        headers = {"Authorization": f"Bearer {self.settings.openrouter_api_key.get_secret_value()}"}
        attempts = self.settings.max_retries + 1  # max_retries counts *re*-tries, like the OpenAI SDK
        for attempt in range(attempts):
            last_try = attempt == attempts - 1
            try:
                response = self.http.post(
                    self.settings.openrouter_decisions_url,
                    json=payload,
                    headers=headers,
                    timeout=self.settings.request_timeout_s,
                )
            except httpx.TransportError:  # timeouts, connection resets, DNS failures
                if last_try:
                    raise
            else:
                if response.is_success:
                    return response.json()
                if response.status_code not in RETRYABLE_STATUS or last_try:
                    # The body holds the API's reason (e.g. a schema error); it never contains our key.
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
            time.sleep(self.backoff_base_s * 2**attempt)
        raise AssertionError("unreachable")
