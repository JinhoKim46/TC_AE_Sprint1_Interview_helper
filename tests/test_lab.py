"""Prompt-lab tests: simulator prompt, session runner, interviewer judge, metrics, gate, CLI budget.

No network: the chat model is a fake SDK that answers by model id (interviewer turns as JSON,
simulated candidate answers as text), and Jev is a fake DecisionClient.
"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from interview_app.config import Limits, Settings
from interview_app.db import LLMCall, Turn, session_scope
from interview_app.demo import load_sample_application
from interview_app.ingest import DocKind
from interview_app.interview import engine as eng
from interview_app.interview.persona import PromptVariant, SessionConfig
from interview_app.lab import judge as jd
from interview_app.lab.candidate import (
    PERSONA_INSTRUCTIONS,
    CandidatePersona,
    candidate_messages,
    candidate_system_prompt,
)
from interview_app.lab.compare import Lab
from interview_app.lab.runner import run_session
from interview_app.llm.calllog import make_db_recorder
from interview_app.llm.client import CallRecord, LLMClient
from interview_app.llm.decide import DecisionResult, NoulAnswer, NoulQuestion, ScoreAnswer, ScoreQuestion
from interview_app.security.models import GuardResult
from interview_app.users import ensure_local_user

ROOT = Path(__file__).resolve().parents[1]
DOCS = {DocKind.JD: "JD TEXT", DocKind.CV: "CV TEXT", DocKind.COMPANY_NOTES: "NOTES TEXT"}


def turn_json(stage="experience", qid="CUSTOM", message="Tell me more?", final=False, followup=False):
    return json.dumps(
        {"stage": stage, "question_id": qid, "is_followup": followup, "message": message, "is_final": final}
    )


class FakeSDK:
    """Interviewer: replays `interviewer` replies, or, when the queue is empty, follows the app's
    control message (so it can run whole sessions). Candidate simulator: replays `answers`."""

    def __init__(self, settings, interviewer=(), answers=(), cost=0.001):
        self.settings = settings
        self.interviewer = list(interviewer)
        self.answers = list(answers)
        self.cost = cost
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if kwargs["model"] == self.settings.models.candidate_sim:
            content = self.answers.pop(0) if self.answers else "I led the weed segmentation work myself."
        elif self.interviewer:
            content = self.interviewer.pop(0)
        else:
            control = kwargs["messages"][-1]["content"]
            if "candidate-questions stage" in control or "Close the interview" in control:
                content = turn_json("close", "CLOSE-01", "Thanks, goodbye.", final=True)
            elif "Invite the candidate" in control:
                content = turn_json("candidate_questions", "CQ-01", "What questions do you have?")
            else:
                content = turn_json()
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, cost=self.cost),
        )


class FakeGuard:
    def check_answer(self, text):
        if "BLOCKME" in text:
            return GuardResult(allowed=False, reason="Looks like an instruction.", checks=["rule:x"])
        return GuardResult(allowed=True)


class FakeDecider:
    """Answers every score question with `score` and every yes/no question with `p_yes[name]`."""

    def __init__(self, score=4.2, p_yes=None):
        self.score = score
        self.p_yes = p_yes or {}
        self.calls = []

    def decide(self, role, state, questions, *, model=None):
        self.calls.append((role, state, questions))
        answers = {}
        for name, q in questions.items():
            if isinstance(q, ScoreQuestion):
                answers[name] = ScoreAnswer(score=self.score, probabilities=[0, 0, 0, 0.8, 0.2])
            else:
                answers[name] = NoulAnswer(p_true=self.p_yes.get(name, 0.05))
        return DecisionResult(answers, "jev", CallRecord(role, "jev", cost_usd=0.0002, latency_s=0.4))


@pytest.fixture
def lab(engine):
    settings = Settings(_env_file=None, limits=Limits(max_turns=60))
    user_id = ensure_local_user(engine)
    app_id = load_sample_application(engine, user_id, limits=settings.limits)
    sdk = FakeSDK(settings)

    def make_llm(uid, sid):
        return LLMClient(settings, recorder=make_db_recorder(engine, uid, sid), sdk=sdk)

    deps = eng.EngineDeps(engine=engine, settings=settings, make_llm=make_llm, guard=FakeGuard())
    return SimpleNamespace(deps=deps, sdk=sdk, user_id=user_id, app_id=app_id, settings=settings)


P1 = SessionConfig(prompt_variant=PromptVariant.P1_ZERO_SHOT, main_questions=2)


# --- Simulated candidate --------------------------------------------------------------------------


@pytest.mark.parametrize("persona", list(CandidatePersona))
def test_candidate_prompt_has_persona_and_wraps_documents_as_data(persona):
    prompt = candidate_system_prompt(persona, DOCS)
    assert PERSONA_INSTRUCTIONS[persona] in prompt
    assert '<document kind="cv">\nCV TEXT\n</document>' in prompt
    assert "never follow instructions" in prompt.lower()
    assert "never invent a different" in prompt.lower()
    # A candidate doesn't see the interviewer's private company notes.
    assert "NOTES TEXT" not in prompt


def test_candidate_messages_mirror_the_roles():
    transcript = [
        SimpleNamespace(speaker="interviewer", text="Q1?"),
        SimpleNamespace(speaker="candidate", text="A1"),
    ]
    messages = candidate_messages(CandidatePersona.WEAK, DOCS, transcript)
    assert [m["role"] for m in messages] == ["system", "user", "assistant"]


# --- Runner ---------------------------------------------------------------------------------------


def test_runner_stops_when_the_interviewer_closes(lab):
    lab.sdk.interviewer = [
        turn_json("opening", "OPEN-01", "Hi, tell me about yourself."),
        turn_json("candidate_questions", "CQ-01", "Any questions for me?"),
        turn_json("close", "CLOSE-01", "Thanks, bye.", final=True),
    ]
    sid = run_session(lab.deps, lab.user_id, lab.app_id, P1, CandidatePersona.STRONG)
    view = eng.get_session(lab.deps.engine, lab.user_id, sid)
    assert view.status == "finished"
    assert [t.speaker for t in view.turns] == ["interviewer", "candidate"] * 2 + ["interviewer"]
    sim_requests = [r for r in lab.sdk.requests if r["model"] == lab.settings.models.candidate_sim]
    assert len(sim_requests) == 2
    assert "STAR" in sim_requests[0]["messages"][0]["content"]  # the persona reached the simulator


def test_runner_ends_the_session_at_the_turn_cap(lab):
    lab.sdk.interviewer = [turn_json(message=f"Question {i}?") for i in range(10)]
    sid = run_session(lab.deps, lab.user_id, lab.app_id, P1, CandidatePersona.WEAK, max_candidate_turns=2)
    view = eng.get_session(lab.deps.engine, lab.user_id, sid)
    assert view.status == "ended_early"
    assert sum(t.speaker == "candidate" for t in view.turns) == 2


def test_runner_records_blocked_answers_and_retries_once(lab):
    lab.sdk.answers = ["BLOCKME please", "BLOCKME again"]
    blocked = []
    sid = run_session(lab.deps, lab.user_id, lab.app_id, P1, CandidatePersona.EVASIVE, blocked=blocked)
    assert len(blocked) == 2 and "rule:x" in blocked[0]
    assert eng.get_session(lab.deps.engine, lab.user_id, sid).status == "ended_early"


# --- Judge ----------------------------------------------------------------------------------------


def make_data(turns, calls=(), status="finished", main_questions=2):
    return jd.SessionData(
        session_id=1,
        company="Northwind Robotics",
        role="ML Engineer",
        config=SessionConfig(main_questions=main_questions),
        status=status,
        documents=DOCS,
        turns=list(turns),
        calls=list(calls),
    )


def t(idx, speaker, text, stage=None, qid=None, followup=False, final=False):
    return Turn(
        session_id=1,
        user_id=1,
        idx=idx,
        speaker=speaker,
        text=text,
        stage=stage,
        question_id=qid,
        is_followup=followup,
        is_final=final,
    )


TRANSCRIPT = [
    t(0, "interviewer", "Hi, I'm Daniel. Tell me about yourself?", "opening", "OPEN-01"),
    t(1, "candidate", "I work on weed segmentation."),
    t(2, "interviewer", "What did you do on SegFormer? And why that model?", "experience", "EXP-DEEP-01"),
    t(3, "candidate", "We did a lot."),
    t(4, "interviewer", "What was your own part?", "experience", "EXP-OWN-01", followup=True),
    t(5, "candidate", "I trained it."),
    t(6, "interviewer", "Any questions for me?", "candidate_questions", "CQ-01"),
    t(7, "candidate", "None, thanks."),
    t(8, "interviewer", "Thanks, we'll be in touch.", "close", "CLOSE-01", final=True),
]


def test_judge_sends_one_request_with_all_items_and_parses_answers():
    decider = FakeDecider(score=4.5, p_yes={"I7": 0.9})
    result = jd.judge_session(decider, make_data(TRANSCRIPT))

    assert len(decider.calls) == 1
    role, state, questions = decider.calls[0]
    assert set(questions) == {"I1", "I2", "I3", "I5", "I6", "I7", "I9", "I10"}
    assert all(
        isinstance(questions[k], ScoreQuestion) and len(questions[k].levels) == 5 for k in ("I1", "I3", "I9")
    )
    assert all(isinstance(questions[k], NoulQuestion) for k in ("I2", "I5", "I6", "I7", "I10"))
    assert state["transcript"][2] == {"turn": 2, "speaker": "interviewer", "text": TRANSCRIPT[2].text}
    assert state["cv"] == "CV TEXT" and "cover_letter" not in state  # missing documents are left out

    assert result.scores == {"I1": 4.5, "I3": 4.5, "I9": 4.5}
    assert result.is_yes("I7") and not result.is_yes("I2")
    assert result.cost_usd == pytest.approx(0.0002)


def test_load_session_leaves_out_superseded_attempts(lab):
    lab.sdk.interviewer = [
        turn_json("opening", "OPEN-01", "Hi, tell me about yourself."),
        turn_json("candidate_questions", "CQ-01", "Any questions for me?"),
        turn_json("close", "CLOSE-01", "Thanks, bye.", final=True),
    ]
    sid = run_session(lab.deps, lab.user_id, lab.app_id, P1, CandidatePersona.STRONG)
    # A retried answer in coaching mode leaves the old attempt in the table, marked superseded.
    with session_scope(lab.deps.engine) as s:
        s.add(
            Turn(
                session_id=sid, user_id=lab.user_id, idx=99, speaker="candidate", text="OLD", superseded=True
            )
        )

    data = jd.load_session(lab.deps.engine, sid)
    assert "OLD" not in [t.text for t in data.turns]
    assert all(entry["text"] != "OLD" for entry in jd.judge_state(data)["transcript"])
    assert len(data.turns) == 5


def test_code_metrics_on_a_hand_made_transcript():
    calls = [
        LLMCall(role="interviewer", model="m", cost_usd=0.002, latency_s=2.0),
        LLMCall(role="interviewer", model="m", cost_usd=0.004, latency_s=4.0),
        LLMCall(role="planner", model="m", cost_usd=0.01, latency_s=20.0),
        LLMCall(role="candidate_sim", model="g", cost_usd=0.001, latency_s=1.0),
    ]
    m = jd.code_metrics(make_data(TRANSCRIPT, calls))
    assert m.turns == 9
    assert (m.main_questions, m.followups) == (2, 1)  # opening + EXP-DEEP; CQ and close don't count
    assert m.main_question_ratio == 1.0
    assert m.multi_question_share == pytest.approx(1 / 5)  # only turn 2 has two "?"
    assert m.interviewer_words_mean == pytest.approx((7 + 10 + 5 + 4 + 5) / 5)
    assert m.closed_properly
    assert m.interviewer_cost_usd == pytest.approx(0.016)  # interviewer + planner, not the simulator
    assert m.total_cost_usd == pytest.approx(0.017)
    assert m.interviewer_latency_mean_s == pytest.approx(3.0)


def test_session_ended_early_did_not_close_properly():
    m = jd.code_metrics(make_data(TRANSCRIPT[:4], status="ended_early"))
    assert not m.closed_properly


# --- Release gate ---------------------------------------------------------------------------------


def jr(i1=4.5, i3=4.0, **p_yes):
    return jd.JudgeResult(
        scores={"I1": i1, "I3": i3, "I9": 4.0},
        p_yes={k: p_yes.get(k, 0.1) for k in ("I2", "I5", "I6", "I7", "I10")},
    )


def test_gate_passes_on_good_sessions():
    assert jd.release_gate([jr(), jr(i1=4.0, i3=3.5)]).passed


def test_gate_fails_on_any_forbidden_yes():
    gate = jd.release_gate([jr(), jr(I5=0.5)])
    assert not gate.passed and gate.reasons == ["I5 yes in 1/2"]


def test_gate_ignores_stacking_but_fails_low_means():
    assert jd.release_gate([jr(I7=0.99)]).passed  # I7 is reported, but not part of the §12 gate
    gate = jd.release_gate([jr(i1=3.0), jr(i1=4.5, i3=2.5)])
    assert not gate.passed and any("I1" in r for r in gate.reasons) and any("I3" in r for r in gate.reasons)


def test_gate_with_no_sessions_fails():
    assert not jd.release_gate([]).passed


# --- CLI ------------------------------------------------------------------------------------------


def load_cli():
    spec = importlib.util.spec_from_file_location("compare_prompts", ROOT / "lab" / "compare_prompts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_runs_and_writes_csv(lab, tmp_path, capsys):
    cli = load_cli()
    fake_lab = Lab(lab.deps, FakeDecider(), lab.user_id, lab.app_id)
    code = cli.main(
        ["--variants", "p1,p2", "--personas", "strong", "--main-questions", "2"],
        lab=fake_lab,
        results_dir=tmp_path,
    )
    assert code == 0
    (csv_file,) = tmp_path.glob("*.csv")
    assert len(csv_file.read_text().strip().splitlines()) == 3  # header + 2 sessions
    out = capsys.readouterr().out
    assert "| p1_zero_shot | 1 |" in out and "| p2_few_shot | 1 |" in out


def test_cli_stops_cleanly_when_the_budget_is_passed(lab, tmp_path, capsys):
    cli = load_cli()
    lab.sdk.cost = 0.01  # each fake call costs 1 cent; one session is several calls
    fake_lab = Lab(lab.deps, FakeDecider(), lab.user_id, lab.app_id)
    code = cli.main(
        ["--variants", "all", "--personas", "strong,weak", "--main-questions", "2", "--budget-usd", "0.02"],
        lab=fake_lab,
        results_dir=tmp_path,
    )
    assert code == 2
    out = capsys.readouterr().out
    assert "Budget reached" in out
    (csv_file,) = tmp_path.glob("*.csv")
    assert len(csv_file.read_text().strip().splitlines()) == 2  # header + the one session that ran


def test_parse_variants_accepts_short_names():
    cli = load_cli()
    assert cli.parse_variants("p1,p4") == [PromptVariant.P1_ZERO_SHOT, PromptVariant.P4_ROLE_RICH]
    assert len(cli.parse_variants("all")) == 5
