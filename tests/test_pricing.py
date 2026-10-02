"""PriceCatalog tests. A fake `fetch` replaces the HTTP call and `tmp_path` holds the cache."""

import json
from types import SimpleNamespace

import pytest

from interview_app.config import Settings
from interview_app.llm.client import CallRecord, LLMClient
from interview_app.llm.pricing import CACHE_TTL_S, RETRY_AFTER_FAILURE_S, PriceCatalog

# A trimmed copy of the real response shape (prices are strings, "-1" means unknown).
CATALOG = {
    "data": [
        {
            "id": "openai/gpt-5-mini",
            "name": "OpenAI: GPT-5 Mini",
            "pricing": {"prompt": "0.00000025", "completion": "0.000002"},
            "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
            "supported_parameters": ["max_tokens", "reasoning", "structured_outputs"],
            "context_length": 400000,
        },
        {
            "id": "typesafe/jev-router",
            "name": "Jev Router",
            "pricing": {"prompt": "-1", "completion": "-1"},
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            "supported_parameters": ["temperature"],
            "context_length": None,
        },
    ]
}


class FakeFetch:
    """Counts calls so tests can check the cache prevents re-fetching."""

    def __init__(self, payload=CATALOG, error: Exception | None = None):
        self.payload, self.error, self.calls = payload, error, 0

    def __call__(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload


class Clock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def settings(tmp_path):
    return Settings(openrouter_api_key="test", data_dir=tmp_path)


def test_parses_string_prices_and_flags(settings):
    info = PriceCatalog(settings, fetch=FakeFetch()).get("openai/gpt-5-mini")

    assert info.prompt_price == pytest.approx(0.00000025)
    assert info.completion_price == pytest.approx(0.000002)
    assert info.context_length == 400000
    assert info.input_modalities == ["text", "image"]
    assert info.supports_structured_outputs and info.supports_reasoning


def test_negative_price_means_unknown(settings):
    catalog = PriceCatalog(settings, fetch=FakeFetch())
    info = catalog.get("typesafe/jev-router")

    assert info.prompt_price is None and info.completion_price is None
    assert not info.supports_structured_outputs
    assert catalog.estimate_cost("typesafe/jev-router", 100, 100) is None


def test_estimate_cost_math(settings):
    catalog = PriceCatalog(settings, fetch=FakeFetch())
    # 1000 * 0.25 $/M + 500 * 2 $/M = 0.00025 + 0.001
    assert catalog.estimate_cost("openai/gpt-5-mini", 1000, 500) == pytest.approx(0.00125)
    assert catalog.estimate_cost("no/such-model", 1000, 500) is None
    assert len(catalog.models()) == 2


def test_cache_written_and_reused_within_ttl(settings):
    fetch, clock = FakeFetch(), Clock()
    PriceCatalog(settings, fetch=fetch, now=clock).models()
    cache_file = settings.data_dir / "cache" / "models.json"
    assert json.loads(cache_file.read_text())["fetched_at"] == clock.t

    clock.t += CACHE_TTL_S - 60  # still fresh, and a new catalog (= app restart) reads the file
    assert PriceCatalog(settings, fetch=fetch, now=clock).get("openai/gpt-5-mini") is not None
    assert fetch.calls == 1


def test_refreshes_after_ttl(settings):
    fetch, clock = FakeFetch(), Clock()
    catalog = PriceCatalog(settings, fetch=fetch, now=clock)
    catalog.models()
    clock.t += CACHE_TTL_S + 1
    catalog.models()
    assert fetch.calls == 2


def test_stale_cache_used_when_fetch_fails(settings):
    clock = Clock()
    PriceCatalog(settings, fetch=FakeFetch(), now=clock).models()
    clock.t += CACHE_TTL_S * 3

    failing = FakeFetch(error=RuntimeError("offline"))
    catalog = PriceCatalog(settings, fetch=failing, now=clock)
    assert catalog.get("openai/gpt-5-mini") is not None
    assert failing.calls == 1


def test_failed_fetch_is_not_retried_on_every_lookup(settings):
    clock = Clock()
    PriceCatalog(settings, fetch=FakeFetch(), now=clock).models()
    clock.t += CACHE_TTL_S * 3

    failing = FakeFetch(error=RuntimeError("offline"))
    catalog = PriceCatalog(settings, fetch=failing, now=clock)
    for _ in range(5):
        catalog.get("openai/gpt-5-mini")
    assert failing.calls == 1  # offline lookups must not each wait for a new HTTP timeout

    clock.t += RETRY_AFTER_FAILURE_S + 1
    catalog.get("openai/gpt-5-mini")
    assert failing.calls == 2


def test_empty_catalog_when_fetch_fails_and_no_cache(settings):
    catalog = PriceCatalog(settings, fetch=FakeFetch(error=RuntimeError("offline")))
    assert catalog.models() == []
    assert catalog.estimate_cost("openai/gpt-5-mini", 10, 10) is None


def fake_sdk(cost: float | None):
    """A minimal stand-in for the OpenAI SDK returning one reply with 1000 prompt + 500 completion tokens."""
    usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=500)
    if cost is not None:
        usage.cost = cost  # only OpenRouter adds this field
    reply = SimpleNamespace(
        model="openai/gpt-5-mini",
        choices=[SimpleNamespace(message=SimpleNamespace(content="a"))],
        usage=usage,
    )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: reply)))


