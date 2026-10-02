"""Headless UI tests with Streamlit's AppTest: the pages run for real against a temp database."""

import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from interview_app.config import PROJECT_ROOT, get_settings

APP_DIR = PROJECT_ROOT / "app"


@pytest.fixture(autouse=True)
def temp_database(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ui.db'}")
    monkeypatch.syspath_prepend(str(APP_DIR))  # pages import ui_common like Streamlit does
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    sys.modules.pop("ui_common", None)  # fresh st.cache_resource engine per test


def run_page(name: str) -> AppTest:
    """Run one page directly (no navigation context)."""
    at = AppTest.from_file(str(APP_DIR / "pages" / name), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def test_home_prompts_to_add_an_application():
    # Through main.py, so st.navigation is set up (home uses st.page_link).
    at = AppTest.from_file(str(APP_DIR / "main.py"), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    assert "Start by adding an application" in at.info[0].value


def test_load_sample_then_it_is_listed():
    at = run_page("applications.py")
    next(b for b in at.button if b.label == "Load sample application").click().run()
    assert not at.exception
    assert any("Northwind Robotics" in e.label for e in at.expander)


def test_saving_without_required_documents_shows_error():
    at = run_page("applications.py")
    at.text_input(key="new_company").input("Acme")
    at.text_input(key="new_role").input("Engineer")
    next(b for b in at.button if b.label == "Save application").click().run()
    assert at.error and "job description" in at.error[0].value.lower()


def test_create_application_from_pasted_text():
    jd = "We need a data engineer with Python, SQL and Airflow experience. " * 10
    cv = "Data engineer, 5 years of Python, SQL and Airflow pipelines at a retail company. " * 10
    at = run_page("applications.py")
    at.text_input(key="new_company").input("Acme")
    at.text_input(key="new_role").input("Data Engineer")
    at.text_area(key="new_text_jd").input(jd)
    at.text_area(key="new_text_cv").input(cv)
    next(b for b in at.button if b.label == "Save application").click().run()
    assert not at.error
    assert any("Acme" in e.label for e in at.expander)
