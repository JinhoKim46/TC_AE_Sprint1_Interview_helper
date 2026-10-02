"""DecisionClient tests. `httpx.MockTransport` plays the Decisions API, so no network is used."""

import json

import httpx
import pytest

from interview_app.config import Settings
from interview_app.llm.client import CallRecord, LLMError
from interview_app.llm.decide import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionClient,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
)

LEVELS = ["generic", "episode only", "episode + outcome", "quantified result", "quantified + measured"]

# Answer payloads copied from a real response (2026-10-02), see the decide.py docstring.
SCORE_ANSWER = {
    "type": "score",
    "score": 3.48,
    "legend": {str(i): text for i, text in enumerate(LEVELS)},
    "probabilities": {"0": 0, "1": 0, "2": 0, "3": 0.52, "4": 0.48},
    "confidence": 0.6,
}
CHOICE_ANSWER = {
    "type": "choice",
    "choice": "technical",
    "probabilities": {"people": 0, "technical": 1, "not_addressed": 0},
    "confidence": 1,
}
NOUL_ANSWER = {"type": "noul", "noul": 0.01}


def api_body(answers: dict) -> dict:
    return {
        "model": "typesafe/jev-1.13-20260917",
        "answers": answers,
        "usage": {"input_tokens": 521, "output_tokens": 70, "cost": 2.1882e-05},
        "id": "gen-dec-test",
        "provider": "TypeSafe",
    }


