"""Evaluation tests: exchanges, metrics, hand-computed aggregation, judge prompt, and the service."""

import json
from types import SimpleNamespace

import pytest

from interview_app.config import Settings
from interview_app.evaluation.aggregate import aggregate, weighted_overall
from interview_app.evaluation.exchanges import build_exchanges, category_of
from interview_app.evaluation.judge import judge_messages
from interview_app.evaluation.metrics import compute_metrics
from interview_app.evaluation.rubric import load_rubric
from interview_app.evaluation.schemas import (
    ExchangeJudgement,
    ItemScore,
    Judgement,
    RequirementEvidence,
    Strength,
)
from interview_app.evaluation.service import EvaluationError, evaluate_session, stored_report
from interview_app.ingest import DocKind
from interview_app.interview.engine import TurnView

SETTINGS = Settings(_env_file=None)
RUBRIC = load_rubric(SETTINGS.rubric_path)


def tv(idx, speaker, text, stage=None, qid=None, followup=False):
    return TurnView(idx, speaker, text, stage, qid, followup, False)


TRANSCRIPT = [
    tv(0, "interviewer", "Walk me through your background.", "opening", "OPEN-01"),
    tv(1, "candidate", "I am an ML engineer. " * 10),
    tv(2, "interviewer", "Walk me through the segmentation project.", "experience", "EXP-DEEP-01"),
    tv(3, "candidate", "We built it."),
    tv(4, "interviewer", "What was your part?", "experience", "EXP-OWN-01", followup=True),
    tv(5, "candidate", "I designed the data pipeline and measured mIoU on a frozen split."),
    tv(6, "interviewer", "What questions do you have?", "candidate_questions", "CQ-01"),
    tv(7, "candidate", "What does the first month look like?"),
]


TURN_TEXTS = {f"T{t.idx + 1:02d}": t.text for t in TRANSCRIPT}


def item(item_id, score, evidence=("T02",)):
    return ItemScore(item=item_id, rationale="r", evidence=list(evidence), score=score)


# --- exchanges and metrics ----------------------------------------------------------------------


def test_follow_ups_belong_to_their_main_question():
    exchanges = build_exchanges(TRANSCRIPT)
    assert [e.exchange_id for e in exchanges] == ["E01", "E02", "E03"]
    assert [e.category for e in exchanges] == ["OPEN", "EXP", "CQ"]
    assert exchanges[1].followups == 1 and len(exchanges[1].candidate_turns) == 2


def test_category_falls_back_to_stage_for_custom_questions():
    assert category_of("CUSTOM", "behavioral") == "BEH"
    assert category_of("TECH-GAP-01", "gap") == "TECH"
    assert category_of(None, "gap") == "EXP"


def test_metrics_flag_short_answers_and_count_candidate_questions():
    metrics = compute_metrics(build_exchanges(TRANSCRIPT), RUBRIC)
    by_id = {m.exchange_id: m for m in metrics.exchanges}
    assert by_id["E01"].answer_words == 50 and by_id["E01"].short_answer  # OPEN minimum is 80 words
    assert metrics.candidate_question_count == 1
    assert 0 < metrics.talk_ratio < 1


# --- aggregation (hand-computed) ----------------------------------------------------------------


def test_exchange_score_is_the_weighted_mean_of_applicable_items():
    exchanges = build_exchanges(TRANSCRIPT)
    judgement = Judgement(
        exchanges=[
            # EXP weights from rubric.json: A3 = 2.0, A4 = 2.0. norm(5) = 100, norm(3) = 50.
            ExchangeJudgement(exchange_id="E02", items=[item("A3", 5, ["T06"]), item("A4", 3, ["T06"])]),
        ],
        session_items=[],
        requirements=[],
        strengths=[],
        improvements=[],
        summary="",
    )
    result = aggregate(judgement, exchanges, compute_metrics(exchanges, RUBRIC), RUBRIC, "hiring_manager")
    e02 = next(r for r in result["exchanges"] if r.exchange_id == "E02")
    assert e02.score == pytest.approx((2.0 * 100 + 2.0 * 50) / 4.0)  # 75.0
    assert result["components"]["experience_technical"] == pytest.approx(75.0)


