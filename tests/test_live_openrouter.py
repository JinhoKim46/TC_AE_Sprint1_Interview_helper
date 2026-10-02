"""Real OpenRouter calls. Run with `uv run pytest -m live` (needs OPENROUTER_API_KEY in .env)."""

import pytest
from pydantic import BaseModel

from interview_app.config import Settings
from interview_app.llm.client import CallRecord, LLMClient

pytestmark = pytest.mark.live


@pytest.fixture
def client_and_records():
    settings = Settings()
    if not settings.openrouter_api_key.get_secret_value():
        pytest.skip("OPENROUTER_API_KEY not set")
    records: list[CallRecord] = []
    return LLMClient(settings, recorder=records.append), records


def test_chat_reports_cost(client_and_records):
    client, records = client_and_records
    result = client.chat("test", [{"role": "user", "content": "Reply with the word OK."}], model="openai/gpt-5-nano")
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
