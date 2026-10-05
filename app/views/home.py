"""Home: what the app does, where the user is in the flow, and the one thing to do next."""

from collections import defaultdict

import streamlit as st
from report_view import band_badge
from ui_common import (
    button_row,
    card_footer,
    card_row,
    current_user_id,
    get_engine,
    go_button,
    panel,
    safe_md,
    short,
)

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
# One card per step in a row of equal-height cards; the state sits in each card's footer so the three
# states line up, and the current step also carries the accent bar.
for i, (card, (title, detail)) in enumerate(
    zip(card_row(len(STEPS), key="steps", highlight=current), STEPS, strict=True)
):
    with card:
        st.markdown(f"**{i + 1}. {title}**")
        st.caption(detail)
        with card_footer(key=f"step-{i}"):
            if done[i]:
                st.markdown(":green[:material/check_circle:] Done")
            elif i == current:
                st.markdown(":primary[:material/radio_button_checked:] Next")
            else:
                st.markdown(":gray[:material/radio_button_unchecked:] Later")

# --- The next step ---------------------------------------------------------------------------------

newest = max(sessions, key=lambda s: (s.started_at, s.session_id)) if sessions else None
with panel(key="next-step"):
    st.subheader("Next step")
    if step == Step.ADD_APPLICATION:
        st.info("Start by adding an application: upload the job description and your CV.")
        st.caption("No documents at hand? The Applications page can load a fictional sample.")
        with button_row(key="next"):
            go_button("views/applications.py", "Add an application", icon=":material/add:")
    elif step == Step.START_INTERVIEW:
        st.markdown("Your application is ready. Run your first mock interview.")
        with button_row(key="next"):
            go_button("views/interview.py", "Start an interview", icon=":material/play_arrow:")
    elif step == Step.RESUME_INTERVIEW:
        st.markdown("You have an interview in progress. Pick it up where you left off.")
        with button_row(key="next"):
            go_button("views/interview.py", "Resume the interview", icon=":material/forum:")
    elif step == Step.GET_FEEDBACK and newest is not None:
        st.markdown("Your last interview has no feedback report yet. Writing it takes about a minute.")
        # A button row gives both buttons one size, side by side; on a phone they stack full width.
        with button_row(key="next"):
            go_button(
                "views/interview.py",
                "Get feedback on the last interview",
                icon=":material/assessment:",
                state={"open_session": newest.session_id},
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
        with button_row(key="next"):
            go_button("views/interview.py", "Start an interview", icon=":material/play_arrow:")
            go_button("views/history.py", "See your progress", icon=":material/insights:", primary=False)

# --- Applications at a glance ----------------------------------------------------------------------

if apps:
    st.subheader("Your applications")
    by_app: dict[int, list[SessionSummary]] = defaultdict(list)
    for s in sessions:  # newest first, so [0] is the latest interview of that application
        by_app[s.application_id].append(s)
    # Equal-height cards: the company and role on top, the interview count and score in a footer that
    # lines up across the row however long the role title is.
    for app, card in zip(apps, card_row(len(apps), key="apps"), strict=True):
        app_sessions = by_app.get(app.id, [])
        latest = next((s for s in app_sessions if s.overall is not None), None)
        with card:
            st.markdown(
                f"**{safe_md(short(app.company, 60), inline=True)}**  \n"
                f"{safe_md(short(app.role, 80), inline=True)}"
            )
            # Always two lines (the count, then the score or "No score yet"): when the count, score and badge
            # shared one line, the badge wrapped in narrow cards and the footers of a row no longer lined up.
            with card_footer(key=f"app-{app.id}"):
                n = len(app_sessions)
                st.caption(f"{n} interview{'' if n == 1 else 's'}" if n else "No interviews yet")
                if latest is not None:
                    st.markdown(f"Latest score **{latest.overall:.0f}** {band_badge(latest.band)}")
                else:
                    st.markdown("No score yet")
