"""Weak-spot drill: turn a feedback report into a focused practice interview.

The report already says what went wrong: job requirements the candidate never showed, rubric skills
that scored lowest, and improvement advice. A drill keeps the same application, interview type and
difficulty, and tells the interviewer (and the planner) to spend the session on exactly those.
Code picks the targets from the report's numbers; the model only decides how to ask about them.
"""

from statistics import mean

from interview_app.evaluation.rubric import Rubric
from interview_app.evaluation.schemas import Report
from interview_app.interview.persona import Focus, SessionConfig

# Requirement levels that still need practice ("claimed" = said, but without evidence).
WEAK_LEVELS = ("not_addressed", "not_demonstrated", "claimed")
WEAK_SKILL_BELOW = 3.5  # mean 1-5 score under which a rubric skill counts as a weak spot
MAX_REQUIREMENTS = 4
MAX_SKILLS = 3


def focus_from_report(report: Report, rubric: Rubric, source_session_id: int | None = None) -> Focus | None:
    """Pick the drill targets. None when the report shows nothing worth drilling."""
    weak_reqs = [r for r in report.requirements if r.level in WEAK_LEVELS]
    # Must-haves first, then the weakest level first (not addressed before claimed).
    weak_reqs.sort(key=lambda r: (r.priority != "must", WEAK_LEVELS.index(r.level)))
    requirements = [r.requirement for r in weak_reqs[:MAX_REQUIREMENTS]]

    scores: dict[str, list[int]] = {}
    for ex in report.exchanges:
        for item in ex.items:
            if item.score is not None and item.item in rubric.exchange_items:
                scores.setdefault(item.item, []).append(item.score)
    weakest = sorted((mean(v), k) for k, v in scores.items() if mean(v) < WEAK_SKILL_BELOW)
    skills = [rubric.exchange_items[k]["name"] for _, k in weakest[:MAX_SKILLS]]

    advice = [i.area for i in report.improvements[:3]]
    if not requirements and not skills:
        return None
    return Focus(source_session_id=source_session_id, requirements=requirements, skills=skills, advice=advice)


def drill_config(base: SessionConfig, focus: Focus) -> SessionConfig:
    """Same interview type, difficulty, mode and models as the original; one main question per target
    plus the warm-up, kept inside the allowed range."""
    targets = len(focus.requirements) + len(focus.skills)
    return base.model_copy(update={"focus": focus, "main_questions": max(3, min(8, targets + 1))})
