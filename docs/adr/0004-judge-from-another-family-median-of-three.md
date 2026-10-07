---
status: accepted
date: 2026-10-02
---

# The final judge comes from another model family and runs three times

The interviewer must be `openai/gpt-5-mini` (course requirement R3). A judge from the same family tends to prefer that family's style (self-preference bias), and here half the transcript is the interviewer's own text. So the default judge is `anthropic/claude-haiku-4.5` (`RoleModels.judge` in `config.py`). One judge run can differ from the next by several points, so each report runs the judge three times in parallel and shows the run whose overall score is the median. The whole run is picked, not a median per item, so the numbers and the written feedback come from the same judgement (`evaluation/service.py`).

## Evidence

In the audit, the same strong, weak and evasive simulated transcripts were scored 77 / 76 / 75 by `gpt-5-mini` and 76 / 55 / 58 by Haiku: only Haiku separated the candidates. This was one transcript per persona, so it shows that `gpt-5-mini` failed on this test, not that Haiku is the better judge in general. Same-family bias is the design reason, but the audit did not isolate it from plain leniency.

## Considered Options

- **`gpt-5-mini` as the judge:** one provider and cheaper, but it did not discriminate in the audit.
- **A single judge run:** about three times cheaper and faster, but the score could move by several points between runs. Still available through `JUDGE_RUNS=1`.

## Consequences

- A report takes about 60–80 s and costs about $0.10 (three Haiku runs), and the app depends on a second provider.
- The judge has not yet been calibrated against human-scored transcripts; that is the next step to trust its numbers.
