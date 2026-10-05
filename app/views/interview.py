"""Interview page: pick an application, configure the interview, then talk to the interviewer.

The page holds no interview state of its own: the engine stores every turn in the database and the
page re-reads it on each rerun, so refreshing the browser resumes the interview where it was.
"""

import hashlib

import streamlit as st
from drill_ui import drill_offer
from report_view import render_report, session_badge
from ui_common import (
    CANDIDATE_AVATAR,
    INTERVIEWER_AVATAR,
    button_row,
    current_user_id,
    engine_deps,
    form_row,
    get_engine,
    kept_widget,
    mic_recording,
    page_link,
    panel,
    safe_md,
    slider_start,
)

from interview_app.applications import list_applications
from interview_app.config import get_settings
from interview_app.evaluation.service import EvaluationError, evaluate_session
from interview_app.history import load_report
from interview_app.interview import engine as eng
from interview_app.interview.persona import (
    CHANNEL_LABELS,
    DEFAULT_MAIN_QUESTIONS,
    LENGTH_LABELS,
    TYPE_LABELS,
    Channel,
    Difficulty,
    InterviewType,
    Length,
    Mode,
)
from interview_app.interview.schemas import Stage
from interview_app.preferences import (
    judge_model,
    load_preferences,
    preset_main_questions,
    to_session_config,
)
from interview_app.voice import speak, stored_audio, transcribe

engine = get_engine()
user_id = current_user_id()

st.title("Interview")

# Plain-words names for the interviewer's stages, shown next to the progress bar.
STAGE_LABELS = {
    Stage.OPENING: "Introduction",
    Stage.MOTIVATION: "Motivation",
    Stage.EXPERIENCE: "Experience",
    Stage.TECHNICAL: "Technical",
    Stage.BEHAVIORAL: "Behavioral",
    Stage.GAP: "The tough question",
    Stage.LOGISTICS: "Logistics",
    Stage.CANDIDATE_QUESTIONS: "Your questions for the interviewer",
    Stage.CLOSE: "Wrap-up",
}
LENGTH_HELP = (
    "Quick: a short practice on the core questions. Full: the real interview. "
    "Custom: pick the number of questions yourself."
)
CHANNEL_HELP = (
    "Voice: the interviewer speaks each question and you can answer by speaking (or typing). "
    "Text: you read the questions and type your answers."
)
DIFFICULTY_HELP = "Friendly: supportive, one follow-up per topic. Tough: probes gaps and assumptions harder."

MODE_LABELS = {Mode.REALISTIC.value: "Realistic", Mode.COACHING.value: "Coaching"}
MODE_CAPTIONS = {
    Mode.REALISTIC.value: "Like the real thing: feedback at the end.",
    Mode.COACHING.value: "Feedback after every answer, with retries.",
}


