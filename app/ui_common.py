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


@st.cache_resource
def get_price_catalog():
    from interview_app.llm.pricing import PriceCatalog

    return PriceCatalog(get_settings())


def engine_deps():
    """Wire the interview engine to real models, the call log, pricing and the injection guard."""
    from interview_app.interview.engine import EngineDeps
    from interview_app.llm.calllog import make_db_recorder
    from interview_app.llm.client import LLMClient
    from interview_app.llm.decide import DecisionClient
    from interview_app.security import InjectionGuard

    engine, cfg, user_id = get_engine(), get_settings(), current_user_id()

    def make_llm(uid: int, session_id: int | None) -> LLMClient:
        return LLMClient(cfg, recorder=make_db_recorder(engine, uid, session_id), pricing=get_price_catalog())

    def make_decider(uid: int, session_id: int | None) -> DecisionClient:
        # Bound to the session like make_llm, so guard and live-score calls count in that interview's cost.
        return DecisionClient(cfg, recorder=make_db_recorder(engine, uid, session_id))

    decider = make_decider(user_id, None)
    guard = InjectionGuard(cfg, decider)
    return EngineDeps(
        engine=engine,
        settings=cfg,
        make_llm=make_llm,
        guard=guard,
        decider=decider,
        make_decider=make_decider,
    )


def document_guard():
    """Injection guard for uploaded documents (rules first, then Jev)."""
    from interview_app.llm.calllog import make_db_recorder
    from interview_app.llm.decide import DecisionClient
    from interview_app.security import InjectionGuard

    cfg = get_settings()
    return InjectionGuard(
        cfg, DecisionClient(cfg, recorder=make_db_recorder(get_engine(), current_user_id()))
    )
