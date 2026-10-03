"""The design system's stylesheet stays a static file: no placeholders, no data, one argument-free loader."""

import ast
import inspect
import re
import sys

import pytest

from interview_app.config import PROJECT_ROOT

APP_DIR = PROJECT_ROOT / "app"
CSS = APP_DIR / "styles" / "app.css"

# Markers of a template that would be filled from data: str.format / f-string fields ({name}, {0}, {}),
# doubled braces, ${...} (JS/shell/string.Template), $name, %(name)s and %s. CSS rule braces are always
# followed by whitespace or a newline, so they don't match.
PLACEHOLDER = re.compile(r"\{\{|\}\}|\$\{|\$[A-Za-z_]|%\(|%s|\{\s*\w*\s*\}")


@pytest.fixture
def ui_common(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_DIR))
    import ui_common

    yield ui_common
    sys.modules.pop("ui_common", None)


def test_stylesheet_has_no_template_placeholders():
    css = CSS.read_text(encoding="utf-8")
    assert css.strip(), "the stylesheet is empty"
    assert not PLACEHOLDER.findall(css)
    # No markup either: the file is wrapped in <style> as it is, so a "</style>" would end it early.
    assert "<" not in css


def test_placeholder_check_catches_template_markers():
    for template in ("color: {color};", "a {{ b }}", "url(${x})", "content: '%(name)s'", "x: {}", "$var"):
        assert PLACEHOLDER.search(template), template
    assert not PLACEHOLDER.search(".a {\n  color: red;\n}\n.b > .c { gap: 1rem; }")


def test_loader_takes_no_arguments_and_passes_only_the_static_path(ui_common, monkeypatch):
    assert inspect.signature(ui_common.load_styles).parameters == {}
    assert ui_common.STYLESHEET == CSS
    calls = []
    monkeypatch.setattr(ui_common.st, "html", lambda *args, **kwargs: calls.append((args, kwargs)))
    ui_common.load_styles()
    # The Path itself (Streamlit reads the file), not a string the code could have built.
    assert calls == [((CSS,), {})]


def test_loader_builds_no_strings(ui_common):
    # No f-strings, .format or concatenation in the loader: nothing can be mixed into what st.html gets.
    tree = ast.parse(inspect.getsource(ui_common.load_styles))
    for node in ast.walk(tree):
        assert not isinstance(node, ast.JoinedStr | ast.BinOp)
        assert not (isinstance(node, ast.Attribute) and node.attr in {"format", "replace", "join"})


def test_no_page_injects_html_from_data():
    # unsafe_allow_html would render markup; every page passes untrusted text through safe_md instead.
    for path in APP_DIR.rglob("*.py"):
        assert not re.search(r"unsafe_allow_html\s*=\s*True", path.read_text(encoding="utf-8")), path


def test_sentence_case_keeps_acronyms(ui_common):
    assert ui_common.sentence_case("job description") == "Job description"
    assert ui_common.sentence_case("CV") == "CV"
    assert ui_common.sentence_case("") == ""


def _rule(css: str, selector_end: str) -> str:
    """The declarations of the first rule with a selector (in its comma list) ending in `selector_end`."""
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if any(sel.strip().endswith(selector_end) for sel in selectors.split(",")):
            return body
    raise AssertionError(f"no rule for {selector_end!r}")


def test_selected_options_are_not_marked_by_accent_text_alone():
    # The accent is only 3.5:1 on the dark background, so a selected segment keeps the text colour and is
    # marked by weight and a ring as well (WCAG 1.4.1 and 1.4.3).
    css = CSS.read_text(encoding="utf-8")
    body = _rule(css, 'button[aria-checked="true"]')
    assert "color: inherit" in body and "box-shadow" in body
    assert "font-weight: 600" in _rule(css, 'button[aria-checked="true"] p')


def test_every_focusable_kind_has_a_visible_focus_ring():
    css = CSS.read_text(encoding="utf-8")
    for selector in (
        "button:focus-visible",
        "audio:focus-visible",
        "canvas:focus-visible",
        "div:has(> textarea:focus-visible)",
    ):
        assert "outline: 2px solid" in _rule(css, selector), selector
    assert "outline: 2px solid" in _rule(css, "label:has(input:focus-visible) > span + div")
