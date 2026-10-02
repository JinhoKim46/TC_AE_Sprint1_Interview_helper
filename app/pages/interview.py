"""Interview page: pick an application, configure the interview, then talk to the interviewer.

The page holds no interview state of its own: the engine stores every turn in the database and the
page re-reads it on each rerun, so refreshing the browser resumes the interview where it was.
"""

import time

import streamlit as st
from ui_common import current_user_id, engine_deps, get_engine

from interview_app.applications import list_applications
from interview_app.interview import engine as eng
from interview_app.interview.persona import (
    DEFAULT_MAIN_QUESTIONS,
    TYPE_LABELS,
    VARIANT_LABELS,
    Difficulty,
    InterviewType,
    PromptVariant,
    SessionConfig,
)

engine = get_engine()
user_id = current_user_id()

st.title("Interview")


def start_form() -> None:
    apps = list_applications(engine, user_id)
    if not apps:
        st.info("Add an application first (job description + CV).")
        st.page_link("pages/applications.py", label="Go to Applications", icon=":material/folder_open:")
        return

    labels = {a.id: f"{a.company} — {a.role}" for a in apps}
    app_id = st.selectbox("Application", options=list(labels), format_func=labels.get)
    col1, col2 = st.columns(2)
    # Options are plain strings (enum values) and labels come from a lookup: widgets compare
    # options by value across reruns, which is simplest and most robust with plain strings.
    interview_type = InterviewType(
        col1.selectbox(
            "Interview type",
            options=[t.value for t in InterviewType],
            format_func=lambda v: TYPE_LABELS[InterviewType(v)],
            index=1,
        )
    )
    difficulty = col2.segmented_control(
        "Difficulty",
        options=[d.value for d in Difficulty],
        default=Difficulty.STANDARD.value,
        format_func=str.capitalize,
    )
    main_questions = st.slider(
        "Main questions (follow-ups come on top)", 3, 12, DEFAULT_MAIN_QUESTIONS[interview_type]
    )

    # Developer options are kept out of the main flow (course task M9): a candidate doesn't need them.
    with st.expander("Developer options"):
        variant = PromptVariant(
            st.selectbox(
                "Interviewer system prompt",
                options=[v.value for v in PromptVariant],
                format_func=lambda v: VARIANT_LABELS[PromptVariant(v)],
                index=list(PromptVariant).index(PromptVariant.P4_ROLE_RICH),
            )
        )

    if st.button("Start interview", type="primary", icon=":material/play_arrow:"):
        config = SessionConfig(
            interview_type=interview_type,
            difficulty=Difficulty(difficulty or Difficulty.STANDARD),
            main_questions=main_questions,
            prompt_variant=variant,
        )
        with st.spinner("Reading your documents and preparing the interview (about 30 seconds)…"):
            try:
                eng.start_interview(engine_deps(), user_id, app_id, config)
            except eng.InterviewError as e:
                st.error(str(e))
                return
        st.rerun()


def chat(view: eng.SessionView) -> None:
    persona = view.persona
    st.caption(f"{view.company} — {view.role} · {TYPE_LABELS[view.config.interview_type]}")
    progress = view.progress
    done = min(progress.main_asked, view.config.main_questions)
    st.progress(
        done / view.config.main_questions, text=f"Main questions: {done} of {view.config.main_questions}"
    )

    for t in view.turns:
        if t.speaker == "interviewer":
            with st.chat_message("assistant", avatar=":material/person:"):
                st.markdown(f"**{persona.name}** · {persona.title}\n\n{t.text}")
        else:
            with st.chat_message("user"):
                st.markdown(t.text)

    if view.status == "active":
        if progress.last_speaker == "candidate":
            # The model failed after the answer was saved: offer a retry instead of losing it.
            st.warning("The interviewer didn't respond.")
            if st.button("Try again", icon=":material/refresh:"):
                with st.spinner(f"{persona.name} is thinking…"):
                    try:
                        eng.respond(engine_deps(), user_id, view.id)
                    except eng.InterviewError as e:
                        st.error(str(e))
                        return
                st.rerun()
        elif text := st.chat_input("Your answer"):
            with st.spinner(f"{persona.name} is thinking…"):
                try:
                    outcome = eng.answer(engine_deps(), user_id, view.id, text)
                except eng.InterviewError as e:
                    st.error(str(e))
                    time.sleep(1)
                    st.rerun()
                    return
            if not outcome.accepted:
                # Keep the warning across the rerun so the user sees why nothing happened.
                st.session_state.guard_notice = outcome.guard.reason or "That answer could not be sent."
            st.rerun()

        if notice := st.session_state.pop("guard_notice", None):
            st.warning(notice, icon=":material/shield:")

        with st.sidebar:
            st.metric("Cost so far", f"${view.cost_usd:.4f}")
            if st.button("End interview", icon=":material/stop:"):
                eng.end_interview(engine_deps(), user_id, view.id)
                st.rerun()
    else:
        st.success("Interview complete." if view.status == "finished" else "Interview ended.")
        st.metric("Cost", f"${view.cost_usd:.4f}")
        if st.button("Start a new interview", type="primary"):
            st.session_state.pop("viewing_session", None)
            st.rerun()


active = eng.active_session(engine, user_id)
if active is not None:
    st.session_state.viewing_session = active.id
    chat(active)
elif (sid := st.session_state.get("viewing_session")) and (view := eng.get_session(engine, user_id, sid)):
    chat(view)  # just finished: keep the transcript on screen until a new interview starts
else:
    start_form()
