"""Entry point: `uv run streamlit run app/main.py`.

Only page registration lives here. Each page is a script in app/pages/ and calls the core
package (src/interview_app) for all real work.
"""

import logging

import streamlit as st

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title="Interview Helper", page_icon=":material/record_voice_over:", layout="wide")

pages = [
    st.Page("pages/home.py", title="Home", icon=":material/home:", default=True),
    st.Page("pages/applications.py", title="Applications", icon=":material/folder_open:"),
]
st.navigation(pages).run()