def start_form() -> None:
    apps = list_applications(engine, user_id)
    if not apps:
        st.info("Add an application first (job description + CV).")
        page_link("views/applications.py", label="Go to Applications", icon=":material/folder_open:")
        return

    # Saved preferences (Settings page) pre-fill the form; the developer part (prompt variant, model
    # settings) is not shown here at all and flows into the session through to_session_config.
    prefs = load_preferences(engine, user_id)

    st.caption("Set up a mock interview for one of your applications. Your saved defaults are pre-filled.")
    labels = {a.id: f"{a.company} — {a.role}" for a in apps}
    # "Practise this application" on the Applications page pre-selects it here (read once).
    picked = st.session_state.pop("start_app_pick", None)
    # Three panels, one per decision, in the order they are made. Inside "The interview" the four settings sit
    # in a 2 x 2 grid (form_row): the rows share their columns, and the controls of a row are level.
    with panel(key="start-app"):
        st.markdown("**1. Application**")
        app_id = st.selectbox(
            "Application",
            options=list(labels),
            format_func=labels.get,
            index=list(labels).index(picked) if picked in labels else 0,
            label_visibility="collapsed",
        )
    limits = get_settings().limits
    with panel(key="start-interview"):
        st.markdown("**2. The interview**")
        col1, col2 = form_row(2, key="start-kind")
        # Options are plain strings (enum values) and labels come from a lookup: widgets compare
        # options by value across reruns, which is simplest and most robust with plain strings.
        interview_type = InterviewType(
            col1.selectbox(
                "Interview type",
                options=[t.value for t in InterviewType],
                format_func=lambda v: TYPE_LABELS[InterviewType(v)],
                index=list(InterviewType).index(prefs.interview_type),
                help="Who you are talking to. Each type has its own interviewer, focus and usual length.",
            )
        )
        difficulty = col2.segmented_control(
            "Difficulty",
            options=[d.value for d in Difficulty],
            default=prefs.difficulty.value,
            format_func=str.capitalize,
            help=DIFFICULTY_HELP,
        )
        col3, col4 = form_row(2, key="start-length")
        length = Length(
            col3.segmented_control(
                "Length",
                options=[v.value for v in Length],
                default=prefs.length.value,
                format_func=lambda v: LENGTH_LABELS[Length(v)],
                help=LENGTH_HELP,
            )
            # Clicking the selected segment again deselects it; fall back to the saved default.
            or prefs.length
        )
        channel = Channel(
            col4.segmented_control(
                "Channel",
                options=[c.value for c in Channel],
                default=prefs.channel.value,
                format_func=lambda v: CHANNEL_LABELS[Channel(v)],
                help=CHANNEL_HELP,
            )
            or prefs.channel
        )
        main_questions = None
        if length == Length.CUSTOM:
            # One key per interview type: each type keeps the user's choice when they switch back and
            # forth, and a type not touched yet starts at its saved or usual length (like Settings).
            main_questions = kept_widget(
                st.slider,
                f"start_main_questions_{interview_type.value}",
                slider_start(prefs.main_questions or DEFAULT_MAIN_QUESTIONS[interview_type]),
                "Main questions (follow-ups come on top)",
                limits.min_main_questions,
                limits.max_main_questions,
                help="Each main question opens a topic; the interviewer may ask follow-ups before moving on.",
            )
        else:
            count = preset_main_questions(length, get_settings().length_presets, interview_type)
            st.caption(f"{LENGTH_LABELS[length]}: {count} main questions, follow-ups come on top.")
    with panel(key="start-mode"):
        st.markdown("**3. Feedback style**")
        mode = st.radio(
            "Mode",
            options=list(MODE_LABELS),
            format_func=MODE_LABELS.get,
            captions=list(MODE_CAPTIONS.values()),
            index=list(MODE_LABELS).index(prefs.mode.value),
            horizontal=True,
            label_visibility="collapsed",
        )
    # Developer options live on the Settings page (course task M9): a candidate doesn't need them here.
    page_link("views/settings.py", label="Defaults, prompt and model settings", icon=":material/settings:")

    with button_row(key="start"):
        start_clicked = st.button("Start interview", type="primary", icon=":material/play_arrow:")
    if start_clicked:
        config = to_session_config(
            prefs,
            interview_type=interview_type,
            difficulty=Difficulty(difficulty or Difficulty.STANDARD),
            length=length,
            channel=channel,
            # Only used for Custom: a preset length takes its count from config (to_session_config).
            main_questions=main_questions,
            mode=Mode(mode),
        )
        # st.status rather than a bare spinner: the start is the slowest wait in the app, so it says
        # what is happening and keeps a visible end state (done or failed).
        with st.status("Preparing your interview…", expanded=True) as status:
            st.write(
                "The interviewer is reading your documents, planning the questions and writing the "
                "opening one. This takes about 30 seconds."
            )
            try:
                eng.start_interview(engine_deps(), user_id, app_id, config)
            except eng.InterviewError as e:
                status.update(label="The interview could not start", state="error")
                st.error(str(e))
                return
            status.update(label="Interview ready", state="complete")
        st.rerun()
    else:
        st.caption("Preparing takes about 30 seconds. You can end the interview at any time.")


