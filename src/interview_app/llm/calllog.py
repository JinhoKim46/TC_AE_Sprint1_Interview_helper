"""Turns a CallRecord into an LLMCall row, so every model call shows up in cost reports."""

from sqlalchemy.engine import Engine

from interview_app.db import LLMCall, session_scope
from interview_app.llm.client import CallRecord, Recorder


def make_db_recorder(engine: Engine, user_id: int | None = None, session_id: int | None = None) -> Recorder:
    """Build a recorder bound to one user (and optionally one interview session)."""

    def record(call: CallRecord) -> None:
        with session_scope(engine) as s:
            s.add(
                LLMCall(
                    user_id=user_id,
                    session_id=session_id,
                    role=call.role,
                    model=call.model,
                    prompt_tokens=call.prompt_tokens,
                    completion_tokens=call.completion_tokens,
                    cost_usd=call.cost_usd,
                    latency_s=call.latency_s,
                    ok=call.ok,
                    error=call.error,
                )
            )

    return record
