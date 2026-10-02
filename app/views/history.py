"""History page: past interviews, their transcripts and reports, and progress per application.

Read-only over what is stored: this page never calls the interviewer or the judge, so opening it costs
nothing. A report that doesn't exist yet is generated from the Interview page.
"""

import streamlit as st
from drill_ui import drill_offer
from report_view import BAND_LABELS, LEVEL_LABELS, render_report
from ui_common import (
    CANDIDATE_AVATAR,
    INTERVIEWER_AVATAR,
    current_user_id,
    get_engine,
    go_button,
    page_link,
    safe_md,
)

from interview_app.applications import list_applications
from interview_app.config import get_settings
from interview_app.history import SessionSummary, delete_session, list_sessions, load_report, progress
from interview_app.interview.engine import get_session
from interview_app.interview.persona import TYPE_LABELS, InterviewType
from interview_app.journey import score_summary

engine = get_engine()
user_id = current_user_id()

st.title("History")
st.caption("Your past interviews, their reports, and how your scores develop per application.")

STATUS_LABELS = {"active": "In progress", "finished": "Finished", "ended_early": "Ended early"}


def session_label(s: SessionSummary) -> str:
    score = f"{s.overall:.0f}/100" if s.overall is not None else "no score"
    kind = TYPE_LABELS[InterviewType(s.interview_type)]
    return f"{s.started_at:%Y-%m-%d %H:%M} · {s.company} — {kind} · {score}"


def sessions_table(sessions: list[SessionSummary]) -> None:
    def open_selected() -> None:
        # Runs before the rerun draws the widgets, so it may set the selectbox below to the clicked row.
        rows = st.session_state.history_table.selection.rows
        if rows:
            st.session_state.history_open = sessions[rows[0]].session_id

    st.dataframe(
        [
            {
                "Date": s.started_at,
                "Application": f"{s.company} — {s.role}",
                "Type": TYPE_LABELS[InterviewType(s.interview_type)],
                "Difficulty": s.difficulty.capitalize(),
                "Mode": s.mode.capitalize(),
                "Score": s.overall,
                "Result": BAND_LABELS[s.band][0] if s.band in BAND_LABELS else "—",
                "Cost": s.cost_usd,
            }
            for s in sessions
        ],
        column_config={
            "Date": st.column_config.DatetimeColumn("Date (UTC)", format="YYYY-MM-DD HH:mm"),
            "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
            "Cost": st.column_config.NumberColumn("Cost", format="$%.4f"),
        },
        hide_index=True,
        width="stretch",
        key="history_table",
        on_select=open_selected,
        selection_mode="single-row",
    )


def progress_block(application_id: int) -> None:
    st.header("Progress")
    prog = progress(engine, user_id, application_id, get_settings().rubric_path)

    if len(prog.trend) >= 2:
        st.subheader("Overall score over time")
        st.line_chart(
            [{"Date": started_at, "Score": score} for started_at, score in prog.trend], x="Date", y="Score"
        )
    elif prog.trend:
        st.caption("One scored interview so far: the trend appears after the second one.")
    else:
        st.caption("No scored interviews yet: get a feedback report on the Interview page to see a trend.")

    if prog.item_means:
        st.subheader("Skills to work on")
        st.caption("Average answer score per skill (1 = weak, 5 = excellent), weakest first.")
        st.dataframe(
            [{"Skill": m.name, "Average": m.mean, "Answers scored": m.count} for m in prog.item_means],
            column_config={
                "Average": st.column_config.ProgressColumn(
                    "Average (1–5)", min_value=1, max_value=5, format="%.1f"
                )
            },
            hide_index=True,
            width="stretch",
        )

    if prog.requirements:
        st.subheader("Job requirements")
        st.dataframe(
            [
                {
                    "Requirement": r.requirement,
                    "Latest": LEVEL_LABELS.get(r.latest_level, r.latest_level),
                    "History": ", ".join(
                        f"{LEVEL_LABELS.get(level, level)} ×{n}" for level, n in r.level_counts.items()
                    ),
                }
                for r in prog.requirements
            ],
            hide_index=True,
            width="stretch",
        )

    if prog.recurring_improvements:
        st.subheader("Advice that keeps coming back")
        for imp in prog.recurring_improvements:
            st.markdown(f"- **{safe_md(imp.area, inline=True)}** — in {imp.count} reports")


def score_metrics(sessions: list[SessionSummary]) -> None:
    """Three numbers to answer "am I improving?" before any table has to be read."""
    stats = score_summary(sessions)
    m1, m2, m3 = st.columns(3)
    m1.metric("Interviews", len(sessions), help=f"{stats.scored} of them with a feedback report")
    m2.metric(
        "Latest score",
        f"{stats.latest:.0f}" if stats.latest is not None else "—",
        # The delta shows an arrow and a sign as well as a colour, so it reads without colour too.
        delta=f"{stats.change:+.0f} vs previous" if stats.change is not None else None,
        help="Change against the previous interview with a report.",
    )
    m3.metric("Best score", f"{stats.best:.0f}" if stats.best is not None else "—")


