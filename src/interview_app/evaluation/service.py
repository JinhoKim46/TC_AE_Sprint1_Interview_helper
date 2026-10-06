"""Evaluate a finished interview and store the report.

Pipeline: transcript -> exchanges (code) -> metrics (code) -> judge (model) -> aggregate (code) -> Report.

Median of several runs: the same transcript scored 56.6 and 71.5 on two single runs, so one run is not
a reliable number. The judge runs `runs` times in parallel (latency stays about one run), each run is
aggregated on its own, and the report is the run whose overall score is the median. Picking a whole run
(rather than a median per item) keeps the numbers and the written feedback from the same judgement.
The report is stored, so re-opening it costs nothing; `force=True` re-runs the judge.
"""

import logging
import math
import re
import statistics
from concurrent.futures import ThreadPoolExecutor

from pydantic import ValidationError
from sqlalchemy.engine import Engine
from sqlmodel import col, or_, select

from interview_app.config import Settings
from interview_app.db import Evaluation, InterviewSession, LLMCall, session_scope
from interview_app.evaluation.aggregate import aggregate
from interview_app.evaluation.exchanges import build_exchanges
from interview_app.evaluation.judge import judge_messages, run_judge
from interview_app.evaluation.metrics import compute_metrics
from interview_app.evaluation.rubric import load_rubric
from interview_app.evaluation.schemas import Report
from interview_app.history import load_report
from interview_app.interview.engine import (
    EngineDeps,
    get_session,
    session_cost,
    session_documents,
    session_plan,
)
from interview_app.interview.persona import Length
from interview_app.llm.client import LLMError
from interview_app.security import check_budget

log = logging.getLogger(__name__)


class EvaluationError(Exception):
    """Shown to the user as is."""


