import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from interview_app.db import Application, LLMCall, User, init_db, make_engine, session_scope
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
    # An application for a user that doesn't exist must be rejected (PRAGMA foreign_keys=ON).
    with pytest.raises(IntegrityError), session_scope(engine) as s:
        s.add(Application(user_id=999, company="Acme", role="Engineer"))


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


def test_new_database_file_is_owner_only(tmp_path):
    import stat

    path = tmp_path / "data" / "app.db"
    engine = make_engine(f"sqlite:///{path}")
    init_db(engine)
    add_user(engine)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_world_readable_database_file_is_tightened(tmp_path, caplog):
    import stat

    path = tmp_path / "app.db"
    path.touch()
    path.chmod(0o644)
    make_engine(f"sqlite:///{path}")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "readable by other users" in caplog.text
    caplog.clear()
    make_engine(f"sqlite:///{path}")  # already private: no second warning
    assert "readable by other users" not in caplog.text


def test_every_connection_uses_secure_delete(tmp_path):
    from sqlalchemy import text

    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA secure_delete")).scalar() == 1
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_connect_hook_turns_secure_delete_on():
    # Some SQLite builds already default to secure_delete=1, so start from OFF to prove the hook sets it.
    import sqlite3

    from interview_app.db import _sqlite_pragmas

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA secure_delete=OFF")
    _sqlite_pragmas(conn, None)
    assert conn.execute("PRAGMA secure_delete").fetchone() == (1,)


def test_deleted_text_does_not_linger_in_the_file(tmp_path):
    path = tmp_path / "app.db"
    engine = make_engine(f"sqlite:///{path}")
    init_db(engine)
    user_id = add_user(engine)
    marker = "FICTIONAL-CV-MARKER-" * 50
    with session_scope(engine) as s:
        app = Application(user_id=user_id, company=marker, role="Engineer")
        s.add(app)
    with session_scope(engine) as s:
        s.delete(s.exec(select(Application)).one())
    engine.dispose()
    assert b"FICTIONAL-CV-MARKER-" not in path.read_bytes()
