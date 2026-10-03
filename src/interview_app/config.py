"""All settings in one place.

Values come from (highest priority first): real environment variables, the `.env` file,
then the defaults below. Nested groups use a double underscore in env vars, e.g.
`MODELS__INTERVIEWER=openai/gpt-5-nano` or `LIMITS__MAX_TURNS=40`.

Every value is validated at startup: out-of-range numbers and misspelled nested keys
(e.g. `LIMITS__MAX_TURN=40`) stop the app with a clear error instead of being silently ignored.
"""

from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The project root (the folder that holds pyproject.toml), so paths work no matter
# which directory Streamlit or pytest is started from.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# For the nested groups below: an unknown key is a typo (`LIMITS__MAX_TURN=40`), and silently
# ignoring it would leave the default in place without anyone noticing, so fail loudly instead.
_STRICT = ConfigDict(extra="forbid")


class RoleModels(BaseModel):
    """Which model plays which role. Different families on purpose: a judge from the
    same family as the interviewer tends to prefer that family's style (self-preference bias)."""

    model_config = _STRICT

    interviewer: str = "openai/gpt-5-mini"  # on the course allow-list (requirement R3)
    planner: str = "openai/gpt-5-mini"  # JD + CV -> interview plan
    judge: str = "anthropic/claude-haiku-4.5"  # final LLM-as-a-judge report
    candidate_sim: str = "google/gemini-2.5-flash"  # simulated candidate for prompt comparison
    jev: str = "typesafe/jev-1.13-20260917"  # decision model: live scores + injection guard


class ModelChoice(BaseModel):
    """One entry of the model picker on the Settings page (course tasks M7 and H4)."""

    model_config = _STRICT

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
    """Hard limits enforced in code (OWASP LLM10: unbounded consumption).

    The upper bounds are sanity caps, not recommendations: a limit raised far beyond them is almost
    certainly a typo (an extra zero) that would let one session burn through the budget.
    """

    model_config = _STRICT

    # Keep in step with `maxUploadSize` in .streamlit/config.toml: Streamlit rejects bigger files
    # before our code sees them, so a higher value here alone has no effect.
    max_upload_mb: float = Field(default=5.0, gt=0, le=50)
    # PDF decompression-bomb bounds (see ingest.extract_pdf_text). A real CV page's text stream is tens
    # of KB, so 5 MB per stream is generous.
    pdf_max_stream_bytes: int = Field(default=5_000_000, gt=0)
    pdf_extract_timeout_s: float = Field(default=20.0, gt=0, le=300)
    max_pdf_pages: int = Field(default=20, gt=0, le=200)
    max_document_chars: int = Field(default=40_000, gt=0, le=500_000)
    max_answer_chars: int = Field(default=4_000, gt=0, le=50_000)
    max_turns: int = Field(default=60, gt=0, le=500)
    max_session_cost_usd: float = Field(default=1.00, gt=0, le=50)
    # Coaching mode: how many times one answer may be retried (so 1 + this many attempts in total).
    # A cap keeps a session from turning into an endless loop of re-answers (and Jev calls).
    # 0 is allowed on purpose: it means "no retries", a valid way to practise without coaching loops.
    max_retries_per_answer: int = Field(default=2, ge=0, le=10)
    # A start (planning + opening turn) still "preparing" after this long was interrupted; it is marked
    # failed so it can't block new interviews. Generous on purpose: with the default 60 s request timeout
    # and 3 retries, a slow but healthy start (plan + opening turn + one repair) can take over 10 minutes.
    start_timeout_minutes: int = Field(default=15, gt=0, le=60)
    # Range of the "main questions" slider on the start form and Settings page. It must stay inside
    # SessionConfig.main_questions' bounds (2-15), which the engine enforces.
    min_main_questions: int = Field(default=3, ge=2, le=15)
    max_main_questions: int = Field(default=12, ge=2, le=15)

    @model_validator(mode="after")
    def _slider_range(self) -> Self:
        if self.min_main_questions >= self.max_main_questions:
            raise ValueError("min_main_questions must be below max_main_questions")
        return self


