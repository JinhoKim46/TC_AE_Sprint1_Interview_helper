"""Database tables and session helpers (SQLite via SQLModel).

Every row a person owns carries a `user_id`. The app has one user today, but adding
more users later then needs no migration of existing data.

New tables are added by the feature that needs them (applications, sessions, turns...).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import Column, ForeignKey, Integer, event
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, create_engine


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
    """Create any missing tables. (No migrations yet: tables are only ever added.)"""
    SQLModel.metadata.create_all(engine)


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