def test_items_without_evidence_or_not_applicable_are_ignored():
    exchanges = build_exchanges(TRANSCRIPT)
    judgement = Judgement(
        exchanges=[
            ExchangeJudgement(
                exchange_id="E02",
                items=[
                    item("A3", 5, ["T99"]),  # cited a turn that doesn't exist
                    item("A3", 4, []),  # no evidence at all
                    item("A2", 2, ["T04"]),  # applicable to EXP (weight 1.5)
                ],
            ),
            # A5 (technical correctness) has no weight for OPEN, so it must not count.
            ExchangeJudgement(exchange_id="E01", items=[item("A5", 1, ["T02"])]),
        ],
        session_items=[],
        requirements=[],
        strengths=[],
        improvements=[],
        summary="",
    )
    result = aggregate(judgement, exchanges, compute_metrics(exchanges, RUBRIC), RUBRIC, "hiring_manager")
    by_id = {r.exchange_id: r for r in result["exchanges"]}
    assert [i.item for i in by_id["E02"].items] == ["A2"]
    assert by_id["E02"].score == pytest.approx(25.0)
    assert by_id["E01"].items == [] and by_id["E01"].score is None


def test_missing_components_redistribute_their_weight():
    # Only two components present: their weights (0.3 and 0.1) are rescaled to sum to 1.
    overall = weighted_overall(
        {"requirement_coverage": 80.0, "S1": 40.0, "behavioral": None},
        RUBRIC.aggregation_weights("hiring_manager"),
    )
    assert overall == pytest.approx((0.3 * 80 + 0.1 * 40) / 0.4)


def test_requirement_coverage_weights_must_double_and_skips_not_addressed():
    exchanges = build_exchanges(TRANSCRIPT)
    reqs = [
        RequirementEvidence(
            requirement="a",
            priority="must",
            rationale="",
            evidence=["T06"],
            quote="I designed the data pipeline",
            level="convincingly_demonstrated",
        ),
        RequirementEvidence(
            requirement="b",
            priority="nice",
            rationale="",
            evidence=["T04"],
            quote="We built it.",
            level="claimed",
        ),
        RequirementEvidence(requirement="c", priority="must", rationale="", level="not_addressed"),
    ]
    judgement = Judgement(
        exchanges=[], session_items=[], requirements=reqs, strengths=[], improvements=[], summary=""
    )
    result = aggregate(judgement, exchanges, compute_metrics(exchanges, RUBRIC), RUBRIC, "hiring_manager")
    assert result["components"]["requirement_coverage"] == pytest.approx((2 * 100 + 1 * 35) / 3, abs=0.1)


def test_cv_only_credit_is_removed():
    """A requirement rating or a strength without a cited interview turn doesn't count."""
    exchanges = build_exchanges(TRANSCRIPT)
    judgement = Judgement(
        exchanges=[],
        session_items=[],
        requirements=[
            RequirementEvidence(requirement="C++", priority="must", rationale="CV says so", level="claimed")
        ],
        strengths=[
            Strength(point="From the CV", evidence=[]),
            Strength(point="Said it", evidence=["T06"], quote="measured mIoU on a frozen split"),
        ],
        improvements=[],
        summary="",
    )
    result = aggregate(judgement, exchanges, compute_metrics(exchanges, RUBRIC), RUBRIC, "hiring_manager")
    assert result["requirements"][0].level == "not_addressed"
    assert result["components"]["requirement_coverage"] is None  # nothing left to rate
    assert [s.point for s in result["strengths"]] == ["Said it"]


def test_a_quote_that_is_not_in_the_cited_turn_is_rejected():
    from interview_app.evaluation.aggregate import quote_found

    texts = {"T02": "I built shelf detection at Shelfwise."}
    assert quote_found("built shelf detection at Shelfwise", ["T02"], texts)
    assert quote_found("I built shelf-detection, at Shelfwise", ["T02"], texts)  # punctuation slips are fine
    assert not quote_found(
        "I found test-set leakage and fixed it", ["T02"], texts
    )  # true in the CV, never said
    assert not quote_found("", ["T02"], texts)


def test_no_company_motivation_costs_five_points_and_bands_come_from_rubric():
    exchanges = build_exchanges(TRANSCRIPT)
    judgement = Judgement(
        exchanges=[],
        session_items=[item("S1", 1, ["T02"])],
        requirements=[
            RequirementEvidence(
                requirement="a",
                priority="must",
                rationale="",
                evidence=["T02"],
                quote="I am an ML engineer",
                level="convincingly_demonstrated",
            )
        ],
        strengths=[],
        improvements=[],
        summary="",
    )
    result = aggregate(judgement, exchanges, compute_metrics(exchanges, RUBRIC), RUBRIC, "hiring_manager")
    # coverage 100 (w 0.3) and S1 norm(1) = 0 (w 0.1): 30 / 0.4 = 75, minus 5 = 70 -> "yes" (65-79)
    assert result["overall"] == pytest.approx(70.0)
    assert result["band"] == "yes" and result["penalties"]


