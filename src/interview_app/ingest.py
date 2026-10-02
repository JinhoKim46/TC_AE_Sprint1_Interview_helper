"""Turn uploaded or pasted documents into clean, validated text.

Flow: PDF bytes -> `extract_pdf_text` (or pasted text) -> `clean_text` -> `validate_document`.
Everything here is pure (no DB, no Streamlit), so it is easy to test and reuse from the UI,
the URL importer (later PR) and the lab scripts.

Limits come from `config.Limits` so they can be changed in `.env` without touching code
(OWASP LLM10: unbounded consumption — huge files cost money and time downstream).
"""

import io
import logging
import re
from enum import StrEnum

from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from interview_app.config import Limits

log = logging.getLogger(__name__)


class IngestError(ValueError):
    """A document can't be used. The message is written for the end user, so the UI can show it as is."""


class DocKind(StrEnum):
    JD = "jd"
    CV = "cv"
    COVER_LETTER = "cover_letter"
    COMPANY_NOTES = "company_notes"


# Without a job description and a CV there is nothing to ground the interview in.
REQUIRED_KINDS: frozenset[DocKind] = frozenset({DocKind.JD, DocKind.CV})

# Friendly names for error messages ("job description" reads better than "jd").
KIND_LABELS: dict[DocKind, str] = {
    DocKind.JD: "job description",
    DocKind.CV: "CV",
    DocKind.COVER_LETTER: "cover letter",
    DocKind.COMPANY_NOTES: "company notes",
}


class DocSource(StrEnum):
    PDF = "pdf"
    PASTE = "paste"
    URL = "url"  # reserved for the JD-from-URL import (later PR)


class ExtractResult(BaseModel):
    text: str
    pages: int
    warnings: list[str] = Field(default_factory=list)


# A page with fewer characters than this is probably a scanned image (no text layer).
MIN_CHARS_PER_PAGE = 20
# Below this a whole document is suspiciously short (e.g. only a title) — warn, don't fail.
MIN_DOCUMENT_CHARS = 200


def extract_pdf_text(data: bytes, limits: Limits) -> ExtractResult:
    """Extract the text layer of a PDF, page by page.

    Size is checked *before* parsing so a huge file never reaches the PDF parser.
    """
    max_bytes = int(limits.max_upload_mb * 1024 * 1024)
    if len(data) > max_bytes:
        size_mb = len(data) / (1024 * 1024)
        raise IngestError(
            f"The file is {size_mb:.1f} MB; the limit is {limits.max_upload_mb:g} MB. "
            "Try a smaller PDF or paste the text instead."
        )
    # Every real PDF starts with this magic header; checking it gives a clearer message than
    # whatever the parser would say about a .docx renamed to .pdf.
    if not data.lstrip()[:5].startswith(b"%PDF-"):
        raise IngestError("This file is not a PDF. Upload a PDF or paste the text instead.")

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise IngestError(
                "This PDF is password-protected. Remove the password or paste the text instead."
            )
        pages = reader.pages
        page_count = len(pages)
    except PdfReadError as exc:
        log.warning("PDF parse failed: %s", exc)  # the exception text, never document contents
        raise IngestError("This PDF could not be read (it may be damaged). Paste the text instead.") from exc

    if page_count == 0:
        raise IngestError("This PDF has no pages.")
    if page_count > limits.max_pdf_pages:
        raise IngestError(
            f"The PDF has {page_count} pages; the limit is {limits.max_pdf_pages}. "
            "Upload only the relevant pages or paste the text instead."
        )

    texts: list[str] = []
    empty_pages: list[int] = []
    for number, page in enumerate(pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:  # pypdf raises many types on odd pages; one bad page shouldn't sink the file
            log.warning("Text extraction failed on page %d: %s", number, exc)
            page_text = ""
        if len(page_text.strip()) < MIN_CHARS_PER_PAGE:
            empty_pages.append(number)
        texts.append(page_text)

    warnings: list[str] = []
    if empty_pages:
        listed = ", ".join(str(n) for n in empty_pages)
        warnings.append(
            f"Little or no text found on page(s) {listed}. They may be scanned images; "
            "if text is missing, paste it instead."
        )
    # Pages are joined by a blank line so paragraphs from different pages don't run together.
    return ExtractResult(text="\n\n".join(texts), pages=page_count, warnings=warnings)


# C0 control characters except tab (\x09) and newline (\x0a), plus DEL. \r is handled earlier.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# "experi-\nence" -> "experience". Only a letter + hyphen at the end of a line followed by a
# lowercase letter counts: list dashes ("\n- item") and "Q3-\nQ4" ranges are left alone. A real
# compound split at a line end ("well-\nknown") gets joined too; that small loss is acceptable.
_HYPHEN_BREAK = re.compile(r"(\w)-\n[ \t]*([a-z])")
_SPACES = re.compile(r"[ \t ]+")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Normalise text from PDFs and copy-paste so the LLM sees tidy, compact input."""
    # Windows (\r\n) and old Mac (\r) line endings -> \n, so the regexes below only need \n.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Form feeds separate PDF pages; treat them as paragraph breaks before stripping controls.
    text = text.replace("\f", "\n\n")
    text = _CONTROL_CHARS.sub("", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    # Runs of spaces/tabs/non-breaking spaces -> one space, and no trailing spaces on lines.
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    # Keep paragraph structure (one blank line) but drop the big gaps PDFs often produce.
    text = _MANY_BLANK_LINES.sub("\n\n", text)
    return text.strip()


def validate_document(kind: DocKind, text: str, limits: Limits) -> list[str]:
    """Check a (cleaned) document. Raises IngestError when unusable; returns soft warnings otherwise.

    Prompt-injection scanning is deliberately not here: it lives in `security/` (InjectionGuard).
    """
    label = KIND_LABELS[kind]
    stripped = text.strip()
    if not stripped:
        raise IngestError(f"The {label} is empty.")
    if len(stripped) > limits.max_document_chars:
        raise IngestError(
            f"The {label} has {len(stripped):,} characters; the limit is {limits.max_document_chars:,}. "
            "Shorten it to the relevant parts."
        )
    warnings: list[str] = []
    if len(stripped) < MIN_DOCUMENT_CHARS:
        warnings.append(f"The {label} is very short ({len(stripped)} characters). Is anything missing?")
    return warnings
