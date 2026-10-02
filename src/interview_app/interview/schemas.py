"""Structured outputs of the interviewer side (course task M2: JSON output formats).

1. `InterviewPlan` — produced once, before the interview, from the JD + CV + cover letter.
2. `InterviewerTurn` (and two variants) — produced on every interviewer turn.

Field ORDER matters for the turn variants: a model writes JSON from top to bottom, so fields placed
before `message` are generated first. `CotTurn.notes` therefore makes the model reason before it
asks (chain-of-thought), and `CritiqueTurn.draft` + `critique` make it write, check and then fix
its question (self-critique). Those private fields are stored for analysis but never shown.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class Stage(StrEnum):
    OPENING = "opening"
    MOTIVATION = "motivation"
    EXPERIENCE = "experience"
    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    GAP = "gap"
    LOGISTICS = "logistics"
    CANDIDATE_QUESTIONS = "candidate_questions"
    CLOSE = "close"


# --- 1. Interview plan --------------------------------------------------------------------------


class Priority(StrEnum):
    MUST = "must"
    NICE = "nice"


class Coverage(StrEnum):
    STRONG = "strong"  # a concrete claim with evidence (a number, a named project)
    PARTIAL = "partial"  # an adjacent claim, or no evidence
    GAP = "gap"  # nothing in the documents covers it


class Requirement(BaseModel):
    id: str = Field(description="Short id like R1, R2 ...")
    text: str = Field(description="The requirement, paraphrased from the job description")
    priority: Priority
    category: str = Field(description="technical, behavioral, domain or logistics")
    coverage: Coverage
    evidence: str = Field(description="The CV/cover-letter claim that addresses it, or 'none'")


class Probe(BaseModel):
    focus: str = Field(description="What to ask about, grounded in a concrete document detail")
    requirement_ids: list[str]
    stage: Stage
    why: str = Field(description="Why this is worth testing (e.g. a gap, an unverified number)")


class InterviewPlan(BaseModel):
    role_summary: str = Field(description="One sentence: the role, its seniority and its main focus")
    requirements: list[Requirement] = Field(description="The 5-8 most important requirements")
    probes: list[Probe] = Field(description="Ordered list of things to probe, one per planned main question")
    cv_numbers_to_verify: list[str] = Field(
        description="Strong numeric claims in the CV worth an evidence probe"
    )
    timeline_flags: list[str] = Field(
        description="Gaps, short tenures or changes of direction to ask about neutrally"
    )
    motivation_claims: list[str] = Field(
        description="Motivation claims from the cover letter to test (empty if none)"
    )


# --- 2. Interviewer turns -----------------------------------------------------------------------


class InterviewerTurn(BaseModel):
    """The basic turn format, used by P1, P2 and P4."""

    stage: Stage
    question_id: str = Field(
        description="Question-bank id such as EXP-DEEP-01, or CUSTOM, or NONE for no question"
    )
    is_followup: bool = Field(
        description="True if this probes the previous answer rather than opening a new topic"
    )
    message: str = Field(description="Exactly what you say to the candidate (1-4 sentences, one question)")
    is_final: bool = Field(description="True only for your closing turn, after the candidate's questions")


class CotTurn(BaseModel):
    """P3: private reasoning first, then the turn."""

    notes: str = Field(
        description="Private notes, never shown: what the last answer showed, which requirements are "
        "covered, "
        "what to probe next and why. On your first turn, write your interview plan here."
    )
    stage: Stage
    question_id: str
    is_followup: bool
    message: str
    is_final: bool


class CritiqueTurn(BaseModel):
    """P5: draft, check it against the rules, then the corrected turn."""

    draft: str = Field(description="Your first draft of what to say")
    critique: str = Field(
        description="Check the draft: one question only? grounded in the documents? no praise or hints? "
        "right depth for the seniority? Name every problem, or write 'ok'."
    )
    stage: Stage
    question_id: str
    is_followup: bool
    message: str = Field(description="The final, corrected text you say to the candidate")
    is_final: bool


AnyTurn = InterviewerTurn | CotTurn | CritiqueTurn


def private_fields(turn: AnyTurn) -> dict[str, str]:
    """The reasoning fields a variant produced (stored for the lab, never shown to the candidate)."""
    if isinstance(turn, CotTurn):
        return {"notes": turn.notes}
    if isinstance(turn, CritiqueTurn):
        return {"draft": turn.draft, "critique": turn.critique}
    return {}
