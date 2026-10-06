"""Cost overview: spend per application, over time and by purpose, aggregated by the database."""

from datetime import UTC, date, datetime, timedelta

import pytest
from test_dashboard import add_session
from test_history import add_application, add_user

from interview_app.config import Settings
from interview_app.cost import OTHER, SIMULATION, chart_group, cost_overview, purpose
from interview_app.dashboard import dashboard
from interview_app.db import LLMCall, session_scope
from interview_app.usage import usage_summary

RUBRIC_PATH = Settings(_env_file=None).rubric_path
DAY1 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
DAY2 = DAY1 + timedelta(days=1)


def add_call(engine, user_id, role, cost, at, session_id=None):
    with session_scope(engine) as s:
        s.add(
            LLMCall(
                user_id=user_id, session_id=session_id, role=role, model="m", cost_usd=cost, created_at=at
            )
        )


@pytest.fixture
def user_id(engine) -> int:
    return add_user(engine, "alex")


@pytest.fixture
def seeded(engine, user_id):
    """Fjordlight: two interviews ($0.03 + $0.01). Brightwater: one ($0.005), with one unused interview.
    Plus a session-less guard call (an uploaded document) and a lab call, and another user's spend."""
    fjord = add_application(engine, user_id, "Fjordlight Analytics")
    bright = add_application(engine, user_id, "Brightwater Labs")
    f1 = add_session(engine, user_id, fjord, "Fjordlight Analytics", started=DAY1)
    f2 = add_session(engine, user_id, fjord, "Fjordlight Analytics", started=DAY2)
    b1 = add_session(engine, user_id, bright, "Brightwater Labs", started=DAY2)
    add_session(engine, user_id, bright, "Brightwater Labs", started=DAY2)  # no model spend at all
    add_call(engine, user_id, "interviewer", 0.01, DAY1, f1)
    add_call(engine, user_id, "planner", 0.005, DAY1, f1)
    add_call(engine, user_id, "judge", 0.015, DAY1, f1)
    add_call(engine, user_id, "tts", 0.004, DAY2, f2)
    add_call(engine, user_id, "stt", 0.006, DAY2, f2)
    add_call(engine, user_id, "live_score", 0.005, DAY2, b1)
    add_call(engine, user_id, "guard", 0.002, DAY1)  # an uploaded document: no interview
    add_call(engine, user_id, "lab_judge", 0.003, DAY2)
    other = add_user(engine, "sam")
    other_app = add_application(engine, other, "Copperleaf Studio")
    other_session = add_session(engine, other, other_app, "Copperleaf Studio")
    add_call(engine, other, "interviewer", 5.0, DAY1, other_session)
    return fjord, bright


def test_purposes_have_plain_names_and_unknown_roles_are_other():
    assert purpose("interviewer") == "Interviewer"
    assert purpose("planner") == "Planning"
    assert purpose("judge") == "Report"
    assert purpose("live_score") == "Live scoring"
    assert purpose("tts") == "Voice"
    assert purpose("stt") == "Transcription"
    assert purpose("guard") == "Guard"
    # Lab and audit runs (the simulated candidate, the lab judge, voicing simulated answers) are named as
    # such, so "Other" never hides them; only a role nobody mapped is Other.
    assert purpose("lab_judge") == purpose("candidate_sim") == purpose("audit_tts") == SIMULATION
    assert SIMULATION == "Simulation (lab)"
    assert purpose("something_new") == OTHER == "Other"
    # The chart stacks at most four groups, so each purpose has a fixed group (and colour).
    assert chart_group("Planning") == chart_group("Interviewer")
    assert chart_group("Transcription") == chart_group("Voice")
    assert chart_group("Guard") == chart_group(OTHER)


def test_empty(engine, user_id):
    cost = cost_overview(engine, user_id)
    assert cost.total_usd == 0 and cost.unassigned_usd == 0
    assert cost.average_per_interview_usd is None
    assert cost.by_application == {} and cost.over_time == [] and cost.by_purpose == []


def test_cost_per_application_and_average_per_interview(engine, user_id, seeded):
    fjord, bright = seeded
    cost = cost_overview(engine, user_id)
    f, b = cost.by_application[fjord], cost.by_application[bright]
    assert f.cost_usd == pytest.approx(0.04) and f.interviews == 2
    assert f.average_usd == pytest.approx(0.02)
    # The unused Brightwater interview made no call, so it doesn't pull the average down.
    assert b.cost_usd == pytest.approx(0.005) and b.interviews == 1
    assert b.average_usd == pytest.approx(0.005)
    assert cost.interviews == 3
    assert cost.average_per_interview_usd == pytest.approx(0.045 / 3)


def test_session_less_calls_count_in_totals_but_in_no_company(engine, user_id, seeded):
    cost = cost_overview(engine, user_id)
    assert cost.unassigned_usd == pytest.approx(0.005)  # the document guard and the lab call
    assert sum(a.cost_usd for a in cost.by_application.values()) == pytest.approx(0.045)
    assert cost.total_usd == pytest.approx(0.05)


def test_total_agrees_with_settings_usage_table(engine, user_id, seeded):
    cost = cost_overview(engine, user_id)
    assert cost.total_usd == pytest.approx(usage_summary(engine, user_id).total_cost_usd)
    assert sum(p.cost_usd for p in cost.by_purpose) == pytest.approx(cost.total_usd)
    assert sum(b.cost_usd for b in cost.over_time) == pytest.approx(cost.total_usd)


