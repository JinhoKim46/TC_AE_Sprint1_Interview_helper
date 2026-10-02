"""The result every guard returns, so the UI and the call log handle all guards the same way."""

from pydantic import BaseModel, Field

# Methods, so callers (and tests) can compare against a name instead of a typo-prone string.
METHOD_RULES = "rules"
METHOD_RULES_MODEL = "rules+model"
METHOD_MODEL_UNAVAILABLE = "rules (model unavailable)"


class GuardResult(BaseModel):
    """What a guard decided about one piece of user text.

    - `allowed=False`: the text must not be sent to a model (e.g. an injected interview answer).
    - `flagged=True` with `allowed=True`: suspicious, but we do not decide alone. Used for documents:
      the UI shows `reason` and the user confirms or edits the text before it is used.
    """

    allowed: bool
    flagged: bool = False
    # Short and user-facing. Never echoes more than a short excerpt of the suspicious text, because
    # the reason is shown in the UI and written to logs (and the text may be long or personal).
    reason: str | None = None
    checks: list[str] = Field(default_factory=list)  # e.g. ["length"], ["rule:ignore_instructions"]
    score: float | None = None  # Jev's injection probability, when the model check ran
    method: str = METHOD_RULES


def ok() -> GuardResult:
    """A plain 'allowed, nothing found' result."""
    return GuardResult(allowed=True)


def blocked(reason: str, checks: list[str]) -> GuardResult:
    """A 'not allowed' result."""
    return GuardResult(allowed=False, reason=reason, checks=checks)