def test_bands():
    assert RUBRIC.band(85) == "strong_yes" and RUBRIC.band(64.9) == "lean_no" and RUBRIC.band(10) == "no"


# --- judge prompt -------------------------------------------------------------------------------


def test_judge_prompt_contains_rubric_applicability_and_wrapped_answers():
    exchanges = build_exchanges(TRANSCRIPT)
    docs = {DocKind.JD: "Job text", DocKind.CV: "CV text"}
    prompt = judge_messages(RUBRIC, "Acme", "Engineer", docs, exchanges, plan=None)[0]["content"]
    assert "### A3 — Specificity and evidence" in prompt
    assert RUBRIC.exchange_items["A3"]["criteria"][4] in prompt  # level texts come from rubric.json
    assert "state.cv" not in prompt  # the decision-model prefix is stripped
    assert "E02 (category EXP; applicable items: A1, A2, A3, A4, A5, A6, A7, A8, A9, A10)" in prompt
    assert "E03 (category CQ; applicable items: none - feedback only)" in prompt
    assert "<candidate_answer>\nWe built it.\n</candidate_answer>" in prompt
    assert "T06 candidate: <candidate_answer>" in prompt
    assert "list the 5-8 most important requirements" in prompt  # no plan given


# --- service ------------------------------------------------------------------------------------

JUDGEMENT = Judgement(
    exchanges=[ExchangeJudgement(exchange_id="E01", items=[item("A1", 4, ["T02"]), item("A9", 4, ["T02"])])],
    session_items=[item("S1", 3, ["T02"])],
    requirements=[RequirementEvidence(requirement="Python", priority="must", rationale="", level="claimed")],
    strengths=[Strength(point="Clear opening.", evidence=["T02"], quote="ML engineer")],
    improvements=[],
    summary="Solid start.",
)


@pytest.fixture
def finished_session(engine, request):
    """A real session (via the engine) with one answer, then ended. Judge runs = request.param (default 1),
    so tests that script exactly one judge reply stay deterministic."""
    settings = Settings(_env_file=None, judge_runs=getattr(request, "param", 1))
    from interview_app.demo import load_sample_application
    from interview_app.interview import engine as eng
    from interview_app.interview.persona import PromptVariant, SessionConfig
    from interview_app.llm.calllog import make_db_recorder
    from interview_app.llm.client import LLMClient
    from interview_app.users import ensure_local_user

    replies = [
        json.dumps(
            {
                "stage": "opening",
                "question_id": "OPEN-01",
                "is_followup": False,
                "message": "Tell me about yourself.",
                "is_final": False,
            }
        ),
        json.dumps(
            {
                "stage": "experience",
                "question_id": "EXP-DEEP-01",
                "is_followup": False,
                "message": "Next?",
                "is_final": False,
            }
        ),
    ]
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10, cost=0.002),
        )

    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    uid = ensure_local_user(engine)
    app_id = load_sample_application(engine, uid)
    deps = eng.EngineDeps(
        engine, settings, lambda u, sid: LLMClient(settings, make_db_recorder(engine, u, sid), sdk=sdk)
    )
    sid = eng.start_interview(deps, uid, app_id, SessionConfig(prompt_variant=PromptVariant.P1_ZERO_SHOT))
    eng.answer(deps, uid, sid, "I am an ML engineer with four years of computer vision experience.")
    eng.end_interview(deps, uid, sid)
    return SimpleNamespace(deps=deps, uid=uid, sid=sid, replies=replies, requests=requests, eng=eng)


def test_evaluate_stores_and_reuses_the_report(finished_session):
    f = finished_session
    f.replies.append(JUDGEMENT.model_dump_json())
    report = evaluate_session(f.deps, f.uid, f.sid)
    assert report.band is not None and report.summary == "Solid start."
    assert f.requests[-1]["model"] == SETTINGS.models.judge and f.requests[-1]["temperature"] == 0

    calls = len(f.requests)
    again = evaluate_session(f.deps, f.uid, f.sid)  # stored: no second judge call
    assert again == report and len(f.requests) == calls
    assert stored_report(f.deps, f.uid + 1, f.sid) is None  # other users can't read it


