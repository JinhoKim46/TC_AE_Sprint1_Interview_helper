"""Database tables and session helpers (SQLite via SQLModel).

Every row a person owns carries a `user_id`. The app has one user today, but adding
more users later then needs no migration of existing data.

New tables are added by the feature that needs them (applications, sessions, turns...).
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import Column, ForeignKey, Integer, event, text
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, create_engine

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    totp_secret_enc: str  # Fernet-encrypted base32 secret, never stored in plain text
    totp_confirmed: bool = False  # True once the user proved their authenticator works
    failed_attempts: int = 0
    locked_until: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class RecoveryCode(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    code_hash: str  # hashed like a password: a leaked DB must not reveal usable codes
    used_at: datetime | None = None


class LLMCall(SQLModel, table=True):
    """One row per model call: the source for cost display, the dashboard and debugging."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, foreign_key="user.id", index=True)
    session_id: int | None = Field(default=None, index=True)
    role: str  # interviewer, planner, judge, jev, guard, image ...
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    ok: bool = True
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Application(SQLModel, table=True):
    """One job the user is interviewing for. It owns its own copies of the documents, so
    editing a CV for one application never changes another."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    company: str
    role: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Document(SQLModel, table=True):
    """The cleaned text of one document (JD, CV, cover letter, company notes) of an application."""

    id: int | None = Field(default=None, primary_key=True)
    # ondelete="CASCADE" lets the database itself remove documents when their application is
    # deleted. A plain `foreign_key=` can't express that, so the column is built explicitly.
    application_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    user_id: int = Field(foreign_key="user.id", index=True)
    kind: str  # an ingest.DocKind value; stored as text so adding a kind needs no migration
    source: str  # an ingest.DocSource value: pdf, paste, url
    filename: str | None = None
    text: str
    char_count: int
    created_at: datetime = Field(default_factory=utcnow)


@event.listens_for(Engine, "connect")
def _sqlite_foreign_keys(dbapi_connection, _record) -> None:
    # SQLite ignores foreign keys unless asked, so "delete application -> delete its
    # sessions" would silently leave orphans without this.
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
        from pathlib import Path

        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: Streamlit serves each rerun from a different thread.
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def init_db(engine: Engine) -> None:
    """Create any missing tables, then add any missing columns to existing ones."""
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)


def _sql_literal(value) -> str:
    # SQLite stores booleans as 0/1. Only simple literals are supported; anything fancier
    # (a function default like utcnow) can't be expressed in ALTER TABLE ... DEFAULT.
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(f"unsupported default {value!r}")


def _add_missing_columns(engine: Engine) -> None:
    """A tiny migration step: `ALTER TABLE ... ADD COLUMN` for model columns the database lacks.

    Why: `create_all` only creates *missing tables*; it never changes a table that already exists.
    So a field added to a model (e.g. `Turn.superseded`) would make every query fail on an existing
    `data/app.db` with "no such column". This handles the common, safe case — a new nullable column,
    or one with a simple literal default — which is all this app has needed. Renames, type changes
    or dropped columns would need a real migration tool (Alembic); we don't use one yet.
    SQLite only (the only database this app uses).
    """
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            rows = conn.execute(text(f'PRAGMA table_info("{table.name}")')).all()
            if not rows:
                continue  # table doesn't exist (create_all just ran, so this shouldn't happen)
            existing = {row[1] for row in rows}  # row = (cid, name, type, notnull, default, pk)
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" '
                ddl += column.type.compile(dialect=engine.dialect)
                default = column.default.arg if column.default is not None else None
                if default is not None and not callable(default):
                    # Existing rows get the default, so NOT NULL is safe here.
                    ddl += f" NOT NULL DEFAULT {_sql_literal(default)}"
                elif not column.nullable:
                    raise RuntimeError(
                        f"Cannot add required column {table.name}.{column.name} without a default; "
                        "make it nullable or give it a literal default."
                    )
                log.info("Migrating database: %s", ddl)
                conn.execute(text(ddl))


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """`with session_scope(engine) as s:` commits on success and rolls back on error."""
    with Session(engine, expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


class InterviewSession(SQLModel, table=True):
    """One mock interview. It snapshots the documents and settings it used, so later edits to the
    application don't change what an old transcript was based on."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    application_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    company: str
    role: str
    config_json: str  # SessionConfig
    documents_json: str  # {kind: text} snapshot
    plan_json: str | None = None  # InterviewPlan, for variants that use one
    status: str = "preparing"  # preparing -> active -> finished / ended_early
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: datetime | None = None


class Turn(SQLModel, table=True):
    """One message in an interview transcript."""

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("interviewsession.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    user_id: int = Field(foreign_key="user.id", index=True)
    idx: int  # 0, 1, 2 ... in conversation order
    speaker: str  # "interviewer" or "candidate"
    text: str
    stage: str | None = None
    question_id: str | None = None
    is_followup: bool = False
    is_final: bool = False
    private_json: str | None = None  # P3 notes / P5 draft+critique: kept for analysis, never shown
    # Coaching mode: an earlier attempt the candidate chose to retry. Kept (history, analysis) but
    # excluded from every transcript view, the interviewer's messages and the final evaluation.
    superseded: bool = False
    live_json: str | None = None  # coaching mode: evaluation.live.LiveFeedback for a candidate answer
    created_at: datetime = Field(default_factory=utcnow)


class UserPreferences(SQLModel, table=True):
    """Saved Settings-page choices, one row per user (see preferences.py).

    Stored as one JSON text column instead of a column per setting: settings change often while
    the app grows, and a JSON blob needs no schema migration when one is added or renamed.
    """

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True, index=True)
    prefs_json: str
    updated_at: datetime = Field(default_factory=utcnow)


class Evaluation(SQLModel, table=True):
    """The feedback report for one interview (at most one per session)."""

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("interviewsession.id", ondelete="CASCADE"), nullable=False, unique=True
        )
    )
    user_id: int = Field(foreign_key="user.id", index=True)
    judge_model: str
    overall: float | None = None
    band: str | None = None
    report_json: str
    created_at: datetime = Field(default_factory=utcnow)
