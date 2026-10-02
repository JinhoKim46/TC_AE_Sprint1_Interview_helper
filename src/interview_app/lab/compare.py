"""The experiment loop behind lab/compare_prompts.py and lab/sweep_setting.py.

An *arm* is one interviewer configuration to test (a prompt variant, or one value of a setting).
Every arm is run against every candidate persona N times; each session is judged and measured;
the results become one CSV row each and one summary row per arm.

Spend is checked between sessions against a budget, from the call log (the real charged cost),
so an expensive run stops cleanly with the results so far instead of running away.
"""

import csv
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean

from sqlalchemy.engine import Engine
from sqlmodel import func, select

from interview_app.config import Settings
from interview_app.db import LLMCall, init_db, make_engine, session_scope
from interview_app.demo import load_sample_application
from interview_app.interview.engine import EngineDeps, InterviewError, active_session, end_interview
from interview_app.interview.persona import SessionConfig
from interview_app.lab.candidate import CandidatePersona
from interview_app.lab.judge import (
    NOUL_ITEMS,
    SCORE_ITEMS,
    CodeMetrics,
    GateResult,
    JudgeResult,
    code_metrics,
    judge_session,
    load_session,
    release_gate,
)
from interview_app.lab.runner import run_session
from interview_app.llm.calllog import make_db_recorder
from interview_app.llm.client import LLMClient, LLMError
from interview_app.llm.decide import DecisionClient
from interview_app.llm.pricing import PriceCatalog
from interview_app.security import InjectionGuard
from interview_app.users import ensure_local_user

log = logging.getLogger(__name__)


@dataclass
class Arm:
    label: str
    config: SessionConfig


@dataclass
class SessionResult:
    arm: str
    persona: str
    repeat: int
    session_id: int
    status: str
    judge: JudgeResult
    metrics: CodeMetrics
    blocked: int  # simulated answers a guard blocked (should be 0)


class BudgetExceeded(Exception):
    pass


def spend_since(engine: Engine, first_call_id: int) -> float:
    """Total charged cost of the calls logged after `first_call_id` (this run only)."""
    with session_scope(engine) as s:
        total = s.exec(select(func.sum(LLMCall.cost_usd)).where(LLMCall.id > first_call_id)).one()
    return float(total or 0.0)


def last_call_id(engine: Engine) -> int:
    with session_scope(engine) as s:
        return int(s.exec(select(func.max(LLMCall.id))).one() or 0)


def run_arms(
    deps: EngineDeps,
    decider: DecisionClient,
    user_id: int,
    app_id: int,
    arms: list[Arm],
    personas: list[CandidatePersona],
    sessions_per_persona: int,
    budget_usd: float,
    max_candidate_turns: int = 16,
    progress: Callable[[str], None] = print,
) -> tuple[list[SessionResult], bool]:
    """Run every arm x persona x repeat. Returns (results, aborted_on_budget)."""
    start_id = last_call_id(deps.engine)
    results: list[SessionResult] = []
    for arm in arms:
        for persona in personas:
            for repeat in range(sessions_per_persona):
                spent = spend_since(deps.engine, start_id)
                if spent >= budget_usd:
                    progress(f"Budget reached (${spent:.3f} >= ${budget_usd:.2f}); stopping.")
                    return results, True
                blocked: list[str] = []
                try:
                    sid = run_session(
                        deps, user_id, app_id, arm.config, persona, max_candidate_turns, blocked=blocked
                    )
                    data = load_session(deps.engine, sid)
                    metrics = code_metrics(data)
                    verdict = judge_session(decider, data)
                except (InterviewError, LLMError) as e:
                    # One failed session shouldn't lose the whole run; it is reported and skipped.
                    progress(f"  {arm.label} / {persona.value} #{repeat + 1}: FAILED ({e})")
                    continue
                results.append(
                    SessionResult(
                        arm.label, persona.value, repeat + 1, sid, data.status, verdict, metrics, len(blocked)
                    )
                )
                progress(
                    f"  {arm.label} / {persona.value} #{repeat + 1}: session {sid}, {metrics.turns} turns, "
                    f"I1={verdict.scores['I1']:.2f} I3={verdict.scores['I3']:.2f} "
                    f"I9={verdict.scores['I9']:.2f}, run spend ${spend_since(deps.engine, start_id):.3f}"
                )
    return results, False


# --- Output -------------------------------------------------------------------------------------


