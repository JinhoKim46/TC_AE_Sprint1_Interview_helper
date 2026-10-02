"""Interview page: pick an application, configure the interview, then talk to the interviewer.

The page holds no interview state of its own: the engine stores every turn in the database and the
page re-reads it on each rerun, so refreshing the browser resumes the interview where it was.
"""

import time

import streamlit as st
from drill_ui import drill_offer
from report_view import render_report
from ui_common import current_user_id, engine_deps, get_engine, settings

from interview_app.applications import list_applications
from interview_app.evaluation.service import EvaluationError, evaluate_session, stored_report
from interview_app.interview import engine as eng
from interview_app.interview.persona import (
    DEFAULT_MAIN_QUESTIONS,
    TYPE_LABELS,
    Difficulty,
    InterviewType,
    Mode,
)
from interview_app.preferences import judge_model, load_preferences, to_session_config

engine = get_engine()
user_id = current_user_id()

st.title("Interview")

MODE_LABELS = {Mode.REALISTIC.value: "Realistic", Mode.COACHING.value: "Coaching"}
MODE_CAPTIONS = {
    Mode.REALISTIC.value: "Like the real thing: feedback at the end.",
    Mode.COACHING.value: "Feedback after every answer, with retries.",
}


def start_form() -> None:
    apps = list_applications(engine, user_id)
    if not apps:
        st.info("Add an application first (job description + CV).")
        st.page_link("pages/applications.py", label="Go to Applications", icon=":material/folder_open:")
        return

    # Saved preferences (Settings page) pre-fill the form; the developer part (prompt variant, model
    # settings) is not shown here at all and flows into the session through to_session_config.
    prefs = load_preferences(engine, user_id)

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
            index=list(InterviewType).index(prefs.interview_type),
        )
    )
    difficulty = col2.segmented_control(
        "Difficulty",
        options=[d.value for d in Difficulty],
        default=prefs.difficulty.value,
        format_func=str.capitalize,
    )
    main_questions = st.slider(
        "Main questions (follow-ups come on top)",
        3,
        12,
        prefs.main_questions or DEFAULT_MAIN_QUESTIONS[interview_type],
    )
    mode = st.radio(
        "Mode",
        options=list(MODE_LABELS),
        format_func=MODE_LABELS.get,
        captions=list(MODE_CAPTIONS.values()),
        index=list(MODE_LABELS).index(prefs.mode.value),
        horizontal=True,
    )
    # Developer options live on the Settings page (course task M9): a candidate doesn't need them here.
    st.caption("Defaults, prompt and model settings: see the [Settings](/settings) page.")

    if st.button("Start interview", type="primary", icon=":material/play_arrow:"):
        config = to_session_config(
            prefs,
            interview_type=interview_type,
            difficulty=Difficulty(difficulty or Difficulty.STANDARD),
            main_questions=main_questions,
            mode=Mode(mode),
        )
        with st.spinner("Reading your documents and preparing the interview (about 30 seconds)…"):
            try:
                eng.start_interview(engine_deps(), user_id, app_id, config)
            except eng.InterviewError as e:
                st.error(str(e))
                return
        st.rerun()


def live_chips(live) -> None:
    """Coaching mode: the answer's live rubric scores as small coloured badges, then the tip."""
    chips = []
    for item in live.items:
        # Colour by level so the weakest item stands out at a glance.
        color = "red" if item.level <= 2 else "orange" if item.level == 3 else "green"
        chips.append(f":{color}-badge[{item.name} {item.score:.1f}/5]")
    st.markdown(" ".join(chips))
    if live.tip:
        st.caption(f":material/lightbulb: {live.tip}")


def earlier_attempts(view: eng.SessionView, turn: eng.TurnView, previous_idx: int) -> None:
    """Superseded attempts for this answer: those stored between the previous kept turn and this one."""
    attempts = [a for a in view.superseded if previous_idx < a.idx < turn.idx]
    for n, attempt in enumerate(attempts, start=1):
        label = "Earlier attempt" if len(attempts) == 1 else f"Earlier attempt {n}"
        with st.expander(label):
            st.markdown(attempt.text)
            if attempt.live:
                live_chips(attempt.live)


def submit(action, view: eng.SessionView, text: str) -> None:
    """Send an answer (eng.answer or eng.retry), then rerun so the page re-reads the stored turns."""
    thinking = (
        "Scoring your answer…" if view.config.mode == Mode.COACHING else f"{view.persona.name} is thinking…"
    )
    with st.spinner(thinking):
        try:
            outcome = action(engine_deps(), user_id, view.id, text)
        except eng.InterviewError as e:
            st.error(str(e))
            time.sleep(1)
            st.rerun()
            return
    if not outcome.accepted:
        # Keep the warning across the rerun so the user sees why nothing happened.
        st.session_state.guard_notice = outcome.guard.reason or "That answer could not be sent."
    st.rerun()


