"""Applications page: create an application from a JD + CV (+ optional cover letter / notes),
review the extracted text, edit it, or delete the application.

Each document can be uploaded as a PDF or pasted. PDF text is extracted into an editable box, so
extraction mistakes (columns, headers, hyphenation) can be fixed before saving.
"""

import streamlit as st
from ui_common import current_user_id, document_guard, get_engine, settings

from interview_app.applications import (
    DocumentIn,
    create_application,
    delete_application,
    get_application,
    list_applications,
    update_document,
)
from interview_app.demo import load_sample_application
from interview_app.ingest import (
    KIND_LABELS,
    REQUIRED_KINDS,
    DocKind,
    DocSource,
    IngestError,
    extract_pdf_text,
)

engine = get_engine()
user_id = current_user_id()
limits = settings().limits

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
        f"{label} PDF", type=["pdf"], key=f"new_pdf_{kind}", label_visibility="collapsed"
    )
    if upload is not None:
        # Only extract when a *new* file arrives; otherwise every rerun would overwrite the user's edits.
        file_id = f"{upload.name}:{upload.size}"
        if st.session_state.get(f"new_pdf_id_{kind}") != file_id:
            st.session_state[f"new_pdf_id_{kind}"] = file_id
            try:
                result = extract_pdf_text(upload.getvalue(), limits)
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


def _flag_documents(documents: list[DocumentIn]) -> list[str]:
    guard = document_guard()
    results = [guard.check_document(KIND_LABELS[d.kind], d.text) for d in documents]
    return [r.reason for r in results if r.flagged]


def _save(company: str, role: str, documents: list[DocumentIn]) -> None:
    try:
        create_application(engine, user_id, company, role, documents, limits=limits)
    except IngestError as e:
        st.error(str(e))
    else:
        _clear_new_form()
        st.toast("Application saved.", icon=":material/check:")
        st.rerun()


def _save_edit(application_id: int, kind: DocKind, text: str) -> None:
    try:
        for warning in update_document(engine, user_id, application_id, kind, text, limits=limits):
            st.warning(warning)
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
        flags = _flag_documents(documents)
        if flags:
            st.session_state.new_flags = flags
        else:
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
        load_sample_application(engine, user_id, limits=limits)
        st.rerun()

# --- List / edit / delete ---------------------------------------------------------------------

apps = list_applications(engine, user_id)
if not apps:
    st.info("No applications yet.")

for summary in apps:
    with st.expander(f"**{summary.company}** — {summary.role}"):
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
                )
                flag_key = f"edit_flag_{summary.id}_{kind}"
                if st.button("Save changes", key=f"save_{summary.id}_{kind}"):
                    # Edited text is as untrusted as uploaded text, so it passes the same document check.
                    verdict = document_guard().check_document(KIND_LABELS[kind], st.session_state[key])
                    if verdict.flagged:
                        st.session_state[flag_key] = verdict.reason
                    else:
                        _save_edit(summary.id, kind, st.session_state[key])
                if reason := st.session_state.get(flag_key):
                    st.warning(reason, icon=":material/shield:")
                    if st.button("Save anyway", key=f"save_anyway_{summary.id}_{kind}"):
                        del st.session_state[flag_key]
                        _save_edit(summary.id, kind, st.session_state[key])

        confirm = st.checkbox("I want to delete this application", key=f"confirm_{summary.id}")
        if st.button("Delete", key=f"delete_{summary.id}", disabled=not confirm, icon=":material/delete:"):
            delete_application(engine, user_id, summary.id)
            st.rerun()
