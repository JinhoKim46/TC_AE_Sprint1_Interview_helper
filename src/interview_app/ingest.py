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
import threading
from enum import StrEnum

from pydantic import BaseModel, Field
from pypdf import PdfReader, apply_configuration
from pypdf.errors import LimitReachedError, PdfReadError

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


# A PDF is a small file that can describe a huge amount of work: one 80 KB page with a compressed
# 33 MB content stream took 26 s and 1.5 GB of memory to read (a "decompression bomb"). Three bounds:
# 1. Decompressed streams are capped by pypdf itself (limits.pdf_max_stream_bytes); a bigger stream
#    raises LimitReachedError instead of being inflated.
# 2. Reading stops once the text is clearly over the document limit; the rest can't be used anyway.
#    The margin allows for the whitespace `clean_text` removes later.
PDF_TEXT_MARGIN = 2
# 3. The whole read runs in a worker thread and we stop waiting after this many seconds. Python
#    can't kill a thread, so a stuck read finishes in the background; the bounds above keep that short.
#    (limits.pdf_extract_timeout_s, overridable per call for tests.)


def extract_pdf_text(data: bytes, limits: Limits, timeout_s: float | None = None) -> ExtractResult:
    """Extract the text layer of a PDF, page by page.

    Size is checked *before* parsing so a huge file never reaches the PDF parser. `timeout_s` is a
    parameter so tests can use a tiny one.
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

    outcome: dict[str, object] = {}

    def work() -> None:
        try:
            outcome["result"] = _read_pdf(data, limits)
        except BaseException as exc:  # handed to the caller's thread, which re-raises it
            outcome["error"] = exc

    # daemon=True: a read still running when the app exits must not keep the process alive.
    worker = threading.Thread(target=work, name="pdf-extract", daemon=True)
    worker.start()
    timeout_s = limits.pdf_extract_timeout_s if timeout_s is None else timeout_s
    worker.join(timeout_s)
    if worker.is_alive():
        log.warning("PDF extraction timed out after %.0f s", timeout_s)
        raise IngestError(
            "This PDF takes too long to read (it may be damaged or unusually complex). "
            "Paste the text instead."
        )
    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]
    return outcome["result"]  # type: ignore[return-value]


def _read_pdf(data: bytes, limits: Limits) -> ExtractResult:
    # pypdf keeps its limits in a ContextVar, and a new thread starts with the defaults, so they are
    # applied here, inside the worker thread.
    with apply_configuration(
        zlib_maximum_output_length=limits.pdf_max_stream_bytes,
        lzw_maximum_output_length=limits.pdf_max_stream_bytes,
        run_length_maximum_output_length=limits.pdf_max_stream_bytes,
        array_based_stream_maximum_output_length=limits.pdf_max_stream_bytes,
        maximum_declared_stream_length=limits.pdf_max_stream_bytes,
    ):
        try:
            return _extract_pages(data, limits)
        except LimitReachedError as exc:
            log.warning("PDF hit a size limit: %s", exc)
            raise IngestError(
                "This PDF contains a part that is too large to read safely. Paste the text instead."
            ) from exc


def _extract_pages(data: bytes, limits: Limits) -> ExtractResult:
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

    max_chars = limits.max_document_chars * PDF_TEXT_MARGIN
    texts: list[str] = []
    empty_pages: list[int] = []
    total_chars = 0
    for number, page in enumerate(pages, start=1):
        if total_chars > max_chars:
            break
        try:
            page_text = page.extract_text() or ""
        except LimitReachedError:
            raise  # a bomb, not an odd page: refuse the whole file
        except Exception as exc:  # pypdf raises many types on odd pages; one bad page shouldn't sink the file
            log.warning("Text extraction failed on page %d: %s", number, exc)
            page_text = ""
        if len(page_text.strip()) < MIN_CHARS_PER_PAGE:
            empty_pages.append(number)
        texts.append(page_text)
        total_chars += len(page_text)

    warnings: list[str] = []
    if empty_pages:
        listed = ", ".join(str(n) for n in empty_pages)
        warnings.append(
            f"Little or no text found on page(s) {listed}. They may be scanned images; "
            "if text is missing, paste it instead."
        )
    if len(texts) < page_count:
        warnings.append(
            f"Only the first {len(texts)} of {page_count} pages were read: the text is already over the "
            f"{limits.max_document_chars:,}-character limit."
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
