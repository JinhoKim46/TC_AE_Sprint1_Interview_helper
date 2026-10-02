# Interview Helper

A mock-interview practice app tailored to **one specific job application** (Turing College AE, Sprint 1 capstone). You upload the job description and your CV (cover letter optional). An LLM interviewer reads them and runs a realistic, multi-turn interview: it asks what *this* role's interviewers would ask, probes vague or unevidenced answers, and tests the gaps between the job description and your CV. Afterwards, an LLM judge scores the transcript against a rubric and writes evidence-based feedback.

## Quick start

```bash
uv sync
cp .env.example .env          # set OPENROUTER_API_KEY
uv run streamlit run app/main.py
```

The app listens on 127.0.0.1 only (set in `.streamlit/config.toml`), so it isn't reachable from other machines.

To keep it running as a local service in Docker instead: `cp .env.example .env`, set the key, then `make up` and open http://localhost:8501. Run `make` to list every command (`down`, `logs`, `status`, `backup`, `rebuild` …). Details: [`docs/06-docker.md`](docs/06-docker.md).

1. **Applications** → upload a JD and a CV as PDF or paste them (cover letter and company notes optional), or click **Load sample application** for a fictional one.
2. **Interview** → pick the application, the interview type and the difficulty, then **Start interview**.
3. Answer in the chat. When it ends (or you click **End interview**), click **Get my feedback report**.
4. **Settings** → interview defaults, plus developer settings: prompt variant, models, temperature, max tokens, reasoning effort, judge model; and usage and cost.
5. **History** → past interviews with their transcripts and reports; pick one application to see its progress (score trend, weakest rubric skills, job requirements over time, recurring advice).

Everything runs locally: a SQLite database in `data/`, model calls through OpenRouter.

## How it works

```text
Applications page ── PDF/paste ──► ingest (clean, validate) ──► SQLite (one application = its own copies)
                                                                      │
Interview page ──► start: [planning call → InterviewPlan JSON] ──► interviewer opening turn
                   each answer ──► guards (length, injection rules → Jev) ──► interviewer turn (JSON)
                                    code counts questions/follow-ups, enforces limits, decides the phase
                   end ──► exchanges + metrics (code) ──► LLM judge (rubric JSON) ──► aggregation (code) ──► report
```

| Module | Responsibility |
|---|---|
| `app/` | Streamlit UI only (pages, report view). No business logic. |
| `src/interview_app/llm/client.py` | The single chat gateway: OpenAI-compatible (provider-agnostic), retries, every call logged with tokens, cost and latency; `chat_json` validates against a pydantic schema and repairs once |
| `src/interview_app/llm/decide.py` | Jev decision-model client (typed yes/no, score and choice answers with probabilities) |
| `src/interview_app/llm/pricing.py` | OpenRouter model catalog: prices for cost estimates, data for the model picker |
| `src/interview_app/ingest.py`, `applications.py` | PDF/paste ingest and application storage |
| `src/interview_app/security/` | Guards: length/turn/budget limits, injection detection, spotlighting |
| `src/interview_app/interview/` | Personas, prompt rendering, the planning call, the interview engine |
| `src/interview_app/prompts/` | Jinja2 templates: 5 interviewer variants, planner, judge |
| `src/interview_app/evaluation/` | Exchanges, metrics, LLM judge, rubric aggregation, report storage |
| `src/interview_app/history.py` | Past sessions and per-application progress, computed in code from stored reports (no model calls) |
| `docs/rubric.json` | The single source of truth for rubric items, weights and bands |

Design rule throughout: **the model judges, code computes.** Models decide what to ask and how good an answer is. Code counts, enforces limits, weights, normalises and decides bands.

**Coaching mode** (pick it on the start form): after each answer, Jev scores it on the three rubric items that weigh most for that kind of question (one request, about 0.5 s; `evaluation/live.py`), and the app shows them as chips with a tip. The tip is built in code: it quotes the rubric's description of the next level up for the weakest item, so it is grounded in the rubric and costs nothing. The candidate can then **Retry** the answer (up to `LIMITS__MAX_RETRIES_PER_ANSWER`, default 2) or **Continue**. A retried attempt is kept in the database but marked superseded, so neither the interviewer nor the final judge ever sees it. Realistic mode shows nothing until the report.

