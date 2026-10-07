# Interview Practice App — Design Spec

The current design, kept short so it can be read in one sitting. **Why** the big decisions were made is in the [ADRs](adr/README.md); every dated change since the design was approved on 2026-10-02 is in the [decision log](decision-log.md); the finished build plan is [archived](archive/2026-10-02-build-plan.md). Feature specs and their tickets live in `docs/specs/`.

## Context

Sprint 1 capstone (brief: `docs/00-project-objective.md`), reviewed Fri 2026-10-09, hard deadline Mon 2026-10-12. After the review the owner keeps using it for real job applications, so it is a clean, tested, readable personal tool rather than a throwaway demo. Reference inputs: `docs/01-interviewer-guideline.md`, `02-question-bank.md`, `03-evaluation-rubric.md` and `rubric.json` (the source of truth for scoring).

## Key decisions

| ADR | Decision |
|---|---|
| [0001](adr/0001-ui-free-core-with-thin-streamlit-ui.md) | A UI-free core package with a thin Streamlit UI |
| [0002](adr/0002-local-single-user-sqlite-no-login.md) | A local single-user app on SQLite, with no login but a `user_id` on every row |
| [0003](adr/0003-model-judges-code-computes.md) | The model judges, code computes: a two-tier evaluation |
| [0004](adr/0004-judge-from-another-family-median-of-three.md) | The final judge comes from another model family and runs three times |
| [0005](adr/0005-layered-injection-guard.md) | A layered prompt-injection guard: answers are blocked, documents are flagged |

## Design at a glance

