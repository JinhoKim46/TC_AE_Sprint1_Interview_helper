"""Applications page: create an application from a JD + CV (+ optional cover letter / notes),
review the extracted text, edit it, or delete the application.

Each document can be uploaded as a PDF or pasted. PDF text is extracted into an editable box, so
extraction mistakes (columns, headers, hyphenation) can be fixed before saving.
"""

import hashlib
import math
from collections import Counter

import streamlit as st
from ui_common import current_user_id, document_guard, get_engine, safe_md, short

from interview_app.applications import (
    DocumentIn,
    create_application,
    delete_application,
    get_application,
    list_applications,
    update_document,
)
from interview_app.config import get_settings
from interview_app.demo import SAMPLE_COMPANY, SAMPLE_ROLE, load_sample_application
from interview_app.history import list_sessions
from interview_app.ingest import (
    KIND_LABELS,
    REQUIRED_KINDS,
    DocKind,
    DocSource,
    IngestError,
    clean_text,
    extract_pdf_text,
    validate_document,
)
from interview_app.interview.engine import active_session

engine = get_engine()
user_id = current_user_id()
limits = get_settings().limits
# st.file_uploader takes whole megabytes; rounding up keeps the stricter check in extract_pdf_text.
UPLOAD_MB = max(1, math.ceil(limits.max_upload_mb))

st.title("Applications")
st.caption("One application = one job you are preparing for. The interview is built from its documents.")


def _text_key(kind: DocKind) -> str:
    return f"new_text_{kind}"


def _document_input(kind: DocKind) -> None:
    """Upload-or-paste widget for one document. The text always ends up in st.session_state[_text_key]."""
    label = KIND_LABELS[kind].capitalize()
    required = kind in REQUIRED_KINDS
    st.markdown(f"**{label}**" + (" *(required)*" if required else " *(optional)*"))

    upload = st.file_uploader(
        f"{label} PDF",
        type=["pdf"],
        key=f"new_pdf_{kind}",
        label_visibility="collapsed",
        max_upload_size=UPLOAD_MB,
    )
    if upload is not None:
        # Only extract when a *new* file arrives; otherwise every rerun would overwrite the user's edits.
        file_id = f"{upload.name}:{upload.size}"
        if st.session_state.get(f"new_pdf_id_{kind}") != file_id:
            st.session_state[f"new_pdf_id_{kind}"] = file_id
            try:
                result = extract_pdf_text(upload.getvalue(), limits)
                # The text box below cuts anything over max_chars without a word, so a too-long PDF is
                # refused here with the reason instead of being silently truncated.
                _check_length(kind, result.text)
                st.session_state[_text_key(kind)] = result.text
                st.session_state[f"new_source_{kind}"] = DocSource.PDF
                st.session_state[f"new_warn_{kind}"] = result.warnings
            except IngestError as e:
                st.session_state[f"new_warn_{kind}"] = []
                st.error(str(e))
        for warning in st.session_state.get(f"new_warn_{kind}", []):
            st.warning(warning)

    st.text_area(
        f"{label} text",
        key=_text_key(kind),
        height=200 if required else 120,
        placeholder="…or paste the text here",
        label_visibility="collapsed",
        max_chars=limits.max_document_chars,
    )


def _collect_documents() -> list[DocumentIn]:
    return [
        DocumentIn(
            kind=kind,
            source=st.session_state.get(f"new_source_{kind}", DocSource.PASTE),
            text=st.session_state.get(_text_key(kind), ""),
            filename=getattr(st.session_state.get(f"new_pdf_{kind}"), "name", None),
        )
        for kind in DocKind
        if st.session_state.get(_text_key(kind), "").strip()
    ]


def _check_length(kind: DocKind, text: str) -> None:
    """The same limits the save applies (raises IngestError). Run before the guard, so an oversize
    document is refused for free instead of being sent to Jev first."""
    validate_document(kind, clean_text(text), limits)


def _flag_documents(documents: list[DocumentIn]) -> list[str]:
    """Injection-check the documents. Raises IngestError first if one is unusable (e.g. too long)."""
    for d in documents:
        _check_length(d.kind, d.text)
    guard = document_guard()
    results = [guard.check_document(KIND_LABELS[d.kind], d.text) for d in documents]
    return [r.reason for r in results if r.flagged]


def _fingerprint(company: str, role: str, documents: list[DocumentIn]) -> str:
    parts = [company.strip(), role.strip()] + [f"{d.kind}:{d.text}" for d in documents]
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


def _save(company: str, role: str, documents: list[DocumentIn]) -> None:
    # A double click sends two reruns; the second would save the same application again. The
    # fingerprint is stored before saving (not after), because Streamlit stops the first run as soon as
    # the second click arrives, possibly right after the row is written. Its key doesn't start with
    # "new_", so clearing the form keeps it.
    fingerprint = _fingerprint(company, role, documents)
    if st.session_state.get("saved_application") == fingerprint:
        st.toast("This application is already saved.", icon=":material/check:")
        return
    st.session_state.saved_application = fingerprint
    try:
        create_application(engine, user_id, company, role, documents, limits=limits)
    except IngestError as e:
        st.session_state.pop("saved_application", None)
        st.error(str(e))
    else:
        _clear_new_form()
        st.toast("Application saved.", icon=":material/check:")
        st.rerun()


