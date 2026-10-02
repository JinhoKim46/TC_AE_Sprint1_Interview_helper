"""Turn the judge's 1-5 scores into the report's numbers (rubric §6-7). Pure code, no model.

norm(s)              = (s - 1) / 4 * 100
exchange_score       = weighted mean of norm(item) over the items applicable to its category
experience_technical = mean exchange_score over EXP / TECH / CASE / RES exchanges
behavioral           = mean exchange_score over BEH exchanges
requirement_coverage = weighted mean of S2 points (must x2, nice x1), "not addressed" excluded
communication        = mean over exchanges of norm(A9) and norm(A10)
overall              = weighted sum of the components (weights depend on interview type)
                       - penalties, with missing components' weight redistributed proportionally
"""

import re
from difflib import SequenceMatcher
from statistics import mean

from interview_app.evaluation.exchanges import Exchange, turn_id
from interview_app.evaluation.metrics import SessionMetrics
from interview_app.evaluation.rubric import Rubric
from interview_app.evaluation.schemas import (
    ExchangeReport,
    ItemScore,
    Judgement,
    RequirementEvidence,
    Strength,
)

QUOTE_MATCH = 0.8  # share of a quote's words that must appear, in order, in the cited candidate turns
QUOTE_MIN_WORDS = 3  # "yes" or "Python" alone proves nothing


def usable(item: ItemScore, allowed: set[str], valid_turns: set[str], evidence_required: bool = True) -> bool:
    if item.item not in allowed or item.score is None:
        return False
    return not evidence_required or any(e in valid_turns for e in item.evidence)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def quote_found(quote: str, evidence: list[str], candidate_texts: dict[str, str]) -> bool:
    """Is the judge's quote really in the cited candidate turns?

    A cited turn id alone isn't proof: on a real session the judge cited an existing turn for a CV
    fact the candidate never said. So the judge must quote, and code checks the quote. Matching is on
    words (>= QUOTE_MATCH present), so small slips in punctuation or a dropped word don't void a true quote.
    """
    quote_words = _words(quote)
    if len(quote_words) < QUOTE_MIN_WORDS:
        return False
    for e in evidence:
        said = _words(candidate_texts.get(e, ""))
        # Ordered matching, in runs of at least two words: a bag of words would accept a "quote" stitched
        # together from common words scattered over a long answer.
        blocks = SequenceMatcher(None, quote_words, said, autojunk=False).get_matching_blocks()
        matched = sum(b.size for b in blocks if b.size >= 2)
        if matched / len(quote_words) >= QUOTE_MATCH:
            return True
    return False


def grounded_requirements(
    reqs: list[RequirementEvidence], candidate_texts: dict[str, str]
) -> list[RequirementEvidence]:
    """Rubric S2: only what was said in the interview counts — the CV alone earns nothing.

    A positive level (claimed and up) needs a verified quote. Without one it drops to "not_demonstrated"
    if the requirement was discussed in cited candidate turns (it came up, nothing was shown), else to
    "not_addressed". Dropping straight to "not_addressed" would be wrong in the candidate's favour: it is
    excluded from coverage, so a discussed gap would vanish instead of counting as 0.
    """
    out = []
    for r in reqs:
        cited = [e for e in r.evidence if e in candidate_texts]
        level = r.level
        if level not in ("not_addressed", "not_demonstrated") and not quote_found(
            r.quote, cited, candidate_texts
        ):
            level = "not_demonstrated" if cited else "not_addressed"
        elif level == "not_demonstrated" and not cited:
            level = "not_addressed"
        if level != r.level:
            r = r.model_copy(update={"level": level, "rationale": f"{r.rationale} (no interview evidence)"})
        out.append(r.model_copy(update={"evidence": cited}))
    return out


def grounded_strengths(strengths: list[Strength], candidate_texts: dict[str, str]) -> list[Strength]:
    """Praise must point at something the candidate actually said."""
    return [s for s in strengths if quote_found(s.quote, s.evidence, candidate_texts)]


def _first_per_item(items) -> list[ItemScore]:
    """One score per rubric item: a duplicate (the judge listing A3 twice) would count double."""
    seen: dict[str, ItemScore] = {}
    for i in items:
        seen.setdefault(i.item, i)
    return list(seen.values())


def exchange_score(items: list[ItemScore], weights: dict[str, float], rubric: Rubric) -> float | None:
    pairs = [(weights[i.item], rubric.norm(i.score)) for i in items]
    total = sum(w for w, _ in pairs)
    return round(sum(w * v for w, v in pairs) / total, 1) if total else None