class LengthPresets(BaseModel):
    """Main questions per interview Length (spec 2026-10-03-length-voice-design).

    Quick and Standard take their question count from here. Full is "the real interview", so it keeps
    each interview type's realistic count (persona.DEFAULT_MAIN_QUESTIONS: 4 for an ML case, 8 for a
    final round); Custom uses the slider. No count is written into prompts.
    Env example: `LENGTH_PRESETS__QUICK=4`. The bounds match SessionConfig.main_questions (2-15).
    """

    model_config = _STRICT

    quick: int = Field(default=3, ge=2, le=15)  # a short practice on the core questions
    standard: int = Field(default=5, ge=2, le=15)
    # Quick also caps follow-ups per main question; the session uses min(difficulty cap, this).
    quick_max_followups: int = Field(default=1, ge=0, le=3)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        # A "Quick" longer than "Standard" is a typo in .env, and the labels would then mislead the user.
        if not self.quick <= self.standard:
            raise ValueError("length presets must satisfy quick <= standard")
        return self


# Voices of the TTS model, from `GET /api/v1/models?output_modalities=speech` -> `supported_voices`
# (checked 2026-10-03). Kept here (not fetched) so the Settings picker works offline.
GEMINI_TTS_VOICES: list[str] = [
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede", "Callirrhoe", "Autonoe",
    "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina", "Erinome", "Algenib", "Rasalgethi",
    "Laomedeia", "Achernar", "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
]  # fmt: skip


class TTSSettings(BaseModel):
    """Text-to-speech for the Voice channel (spec 2026-10-03-length-voice-design, voice.py).

    Env example: `TTS__MODEL=...` or `TTS__VOICES='{"hiring_manager": "Puck"}'`.
    """

    model_config = _STRICT

    # The only TTS model this account's OpenRouter guardrail allows (checked 2026-10-03; others 404).
    # It returns raw 16-bit PCM only, which voice.py wraps into a WAV file.
    model: str = "google/gemini-3.8-flash-lite-tts"
    # Interview type -> voice, so each fixed persona (persona._BASE) always sounds like the same person.
    # Keys are InterviewType values; config can't import persona.py, so they are plain strings here.
    voices: dict[str, str] = {
        "recruiter_screen": "Aoede",  # Lena Brandt: friendly, organised
        "hiring_manager": "Charon",  # Daniel Okafor: pragmatic, direct
        "technical_deep_dive": "Kore",  # Dr. Mira Castellano: precise
        "ml_case": "Orus",  # Jonas Weber: collaborative but demanding
        "behavioral": "Leda",  # Aisha Rahman: warm, structured
        "final_round": "Zephyr",  # Sofia Lindgren: calm, thorough
    }
    default_voice: str = "Charon"  # for an interview type missing from `voices`
    available_voices: list[str] = GEMINI_TTS_VOICES
    # The speech response carries no token usage, so cost is ESTIMATED from the catalog prices (see
    # LLMClient.speech). Gemini bills audio as tokens per second of audio; it documents 32/s for audio
    # input, and that rate is used for the generated audio too, as a deliberately conservative estimate.
    audio_tokens_per_second: float = Field(default=32.0, gt=0, le=1000)
    # A question longer than this is cut before speaking (OWASP LLM10: one turn can't burn the budget).
    max_chars: int = Field(default=2000, gt=0, le=10_000)

    @model_validator(mode="after")
    def _known_voices(self) -> Self:
        unknown = {*self.voices.values(), self.default_voice} - set(self.available_voices)
        if unknown:
            raise ValueError(f"unknown TTS voice(s): {sorted(unknown)}")
        return self

    def voice_for(self, interview_type: str) -> str:
        return self.voices.get(interview_type, self.default_voice)


