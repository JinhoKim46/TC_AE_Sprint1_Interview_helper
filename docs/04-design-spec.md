# Interview Practice App — Design Plan

## Changes since approval (kept up to date)

| Date | Change | Why |
|---|---|---|
| 2026-10-02 | **Priority:** the grading criteria and the core flow (upload JD + CV, optional cover letter → tailored interview → feedback) come first. Secondary until after the review: MFA, Jev live scoring + Coaching mode, History, Dashboard, avatars (M8), JD from URL, voice. | Owner's decision; the extras aren't graded |
| 2026-10-02 | **MFA parked** in draft PR #4 (its behaviour is specified as tests). The app runs as one built-in local user; tables keep `user_id`. | Not graded; local single-user app |
| 2026-10-02 | **Models:** this account's OpenRouter guardrail blocks `openai/gpt-5`, DeepSeek and `z-ai/glm-5.2`. Open-weight options (H4) are `google/gemma-4-31b-it` and `minimax/minimax-m2.7`. | Checked with real calls (see `config.py`) |
| 2026-10-02 | **Prompt variants:** only P4 receives the plan from the separate planning call (prompt chaining); P3 plans in its own `notes`; P1/P2/P5 get no plan. Each variant = zero-shot baseline + one technique. | Clean comparison of techniques (R4) |
| 2026-10-02 | **Planning call** at `reasoning_effort="low"`: ~21 s / $0.006 vs ~36 s / $0.012 at medium, same plan structure. | Start-up latency |
| 2026-10-02 | **Developer settings** live on the Settings page (prompt variant, models, temperature, max tokens, reasoning effort, judge model), not on the Interview page. | M9 separation |
| 2026-10-02 | **Final judge:** one call per session (not per exchange); rationale and evidence before each score; requirement credit and strengths need a verbatim quote that code checks in the cited candidate turns. Median-of-3 runs is not done yet (scores vary between runs). | Latency; a real run showed CV-only credit |
| 2026-10-02 | **Jev's role so far:** injection guard (rules → Jev) and the interviewer-quality judge in `lab/`. Live per-answer scoring is secondary. | Priority change above |

## Context
Sprint 1 capstone (brief: `docs/00-project-objective.md`). After the review the user keeps using it for real job
applications → a clean, tested, readable personal tool rather than a throwaway demo. Existing inputs:
`docs/01-interviewer-guideline.md`, `02-question-bank.md`, `03-evaluation-rubric.md`, `rubric.json` (the source of truth
for scoring), `docs/applications/**` (real example cases, mostly PDFs), and `references/app_design/` (Attio, Plain).
Dates: build Fri 10/2 → Thu 10/8, **review Fri 2026-10-09**, hard submission deadline Mon 10/12.
Scope: **everything, including Jev and voice**, before the review. Voice sits behind a feature flag.

