"""Home: what the app does, where the user is in the flow, and the one thing to do next."""

from collections import defaultdict

import streamlit as st
from report_view import band_badge
from ui_common import current_user_id, get_engine, go_button, safe_md, short

from interview_app.applications import list_applications
from interview_app.history import SessionSummary, list_sessions
from interview_app.journey import Step, next_step

engine = get_engine()
user_id = current_user_id()

st.title("Interview Helper")
st.write(
    "Practise a job interview tailored to **one specific application**: the interviewer reads your "
    "job description, CV and (optionally) cover letter, and asks what this role's interviewers would ask."
)

apps = list_applications(engine, user_id)
sessions = list_sessions(engine, user_id)
step = next_step(len(apps), sessions)

# --- Where you are: three steps, each marked with an icon AND a word (never colour alone) ----------

has_interview = any(s.status != "active" for s in sessions)
has_report = any(s.has_report for s in sessions)
done = [bool(apps), has_interview, has_report]
current = done.index(False) if False in done else None
STEPS = [
    ("Add an application", "The job description and your CV."),
    ("Practise an interview", "About 30 seconds to prepare, then a real conversation."),
    ("Read your feedback", "Scores against a rubric, with quotes and a stronger answer."),
]
for i, (col, (title, detail)) in enumerate(zip(st.columns(3), STEPS, strict=True)):
    with col.container(border=True):
        if done[i]:
            mark = ":green[:material/check_circle:] Done"
        elif i == current:
            mark = ":primary[:material/radio_button_checked:] Next"
        else:
            mark = ":gray[:material/radio_button_unchecked:] Later"
        st.markdown(f"**{i + 1}. {title}**  \n{mark}")
        st.caption(detail)

# --- The next step ---------------------------------------------------------------------------------

newest = max(sessions, key=lambda s: (s.started_at, s.session_id)) if sessions else None
with st.container(border=True):
    st.subheader("Next step")
    if step == Step.ADD_APPLICATION:
        st.info("Start by adding an application: upload the job description and your CV.")
        st.caption("No documents at hand? The Applications page can load a fictional sample.")
        go_button("views/applications.py", "Add an application", icon=":material/add:")
    elif step == Step.START_INTERVIEW:
        st.markdown("Your application is ready. Run your first mock interview.")
        go_button("views/interview.py", "Start an interview", icon=":material/play_arrow:")
    elif step == Step.RESUME_INTERVIEW:
        st.markdown("You have an interview in progress. Pick it up where you left off.")
        go_button("views/interview.py", "Resume the interview", icon=":material/forum:")
    elif step == Step.GET_FEEDBACK and newest is not None:
        st.markdown("Your last interview has no feedback report yet. Writing it takes about a minute.")
        # A horizontal container keeps the buttons side by side at their natural width (columns would
        # stretch them apart on a wide screen) and still wraps on a phone.
        with st.container(horizontal=True):
            go_button(
                "views/interview.py",
                "Get feedback on the last interview",
                icon=":material/assessment:",
                state={"viewing_session": newest.session_id},
            )
            # The way out when that interview had no answers to judge, or the report isn't wanted.
            go_button(
                "views/interview.py",
                "Start a new interview",
                icon=":material/play_arrow:",
                primary=False,
                state={"viewing_session": None},
            )
    else:
        st.markdown(
            "Practise again, or open a report in History and start a focused interview on your weak spots."
        )
        with st.container(horizontal=True):
            go_button("views/interview.py", "Start an interview", icon=":material/play_arrow:")
            go_button("views/history.py", "See your progress", icon=":material/insights:", primary=False)

# --- Applications at a glance ----------------------------------------------------------------------

if apps:
    st.subheader("Your applications")
    by_app: dict[int, list[SessionSummary]] = defaultdict(list)
    for s in sessions:  # newest first, so [0] is the latest interview of that application
        by_app[s.application_id].append(s)
    cols = st.columns(min(len(apps), 3))
    for i, app in enumerate(apps):
        app_sessions = by_app.get(app.id, [])
        latest = next((s for s in app_sessions if s.overall is not None), None)
        with cols[i % len(cols)].container(border=True):
            st.markdown(
                f"**{safe_md(short(app.company, 60), inline=True)}**  \n"
                f"{safe_md(short(app.role, 80), inline=True)}"
            )
            n = len(app_sessions)
            count = f"{n} interview{'' if n == 1 else 's'}" if n else "No interviews yet"
            if latest is not None:
                st.markdown(f"{count} · latest score **{latest.overall:.0f}** {band_badge(latest.band)}")
            else:
                st.caption(count)