**Weak-spot drill** (under every feedback report, on the Interview and History pages): code takes the job requirements the report rated *not discussed*, *not demonstrated* or *claimed only* (must-haves first, up to 4) and the rubric skills with the lowest average (below 3.5 of 5, up to 3), and starts a new interview for the same application with the same type, difficulty and models. The targets reach every prompt variant through the shared base prompt and the planner, so the plan and the questions aim at them (`interview/drill.py`).

## Course requirements and where they are met

| Requirement | Where |
|---|---|
| R1 Interview-prep focus | Application-specific mock interviews (JD + CV + optional cover letter) with a rubric report |
| R2 Front end | Streamlit, multi-page (`app/`) |
| R3 Allowed model | Interviewer `openai/gpt-5-mini` (default, configurable) |
| R4 Five system prompts, compared | `src/interview_app/prompts/interviewer_p1..p5_*.md`; compared in `lab/` → [`docs/05-prompt-comparison.md`](docs/05-prompt-comparison.md) |
| R5 Security guard | `src/interview_app/security/` (see *Security* below) |
| E3 More security constraints | Input validation, LLM-based (Jev) injection check, document flags |
| E4 Difficulty levels / E7 Personas | Interview type + difficulty → interviewer persona (`interview/persona.py`) |
| E8 Tune a setting | `lab/sweep_setting.py` (reasoning effort), results in `docs/05-prompt-comparison.md` |
| M1 All model settings in the UI | Settings → Developer settings |
| M2 Two+ JSON output formats | `InterviewPlan`, `InterviewerTurn` (3 variants), `Judgement` / `Report` |
| M3 Prompt price | Cost per session (live) and Settings → Usage and cost; prices from the OpenRouter models endpoint |
| M6 Job description field | The whole app is built around the JD (+ CV, cover letter, company notes) |
| M7 Choose the LLM | Model pickers on the Settings page |
| M9 Guard + developer settings separated | Developer settings behind a toggle on the Settings page |
| H1 Full chatbot | Multi-turn interview with persistent sessions (`interview/engine.py`) |
| H4 Open-source LLMs | `google/gemma-4-31b-it`, `minimax/minimax-m2.7` in the model picker |
| H5 LLM-as-a-judge | Candidate report (`evaluation/`) and interviewer-quality judge (`lab/`) |

## Prompt engineering

### Message roles

- **system**: our instructions: persona, rules, the documents (wrapped as data), the output format.
- **user**: the candidate's answers, wrapped in `<candidate_answer>` tags after passing the guards.
- **assistant**: the interviewer's earlier turns, sent back so the model sees the whole conversation.
- A short **system** message at the end carries the status the app computed (questions asked, follow-ups used, what to do next). It sits last so the long system prompt above stays identical between turns, and the provider can cache it.

### The five interviewer prompts (R4)

Each variant is the zero-shot baseline plus **exactly one** technique, so a comparison shows what each technique adds.

| Variant | Technique | What changes |
|---|---|---|
| P1 | Zero-shot | Instructions only: persona line, core rules, documents, output format |
| P2 | Few-shot | + worked example turns from a *different* fictional interview (copy the pattern, not the content) |
| P3 | Chain-of-thought | + private `notes` field written **before** the message: plan on turn 1, reasoning after each answer |
| P4 | Role-rich + prompt chaining | + detailed persona, the interviewer guideline, and a plan made by a separate planning call |
| P5 | Self-critique | + `draft` → `critique` against a checklist → final message, all in one turn |

Field order in the JSON schema is part of the technique: a model writes JSON top to bottom, so `notes`, `draft` and `critique` come before `message`.

### Which prompt works best

`lab/compare_prompts.py` runs each variant against a simulated candidate (Gemini 2.5 Flash playing strong, weak and evasive personas from the fictional sample CV) and has Jev judge each transcript on the interviewer-quality items in rubric §12. Full results and limitations: [`docs/05-prompt-comparison.md`](docs/05-prompt-comparison.md).

