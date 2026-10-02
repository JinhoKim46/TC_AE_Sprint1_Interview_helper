import logging

from sqlmodel import select

from interview_app.config import Settings
from interview_app.db import User, UserPreferences, session_scope
from interview_app.interview.persona import (
    DEFAULT_MAIN_QUESTIONS,
    Difficulty,
    InterviewType,
    LLMSettings,
    PromptVariant,
)
from interview_app.preferences import (
    Preferences,
    judge_model,
    load_preferences,
    save_preferences,
    to_session_config,
)


def add_user(engine, name: str) -> int:
    with session_scope(engine) as s:
        user = User(username=name, password_hash="h", totp_secret_enc="e")
        s.add(user)
        s.flush()
        return user.id


def test_defaults_when_nothing_saved(engine):
    uid = add_user(engine, "alex")
    prefs = load_preferences(engine, uid)
    assert prefs == Preferences()
    assert prefs.prompt_variant == PromptVariant.P4_ROLE_RICH
    assert prefs.judge_model is None


def test_save_then_load_round_trip_and_overwrite(engine):
    uid = add_user(engine, "alex")
    prefs = Preferences(
        interview_type=InterviewType.BEHAVIORAL,
        difficulty=Difficulty.TOUGH,
        main_questions=5,
        prompt_variant=PromptVariant.P1_ZERO_SHOT,
        interviewer=LLMSettings(model="google/gemma-4-31b-it", temperature=0.3, max_tokens=900),
        judge_model="google/gemini-2.5-flash",
    )
    save_preferences(engine, uid, prefs)
    assert load_preferences(engine, uid) == prefs

    save_preferences(engine, uid, prefs.model_copy(update={"main_questions": 9}))
    assert load_preferences(engine, uid).main_questions == 9
    with session_scope(engine) as s:  # still one row per user
        assert len(s.exec(select(UserPreferences)).all()) == 1


def test_preferences_are_per_user(engine):
    alex, sam = add_user(engine, "alex"), add_user(engine, "sam")
    save_preferences(engine, alex, Preferences(main_questions=4))
    assert load_preferences(engine, sam).main_questions is None


def test_invalid_row_falls_back_to_defaults(engine, caplog):
    uid = add_user(engine, "alex")
    with session_scope(engine) as s:
        s.add(UserPreferences(user_id=uid, prefs_json='{"prompt_variant": "p9_removed"}'))
    with caplog.at_level(logging.WARNING):
        assert load_preferences(engine, uid) == Preferences()
    assert "invalid" in caplog.text


def test_garbage_json_falls_back_and_unknown_keys_are_ignored(engine):
    uid = add_user(engine, "alex")
    with session_scope(engine) as s:
        s.add(UserPreferences(user_id=uid, prefs_json="not json"))
    assert load_preferences(engine, uid) == Preferences()

    save_preferences(engine, uid, Preferences())
    with session_scope(engine) as s:
        row = s.exec(select(UserPreferences)).one()
        row.prefs_json = '{"main_questions": 6, "old_setting": true}'
        s.add(row)
    assert load_preferences(engine, uid).main_questions == 6


def test_to_session_config_uses_prefs_and_overrides():
    prefs = Preferences(
        interview_type=InterviewType.RECRUITER_SCREEN,
        prompt_variant=PromptVariant.P5_SELF_CRITIQUE,
        interviewer=LLMSettings(model="minimax/minimax-m2.7", reasoning_effort="high"),
        main_questions=4,
    )
    config = to_session_config(prefs)
    assert config.interview_type == InterviewType.RECRUITER_SCREEN
    assert config.prompt_variant == PromptVariant.P5_SELF_CRITIQUE
    assert config.llm.model == "minimax/minimax-m2.7" and config.llm.reasoning_effort == "high"
    assert config.main_questions == 4

    config = to_session_config(prefs, difficulty=Difficulty.FRIENDLY, main_questions=10)
    assert config.difficulty == Difficulty.FRIENDLY and config.main_questions == 10
    config.llm.temperature = 1.0
    assert prefs.interviewer.temperature is None  # the session got a copy


def test_to_session_config_uses_type_length_when_unset():
    config = to_session_config(Preferences(), interview_type=InterviewType.ML_CASE)
    assert config.main_questions == DEFAULT_MAIN_QUESTIONS[InterviewType.ML_CASE]


def test_judge_model_falls_back_to_settings():
    settings = Settings(_env_file=None)
    assert judge_model(Preferences(), settings) == settings.models.judge
    assert judge_model(Preferences(judge_model="x/y"), settings) == "x/y"