## Decisions (from the grilling)
| Topic | Decision |
|---|---|
| UI | UI-independent Python core package + Streamlit (`st.navigation` multipage) |
| Users / hosting | Single user for now, local machine only. Data model is multi-user ready: a `User` table, and `user_id` on every owned row (Application, Session, LLMCall...). Registration closes after the first account |
| Auth + MFA | Local password (argon2-cffi) + TOTP (pyotp; QR enrolment via `qrcode`; 10 one-time recovery codes, stored hashed). Lockout after 5 failed attempts (15 min), idle session timeout (30 min), all pages behind an auth gate in `app/main.py`. The TOTP secret is encrypted at rest with a key from `.env` |
| DB | SQLite via SQLModel (moving to Postgres later = changing the URL) |
| Providers | One OpenAI-compatible client; provider profiles in config. OpenRouter only for now (no local model beats it on 16 GB VRAM); an Ollama profile can be added later |
| Models (defaults, all changeable) | Interviewer `openai/gpt-5-mini` (R3); final judge from another family (Claude Haiku 4.5 / Gemini Flash); candidate simulator from a third family; live scoring + guard = **Jev**; avatar `google/gemini-2.5-flash-image`; open-weight options in the picker for H4 (Gemma 4 31B, DeepSeek V4, GLM 5.2, MiniMax M2.7) |
| Inputs | JD + CV required; cover letter and company notes optional. Formats: PDF, pasted text, JD from URL. Each application owns its own copies |
| Interview | Type (recruiter_screen, hiring_manager, technical_deep_dive, ml_case/system_design, behavioral, final_round) + difficulty (friendly/standard/tough) → derived persona; "Advanced" override. Target number of main questions + follow-up cap + elapsed-time display |
| Modes | Realistic (live scores hidden, report at the end) and Coaching (live score chips + tip + retry; the last attempt is scored and the session is marked "coached") |
| Input/output channel | Text, or voice (STT for answers, TTS for questions) via OpenRouter audio models; chosen per session |
| Turn format | Structured JSON per interviewer turn `{stage, question_id, message, is_final}`, no streaming |
| 5 prompts (R4) | P1 zero-shot · P2 few-shot · P3 CoT plan-first · P4 role-rich · P5 self-critique |
| Prompt eval (R4/H5) | Simulated-candidate LLM + judge harness (CLI); results shown read-only in Settings → Lab |
| **Two-tier evaluation** | **Live (Jev, ~0.4 s, after every answer):** A1 relevance, A3 specificity, A6 depth + a "needs follow-up?" yes/no that routes the interviewer to probe or move on. **Final (LLM judge):** the full rubric A1–A10 with rationale, S1–S6, red flags, recommendations. Aggregation in code (rubric §7). Dashboard shows Jev vs LLM agreement on the same answers |
| Security | (1) limits + validation (OWASP LLM10); (2) regex rules → Jev yes/no injection check with a threshold tuned in the Lab (LLM01), on docs and every answer; (3) documents wrapped in delimiters as data |
| Pages | Interview, Applications, History, Dashboard (score trend, rubric radar, usage + cost, judge agreement), Settings (user + Developer section), Help |
| Extras | M8 interviewer avatar per persona (cached). English only |
| Privacy / repo | Standalone **public** repo `JinhoKim46/TC_AE_Sprint1_Interview_helper` (this folder), own `pyproject.toml` + uv. Gitignored: `docs/applications/` (real CVs), `references/app_design/` (third-party screenshots), `data/`, `.env`, `.worktrees/`. A fake sample application is committed |
| Quality bar | Type hints, pydantic, pytest with mocked LLM, ruff, pydantic-settings + `.env`, logging, retries, comments that explain *why* |

Optional tasks covered: E3 E4 E7 (E8 via the Lab reasoning-effort sweep, `lab/sweep_setting.py`: gpt-5 ignores temperature), M1 M2 M3 M6 M7 M8 M9, H1 H4 H5 → well over the 2 medium + 1 hard needed for the bonus.

## Components I added that weren't in the brainstorm
1. **Prep step** (prompt chaining): JD + CV + cover letter → `InterviewPlan` JSON (requirement map, claim map, probe list). Shared by all prompt variants. This is M2 format #1; `Evaluation` is #2.
2. **Candidate simulator** to compare prompts reproducibly (strong / weak / evasive personas).
3. **LLM call log**: each call stores its role, model, tokens, cost and latency → cost display (M3) and dashboard.
4. **Pricing cache** from OpenRouter `GET /api/v1/models` (refreshed daily).
5. **Session persistence**: every turn is written to the DB right away, so a refresh or crash resumes the interview.
6. **Code-enforced limits**: question count, follow-up cap, turn cap, spend cap per session. When a limit is hit, code forces the closing stage.
7. **Missing cover letter**: the prompt and rubric skip items that depend on the cover letter.
8. **Data deletion**: delete an application together with its sessions, calls and audio.
9. **Failure handling**: retry with backoff, then a friendly error, and state is kept. Invalid JSON → one repair retry. Jev down → skip live scores (the final LLM judge still runs). STT failure → fall back to text input for that answer.