def session_detail(summary: SessionSummary) -> None:
    view = get_session(engine, user_id, summary.session_id)
    if view is None:  # deleted in another tab
        st.warning("This interview no longer exists.")
        return
    kind = TYPE_LABELS[InterviewType(summary.interview_type)]
    score = f" · {summary.overall:.0f}/100" if summary.overall is not None else ""
    st.subheader(f"{safe_md(summary.company, inline=True)} — {kind}{score}")
    st.caption(
        f"{summary.started_at:%Y-%m-%d %H:%M} UTC · {STATUS_LABELS.get(view.status, view.status)} · "
        f"{summary.main_questions_asked} main question(s) · {summary.difficulty} · {summary.mode} · "
        f"prompt {summary.prompt_variant} · ${summary.cost_usd:.4f}"
    )

    transcript, report_tab = st.tabs(["Transcript", "Report"])
    with transcript:
        persona = view.persona
        for t in view.turns:
            if t.speaker == "interviewer":
                with st.chat_message("assistant", avatar=INTERVIEWER_AVATAR):
                    st.markdown(
                        f"**{safe_md(persona.name, inline=True)}** · {safe_md(persona.title, inline=True)}"
                        f"\n\n{safe_md(t.text)}"
                    )
            else:
                with st.chat_message("user", avatar=CANDIDATE_AVATAR):
                    st.markdown(safe_md(t.text))
        if not view.turns:
            st.caption("No messages were exchanged.")
    with report_tab:
        report = load_report(engine, user_id, summary.session_id)
        if report is not None:
            render_report(report, get_settings().rubric_path)
            drill_offer(view, report, key=f"drill-history-{summary.session_id}", go_to_interview=True)
        elif view.status == "active":
            st.info("This interview is still in progress. Finish it on the Interview page.")
            go_button("views/interview.py", "Go to the running interview", icon=":material/forum:")
        else:
            # Opening the interview on the Interview page shows its "Get my feedback report" button, so
            # the judge (and its cost) only ever runs from there, on an explicit click.
            st.info("No report yet. Open the interview to get one (about a minute).")
            go_button(
                "views/interview.py",
                "Open it to get feedback",
                icon=":material/assessment:",
                key=f"history_get_report_{summary.session_id}",
                state={"viewing_session": summary.session_id},
            )

    with st.expander("Delete this interview", icon=":material/delete:"):
        # Keyed per session, so a tick given for one interview never carries over to the next one opened.
        confirm_key = f"history_confirm_{summary.session_id}"
        sure = st.checkbox("Yes, delete the transcript and report for good", key=confirm_key)
        if st.button("Delete interview", type="primary", disabled=not sure):
            delete_session(engine, user_id, summary.session_id)
            for key in ("history_open", confirm_key, "history_table"):
                st.session_state.pop(key, None)
            st.toast("Interview deleted")
            st.rerun()


all_sessions = list_sessions(engine, user_id)
if not all_sessions:
    st.info("No interviews yet. Your past interviews and their reports will appear here.")
    page_link("views/interview.py", label="Start an interview", icon=":material/forum:")
    st.stop()

apps = {a.id: f"{a.company} — {a.role}" for a in list_applications(engine, user_id)}
# The remembered filter may point at an application deleted since; fall back to all of them. This must
# run before the selectbox is drawn, because a drawn widget's value can't be changed in the same run.
if st.session_state.get("history_app") not in (None, *apps):
    st.session_state.history_app = None
app_id = st.selectbox(
    "Application",
    options=[None, *apps],
    format_func=lambda a: "All applications" if a is None else apps[a],
    key="history_app",
)
sessions = list_sessions(engine, user_id, app_id)

if sessions:
    score_metrics(sessions)

if app_id is not None:
    progress_block(app_id)
    st.divider()

st.header("Interviews")
if not sessions:
    st.caption("No interviews for this application yet.")
    st.stop()

sessions_table(sessions)
by_id = {s.session_id: s for s in sessions}
# A row picked under another filter, or a deleted session, must not stay selected.
if st.session_state.get("history_open") not in by_id:
    st.session_state.history_open = None
opened = st.selectbox(
    "Open an interview (or click a row above)",
    options=[None, *by_id],
    format_func=lambda sid: "Choose an interview…" if sid is None else session_label(by_id[sid]),
    key="history_open",
)
if opened is not None:
    st.divider()
    session_detail(by_id[opened])
