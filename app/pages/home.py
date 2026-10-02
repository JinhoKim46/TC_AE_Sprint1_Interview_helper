import streamlit as st
from ui_common import current_user_id, get_engine

from interview_app.applications import list_applications

st.title("Interview Helper")
st.write(
    "Practise a job interview tailored to **one specific application**: the interviewer reads your "
    "job description, CV and (optionally) cover letter, and asks what this role's interviewers would ask."
)

apps = list_applications(get_engine(), current_user_id())
if not apps:
    st.info("Start by adding an application: upload the job description and your CV.")
    st.page_link("pages/applications.py", label="Add an application", icon=":material/add:")
else:
    st.subheader("Your applications")
    for app in apps:
        st.markdown(f"- **{app.company}** — {app.role}")
    st.page_link("pages/interview.py", label="Start an interview", icon=":material/forum:")
