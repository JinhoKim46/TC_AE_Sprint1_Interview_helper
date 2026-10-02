from interview_app.config import Settings


def test_defaults_follow_course_requirements():
    s = Settings(_env_file=None)
    assert s.models.interviewer == "openai/gpt-5-mini"  # requirement R3
    assert s.models.judge.split("/")[0] != s.models.interviewer.split("/")[0]  # different family


def test_nested_settings_from_env(monkeypatch):
    monkeypatch.setenv("MODELS__INTERVIEWER", "openai/gpt-5")
    monkeypatch.setenv("LIMITS__MAX_MAIN_QUESTIONS", "5")
    s = Settings(_env_file=None)
    assert s.models.interviewer == "openai/gpt-5"
    assert s.limits.max_main_questions == 5


def test_secrets_are_not_printed():
    s = Settings(_env_file=None, openrouter_api_key="sk-secret")
    assert "sk-secret" not in repr(s)
