import pytest

from interview_app.db import LLMCall, User, session_scope
from interview_app.usage import usage_summary


def add_user(engine, name: str) -> int:
    with session_scope(engine) as s:
        user = User(username=name, password_hash="h", totp_secret_enc="e")
        s.add(user)
        s.flush()
        return user.id


def add_call(engine, user_id, role, model, cost, pt=10, ct=5):
    with session_scope(engine) as s:
        s.add(
            LLMCall(
                user_id=user_id, role=role, model=model, cost_usd=cost, prompt_tokens=pt, completion_tokens=ct
            )
        )


def test_empty_usage(engine):
    summary = usage_summary(engine, add_user(engine, "alex"))
    assert summary.total_cost_usd == 0 and summary.total_calls == 0
    assert summary.by_role == [] and summary.by_model == []


def test_usage_is_aggregated_by_role_and_model_for_one_user_only(engine):
    alex, sam = add_user(engine, "alex"), add_user(engine, "sam")
    add_call(engine, alex, "interviewer", "openai/gpt-5-mini", 0.01)
    add_call(engine, alex, "interviewer", "openai/gpt-5-mini", 0.02)
    add_call(engine, alex, "planner", "openai/gpt-5-mini", 0.005)
    add_call(engine, alex, "judge", "anthropic/claude-haiku-4.5", 0.04)
    add_call(engine, sam, "interviewer", "openai/gpt-5-mini", 5.0)  # someone else's spend

    summary = usage_summary(engine, alex)
    assert summary.total_cost_usd == pytest.approx(0.075)
    assert summary.total_calls == 4

    roles = {r.name: r for r in summary.by_role}
    assert roles["interviewer"].calls == 2
    assert roles["interviewer"].cost_usd == pytest.approx(0.03)
    assert roles["interviewer"].prompt_tokens == 20 and roles["interviewer"].completion_tokens == 10
    assert summary.by_role[0].name == "judge"  # most expensive first

    models = {r.name: r for r in summary.by_model}
    assert models["openai/gpt-5-mini"].calls == 3
    assert models["openai/gpt-5-mini"].cost_usd == pytest.approx(0.035)
    assert models["anthropic/claude-haiku-4.5"].cost_usd == pytest.approx(0.04)
