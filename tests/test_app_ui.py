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


def test_interview_page_start_answer_and_reply(monkeypatch):
    """Start an interview from the page and answer once, with a scripted model behind the engine."""
    import json
    from types import SimpleNamespace

    import ui_common

    from interview_app.demo import load_sample_application
    from interview_app.interview.engine import EngineDeps
    from interview_app.llm.client import LLMClient

    replies = [
        json.dumps(
            {
                "stage": "opening",
                "question_id": "OPEN-01",
                "is_followup": False,
                "message": "Hi, walk me through your background.",
                "is_final": False,
            }
        ),
        json.dumps(
            {
                "stage": "experience",
                "question_id": "EXP-EVID-01",
                "is_followup": True,
                "message": "How did you measure that?",
                "is_final": False,
            }
        ),
    ]

    def create(**kwargs):
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content=replies.pop(0)))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, cost=0.0),
        )

    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def fake_deps():
        settings = ui_common.get_settings()
        return EngineDeps(ui_common.get_engine(), settings, lambda uid, sid: LLMClient(settings, sdk=sdk))

    monkeypatch.setattr(ui_common, "engine_deps", fake_deps)
    load_sample_application(ui_common.get_engine(), ui_common.ensure_local_user(ui_common.get_engine()))

    at = AppTest.from_file(str(APP_DIR / "pages" / "interview.py"), default_timeout=30)
    at.run()
    at.selectbox[2].select_index(0)  # developer option: P1 needs no separate planning call
    next(b for b in at.button if b.label == "Start interview").click().run()
    assert not at.exception, at.exception
    assert "walk me through your background" in at.chat_message[0].markdown[0].value

    at.chat_input[0].set_value("I improved mIoU from 0.61 to 0.74.").run()
    assert not at.exception, at.exception
    texts = [m.markdown[0].value for m in at.chat_message]
    assert "I improved mIoU" in texts[1] and "How did you measure that?" in texts[2]