def result_row(r: SessionResult) -> dict:
    row = {
        "arm": r.arm,
        "persona": r.persona,
        "repeat": r.repeat,
        "session_id": r.session_id,
        "status": r.status,
        "blocked_answers": r.blocked,
    }
    row |= {k: round(v, 3) for k, v in r.judge.scores.items()}
    row |= {f"{k}_p_yes": round(v, 3) for k, v in r.judge.p_yes.items()}
    row |= {k: (round(v, 5) if isinstance(v, float) else v) for k, v in asdict(r.metrics).items()}
    row["judge_cost_usd"] = round(r.judge.cost_usd, 6)
    return row


def write_csv(results: list[SessionResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [result_row(r) for r in results]
    with path.open("w", newline="") as f:
        if not rows:
            return
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@dataclass
class ArmSummary:
    arm: str
    n: int
    score_means: dict[str, float]  # I1, I3, I9
    yes_rates: dict[str, float]  # I2, I5, I6, I7, I10: share of sessions with p >= 0.5
    main_questions: float
    followups: float
    words: float
    multi_q_share: float
    closed_share: float
    interviewer_cost: float  # mean per session
    latency: float
    gate: GateResult


def summarize(
    results: list[SessionResult], key: Callable[[SessionResult], str] = lambda r: r.arm
) -> list[ArmSummary]:
    """One summary per group; by arm by default, or e.g. by (arm, persona) for a breakdown."""
    summaries = []
    for group in dict.fromkeys(key(r) for r in results):  # keeps the run order
        rs = [r for r in results if key(r) == group]
        m = [r.metrics for r in rs]
        summaries.append(
            ArmSummary(
                arm=group,
                n=len(rs),
                score_means={k: mean(r.judge.scores[k] for r in rs) for k in SCORE_ITEMS},
                yes_rates={k: mean(r.judge.is_yes(k) for r in rs) for k in NOUL_ITEMS},
                main_questions=mean(x.main_questions for x in m),
                followups=mean(x.followups for x in m),
                words=mean(x.interviewer_words_mean for x in m),
                multi_q_share=mean(x.multi_question_share for x in m),
                closed_share=mean(x.closed_properly for x in m),
                interviewer_cost=mean(x.interviewer_cost_usd for x in m),
                latency=mean(x.interviewer_latency_mean_s for x in m),
                gate=release_gate([r.judge for r in rs]),
            )
        )
    return summaries


def markdown_table(summaries: list[ArmSummary]) -> str:
    """I1/I3/I9 are means (1-5); I2..I10 are the share of sessions judged "yes" (p >= 0.5)."""
    head = (
        "| Arm | n | I1 | I3 | I9 | I2 | I5 | I6 | I7 | I10 | main Q | follow-ups | words/turn "
        "| >1 '?' | closed | $/session | s/turn | gate |"
    )
    sep = "|" + "---|" * 18
    lines = [head, sep]
    for s in summaries:
        sc, yr = s.score_means, s.yes_rates
        gate = "pass" if s.gate.passed else "FAIL: " + "; ".join(s.gate.reasons)
        lines.append(
            f"| {s.arm} | {s.n} | {sc['I1']:.2f} | {sc['I3']:.2f} | {sc['I9']:.2f} "
            f"| {yr['I2']:.0%} | {yr['I5']:.0%} | {yr['I6']:.0%} | {yr['I7']:.0%} | {yr['I10']:.0%} "
            f"| {s.main_questions:.1f} | {s.followups:.1f} | {s.words:.0f} | {s.multi_q_share:.0%} "
            f"| {s.closed_share:.0%} | {s.interviewer_cost:.4f} | {s.latency:.1f} | {gate} |"
        )
    return "\n".join(lines)


# --- Wiring for the CLIs ------------------------------------------------------------------------


@dataclass
class Lab:
    deps: EngineDeps
    decider: DecisionClient
    user_id: int
    app_id: int


def make_lab(settings: Settings, db_path: Path) -> Lab:
    """Real models, a separate lab database (never the app's own), and a fresh copy of the
    fictional sample application. The injection guard stays on, as in the app."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(f"sqlite:///{db_path}")
    init_db(engine)
    user_id = ensure_local_user(engine)
    app_id = load_sample_application(engine, user_id, limits=settings.limits)
    pricing = PriceCatalog(settings)

    def make_llm(uid: int, session_id: int | None) -> LLMClient:
        return LLMClient(settings, recorder=make_db_recorder(engine, uid, session_id), pricing=pricing)

    recorder = make_db_recorder(engine, user_id)
    guard = InjectionGuard(settings, DecisionClient(settings, recorder=recorder))
    deps = EngineDeps(engine=engine, settings=settings, make_llm=make_llm, guard=guard)
    # A run killed hard (no `finally`) may have left a session active; it would block every new start.
    while (leftover := active_session(engine, user_id, settings)) is not None:
        end_interview(deps, user_id, leftover.id)
    return Lab(deps, DecisionClient(settings, recorder=recorder), user_id, app_id)