def coaching_choice(view: eng.SessionView) -> None:
    """Coaching mode, after an answer: retry it (up to the limit) or continue to the next question."""
    if st.session_state.get("retrying") == view.id:
        if text := st.chat_input("Your new answer"):
            st.session_state.pop("retrying", None)
            submit(eng.retry, view, text)
        return
    left = settings().limits.max_retries_per_answer - view.retries_used
    col1, col2 = st.columns(2)
    if col1.button(
        "Retry this answer",
        icon=":material/replay:",
        disabled=left <= 0,
        help=f"{left} retr{'y' if left == 1 else 'ies'} left for this question. The last attempt counts.",
    ):
        st.session_state.retrying = view.id
        st.rerun()
    if col2.button("Continue", type="primary", icon=":material/arrow_forward:"):
        with st.spinner(f"{view.persona.name} is thinking…"):
            try:
                eng.continue_interview(engine_deps(), user_id, view.id)
            except eng.InterviewError as e:
                st.error(str(e))  # the answer is stored: pressing Continue again retries
                return
        st.rerun()


def chat(view: eng.SessionView) -> None:
    persona = view.persona
    coaching = view.config.mode == Mode.COACHING
    st.caption(
        f"{view.company} — {view.role} · {TYPE_LABELS[view.config.interview_type]}"
        + (" · Coaching mode" if coaching else "")
    )
    if focus := view.config.focus:
        targets = focus.requirements + focus.skills
        st.info("Focused practice on: " + "; ".join(targets), icon=":material/target:")
    progress = view.progress
    done = min(progress.main_asked, view.config.main_questions)
    st.progress(
        done / view.config.main_questions, text=f"Main questions: {done} of {view.config.main_questions}"
    )

    previous_idx = -1
    for t in view.turns:
        if t.speaker == "interviewer":
            with st.chat_message("assistant", avatar=":material/person:"):
                st.markdown(f"**{persona.name}** · {persona.title}\n\n{t.text}")
        else:
            with st.chat_message("user"):
                st.markdown(t.text)
                if coaching:
                    if t.live:
                        live_chips(t.live)
                    earlier_attempts(view, t, previous_idx)
        previous_idx = t.idx

    if view.status == "active":
        if progress.last_speaker == "candidate" and coaching:
            coaching_choice(view)
        elif progress.last_speaker == "candidate":
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
            submit(eng.answer, view, text)

        if notice := st.session_state.pop("guard_notice", None):
            st.warning(notice, icon=":material/shield:")

        with st.sidebar:
            st.metric("Cost so far", f"${view.cost_usd:.4f}")
            if st.button("End interview", icon=":material/stop:"):
                eng.end_interview(engine_deps(), user_id, view.id)
                st.rerun()
    else:
        st.success("Interview complete." if view.status == "finished" else "Interview ended.")
        feedback(view)
        if st.button("Start a new interview", type="primary"):
            st.session_state.pop("viewing_session", None)
            st.rerun()


def feedback(view: eng.SessionView) -> None:
    """The report for a finished interview: generated once on request, then stored."""
    st.divider()
    st.header("Feedback")
    if not any(t.speaker == "candidate" for t in view.turns):
        st.caption("No answers were given, so there is nothing to evaluate.")
        return
    report = stored_report(engine_deps(), user_id, view.id)
    if report is None:
        if not st.button("Get my feedback report", type="primary", icon=":material/assessment:"):
            return
        with st.spinner("The evaluator is reading your interview (about a minute)…"):
            try:
                prefs = load_preferences(engine, user_id)
                report = evaluate_session(
                    engine_deps(), user_id, view.id, judge_model=judge_model(prefs, settings())
                )
            except EvaluationError as e:
                st.error(str(e))
                return
    render_report(report, settings().rubric_path)
    st.caption(f"Interview + report cost: ${eng.session_cost(engine, view.id):.4f}")
    drill_offer(view, report, key="drill-interview")


active = eng.active_session(engine, user_id)
if active is not None:
    st.session_state.viewing_session = active.id
    chat(active)
elif (sid := st.session_state.get("viewing_session")) and (view := eng.get_session(engine, user_id, sid)):
    chat(view)  # just finished: keep the transcript on screen until a new interview starts
else:
    start_form()
