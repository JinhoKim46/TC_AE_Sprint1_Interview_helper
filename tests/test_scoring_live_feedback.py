"""Live per-answer scoring (coaching mode). Jev is played by an httpx MockTransport: no network."""

import json

import httpx
import pytest

from interview_app.config import Settings
from interview_app.evaluation.live import LiveFeedback, LiveItemScore, build_tip, live_items, live_score
from interview_app.evaluation.rubric import load_rubric
from interview_app.llm.decide import DecisionClient

SETTINGS = Settings(_env_file=None, max_retries=0)
RUBRIC = load_rubric(SETTINGS.rubric_path)


def score_answer(level_index: int) -> dict:
    """A Jev score answer that is certain of one level (0-based, as the API returns it)."""
    return {
        "type": "score",
        "score": float(level_index),
        "probabilities": {str(i): float(i == level_index) for i in range(5)},
        "confidence": 1,
    }


class FakeJev:
    def __init__(self, answers: dict | None = None, status: int = 200):
        self.answers, self.status = answers or {}, status
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "nope"}})
        answers = {name: self.answers.get(name, score_answer(2)) for name in body["questions"]}
        return httpx.Response(200, json={"model": body["model"], "answers": answers, "usage": {"cost": 2e-5}})


def decider(fake: FakeJev) -> DecisionClient:
    client = DecisionClient(SETTINGS, http=httpx.Client(transport=httpx.MockTransport(fake)))
    client.backoff_base_s = 0
    return client


def run(fake: FakeJev, category="EXP") -> LiveFeedback | None:
    return live_score(
        decider(fake),
        RUBRIC,
        category=category,
        question="Walk me through the data engine.",
        answer="I built it.",
        jd_text="JD TEXT",
        cv_text="CV TEXT",
    )


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("EXP", ["A3", "A4", "A2"]),  # 2.0, 2.0, then 1.5 (A2 is listed before A6)
        ("TECH", ["A5", "A6", "A1"]),  # 2.5, 2.0, then the first of the 1.0s
        ("BEH", ["A2", "A3", "A4"]),
        ("LOG", ["A1", "A3", "A9"]),
        ("CQ", []),  # candidate questions are judged per session, not live
    ],
)
def test_items_are_the_highest_weighted_for_the_category(category, expected):
    assert live_items(RUBRIC, category) == expected


def test_one_request_with_three_rubric_questions_and_the_named_state():
    fake = FakeJev()
    run(fake)
    assert len(fake.requests) == 1  # all three items in one Jev call
    body = fake.requests[0]
    assert list(body["questions"]) == ["A3", "A4", "A2"]
    a3 = body["questions"]["A3"]
    assert a3["type"] == "score"
    assert a3["instructions"].startswith(RUBRIC.data["shared_instruction_prefix"])
    assert a3["criteria"] == RUBRIC.exchange_items["A3"]["criteria"]  # straight from rubric.json
    state = body["state"]
    assert state["jd_requirements"] == "JD TEXT" and state["cv"] == "CV TEXT"
    assert state["exchange"] == {"question": "Walk me through the data engine.", "answer": "I built it."}


def test_scores_are_one_based_with_rounded_levels():
    fake = FakeJev({"A3": score_answer(1), "A4": score_answer(3), "A2": score_answer(4)})
    feedback = run(fake)
    assert [(i.item, i.score, i.level) for i in feedback.items] == [
        ("A3", 2.0, 2),
        ("A4", 4.0, 4),
        ("A2", 5.0, 5),
    ]
    assert feedback.items[0].name == "Specificity and evidence"


def test_tip_quotes_the_next_level_of_the_weakest_item():
    fake = FakeJev({"A3": score_answer(1), "A4": score_answer(3), "A2": score_answer(4)})
    tip = run(fake).tip
    next_level = RUBRIC.exchange_items["A3"]["criteria"][2]  # level 3 of A3
    assert tip == f"To reach 3 on Specificity and evidence: {next_level}"


def test_no_tip_when_everything_is_at_the_top():
    items = [LiveItemScore(item="A3", name="Specificity and evidence", score=5, level=5)]
    assert build_tip(RUBRIC, items) is None


def test_jev_failure_returns_none():
    assert run(FakeJev(status=400)) is None


def test_category_without_items_makes_no_call():
    fake = FakeJev()
    assert run(fake, category="CQ") is None
    assert fake.requests == []


def test_half_levels_round_up():
    # Python's round() would show 2.5 as 2 (half to even); a coach reads 2.5 as "nearly 3".
    half = {**score_answer(1), "score": 1.5}  # 0-based 1.5 -> 2.5 on the 1-5 scale
    feedback = run(FakeJev({"A3": half}))
    assert feedback.items[0].score == 2.5 and feedback.items[0].level == 3
