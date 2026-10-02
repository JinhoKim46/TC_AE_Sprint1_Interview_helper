"""Security guards: run in code on every piece of untrusted user text before it reaches a model.

- `limits`: length, budget and turn limits (OWASP LLM10, unbounded consumption).
- `injection`: regex rules + a Jev yes/no check for prompt injection (OWASP LLM01).
- `spotlight`: wraps untrusted text as data inside prompts (defence in depth for LLM01).
"""

from interview_app.security.injection import RULES, InjectionGuard, find_rule_hits, split_into_chunks
from interview_app.security.limits import check_answer_length, check_budget, check_turns
from interview_app.security.models import GuardResult
from interview_app.security.spotlight import (
    ANSWER_DATA_NOTE,
    UNTRUSTED_DATA_NOTE,
    canonical,
    wrap_answer,
    wrap_untrusted,
)

__all__ = [
    "ANSWER_DATA_NOTE",
    "RULES",
    "UNTRUSTED_DATA_NOTE",
    "GuardResult",
    "InjectionGuard",
    "canonical",
    "check_answer_length",
    "check_budget",
    "check_turns",
    "find_rule_hits",
    "split_into_chunks",
    "wrap_answer",
    "wrap_untrusted",
]
