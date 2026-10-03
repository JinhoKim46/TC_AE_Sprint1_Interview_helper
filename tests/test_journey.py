"""The user's next step and score summary (pure functions over SessionSummary rows, no DB)."""

from datetime import UTC, datetime, timedelta

from interview_app.history import SessionSummary
from interview_app.interview.persona import Length
from interview_app.journey import Step, next_step, score_summary

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def summary(
    n: int, status: str = "finished", overall: float | None = None, length: Length = Length.FULL
) -> SessionSummary:
    """Session n starts n days after T0 (a higher n is newer)."""
    return SessionSummary(
        session_id=n,
        application_id=1,
        company="Northwind Robotics",
        role="Perception Engineer",
        started_at=T0 + timedelta(days=n),
        ended_at=None,
        status=status,
        interview_type="hiring_manager",
        difficulty="standard",
        mode="realistic",
        prompt_variant="p4_role_rich",
        length=length,
        main_questions_asked=3,
        cost_usd=0.01,
        overall=overall,
        band=None,
        has_report=overall is not None,
    )


def test_first_run_starts_with_an_application():
    assert next_step(0, []) == Step.ADD_APPLICATION


def test_with_an_application_but_no_interview_start_one():
    assert next_step(1, []) == Step.START_INTERVIEW


def test_a_running_interview_comes_first():
    assert next_step(1, [summary(2, status="active"), summary(1, overall=60)]) == Step.RESUME_INTERVIEW


def test_newest_interview_without_report_asks_for_feedback():
    assert next_step(1, [summary(2, status="ended_early"), summary(1, overall=60)]) == Step.GET_FEEDBACK


def test_an_older_unreported_interview_does_not_nag():
    # Only the newest interview counts: an old one without a report was probably skipped on purpose.
    assert next_step(1, [summary(2, overall=70), summary(1)]) == Step.PRACTISE


def test_order_of_the_list_does_not_matter():
    assert next_step(1, [summary(1, overall=60), summary(2)]) == Step.GET_FEEDBACK


def test_score_summary_latest_best_and_change():
    s = score_summary([summary(3, overall=71), summary(2), summary(1, overall=52), summary(0, overall=80)])
    assert s.scored == 3
    assert s.latest == 71
    assert s.best == 80
    assert s.change == 71 - 52  # against the previous *scored* interview, unscored ones are skipped


def test_score_summary_with_one_or_no_scores():
    one = score_summary([summary(1, overall=60), summary(2)])
    assert (one.scored, one.latest, one.best, one.change) == (1, 60, 60, None)
    none = score_summary([summary(1)])
    assert (none.scored, none.latest, none.best, none.change) == (0, None, None, None)


def test_latest_and_best_count_only_standard_and_full():
    s = score_summary(
        [
            summary(4, overall=95, length=Length.QUICK),  # newest, but a short practice
            summary(3, overall=90, length=Length.CUSTOM),  # e.g. a weak-spot drill
            summary(2, overall=70, length=Length.STANDARD),
            summary(1, overall=60, length=Length.FULL),
        ]
    )
    assert (s.latest, s.best, s.change) == (70, 70, 10)
    assert s.scored == 4 and s.practice == 2  # practice sessions are still counted as scored


def test_only_practice_scores_give_no_latest_or_best():
    s = score_summary([summary(1, overall=80, length=Length.QUICK)])
    assert (s.scored, s.practice, s.latest, s.best, s.change) == (1, 1, None, None, None)