def live_chips(live) -> None:
    """Coaching mode: the answer's live rubric scores as small coloured badges, then the tip."""
    chips = []
    for item in live.items:
        # Colour by level so the weakest item stands out at a glance, plus an icon so the signal doesn't
        # rely on colour alone (colour-blind users, greyscale screenshots).
        color, icon = (
            ("red", ":material/priority_high:")
            if item.level <= 2
            else ("orange", ":material/remove:")
            if item.level == 3
            else ("green", ":material/check:")
        )
        chips.append(f":{color}-badge[{icon} {item.name} {item.score:.1f}/5]")
    st.markdown("Live scores " + " ".join(chips))
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
    with button_row(key="blocked"):
        send = st.button("Send again", type="primary", icon=":material/send:")
        discard = st.button("Discard", icon=":material/close:")
    if send:
        submit(eng.retry if blocked["action"] == "retry" else eng.answer, view, text)
    if discard:
        st.session_state.pop("blocked_answer", None)
        st.rerun()
    return True


def _spoken_memo(view: eng.SessionView, context: str) -> dict:
    """The transcript-draft memo of one answer box ("answer", or "retry" in Coaching mode).

    It lives in session_state only: a draft is never stored and never reaches a model until it is sent.
    `nonce` is part of the mic's widget key; `digest` is the hash of the recording already transcribed.
    """
    memos = st.session_state.setdefault("spoken_answer", {})
    memo = memos.get(context)
    if memo is None or memo["session"] != view.id:
        nonce = memo["nonce"] + 1 if memo else 0  # a fresh mic for the new session, too
        memo = {"session": view.id, "nonce": nonce, "digest": None, "draft": None, "notice": None}
        memos[context] = memo
    return memo


def clear_spoken(view: eng.SessionView, context: str) -> None:
    """Forget the draft and empty the mic. The mic gets a new widget key: a keyed st.audio_input keeps its
    recording across reruns, which would bring the old answer straight back."""
    memo = _spoken_memo(view, context)
    memo.update(nonce=memo["nonce"] + 1, digest=None, draft=None, notice=None)


def spoken_answer(view: eng.SessionView, context: str, label: str) -> str | None:
    """Voice sessions: the mic, then the transcript draft with Send and Re-record (speak-then-confirm).

    Returns the confirmed text when Send is pressed, else None. The caller sends it through the normal
    answer path (eng.answer / eng.retry), so the guard, storage and judging see exactly what a typed answer
    gets. Text sessions show no mic.
    """
    if view.config.channel != Channel.VOICE:
        return None
    cfg = get_settings()
    memo = _spoken_memo(view, context)
    audio = mic_recording(
        label,
        key=f"mic-{context}-{view.id}-{memo['nonce']}",
        sample_rate=cfg.stt.sample_rate,
        help="Record, stop, then check the transcript before sending. Recordings are not kept.",
    )
    # Every click reruns the page with the same recording still in the widget: transcribe each recording
    # once (by its hash), or each rerun would pay for it again and overwrite the candidate's edits.
    if audio is not None and (digest := hashlib.sha256(audio).hexdigest()) != memo["digest"]:
        with st.spinner("Transcribing your answer…"):
            outcome = transcribe(engine, cfg, engine_deps().make_llm, user_id, view.id, audio)
        memo.update(digest=digest, draft=outcome.text, notice=outcome.notice)
    if memo["notice"]:
        st.caption(f":material/mic_off: {memo['notice']}")
    if memo["draft"] is None:
        return None
    text = st.text_area(
        "Your spoken answer (check it, fix any misheard words, then send)",
        value=memo["draft"],
        key=f"draft-{context}-{view.id}-{memo['nonce']}",
    )
    with button_row(key=f"spoken-{context}"):
        send = st.button("Send", type="primary", icon=":material/send:", key=f"spoken-send-{context}")
        again = st.button("Re-record", icon=":material/mic:", key=f"spoken-again-{context}")
    if again:
        clear_spoken(view, context)
        st.rerun()
    if send:
        clear_spoken(view, context)
        return text
    return None


