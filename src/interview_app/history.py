"""Past interviews and progress across them (read-only views over stored sessions and reports).

Everything here is computed in code from what is already stored: no model is called. The judge's
numbers and words are in `Evaluation.report_json`; this module only counts, averages and orders them
("the model judges, code computes").
"""

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlmodel import col, func, select

from interview_app.config import get_settings
from interview_app.db import Evaluation, InterviewSession, LLMCall, Turn, session_scope
from interview_app.evaluation.rubric import load_rubric
from interview_app.evaluation.schemas import Report
from interview_app.interview.engine import TurnView, compute_progress
from interview_app.interview.persona import SessionConfig

# A session that never got going (still preparing, or the plan call failed) has no transcript worth
# showing, so History hides it. "active" stays visible: it is a real, resumable interview.
HIDDEN_STATUSES = ("preparing", "failed")

# Two reports mentioning the same improvement is the smallest number that makes it a pattern.
RECURRING_MIN_REPORTS = 2


class SessionSummary(BaseModel):
    session_id: int
    application_id: int
    company: str
    role: str
    started_at: datetime
    ended_at: datetime | None
    status: str
    interview_type: str
    difficulty: str
    mode: str
    prompt_variant: str
    main_questions_asked: int
    cost_usd: float
    overall: float | None
    band: str | None
    has_report: bool


class ItemMean(BaseModel):
    item: str  # rubric id, e.g. "A3"
    name: str  # plain-words name from rubric.json
    mean: float  # 1-5
    count: int  # how many exchange scores the mean is based on


class RequirementHistory(BaseModel):
    requirement: str
    priority: str
    latest_level: str
    level_counts: dict[str, int]  # level -> number of sessions that rated it so


class RecurringImprovement(BaseModel):
    area: str
    count: int  # number of reports that named it


class Progress(BaseModel):
    trend: list[tuple[datetime, float]]  # (started_at, overall), oldest first
    item_means: list[ItemMean]  # weakest first
    requirements: list[RequirementHistory]
    recurring_improvements: list[RecurringImprovement]  # most frequent first


def _visible_sessions(user_id: int, application_id: int | None = None):
    query = select(InterviewSession).where(
        InterviewSession.user_id == user_id, col(InterviewSession.status).not_in(HIDDEN_STATUSES)
    )
    if application_id is not None:
        query = query.where(InterviewSession.application_id == application_id)
    return query


def list_sessions(engine: Engine, user_id: int, application_id: int | None = None) -> list[SessionSummary]:
    """The user's interviews, newest first.

    Reports, turns and costs are each fetched with one query for all sessions (not one per session),
    so the page stays fast however many interviews pile up.
    """
    with session_scope(engine) as s:
        rows = s.exec(
            _visible_sessions(user_id, application_id).order_by(
                col(InterviewSession.started_at).desc(), col(InterviewSession.id).desc()
            )
        ).all()
        ids = [r.id for r in rows]
        if not ids:
            return []
        # Evaluation keeps overall/band in their own columns, so the list needs no JSON parsing.
        reports = {
            e.session_id: e
            for e in s.exec(
                select(Evaluation).where(col(Evaluation.session_id).in_(ids), Evaluation.user_id == user_id)
            ).all()
        }
        turns: dict[int, list[TurnView]] = defaultdict(list)
        for t in s.exec(
            select(Turn).where(col(Turn.session_id).in_(ids)).order_by(col(Turn.session_id), col(Turn.idx))
        ).all():
            turns[t.session_id].append(
                TurnView(t.idx, t.speaker, t.text, t.stage, t.question_id, t.is_followup, t.is_final)
            )
        costs = dict(
            s.exec(
                select(LLMCall.session_id, func.sum(LLMCall.cost_usd))
                .where(col(LLMCall.session_id).in_(ids))
                .group_by(col(LLMCall.session_id))
            ).all()
        )

    summaries = []
    for row in rows:
        config = SessionConfig.model_validate_json(row.config_json)
        evaluation = reports.get(row.id)
        summaries.append(
            SessionSummary(
                session_id=row.id,
                application_id=row.application_id,
                company=row.company,
                role=row.role,
                started_at=row.started_at,
                ended_at=row.ended_at,
                status=row.status,
                interview_type=config.interview_type.value,
                difficulty=config.difficulty.value,
                mode=config.mode.value,
                prompt_variant=config.prompt_variant.value,
                # Same counting rule as the live interview, so the numbers match what the user saw.
                main_questions_asked=compute_progress(turns[row.id]).main_asked,
                cost_usd=float(costs.get(row.id) or 0.0),
                overall=evaluation.overall if evaluation else None,
                band=evaluation.band if evaluation else None,
                has_report=evaluation is not None,
            )
        )
    return summaries


