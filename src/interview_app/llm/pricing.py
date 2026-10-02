"""Model prices and capabilities from OpenRouter's public model catalog.

Two uses:
- Cost estimates (course task M3) for providers that don't report the charged cost in `usage.cost`
  (OpenRouter does; OpenAI, Ollama or vLLM don't).
- Data for the model picker (M7): which models take images, support structured outputs, reasoning...

The catalog is a few hundred models and changes slowly, so we cache the raw JSON on disk and refresh
it at most once a day. Pricing is a nice-to-have: any failure here degrades to "cost unknown", it never
stops an interview.
"""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from interview_app.config import Settings

log = logging.getLogger(__name__)

# Prices change rarely (days or weeks), so one fetch per day is plenty and keeps startup fast.
CACHE_TTL_S = 24 * 60 * 60
# After a failed fetch, wait this long before trying the network again. Without it, every
# cost lookup while offline would block on a fresh HTTP timeout.
RETRY_AFTER_FAILURE_S = 10 * 60


class ModelInfo(BaseModel):
    """One catalog entry, reduced to what the app needs. Prices are USD per token."""

    id: str
    name: str
    prompt_price: float | None
    completion_price: float | None
    context_length: int | None = None
    input_modalities: list[str] = []
    output_modalities: list[str] = []
    supports_structured_outputs: bool = False
    supports_reasoning: bool = False


def _parse_price(value: Any) -> float | None:
    # API quirk: prices arrive as strings ("0.00000025"), not numbers, to avoid float rounding in JSON.
    # Routers and some special models use "-1" to mean "variable / unknown", so negative -> None.
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price >= 0 else None


def parse_model(raw: dict) -> ModelInfo:
    pricing = raw.get("pricing") or {}
    arch = raw.get("architecture") or {}
    params = raw.get("supported_parameters") or []
    return ModelInfo(
        id=raw["id"],
        name=raw.get("name") or raw["id"],
        prompt_price=_parse_price(pricing.get("prompt")),
        completion_price=_parse_price(pricing.get("completion")),
        context_length=raw.get("context_length"),
        input_modalities=arch.get("input_modalities") or [],
        output_modalities=arch.get("output_modalities") or [],
        supports_structured_outputs="structured_outputs" in params,
        supports_reasoning="reasoning" in params,
    )


class PriceCatalog:
    """Lazy, disk-cached view of `GET /api/v1/models`.

    `fetch` and `now` are injectable so tests can run without network and can fake the clock
    to check the 24 h refresh.
    """

    def __init__(
        self,
        settings: Settings,
        fetch: Callable[[], dict] | None = None,
        now: Callable[[], float] = time.time,
    ):
        self.settings = settings
        self.fetch = fetch or self._fetch_from_openrouter
        self.now = now
        self.cache_path: Path = settings.data_dir / "cache" / "models.json"
        self._models: dict[str, ModelInfo] | None = None  # parsed once per process
        self._loaded_at: float = 0.0

    def _fetch_from_openrouter(self) -> dict:
        # The endpoint works without a key, but sending it lets OpenRouter apply this account's
        # settings. This is catalog data, not a model call, so it doesn't go through LLMClient.
        key = self.settings.openrouter_api_key.get_secret_value()
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        response = httpx.get(
            self.settings.openrouter_models_url, headers=headers, timeout=self.settings.request_timeout_s
        )
        response.raise_for_status()
        return response.json()

    def _read_cache(self) -> dict | None:
        try:
            return json.loads(self.cache_path.read_text())
        except (OSError, ValueError):
            return None  # missing or corrupt cache: treat as no cache

    def _write_cache(self, payload: dict, fetched_at: float) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps({"fetched_at": fetched_at, "payload": payload}))
        except OSError as e:
            log.warning("Could not write the model price cache: %r", e)

    def _load(self) -> dict[str, ModelInfo]:
        # Re-check the clock even after loading, so a long-running app picks up new prices daily.
        if self._models is not None and self.now() - self._loaded_at < CACHE_TTL_S:
            return self._models

        cache = self._read_cache()
        fresh = cache is not None and self.now() - cache.get("fetched_at", 0) < CACHE_TTL_S
        fetch_failed = False
        if fresh:
            payload = cache["payload"]
            fetched_at = cache["fetched_at"]
        else:
            try:
                payload = self.fetch()
                fetched_at = self.now()
                self._write_cache(payload, fetched_at)
            except Exception as e:
                fetch_failed = True
                if cache is not None:
                    log.warning("Model catalog fetch failed, using stale cache: %r", e)
                    payload, fetched_at = cache["payload"], cache.get("fetched_at", 0)
                else:
                    log.warning("Model catalog fetch failed and no cache exists; costs unknown: %r", e)
                    payload, fetched_at = {"data": []}, self.now()

        models: dict[str, ModelInfo] = {}
        for raw in payload.get("data", []):
            try:
                info = parse_model(raw)
            except (KeyError, ValueError) as e:
                # One odd entry shouldn't hide the other few hundred models.
                log.debug("Skipping unparseable catalog entry: %r", e)
                continue
            models[info.id] = info
        self._models = models
        # Remember when the data was fetched (not when we read it), so stale data is retried soon.
        self._loaded_at = fetched_at
        if fetch_failed:
            # Pretend the data is almost expired so the next retry happens after RETRY_AFTER_FAILURE_S.
            self._loaded_at = self.now() - CACHE_TTL_S + RETRY_AFTER_FAILURE_S
        return models

    def models(self) -> list[ModelInfo]:
        return list(self._load().values())

    def get(self, model_id: str) -> ModelInfo | None:
        return self._load().get(model_id)

    def estimate_cost(self, model_id: str, prompt_tokens: int, completion_tokens: int) -> float | None:
        """USD estimate from list prices. None when the model or one of its prices is unknown.

        Only an estimate: it ignores cached-token discounts and reasoning tokens billed separately.
        """
        info = self.get(model_id)
        if info is None or info.prompt_price is None or info.completion_price is None:
            return None
        return prompt_tokens * info.prompt_price + completion_tokens * info.completion_price
