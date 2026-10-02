# Interview Helper App — Guideline Docs

These documents are the reference material for the two kinds of agents in the app:

| Agent | Role | Reads |
|---|---|---|
| **Interviewer agent** | Runs a realistic mock interview grounded in a specific JD, CV and cover letter | `04-design-spec.md` | The approved design: decisions, architecture, flows, git workflow, PR sequence, build order, verification |
| `brainstorming.md` | My original feature brainstorm (input to the design spec) |
| `01-interviewer-guideline.md`, `02-question-bank.md` |
| **Evaluator agent(s)** | Scores the finished transcript (LLM-as-a-judge and/or a decision model such as Jev) | `03-evaluation-rubric.md`, `rubric.json` |

## Files

| File | Purpose |
|---|---|
| `00-project-objective.md` | The full course brief with my understanding of each item: requirements, allowed models, every optional task (easy/medium/hard), evaluation criteria, submission, and a master checklist |
| `01-interviewer-guideline.md` | How the interviewer behaves: preparation, interview types, stage flow, follow-up rules, difficulty, conduct, and when to stop |
| `02-question-bank.md` | Question templates by category, each with the signal it probes and what a strong vs. weak answer looks like |
| `03-evaluation-rubric.md` | Evaluation design: transcript format, per-answer and per-session rubric items with anchored levels, red flags, aggregation, LLM-judge prompt, Jev/decision-model mapping, and calibration |
| `rubric.json` | The same rubric in machine-readable form (item ids, primitive, instructions, criteria, weights) so the app code loads one source of truth |
| `applications/` | **Local only (gitignored).** Real example applications. Per-application inputs: one folder per `<company>_<role>/` holding `jd.md`, `cv.md` (or `.pdf`/`.tex`), `cover_letter.md`, and optionally `company_notes.md` and `prep_notes.md` |

## Pipeline

```
applications/<company>_<role>/{jd, cv, cover_letter, company_notes?}
        │
        ▼
[1] Prep step (code + LLM): extract JD requirements, CV claims, cover-letter claims  →  interview_plan.json
        │
        ▼
[2] Interviewer agent (live, multi-turn)  →  transcript.json  (turn ids, timestamps, stage, question_id)
        │
        ▼
[3] Deterministic metrics (code): talk time, answer length, filler counts, coverage   →  metrics.json
        │
        ▼
[4] Evaluator(s): per-answer items + per-session items, evidence-cited               →  evaluation.json
        │
        ▼
[5] Aggregation (code): weights, caps, red-flag gates, final band + feedback report   →  report.md
```

Key design rules carried through all docs:

1. **Grounding.** Every question and every judgment is tied to the actual JD, CV and cover letter. The interviewer never invents facts about the candidate, and the evaluator never rewards claims the CV does not support.
2. **Evidence.** Every evaluator score cites transcript turn ids. A score with no evidence is invalid.
3. **The model judges, code computes.** Counting, timing, weighting and thresholds are done in code. The models only make the judgments that code can't.
4. **Separation.** The interviewer never sees the rubric's scoring anchors, so it can't "teach to the test". The evaluator never sees the interviewer's private notes, only the transcript and the source documents.
