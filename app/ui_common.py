"""Shared UI plumbing: cached resources and small helpers used by every page.

Streamlit reruns the whole script on every click, so expensive objects (the DB engine) are
created once with st.cache_resource and reused across reruns.
"""

import streamlit as st
from sqlalchemy.engine import Engine

from interview_app.config import Settings, get_settings
from interview_app.db import init_db, make_engine
from interview_app.users import ensure_local_user


@st.cache_resource
def get_engine() -> Engine:
    engine = make_engine(get_settings().database_url)
    init_db(engine)
    return engine


def settings() -> Settings:
    return get_settings()


def current_user_id() -> int:
    """Single local user for now (see interview_app/users.py)."""
    if "user_id" not in st.session_state:
        st.session_state.user_id = ensure_local_user(get_engine())
    return st.session_state.user_id
