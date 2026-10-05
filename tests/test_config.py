import pytest
from pydantic import ValidationError

from interview_app.config import PROJECT_ROOT, GuardSettings, LengthPresets, Limits, Settings, STTSettings


def test_defaults_follow_course_requirements():
    s = Settings(_env_file=None)
    assert s.models.interviewer == "openai/gpt-5-mini"  # requirement R3
    assert s.models.judge.split("/")[0] != s.models.interviewer.split("/")[0]  # different family


def test_nested_settings_from_env(monkeypatch):
    monkeypatch.setenv("MODELS__INTERVIEWER", "openai/gpt-5-nano")
    monkeypatch.setenv("LIMITS__MAX_TURNS", "40")
    s = Settings(_env_file=None)
    assert s.models.interviewer == "openai/gpt-5-nano"
    assert s.limits.max_turns == 40


def test_secrets_are_not_printed():
    s = Settings(_env_file=None, openrouter_api_key="sk-secret")
    assert "sk-secret" not in repr(s)


# --- Validation ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "max_upload_mb",
        "max_pdf_pages",
        "max_document_chars",
        "max_answer_chars",
        "max_turns",
        "max_session_cost_usd",
    ],
)
def test_limits_must_be_positive(field):
    with pytest.raises(ValidationError):
        Limits(**{field: 0})


@pytest.mark.parametrize(
    ("field", "too_big"),
    [("max_upload_mb", 51), ("max_turns", 501), ("max_session_cost_usd", 51), ("max_retries_per_answer", 11)],
)
def test_limits_have_sanity_caps(field, too_big):
    with pytest.raises(ValidationError):
        Limits(**{field: too_big})


def test_zero_retries_per_answer_is_allowed():
    assert Limits(max_retries_per_answer=0).max_retries_per_answer == 0
    with pytest.raises(ValidationError):
        Limits(max_retries_per_answer=-1)


@pytest.mark.parametrize("threshold", [-0.1, 1.1])
def test_injection_threshold_is_a_probability(threshold):
    with pytest.raises(ValidationError):
        GuardSettings(injection_threshold=threshold)


def test_document_chunk_chars_must_be_positive():
    with pytest.raises(ValidationError):
        GuardSettings(document_chunk_chars=0)


@pytest.mark.parametrize("runs", [0, 6])
def test_judge_runs_bounds(runs):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, judge_runs=runs)


def test_judge_runs_defaults_to_rubric():
    assert Settings(_env_file=None).judge_runs is None
    assert Settings(_env_file=None, judge_runs=1).judge_runs == 1


def test_judge_max_tokens(monkeypatch):
    assert Settings(_env_file=None).judge_max_tokens == 16000
    monkeypatch.setenv("JUDGE_MAX_TOKENS", "32000")
    assert Settings(_env_file=None).judge_max_tokens == 32000
    for bad in (999, 64001):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, judge_max_tokens=bad)


def test_out_of_range_env_value_fails(monkeypatch):
    monkeypatch.setenv("LIMITS__MAX_TURNS", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_typo_in_nested_env_var_fails_loudly(monkeypatch):
    monkeypatch.setenv("LIMITS__MAX_TURN", "40")  # missing the final S
    with pytest.raises(ValidationError, match="max_turn"):
        Settings(_env_file=None)


def test_unknown_top_level_env_vars_are_ignored(monkeypatch):
    # Stale keys (the dropped login feature's secret) and other tools' values must not crash startup.
    monkeypatch.setenv("APP_SECRET_KEY", "old")
    monkeypatch.setenv("APP_UID", "1000")
    Settings(_env_file=None)


# --- Database URL -------------------------------------------------------------------------------


def test_database_url_default_is_unchanged():
    assert Settings(_env_file=None).database_url == f"sqlite:///{PROJECT_ROOT / 'data' / 'app.db'}"


def test_database_url_follows_data_dir(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path)
    assert s.database_url == f"sqlite:///{tmp_path / 'app.db'}"


def test_explicit_database_url_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    assert Settings(_env_file=None, data_dir=tmp_path).database_url == "sqlite://"


# --- The test suite itself ----------------------------------------------------------------------


def test_unit_tests_do_not_read_the_developers_env_file():
    # The autouse fixture in conftest.py: a plain Settings() must not see the real .env.
    assert Settings.model_config["env_file"] is None


def test_main_question_slider_bounds():
    limits = Limits()
    assert (limits.min_main_questions, limits.max_main_questions) == (3, 12)
    # Inside SessionConfig's own bounds (2-15), and min below max, or the slider can't be drawn.
    with pytest.raises(ValidationError):
        Limits(min_main_questions=1)
    with pytest.raises(ValidationError):
        Limits(max_main_questions=16)
    with pytest.raises(ValidationError):
        Limits(min_main_questions=8, max_main_questions=8)


# --- Length presets -------------------------------------------------------------------------------


def test_length_presets_defaults_and_env(monkeypatch):
    p = Settings(_env_file=None).length_presets
    assert (p.quick, p.standard, p.quick_max_followups) == (3, 5, 1)
    monkeypatch.setenv("LENGTH_PRESETS__QUICK", "4")
    assert Settings(_env_file=None).length_presets.quick == 4


@pytest.mark.parametrize("values", [{"quick": 1}, {"standard": 16}, {"quick_max_followups": -1}, {"full": 7}])
def test_length_presets_bounds(values):
    with pytest.raises(ValidationError):
        LengthPresets(**values)


def test_length_presets_must_grow_from_quick_to_standard():
    with pytest.raises(ValidationError, match="quick <= standard"):
        LengthPresets(quick=6, standard=5)


# --- Speech-to-text -------------------------------------------------------------------------------


def test_stt_defaults_and_env(monkeypatch):
    s = Settings(_env_file=None)
    # The only transcription model this account's guardrail allows (checked 2026-10-05).
    assert s.stt.model == "openai/whisper-large-v3-turbo"
    assert s.stt.language == "en"
    assert s.stt.max_seconds > 0 and s.stt.max_bytes > 0
    monkeypatch.setenv("STT__MAX_SECONDS", "90")
    monkeypatch.setenv("STT__LANGUAGE", "de")
    s = Settings(_env_file=None)
    assert (s.stt.max_seconds, s.stt.language) == (90, "de")


@pytest.mark.parametrize("field, value", [("max_seconds", 0), ("max_seconds", 10_000), ("max_bytes", 0)])
def test_stt_limits_are_bounded(field, value):
    with pytest.raises(ValidationError):
        STTSettings(**{field: value})
