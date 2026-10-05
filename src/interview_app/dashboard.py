"""The Dashboard: how practice is going across all applications, in one read-only overview.

Computed in code from stored rows, with no model call, so opening the page costs nothing. It reuses the
History module's rules (which sessions count towards scores, how trend points and skill means are made)
and the journey's score summary, so a number shown here agrees with the same number on History and Home.
"""

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlmodel import col, select

from interview_app.applications import list_applications
from interview_app.config import get_settings
from interview_app.db import Turn, session_scope
from interview_app.evaluation.rubric import load_rubric
from interview_app.history import (
    ItemMean,
    SessionSummary,
    StoredReport,
    counts_towards_scores,
    item_means,
    list_sessions,
    stored_reports,
    trend_points,
)
from interview_app.journey import score_summary


class Kpis(BaseModel):
    interviews: int  # every visible session, as History counts them (an interview in progress too)
    practised_seconds: float  # sum over sessions of first-to-last-turn time (Quick practice included)
    scored: int  # sessions that count towards scores and have one
    average_score: float | None  # over the counted sessions only (Standard and Full)
    best_score: float | None
    cost_usd: float  # model spend of the visible interviews


class CompanyPoint(BaseModel):
    """One counted score on the cross-application chart."""

    application_id: int
    label: str  # the company; "company — role" when two applications share a company name
    started_at: datetime
    score: float


class ApplicationRow(BaseModel):
    application_id: int
    label: str
    company: str
    role: str
    interviews: int
    latest: float | None  # latest / best / change follow score_summary: counted sessions only
    best: float | None
    change: float | None  # latest minus the previous counted interview
    last_practised: datetime | None  # the newest session of any length
    weakest_skill: str | None  # the plain-words name of its weakest rubric item


class Dashboard(BaseModel):
    applications: int
    kpis: Kpis
    trend: list[CompanyPoint]  # oldest first
    rows: list[ApplicationRow]  # most recently practised first, never-practised last
    item_means: list[ItemMean]  # across every scored session, weakest first


def _labels(apps) -> dict[int, str]:
    # Case-insensitive, because "Fjordlight" and "fjordlight" would read as one line on the chart.
    counts = Counter(a.company.strip().casefold() for a in apps)
    return {
        a.id: f"{a.company} — {a.role}" if counts[a.company.strip().casefold()] > 1 else a.company
        for a in apps
    }


def _practised_seconds(engine: Engine, user_id: int, sessions: list[SessionSummary]) -> float:
    """First-to-last-turn time per session, summed. Turn times (not started/ended) are used because an
    interview left open in a tab, or one still preparing, would otherwise count hours nobody practised."""
    ids = [s.session_id for s in sessions]
    if not ids:
        return 0.0
    spans: dict[int, list[datetime]] = defaultdict(list)
    with session_scope(engine) as s:
        for session_id, created_at in s.exec(
            select(Turn.session_id, Turn.created_at).where(
                col(Turn.session_id).in_(ids), Turn.user_id == user_id
            )
        ).all():
            spans[session_id].append(created_at)
    return sum((max(times) - min(times)).total_seconds() for times in spans.values())


def dashboard(engine: Engine, user_id: int, rubric_path: Path | None = None) -> Dashboard:
    """Everything the Dashboard page shows, computed from stored sessions and reports."""
    rubric = load_rubric(rubric_path or get_settings().rubric_path)
    apps = list_applications(engine, user_id)
    sessions = list_sessions(engine, user_id)  # newest first
    reports = stored_reports(engine, user_id)  # oldest first
    labels = _labels(apps)

    counted = [s.overall for s in sessions if s.overall is not None and counts_towards_scores(s.length)]
    kpis = Kpis(
        interviews=len(sessions),
        practised_seconds=_practised_seconds(engine, user_id, sessions),
        scored=len(counted),
        average_score=sum(counted) / len(counted) if counted else None,
        best_score=max(counted) if counted else None,
        cost_usd=sum(s.cost_usd for s in sessions),
    )

    by_app_reports: dict[int, list[StoredReport]] = defaultdict(list)
    for r in reports:
        by_app_reports[r.application_id].append(r)
    by_app_sessions: dict[int, list[SessionSummary]] = defaultdict(list)
    for s in sessions:
        by_app_sessions[s.application_id].append(s)

    # The chart draws the progress line only: practice points are left out here, as in latest / best.
    trend = [
        CompanyPoint(
            application_id=r.application_id,
            label=labels[r.application_id],
            started_at=p.started_at,
            score=p.score,
        )
        for r in reports
        if r.application_id in labels
        for p in trend_points([r])
        if p.counted
    ]

    rows = []
    for app in apps:
        app_sessions = by_app_sessions.get(app.id, [])
        stats = score_summary(app_sessions)
        weakest = item_means(by_app_reports.get(app.id, []), rubric)
        rows.append(
            ApplicationRow(
                application_id=app.id,
                label=labels[app.id],
                company=app.company,
                role=app.role,
                interviews=len(app_sessions),
                latest=stats.latest,
                best=stats.best,
                change=stats.change,
                last_practised=max((s.started_at for s in app_sessions), default=None),
                weakest_skill=weakest[0].name if weakest else None,
            )
        )
    # Most recently practised first: the applications in play lead, the untouched ones sit at the end.
    rows.sort(key=lambda r: (r.last_practised is not None, r.last_practised or datetime.min), reverse=True)

    return Dashboard(
        applications=len(apps),
        kpis=kpis,
        trend=trend,
        rows=rows,
        item_means=item_means(reports, rubric),
    )
