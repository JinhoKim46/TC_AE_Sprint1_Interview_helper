"""Real OpenRouter calls. Run with `uv run pytest -m live` (needs OPENROUTER_API_KEY in .env)."""

import pytest
from pydantic import BaseModel

from interview_app.config import Settings
from interview_app.llm.client import CallRecord, LLMClient, pcm_format, pcm_seconds
from interview_app.llm.pricing import PriceCatalog

pytestmark = pytest.mark.live


@pytest.fixture
def client_and_records():
    settings = Settings()
    records: list[CallRecord] = []
    return LLMClient(settings, recorder=records.append), records


def test_chat_reports_cost(client_and_records):
    client, records = client_and_records
    result = client.chat(
        "test", [{"role": "user", "content": "Reply with the word OK."}], model="openai/gpt-5-nano"
    )
    assert result.text.strip()
    assert records[0].cost_usd > 0  # OpenRouter's usage.cost reached the record


class Color(BaseModel):
    name: str


def test_chat_json_with_open_weight_model(client_and_records):
    client, _ = client_and_records
    color, _ = client.chat_json(
        "test",
        [{"role": "user", "content": 'Return JSON {"name": <a primary color>}.'}],
        Color,
        model="google/gemma-4-31b-it",
    )
    assert color.name


def test_price_catalog_has_interviewer_model(tmp_path):
    settings = Settings(data_dir=tmp_path)
    info = PriceCatalog(settings).get("openai/gpt-5-mini")
    assert info is not None
    assert info.prompt_price and info.prompt_price > 0


def test_speech_returns_pcm_and_an_estimated_cost(tmp_path):
    # One short sentence with the configured TTS model (about a second of audio, a fraction of a cent).
    settings = Settings(data_dir=tmp_path)
    records: list[CallRecord] = []
    client = LLMClient(settings, recorder=records.append, pricing=PriceCatalog(settings))
    result = client.speech("tts", "Hello.", model=settings.tts.model, voice=settings.tts.default_voice)
    assert pcm_format(result.content_type) == (24000, 1)
    assert pcm_seconds(result.audio, result.content_type) > 0.2
    assert records[0].ok and records[0].cost_usd > 0  # the TTS model is in the price catalog


def test_transcribe_reads_back_a_spoken_sentence(tmp_path):
    # A short fictional sentence, spoken by the TTS model, then transcribed (well under a cent in total).
    from interview_app.voice import pcm_to_wav

    settings = Settings(data_dir=tmp_path)
    records: list[CallRecord] = []
    client = LLMClient(settings, recorder=records.append, pricing=PriceCatalog(settings))
    sentence = "I trained the forecasting model at Fjordlight Analytics."
    speech = client.speech("tts", sentence, model=settings.tts.model, voice=settings.tts.default_voice)
    rate, channels = pcm_format(speech.content_type)
    wav = pcm_to_wav(speech.audio, rate=rate, channels=channels)

    result = client.transcribe("stt", wav, model=settings.stt.model, language=settings.stt.language)

    assert "forecasting" in result.text.lower()
    stt = records[-1]
    assert stt.role == "stt" and stt.ok and stt.cost_usd > 0  # OpenRouter's usage.cost reached the record