def weighted_overall(components: dict[str, float | None], weights: dict[str, float]) -> float | None:
    """Missing components (None) drop out and their weight is spread over the rest (null_item_policy)."""
    present = {k: w for k, w in weights.items() if components.get(k) is not None}
    total = sum(present.values())
    if not total:
        return None
    return sum(w * components[k] for k, w in present.items()) / total


def aggregate(
    judgement: Judgement,
    exchanges: list[Exchange],
    metrics: SessionMetrics,
    rubric: Rubric,
    interview_type: str,
) -> dict:
    """Evidence (turn ids) and quotes are checked against the candidate's turns only."""
    candidate_texts = {turn_id(t.idx): t.text for ex in exchanges for t in ex.candidate_turns}
    by_id = {j.exchange_id: j for j in judgement.exchanges}
    metric_by_id = {m.exchange_id: m for m in metrics.exchanges}
    reports: list[ExchangeReport] = []
    for ex in exchanges:
        weights = rubric.weights_for(ex.category, ex.question_id)
        judged = by_id.get(ex.exchange_id)
        # An answer's score must cite that answer, not a turn from another exchange.
        own_turns = {turn_id(t.idx) for t in ex.candidate_turns}
        items = _first_per_item(
            i
            for i in (judged.items if judged else [])
            if usable(i, set(weights), own_turns, rubric.evidence_required)
        )
        m = metric_by_id[ex.exchange_id]
        flags = (["long answer"] if m.long_answer else []) + (["short answer"] if m.short_answer else [])
        reports.append(
            ExchangeReport(
                exchange_id=ex.exchange_id,
                category=ex.category,
                question=ex.question,
                score=exchange_score(items, weights, rubric) if ex.candidate_turns else None,
                items=items,
                answer_words=m.answer_words,
                followups=m.followups,
                flags=flags,
            )
        )

    def section(categories: list[str]) -> float | None:
        scores = [r.score for r in reports if r.category in categories and r.score is not None]
        return round(mean(scores), 1) if scores else None

    sections = rubric.section_categories()
    # Session items follow the same evidence rule as exchange items. S4 (the candidate's questions)
    # needs a candidate-questions exchange: an interview ended before that stage has no questions to rate.
    session_allowed = {"S1", "S3"} | ({"S4"} if any(ex.category == "CQ" for ex in exchanges) else set())
    session = {
        i.item: i
        for i in _first_per_item(
            i
            for i in judgement.session_items
            if usable(i, session_allowed, set(candidate_texts), rubric.evidence_required)
        )
    }

    requirements = grounded_requirements(judgement.requirements, candidate_texts)
    points = rubric.requirement_points()
    req_weights = rubric.requirement_weights()
    rated = [(req_weights[r.priority], points[r.level]) for r in requirements if points[r.level] is not None]
    coverage = round(sum(w * p for w, p in rated) / sum(w for w, _ in rated), 1) if rated else None

    comm_values = [rubric.norm(i.score) for r in reports for i in r.items if i.item in ("A9", "A10")]
    components = {
        "requirement_coverage": coverage,
        "experience_technical": section(sections["experience_technical"]),
        "behavioral": section(sections["behavioral"]),
        "S1": rubric.norm(session["S1"].score) if "S1" in session else None,
        "S3": rubric.norm(session["S3"].score) if "S3" in session else None,
        "S4": rubric.norm(session["S4"].score) if "S4" in session else None,
        "communication": round(mean(comm_values), 1) if comm_values else None,
        "logistics": None,  # S5 is not judged by the app yet; its weight is redistributed
    }

    penalties: list[str] = []
    overall = weighted_overall(components, rubric.aggregation_weights(interview_type))
    if overall is not None and "S1" in session and session["S1"].score == 1:
        # RF5: no (or wrong) company knowledge. The other red flags need the N-item checks (not run yet).
        overall -= rubric.penalty("major")
        penalties.append("RF5: no specific or correct motivation for this company (−5)")
    overall = None if overall is None else round(max(0.0, min(100.0, overall)), 1)
    return {
        "overall": overall,
        "band": rubric.band(overall) if overall is not None else None,
        "components": components,
        "penalties": penalties,
        "exchanges": reports,
        "session_items": list(session.values()),
        "requirements": requirements,
        "strengths": grounded_strengths(judgement.strengths, candidate_texts),
    }