def test_force_re_evaluates(finished_session):
    f = finished_session
    f.replies += [
        JUDGEMENT.model_dump_json(),
        JUDGEMENT.model_copy(update={"summary": "Second"}).model_dump_json(),
    ]
    evaluate_session(f.deps, f.uid, f.sid)
    assert evaluate_session(f.deps, f.uid, f.sid, force=True).summary == "Second"


def test_active_interview_cannot_be_evaluated(engine, finished_session):
    f = finished_session
    from interview_app.db import InterviewSession, session_scope

    with session_scope(engine) as s:
        row = s.get(InterviewSession, f.sid)
        row.status = "active"
        s.add(row)
    with pytest.raises(EvaluationError):
        evaluate_session(f.deps, f.uid, f.sid)


def test_judge_failure_is_a_friendly_error(finished_session):
    f = finished_session
    f.replies += ["not json", "still not json"]
    with pytest.raises(EvaluationError):
        evaluate_session(f.deps, f.uid, f.sid)
    assert stored_report(f.deps, f.uid, f.sid) is None


# --- median of several judge runs ---------------------------------------------------------------


def judged(a9: int, summary: str) -> str:
    """A judgement whose overall score comes from one communication score (A9): with every other
    component missing, its weight is redistributed and overall = norm(A9)."""
    return JUDGEMENT.model_copy(
        update={
            "exchanges": [ExchangeJudgement(exchange_id="E01", items=[item("A9", a9, ["T02"])])],
            "session_items": [],
            "requirements": [],
            "summary": summary,
        }
    ).model_dump_json()


@pytest.mark.parametrize("finished_session", [3], indirect=True)
def test_report_is_the_median_of_three_runs(finished_session):
    f = finished_session
    f.replies += [judged(5, "high"), judged(2, "low"), judged(4, "middle")]
    report = evaluate_session(f.deps, f.uid, f.sid)
    assert len([r for r in f.requests if r["model"] == SETTINGS.models.judge]) == 3
    assert sorted(report.runs) == [25.0, 75.0, 100.0]
    assert report.overall == 75.0 and report.summary == "middle"  # numbers and words from the same run
    assert report.spread == 75.0
    # 2 interviewer calls + 3 judge calls at $0.002 each: every run is billed, so every run is logged.
    assert f.eng.session_cost(f.deps.engine, f.sid) == pytest.approx(0.010)


@pytest.mark.parametrize("finished_session", [3], indirect=True)
def test_a_failed_run_does_not_sink_the_report(finished_session):
    f = finished_session
    # Two good replies; the third run gets nothing (an API error) and its repair retry fails too.
    f.replies += [judged(4, "a"), judged(2, "b")]
    report = evaluate_session(f.deps, f.uid, f.sid)
    assert sorted(report.runs) == [25.0, 75.0]
    assert report.overall == 25.0  # even count: the lower middle, the more cautious score


def test_median_run_ordering():
    from interview_app.evaluation.service import median_run

    runs = [
        ("a", {"overall": 80.0}),
        ("b", {"overall": None}),
        ("c", {"overall": 40.0}),
        ("d", {"overall": 60.0}),
    ]
    assert median_run(runs)[0] == "d"
    assert median_run([("x", {"overall": None})])[0] == "x"


def test_old_reports_without_runs_still_load():
    from interview_app.evaluation.schemas import Report

    old = {
        k: v
        for k, v in Report(
            overall=50.0,
            band="lean_no",
            components={},
            penalties=[],
            exchanges=[],
            session_items=[],
            requirements=[],
            strengths=[],
            improvements=[],
            better_answer=None,
            summary="",
            talk_ratio=None,
            judge_model="m",
            rubric_version="1",
        )
        .model_dump()
        .items()
        if k not in ("runs", "spread")
    }
    report = Report.model_validate(old)
    assert report.runs == [] and report.spread is None


# --- evidence rules (audit fixes) ---------------------------------------------------------------


def judgement_with(**kw):
    base = dict(exchanges=[], session_items=[], requirements=[], strengths=[], improvements=[], summary="")
    return Judgement(**{**base, **kw})


def run_aggregate(judgement):
    exchanges = build_exchanges(TRANSCRIPT)
    return aggregate(judgement, exchanges, compute_metrics(exchanges, RUBRIC), RUBRIC, "hiring_manager")