def load_report(engine: Engine, user_id: int, session_id: int) -> Report | None:
    """The stored report of one session, read straight from the DB (History never calls the judge)."""
    with session_scope(engine) as s:
        row = s.exec(
            select(Evaluation).where(Evaluation.session_id == session_id, Evaluation.user_id == user_id)
        ).first()
    return Report.model_validate_json(row.report_json) if row else None


def _reports_oldest_first(engine: Engine, user_id: int, application_id: int) -> list[tuple[datetime, Report]]:
    with session_scope(engine) as s:
        rows = s.exec(
            select(InterviewSession.started_at, Evaluation.report_json)
            .join(Evaluation, col(Evaluation.session_id) == col(InterviewSession.id))
            .where(
                InterviewSession.user_id == user_id,
                Evaluation.user_id == user_id,
                InterviewSession.application_id == application_id,
                col(InterviewSession.status).not_in(HIDDEN_STATUSES),
            )
            .order_by(col(InterviewSession.started_at), col(InterviewSession.id))
        ).all()
    return [(started_at, Report.model_validate_json(raw)) for started_at, raw in rows]


def progress(engine: Engine, user_id: int, application_id: int, rubric_path: Path | None = None) -> Progress:
    """How one application's interviews developed over time."""
    rubric = load_rubric(rubric_path or get_settings().rubric_path)
    reports = _reports_oldest_first(engine, user_id, application_id)

    trend = [(started_at, r.overall) for started_at, r in reports if r.overall is not None]

    # Item means use the raw 1-5 scores, not the weighted 0-100 exchange scores: a weight says how
    # much an item counts for one question type, not how good the candidate is at that skill.
    scores: dict[str, list[int]] = defaultdict(list)
    for _, report in reports:
        for exchange in report.exchanges:
            for item in exchange.items:
                if item.score is not None and item.item in rubric.exchange_items:
                    scores[item.item].append(item.score)
    order = list(rubric.exchange_items)
    item_means = sorted(
        (
            ItemMean(
                item=item_id,
                name=rubric.exchange_items[item_id]["name"],
                mean=sum(values) / len(values),
                count=len(values),
            )
            for item_id, values in scores.items()
        ),
        # Ties keep rubric order (A1 before A2) so the table doesn't shuffle between reruns.
        key=lambda m: (m.mean, order.index(m.item)),
    )

    # Requirement texts are matched case-insensitively: the judge copies them from the same plan,
    # but may capitalise differently between runs. Reports are oldest first, so the last one wins.
    requirements: dict[str, RequirementHistory] = {}
    for _, report in reports:
        for req in report.requirements:
            key = req.requirement.strip().casefold()
            entry = requirements.get(key)
            if entry is None:
                entry = requirements[key] = RequirementHistory(
                    requirement=req.requirement.strip(),
                    priority=req.priority,
                    latest_level=req.level,
                    level_counts={},
                )
            entry.latest_level = req.level
            entry.level_counts[req.level] = entry.level_counts.get(req.level, 0) + 1

    # Count each area once per report: one report naming "Quantify results" twice is not a trend.
    area_counts: Counter[str] = Counter()
    area_names: dict[str, str] = {}
    for _, report in reports:
        seen = {imp.area.strip().casefold(): imp.area.strip() for imp in report.improvements}
        area_counts.update(seen.keys())
        area_names.update(seen)  # latest wording wins
    recurring = [
        RecurringImprovement(area=area_names[key], count=n)
        for key, n in area_counts.most_common()
        if n >= RECURRING_MIN_REPORTS
    ]

    return Progress(
        trend=trend,
        item_means=item_means,
        requirements=list(requirements.values()),
        recurring_improvements=recurring,
    )


def delete_session(engine: Engine, user_id: int, session_id: int) -> bool:
    """Delete one interview. The database cascades to its turns and evaluation.

    LLMCall rows are kept on purpose: they have no foreign key, and they are the spend history
    (the Settings page total must not drop because an old interview was tidied away).
    """
    with session_scope(engine) as s:
        row = s.exec(
            select(InterviewSession).where(
                InterviewSession.id == session_id, InterviewSession.user_id == user_id
            )
        ).first()
        if row is None:
            return False
        s.delete(row)
    return True