| Variant | Realism (I9, 1–5) | Mean follow-ups per session | $ / session | s / turn |
|---|---|---|---|---|
| P1 zero-shot | 3.69 | 6.0 | 0.009 | 2.7 |
| P2 few-shot | 4.06 | 5.7 | 0.010 | 2.9 |
| P3 chain-of-thought | 3.96 | 7.0 | 0.015 | 3.8 |
| **P4 role-rich + plan** | **4.07** | **3.3 (2 / 2 / 6 for strong / weak / evasive)** | 0.016 | 2.9 |
| P5 self-critique | 4.02 | 6.7 | 0.016 | 5.2 |

What the data supports:

- **Zero-shot (P1) scored lowest on realism** (3.69 vs 3.96–4.07), mostly from one session (weak persona, 3.38). With one session per persona this is a lead, not a proven gap.
- **P2, P4 and P5 are within noise of each other** with one session per persona. P4's adaptive follow-ups (2 / 2 / 6) in the first run did **not** reproduce in a second run (4 / 4 / 4).
- **All five passed the safety release gate:** no fabrication, coaching, illegal questions or role breaks.
- **All five packed several sub-questions into a turn.** Spelling out "one question" in the shared base prompt made turns 18–28% shorter (P2 −28%, P4 −18%). Stacking still happens in at least one turn per session, so it's only partly fixed.

**P4 stays the default.** It follows the full interviewer guideline and a plan of the job's requirements, which makes coverage traceable. **P2** is the cheaper alternative, at about 60% of the cost and with no planning wait. Separating P2, P4 and P5 for certain needs a larger run (at least 3 sessions per persona).

E8 (one setting tuned): with P4, `reasoning_effort` medium vs low doubled the latency (2.9 → 6.0 s per turn), cost about 50% more, and gave no quality gain. So the interviewer runs at `low`.

### Output types

