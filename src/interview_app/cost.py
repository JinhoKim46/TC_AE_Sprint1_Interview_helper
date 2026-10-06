"""Where the money goes: model spend per application, over time and by purpose, for the Dashboard.

Read from the LLMCall log like the Settings usage table (usage.py), and like it the database does the
adding up (SUM ... GROUP BY): the log grows with every turn, and nothing here needs the single rows. Every
call counts in the total, over time and by purpose; only calls tied to an interview count for a company,
so a guard check on an uploaded document (no session) is part of the total but of no company row.
"""

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import case
from sqlalchemy.engine import Engine
from sqlmodel import col, func, select

from interview_app.db import InterviewSession, LLMCall, session_scope

OTHER = "Other"
# Call-log role -> plain-words purpose. A display label map, the one place it lives; any role not listed
# (the lab's judge and candidate simulator, Jev calls outside the guard) is shown as Other.
PURPOSES: dict[str, str] = {
    "interviewer": "Interviewer",
    "planner": "Planning",
    "judge": "Report",
    "live_score": "Live scoring",
    "tts": "Voice",
    "stt": "Transcription",
    "guard": "Guard",
}
# The spend-over-time chart stacks four groups at most: the theme has four colours that stay apart for
# colour-blind readers, and eight stacked colours could not be told apart. Each purpose has a fixed group,
# so a colour always means the same thing. The tables keep every purpose.
CHART_GROUPS: dict[str, str] = {
    "Interviewer": "Interview",
    "Planning": "Interview",
    "Report": "Report and scoring",
    "Live scoring": "Report and scoring",
    "Voice": "Voice",
    "Transcription": "Voice",
    "Guard": "Guard and other",
    OTHER: "Guard and other",
}
CHART_GROUP_ORDER: list[str] = list(dict.fromkeys(CHART_GROUPS.values()))
# Past this span the daily bars get too thin to read, so they become weekly.
DAILY_SPAN_DAYS = 60


def purpose(role: str) -> str:
    return PURPOSES.get(role, OTHER)


def chart_group(purpose_name: str) -> str:
    return CHART_GROUPS.get(purpose_name, CHART_GROUPS[OTHER])


class ApplicationCost(BaseModel):
    application_id: int
    cost_usd: float
    interviews: int  # interviews of this application that made at least one model call
    average_usd: float


class SpendBucket(BaseModel):
    start: date  # the day, or the Monday that starts the week
    purpose: str
    cost_usd: float


class PurposeCost(BaseModel):
    purpose: str
    calls: int
    cost_usd: float


class CostOverview(BaseModel):
    total_usd: float  # every call of the user: the same number as the Settings usage table
    unassigned_usd: float  # calls tied to no interview (document checks, lab runs)
    interviews: int  # interviews with spend, over all applications
    average_per_interview_usd: float | None
    by_application: dict[int, ApplicationCost]
    bucket: Literal["day", "week"]
    over_time: list[SpendBucket]  # oldest first
    by_purpose: list[PurposeCost]  # most expensive first


def _purpose_column():
    """The purpose as a SQL expression, so the database can group by it (two unknown roles merge into
    one Other row instead of two)."""
    return case(PURPOSES, value=LLMCall.role, else_=OTHER)


def cost_overview(engine: Engine, user_id: int) -> CostOverview:
    cost = func.coalesce(func.sum(LLMCall.cost_usd), 0.0)
    mine = LLMCall.user_id == user_id
    purpose_col = _purpose_column()
    with session_scope(engine) as s:
        # An inner join: a call whose session no longer exists (or never did) belongs to no company.
        per_app = s.exec(
            select(InterviewSession.application_id, func.count(func.distinct(LLMCall.session_id)), cost)
            .join(InterviewSession, col(InterviewSession.id) == col(LLMCall.session_id))
            .where(mine, InterviewSession.user_id == user_id)
            .group_by(InterviewSession.application_id)
        ).all()
        per_purpose = s.exec(
            select(purpose_col, func.count(), cost).where(mine).group_by(purpose_col).order_by(cost.desc())
        ).all()
        first, last = s.exec(
            select(func.min(LLMCall.created_at), func.max(LLMCall.created_at)).where(mine)
        ).one()
        weekly = first is not None and (last - first) > timedelta(days=DAILY_SPAN_DAYS)
        # SQLite date modifiers: go back six days, then forward to the next Monday, which lands on the
        # Monday on or before the call's day.
        start = (
            func.date(LLMCall.created_at, "-6 days", "weekday 1") if weekly else func.date(LLMCall.created_at)
        )
        per_bucket = s.exec(
            select(start, purpose_col, cost).where(mine).group_by(start, purpose_col).order_by(start)
        ).all()

    by_application = {
        app_id: ApplicationCost(
            application_id=app_id, cost_usd=float(c), interviews=int(n), average_usd=float(c) / int(n)
        )
        for app_id, n, c in per_app
    }
    by_purpose = [PurposeCost(purpose=p, calls=int(n), cost_usd=float(c)) for p, n, c in per_purpose]
    total = sum(p.cost_usd for p in by_purpose)
    assigned = sum(a.cost_usd for a in by_application.values())
    interviews = sum(a.interviews for a in by_application.values())
    return CostOverview(
        total_usd=total,
        # Rounding noise from float sums must not show as "-$0.0000".
        unassigned_usd=max(total - assigned, 0.0),
        interviews=interviews,
        average_per_interview_usd=assigned / interviews if interviews else None,
        by_application=by_application,
        bucket="week" if weekly else "day",
        over_time=[
            SpendBucket(start=date.fromisoformat(day), purpose=p, cost_usd=float(c))
            for day, p, c in per_bucket
        ],
        by_purpose=by_purpose,
    )
