"""All settings in one place.

Values come from (highest priority first): real environment variables, the `.env` file,
then the defaults below. Nested groups use a double underscore in env vars, e.g.
`MODELS__INTERVIEWER=openai/gpt-5` or `LIMITS__MAX_MAIN_QUESTIONS=6`.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# The project root (the folder that holds pyproject.toml), so paths work no matter
# which directory Streamlit or pytest is started from.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RoleModels(BaseModel):
    """Which model plays which role. Different families on purpose: a judge from the
    same family as the interviewer tends to prefer that family's style (self-preference bias)."""

    interviewer: str = "openai/gpt-5-mini"  # on the course allow-list (requirement R3)
    planner: str = "openai/gpt-5-mini"  # JD + CV -> interview plan
    judge: str = "anthropic/claude-haiku-4.5"  # final LLM-as-a-judge report
    candidate_sim: str = "google/gemini-2.5-flash"  # simulated candidate for prompt comparison
    jev: str = "typesafe/jev-1.13-20260917"  # decision model: live scores + injection guard
    image: str = "google/gemini-2.5-flash-image"  # interviewer avatars


class Limits(BaseModel):
    """Hard limits enforced in code (OWASP LLM10: unbounded consumption)."""

    max_upload_mb: float = 5.0
    max_pdf_pages: int = 20
    max_document_chars: int = 40_000
    max_answer_chars: int = 4_000
    max_main_questions: int = 8
    max_followups_per_question: int = 2
    max_turns: int = 60
    max_session_cost_usd: float = 1.00


class Features(BaseModel):
    """Feature flags, so an unfinished or broken feature can be switched off without code changes."""

    voice: bool = False
    avatars: bool = True
    live_scoring: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Encrypts the TOTP secret at rest (see auth.py). Must be a Fernet key.
    app_secret_key: SecretStr = SecretStr("")

    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'app.db'}"
    rubric_path: Path = PROJECT_ROOT / "docs" / "rubric.json"

    request_timeout_s: float = 60.0
    max_retries: int = 3

    models: RoleModels = RoleModels()
    limits: Limits = Limits()
    features: Features = Features()


@lru_cache
def get_settings() -> Settings:
    """One shared Settings object. Tests build their own `Settings(...)` instead."""
    return Settings()