def test_unverified_positive_level_on_a_discussed_requirement_counts_as_zero():
    """Downgrading to not_addressed would drop it from coverage, which favours the candidate."""
    reqs = [
        RequirementEvidence(
            requirement="a",
            priority="must",
            rationale="",
            evidence=["T06"],
            quote="I designed the data pipeline",
            level="convincingly_demonstrated",
        ),
        RequirementEvidence(
            requirement="b",
            priority="must",
            rationale="",
            evidence=["T04"],
            quote="I have ten years of Kubernetes",  # never said
            level="claimed",
        ),
    ]
    result = run_aggregate(judgement_with(requirements=reqs))
    assert [r.level for r in result["requirements"]] == ["convincingly_demonstrated", "not_demonstrated"]
    assert result["components"]["requirement_coverage"] == pytest.approx(50.0)


def test_not_demonstrated_needs_a_cited_candidate_turn():
    req = RequirementEvidence(requirement="a", priority="must", rationale="", level="not_demonstrated")
    assert run_aggregate(judgement_with(requirements=[req]))["requirements"][0].level == "not_addressed"


def test_exchange_items_must_cite_their_own_exchange():
    # T06 is a real candidate turn, but it belongs to E02, not E01.
    judgement = judgement_with(
        exchanges=[ExchangeJudgement(exchange_id="E01", items=[item("A3", 5, ["T06"])])]
    )
    e01 = next(r for r in run_aggregate(judgement)["exchanges"] if r.exchange_id == "E01")
    assert e01.items == []


def test_duplicate_items_count_once():
    items = [item("A3", 5, ["T06"]), item("A3", 5, ["T06"]), item("A4", 1, ["T06"])]
    judgement = judgement_with(exchanges=[ExchangeJudgement(exchange_id="E02", items=items)])
    e02 = next(r for r in run_aggregate(judgement)["exchanges"] if r.exchange_id == "E02")
    assert [i.item for i in e02.items] == ["A3", "A4"] and e02.score == pytest.approx(50.0)


def test_session_items_need_evidence_and_rf5_needs_an_evidenced_s1():
    result = run_aggregate(judgement_with(session_items=[item("S1", 1, []), item("S3", 4, ["T99"])]))
    assert result["session_items"] == [] and result["penalties"] == []


def test_s4_needs_a_candidate_questions_exchange():
    exchanges = [ex for ex in build_exchanges(TRANSCRIPT) if ex.category != "CQ"]
    judgement = judgement_with(session_items=[item("S4", 1, ["T02"])])
    result = aggregate(judgement, exchanges, compute_metrics(exchanges, RUBRIC), RUBRIC, "hiring_manager")
    assert result["components"]["S4"] is None


def test_quote_must_appear_in_order_not_as_scattered_words():
    from interview_app.evaluation.aggregate import quote_found

    texts = {"T02": "We shipped the model and then the team measured the latency on the device every week."}
    assert quote_found("the team measured the latency on the device", ["T02"], texts)
    assert quote_found("the team measured latency on the device", ["T02"], texts)  # one dropped word
    assert not quote_found("the device measured the team", ["T02"], texts)  # same words, scrambled
    assert not quote_found("the model", ["T02"], texts)  # too short to prove anything


def test_length_flags_use_the_main_answer_not_the_followups():
    transcript = [
        tv(0, "interviewer", "Walk me through the project.", "experience", "EXP-DEEP-01"),
        tv(1, "candidate", "word " * 300),
        tv(2, "interviewer", "What was your part?", "experience", "EXP-OWN-01", followup=True),
        tv(3, "candidate", "word " * 300),
    ]
    m = compute_metrics(build_exchanges(transcript), RUBRIC).exchanges[0]
    assert m.answer_words == 600 and not m.long_answer  # EXP long limit is 550 per answer


def test_case_length_limits_apply_per_turn():
    transcript = [
        tv(0, "interviewer", "Estimate it.", "technical", "CASE-01"),
        tv(1, "candidate", "word " * 300),
        tv(2, "interviewer", "And then?", "technical", "CASE-01", followup=True),
        tv(3, "candidate", "word " * 300),
    ]
    m = compute_metrics(build_exchanges(transcript), RUBRIC).exchanges[0]
    assert not m.long_answer and not m.short_answer  # each turn is within CASE's 400-word limit


def test_judge_max_tokens_comes_from_settings():
    from interview_app.evaluation.judge import run_judge

    seen = {}

    class FakeLLM:
        def chat_json(self, role, messages, schema, **kw):
            seen.update(kw)
            raise RuntimeError("stop")

    with pytest.raises(RuntimeError):
        run_judge(FakeLLM(), Settings(_env_file=None, judge_max_tokens=12345), [])
    assert seen["max_tokens"] == 12345
