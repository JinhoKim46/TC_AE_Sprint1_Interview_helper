"""Store and load applications (one job + its documents).

Every function takes `user_id` and filters on it, so one user can never read, change or delete
another user's rows — even if the UI passes a wrong id. "Not yours" and "doesn't exist" look
the same to the caller on purpose: it doesn't leak which ids exist.

Callers get plain pydantic objects back, not live SQLModel rows, so nothing depends on an open
database session after the function returns.
"""

from collections import Counter
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlmodel import col, select

from interview_app.config import Limits, get_settings
from interview_app.db import Application, Document, session_scope, utcnow
from interview_app.ingest import (
    KIND_LABELS,
    REQUIRED_KINDS,
    DocKind,
    DocSource,
    IngestError,
    clean_text,
    validate_document,
)


class ApplicationNotFoundError(LookupError):
    """No application with this id belongs to this user."""


class DocumentIn(BaseModel):
    kind: DocKind
    source: DocSource
    text: str
    filename: str | None = None


class DocumentOut(BaseModel):
    kind: DocKind
    source: DocSource
    filename: str | None
    text: str
    char_count: int
    created_at: datetime


class ApplicationSummary(BaseModel):
    id: int
    company: str
    role: str
    kinds: list[DocKind]  # which documents are present, in DocKind order
    updated_at: datetime


class ApplicationDetail(BaseModel):
    id: int
    company: str
    role: str
    created_at: datetime
    updated_at: datetime
    documents: dict[DocKind, DocumentOut]


def _limits(limits: Limits | None) -> Limits:
    # Tests pass their own limits; the app uses the configured ones.
    return limits if limits is not None else get_settings().limits


def _clean_label(value: str, what: str) -> str:
    value = " ".join(value.split())  # also collapses inner runs of whitespace / newlines
    if not value:
        raise IngestError(f"Please enter the {what}.")
    return value


def _prepare(doc: DocumentIn, limits: Limits) -> str:
    """Clean then validate. Validation runs on the cleaned text, because that is what gets stored."""
    text = clean_text(doc.text)
    validate_document(doc.kind, text, limits)
    return text


def _get_owned(session, user_id: int, application_id: int) -> Application | None:
    return session.exec(
        select(Application).where(Application.id == application_id, Application.user_id == user_id)
    ).first()


def create_application(
    engine: Engine,
    user_id: int,
    company: str,
    role: str,
    documents: list[DocumentIn],
    limits: Limits | None = None,
) -> int:
    """Validate everything first, then save in one transaction, so a bad document never leaves
    a half-created application behind. Returns the new application id."""
    limits = _limits(limits)
    company = _clean_label(company, "company name")
    role = _clean_label(role, "role")

    counts = Counter(doc.kind for doc in documents)
    duplicates = [KIND_LABELS[k] for k, n in counts.items() if n > 1]
    if duplicates:
        raise IngestError(f"Only one document of each kind is allowed (duplicate: {', '.join(duplicates)}).")
    missing = [KIND_LABELS[k] for k in DocKind if k in REQUIRED_KINDS and k not in counts]
    if missing:
        raise IngestError(f"Missing required document(s): {', '.join(missing)}.")

    cleaned = [(doc, _prepare(doc, limits)) for doc in documents]

    with session_scope(engine) as s:
        app = Application(user_id=user_id, company=company, role=role)
        s.add(app)
        s.flush()  # assigns app.id, needed for the documents' foreign key
        for doc, text in cleaned:
            s.add(
                Document(
                    application_id=app.id,
                    user_id=user_id,
                    kind=doc.kind,
                    source=doc.source,
                    filename=doc.filename,
                    text=text,
                    char_count=len(text),
                )
            )
        return app.id


def list_applications(engine: Engine, user_id: int) -> list[ApplicationSummary]:
    """All of the user's applications, most recently changed first."""
    with session_scope(engine) as s:
        apps = s.exec(
            select(Application)
            .where(Application.user_id == user_id)
            # id breaks ties when two rows share a timestamp (fast tests, clock resolution).
            .order_by(col(Application.updated_at).desc(), col(Application.id).desc())
        ).all()
        # One query for all document kinds instead of one query per application.
        rows = s.exec(select(Document.application_id, Document.kind).where(Document.user_id == user_id)).all()

    kinds_by_app: dict[int, set[str]] = {}
    for application_id, kind in rows:
        kinds_by_app.setdefault(application_id, set()).add(kind)
    return [
        ApplicationSummary(
            id=a.id,
            company=a.company,
            role=a.role,
            kinds=[k for k in DocKind if k in kinds_by_app.get(a.id, set())],
            updated_at=a.updated_at,
        )
        for a in apps
    ]


def get_application(engine: Engine, user_id: int, application_id: int) -> ApplicationDetail | None:
    """The application with all its documents, or None if it doesn't exist or isn't this user's."""
    with session_scope(engine) as s:
        app = _get_owned(s, user_id, application_id)
        if app is None:
            return None
        docs = s.exec(
            select(Document).where(Document.application_id == app.id, Document.user_id == user_id)
        ).all()

    return ApplicationDetail(
        id=app.id,
        company=app.company,
        role=app.role,
        created_at=app.created_at,
        updated_at=app.updated_at,
        documents={
            DocKind(d.kind): DocumentOut(
                kind=DocKind(d.kind),
                source=DocSource(d.source),
                filename=d.filename,
                text=d.text,
                char_count=d.char_count,
                created_at=d.created_at,
            )
            for d in docs
        },
    )


def update_document(
    engine: Engine,
    user_id: int,
    application_id: int,
    kind: DocKind,
    text: str,
    source: DocSource = DocSource.PASTE,
    filename: str | None = None,
    limits: Limits | None = None,
) -> list[str]:
    """Add a document of `kind`, or replace the existing one. Returns validation warnings.

    Raises ApplicationNotFoundError if the application isn't this user's, IngestError if the
    text is unusable. Replacing (instead of keeping versions) keeps the model simple; past
    interview sessions will store what they used themselves.
    """
    limits = _limits(limits)
    kind = DocKind(kind)
    cleaned = clean_text(text)
    warnings = validate_document(kind, cleaned, limits)

    with session_scope(engine) as s:
        app = _get_owned(s, user_id, application_id)
        if app is None:
            raise ApplicationNotFoundError(f"Application {application_id} not found.")
        doc = s.exec(select(Document).where(Document.application_id == app.id, Document.kind == kind)).first()
        if doc is None:
            doc = Document(
                application_id=app.id, user_id=user_id, kind=kind, source=source, text="", char_count=0
            )
        doc.source = source
        doc.filename = filename
        doc.text = cleaned
        doc.char_count = len(cleaned)
        doc.created_at = utcnow()  # "when this text was provided", so a replacement gets a new time
        app.updated_at = utcnow()
        s.add(doc)
        s.add(app)
    return warnings


def delete_application(engine: Engine, user_id: int, application_id: int) -> bool:
    """Delete the application; its documents go with it via ON DELETE CASCADE.
    Returns False if there was nothing (of this user's) to delete."""
    with session_scope(engine) as s:
        app = _get_owned(s, user_id, application_id)
        if app is None:
            return False
        s.delete(app)
    return True
