import pytest
from fpdf import FPDF

from interview_app.config import Limits
from interview_app.ingest import DocKind, IngestError, clean_text, extract_pdf_text, validate_document

LIMITS = Limits()


def make_pdf(pages: list[str]) -> bytes:
    """Build a real PDF in memory. An empty string gives a page with no text layer,
    which is what a scanned page looks like to a text extractor."""
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for text in pages:
        pdf.add_page()
        if text:
            pdf.multi_cell(0, 10, text)
    return bytes(pdf.output())


# --- extract_pdf_text ---------------------------------------------------------------------------


def test_extracts_text_from_a_pdf():
    result = extract_pdf_text(make_pdf(["Machine Learning Engineer at Northwind Robotics"]), LIMITS)
    assert "Northwind Robotics" in result.text
    assert result.pages == 1
    assert result.warnings == []


def test_extracts_all_pages_in_order():
    result = extract_pdf_text(
        make_pdf([f"This is page number {n} of the document." for n in (1, 2, 3)]), LIMITS
    )
    assert result.pages == 3
    assert (
        result.text.index("page number 1")
        < result.text.index("page number 2")
        < result.text.index("page number 3")
    )


def test_blank_page_gives_a_warning_not_an_error():
    result = extract_pdf_text(make_pdf(["Some real text on the first page here.", ""]), LIMITS)
    assert result.pages == 2
    assert len(result.warnings) == 1
    assert "page(s) 2" in result.warnings[0]
    assert "paste" in result.warnings[0]


def test_rejects_too_many_pages():
    data = make_pdf(["page text long enough"] * 3)
    with pytest.raises(IngestError, match="3 pages; the limit is 2"):
        extract_pdf_text(data, Limits(max_pdf_pages=2))


def test_rejects_oversize_file_before_parsing():
    # 0.0001 MB ~ 105 bytes: any real PDF is bigger. Size is checked first, so even
    # garbage of that size gets the size message rather than the "not a PDF" one.
    with pytest.raises(IngestError, match="limit is 0.0001 MB"):
        extract_pdf_text(b"x" * 1000, Limits(max_upload_mb=0.0001))


def test_rejects_non_pdf_bytes():
    with pytest.raises(IngestError, match="not a PDF"):
        extract_pdf_text(b"PK\x03\x04 this is a zip / docx file", LIMITS)


def test_rejects_corrupt_pdf():
    with pytest.raises(IngestError, match="could not be read"):
        extract_pdf_text(b"%PDF-1.7\n garbage garbage garbage", LIMITS)


def test_rejects_encrypted_pdf():
    pdf = FPDF()
    pdf.set_encryption(owner_password="owner", user_password="secret")
    pdf.set_font("Helvetica", size=12)
    pdf.add_page()
    pdf.cell(0, 10, "secret text")
    with pytest.raises(IngestError, match="password-protected"):
        extract_pdf_text(bytes(pdf.output()), LIMITS)


# --- clean_text ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("line one\r\nline two\rline three", "line one\nline two\nline three"),
        ("too    many \t spaces here", "too many spaces here"),
        ("trailing spaces   \n  leading", "trailing spaces\nleading"),
        ("nul\x00 and bell\x07 removed", "nul and bell removed"),
        ("years of experi-\nence in vision", "years of experience in vision"),
        ("a\n\n\n\n\nb", "a\n\nb"),
        ("keep\n\none blank line", "keep\n\none blank line"),
        ("- bullet one\n- bullet two", "- bullet one\n- bullet two"),
        ("Q3-\nQ4 roadmap", "Q3-\nQ4 roadmap"),  # uppercase after the break: not a split word
        ("page one\fpage two", "page one\n\npage two"),
        ("   \n  padded  \n\n ", "padded"),
    ],
)
def test_clean_text(raw, expected):
    assert clean_text(raw) == expected


def test_clean_text_turns_tabs_into_spaces_and_keeps_newlines():
    # Tabs are allowed through the control-char filter, then collapsed like other spaces.
    assert clean_text("name\tvalue\nnext") == "name value\nnext"


# --- validate_document --------------------------------------------------------------------------


def test_validate_rejects_empty_text():
    with pytest.raises(IngestError, match="job description is empty"):
        validate_document(DocKind.JD, "   \n ", LIMITS)


def test_validate_rejects_text_over_the_limit():
    with pytest.raises(IngestError, match="CV has 101 characters; the limit is 100"):
        validate_document(DocKind.CV, "x" * 101, Limits(max_document_chars=100))


def test_validate_warns_on_very_short_text():
    warnings = validate_document(DocKind.COVER_LETTER, "Dear team, hire me.", LIMITS)
    assert len(warnings) == 1
    assert "very short" in warnings[0]


def test_validate_accepts_a_normal_document():
    assert validate_document(DocKind.JD, "A reasonable job description. " * 20, LIMITS) == []
