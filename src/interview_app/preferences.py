"""Saved user preferences: interview defaults and developer settings (course tasks M1, M9).

The Settings page writes them; the Interview page reads them to pre-fill its start form and to build
the SessionConfig. The candidate-facing part (type, difficulty, length) and the developer part
(prompt variant, model settings) live in one object but are shown in separate areas of the UI.
"""

import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.engine import Engine
from sqlmodel import select

from interview_app.config import Settings
from interview_app.db import UserPreferences, session_scope, utcnow
from interview_app.interview.persona import (
    DEFAULT_MAIN_QUESTIONS,
    Difficulty,
    InterviewType,
    LLMSettings,
    Mode,
    PromptVariant,
    SessionConfig,
)

log = logging.getLogger(__name__)


class Preferences(BaseModel):
    # Ignore unknown keys: a row saved by an older/newer app version with an extra field still loads.
    model_config = ConfigDict(extra="ignore")

    # --- Interview defaults (for the candidate) ---
    interview_type: InterviewType = InterviewType.HIRING_MANAGER
    difficulty: Difficulty = Difficulty.STANDARD
    # None = "the usual length for the chosen interview type" (DEFAULT_MAIN_QUESTIONS), so switching
    # from a recruiter screen to a case interview doesn't keep an unsuitable number.
    # Same range as the sliders on the Settings and Interview pages, so a saved value always fits them.
    main_questions: int | None = Field(default=None, ge=3, le=12)
    mode: Mode = Mode.REALISTIC

    # --- Developer settings ---
    prompt_variant: PromptVariant = PromptVariant.P4_ROLE_RICH
    interviewer: LLMSettings = LLMSettings()
    judge_model: str | None = None  # None -> Settings.models.judge


def load_preferences(engine: Engine, user_id: int) -> Preferences:
    """The user's saved preferences, or the defaults if nothing (usable) is saved."""
    with session_scope(engine) as s:
        row = s.exec(select(UserPreferences).where(UserPreferences.user_id == user_id)).first()
        raw = row.prefs_json if row else None
    if raw is None:
        return Preferences()
    try:
        return Preferences.model_validate_json(raw)
    except ValidationError as e:
        # A broken or outdated row (e.g. a removed enum value) must not lock the user out of the
        # Interview page. Defaults are safe; the next save overwrites the bad row.
        log.warning("Saved preferences for user %s are invalid, using defaults: %s", user_id, e)
        return Preferences()


def save_preferences(engine: Engine, user_id: int, prefs: Preferences) -> None:
    """Insert or replace the user's one preferences row."""
    with session_scope(engine) as s:
        row = s.exec(select(UserPreferences).where(UserPreferences.user_id == user_id)).first()
        if row is None:
            row = UserPreferences(user_id=user_id, prefs_json=prefs.model_dump_json())
        else:
            row.prefs_json = prefs.model_dump_json()
            row.updated_at = utcnow()
        s.add(row)


def to_session_config(prefs: Preferences, **overrides) -> SessionConfig:
    """Build a SessionConfig from saved preferences; `overrides` are what the start form changed.

    Example: `to_session_config(prefs, interview_type=InterviewType.BEHAVIORAL, main_questions=5)`.
    """
    values = {
        "interview_type": prefs.interview_type,
        "difficulty": prefs.difficulty,
        "mode": prefs.mode,
        "main_questions": prefs.main_questions,
        "prompt_variant": prefs.prompt_variant,
        # A copy, so editing the session config can never change the saved preferences object.
        "llm": prefs.interviewer.model_copy(),
        **overrides,
    }
    if values["main_questions"] is None:
        values["main_questions"] = DEFAULT_MAIN_QUESTIONS[InterviewType(values["interview_type"])]
    return SessionConfig(**values)


def judge_model(prefs: Preferences, settings: Settings) -> str:
    """The model the final LLM judge should use for this user."""
    return prefs.judge_model or settings.models.judge
