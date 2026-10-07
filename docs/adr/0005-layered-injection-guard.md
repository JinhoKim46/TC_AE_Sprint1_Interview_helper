---
status: accepted
date: 2026-10-02
---

# A layered prompt-injection guard: answers are blocked, documents are flagged

Every JD, CV, cover letter, company note and answer is untrusted text that ends up in a model prompt (OWASP LLM01). No single defence catches everything, so the guard has layers: limits on length, turns and spend (LLM10); a canonical form of the text (NFKC, zero-width characters removed) so Unicode tricks can't hide an attack; regex rules for the well-known patterns; and Jev, a decision model, for paraphrases, returning a probability that code compares with `guard.injection_threshold` (0.7). On top of that, untrusted text is always wrapped as data in prompts (`security/spotlight.py`), so an attack that slips through is unlikely to be obeyed. A hit on an **answer** blocks it and asks the candidate to rephrase, because losing one answer is cheap. A hit on a **document** only flags it for the user to confirm or edit, because a real job ad can contain odd text and a wrong block would make the app unusable.

## Considered Options

- **Rules only:** free and explainable, but they miss paraphrased attacks.
- **An LLM classifier that writes its verdict:** slower, and its prose must be parsed; Jev gives a probability directly.
- **Blocking documents too:** safer on paper, but a false positive would lock the user out of their own application.

## Consequences

- If Jev is unavailable, the guard **fails open**: the text passes on the rules and spotlighting alone, and the result records `model_unavailable`. This was chosen so an outage of the guard model never stops an interview.
- The 0.7 threshold has not been tuned on a labelled attack set yet; the planned `lab/tune_guard.py` was not built.
- Every answer costs one extra Jev call (a fraction of a second, a tiny fraction of a cent).
