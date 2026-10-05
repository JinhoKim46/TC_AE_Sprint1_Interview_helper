"""Dashboard: the cross-application overview, computed from rows written straight into an in-memory DB."""

from datetime import UTC, datetime, timedelta

import pytest
from test_history import add_application, add_user, make_report

from interview_app.config import Settings
from interview_app.dashboard import dashboard
from interview_app.db import Application, Evaluation, InterviewSession, LLMCall, Turn, session_scope
from interview_app.evaluation.rubric import load_rubric
from interview_app.evaluation.schemas import Report
from interview_app.interview.persona import Length, SessionConfig

RUBRIC_PATH = Settings(_env_file=None).rubric_path
T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
# Names are read from rubric.json, the single source of truth, rather than copied here.
SKILL_NAMES = {k: v["name"] for k, v in load_rubric(RUBRIC_PATH).exchange_items.items()}


def add_session(
    engine,
    user_id: int,
    application_id: int,
    company: str,
    *,
    started: datetime = T0,
    minutes: float = 10,
    status: str = "finished",
    report: Report | None = None,
    length: Length = Length.FULL,
    cost: float = 0.0,
) -> int:
    """One interview with two turns `minutes` apart (the time practised) and an optional report."""
    with session_scope(engine) as s:
        row = InterviewSession(
            user_id=user_id,
            application_id=application_id,
            company=company,
            role="ML Engineer",
            config_json=SessionConfig(length=length).model_dump_json(),
            documents_json="{}",
            status=status,
            started_at=started,
        )
        s.add(row)
        s.flush()
        for idx, (speaker, at) in enumerate(
            [("interviewer", started), ("candidate", started + timedelta(minutes=minutes))]
        ):
            s.add(Turn(session_id=row.id, user_id=user_id, idx=idx, speaker=speaker, text="t", created_at=at))
        if report is not None:
            s.add(
                Evaluation(
                    session_id=row.id,
                    user_id=user_id,
                    judge_model="judge/test",
                    overall=report.overall,
                    band=report.band,
                    report_json=report.model_dump_json(),
                )
            )
        if cost:
            s.add(LLMCall(user_id=user_id, session_id=row.id, role="interviewer", model="m", cost_usd=cost))
        return row.id


@pytest.fixture
def user_id(engine) -> int:
    return add_user(engine, "alex")


@pytest.fixture
def two_apps(engine, user_id) -> tuple[int, int]:
    """Fjordlight: 50 then 70 (plus a 95 Quick practice). Brightwater: one 60, then an unscored one."""
    fjord = add_application(engine, user_id, "Fjordlight Analytics")
    bright = add_application(engine, user_id, "Brightwater Labs")
    day = timedelta(days=1)
    add_session(
        engine, user_id, fjord, "Fjordlight Analytics", report=make_report(50.0, items={"A1": 2, "A3": 4})
    )
    add_session(
        engine,
        user_id,
        fjord,
        "Fjordlight Analytics",
        started=T0 + 2 * day,
        report=make_report(70.0, items={"A1": 3, "A3": 5}),
        cost=0.02,
    )
    add_session(
        engine,
        user_id,
        fjord,
        "Fjordlight Analytics",
        started=T0 + 3 * day,
        minutes=4,
        length=Length.QUICK,
        report=make_report(95.0, items={"A1": 5}),
    )
    add_session(
        engine,
        user_id,
        bright,
        "Brightwater Labs",
        started=T0 + day,
        minutes=20,
        report=make_report(60.0, items={"A3": 1}),
        cost=0.01,
    )
    add_session(engine, user_id, bright, "Brightwater Labs", started=T0 + 4 * day, status="ended_early")
    return fjord, bright


def test_empty_state(engine, user_id):
    board = dashboard(engine, user_id, RUBRIC_PATH)
    assert board.applications == 0 and board.kpis.interviews == 0
    assert board.trend == [] and board.rows == [] and board.item_means == []
    assert board.kpis.average_score is None and board.kpis.best_score is None

    add_application(engine, user_id, "Fjordlight Analytics")
    board = dashboard(engine, user_id, RUBRIC_PATH)
    assert board.applications == 1 and board.kpis.interviews == 0
    assert [(r.company, r.interviews, r.latest, r.last_practised) for r in board.rows] == [
        ("Fjordlight Analytics", 0, None, None)
    ]