def coaching_choice(view: eng.SessionView) -> None:
    """Coaching mode, after an answer: retry it (up to the limit) or continue to the next question."""
    left = get_settings().limits.max_retries_per_answer - view.retries_used
    retries_left = f"{left} retr{'y' if left == 1 else 'ies'} left for this answer."
    if st.session_state.get("retrying") == view.id:
        st.caption(retries_left + " The last attempt counts.")
        with button_row(key="keep"):
            keep = st.button("Keep my answer", icon=":material/undo:")
        if keep:
            st.session_state.pop("retrying", None)
            clear_spoken(view, "retry")
            st.rerun()
        if (spoken := spoken_answer(view, "retry", "Record your new answer")) is not None:
            st.session_state.pop("retrying", None)
            submit(eng.retry, view, spoken)
        if text := st.chat_input("Your new answer"):
            st.session_state.pop("retrying", None)
            clear_spoken(view, "retry")
            submit(eng.retry, view, text)
        return
    with panel(key="coach"):
        st.markdown("**Your answer is scored.** Try it again with the tip in mind, or move on.")
        st.caption(retries_left)
        # Both buttons are drawn before either click is handled, so the row never loses a button while
        # Continue waits for the interviewer. Primary action first; the row gives both one size.
        with button_row(key="coach"):
            go_on = st.button("Continue", type="primary", icon=":material/arrow_forward:")
            retry = st.button(
                "Retry this answer",
                icon=":material/replay:",
                disabled=left <= 0,
                help=retries_left + " The last attempt counts.",
            )
    if retry:
        st.session_state.retrying = view.id
        st.rerun()
    if go_on:
        with st.spinner(f"{view.persona.name} is thinking…"):
            try:
                eng.continue_interview(engine_deps(), user_id, view.id)
            except eng.InterviewError as e:
                st.error(str(e))  # the answer is stored: pressing Continue again retries
                return
        st.rerun()


def interviewer_message(view: eng.SessionView, t: eng.TurnView, newest: bool) -> None:
    """One interviewer turn. Text sessions show the text; Voice sessions show a player with the text behind
    "Show text", and the text by itself whenever there is no audio (so a TTS problem never blocks anyone)."""
    persona = view.persona
    header = f"**{safe_md(persona.name, inline=True)}** · {safe_md(persona.title, inline=True)}"
    with_text = f"{header}\n\n{safe_md(t.text)}"
    if view.config.channel != Channel.VOICE:
        st.markdown(with_text)
        return
    cfg = get_settings()
    key = f"{view.id}-{t.idx}"
    notices = st.session_state.setdefault("voice_notices", {})
    path = stored_audio(engine, cfg, user_id, view.id, t.idx)
    # Generate only the newest question of a running interview (or its closing words), once: replays and
    # older turns read the stored file, and a failure is remembered so a rerun doesn't pay for it again.
    if path is None and newest and key not in notices and (view.status == "active" or t.is_final):
        with st.spinner(f"{persona.name} is speaking…"):
            outcome = speak(engine, cfg, engine_deps().make_llm, user_id, view.id, t.idx)
        path = outcome.path
        if path is None:
            notices[key] = outcome.notice
    if path is None:
        st.markdown(with_text)
        st.caption(
            f":material/subtitles: {notices.get(key) or 'No audio for this question, so the text is shown.'}"
        )
        return
    st.markdown(header)
    # Autoplay the newest question once: without the memo, every rerun (e.g. "Show text") would replay it.
    played = st.session_state.setdefault("voice_autoplayed", set())
    st.audio(str(path), format="audio/wav", autoplay=newest and key not in played)
    if newest:
        played.add(key)
    if st.toggle("Show text", key=f"show_text_{key}", help="Practise listening; check a word you missed."):
        st.markdown(safe_md(t.text))


def progress_text(view: eng.SessionView, done: int) -> str:
    """'Question 3 of 7 · Experience (follow-up)': where the interview is, in words."""
    text = f"Question {done} of {view.config.main_questions}"
    last = next((t for t in reversed(view.turns) if t.speaker == "interviewer"), None)
    if last is not None and last.stage in STAGE_LABELS:
        text += f" · {STAGE_LABELS[Stage(last.stage)]}" + (" (follow-up)" if last.is_followup else "")
    return text


