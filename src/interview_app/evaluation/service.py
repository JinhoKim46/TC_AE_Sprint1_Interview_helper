"""Evaluate a finished interview and store the report.

Pipeline: transcript -> exchanges (code) -> metrics (code) -> judge (model) -> aggregate (code) -> Report.
The report is stored, so re-opening it costs nothing; `force=True` re-runs the judge.
"""

import json
import logging

from pydantic import ValidationError
from sqlmodel import select

from interview_app.db import Evaluation, InterviewSession, session_scope
from interview_app.evaluation.aggregate import aggregate
from interview_app.evaluation.exchanges import build_exchanges, turn_id
from interview_app.evaluation.judge import judge_messages, run_judge
from interview_app.evaluation.metrics import compute_metrics
from interview_app.evaluation.rubric import load_rubric
from interview_app.evaluation.schemas import Report
from interview_app.ingest import DocKind
from interview_app.interview.engine import EngineDeps, get_session
from interview_app.interview.schemas import InterviewPlan
from interview_app.llm.client import LLMError

log = logging.getLogger(__name__)


class EvaluationError(Exception):
    """Shown to the user as is."""


def stored_report(deps: EngineDeps, user_id: int, session_id: int) -> Report | None:
    with session_scope(deps.engine) as s:
        row = s.exec(
            select(Evaluation).where(Evaluation.session_id == session_id, Evaluation.user_id == user_id)
        ).first()
    return Report.model_validate_json(row.report_json) if row else None


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
        documents = {DocKind(k): v for k, v in json.loads(row.documents_json).items()}
        plan = InterviewPlan.model_validate_json(row.plan_json) if row.plan_json else None

    rubric = load_rubric(deps.settings.rubric_path)
    metrics = compute_metrics(exchanges, rubric)
    model = judge_model or deps.settings.models.judge
    messages = judge_messages(rubric, view.company, view.role, documents, exchanges, plan)
    try:
        judgement = run_judge(deps.make_llm(user_id, session_id), deps.settings, messages, model)
    except (LLMError, ValidationError) as e:
        log.warning("Judge failed for session %s: %r", session_id, e)
        raise EvaluationError("The evaluator could not produce a report. Please try again.") from e

    turn_texts = {turn_id(t.idx): t.text for t in view.turns}
    numbers = aggregate(judgement, exchanges, metrics, rubric, view.config.interview_type.value, turn_texts)
    report = Report(
        **numbers,
        improvements=judgement.improvements,
        better_answer=judgement.better_answer,
        summary=judgement.summary,
        talk_ratio=metrics.talk_ratio,
        judge_model=model,
        rubric_version=rubric.version,
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
