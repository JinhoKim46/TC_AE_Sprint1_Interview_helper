"""LLMClient tests. A fake SDK stands in for OpenRouter, so no network is used."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from interview_app.config import Settings
from interview_app.llm.client import CallRecord, LLMClient, LLMError


def completion(text: str, *, prompt_tokens: int = 10, completion_tokens: int = 5, cost: float | None = 0.001):
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    if cost is not None:
        usage.cost = cost  # OpenRouter adds the real USD cost to `usage`
    return SimpleNamespace(
        model="openai/gpt-5-mini",
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
        usage=usage,
    )


class FakeSDK:
    """Mimics `OpenAI().chat.completions.create`; returns queued replies and records requests."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def make_client(replies):
    records: list[CallRecord] = []
    sdk = FakeSDK(replies)
    client = LLMClient(Settings(openrouter_api_key="test"), recorder=records.append, sdk=sdk)
    return client, sdk, records


def test_chat_returns_text_and_records_usage():
    client, sdk, records = make_client([completion("Hello")])
    result = client.chat("interviewer", [{"role": "user", "content": "hi"}], model="openai/gpt-5-mini")

    assert result.text == "Hello"
    assert sdk.requests[0]["model"] == "openai/gpt-5-mini"
    assert len(records) == 1
    rec = records[0]
    assert (rec.role, rec.prompt_tokens, rec.completion_tokens, rec.cost_usd, rec.ok) == (
        "interviewer",
        10,
        5,
        0.001,
        True,
    )


def test_optional_settings_only_sent_when_given():
    client, sdk, _ = make_client([completion("a"), completion("b")])
    client.chat("x", [], model="m")
    client.chat("x", [], model="m", temperature=0.2, max_tokens=300, reasoning_effort="low")

    assert "temperature" not in sdk.requests[0] and "max_tokens" not in sdk.requests[0]
    assert sdk.requests[1]["temperature"] == 0.2
    assert sdk.requests[1]["max_tokens"] == 300
    # OpenRouter's unified reasoning parameter travels in the request body
    assert sdk.requests[1]["extra_body"]["reasoning"] == {"effort": "low"}


def test_missing_cost_is_recorded_as_zero():
    client, _, records = make_client([completion("a", cost=None)])
    client.chat("x", [], model="m")
    assert records[0].cost_usd == 0.0


def test_api_error_is_recorded_and_raised_as_llm_error():
    client, _, records = make_client([RuntimeError("boom")])
    with pytest.raises(LLMError):
        client.chat("judge", [], model="m")
    assert records[0].ok is False
    assert "boom" in records[0].error


class Verdict(BaseModel):
    score: int
    reason: str


def test_chat_json_parses_into_schema_and_strips_code_fences():
    client, sdk, _ = make_client([completion('```json\n{"score": 4, "reason": "clear"}\n```')])
    verdict, _ = client.chat_json("judge", [{"role": "user", "content": "rate"}], Verdict, model="m")

    assert verdict == Verdict(score=4, reason="clear")
    assert sdk.requests[0]["response_format"]["type"] == "json_schema"


def test_chat_json_repairs_once_after_invalid_reply():
    client, sdk, records = make_client([completion("not json"), completion('{"score": 2, "reason": "ok"}')])
    verdict, _ = client.chat_json("judge", [{"role": "user", "content": "rate"}], Verdict, model="m")

    assert verdict.score == 2
    assert len(records) == 2  # both attempts are billed, so both are logged
    repair_messages = sdk.requests[1]["messages"]
    assert repair_messages[-2] == {"role": "assistant", "content": "not json"}
    assert "valid JSON" in repair_messages[-1]["content"]


def test_chat_json_gives_up_after_second_invalid_reply():
    client, _, _ = make_client([completion("nope"), completion('{"score": "high"}')])
    with pytest.raises(LLMError):
        client.chat_json("judge", [], Verdict, model="m")


def test_empty_reply_counts_as_invalid_json():
    client, _, _ = make_client([completion(""), completion('{"score": 1, "reason": "r"}')])
    verdict, _ = client.chat_json("judge", [], Verdict, model="m")
    assert verdict.score == 1


def test_empty_choices_are_recorded_as_a_failure_and_raised():
    empty = completion("x")
    empty.choices = []
    client, _, records = make_client([empty])
    with pytest.raises(LLMError, match="empty response"):
        client.chat("judge", [{"role": "user", "content": "hi"}], model="m")
    assert not records[0].ok and records[0].cost_usd == 0.001  # still billed, so still logged


def test_truncated_json_is_not_repaired():
    class Out(BaseModel):
        a: int

    cut = completion('{"a": ')
    cut.choices[0].finish_reason = "length"
    client, sdk, _ = make_client([cut])
    with pytest.raises(LLMError, match="output tokens"):
        client.chat_json("judge", [{"role": "user", "content": "hi"}], Out, model="m")
    assert len(sdk.requests) == 1  # no repair round-trip
