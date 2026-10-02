from pathlib import Path

import pytest
from sqlmodel import select

from interview_app.applications import (
    ApplicationNotFoundError,
    DocumentIn,
    create_application,
    delete_application,
    get_application,
    list_applications,
    update_document,
)
from interview_app.config import PROJECT_ROOT, Limits
from interview_app.db import Document, User, session_scope
from interview_app.ingest import DocKind, DocSource, IngestError

LIMITS = Limits()
SAMPLE_DIR: Path = PROJECT_ROOT / "samples" / "demo_application"

JD_TEXT = "We are hiring a perception engineer to build detection models. " * 5
CV_TEXT = "Five years of computer vision experience, PyTorch and TensorRT. " * 5


def add_user(engine, name: str) -> int:
    with session_scope(engine) as s:
        user = User(username=name, password_hash="h", totp_secret_enc="e")
        s.add(user)
        s.flush()
        return user.id


@pytest.fixture
def user_id(engine) -> int:
    return add_user(engine, "alex")


def docs(*extra: DocumentIn) -> list[DocumentIn]:
    return [
        DocumentIn(kind=DocKind.JD, source=DocSource.PASTE, text=JD_TEXT),
        DocumentIn(kind=DocKind.CV, source=DocSource.PDF, text=CV_TEXT, filename="cv.pdf"),
        *extra,
    ]


def create(engine, user_id, company="Northwind Robotics", role="ML Engineer", documents=None) -> int:
    return create_application(engine, user_id, company, role, documents or docs(), limits=LIMITS)


def document_count(engine) -> int:
    with session_scope(engine) as s:
        return len(s.exec(select(Document)).all())


# --- create -------------------------------------------------------------------------------------


def test_create_and_get_round_trip(engine, user_id):
    app_id = create(engine, user_id, company="  Northwind  Robotics ", role=" ML Engineer\n")
    detail = get_application(engine, user_id, app_id)

    assert detail is not None
    assert (detail.company, detail.role) == ("Northwind Robotics", "ML Engineer")
    assert set(detail.documents) == {DocKind.JD, DocKind.CV}
    cv = detail.documents[DocKind.CV]
    assert (cv.source, cv.filename) == (DocSource.PDF, "cv.pdf")
    assert cv.text == CV_TEXT.strip()
    assert cv.char_count == len(cv.text)


def test_create_stores_cleaned_text(engine, user_id):
    messy = DocumentIn(
        kind=DocKind.COVER_LETTER, source=DocSource.PASTE, text="My experi-\nence\r\n\n\n\nThanks"
    )
    app_id = create(engine, user_id, documents=docs(messy))
    detail = get_application(engine, user_id, app_id)
    assert detail.documents[DocKind.COVER_LETTER].text == "My experience\n\nThanks"


@pytest.mark.parametrize("missing", [DocKind.JD, DocKind.CV])
def test_create_requires_jd_and_cv(engine, user_id, missing):
    documents = [d for d in docs() if d.kind != missing]
    with pytest.raises(IngestError, match="Missing required"):
        create(engine, user_id, documents=documents)


def test_create_rejects_duplicate_kind(engine, user_id):
    extra = DocumentIn(kind=DocKind.CV, source=DocSource.PASTE, text=CV_TEXT)
    with pytest.raises(IngestError, match="duplicate: CV"):
        create(engine, user_id, documents=docs(extra))


@pytest.mark.parametrize(("company", "role"), [("   ", "ML Engineer"), ("Northwind", "\n\t")])
def test_create_requires_company_and_role(engine, user_id, company, role):
    with pytest.raises(IngestError, match="Please enter"):
        create(engine, user_id, company=company, role=role)


def test_invalid_document_saves_nothing(engine, user_id):
    empty_notes = DocumentIn(kind=DocKind.COMPANY_NOTES, source=DocSource.PASTE, text=" \x00 ")
    with pytest.raises(IngestError, match="company notes is empty"):
        create(engine, user_id, documents=docs(empty_notes))
    assert list_applications(engine, user_id) == []
    assert document_count(engine) == 0


# --- list ---------------------------------------------------------------------------------------


