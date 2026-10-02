"""Read access to docs/rubric.json — the single source of truth for items, weights and bands.
Nothing in code or prompts repeats these numbers."""

import json
from functools import lru_cache
from pathlib import Path

# Categories that A-items score. CQ (candidate questions) is judged once per session (S4), not per exchange.
SCORED_CATEGORIES = ("OPEN", "MOT", "EXP", "TECH", "CASE", "RES", "BEH", "LOG", "CLOSE")


class Rubric:
    def __init__(self, data: dict):
        self.data = data
        self.version: str = data["rubric_version"]
        self.exchange_items: dict[str, dict] = data["exchange_items"]
        self.session_items: dict[str, dict] = data["session_items"]
        self.bands: list[dict] = sorted(data["bands"], key=lambda b: -b["min"])

    @staticmethod
    def norm(score: float) -> float:
        """1-5 -> 0-100, as `scale.normalize` in rubric.json says: (s-1)/4*100."""
        return (score - 1) / 4 * 100

    def weights_for(self, category: str, question_id: str | None = None) -> dict[str, float]:
        """Applicable A-items and their weights for one exchange (None in rubric.json = not applicable)."""
        weights = {
            item_id: item["weights"][category]
            for item_id, item in self.exchange_items.items()
            if item["weights"].get(category) is not None
        }
        overrides = self.data.get("exchange_weight_overrides_by_question_id", {}).get(question_id or "", {})
        weights.update({k: v for k, v in overrides.items() if k in weights})
        return weights

    def word_limits(self, category: str) -> dict | None:
        return self.data["deterministic_metrics_word_limits"].get(category)

    def aggregation_weights(self, interview_type: str) -> dict[str, float]:
        agg = self.data["aggregation"]
        return agg.get(interview_type) if isinstance(agg.get(interview_type), dict) else agg["default"]

    def section_categories(self) -> dict[str, list[str]]:
        return self.data["aggregation"]["sections"]

    def requirement_points(self) -> dict[str, float | None]:
        return self.session_items["S2"]["points"]

    def requirement_weights(self) -> dict[str, float]:
        return self.session_items["S2"]["requirement_weights"]

    def penalty(self, severity: str) -> float:
        return self.data["penalties"][severity]

    @property
    def judge_temperature(self) -> float:
        return float(self.data.get("judge_settings", {}).get("temperature", 0))

    @property
    def evidence_required(self) -> bool:
        """judge_settings.evidence_required: a score without a cited transcript turn is ignored."""
        return bool(self.data.get("judge_settings", {}).get("evidence_required", True))

    @property
    def judge_runs(self) -> int:
        """How many independent judge runs a report uses (rubric judge_settings.runs)."""
        return int(self.data.get("judge_settings", {}).get("runs", 1))

    def band(self, overall: float) -> str:
        return next(b["band"] for b in self.bands if overall >= b["min"])


@lru_cache
def load_rubric(path: Path) -> Rubric:
    return Rubric(json.loads(Path(path).read_text()))
