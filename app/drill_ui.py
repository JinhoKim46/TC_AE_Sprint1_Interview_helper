"""The "practise your weak spots" offer under a feedback report (Interview and History pages)."""

import streamlit as st
import ui_common  # module attribute lookups (not `from … import`), so tests can swap engine_deps
from ui_common import safe_md

from interview_app.evaluation.rubric import load_rubric
from interview_app.evaluation.schemas import Report
from interview_app.interview import engine as eng
from interview_app.interview.drill import drill_config, focus_from_report


def _joined(items: list[str]) -> str:
    return "; ".join(safe_md(i, inline=True) for i in items)


def drill_offer(view: eng.SessionView, report: Report, key: str, go_to_interview: bool = False) -> None:
    """Turn the report's weak spots into the next practice interview for the same application.
    `go_to_interview`: from another page (History), jump to the Interview page once it has started."""
    focus = focus_from_report(
        report, load_rubric(ui_common.get_settings().rubric_path), source_session_id=view.id
    )
    if focus is None:
        return
    st.subheader("Practise your weak spots")
    if focus.requirements:
        st.markdown("Job requirements to show better: " + _joined(focus.requirements))
    if focus.skills:
        st.markdown("Answer qualities to improve: " + _joined(focus.skills))
    if focus.advice:
        st.caption("Advice from that report: " + _joined(focus.advice))

    # One interview at a time: a second one would leave two "active" sessions, and the Interview page
    # only ever resumes the newest.
    active = eng.active_session(ui_common.get_engine(), ui_common.current_user_id())
    if active is not None and active.id != view.id:
        st.info("Another interview is in progress. Finish or end it before starting a practice interview.")
        ui_common.page_link(
            "pages/interview.py", label="Go to the running interview", icon=":material/forum:"
        )
        return

    # A second click while the first start is still running would otherwise start a second interview;
    # the flag disables the button from the first click on (cleared again only if the start fails).
    started_key = f"drill_started_{key}"
    if st.session_state.get(started_key):
        st.caption("A practice interview was already started from this report.")
    if st.button(
        "Start a focused practice interview",
        type="primary",
        icon=":material/target:",
        key=key,
        disabled=bool(st.session_state.get(started_key)),
    ):
        st.session_state[started_key] = True
        with st.spinner("Preparing a focused interview (about 30 seconds)…"):
            try:
                config = drill_config(view.config, focus)
                eng.start_interview(
                    ui_common.engine_deps(), ui_common.current_user_id(), view.application_id, config
                )
            except eng.InterviewError as e:
                st.session_state.pop(started_key, None)
                st.error(str(e))
                return
        st.session_state.pop("viewing_session", None)
        if go_to_interview:
            st.switch_page("pages/interview.py")
        st.rerun()
