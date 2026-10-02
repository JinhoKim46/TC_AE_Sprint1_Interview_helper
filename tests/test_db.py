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


# The `turn` table as it was before coaching mode added `superseded` and `live_json`.
OLD_TURN_TABLE = """
CREATE TABLE turn (
    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, user_id INTEGER NOT NULL, idx INTEGER NOT NULL,
    speaker VARCHAR NOT NULL, text VARCHAR NOT NULL, stage VARCHAR, question_id VARCHAR,
    is_followup BOOLEAN NOT NULL, is_final BOOLEAN NOT NULL, private_json VARCHAR,
    created_at DATETIME NOT NULL
)
"""


def test_init_db_adds_missing_columns_to_an_old_database(tmp_path):
    from sqlalchemy import inspect, text

    from interview_app.db import Turn, init_db

    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text(OLD_TURN_TABLE))
        conn.execute(
            text(
                "INSERT INTO turn (session_id, user_id, idx, speaker, text, is_followup, is_final, "
                "created_at) VALUES (1, 1, 0, 'candidate', 'old answer', 0, 0, '2026-10-01 10:00:00')"
            )
        )

    init_db(engine)
    init_db(engine)  # running it again must be a no-op, not a "duplicate column" error

    columns = {c["name"] for c in inspect(engine).get_columns("turn")}
    assert {"superseded", "live_json"} <= columns
    with session_scope(engine) as s:
        old = s.exec(select(Turn)).one()
    assert old.text == "old answer" and old.superseded is False and old.live_json is None
