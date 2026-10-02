"""Hard limits checked in code (OWASP LLM10: Unbounded Consumption).

Every model call costs money and time. Without limits, one very long answer, a runaway loop, or a
user (or script) that keeps chatting could burn through the API budget. These checks are cheap,
deterministic and run *before* any model is called. The numbers live in `config.Limits`.
"""

from interview_app.config import Limits
from interview_app.security.models import GuardResult, blocked, ok


def check_answer_length(text: str, limits: Limits) -> GuardResult:
    """Block empty answers (nothing to score) and answers over `limits.max_answer_chars`.

    A huge answer is expensive (every later turn re-sends the history) and is also a common way to
    hide an injection deep inside harmless-looking text.
    """
    if not text.strip():
        return blocked("Your answer is empty. Please type an answer.", ["length:empty"])
    if len(text) > limits.max_answer_chars:
        return blocked(
            f"Your answer is too long ({len(text):,} characters; the limit is "
            f"{limits.max_answer_chars:,}). Please shorten it.",
            ["length"],
        )
    return ok()


def check_budget(spent_usd: float, limits: Limits) -> GuardResult:
    """Block further model calls once this session has spent its budget."""
    if spent_usd >= limits.max_session_cost_usd:
        return blocked(
            f"This session reached its cost limit (${limits.max_session_cost_usd:.2f}). "
            "Please finish the interview or start a new session.",
            ["budget"],
        )
    return ok()


def check_turns(turn_count: int, limits: Limits) -> GuardResult:
    """Block once the interview reaches `limits.max_turns` turns (stops endless conversations)."""
    if turn_count >= limits.max_turns:
        return blocked(
            f"This interview reached its maximum length ({limits.max_turns} turns). Please finish it.",
            ["turns"],
        )
    return ok()
