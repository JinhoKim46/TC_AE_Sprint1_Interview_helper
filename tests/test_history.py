"""History and progress: sessions and reports are written straight into an in-memory DB (no models)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from interview_app.config import Settings
from interview_app.db import (
    Application,
    Evaluation,
    InterviewSession,
    LLMCall,
    Turn,
    User,
    session_scope,
)
from interview_app.evaluation.schemas import (
    ExchangeReport,
    Improvement,
    ItemScore,
    Report,
    RequirementEvidence,
)
from interview_app.history import counts_towards_scores, delete_session, list_sessions, load_report, progress
from interview_app.interview.persona import Channel, Difficulty, InterviewType, Length, SessionConfig

RUBRIC_PATH = Settings(_env_file=None).rubric_path
T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def add_user(engine, name: str) -> int:
    with session_scope(engine) as s:
        user = User(username=name, password_hash="h", totp_secret_enc="e")
        s.add(user)
        s.flush()
        return user.id


def add_application(engine, user_id: int, company: str = "Fjordlight Analytics") -> int:
    with session_scope(engine) as s:
        app = Application(user_id=user_id, company=company, role="ML Engineer")
        s.add(app)
        s.flush()
        return app.id


def make_report(
    overall: float | None,
    items: dict[str, int | None] | None = None,
    requirements: dict[str, str] | None = None,
    improvements: list[str] | None = None,
) -> Report:
    """A hand-written report: only the fields History reads are meaningful."""
    return Report(
        overall=overall,
        band="yes" if overall is not None and overall >= 60 else "lean_no",
        components={},
        penalties=[],
        exchanges=[
            ExchangeReport(
                exchange_id="E01",
                category="EXP",
                question="Walk me through a project.",
                score=overall,
                items=[
                    ItemScore(item=k, rationale="r", evidence=["T02"], score=v)
                    for k, v in (items or {}).items()
                ],
                answer_words=120,
                followups=0,
                flags=[],
            )
        ],
        session_items=[],
        requirements=[
            RequirementEvidence(requirement=req, priority="must", rationale="r", level=level)
            for req, level in (requirements or {}).items()
        ],
        strengths=[],
        improvements=[Improvement(area=a, advice="Do it.") for a in (improvements or [])],
        better_answer=None,
        summary="Fine.",
        talk_ratio=0.6,
        judge_model="judge/test",
        rubric_version="test",
    )


def add_session(
    engine,
    user_id: int,
    application_id: int,
    *,
    started: datetime = T0,
    status: str = "finished",
    report: Report | None = None,
    config: SessionConfig | None = None,
    cost: float = 0.0,
) -> int:
    with session_scope(engine) as s:
        row = InterviewSession(
            user_id=user_id,
            application_id=application_id,
            company="Fjordlight Analytics",
            role="ML Engineer",
            config_json=(config or SessionConfig()).model_dump_json(),
            documents_json="{}",
            status=status,
            started_at=started,
            ended_at=started + timedelta(minutes=20),
        )
        s.add(row)
        s.flush()
        turns = [
            ("interviewer", "Walk me through your background.", "opening", "OPEN-01", False),
            ("candidate", "I build vision models.", None, None, False),
            ("interviewer", "Tell me about the segmentation project.", "experience", "EXP-DEEP-01", False),
            ("candidate", "We built it.", None, None, False),
            ("interviewer", "What was your part?", "experience", "EXP-OWN-01", True),
            ("candidate", "I designed the data pipeline.", None, None, False),
        ]
        for idx, (speaker, text, stage, qid, followup) in enumerate(turns):
            s.add(
                Turn(
                    session_id=row.id,
                    user_id=user_id,
                    idx=idx,
                    speaker=speaker,
                    text=text,
                    stage=stage,
                    question_id=qid,
                    is_followup=followup,
                )
            )
        if report is not None:
            s.add(
                Evaluation(
                    session_id=row.id,
                    user_id=user_id,
                    judge_model=report.judge_model,
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
def app_id(engine, user_id) -> int:
    return add_application(engine, user_id)


# --- list_sessions ---------------------------------------------------------------------------------


def test_sessions_are_listed_newest_first_with_their_numbers(engine, user_id, app_id):
    old = add_session(engine, user_id, app_id, started=T0, report=make_report(55.0), cost=0.01)
    config = SessionConfig(
        interview_type=InterviewType.BEHAVIORAL,
        difficulty=Difficulty.TOUGH,
        length=Length.QUICK,
        channel=Channel.VOICE,
    )
    new = add_session(engine, user_id, app_id, started=T0 + timedelta(days=2), config=config)

    sessions = list_sessions(engine, user_id)
    assert [s.session_id for s in sessions] == [new, old]
    latest, first = sessions
    assert latest.interview_type == "behavioral" and latest.difficulty == "tough"
    assert not latest.has_report and latest.overall is None
    assert first.has_report and first.overall == 55.0 and first.band == "lean_no"
    assert first.cost_usd == pytest.approx(0.01)
    assert first.main_questions_asked == 2  # the follow-up does not count as a main question
    assert (latest.length, latest.channel) == (Length.QUICK, Channel.VOICE)
    assert (first.length, first.channel) == (Length.FULL, Channel.TEXT)  # stored before the choice existed


def test_preparing_and_failed_sessions_are_hidden(engine, user_id, app_id):
    kept = {add_session(engine, user_id, app_id, status=s) for s in ("active", "finished", "ended_early")}
    for status in ("preparing", "failed"):
        add_session(engine, user_id, app_id, status=status)
    assert {s.session_id for s in list_sessions(engine, user_id)} == kept


def test_sessions_of_other_users_are_invisible(engine, user_id, app_id):
    other = add_user(engine, "sam")
    other_app = add_application(engine, other, "Brightwater Labs")
    add_session(engine, other, other_app, report=make_report(80.0))
    mine = add_session(engine, user_id, app_id)

    assert [s.session_id for s in list_sessions(engine, user_id)] == [mine]
    assert progress(engine, user_id, other_app, RUBRIC_PATH).trend == []
    assert load_report(engine, user_id, mine) is None


def test_application_filter(engine, user_id, app_id):
    second_app = add_application(engine, user_id, "Brightwater Labs")
    add_session(engine, user_id, app_id)
    wanted = add_session(engine, user_id, second_app)
    assert [s.session_id for s in list_sessions(engine, user_id, second_app)] == [wanted]
    assert len(list_sessions(engine, user_id)) == 2


# --- progress ----------------------------------------------------------------------------------------


def test_trend_is_oldest_first_and_skips_sessions_without_a_score(engine, user_id, app_id):
    add_session(engine, user_id, app_id, started=T0 + timedelta(days=3), report=make_report(70.0))
    add_session(engine, user_id, app_id, started=T0, report=make_report(50.0))
    add_session(engine, user_id, app_id, started=T0 + timedelta(days=1), report=make_report(None))
    add_session(engine, user_id, app_id, started=T0 + timedelta(days=2))  # no report

    trend = progress(engine, user_id, app_id, RUBRIC_PATH).trend
    assert [point.score for point in trend] == [50.0, 70.0]
    assert trend[0].started_at < trend[1].started_at


def test_trend_marks_quick_and_custom_points_as_not_counted(engine, user_id, app_id):
    for day, length in enumerate([Length.FULL, Length.QUICK, Length.STANDARD, Length.CUSTOM]):
        add_session(
            engine,
            user_id,
            app_id,
            started=T0 + timedelta(days=day),
            report=make_report(60.0 + day),
            config=SessionConfig(length=length),
        )
    trend = progress(engine, user_id, app_id, RUBRIC_PATH).trend
    assert [(p.length, p.counted) for p in trend] == [
        (Length.FULL, True),
        (Length.QUICK, False),
        (Length.STANDARD, True),
        (Length.CUSTOM, False),
    ]


@pytest.mark.parametrize(
    ("length", "counted"),
    [(Length.QUICK, False), (Length.STANDARD, True), (Length.FULL, True), (Length.CUSTOM, False)],
)
def test_counts_towards_scores(length, counted):
    assert counts_towards_scores(length) is counted


def test_item_means_are_sorted_weakest_first_with_counts(engine, user_id, app_id):
    add_session(engine, user_id, app_id, report=make_report(60.0, items={"A1": 4, "A3": 2, "A4": None}))
    add_session(
        engine,
        user_id,
        app_id,
        started=T0 + timedelta(days=1),
        report=make_report(65.0, items={"A1": 5, "A3": 3, "A9": 3}),
    )

    means = progress(engine, user_id, app_id, RUBRIC_PATH).item_means
    assert [(m.item, m.mean, m.count) for m in means] == [("A3", 2.5, 2), ("A9", 3.0, 1), ("A1", 4.5, 2)]
    assert means[0].name == "Specificity and evidence"  # plain-words name from rubric.json


def test_requirements_keep_the_latest_level_and_a_history(engine, user_id, app_id):
    add_session(engine, user_id, app_id, report=make_report(50.0, requirements={"PyTorch": "claimed"}))
    add_session(
        engine,
        user_id,
        app_id,
        started=T0 + timedelta(days=1),
        report=make_report(
            60.0, requirements={"pytorch": "convincingly_demonstrated", "Docker": "not_addressed"}
        ),
    )
    add_session(
        engine,
        user_id,
        app_id,
        started=T0 + timedelta(days=2),
        report=make_report(65.0, requirements={"PyTorch": "convincingly_demonstrated"}),
    )

    reqs = {r.requirement.lower(): r for r in progress(engine, user_id, app_id, RUBRIC_PATH).requirements}
    assert set(reqs) == {"pytorch", "docker"}
    assert reqs["pytorch"].latest_level == "convincingly_demonstrated"
    assert reqs["pytorch"].level_counts == {"claimed": 1, "convincingly_demonstrated": 2}
    assert reqs["docker"].latest_level == "not_addressed"


def test_recurring_improvements_need_two_reports(engine, user_id, app_id):
    add_session(engine, user_id, app_id, report=make_report(50.0, improvements=["Quantify results", "Pace"]))
    add_session(
        engine,
        user_id,
        app_id,
        started=T0 + timedelta(days=1),
        # The same area twice in one report still counts once.
        report=make_report(55.0, improvements=["quantify results ", "Quantify results", "Ownership"]),
    )

    recurring = progress(engine, user_id, app_id, RUBRIC_PATH).recurring_improvements
    assert [(r.area.lower(), r.count) for r in recurring] == [("quantify results", 2)]


# --- delete ------------------------------------------------------------------------------------------


def test_delete_removes_turns_and_evaluation_but_keeps_cost_history(engine, user_id, app_id):
    sid = add_session(engine, user_id, app_id, report=make_report(60.0), cost=0.02)
    other = add_user(engine, "sam")
    assert delete_session(engine, other, sid) is False  # not theirs

    assert delete_session(engine, user_id, sid) is True
    with session_scope(engine) as s:
        assert s.exec(select(InterviewSession)).all() == []
        assert s.exec(select(Turn)).all() == []
        assert s.exec(select(Evaluation)).all() == []
        assert len(s.exec(select(LLMCall)).all()) == 1
    assert delete_session(engine, user_id, sid) is False


def test_delete_works_on_an_interview_still_in_progress(engine, user_id, app_id):
    # "Discard" in the Exit interview dialog deletes the running interview itself.
    sid = add_session(engine, user_id, app_id, status="active")
    assert delete_session(engine, user_id, sid) is True
    with session_scope(engine) as s:
        assert s.exec(select(InterviewSession)).all() == []
        assert s.exec(select(Turn)).all() == []
