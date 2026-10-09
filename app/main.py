"""Entry point: `uv run streamlit run app/main.py`.

Only page registration lives here. Each page is a script in app/views/ and calls the core
package (src/interview_app) for all real work.

The folder is `views/`, not `pages/`: Streamlit treats a `pages/` folder next to the entry script as
legacy auto-navigation, and a deep link opened right after a server start (a tab reconnecting after a
restart) then showed the raw file list instead of these sections.
"""

import logging

import streamlit as st
from ui_common import interview_running_note, load_styles, navigation_position

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title="Interview Helper", page_icon=":material/record_voice_over:", layout="wide")
# The design system's stylesheet (a static file), drawn on every run so every page gets it.
load_styles()

# Pages in the order of the user's journey (documents -> interview -> results), grouped so the sidebar
# reads as a path rather than a flat list. Settings sit apart: they are rarely needed.
pages = {
    "Practise": [
        st.Page("views/home.py", title="Home", icon=":material/home:", default=True),
        st.Page("views/dashboard.py", title="Dashboard", icon=":material/insights:"),
        st.Page("views/applications.py", title="Applications", icon=":material/folder_open:"),
        st.Page("views/interview.py", title="Interview", icon=":material/forum:"),
        st.Page("views/history.py", title="History", icon=":material/history:"),
    ],
    "Setup": [st.Page("views/settings.py", title="Settings", icon=":material/settings:")],
}
# Hidden while an interview runs: the Interview page's "Exit interview" dialog is then the way out.
position = navigation_position()
page = st.navigation(pages, position=position)
# Remember the page the previous run showed, so a page can tell "entered from another page" from a rerun of
# itself: the Interview page shows a finished interview right after it ends, but the start form when the
# candidate comes back later.
st.session_state.page_entered = st.session_state.get("current_page") != page.url_path
st.session_state.current_page = page.url_path
interview_running_note(page.url_path)
page.run()