def _save_edit(application_id: int, kind: DocKind, text: str) -> None:
    try:
        for warning in update_document(engine, user_id, application_id, kind, text, limits=limits):
            st.warning(warning)
        st.session_state.pop(f"edit_flag_{application_id}_{kind}", None)
        st.toast("Saved.", icon=":material/check:")
    except IngestError as e:
        st.error(str(e))


def _clear_new_form() -> None:
    for key in list(st.session_state):
        if key.startswith("new_"):
            del st.session_state[key]


# --- Create -----------------------------------------------------------------------------------

with st.expander("Add a new application", expanded=not list_applications(engine, user_id)):
    col1, col2 = st.columns(2)
    company = col1.text_input("Company", key="new_company")
    role = col2.text_input("Role", key="new_role")

    left, right = st.columns(2)
    with left:
        _document_input(DocKind.JD)
        _document_input(DocKind.COVER_LETTER)
    with right:
        _document_input(DocKind.CV)
        _document_input(DocKind.COMPANY_NOTES)

    if st.button("Save application", type="primary", icon=":material/save:"):
        documents = _collect_documents()
        # Documents are untrusted input (OWASP LLM01). The guard never blocks a document on its own,
        # because a real JD can contain odd text: it flags it, and the user decides.
        try:
            flags = _flag_documents(documents)
        except IngestError as e:
            st.error(str(e))
        else:
            if flags:
                st.session_state.new_flags = flags
            else:
                # An old warning must not stay on screen once the text checks clean.
                st.session_state.pop("new_flags", None)
                _save(company, role, documents)

    if flags := st.session_state.get("new_flags"):
        for reason in flags:
            st.warning(reason, icon=":material/shield:")
        st.caption("Edit the text above and save again, or save it as it is if it's fine.")
        if st.button("Save anyway", icon=":material/check:"):
            del st.session_state["new_flags"]
            _save(company, role, _collect_documents())

    st.divider()
    st.caption("No documents at hand? Load a fictional sample application.")
    if st.button("Load sample application", icon=":material/science:"):
        # One sample is enough: a second click (or a double click) would add an identical copy.
        if any(
            a.company == SAMPLE_COMPANY and a.role == SAMPLE_ROLE for a in list_applications(engine, user_id)
        ):
            st.toast("The sample application is already loaded.", icon=":material/info:")
        else:
            load_sample_application(engine, user_id, limits=limits)
            st.rerun()

# --- List / edit / delete ---------------------------------------------------------------------

apps = list_applications(engine, user_id)
if not apps:
    st.info("No applications yet.")
running = active_session(engine, user_id)
# One query for every application's interview count, instead of one list_sessions call per application.
interview_counts = Counter(s.application_id for s in list_sessions(engine, user_id))

for summary in apps:
    company = safe_md(short(summary.company, 60), inline=True)
    with st.expander(f"**{company}** — {safe_md(short(summary.role, 80), inline=True)}"):
        detail = get_application(engine, user_id, summary.id)
        if detail is None:  # deleted in another tab
            continue
        missing = [KIND_LABELS[k] for k in DocKind if k not in detail.documents]
        st.caption(
            f"Updated {detail.updated_at:%Y-%m-%d %H:%M}"
            + (f" · not provided: {', '.join(missing)}" if missing else "")
        )

        tabs = st.tabs([KIND_LABELS[k].capitalize() for k in DocKind])
        for tab, kind in zip(tabs, DocKind, strict=True):
            with tab:
                doc = detail.documents.get(kind)
                key = f"edit_{summary.id}_{kind}"
                st.text_area(
                    KIND_LABELS[kind],
                    value=doc.text if doc else "",
                    key=key,
                    height=250,
                    label_visibility="collapsed",
                    max_chars=limits.max_document_chars,
                )
                flag_key = f"edit_flag_{summary.id}_{kind}"
                if st.button("Save changes", key=f"save_{summary.id}_{kind}"):
                    # Edited text is as untrusted as uploaded text, so it passes the same document check
                    # (after the free length check, so an oversize text never reaches Jev).
                    try:
                        _check_length(kind, st.session_state[key])
                    except IngestError as e:
                        st.error(str(e))
                    else:
                        verdict = document_guard().check_document(KIND_LABELS[kind], st.session_state[key])
                        if verdict.flagged:
                            st.session_state[flag_key] = verdict.reason
                        else:
                            st.session_state.pop(flag_key, None)  # the earlier warning no longer applies
                            _save_edit(summary.id, kind, st.session_state[key])
                if reason := st.session_state.get(flag_key):
                    st.warning(reason, icon=":material/shield:")
                    if st.button("Save anyway", key=f"save_anyway_{summary.id}_{kind}"):
                        del st.session_state[flag_key]
                        _save_edit(summary.id, kind, st.session_state[key])

        # Interviews are deleted with their application (ON DELETE CASCADE), so the tick says so.
        n = interview_counts[summary.id]
        consequence = f" (also deletes {n} interview{'' if n == 1 else 's'} and their reports)" if n else ""
        in_use = running is not None and running.application_id == summary.id
        if in_use:
            st.caption("An interview for this application is in progress: end it before deleting.")
        confirm = st.checkbox(
            f"I want to delete this application{consequence}", key=f"confirm_{summary.id}", disabled=in_use
        )
        if st.button(
            "Delete", key=f"delete_{summary.id}", disabled=in_use or not confirm, icon=":material/delete:"
        ):
            delete_application(engine, user_id, summary.id)
            st.rerun()