## Architecture
```
project_Interview_App/
  pyproject.toml  .env.example  README.md  .gitignore (data/, docs/applications/)
  app/                         # Streamlit only — no business logic
    main.py                    # st.navigation, page registry
    pages/{interview,applications,history,dashboard,settings,help}.py
  src/interview_app/
    config.py                  # pydantic-settings: provider profiles, role→model map, limits, feature flags
    models.py                  # pydantic: InterviewPlan, InterviewerTurn, LiveScore, Evaluation, GuardResult
    auth.py                    # register (first user only), verify password, TOTP enrol/verify, recovery codes, lockout
    db.py                      # SQLModel: User, Application, Document, Session, Turn, LLMCall, LiveScore, Evaluation, Avatar
    llm/client.py              # chat(), chat_json(schema): OpenAI SDK + base_url, retries, usage → LLMCall
    llm/decide.py              # Jev decisions API (pattern: sprint1/judge/judgebench/openrouter.py:decide)
    llm/pricing.py             # OpenRouter /models cache → cost per call
    llm/image.py               # avatar generation (modalities=["image","text"], base64 decode)
    llm/audio.py               # STT + TTS via OpenRouter audio models
    ingest.py                  # PDF (pypdf) / paste / URL (httpx + trafilatura) → text; validation
    security/{limits,injection}.py   # rules → Jev check → GuardResult(allowed, reason, score)
    prompts/                   # Jinja2: plan.md, interviewer_p1..p5.md, coach.md, candidate_sim.md, judge_*.md
    interview/{persona,plan,engine}.py   # engine: start(), answer(text) → turn, retry(), finish()
    evaluation/{metrics,live_jev,llm_judge,aggregate,report}.py   # rubric items loaded from docs/rubric.json
  lab/compare_prompts.py       # CLI: 5 variants × N sessions × candidate personas → CSV + markdown
  lab/tune_guard.py            # injection threshold sweep on attack/benign examples
  samples/demo_application/    # fake JD, CV, cover letter (committed)
  tests/                       # unit tests, LLM/Jev calls mocked
```
Reuse: `sprint1/judge/judgebench/openrouter.py` (`chat`, `decide`, `Reply`) and `judges.py` (`jev_request`, `jev_parse`, `LLMJudge`) as patterns for the client, Jev and the judge. `sprint1/streamlit_app.py` as a reference for the chat UI.

## Core flows
- **Auth:** first run → register (password + TOTP enrolment by QR code + recovery codes shown once) → afterwards login = password → 6-digit code (or a recovery code) → session in `st.session_state`, expires when idle.
- **Import:** upload/paste/URL → validate → injection scan (warnings shown) → text preview/edit → save the Application.
- **Interview turn:** answer (typed, or audio → STT) → limits + guard → **Jev live scores + follow-up signal (in parallel)** → engine builds messages (system = variant + persona + plan + spotlighted docs + routing hint; then history) → `chat_json` → validate → save Turn + LiveScore → show (TTS in voice mode; score chips + tip in Coaching mode) → repeat until `is_final` or a limit.
- **Finish:** metrics (code) → LLM judge (full rubric) → aggregate (§7 weights, §6 caps, bands) → report → History/Dashboard (including Jev-vs-LLM agreement).
- **Guard outcome:** blocked answer → not sent, "please rephrase", logged. Flagged document → the user must confirm or edit it.

## Execution method
**Autonomous**, like a real team. I only stop to ask about decisions that really are the user's to make (product behaviour, privacy, spend).
Hybrid: the foundation and the interview engine are built **sequentially**. Independent leaf modules (ingest, pricing, aggregate, avatar, audio, dashboard) go to **2–3 parallel subagents**, each in its own worktree, once their interfaces are fixed. No large Workflow.

### Git workflow (every change)
1. `git worktree add .worktrees/<branch> -b <type>/<short-name> origin/main` (types: feat, fix, chore, docs, test). Never commit on `main` directly.
2. Small Conventional-Commit commits inside the worktree, ending with the Co-Authored-By line.
3. Push → `gh pr create --base main` with Summary, Test plan and the 🤖 footer.
4. CI (GitHub Actions: `uv sync`, `ruff check`, `ruff format --check`, `pytest -m "not live"`) must be green. No API keys in CI; real-API tests are marked `@pytest.mark.live` and run locally.
5. `gh pr merge --squash --delete-branch`, then `git worktree remove .worktrees/<branch>`, `git fetch --prune`, and fast-forward local `main`.
6. Before each PR: a self-review of the diff (code-review skill) and a scan for secrets/PII.

