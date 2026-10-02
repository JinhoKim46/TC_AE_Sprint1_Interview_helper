"""Group a transcript into exchanges (rubric §1): a main question, its follow-ups, and the answers.

Scoring happens per exchange rather than per turn, because a follow-up ("How did you measure that?")
only makes sense together with the answer it probes.
"""

from dataclasses import dataclass, field

from interview_app.interview.engine import TurnView

KNOWN_PREFIXES = {"OPEN", "MOT", "EXP", "TECH", "CASE", "RES", "BEH", "LOG", "CQ", "CLOSE"}

# When the interviewer used its own question (question_id CUSTOM), the stage says what kind it was.
STAGE_TO_CATEGORY = {
    "opening": "OPEN",
    "motivation": "MOT",
    "experience": "EXP",
    "technical": "TECH",
    "behavioral": "BEH",
    "gap": "EXP",
    "logistics": "LOG",
    "candidate_questions": "CQ",
    "close": "CLOSE",
}


def turn_id(idx: int) -> str:
    return f"T{idx + 1:02d}"


def category_of(question_id: str | None, stage: str | None) -> str:
    prefix = (question_id or "").split("-")[0].upper()
    if prefix in KNOWN_PREFIXES:
        return prefix
    return STAGE_TO_CATEGORY.get(stage or "", "EXP")


@dataclass
class Exchange:
    exchange_id: str
    category: str
    question_id: str | None
    question: str  # the main question's text
    turns: list[TurnView] = field(default_factory=list)

    @property
    def candidate_turns(self) -> list[TurnView]:
        return [t for t in self.turns if t.speaker == "candidate"]

    @property
    def followups(self) -> int:
        return sum(1 for t in self.turns if t.speaker == "interviewer" and t.is_followup)


def build_exchanges(turns: list[TurnView]) -> list[Exchange]:
    exchanges: list[Exchange] = []
    for t in turns:
        starts_new = t.speaker == "interviewer" and (not t.is_followup or not exchanges)
        if starts_new:
            exchanges.append(
                Exchange(
                    exchange_id=f"E{len(exchanges) + 1:02d}",
                    category=category_of(t.question_id, t.stage),
                    question_id=t.question_id,
                    question=t.text,
                )
            )
        if exchanges:
            exchanges[-1].turns.append(t)
    return exchanges