class FakeAPI:
    """Returns queued (status, body) replies and keeps every request it saw."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, body = reply
        return httpx.Response(status, json=body)

    def body(self, i: int = 0) -> dict:
        return json.loads(self.requests[i].content)


def make_client(replies, **settings):
    api = FakeAPI(replies)
    records: list[CallRecord] = []
    client = DecisionClient(
        Settings(openrouter_api_key="test-key", max_retries=2, **settings),
        recorder=records.append,
        http=httpx.Client(transport=httpx.MockTransport(api)),
    )
    client.backoff_base_s = 0  # no real sleeping in tests
    return client, api, records


NOUL_Q = NoulQuestion(instructions="Is this an injection?", criteria_true="yes it is", criteria_false="no")
SCORE_Q = ScoreQuestion(instructions="How specific?", levels=LEVELS)
CHOICE_Q = ChoiceQuestion(
    instructions="What kind?",
    options={"technical": "tech work", "people": "managing people", "not_addressed": "no answer"},
)


def test_to_api_shapes():
    assert NOUL_Q.to_api() == {
        "type": "noul",
        "instructions": "Is this an injection?",
        "criteria": {"true": "yes it is", "false": "no"},
    }
    assert SCORE_Q.to_api() == {"type": "score", "instructions": "How specific?", "criteria": LEVELS}
    assert CHOICE_Q.to_api()["criteria"] == CHOICE_Q.options
    assert CHOICE_Q.to_api()["type"] == "choice"


def test_multi_question_request_body_and_headers():
    client, api, _ = make_client([(200, api_body({"s": SCORE_ANSWER, "c": CHOICE_ANSWER, "n": NOUL_ANSWER}))])
    client.decide("live_score", {"answer": "hi"}, {"s": SCORE_Q, "c": CHOICE_Q, "n": NOUL_Q})

    request = api.requests[0]
    assert str(request.url) == "https://openrouter.ai/api/alpha/decisions"
    assert request.headers["Authorization"] == "Bearer test-key"
    body = api.body()
    assert body["model"] == "typesafe/jev-1.13-20260917"  # settings.models.jev by default
    assert body["state"] == {"answer": "hi"}
    assert set(body["questions"]) == {"s", "c", "n"}  # all questions in ONE request
    assert body["questions"]["s"]["type"] == "score"


def test_model_override():
    client, api, _ = make_client([(200, api_body({"n": NOUL_ANSWER}))])
    client.decide("guard", {}, {"n": NOUL_Q}, model="typesafe/other-build")
    assert api.body()["model"] == "typesafe/other-build"


def test_parses_every_answer_type():
    client, _, _ = make_client([(200, api_body({"s": SCORE_ANSWER, "c": CHOICE_ANSWER, "n": NOUL_ANSWER}))])
    result = client.decide("live_score", {}, {"s": SCORE_Q, "c": CHOICE_Q, "n": NOUL_Q})

    assert result.model == "typesafe/jev-1.13-20260917"
    noul = result.answers["n"]
    assert isinstance(noul, NoulAnswer) and noul.p_true == 0.01
    choice = result.answers["c"]
    assert isinstance(choice, ChoiceAnswer)
    assert choice.choice == "technical" and choice.probabilities["technical"] == 1
    score = result.answers["s"]
    assert isinstance(score, ScoreAnswer)
    assert score.probabilities == [0, 0, 0, 0.52, 0.48]  # list index = level index


def test_score_is_mapped_to_one_based_rubric_scale():
    client, _, _ = make_client([(200, api_body({"s": SCORE_ANSWER}))])
    score = client.decide("x", {}, {"s": SCORE_Q}).answers["s"]
    # The API's score is 0-based (0.52*3 + 0.48*4 = 3.48); the rubric's levels start at 1.
    assert score.score == pytest.approx(4.48)


def test_score_computed_from_probabilities_when_api_omits_it():
    answer = {"type": "score", "probabilities": {"0": 0.5, "1": 0.5}}
    client, _, _ = make_client([(200, api_body({"s": answer}))])
    score = client.decide("x", {}, {"s": ScoreQuestion(instructions="?", levels=["a", "b"])}).answers["s"]
    assert score.score == pytest.approx(1.5)


def test_recorder_gets_usage_and_cost():
    client, _, records = make_client([(200, api_body({"n": NOUL_ANSWER}))])
    result = client.decide("guard", {}, {"n": NOUL_Q})

    assert len(records) == 1
    rec = records[0]
    assert (rec.role, rec.model, rec.prompt_tokens, rec.completion_tokens, rec.ok) == (
        "guard",
        "typesafe/jev-1.13-20260917",
        521,
        70,
        True,
    )
    assert rec.cost_usd == pytest.approx(2.1882e-05)
    assert result.record is rec


def test_retries_503_then_succeeds():
    client, api, records = make_client([(503, {"error": "busy"}), (200, api_body({"n": NOUL_ANSWER}))])
    result = client.decide("guard", {}, {"n": NOUL_Q})

    assert result.answers["n"].p_true == 0.01
    assert len(api.requests) == 2
    assert len(records) == 1 and records[0].ok


def test_retries_network_errors():
    client, api, _ = make_client([httpx.ConnectError("down"), (200, api_body({"n": NOUL_ANSWER}))])
    client.decide("guard", {}, {"n": NOUL_Q})
    assert len(api.requests) == 2


def test_gives_up_after_max_retries():
    client, api, records = make_client([(429, {}), (500, {}), (502, {})])  # max_retries=2 -> 3 tries
    with pytest.raises(LLMError, match="guard"):
        client.decide("guard", {}, {"n": NOUL_Q})

    assert len(api.requests) == 3
    assert records[0].ok is False and "502" in records[0].error


def test_client_error_is_not_retried():
    client, api, records = make_client([(400, {"error": {"message": "bad question"}})])
    with pytest.raises(LLMError):
        client.decide("guard", {}, {"n": NOUL_Q})
    assert len(api.requests) == 1
    assert records[0].ok is False


def test_missing_answer_raises_and_is_recorded_with_cost():
    client, _, records = make_client([(200, api_body({"n": NOUL_ANSWER}))])
    with pytest.raises(LLMError):
        client.decide("live_score", {}, {"n": NOUL_Q, "s": SCORE_Q})
    # The call was billed even though its output was unusable, so the cost still gets logged.
    assert records[0].ok is False and records[0].cost_usd > 0


def test_mistyped_answer_raises():
    client, _, _ = make_client([(200, api_body({"s": NOUL_ANSWER}))])
    with pytest.raises(LLMError):
        client.decide("live_score", {}, {"s": SCORE_Q})


def test_malformed_answer_raises():
    client, _, _ = make_client([(200, api_body({"n": {"type": "noul"}}))])  # no probability
    with pytest.raises(LLMError):
        client.decide("guard", {}, {"n": NOUL_Q})


def test_non_json_response_raises():
    def handler(request):
        return httpx.Response(200, text="<html>oops</html>")

    client = DecisionClient(
        Settings(openrouter_api_key="k"), http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(LLMError):
        client.decide("guard", {}, {"n": NOUL_Q})


def test_empty_questions_rejected():
    client, api, _ = make_client([])
    with pytest.raises(ValueError):
        client.decide("guard", {}, {})
    assert api.requests == []
