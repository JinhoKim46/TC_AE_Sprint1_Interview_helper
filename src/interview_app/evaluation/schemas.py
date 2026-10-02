"""JSON formats of the evaluation (course task M2): what the judge returns, and the stored report.

In `ItemScore`, `rationale` and `evidence` come BEFORE `score`: the judge must write down why and
cite the transcript before committing to a number (rubric judge_settings.rationale_before_score).
Scoring first and justifying afterwards invites post-hoc rationalisation.
"""

from typing import Literal

from pydantic import BaseModel, Field

RequirementLevel = Literal[
    "not_addressed", "not_demonstrated", "claimed", "partially_demonstrated", "convincingly_demonstrated"
]


class ItemScore(BaseModel):
    item: str = Field(description="Rubric item id, e.g. A3 or S1")
    rationale: str = Field(description="One or two sentences: why this level, based on the transcript")
    evidence: list[str] = Field(description="Turn ids that support the score, e.g. ['T04', 'T06']")
    score: int | None = Field(default=None, ge=1, le=5, description="1-5, or null if there is no evidence")


class ExchangeJudgement(BaseModel):
    exchange_id: str
    items: list[ItemScore]


class RequirementEvidence(BaseModel):
    requirement: str
    priority: Literal["must", "nice"]
    rationale: str
    evidence: list[str] = Field(default_factory=list, description="Turn ids where it was discussed")
    quote: str = Field(
        default="", description="Up to 25 words quoted verbatim from the candidate in those turns"
    )
    level: RequirementLevel


class Strength(BaseModel):
    point: str = Field(description="A specific strength the candidate showed in the interview")
    evidence: list[str] = Field(description="Turn ids where it showed")
    quote: str = Field(
        default="", description="Up to 25 words quoted verbatim from the candidate in those turns"
    )


class Improvement(BaseModel):
    area: str = Field(description="Short name of the skill, e.g. 'Quantify results'")
    advice: str = Field(description="Concrete, actionable advice tied to this interview")
    example_turn: str | None = Field(default=None, description="A turn id where this showed")


class BetterAnswer(BaseModel):
    exchange_id: str
    why: str = Field(description="What the original answer was missing")
    rewrite: str = Field(description="A stronger answer using only facts from the candidate's CV and answers")


class Judgement(BaseModel):
    """Everything the judge model returns in one call."""

    exchanges: list[ExchangeJudgement]
    session_items: list[ItemScore] = Field(description="S1, S3 and S4")
    requirements: list[RequirementEvidence]
    strengths: list[Strength] = Field(description="2-4 specific strengths, each pointing at what was said")
    improvements: list[Improvement] = Field(
        description="2-4 most valuable improvements, most important first"
    )
    better_answer: BetterAnswer | None = Field(default=None, description="For the weakest exchange")
    summary: str = Field(description="Two or three sentences of overall feedback, addressed to the candidate")


class ExchangeReport(BaseModel):
    exchange_id: str
    category: str
    question: str
    score: float | None  # 0-100, weighted from the applicable items
    items: list[ItemScore]
    answer_words: int
    followups: int
    flags: list[str]


class Report(BaseModel):
    """The stored candidate report. Numbers come from code; words come from the judge."""

    overall: float | None
    band: str | None
    components: dict[str, float | None]  # requirement_coverage, experience_technical, ...
    penalties: list[str]
    exchanges: list[ExchangeReport]
    session_items: list[ItemScore]
    requirements: list[RequirementEvidence]
    strengths: list[Strength]
    improvements: list[Improvement]
    better_answer: BetterAnswer | None
    summary: str
    talk_ratio: float | None
    judge_model: str
    rubric_version: str