def test_client_estimates_cost_when_provider_reports_none(settings):
    records: list[CallRecord] = []
    pricing = PriceCatalog(settings, fetch=FakeFetch())
    sdk = fake_sdk(cost=None)
    client = LLMClient(settings, recorder=records.append, sdk=sdk, pricing=pricing)

    client.chat("x", [], model="openai/gpt-5-mini")
    assert records[0].cost_usd == pytest.approx(0.00125)


def test_client_prefers_reported_cost_over_estimate(settings):
    records: list[CallRecord] = []
    pricing = PriceCatalog(settings, fetch=FakeFetch())
    sdk = fake_sdk(cost=0.0042)
    client = LLMClient(settings, recorder=records.append, sdk=sdk, pricing=pricing)

    client.chat("x", [], model="openai/gpt-5-mini")
    assert records[0].cost_usd == 0.0042


# --- model_options -------------------------------------------------------------------------------


def test_model_options_join_curated_list_with_catalog(tmp_path):
    from interview_app.config import ModelChoice
    from interview_app.llm.pricing import model_options

    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        model_choices=[
            ModelChoice(id="openai/gpt-5-mini"),
            ModelChoice(id="typesafe/jev-router"),  # "-1" prices in the catalog
            ModelChoice(id="vendor/open-model", open_weight=True),  # not in the catalog at all
        ],
    )
    options = {o.id: o for o in model_options(PriceCatalog(settings, fetch=FakeFetch()), settings)}

    mini = options["openai/gpt-5-mini"]
    assert mini.label == "OpenAI: GPT-5 Mini" and not mini.open_weight
    assert mini.prompt_price_per_m == pytest.approx(0.25)
    assert mini.completion_price_per_m == pytest.approx(2.0)
    assert mini.supports_structured_outputs and mini.supports_reasoning

    router = options["typesafe/jev-router"]
    assert router.prompt_price_per_m is None and router.completion_price_per_m is None

    unknown = options["vendor/open-model"]
    assert unknown.open_weight and unknown.label == "vendor/open-model"
    assert unknown.prompt_price_per_m is None and unknown.supports_reasoning is None

    # The configured role defaults are always selectable, even if not in the curated list.
    assert settings.models.judge in options


def test_model_options_survive_an_offline_catalog(tmp_path):
    from interview_app.llm.pricing import model_options

    settings = Settings(_env_file=None, data_dir=tmp_path)
    catalog = PriceCatalog(settings, fetch=FakeFetch(error=RuntimeError("offline")))
    options = model_options(catalog, settings)
    assert [o.id for o in options][: len(settings.model_choices)] == [c.id for c in settings.model_choices]
    assert all(o.prompt_price_per_m is None for o in options)
    assert any(o.open_weight for o in options)