| Topic | Design |
|---|---|
| UI | Streamlit `st.navigation` multipage over a core package that never imports Streamlit ([ADR 0001](adr/0001-ui-free-core-with-thin-streamlit-ui.md)) |
| Users / hosting | One built-in local user, `127.0.0.1` only, no login; `user_id` on every owned row ([ADR 0002](adr/0002-local-single-user-sqlite-no-login.md)) |
| DB | SQLite via SQLModel (moving to Postgres later = changing the URL) |
| Providers | One OpenAI-compatible client to OpenRouter (`llm/client.py`) plus the Jev decisions client (`llm/decide.py`); every call logged as an `LLMCall` row |
| Models (defaults, all changeable in Settings) | Interviewer and planner `openai/gpt-5-mini` (R3); judge `anthropic/claude-haiku-4.5` ([ADR 0004](adr/0004-judge-from-another-family-median-of-three.md)); candidate simulator `google/gemini-2.5-flash`; live scoring + guard Jev; open-weight options in the picker (H4). Model ids live only in `config.py` |
| Inputs | JD + CV required; cover letter and company notes optional. PDF or pasted text. Each application owns its own copies |
| Interview | Type (recruiter screen, hiring manager, technical deep-dive, ML case / system design, behavioural, final round) + difficulty (friendly / standard / tough) → a derived persona. Length (Quick / Standard / Full / Custom) sets the number of main questions; a follow-up cap and an elapsed-time display |
| Modes | Realistic (live scores hidden, report at the end) and Coaching (live score chips + tip + retry; the last attempt is scored and the session is marked "coached") |
| Channel | Text, or Voice: TTS speaks each question; answers are spoken (transcribed, then confirmed and sent like typed text) or typed. Chosen per session |
| Turn format | Structured JSON per interviewer turn `{stage, question_id, message, is_final}`; no streaming |
| 5 prompts (R4) | P1 zero-shot · P2 few-shot · P3 CoT plan-first · P4 role-rich (gets the planning call's plan) · P5 self-critique; compared in `lab/` |
| Evaluation | Live Jev scores on three rubric items per answer; a final LLM-judge report on the full rubric, quotes checked and scores aggregated in code ([ADR 0003](adr/0003-model-judges-code-computes.md)) |
| Security | Limits, canonicalised regex rules, a Jev injection check and spotlighting ([ADR 0005](adr/0005-layered-injection-guard.md)); details in `docs/09-security.md` |
| Pages | Home, Dashboard, Applications, Interview, History, Settings (user + Developer section) |
| Privacy / repo | Public repo. Gitignored: `docs/applications/` (real CVs), `references/app_design/`, `data/`, `.env`, worktrees. Only a fictional sample application is committed |
| Quality bar | Type hints, pydantic, pytest with a mocked LLM, ruff, pydantic-settings + `.env`, logging, retries, comments that explain *why* |

Not built from the original plan: login and MFA (parked in PR #4), JD import from a URL, the interviewer avatar (M8), Jev-vs-judge agreement on the Dashboard, and the guard-threshold sweep (`lab/tune_guard.py`).

Optional tasks covered: E1 E2 E3 E4 E7 (E8 via the reasoning-effort sweep, `lab/sweep_setting.py`: gpt-5 ignores temperature), M1 M2 M3 M6 M7 M9, H1 H4 H5, well over the 2 medium + 1 hard needed for the bonus.

## Components beyond the brief

1. **Planning step** (prompt chaining): JD + CV + cover letter → `InterviewPlan` JSON (requirement map, claim map, probe list). This is structured format #1; the evaluation is #2.
2. **Candidate simulator** to compare prompts reproducibly (strong / weak / evasive personas).
3. **LLM call log**: every call stores its role, model, tokens, cost and latency, which feeds the cost display and the Dashboard.
4. **Pricing cache** from OpenRouter `GET /api/v1/models` (refreshed daily).
5. **Session persistence**: every turn is written to the DB at once, so a refresh or crash resumes the interview.
6. **Code-enforced limits**: question count, follow-up cap, turn cap, spend cap per session. When a limit is hit, code forces the closing stage.
7. **Missing cover letter**: the prompt and rubric skip the items that depend on it.
8. **Data deletion**: deleting an application deletes its sessions, calls and audio.
9. **Failure handling**: retry with backoff, then a friendly error, and state is kept. Invalid JSON → one repair retry. Jev down → no live scores (the final judge still runs) and the guard falls back to rules. TTS failure → the question is shown as text. STT failure, silence or an over-long recording → a short notice; typing still works.

## Architecture

```
project_Interview_App/
  app/                              # Streamlit only, no business logic
    main.py                         # st.navigation, page registry
    views/{home,dashboard,applications,interview,history,settings}.py
    ui_common.py  report_view.py  drill_ui.py  wait_ui.py  styles/app.css
  src/interview_app/
    config.py                       # pydantic-settings: role → model map, limits, guard, voice
    db.py                           # SQLModel tables; user_id on every owned row
    users.py  preferences.py  applications.py  ingest.py  history.py
    dashboard.py  cost.py  usage.py  journey.py  demo.py  voice.py
    llm/{client,decide,pricing,calllog}.py      # every model call goes through here
    security/{limits,injection,spotlight,models}.py
    interview/{persona,plan,prompting,engine,drill,schemas}.py
    evaluation/{rubric,live,judge,exchanges,metrics,aggregate,service,schemas}.py
    lab/{candidate,runner,compare,judge}.py
    prompts/*.md                    # Jinja2: plan, interviewer_p1..p5, judge, candidate_sim, shared parts
  lab/compare_prompts.py  lab/sweep_setting.py  # CLI experiments, results in lab/results/
  samples/demo_application/         # fictional JD, CV, cover letter
  tests/                            # unit tests, LLM and Jev mocked
```

## Core flows

- **Import:** upload or paste → validate → injection scan (warnings shown) → text preview and edit → save the Application.
- **Start:** the planning call builds the `InterviewPlan`; the waiting panel shows its real steps.
- **Interview turn:** answer (typed, or spoken → transcript draft → confirmed) → limits + guard → Jev live scores and a follow-up signal → the engine builds the messages (system = variant + persona + plan + spotlighted documents + routing hint, then the history) → `chat_json` → validate → save Turn and live scores → show (TTS in Voice; score chips + tip in Coaching) → repeat until `is_final` or a limit.
- **Finish:** metrics in code → three parallel judge runs → aggregate in code (rubric weights, caps, bands) → the median run is the report → History and Dashboard.
- **Guard outcome:** a blocked answer is not sent and comes back for rephrasing; a flagged document must be confirmed or edited by the user.

## Known risks

- Judge scores vary between runs (median-of-3 reduces this) and the judge is not calibrated against human scores ([ADR 0004](adr/0004-judge-from-another-family-median-of-three.md)).
- Live Jev scores are not calibrated against the judge, so they are labelled indicative.
- The guard fails open when Jev is down, and its threshold is untuned ([ADR 0005](adr/0005-layered-injection-guard.md)).
- Some open-weight models don't support strict JSON schemas → JSON mode + pydantic validation + one repair retry.
- Waits: about 30 s to start and about a minute for a report.
