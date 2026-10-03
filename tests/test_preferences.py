import logging

import pytest
from sqlmodel import select

from interview_app.config import LengthPresets, Settings
from interview_app.db import User, UserPreferences, session_scope
from interview_app.interview.persona import (
    DEFAULT_MAIN_QUESTIONS,
    Channel,
    Difficulty,
    InterviewType,
    Length,
    LLMSettings,
    PromptVariant,
    SessionConfig,
    length_channel_label,
)
from interview_app.preferences import (
    Preferences,
    judge_model,
    load_preferences,
    preset_main_questions,
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
        length=Length.CUSTOM,
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
    config = to_session_config(Preferences(length=Length.CUSTOM), interview_type=InterviewType.ML_CASE)
    assert config.main_questions == DEFAULT_MAIN_QUESTIONS[InterviewType.ML_CASE]


# --- Length and Channel ---------------------------------------------------------------------------


def test_new_preferences_default_to_standard_voice():
    prefs = Preferences()
    assert prefs.length == Length.STANDARD and prefs.channel == Channel.VOICE


def test_preferences_saved_before_length_existed_load_with_the_new_defaults(engine):
    uid = add_user(engine, "alex")
    with session_scope(engine) as s:
        s.add(UserPreferences(user_id=uid, prefs_json='{"main_questions": 6, "difficulty": "tough"}'))
    prefs = load_preferences(engine, uid)
    assert prefs.main_questions == 6 and prefs.length == Length.STANDARD and prefs.channel == Channel.VOICE


def test_length_and_channel_round_trip(engine):
    uid = add_user(engine, "alex")
    save_preferences(engine, uid, Preferences(length=Length.QUICK, channel=Channel.TEXT))
    prefs = load_preferences(engine, uid)
    assert prefs.length == Length.QUICK and prefs.channel == Channel.TEXT


def test_sessions_stored_before_length_existed_load_as_full_text():
    old = '{"interview_type": "behavioral", "difficulty": "tough", "main_questions": 6}'
    config = SessionConfig.model_validate_json(old)
    assert config.length == Length.FULL and config.channel == Channel.TEXT
    assert config.main_questions == 6  # the stored count stays the truth for an old session


@pytest.mark.parametrize(("length", "expected"), [(Length.QUICK, 3), (Length.STANDARD, 5), (Length.FULL, 7)])
def test_preset_lengths_take_their_question_count_from_config(length, expected):
    # The saved custom count and the type's usual length are both ignored for a preset length.
    prefs = Preferences(length=length, main_questions=11)
    config = to_session_config(prefs, presets=LengthPresets(), interview_type=InterviewType.ML_CASE)
    assert config.length == length and config.main_questions == expected


def test_an_override_count_is_ignored_unless_length_is_custom():
    config = to_session_config(Preferences(), presets=LengthPresets(), length=Length.QUICK, main_questions=9)
    assert config.main_questions == 3
    config = to_session_config(Preferences(), presets=LengthPresets(), length=Length.CUSTOM, main_questions=9)
    assert config.main_questions == 9


def test_presets_come_from_the_given_config_group():
    presets = LengthPresets(quick=2, standard=6, full=9)
    assert to_session_config(Preferences(length=Length.FULL), presets=presets).main_questions == 9
    assert preset_main_questions(Length.QUICK, presets) == 2
    assert preset_main_questions(Length.CUSTOM, presets) is None


def test_channel_comes_from_prefs_unless_the_form_changes_it():
    prefs = Preferences(channel=Channel.TEXT)
    assert to_session_config(prefs).channel == Channel.TEXT
    assert to_session_config(prefs, channel=Channel.VOICE).channel == Channel.VOICE


def test_length_channel_label():
    config = SessionConfig(length=Length.QUICK, channel=Channel.VOICE)
    assert length_channel_label(config) == "Quick · Voice"
    assert length_channel_label(SessionConfig()) == "Full · Text"


def test_judge_model_falls_back_to_settings():
    settings = Settings(_env_file=None)
    assert judge_model(Preferences(), settings) == settings.models.judge
    assert judge_model(Preferences(judge_model="x/y"), settings) == "x/y"
