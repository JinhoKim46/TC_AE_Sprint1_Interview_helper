import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from interview_app.db import LLMCall, RecoveryCode, User, make_engine, session_scope
from interview_app.llm.calllog import make_db_recorder
from interview_app.llm.client import CallRecord


def add_user(engine, name="alex") -> int:
    with session_scope(engine) as s:
        user = User(username=name, password_hash="h", totp_secret_enc="e")
        s.add(user)
        s.flush()
        return user.id


def test_usernames_are_unique(engine):
    add_user(engine)
    with pytest.raises(IntegrityError):
        add_user(engine)


def test_foreign_keys_are_enforced(engine):
    # A recovery code for a user that doesn't exist must be rejected (PRAGMA foreign_keys=ON).
    with pytest.raises(IntegrityError), session_scope(engine) as s:
        s.add(RecoveryCode(user_id=999, code_hash="x"))


def test_session_scope_rolls_back_on_error(engine):
    with pytest.raises(RuntimeError), session_scope(engine) as s:
        s.add(User(username="temp", password_hash="h", totp_secret_enc="e"))
        raise RuntimeError("fail mid-transaction")
    with session_scope(engine) as s:
        assert s.exec(select(User)).all() == []


def test_db_recorder_writes_llm_call_rows(engine):
    user_id = add_user(engine)
    record = make_db_recorder(engine, user_id=user_id, session_id=7)
    record(
        CallRecord(
            role="judge", model="m", prompt_tokens=3, completion_tokens=4, cost_usd=0.01, latency_s=1.5
        )
    )

    with session_scope(engine) as s:
        row = s.exec(select(LLMCall)).one()
    assert (row.user_id, row.session_id, row.role, row.cost_usd, row.ok) == (user_id, 7, "judge", 0.01, True)


def test_make_engine_creates_parent_folder(tmp_path):
    db_file = tmp_path / "nested" / "app.db"
    make_engine(f"sqlite:///{db_file}")
    assert db_file.parent.is_dir()
