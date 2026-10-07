---
status: accepted
date: 2026-10-02
---

# The model judges, code computes: a two-tier evaluation

Language models are good at judging an answer against a criterion but unreliable at arithmetic, counting and applying weights, and an early real run gave requirement credit for skills that were only in the CV. So models only judge, and code does everything that can be computed: limits, counting, quote checks, weights, caps and score bands. Evaluation has two tiers. **Live:** after each answer, Jev (a decision model) scores three rubric items in about 0.4 s, and the tip is built in code from the rubric's next-level descriptor. **Final:** one LLM-judge call per session scores the full rubric, giving a rationale and a verbatim quote before each score. Code checks every quote against the cited candidate turns, and computes the overall score from the weights in `docs/rubric.json`.

## Considered Options

- **One LLM call that returns the final score:** simplest, but the score was inflatable (credit from the CV, unverifiable quotes) and the arithmetic varied from run to run.
- **A judge call per exchange:** finer-grained, but much slower and costlier for the final report.
- **An LLM for live scoring too:** prose to parse and several seconds of wait after each answer, against Jev's direct probability per rubric level.

## Consequences

- `docs/rubric.json` is the single source of truth: items, weights and caps are never copied into prompts or code.
- An unverified positive requirement rating becomes `not_demonstrated` (0 points) instead of counting.
- The red-flag items (N) and logistics (S5) are not judged yet, so their weight is redistributed.
- Live Jev scores are not yet calibrated against the final judge, so the UI labels them indicative.