def test_list_is_newest_first_and_shows_kinds(engine, user_id):
    notes = DocumentIn(kind=DocKind.COMPANY_NOTES, source=DocSource.PASTE, text="Founded 2018 in Gothenburg.")
    first = create(engine, user_id, company="First Co")
    second = create(engine, user_id, company="Second Co", documents=docs(notes))

    summaries = list_applications(engine, user_id)
    assert [s.id for s in summaries] == [second, first]
    assert summaries[0].kinds == [DocKind.JD, DocKind.CV, DocKind.COMPANY_NOTES]
    assert summaries[1].kinds == [DocKind.JD, DocKind.CV]

    # Editing the older application moves it to the top.
    update_document(engine, user_id, first, DocKind.JD, JD_TEXT + " Updated.", limits=LIMITS)
    assert [s.id for s in list_applications(engine, user_id)] == [first, second]


# --- update -------------------------------------------------------------------------------------


def test_update_replaces_existing_document(engine, user_id):
    app_id = create(engine, user_id)
    before = get_application(engine, user_id, app_id)

    update_document(engine, user_id, app_id, DocKind.CV, "A brand new CV text. " * 20, limits=LIMITS)

    after = get_application(engine, user_id, app_id)
    assert after.documents[DocKind.CV].text.startswith("A brand new CV text.")
    assert after.documents[DocKind.CV].source == DocSource.PASTE
    assert after.updated_at >= before.updated_at
    assert document_count(engine) == 2  # replaced, not added


def test_update_adds_a_missing_document_and_returns_warnings(engine, user_id):
    app_id = create(engine, user_id)
    warnings = update_document(engine, user_id, app_id, DocKind.COVER_LETTER, "Short letter.", limits=LIMITS)
    assert warnings and "very short" in warnings[0]
    assert DocKind.COVER_LETTER in get_application(engine, user_id, app_id).documents


def test_update_rejects_empty_text(engine, user_id):
    app_id = create(engine, user_id)
    with pytest.raises(IngestError):
        update_document(engine, user_id, app_id, DocKind.CV, "   ", limits=LIMITS)
    assert get_application(engine, user_id, app_id).documents[DocKind.CV].text == CV_TEXT.strip()


def test_update_unknown_application_raises(engine, user_id):
    with pytest.raises(ApplicationNotFoundError):
        update_document(engine, user_id, 999, DocKind.CV, CV_TEXT, limits=LIMITS)


# --- delete -------------------------------------------------------------------------------------


def test_delete_cascades_to_documents(engine, user_id):
    app_id = create(engine, user_id)
    assert document_count(engine) == 2

    assert delete_application(engine, user_id, app_id) is True

    assert get_application(engine, user_id, app_id) is None
    assert document_count(engine) == 0  # removed by ON DELETE CASCADE in SQLite
    assert delete_application(engine, user_id, app_id) is False


# --- user isolation -----------------------------------------------------------------------------


def test_users_cannot_see_or_change_each_others_applications(engine, user_id):
    other = add_user(engine, "blake")
    app_id = create(engine, user_id)

    assert list_applications(engine, other) == []
    assert get_application(engine, other, app_id) is None
    assert delete_application(engine, other, app_id) is False
    with pytest.raises(ApplicationNotFoundError):
        update_document(engine, other, app_id, DocKind.CV, "Hijacked CV text. " * 20, limits=LIMITS)

    # The owner's data is untouched.
    detail = get_application(engine, user_id, app_id)
    assert detail is not None
    assert detail.documents[DocKind.CV].text == CV_TEXT.strip()


# --- committed sample ---------------------------------------------------------------------------


SAMPLE_FILES = {
    DocKind.JD: "jd.md",
    DocKind.CV: "cv.md",
    DocKind.COVER_LETTER: "cover_letter.md",
    DocKind.COMPANY_NOTES: "company_notes.md",
}


def test_sample_application_loads(engine, user_id):
    # Guards the committed demo data: if someone edits it past a limit, this fails.
    sample_docs = [
        DocumentIn(kind=kind, source=DocSource.PASTE, text=(SAMPLE_DIR / name).read_text(), filename=name)
        for kind, name in SAMPLE_FILES.items()
    ]
    app_id = create(
        engine,
        user_id,
        company="Northwind Robotics",
        role="Machine Learning Engineer, Perception",
        documents=sample_docs,
    )
    detail = get_application(engine, user_id, app_id)
    assert set(detail.documents) == set(DocKind)
    assert "Northwind Robotics" in detail.documents[DocKind.JD].text
    assert "Maya Lindqvist" in detail.documents[DocKind.CV].text