### PR sequence (roughly one per row; parallel where marked ∥)
| # | Branch | Content |
|---|---|---|
| 1 | chore/bootstrap | .gitignore (privacy rules first), pyproject, ruff, pytest, CI workflow, `.env.example`, docs + `docs/04-design-spec.md` |
| 2 | feat/core | config, pydantic models, DB (User + user_id everywhere), LLM client + call log |
| 3 | feat/auth-mfa | password + TOTP + recovery codes + lockout + login gate + app shell (`st.navigation`) |
| 4–6 ∥ | feat/pricing, feat/jev-client, feat/ingest | pricing cache · Jev decisions client · PDF/paste ingest + Applications page + sample application |
| 7 | feat/guards | limits + rules + Jev injection check |
| 8 | feat/plan-and-prompts | prep step + P4 prompt + persona derivation |
| 9 | feat/interview-engine | engine + Interview page (text) → **MVP** |
| 10 | feat/live-scoring | Jev live scores + routing + Coaching mode + retry |
| 11 | feat/final-evaluation | LLM judge + aggregate + report + History |
| 12 | feat/settings-dev | Settings (user + Developer), P1/P2/P3/P5, model picker incl. open-weight (H4), cost display |
| 13–14 ∥ | feat/jd-url, feat/avatar | JD from URL · M8 avatar |
| 15 | feat/lab | candidate simulator, `compare_prompts.py`, `tune_guard.py`, results doc |
| 16 | feat/dashboard-help | Dashboard (trend, radar, cost, judge agreement) + Help |
| 17 | feat/voice | STT/TTS behind a flag |
| 18 | docs/readme-final | README, review notes (prompt choice, settings, problems, improvements) |

## Build order (cut line = what must work for the review)
| When | Work |
|---|---|
| Fri 10/2 – Sat 10/3 | Save the spec, scaffold, config, DB (with User), auth + MFA + login gate, LLM client + Jev client + pricing + call log, ingest (PDF/paste), Applications page, sample application, tests |
| Sun 10/4 | Plan step, P4 prompt, interview engine, guards (rules + Jev), Interview page (text) → **end-to-end MVP** |
| Mon 10/5 | Jev live scoring + routing, Coaching mode, LLM judge + aggregation + report, History |
| Tue 10/6 | Settings (Developer section, cost), P1/P2/P3/P5 variants, open-weight models (H4), JD from URL, avatar (M8) |
| Wed 10/7 | Candidate simulator + `compare_prompts.py` + `tune_guard.py` runs + write-up, Dashboard, Help |
| **── cut line: review-complete without voice ──** | |
| Thu 10/8 | Voice (st.audio_input → STT; TTS playback), behind a flag. Then README (run, architecture, prompt/settings choices, known problems, improvements) and a demo rehearsal |
| Fri 10/9 | Review. Mon 10/12 buffer for fixes before the hard deadline |

## Next step after approval
1. PR 1 (bootstrap): add the privacy .gitignore **before** anything else is staged, then commit the docs + `docs/04-design-spec.md` (this plan).
2. Write a task-level implementation plan (writing-plans) into `docs/plans/`, then execute the PR sequence autonomously.

## Verification
- Auth: register → enrol TOTP → log out → login needs password + a valid code; a wrong code 5× locks the account; a recovery code works once; pages can't be opened without logging in.
- `uv run pytest` (auth, engine, guards, aggregation against hand-computed rubric examples, ingest, pricing; LLM/Jev mocked) and `uv run ruff check`.
- Manual end-to-end with `samples/demo_application`: import → realistic interview → report → History/Dashboard show the session, its cost and judge agreement.
- Coaching mode: live chips appear within about 1 s of submitting; a retry replaces the scored attempt.
- Guard: `lab/tune_guard.py` reports the catch rate and false-positive rate; injection text in a CV and in an answer gets blocked or flagged.
- `uv run python lab/compare_prompts.py --sessions 3` produces the 5-variant table; the winner is named in the README.
- The same interview runs with an open-weight model (H4).
- Voice: a recorded answer is transcribed into the transcript and the next question plays as audio; with the flag off, the app works in text mode.

## Known risks
- **Scope:** voice gets one day (Thu); the flag keeps the demo safe if it slips.
- Jev's per-item thresholds need calibration; until then live scores are labelled "indicative".
- Some open-weight models don't support strict JSON schemas → JSON mode + pydantic validation + one repair retry.
- The exact OpenRouter STT/TTS and decisions request shapes get checked at implementation time (openrouter-stt/tts/decisions skills).