def test_kpis_count_everything_but_score_only_counted_sessions(engine, user_id, two_apps):
    kpis = dashboard(engine, user_id, RUBRIC_PATH).kpis
    assert kpis.interviews == 5
    assert kpis.practised_seconds == (10 + 10 + 4 + 20 + 10) * 60  # Quick practice is still practice
    assert kpis.average_score == pytest.approx(60.0)  # 50, 70 and 60; the 95 Quick session is left out
    assert kpis.best_score == 70.0
    assert kpis.scored == 3
    assert kpis.cost_usd == pytest.approx(0.03)


def test_hidden_sessions_and_other_users_are_left_out(engine, user_id, two_apps):
    fjord, _ = two_apps
    add_session(engine, user_id, fjord, "Fjordlight Analytics", status="failed", report=make_report(99.0))
    other = add_user(engine, "sam")
    other_app = add_application(engine, other, "Copperleaf Studio")
    add_session(engine, other, other_app, "Copperleaf Studio", report=make_report(10.0), cost=1.0)

    board = dashboard(engine, user_id, RUBRIC_PATH)
    assert board.kpis.interviews == 5 and board.kpis.best_score == 70.0
    assert board.kpis.cost_usd == pytest.approx(0.03)
    assert {r.company for r in board.rows} == {"Fjordlight Analytics", "Brightwater Labs"}


def test_trend_has_one_series_per_application_without_practice_points(engine, user_id, two_apps):
    fjord, bright = two_apps
    trend = dashboard(engine, user_id, RUBRIC_PATH).trend
    assert [(p.application_id, p.score) for p in trend] == [(fjord, 50.0), (bright, 60.0), (fjord, 70.0)]
    assert {p.label for p in trend} == {"Fjordlight Analytics", "Brightwater Labs"}


def test_same_company_twice_is_told_apart_by_role(engine, user_id):
    first = add_application(engine, user_id, "Fjordlight Analytics")
    with session_scope(engine) as s:
        app = Application(user_id=user_id, company="Fjordlight Analytics", role="Data Scientist")
        s.add(app)
        s.flush()
        second = app.id
    add_session(engine, user_id, first, "Fjordlight Analytics", report=make_report(50.0))
    add_session(engine, user_id, second, "Fjordlight Analytics", report=make_report(60.0))
    labels = {p.label for p in dashboard(engine, user_id, RUBRIC_PATH).trend}
    assert labels == {"Fjordlight Analytics — ML Engineer", "Fjordlight Analytics — Data Scientist"}


def test_one_row_per_application_with_latest_best_trend_and_weakest_skill(engine, user_id, two_apps):
    fjord, bright = two_apps
    rows = {r.application_id: r for r in dashboard(engine, user_id, RUBRIC_PATH).rows}

    f = rows[fjord]
    assert (f.interviews, f.latest, f.best, f.change) == (3, 70.0, 70.0, 20.0)  # the Quick 95 is ignored
    assert f.last_practised == T0 + timedelta(days=3)  # practice still counts as practising
    # A1 over all three reports: (2 + 3 + 5) / 3 = 3.33; A3: (4 + 5) / 2 = 4.5. Same rule as History.
    assert f.weakest_skill == SKILL_NAMES["A1"]

    b = rows[bright]
    assert (b.interviews, b.latest, b.best, b.change) == (2, 60.0, 60.0, None)
    assert b.last_practised == T0 + timedelta(days=4)
    assert b.weakest_skill == SKILL_NAMES["A3"]  # its only scored item


def test_rows_most_recently_practised_first(engine, user_id, two_apps):
    fjord, bright = two_apps
    idle = add_application(engine, user_id, "Copperleaf Studio")
    assert [r.application_id for r in dashboard(engine, user_id, RUBRIC_PATH).rows] == [bright, fjord, idle]


def test_skill_means_across_all_applications_weakest_first(engine, user_id, two_apps):
    means = dashboard(engine, user_id, RUBRIC_PATH).item_means
    # A1: 2, 3, 5 -> 3.33 (3 answers). A3: 4, 5, 1 -> 3.33 (3 answers); ties keep rubric order.
    assert [(m.item, m.count) for m in means] == [("A1", 3), ("A3", 3)]
    assert means[0].mean == pytest.approx(10 / 3)
    assert means[1].name == SKILL_NAMES["A3"]  # plain-words name from rubric.json
