"""Where the user is in the app's flow (add an application -> interview -> report -> practise again).

Pure functions over the History rows, so the Home and History pages can show "what to do next" and a
score summary without any counting in the UI ("the model judges, code computes").
"""

from dataclasses import dataclass
from enum import StrEnum

from interview_app.history import SessionSummary, counts_towards_scores


class Step(StrEnum):
    ADD_APPLICATION = "add_application"
    START_INTERVIEW = "start_interview"
    RESUME_INTERVIEW = "resume_interview"
    GET_FEEDBACK = "get_feedback"
    PRACTISE = "practise"  # everything is done once: practise again or drill weak spots


def _newest_first(sessions: list[SessionSummary]) -> list[SessionSummary]:
    return sorted(sessions, key=lambda s: (s.started_at, s.session_id), reverse=True)


def next_step(applications: int, sessions: list[SessionSummary]) -> Step:
    """The one most useful next action. Only the newest interview decides "get feedback": an older
    interview without a report was most likely left without one on purpose."""
    if applications == 0:
        return Step.ADD_APPLICATION
    if not sessions:
        return Step.START_INTERVIEW
    if any(s.status == "active" for s in sessions):
        return Step.RESUME_INTERVIEW
    if not _newest_first(sessions)[0].has_report:
        return Step.GET_FEEDBACK
    return Step.PRACTISE


@dataclass(frozen=True)
class ScoreSummary:
    scored: int  # interviews with a report (any length)
    latest: float | None  # latest / best / change use Standard and Full sessions only
    best: float | None
    change: float | None  # latest minus the previous counted interview; None with fewer than two
    practice: int = 0  # scored Quick / Custom sessions, left out of latest / best / change


def score_summary(sessions: list[SessionSummary]) -> ScoreSummary:
    """Latest, best and change over comparable sessions only: a 3-question Quick practice (or a drill on
    two weak spots) is not the same test as a full interview, so its score would distort the progress."""
    scored = [s for s in _newest_first(sessions) if s.overall is not None]
    scores = [s.overall for s in scored if counts_towards_scores(s.length)]
    practice = len(scored) - len(scores)
    if not scores:
        return ScoreSummary(len(scored), None, None, None, practice)
    change = scores[0] - scores[1] if len(scores) >= 2 else None
    return ScoreSummary(len(scored), scores[0], max(scores), change, practice)
