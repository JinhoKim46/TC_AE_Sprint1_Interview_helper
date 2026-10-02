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


class ModelChoice(BaseModel):
    """One entry of the model picker on the Settings page (course tasks M7 and H4)."""

    id: str  # OpenRouter model id
    # Open-weight = the weights are published (anyone can self-host it). The UI labels these,
    # because course task H4 asks for running the app on open-source models.
    open_weight: bool = False


# Curated, not the whole catalog: a few hundred models would be unusable in a dropdown, and this
# account's OpenRouter guardrail blocks some providers. Each entry was checked on 2026-10-02 with a
# tiny real call (plain chat + `chat_json`):
#   passed:  openai/gpt-5-mini, openai/gpt-5-nano, anthropic/claude-haiku-4.5, google/gemini-2.5-flash,
#            google/gemma-4-31b-it (open-weight), minimax/minimax-m2.7 (open-weight; the catalog lists
#            no structured_outputs, but chat_json still validated, via plain JSON + the repair retry)
#   blocked by the guardrail (404 "model-ignored-by-guardrail"): openai/gpt-5, z-ai/glm-5.2,
#            qwen/qwen3-235b-a22b-2507, meta-llama/llama-4-maverick, mistralai/mistral-medium-3.1,
#            openai/gpt-oss-120b
DEFAULT_MODEL_CHOICES: list[ModelChoice] = [
    ModelChoice(id="openai/gpt-5-mini"),
    ModelChoice(id="openai/gpt-5-nano"),
    ModelChoice(id="anthropic/claude-haiku-4.5"),
    ModelChoice(id="google/gemini-2.5-flash"),
    ModelChoice(id="google/gemma-4-31b-it", open_weight=True),
    ModelChoice(id="minimax/minimax-m2.7", open_weight=True),
]


class Limits(BaseModel):
    """Hard limits enforced in code (OWASP LLM10: unbounded consumption)."""

    max_upload_mb: float = 5.0
    max_pdf_pages: int = 20
    max_document_chars: int = 40_000
    max_answer_chars: int = 4_000
    max_turns: int = 60
    max_session_cost_usd: float = 1.00
    # Coaching mode: how many times one answer may be retried (so 1 + this many attempts in total).
    # A cap keeps a session from turning into an endless loop of re-answers (and Jev calls).
    max_retries_per_answer: int = 2


class GuardSettings(BaseModel):
    """Prompt-injection guard (OWASP LLM01), see security/injection.py."""

    # Jev's probability at or above which text counts as an injection. The model only reports a
    # probability; this threshold is where *our code* draws the line.
    # Tune it on the red-team examples in tests/test_guards.py.
    injection_threshold: float = 0.7
    # Switch off the Jev check (rules still run), e.g. to save cost or when offline.
    use_model_check: bool = True
    # Long documents are split into chunks of about this many characters, so a short injected line
    # is not diluted by pages of normal text. All chunks still go in one Jev request.
    document_chunk_chars: int = 3000


class Features(BaseModel):
    """Feature flags, so an unfinished or broken feature can be switched off without code changes."""

    live_scoring: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Public model catalog with per-token prices and capabilities (see llm/pricing.py).
    openrouter_models_url: str = "https://openrouter.ai/api/v1/models"
    # Jev decision model (llm/decide.py). Not OpenAI-compatible, so it has its own URL.
    openrouter_decisions_url: str = "https://openrouter.ai/api/alpha/decisions"

    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'app.db'}"
    rubric_path: Path = PROJECT_ROOT / "docs" / "rubric.json"
    guideline_path: Path = PROJECT_ROOT / "docs" / "01-interviewer-guideline.md"

    # Independent judge runs per report; None = rubric.json judge_settings.runs (3). 1 = cheapest.
    judge_runs: int | None = None
    request_timeout_s: float = 60.0
    max_retries: int = 3

    models: RoleModels = RoleModels()
    # Models offered in the Settings page pickers. Override in .env as JSON, e.g.
    # MODEL_CHOICES='[{"id": "openai/gpt-5-mini"}, {"id": "google/gemma-4-31b-it", "open_weight": true}]'
    model_choices: list[ModelChoice] = DEFAULT_MODEL_CHOICES
    limits: Limits = Limits()
    guard: GuardSettings = GuardSettings()
    features: Features = Features()


@lru_cache
def get_settings() -> Settings:
    """One shared Settings object. Tests build their own `Settings(...)` instead."""
    return Settings()
