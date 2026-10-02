"""Interview page: pick an application, configure the interview, then talk to the interviewer.

The page holds no interview state of its own: the engine stores every turn in the database and the
page re-reads it on each rerun, so refreshing the browser resumes the interview where it was.
"""

import streamlit as st
from drill_ui import drill_offer
from report_view import render_report
from ui_common import current_user_id, engine_deps, get_engine, kept_widget, page_link, safe_md, settings

from interview_app.applications import list_applications
from interview_app.evaluation.service import EvaluationError, evaluate_session
from interview_app.history import load_report
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
        page_link("pages/applications.py", label="Go to Applications", icon=":material/folder_open:")
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
    # One key per interview type: each type keeps the user's choice when they switch back and forth, and
    # a type not touched yet starts at its saved or usual length (like the Settings page's slider).
    main_questions = kept_widget(
        st.slider,
        f"start_main_questions_{interview_type.value}",
        prefs.main_questions or DEFAULT_MAIN_QUESTIONS[interview_type],
        "Main questions (follow-ups come on top)",
        3,
        12,
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
    page_link("pages/settings.py", label="Defaults, prompt and model settings", icon=":material/settings:")

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
        st.caption(f":material/lightbulb: {safe_md(live.tip)}")


def earlier_attempts(view: eng.SessionView, turn: eng.TurnView, previous_idx: int) -> None:
    """Superseded attempts for this answer: those stored between the previous kept turn and this one."""
    attempts = [a for a in view.superseded if previous_idx < a.idx < turn.idx]
    for n, attempt in enumerate(attempts, start=1):
        label = "Earlier attempt" if len(attempts) == 1 else f"Earlier attempt {n}"
        with st.expander(label):
            st.markdown(safe_md(attempt.text))
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
            # Kept in session_state like guard_notice: st.rerun() below would wipe an st.error at once.
            st.session_state.interview_error = str(e)
            st.rerun()
            return
    if not outcome.accepted:
        # Keep the warning across the rerun so the user sees why nothing happened, and keep the blocked
        # text so it can be edited and sent again instead of being typed from scratch.
        st.session_state.guard_notice = outcome.guard.reason or "That answer could not be sent."
        # A new widget key per block: a keyed text area keeps its old content and would ignore the newly
        # blocked text (when "Send again" is blocked too).
        previous = st.session_state.get("blocked_answer") or {}
        st.session_state.blocked_answer = {
            "session": view.id,
            "action": "retry" if action is eng.retry else "answer",
            "text": text,
            "nonce": previous.get("nonce", 0) + 1,
        }
    else:
        st.session_state.pop("blocked_answer", None)
    st.rerun()


def blocked_answer_editor(view: eng.SessionView) -> bool:
    """A blocked answer comes back in an editable box. Returns True while it is shown (in place of the
    chat input, so there is only one place to type)."""
    blocked = st.session_state.get("blocked_answer")
    if not blocked or blocked["session"] != view.id:
        return False
    text = st.text_area(
        "Your answer (not sent: edit it and send again)",
        value=blocked["text"],
        key=f"blocked_text_{blocked['nonce']}",
    )
    col1, col2 = st.columns(2)
    if col1.button("Send again", type="primary", icon=":material/send:"):
        submit(eng.retry if blocked["action"] == "retry" else eng.answer, view, text)
    if col2.button("Discard", icon=":material/close:"):
        st.session_state.pop("blocked_answer", None)
        st.rerun()
    return True


def coaching_choice(view: eng.SessionView) -> None:
    """Coaching mode, after an answer: retry it (up to the limit) or continue to the next question."""
    left = settings().limits.max_retries_per_answer - view.retries_used
    retries_left = f"{left} retr{'y' if left == 1 else 'ies'} left for this answer."
    if st.session_state.get("retrying") == view.id:
        st.caption(retries_left + " The last attempt counts.")
        if st.button("Keep my answer", icon=":material/undo:"):
            st.session_state.pop("retrying", None)
            st.rerun()
        if text := st.chat_input("Your new answer"):
            st.session_state.pop("retrying", None)
            submit(eng.retry, view, text)
        return
    st.caption(retries_left)
    col1, col2 = st.columns(2)
    if col1.button(
        "Retry this answer",
        icon=":material/replay:",
        disabled=left <= 0,
        help=retries_left + " The last attempt counts.",
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
    # A retry started in another interview must not put this one into retry mode.
    if st.session_state.get("retrying") not in (None, view.id):
        st.session_state.pop("retrying", None)
    st.caption(
        f"{safe_md(view.company, inline=True)} — {safe_md(view.role, inline=True)}"
        f" · {TYPE_LABELS[view.config.interview_type]}" + (" · Coaching mode" if coaching else "")
    )
    if view.status == "preparing":
        # The opening turn never arrived (the app was closed or crashed while preparing). Without this the
        # page would wait forever, because an unfinished session blocks starting a new one.
        st.warning(
            "This interview is still being prepared, or preparing it was interrupted. If nothing changes "
            "in a minute, end it and start a new one.",
            icon=":material/hourglass_empty:",
        )
        if st.button("End this interview", type="primary", icon=":material/stop:"):
            eng.end_interview(engine_deps(), user_id, view.id)
            st.session_state.pop("viewing_session", None)
            st.rerun()
        return
    if focus := view.config.focus:
        targets = focus.requirements + focus.skills
        st.info(
            "Focused practice on: " + "; ".join(safe_md(t, inline=True) for t in targets),
            icon=":material/target:",
        )
    progress = view.progress
    done = min(progress.main_asked, view.config.main_questions)
    st.progress(
        done / view.config.main_questions, text=f"Main questions: {done} of {view.config.main_questions}"
    )

    previous_idx = -1
    for t in view.turns:
        if t.speaker == "interviewer":
            with st.chat_message("assistant", avatar=":material/person:"):
                st.markdown(f"**{persona.name}** · {persona.title}\n\n{safe_md(t.text)}")
        else:
            with st.chat_message("user"):
                st.markdown(safe_md(t.text))
                if coaching:
                    if t.live:
                        live_chips(t.live)
                    earlier_attempts(view, t, previous_idx)
        previous_idx = t.idx

    if view.status == "active":
        if blocked_answer_editor(view):
            pass
        elif progress.last_speaker == "candidate" and coaching:
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
        if error := st.session_state.pop("interview_error", None):
            st.error(error)

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
    # Read straight from the DB: building engine_deps (API clients) on every rerun just to read a row
    # was wasted work.
    report = load_report(engine, user_id, view.id)
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
elif (
    (sid := st.session_state.get("viewing_session"))
    and (view := eng.get_session(engine, user_id, sid))
    and view.status != "failed"  # a start that failed has nothing to show: offer a new start instead
):
    chat(view)  # just finished: keep the transcript on screen until a new interview starts
else:
    start_form()
