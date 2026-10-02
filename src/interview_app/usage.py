"""Spend and token usage per user, from the LLMCall log (course task M3).

The database does the aggregation (SUM ... GROUP BY) rather than Python: the call log grows with
every turn, and loading thousands of rows just to add them up would be wasteful.
"""

from dataclasses import dataclass

from sqlalchemy.engine import Engine
from sqlmodel import col, func, select

from interview_app.db import LLMCall, session_scope


@dataclass
class UsageRow:
    name: str  # a role (interviewer, judge, jev...) or a model id
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


@dataclass
class UsageSummary:
    total_cost_usd: float
    total_calls: int
    by_role: list[UsageRow]  # most expensive first
    by_model: list[UsageRow]


def _grouped(engine: Engine, user_id: int, column) -> list[UsageRow]:
    cost = func.coalesce(func.sum(LLMCall.cost_usd), 0.0)
    query = (
        select(
            column,
            func.count(),
            func.coalesce(func.sum(LLMCall.prompt_tokens), 0),
            func.coalesce(func.sum(LLMCall.completion_tokens), 0),
            cost,
        )
        .where(LLMCall.user_id == user_id)
        .group_by(column)
        .order_by(cost.desc(), col(column))
    )
    with session_scope(engine) as s:
        rows = s.exec(query).all()
    return [UsageRow(name, int(n), int(pt), int(ct), float(c)) for name, n, pt, ct, c in rows]


def usage_summary(engine: Engine, user_id: int) -> UsageSummary:
    """Totals plus breakdowns by role and by model, for one user only."""
    by_role = _grouped(engine, user_id, LLMCall.role)
    by_model = _grouped(engine, user_id, LLMCall.model)
    return UsageSummary(
        total_cost_usd=sum(r.cost_usd for r in by_role),
        total_calls=sum(r.calls for r in by_role),
        by_role=by_role,
        by_model=by_model,
    )