- **Structured JSON** (`response_format: json_schema`) for every interviewer turn, the interview plan and the judge's evaluation. It's validated with pydantic and repaired once if invalid.
- **Typed probabilities** from Jev (decision model): `noul` (yes/no probability), `score` (distribution over levels), `choice`. No text to parse, and code sets the thresholds.
- **Free text** inside JSON fields (the interviewer's message, the feedback).

### Model settings

| Setting | Effect | Used here |
|---|---|---|
| `temperature` | Randomness of token sampling. Low = repeatable, high = varied | Judge at 0 for stable scores; gpt-5 models ignore it |
| `max_tokens` | Hard cap on output length. Too low cuts the JSON off and makes it invalid | Judge 8000; interviewer: provider default |
| `reasoning_effort` | How much a reasoning model thinks before answering: quality vs. latency and cost | Interviewer `low` (≈3 s per turn); planner `low` (21 s vs 36 s at `medium`, same plan structure) |
| `model` | Capability, price, speed; judge from a different family than the interviewer (self-preference bias) | Interviewer gpt-5-mini, judge claude-haiku-4.5 |

## Security

Untrusted text (JD, CV, cover letter, notes, answers) goes through guards before it reaches a model, mapped to the OWASP Top 10 for LLM applications:

- **LLM01 Prompt injection:** (1) regex rules for known patterns ("ignore previous instructions", fake role markers, chat-template tokens, score manipulation, delimiter escapes); (2) a Jev yes/no check for paraphrased attacks, with a threshold set in code; (3) **spotlighting**: all user text is wrapped in `<document>` / `<candidate_answer>` tags that it cannot close early, and the prompts say this text is data. Model-written text that came from those documents (the P4 plan, the judge's requirement list, the interviewer's turns in the judge transcript) is wrapped the same way, against second-order injection. Rules and wrapping run on a canonical form of the text (NFKC, zero-width and other format characters removed, HTML-entity forms of our tags caught), so Unicode look-alikes don't slip past them; Cyrillic homoglyphs are not covered. The checks run before the answer is stored: a blocked answer is never saved and never reaches the interviewer or the judge (the Jev check does send the answer text to Jev, via OpenRouter, to classify it). Suspicious documents are flagged for the user to confirm.
- **LLM05 Improper output handling:** model replies, report text and the candidate's own answers are shown as plain text. The UI escapes markdown (`ui_common.safe_md`) and never enables raw HTML, so a reply can't run a script, load a tracking image (`![](https://…)`), add a link or render `$…$` as LaTeX.
- **LLM10 Unbounded consumption:** limits on upload size, PDF pages, document and answer length, turns and spend per session. At a limit, code forces the interview to close. Document length is checked before the (paid) injection check runs, and a document too long to check in one Jev request is flagged instead. PDF reading is bounded against decompression bombs (5 MB per stream, a text cap and a 20 s timeout).
- **Grounding:** the judge must quote the candidate for requirement credit and strengths, and code verifies the quote against the cited turns (at least 2 words, matched in order; parts joined with "..." or ";" may come from different cited turns). An unverified positive requirement rating scores 0.
- **Local only:** Streamlit listens on `127.0.0.1`; the SQLite file is owner-only (mode 600) and deleted rows are zeroed (`secure_delete`).

## Known limitations

- **Judge variance:** a single judge run can score the same transcript several points apart (observed 56.6 vs 71.5). Reports now use the median of 3 parallel runs and show all three scores. On a real interview the runs scored 54.7, 45.0 and 45.0, a median of 45.0. That takes about 60 s and $0.10 per report; set `JUDGE_RUNS=1` in `.env` for the cheaper single run.
- **Partial rubric:** the red-flag checks (N-items) and the logistics item (S5) are not judged yet. Their weight is redistributed, and only the "no company motivation" penalty applies.
- **Simulated evaluation:** the prompt comparison uses a simulated candidate and a single fictional application, so the numbers are indicative, not conclusive.
- **Latency:** starting an interview takes about 25 s (a ~21 s planning call, then the opening turn), and a report about a minute.
- **Single user, local only:** MFA is designed and specified as tests (PR #4, closed without merging) but not built. Owned rows carry a `user_id` and the application, interview and history queries filter on it, but with one built-in user that separation is untested in real use.
- **One interview at a time:** a second interview can't start while one is active; a start that hangs in "preparing" is marked failed after `limits.start_timeout_minutes` (15 min), and a start that was ended meanwhile says so.
- **Lab numbers predate later prompt edits:** the prompt comparison ran on the prompts of PRs #16/#17; later PRs changed them again without a re-run (see `docs/05`).

## Next improvements

- The N-item red-flag checks with Jev.
- Calibrate the live Jev scores against the LLM judge (they are indicative until then).
- Voice (speech-to-text / text-to-speech); JD import from URL.
- A larger evaluation set (several applications, human-rated transcripts) to calibrate the judge.

## Development

```bash
uv run ruff check && uv run ruff format --check
uv run pytest -m "not live"   # unit and UI tests (no API calls) — what CI runs
uv run pytest -m live         # real-API tests (needs .env)
```

Every change goes through a branch in a git worktree and a PR to `main`, merged when CI (lint + tests) passes. See [`CLAUDE.md`](CLAUDE.md) for the rules.

## Docs

| File | What it is |
|---|---|
| [`reports/interview-helper-report.html`](reports/interview-helper-report.html) | Interactive report: clickable system map, session walkthrough, grading map, stack, decisions, prompt chart |
| [`reports/code-flow-report.html`](reports/code-flow-report.html) | Interactive code-flow report generated from the source: agents, prompt journey, call graph, data flow, sequence diagrams, module index |
| [`reports/code_map.json`](reports/code_map.json) | The code map behind it (modules, functions, call edges, model calls, templates, tables); regenerate with `uv run python reports/tools/build_code_map.py` |
| [`reports/2026-10-02-project-report.md`](reports/2026-10-02-project-report.md) | Project report: architecture, stack, decisions, grading map, evidence, risks, next steps |
| [`docs/00-project-objective.md`](docs/00-project-objective.md) | The course brief and my understanding of every requirement |
| [`docs/04-design-spec.md`](docs/04-design-spec.md) | The approved design and the changes since |
| [`docs/05-prompt-comparison.md`](docs/05-prompt-comparison.md) | R4: the five prompts compared |
| [`docs/06-docker.md`](docs/06-docker.md) | Run the app as a local Docker service; `make` commands |
| [`docs/01-interviewer-guideline.md`](docs/01-interviewer-guideline.md), [`02-question-bank.md`](docs/02-question-bank.md), [`03-evaluation-rubric.md`](docs/03-evaluation-rubric.md) | Interviewer and evaluator reference material |
