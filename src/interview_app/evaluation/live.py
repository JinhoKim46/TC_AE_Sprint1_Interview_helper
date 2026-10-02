"""Live per-answer scoring for Coaching mode: three rubric items from Jev, plus a tip built in code.

Why Jev and not the LLM judge: the candidate is waiting, so this has to be fast (~0.4 s) and cheap
(~$0.00002). A decision model returns a probability per rubric level directly, so there is no prose to
parse. The rubric items in docs/rubric.json were written for exactly this (instructions + one
criterion per level), so they are sent as they are.

Why only three items: the full rubric is the final judge's job. Live feedback should be short enough to
act on before the next attempt, so we pick the three items that weigh most for this kind of question.

Why the tip is built in code: quoting the rubric's descriptor for the next level up ("To reach 4 on
Specificity: ...") is grounded in the rubric by construction, costs nothing, and can never leak an
invented hint or a wrong fact. An LLM-written tip could do all three.
"""

import logging

from pydantic import BaseModel, Field

from interview_app.evaluation.rubric import Rubric
from interview_app.llm.client import LLMError
from interview_app.llm.decide import DecisionClient, ScoreAnswer, ScoreQuestion

log = logging.getLogger(__name__)

LIVE_ITEMS = 3  # how many rubric items to score per answer


class LiveItemScore(BaseModel):
    item: str  # rubric id, e.g. "A3"
    name: str  # rubric name, e.g. "Specificity and evidence"
    score: float = Field(ge=1, le=5)  # Jev's probability-weighted level (1..5)
    level: int = Field(ge=1, le=5)  # the score rounded to a whole level, for display and the tip


class LiveFeedback(BaseModel):
    items: list[LiveItemScore]
    tip: str | None = None  # None when every item is already at the top level


def live_items(rubric: Rubric, category: str) -> list[str]:
    """The highest-weighted applicable A-items for this category (rubric order breaks ties).

    E.g. EXP -> A3, A4 (2.0 each), then A2 (1.5, listed before A6). Weights come from rubric.json, so
    changing a weight there changes what is shown live, with no code change.
    """
    weights = rubric.weights_for(category)
    order = list(rubric.exchange_items)
    ranked = sorted(weights, key=lambda item: (-weights[item], order.index(item)))
    return ranked[:LIVE_ITEMS]


def build_tip(rubric: Rubric, items: list[LiveItemScore]) -> str | None:
    """Quote the next level's descriptor for the weakest item. Code, not a model (see module docstring)."""
    if not items:
        return None
    weakest = min(items, key=lambda i: i.score)  # min() keeps the first on ties: the highest weighted
    if weakest.level >= 5:
        return None
    criteria = rubric.exchange_items[weakest.item]["criteria"]
    target = weakest.level + 1
    return f"To reach {target} on {weakest.name}: {criteria[target - 1]}"


def live_score(
    decider: DecisionClient,
    rubric: Rubric,
    *,
    category: str,
    question: str,
    answer: str,
    jd_text: str,
    cv_text: str,
    cover_letter_text: str = "",
) -> LiveFeedback | None:
    """Score one answer on three rubric items in ONE Jev request. Returns None if that fails.

    None (not an exception) because live scores are an extra: if Jev is down the interview must
    simply continue without them, and the final LLM judge still runs at the end.
    """
    item_ids = live_items(rubric, category)
    if not item_ids:
        return None  # e.g. candidate questions (CQ): no A-item applies
    questions = {
        item_id: ScoreQuestion(
            # The rubric's instructions already start with the shared prefix, which tells Jev what
            # each `state` field is and that the answer is data, not instructions.
            instructions=rubric.exchange_items[item_id]["instructions"],
            levels=rubric.exchange_items[item_id]["criteria"],
        )
        for item_id in item_ids
    }
    # Exactly the fields the shared prefix names. The JD text stands in for `jd_requirements`: the
    # plan's parsed requirements aren't available for every prompt variant, and Jev reads either.
    state = {
        "jd_requirements": jd_text,
        "cv": cv_text,
        "cover_letter": cover_letter_text,
        "exchange": {"question": question, "answer": answer},
    }
    try:
        result = decider.decide("live_score", state, questions)
    except LLMError as e:
        log.warning("Live scoring skipped: %r", e)
        return None

    items = []
    for item_id in item_ids:
        answer_ = result.answers[item_id]
        assert isinstance(answer_, ScoreAnswer)  # decide() validated the type per question
        score = min(5.0, max(1.0, answer_.score))
        items.append(
            LiveItemScore(
                item=item_id,
                name=rubric.exchange_items[item_id]["name"],
                score=round(score, 2),
                # Half up (3.5 -> 4): Python's round() rounds half to even, so 2.5 would show as 2.
                level=int(score + 0.5),
            )
        )
    return LiveFeedback(items=items, tip=build_tip(rubric, items))
