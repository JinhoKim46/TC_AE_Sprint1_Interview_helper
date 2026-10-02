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
        per_exchange.append(
            ExchangeMetrics(
                exchange_id=ex.exchange_id,
                answer_words=answer,
                followups=ex.followups,
                long_answer=bool(limits and answer > limits["long"]),
                short_answer=bool(limits and ex.candidate_turns and answer < limits["min"]),
            )
        )
    total = candidate_words + interviewer_words
    return SessionMetrics(
        talk_ratio=round(candidate_words / total, 2) if total else None,
        candidate_question_count=cq_count,
        exchanges=per_exchange,
    )
