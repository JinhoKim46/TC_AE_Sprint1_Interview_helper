"""The "practise your weak spots" offer under a feedback report (Interview and History pages)."""

import streamlit as st
import ui_common  # module attribute lookups (not `from … import`), so tests can swap engine_deps

from interview_app.evaluation.rubric import load_rubric
from interview_app.evaluation.schemas import Report
from interview_app.interview import engine as eng
from interview_app.interview.drill import drill_config, focus_from_report


def drill_offer(view: eng.SessionView, report: Report, key: str, go_to_interview: bool = False) -> None:
    """Turn the report's weak spots into the next practice interview for the same application.
    `go_to_interview`: from another page (History), jump to the Interview page once it has started."""
    focus = focus_from_report(
        report, load_rubric(ui_common.settings().rubric_path), source_session_id=view.id
    )
    if focus is None:
        return
    st.subheader("Practise your weak spots")
    if focus.requirements:
        st.markdown("Job requirements to show better: " + "; ".join(focus.requirements))
    if focus.skills:
        st.markdown("Answer qualities to improve: " + "; ".join(focus.skills))
    if focus.advice:
        st.caption("Advice from that report: " + "; ".join(focus.advice))
    if st.button("Start a focused practice interview", type="primary", icon=":material/target:", key=key):
        with st.spinner("Preparing a focused interview (about 30 seconds)…"):
            try:
                config = drill_config(view.config, focus)
                eng.start_interview(
                    ui_common.engine_deps(), ui_common.current_user_id(), view.application_id, config
                )
            except eng.InterviewError as e:
                st.error(str(e))
                return
        st.session_state.pop("viewing_session", None)
        if go_to_interview:
            st.switch_page("pages/interview.py")
        st.rerun()