class GuardSettings(BaseModel):
    """Prompt-injection guard (OWASP LLM01), see security/injection.py."""

    model_config = _STRICT

    # Jev's probability at or above which text counts as an injection. The model only reports a
    # probability; this threshold is where *our code* draws the line.
    # Tune it on the red-team examples in tests/test_guards.py.
    # It is compared with a probability, so anything outside [0, 1] would block everything or nothing.
    injection_threshold: float = Field(default=0.7, ge=0, le=1)
    # Switch off the Jev check (rules still run), e.g. to save cost or when offline.
    use_model_check: bool = True
    # Long documents are split into chunks of about this many characters, so a short injected line
    # is not diluted by pages of normal text. All chunks still go in one Jev request.
    document_chunk_chars: int = Field(default=3000, gt=0)
    # The most chunks one document may have before the model check refuses it (OWASP LLM10). Each chunk
    # is one question in the Jev request, so without a cap a 1 MB paste would send ~330 questions at
    # once. 20 x 3,000 characters is about 60,000: above the 40,000-character document limit, so a
    # document that passed `ingest.validate_document` always fits.
    max_document_chunks: int = Field(default=20, gt=0, le=200)


class Features(BaseModel):
    """Feature flags, so an unfinished or broken feature can be switched off without code changes."""

    model_config = _STRICT

    live_scoring: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_nested_delimiter="__",
        # Top level stays lenient (unlike the nested groups): .env also holds values for other tools
        # (APP_UID/APP_GID for Docker Compose) and old keys such as APP_SECRET_KEY from the dropped
        # login feature, and none of those should stop the app from starting.
        extra="ignore",
    )

    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Public model catalog with per-token prices and capabilities (see llm/pricing.py). API quirk: the plain
    # URL lists text-output models only; `output_modalities=all` also lists the TTS model, whose prices
    # the speech cost estimate needs.
    openrouter_models_url: str = "https://openrouter.ai/api/v1/models?output_modalities=all"
    # Jev decision model (llm/decide.py). Not OpenAI-compatible, so it has its own URL.
    openrouter_decisions_url: str = "https://openrouter.ai/api/alpha/decisions"

    data_dir: Path = PROJECT_ROOT / "data"
    # Empty = `sqlite:///<data_dir>/app.db` (filled in below), so moving DATA_DIR moves the database
    # with it. Set DATABASE_URL only to point somewhere else entirely.
    database_url: str = ""
    rubric_path: Path = PROJECT_ROOT / "docs" / "rubric.json"
    guideline_path: Path = PROJECT_ROOT / "docs" / "01-interviewer-guideline.md"

    # Independent judge runs per report; None = rubric.json judge_settings.runs (3). 1 = cheapest.
    judge_runs: int | None = Field(default=None, ge=1, le=5)
    # Output budget for one judge call. The report for a long interview is big structured JSON, and a
    # reasoning model spends part of the budget on thinking, so too small a value truncates the JSON.
    judge_max_tokens: int = Field(default=16000, ge=1000, le=64000)
    request_timeout_s: float = Field(default=60.0, gt=0, le=600)
    max_retries: int = Field(default=3, ge=0, le=10)

    models: RoleModels = RoleModels()
    # Models offered in the Settings page pickers. Override in .env as JSON, e.g.
    # MODEL_CHOICES='[{"id": "openai/gpt-5-mini"}, {"id": "google/gemma-4-31b-it", "open_weight": true}]'
    model_choices: list[ModelChoice] = DEFAULT_MODEL_CHOICES
    limits: Limits = Limits()
    length_presets: LengthPresets = LengthPresets()
    tts: TTSSettings = TTSSettings()
    guard: GuardSettings = GuardSettings()
    features: Features = Features()

    @model_validator(mode="after")
    def _derive_database_url(self) -> Self:
        if not self.database_url:
            self.database_url = f"sqlite:///{self.data_dir / 'app.db'}"
        return self


@lru_cache
def get_settings() -> Settings:
    """One shared Settings object. Tests build their own `Settings(...)` instead."""
    return Settings()
