"""Deterministic metrics (rubric §2). Code counts; the judge never has to."""

from pydantic import BaseModel

from interview_app.evaluation.exchanges import Exchange
from interview_app.evaluation.rubric import Rubric


class ExchangeMetrics(BaseModel):
    exchange_id: str
    answer_words: int
    followups: int
    long_answer: bool
    short_answer: bool


class SessionMetrics(BaseModel):
    talk_ratio: float | None  # candidate words / all words; 0.55-0.75 is healthy per the rubric
    candidate_question_count: int
    exchanges: list[ExchangeMetrics]


def words(text: str) -> int:
    return len(text.split())


def _measured_words(ex: Exchange, per_turn: bool) -> int:
    """The word count the rubric's length limits apply to.

    The limits are for one answer to the main question, so follow-up answers don't count (three short
    follow-up answers are not one long answer). A case question is answered across several turns, so
    its limits apply to each turn (the longest one is measured).
    """
    if per_turn:
        return max((words(t.text) for t in ex.candidate_turns), default=0)
    main = 0
    for t in ex.turns:
        if t.speaker == "interviewer" and t.is_followup:
            break
        if t.speaker == "candidate":
            main += words(t.text)
    return main


def compute_metrics(exchanges: list[Exchange], rubric: Rubric) -> SessionMetrics:
    per_exchange = []
    candidate_words = interviewer_words = 0
    cq_count = 0
    for ex in exchanges:
        answer = sum(words(t.text) for t in ex.candidate_turns)
        candidate_words += answer
        interviewer_words += sum(words(t.text) for t in ex.turns if t.speaker == "interviewer")
        if ex.category == "CQ":
            cq_count += sum(1 for t in ex.candidate_turns if "?" in t.text)
        limits = rubric.word_limits(ex.category)
        measured = _measured_words(ex, bool(limits and limits.get("per_turn")))
        per_exchange.append(
            ExchangeMetrics(
                exchange_id=ex.exchange_id,
                answer_words=answer,
                followups=ex.followups,
                long_answer=bool(limits and measured > limits["long"]),
                short_answer=bool(limits and ex.candidate_turns and measured < limits["min"]),
            )
        )
    total = candidate_words + interviewer_words
    return SessionMetrics(
        talk_ratio=round(candidate_words / total, 2) if total else None,
        candidate_question_count=cq_count,
        exchanges=per_exchange,
    )
