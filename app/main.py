"""Entry point: `uv run streamlit run app/main.py`.

Only page registration lives here. Each page is a script in app/views/ and calls the core
package (src/interview_app) for all real work.

The folder is `views/`, not `pages/`: Streamlit treats a `pages/` folder next to the entry script as
legacy auto-navigation, and a deep link opened right after a server start (a tab reconnecting after a
restart) then showed the raw file list instead of these sections.
"""

import logging

import streamlit as st

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title="Interview Helper", page_icon=":material/record_voice_over:", layout="wide")

# Pages in the order of the user's journey (documents -> interview -> results), grouped so the sidebar
# reads as a path rather than a flat list. Settings sit apart: they are rarely needed.
pages = {
    "Practise": [
        st.Page("views/home.py", title="Home", icon=":material/home:", default=True),
        st.Page("views/applications.py", title="Applications", icon=":material/folder_open:"),
        st.Page("views/interview.py", title="Interview", icon=":material/forum:"),
        st.Page("views/history.py", title="History", icon=":material/history:"),
    ],
    "Setup": [st.Page("views/settings.py", title="Settings", icon=":material/settings:")],
}
st.navigation(pages).run()
