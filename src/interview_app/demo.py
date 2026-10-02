"""Load the committed fictional sample application, so the app can be tried (and reviewed)
without uploading personal documents."""

from sqlalchemy.engine import Engine

from interview_app.applications import DocumentIn, create_application
from interview_app.config import PROJECT_ROOT, Limits
from interview_app.ingest import DocKind, DocSource

SAMPLE_DIR = PROJECT_ROOT / "samples" / "demo_application"
SAMPLE_COMPANY = "Northwind Robotics"
SAMPLE_ROLE = "Machine Learning Engineer, Perception"
_FILES = {
    DocKind.JD: "jd.md",
    DocKind.CV: "cv.md",
    DocKind.COVER_LETTER: "cover_letter.md",
    DocKind.COMPANY_NOTES: "company_notes.md",
}


def load_sample_application(engine: Engine, user_id: int, limits: Limits | None = None) -> int:
    documents = [
        DocumentIn(kind=kind, source=DocSource.PASTE, text=(SAMPLE_DIR / name).read_text(), filename=name)
        for kind, name in _FILES.items()
    ]
    return create_application(engine, user_id, SAMPLE_COMPANY, SAMPLE_ROLE, documents, limits=limits)