def median_run(scored: list[tuple]) -> tuple:
    """The (judgement, numbers) pair whose overall score is the median. Runs without an overall score
    sort last; with an even count the lower middle is taken (the more cautious score)."""
    ordered = sorted(scored, key=lambda pair: (pair[1]["overall"] is None, pair[1]["overall"] or 0))
    with_score = [p for p in ordered if p[1]["overall"] is not None] or ordered
    return with_score[(len(with_score) - 1) // 2]


# Shown when this user has no finished report with the chosen judge yet. Deliberately not "about a minute":
# a reasoning judge run three times took 60-70 s on the owner's machine, and an honest range beats a promise.
REPORT_WAIT_FALLBACK = "This usually takes one to two minutes."


def _same_model(stored: str, chosen: str) -> bool:
    # The call log stores the model that answered, which OpenRouter may report as a dated build of the chosen
    # id (`openai/gpt-5-mini-2025-08-07`). Only a date suffix counts: `...-mini-high` is another model.
    return stored == chosen or re.fullmatch(re.escape(chosen) + r"-\d{4}-?\d{2}-?\d{2}", stored) is not None


def report_wait_seconds(engine: Engine, user_id: int, judge_model: str, settings: Settings) -> int | None:
    """How long a report with `judge_model` usually takes for this user, in seconds; None without history.

    "The model judges, code computes": the estimate comes from the call log, not a guess. The judge runs in
    parallel, so one report waits for its slowest run: each recent report (its successful judge calls,
    grouped by session) counts with its slowest call, and the estimate is the median over the last
    `settings.report_wait_history` reports (one unusually slow report doesn't move it much), rounded up
    to the next 5 seconds so it reads like an estimate, not a measurement.
    """
    history = settings.report_wait_history
    with session_scope(engine) as s:
        rows = s.exec(
            select(LLMCall.session_id, LLMCall.model, LLMCall.latency_s)
            .where(
                LLMCall.user_id == user_id,
                LLMCall.role == "judge",
                col(LLMCall.ok).is_(True),
                col(LLMCall.session_id).is_not(None),
                or_(LLMCall.model == judge_model, col(LLMCall.model).startswith(f"{judge_model}-")),
            )
            .order_by(col(LLMCall.created_at).desc(), col(LLMCall.id).desc())
            # Bounded: a report is a handful of calls (runs plus the odd repair), so this covers `history`.
            .limit(history * 12)
        ).all()
    slowest: dict[int, float] = {}  # session -> its slowest judge call; insertion order = newest first
    for session_id, model, latency in rows:
        if _same_model(model, judge_model):
            slowest[session_id] = max(slowest.get(session_id, 0.0), latency)
    recent = list(slowest.values())[:history]
    if not recent:
        return None
    return max(5, math.ceil(statistics.median(recent) / 5) * 5)


def report_wait_text(seconds: int | None) -> str:
    """The wait estimate in words, for the report button."""
    if seconds is None:
        return REPORT_WAIT_FALLBACK
    if seconds < 90:
        return f"This takes about {seconds} seconds, judging by your recent reports."
    return f"This takes about {round(seconds / 60)} minutes, judging by your recent reports."


def stored_report(deps: EngineDeps, user_id: int, session_id: int) -> Report | None:
    return load_report(deps.engine, user_id, session_id)


def evaluate_session(
    deps: EngineDeps, user_id: int, session_id: int, *, judge_model: str | None = None, force: bool = False
) -> Report:
    if not force and (existing := stored_report(deps, user_id, session_id)):
        return existing

    view = get_session(deps.engine, user_id, session_id)
    if view is None:
        raise EvaluationError("Interview not found.")
    if view.status in ("preparing", "active"):
        raise EvaluationError("Finish or end the interview first.")
    exchanges = [ex for ex in build_exchanges(view.turns) if ex.candidate_turns]
    if not exchanges:
        raise EvaluationError("There are no answers to evaluate yet.")

    with session_scope(deps.engine) as s:
        row = s.get(InterviewSession, session_id)
    documents, plan = session_documents(row), session_plan(row)

    rubric = load_rubric(deps.settings.rubric_path)
    metrics = compute_metrics(exchanges, rubric)
    model = judge_model or deps.settings.models.judge
    messages = judge_messages(rubric, view.company, view.role, documents, exchanges, plan)
    runs = max(1, deps.settings.judge_runs or rubric.judge_runs)
    if not check_budget(session_cost(deps.engine, session_id), deps.settings.limits).allowed:
        # The report must still be possible after a budget close, but at the cost of one run, not three.
        runs = 1

    # Each run gets its own client, but its call records are buffered and written to the call log from
    # this thread after all runs finish: SQLite handles one writer at a time, so writes from three
    # threads at once could fail or block.
    buffered: list = []

    def one_run(_: int):
        llm = deps.make_llm(user_id, session_id)
        llm.recorder = buffered.append  # list.append is thread-safe in CPython
        try:
            return run_judge(llm, deps.settings, messages, model, temperature=rubric.judge_temperature)
        except (LLMError, ValidationError) as e:
            log.warning("Judge run failed for session %s: %r", session_id, e)
            return None

    try:
        with ThreadPoolExecutor(max_workers=runs) as pool:
            judgements = [j for j in pool.map(one_run, range(runs)) if j is not None]
    finally:
        # Also on an unexpected error: every run is billed, including failed ones, so every run is logged.
        record = deps.make_llm(user_id, session_id).recorder
        for call in buffered:
            record(call)
    if not judgements:
        raise EvaluationError("The evaluator could not produce a report. Please try again.")

    scored = [
        (
            j,
            aggregate(
                j,
                exchanges,
                metrics,
                rubric,
                view.config.interview_type.value,
                # Quick's question offer is one skippable line: declining it is not scored (S4 stays null).
                cq_optional=view.config.length == Length.QUICK,
            ),
        )
        for j in judgements
    ]
    judgement, numbers = median_run(scored)
    overalls = [n["overall"] for _, n in scored]
    known = [o for o in overalls if o is not None]
    report = Report(
        **numbers,
        improvements=judgement.improvements,
        better_answer=judgement.better_answer,
        summary=judgement.summary,
        talk_ratio=metrics.talk_ratio,
        judge_model=model,
        rubric_version=rubric.version,
        runs=overalls,
        spread=round(max(known) - min(known), 1) if len(known) > 1 else None,
    )

    with session_scope(deps.engine) as s:
        old = s.exec(select(Evaluation).where(Evaluation.session_id == session_id)).first()
        if old:
            s.delete(old)
            s.flush()
        s.add(
            Evaluation(
                session_id=session_id,
                user_id=user_id,
                judge_model=model,
                overall=report.overall,
                band=report.band,
                report_json=report.model_dump_json(),
            )
        )
    return report