def chat(view: eng.SessionView) -> None:
    persona = view.persona
    coaching = view.config.mode == Mode.COACHING
    # A retry started in another interview must not put this one into retry mode.
    if st.session_state.get("retrying") not in (None, view.id):
        st.session_state.pop("retrying", None)
    # The session's facts in one panel above the conversation: what is practised, how, and with whom.
    with panel(key="session-head"):
        st.markdown(
            f"**{safe_md(view.company, inline=True)}** — {safe_md(view.role, inline=True)}  \n"
            f":gray-badge[{TYPE_LABELS[view.config.interview_type]}] "
            f":gray-badge[{view.config.difficulty.value.capitalize()}] "
            f":gray-badge[{MODE_LABELS[view.config.mode.value]} mode] "
            f"{session_badge(view.config)}"
        )
        st.caption(
            f"Your interviewer: {safe_md(persona.name, inline=True)}, {safe_md(persona.title, inline=True)}"
        )
    if view.status == "preparing":
        # The opening turn never arrived (the app was closed or crashed while preparing). Without this the
        # page would wait forever, because an unfinished session blocks starting a new one.
        st.warning(
            "This interview is still being prepared, or preparing it was interrupted. If nothing changes "
            "in a minute, end it and start a new one.",
            icon=":material/hourglass_empty:",
        )
        with button_row(key="end-stuck"):
            end_stuck = st.button("End this interview", type="primary", icon=":material/stop:")
        if end_stuck:
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
    st.progress(done / view.config.main_questions, text=progress_text(view, done))

    previous_idx = -1
    newest_question = max((t.idx for t in view.turns if t.speaker == "interviewer"), default=None)
    for t in view.turns:
        if t.speaker == "interviewer":
            with st.chat_message("assistant", avatar=INTERVIEWER_AVATAR):
                interviewer_message(view, t, newest=t.idx == newest_question)
        else:
            with st.chat_message("user", avatar=CANDIDATE_AVATAR):
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
            with button_row(key="try-again"):
                try_again = st.button("Try again", icon=":material/refresh:")
            if try_again:
                with st.spinner(f"{persona.name} is thinking…"):
                    try:
                        eng.respond(engine_deps(), user_id, view.id)
                    except eng.InterviewError as e:
                        st.error(str(e))
                        return
                st.rerun()
        else:
            # Voice: the mic first, the chat box still below it (a noisy room, or a mic that won't work).
            if (spoken := spoken_answer(view, "answer", "Record your answer")) is not None:
                submit(eng.answer, view, spoken)
            if text := st.chat_input(
                "Your answer (ask your own questions here too)"
                if progress.in_candidate_questions
                else "Your answer",
                max_chars=get_settings().limits.max_answer_chars,
            ):
                clear_spoken(view, "answer")  # a typed answer replaces any unsent transcript draft
                submit(eng.answer, view, text)

        if notice := st.session_state.pop("guard_notice", None):
            st.warning(notice, icon=":material/shield:")
        if error := st.session_state.pop("interview_error", None):
            st.error(error)

        with st.sidebar:
            # No st.divider here: the navigation already ends with a rule, and two rules left a gap.
            st.caption("This interview")
            st.metric("Cost so far", f"${view.cost_usd:.4f}")
            if st.button(
                "End interview",
                icon=":material/stop:",
                help="Stop now. You can still get a feedback report on the answers given so far.",
            ):
                eng.end_interview(engine_deps(), user_id, view.id)
                st.rerun()
    else:
        st.success(
            "Interview complete." if view.status == "finished" else "Interview ended.",
            icon=":material/flag:",
        )
        feedback(view)
        st.divider()
        with button_row(key="new"):
            new_clicked = st.button("Start a new interview", type="primary", icon=":material/add:")
        if new_clicked:
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
        st.markdown(
            "A judge model scores every answer against the interview rubric and writes what went well, "
            "what to improve and a stronger version of your weakest answer."
        )
        with button_row(key="get-report"):
            get_report = st.button("Get my feedback report", type="primary", icon=":material/assessment:")
        if not get_report:
            return
        with st.status("Writing your feedback report…", expanded=True) as status:
            st.write(
                "The judge reads the whole transcript several times independently and the report uses the "
                "median, so one unlucky run can't swing your score. This takes about a minute."
            )
            try:
                prefs = load_preferences(engine, user_id)
                report = evaluate_session(
                    engine_deps(), user_id, view.id, judge_model=judge_model(prefs, get_settings())
                )
            except EvaluationError as e:
                status.update(label="The report could not be written", state="error")
                st.error(str(e))
                st.caption("Your interview is saved: press the button again to retry.")
                return
            status.update(label="Report ready", state="complete", expanded=False)
    render_report(report, get_settings().rubric_path, view.config)
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