def test_dashboard_kpi_cost_is_the_same_total(engine, user_id, seeded):
    board = dashboard(engine, user_id, RUBRIC_PATH)
    assert board.kpis.cost_usd == pytest.approx(usage_summary(engine, user_id).total_cost_usd)
    assert board.cost.unassigned_usd == pytest.approx(0.005)
    fjord, bright = seeded
    rows = {r.application_id: r for r in board.rows}
    assert rows[fjord].cost_usd == pytest.approx(0.04) and rows[fjord].cost_per_interview == pytest.approx(
        0.02
    )
    assert rows[bright].cost_usd == pytest.approx(0.005)


def test_by_purpose_most_expensive_first(engine, user_id, seeded):
    by_purpose = cost_overview(engine, user_id).by_purpose
    got = {p.purpose: (p.calls, p.cost_usd) for p in by_purpose}
    assert got == {
        "Interviewer": (1, pytest.approx(0.01)),
        "Planning": (1, pytest.approx(0.005)),
        "Report": (1, pytest.approx(0.015)),
        "Voice": (1, pytest.approx(0.004)),
        "Transcription": (1, pytest.approx(0.006)),
        "Live scoring": (1, pytest.approx(0.005)),
        "Guard": (1, pytest.approx(0.002)),
        "Simulation (lab)": (1, pytest.approx(0.003)),
    }
    assert by_purpose[0].purpose == "Report"
    costs = [p.cost_usd for p in by_purpose]
    assert costs == sorted(costs, reverse=True)


def test_daily_buckets_by_purpose(engine, user_id, seeded):
    cost = cost_overview(engine, user_id)
    assert cost.bucket == "day"
    got = {(b.start, b.purpose): b.cost_usd for b in cost.over_time}
    assert got == {
        (date(2026, 9, 1), "Interviewer"): pytest.approx(0.01),
        (date(2026, 9, 1), "Planning"): pytest.approx(0.005),
        (date(2026, 9, 1), "Report"): pytest.approx(0.015),
        (date(2026, 9, 1), "Guard"): pytest.approx(0.002),
        (date(2026, 9, 2), "Voice"): pytest.approx(0.004),
        (date(2026, 9, 2), "Transcription"): pytest.approx(0.006),
        (date(2026, 9, 2), "Live scoring"): pytest.approx(0.005),
        (date(2026, 9, 2), "Simulation (lab)"): pytest.approx(0.003),
    }
    assert [b.start for b in cost.over_time] == sorted(b.start for b in cost.over_time)


def test_two_unknown_roles_on_one_day_merge_into_one_other_bucket(engine, user_id):
    # "candidate" is not "candidate_sim", and "summariser" has no lab_/audit_ prefix: both unmapped.
    add_call(engine, user_id, "summariser", 0.001, DAY1)
    add_call(engine, user_id, "candidate", 0.002, DAY1)
    cost = cost_overview(engine, user_id)
    assert [(b.purpose, b.cost_usd) for b in cost.over_time] == [("Other", pytest.approx(0.003))]
    assert [(p.purpose, p.calls) for p in cost.by_purpose] == [("Other", 2)]


def test_simulation_roles_group_in_sql_like_in_python(engine, user_id):
    # The LIKE in the database must treat "_" literally: "labx" is not a lab_ role.
    add_call(engine, user_id, "candidate_sim", 0.001, DAY1)
    add_call(engine, user_id, "audit_tts", 0.002, DAY1)
    add_call(engine, user_id, "labx", 0.004, DAY1)
    got = {p.purpose: p.calls for p in cost_overview(engine, user_id).by_purpose}
    assert got == {"Simulation (lab)": 2, "Other": 1}
    assert purpose("labx") == OTHER


def test_weekly_buckets_when_the_data_spans_more_than_60_days(engine, user_id):
    # 2026-09-01 is a Tuesday, so its week starts on Monday 2026-08-31.
    add_call(engine, user_id, "interviewer", 0.01, DAY1)
    add_call(engine, user_id, "interviewer", 0.02, DAY1 + timedelta(days=5))  # Sunday 09-06, same week
    add_call(engine, user_id, "judge", 0.04, DAY1 + timedelta(days=6))  # Monday 09-07, next week
    add_call(engine, user_id, "interviewer", 0.08, DAY1 + timedelta(days=61))  # Saturday 10-31
    cost = cost_overview(engine, user_id)
    assert cost.bucket == "week"
    got = {(b.start, b.purpose): b.cost_usd for b in cost.over_time}
    assert got == {
        (date(2026, 8, 31), "Interviewer"): pytest.approx(0.03),
        (date(2026, 9, 7), "Report"): pytest.approx(0.04),
        (date(2026, 10, 26), "Interviewer"): pytest.approx(0.08),
    }


def test_exactly_60_days_stays_daily(engine, user_id):
    add_call(engine, user_id, "interviewer", 0.01, DAY1)
    add_call(engine, user_id, "interviewer", 0.01, DAY1 + timedelta(days=60))
    assert cost_overview(engine, user_id).bucket == "day"
