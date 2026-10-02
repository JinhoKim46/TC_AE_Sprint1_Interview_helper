# Interview Helper — Project Report

2 October 2026 · Jinho · [Live version (Claude Docs)](https://claude.ai/code/artifact/cde878a6-a389-40ac-a2d5-710e4ed8578b)

## Executive summary

The project is feature-complete for grading one week ahead of the Friday 9 October review: every mandatory requirement and well over the bonus threshold of optional tasks are built, tested and merged, and so is Phase 2 (History and progress, Coaching mode with live scores, the weak-spot drill, median-of-3 judging and a Docker service). An audit before the review (PRs #30–#38) then fixed interview-state, scoring, security and UI issues, and a UX pass (PRs #40, #41) added a guided Home page, a light and dark theme and clearer interview and report screens.

- **What it is:** a local Streamlit app that rehearses an interview for **one specific job application**. The user uploads a job description and CV (cover letter optional); an LLM interviewer grounded in those documents runs a realistic multi-turn interview; an LLM judge then scores the transcript against a weighted rubric and writes evidence-backed feedback.
- **Status against the grading scheme:** all five mandatory requirements (R1–R5) met; 13 optional tasks delivered (E3, E4, E7, E8, M1, M2, M3, M6, M7, M9, H1, H4, H5) against a bonus threshold of 2 medium and 1 hard.
- **Delivery:** 40 pull requests merged through CI, 421 automated tests (no network); the MFA work was dropped and stays in a closed PR (#4) for reference.
- **Evidence:** live runs on real models show about 25 s to start an interview, about 3 s per interviewer turn, about $0.015 per interview and about $0.10 per report (three judge runs, median). The 15-session prompt comparison plus the setting sweep cost $0.52.
- **Honest caveats:** judge scores vary between runs (the median of three reduces this); the prompt comparison is small (one session per persona), cannot separate the three best prompts and was run on prompts that later PRs changed; question stacking is reduced, not eliminated.

**Recommendation:** freeze features for grading now. Spend the remaining days on review rehearsal and one end-to-end run with real documents, then resume the secondary roadmap after the review.

## Project context and objectives

The project serves two goals at once: pass the Sprint 1 capstone review with full marks, and leave the owner with a tool worth using for real job applications afterwards.

**The course brief** (Turing College AE, Sprint 1, *Build an Interview Practice App*) asks for a single-page app built with Streamlit or Next.js that calls the OpenRouter API, uses at least five system prompts built with different prompting techniques, and has at least one security guard. The focus of the practice is left to the learner. Full marks require at least two medium and one hard optional task. The review itself is a conversation: the learner must explain prompting techniques, model settings, message roles, output types, the app's weaknesses and possible improvements.

**The owner's goal** is interview practice that is specific to an application, not generic question drills. Every question should come from the actual job description and CV, probe the gaps between them, and end in feedback that says what to fix before the real interview. The app must remain useful after submission, so it was built to a "clean, tested, readable" standard rather than as a throwaway demo.

**Success criteria** agreed at the start:

1. The core flow works end to end: upload JD + CV (cover letter optional) → tailored interview → feedback.
2. Every graded requirement is met and can be pointed to in the code.
3. The owner can explain every design choice at the review, with evidence.
4. Personal data never leaves the owner's machine except as model calls, and never reaches the public repository.

**Constraints:** about one week of build time (review Friday 2026-10-09, hard deadline Monday 2026-10-12); a single local user; OpenRouter as the model provider, subject to the account's guardrail; the repository is public.

## Scope and priorities

Scope was set in two passes: a broad design from the owner's brainstorm, then a re-prioritisation on day one to put the grading criteria and the core flow first and move everything else behind them.

| Area | Status | Why |
| --- | --- | --- |
| Application upload (JD + CV required, cover letter and company notes optional; PDF or paste) | Delivered | Core concept of the app |
| Grounded multi-turn interview with personas, difficulty and limits | Delivered | Core concept; H1, E4, E7 |
| Five interviewer prompt variants and a comparison harness | Delivered | Mandatory R4; H5, E8 |
| Security guards (limits, injection detection, spotlighting) | Delivered | Mandatory R5; E3 |
| Rubric-based feedback report with LLM-as-a-judge | Delivered | Core concept; M2, H5 |
| Settings page: model picker, all model settings, cost, developer separation | Delivered | M1, M3, M7, M9, H4 |
| Login with MFA (password + authenticator app) | Dropped (PR #4, closed unmerged) | Not graded; one local user, served on localhost only |
| History, progress dashboard | Delivered after the graded scope (PR #22) | Not graded; valuable for long-term use |
| Live per-answer scoring (Jev) and Coaching mode | Delivered after the graded scope (PR #21) | Not graded; Jev already used for the guard and the lab judge |
| Weak-spot drill, median-of-3 judging, Docker service | Delivered after the graded scope (PRs #23, #24, #26) | Long-term use and score stability |
| UX pass: guided Home with a next step, theme, clearer interview, report and History screens | Delivered after the audit (PRs #40, #41) | A tool the owner keeps using should say what to do next |
| Interviewer avatars (image generation, M8) | Deferred | Bonus already exceeded |
| Voice (speech-to-text, text-to-speech) | Deferred | Highest effort and risk for a demo |
| JD import from URL | Deferred | Fragile (sites block scraping); paste covers it |

Two items in the original brainstorm were changed rather than deferred. **Flask + HTML/CSS** became Streamlit, because the brief requires Streamlit or Next.js and the reviewer checks it. **Supabase** became local SQLite, because the app has one user on one machine and real CVs should stay local.

## System architecture

The app has three layers: a thin Streamlit UI, a Python core that holds all logic and imports no UI code, and shared services. Every model call passes through one logged gateway.

![System architecture: three layers and the offline lab](img/architecture.png)

**How a session flows.** The Applications page turns PDFs or pasted text into clean documents, flags anything that looks like an instruction to an AI, and stores one copy per application. Only one interview runs at a time. Starting one snapshots those documents, makes a plan (for P4), and asks for the opening turn. Each answer passes the length and injection guards before the engine builds the messages; the engine checks whose turn it is, code counts questions and follow-ups and decides the phase, and the model writes the next turn as validated JSON. When the interview ends, code splits the transcript into exchanges and computes metrics, three parallel judge runs score it with cited evidence, code verifies every quote and turns each run's scores into a report using the weights in `rubric.json`, and the median run becomes the report.

**Why this shape.** The core can be tested without a browser, so most of the 421 tests run on plain functions with scripted model replies. The single gateway means every call's tokens, cost and latency are logged in one place, which powers the cost display and keeps provider changes to one setting.

## Technology stack

The stack is deliberately small: one language, one UI library, one database file, and one HTTP gateway to every model, so that each piece can be explained in a sentence at the review.

| Layer | Choice | Why this, not the alternative |
| --- | --- | --- |
| Language and tooling | Python 3.12, uv, ruff, pytest | One language end to end; uv gives a locked, reproducible environment |
| User interface | Streamlit (multi-page, `st.navigation`, pages in `app/views/`) | Required by the brief (or Next.js); fastest path to a working chat UI; `.streamlit/config.toml` binds it to 127.0.0.1 and sets one indigo theme for light and dark mode |
| Core logic | Plain Python package `interview_app`, no UI imports | Testable without a browser; the UI could be replaced later |
| Data models and validation | pydantic, pydantic-settings | Every model response and every setting is validated against a typed schema; settings have bounds, and a misspelt key in a settings group fails at start |
| Storage | SQLite via SQLModel | Single user, local data; moving to Postgres later is a connection-string change |
| Model access | OpenAI Python SDK pointed at OpenRouter | One OpenAI-compatible client reaches any provider; OpenRouter reports the real cost of each call |
| Decision model | Jev (`typesafe/jev-1.13`) via the OpenRouter Decisions API | Returns probabilities instead of text: fast (~0.4 s) and cheap, with no sampling temperature; used where a typed yes/no or score is enough |
| Prompt templates | Jinja2 files in `prompts/` | Prompts are readable documents, versioned and reviewed like code |
| Document ingest | pypdf | Extracts PDF text with decompression and time limits; the user corrects it before saving |
| Local service | Docker + Makefile | `make up` runs the app on localhost with `data/` mounted; pinned base image, all capabilities dropped, no-new-privileges |
| Delivery | GitHub, git worktrees, pull requests, GitHub Actions CI | Every change reviewed and tested (lint, format, unit tests, Docker build) before it reaches `main` |

**Models in use** (all configurable on the Settings page):

| Role | Default model | Reason |
| --- | --- | --- |
| Interviewer and planner | `openai/gpt-5-mini` | The brief's recommended default |
| Final judge | `anthropic/claude-haiku-4.5` (3 runs, median) | A different model family from the interviewer, which avoids self-preference bias; three runs reduce score variance |
| Simulated candidate (lab only) | `google/gemini-2.5-flash` | A third family, so neither side grades its own style |
| Injection guard, live scorer, lab judge | Jev (`typesafe/jev-1.13-20260917`) | Typed probabilities; code sets the threshold |
| Open-weight options (H4) | `google/gemma-4-31b-it`, `minimax/minimax-m2.7` | Passed a live check against the account's guardrail |

The account's OpenRouter guardrail blocks `openai/gpt-5`, DeepSeek and `z-ai/glm-5.2`; each picker entry was confirmed with a real call.

## Key decisions

One principle runs through every decision below: **the model judges, code computes.** Models decide what to ask and how good an answer is; code counts, weighs, enforces limits and makes the final call on thresholds. That split is what makes the app testable and its scores traceable.

| Decision | Alternatives considered | Rationale | Consequence |
| --- | --- | --- | --- |
| Grading criteria and core flow first; extras after the review | Build everything before Friday | The extras are not graded; each one adds explanation burden at the review | Graded scope finished on day one; MFA, voice and dashboard deferred |
| Core package without Streamlit, UI as a thin layer | Logic inside the Streamlit pages | Tests run without a browser; the UI is replaceable | 421 tests, most of them on pure functions |
| One OpenAI-compatible gateway for all chat models | LiteLLM; LangChain | Fewest moving parts; raw API parameters stay visible for the review | Switching provider = a base URL and a key; every call logged with tokens, cost and latency |
| Each of the five prompts = the zero-shot baseline plus exactly one technique | Five independently written prompts | A comparison then isolates what each technique adds | Clean R4 story; only P4 receives the separately generated plan |
| Structured JSON for every interviewer turn, no streaming | Stream plain text | The app needs stage, question id and end-of-interview metadata reliably | 2–5 s spinner per turn instead of streamed words |
| Reasoning fields placed before the message in the JSON | Reasoning after, or no reasoning field | Models write JSON top to bottom, so the model must think or critique before it asks | This ordering is what makes P3 chain-of-thought and P5 self-critique |
| Live status in a trailing system message | Rebuild the whole prompt each turn | The long system prompt stays identical between turns, so the provider can cache it | Cheaper, faster turns |
| Code enforces limits (turns, spend) and the closing rules | Trust the prompt | A prompt can be ignored; code cannot | Interviews always close; the candidate is always invited to ask questions |
| Injection guard = regex rules, then Jev; documents flagged, answers blocked | LLM classifier only | Rules are free and explainable; Jev catches paraphrases in ~0.4 s | Reworded attack blocked at p = 0.99 in a live test; benign "system prompt" answer passed at p = 0.02 |
| Three parallel judge runs per session, median, from a different model family | One run; one call per exchange; the interviewer's own model | One transcript scored 56.6 and 71.5 on two single runs; parallel runs cost no extra time; a different family avoids self-preference bias | About 60 s and $0.10 per report; all three scores are shown |
| Judge must quote the candidate; code verifies the quote | Trust cited turn ids | A real run credited CV facts never said in the interview | Requirement credit and strengths need a verified quote (in order, at least two words); an unverified positive rating scores 0 |
| Local SQLite, single local user, MFA dropped | Supabase; full login now | Data stays on the owner's machine, served on localhost only; login is not graded | `user_id` kept on every owned table (application, interview and history queries filter on it), so accounts can be added without migration |
| Public repository with a privacy-first `.gitignore` | Private repository | Reviewer access without extra setup | Real applications and design screenshots never committed; a fictional sample application ships instead |

## Mapping to the grading scheme

Every mandatory requirement is met, and 13 optional tasks are delivered against a bonus threshold of 2 medium + 1 hard.

**Mandatory requirements**

| ID | Requirement | How it is met | Where |
| --- | --- | --- | --- |
| R1 | Choose the interview-prep focus | Application-specific mock interviews grounded in the JD, CV and optional cover letter, ending in a rubric report | Whole app |
| R2 | Front end with a UI library | Streamlit, five pages in two sidebar sections: Practise (Home, Applications, Interview, History) and Setup (Settings) | `app/` |
| R3 | Allowed OpenRouter model | Interviewer `openai/gpt-5-mini` by default | `config.py` |
| R4 | Five system prompts, different techniques, compared | Zero-shot, few-shot, chain-of-thought, role-rich + plan, self-critique; compared on 15 simulated sessions | `prompts/`, `lab/`, `docs/05-prompt-comparison.md` |
| R5 | At least one security guard | Limits, regex + Jev injection detection on canonical text, spotlighting of untrusted and model-written text | `security/` |

**Optional tasks delivered**

| Level | Task | Delivered as |
| --- | --- | --- |
| Easy | E3 More security constraints | Input validation, LLM-based (Jev) injection check, flagged documents |
| Easy | E4 Difficulty levels | Friendly / standard / tough, changing persona tone and follow-up depth |
| Easy | E7 AI interviewer personas | Six interviewer personas derived from the interview type |
| Easy | E8 Tune a model setting | Reasoning effort low vs medium, measured: medium doubled latency with no quality gain |
| Medium | M1 All model settings in the UI | Model, temperature, max tokens, reasoning effort, judge model on the Settings page |
| Medium | M2 Two or more JSON formats | Interview plan, interviewer turn (three variants), judge evaluation, stored report |
| Medium | M3 Price of the prompt | Real cost per call from OpenRouter, catalog prices from the models endpoint, spend by role and model |
| Medium | M6 Job description field | The JD is the centre of the app, alongside CV, cover letter and company notes |
| Medium | M7 Choose the LLM | Curated model picker with prices and open-weight badges |
| Medium | M9 Guard + developer settings separated | Developer settings behind a toggle on the Settings page, not in the interview flow |
| Hard | H1 Full chatbot | Persistent multi-turn sessions that survive a browser refresh |
| Hard | H4 Open-source LLMs | Gemma 4 31B and MiniMax M2.7 in the picker, tested live |
| Hard | H5 LLM-as-a-judge | Candidate report (Claude Haiku, median of 3 runs) and interviewer-quality judge (Jev) |

Not attempted, by choice: E1, E2, E5, E6 (partly covered by the rubric), M4, M5 (a red-team table exists in the tests but not as a spreadsheet), M8 and H2, H3.

**Evaluation criteria and the evidence for each**

| Criterion | Evidence to show at the review |
| --- | --- |
| Explains prompting techniques | The five-variant table and why each adds exactly one technique |
| Understands model settings | Temperature 0 for the judge; reasoning effort measured (E8); max tokens and truncation |
| Understands system / user / assistant roles | How a turn's messages are assembled, including the trailing status message |
| Understands output types | Structured JSON with schemas, Jev's typed probabilities, free text inside fields |
| Project works as intended | Live demo with the sample application or a real one |
| Correct OpenRouter calls | One gateway, call log with tokens, cost and latency |
| Uses a front-end library | Streamlit multi-page app |
| Justifies technique and parameter choices | Lab results and the reasoning-effort sweep |
| Understands potential problems | Judge variance, small comparison sample on older prompts, partial rubric, latency, what the audit found |
| Suggests improvements | Re-run the lab on current prompts, larger evaluation set, calibrated live scores, code checks for stacking |

## Delivery process and quality

The project was run like a small engineering team: every change went through its own branch, a pull request and automated checks before it reached `main`.

**Workflow.** Each change lives in its own git worktree (`.worktrees/<branch>`), is committed in small Conventional-Commit steps, pushed, and opened as a pull request with a summary and a test plan. GitHub Actions runs lint, format, the unit tests and a Docker build; the PR is squash-merged only when that is green, then the branch and worktree are removed. 40 PRs were merged this way; one (MFA, #4) was closed unmerged and is kept for reference.

**Parallel work.** Independent modules were built by sub-agents in separate worktrees while the interview engine and evaluation, the parts the owner must explain, were built in the main line. Every sub-agent PR was reviewed, rebased and merged by the lead; two real bugs were caught in review (pricing retried the network on every lookup when offline; UI tests leaked a cached database between tests).

**Audit before the review.** After the feature work, independent passes over the core logic, security, UI, infrastructure and documentation looked for what the tests missed, and a second round reviewed the fixes. Each confirmed finding was reproduced, fixed and covered by a regression test: interview-state bugs such as double submits and stuck starts (#30), two scoring rules that inflated the score (#30, #37), config validation and Docker/CI hardening (#32), five security issues including a ReDoS, Unicode bypasses, PDF bombs and second-order injection (#33, #38), markdown/HTML escaping and stale UI state (#31), a simplification pass (#35) and corrections to claims in the docs (#36). The full list is under Risks, limitations and open issues below.

**UX pass.** A heuristic review of every page (hierarchy, onboarding, empty states, feedback during slow steps, error recovery, accessibility) led to PR #40. Home now shows three step cards marked Done, Next or Later (icon and word, never colour alone) and one Next step card whose action is picked in code by the new `journey.py` (`next_step`, `score_summary`). The start form has numbered sections with plain-language help, and the slider range comes from `Limits.min_main_questions` / `max_main_questions`. `st.status` boxes explain the ~30 s start and the ~1 min report and show a clear failed state. The interview screen shows type, difficulty and mode badges and "Question n of N · Stage", live score chips carry an icon per level, and the report opens with a verdict card. History shows the interview count, the latest score with its change and the best score. "Practise this application" preselects an application on the start form. PR #41 renamed `app/pages/` to `app/views/` because Streamlit fell back to its legacy file-list navigation on a deep link right after a server start.

**Testing strategy.**

- **Unit tests** cover the pure logic: progress counting, phase decisions, limit enforcement, rubric aggregation (including a hand-computed example), quote verification, guard rules and prompt rendering. None touch the network; model calls are replaced by scripted fakes.
- **UI tests** run the real Streamlit pages headless against a temporary database: create an application, start an interview, answer, end it and render the report.
- **Live tests** (marked `live`, run locally only) call the real APIs with tiny prompts to confirm costs, JSON output from open-weight models and the Jev guard.
- **Live end-to-end runs** were done before each major merge and are recorded in the PR descriptions.

**Rules of the house** are written in `CLAUDE.md`: the core never imports Streamlit, all model calls go through one gateway and are logged, `rubric.json` is the single source of truth for scoring, untrusted text is always wrapped as data, and the public repository never receives personal data.

## Evidence and results

The app was measured on real models, not only unit-tested, and the measurements changed three design choices.

**Prompt comparison (R4).** Each of the five prompts interviewed a simulated candidate (Gemini 2.5 Flash playing a strong, a weak and an evasive persona from the fictional sample CV), and Jev judged each transcript on the interviewer-quality items of rubric §12.

![Interviewer realism by prompt variant](img/prompt-realism.png)

*Source: `lab/compare_prompts.py`, first run, 2026-10-02 · 5 prompts × 3 personas × 1 session · prompts as of PR #16; the PR #17 re-run covered P2 and P4 only, and later prompt edits (PRs #26, #28, #33) were not re-run, so the figures are indicative (see `docs/05-prompt-comparison.md`).*

Zero-shot scored lowest on realism (3.69 vs 3.96–4.07, one session per persona, so a lead rather than a proven gap); P2, P4 and P5 cannot be separated at this sample size. All five passed the safety gate: no fabrication, coaching, illegal questions or role breaks. P4 stays the default for its structure (guideline + requirement plan), P2 is the cheaper alternative. A second run did not reproduce P4's apparently adaptive follow-ups, so that early claim was withdrawn.

**Live operating figures** (gpt-5-mini interviewer, sample application):

| Measure | Value |
| --- | --- |
| Start an interview (planning call + opening) | about 25 s |
| Interviewer turn | about 3 s |
| Cost of a 5-answer interview | $0.015 |
| Feedback report (Claude Haiku judge, 3 runs, median) | about 60 s, about $0.10 |
| Jev injection check | about 0.4 s per answer |
| Full prompt comparison + setting sweep | $0.52 |

**Issues found by measuring, and fixed:**

1. **Slow start.** The planning call took 36 s at medium reasoning effort; at low it took 21 s for the same plan structure at half the cost. Planner moved to low.
2. **Judge credited the CV, not the interview.** On a real transcript the judge marked requirements as "convincingly demonstrated" that were never discussed. Fix: the judge must quote the candidate, and code checks the quote against the cited turns.
3. **Question stacking.** Every prompt packed several sub-questions into a turn. A sharper shared rule made turns 18–28% shorter (P2 −28%, P4 −18%); stacking still occurs at least once per session.
4. **Reasoning effort (E8).** Medium instead of low doubled turn latency (2.9 s → 6.0 s) and cost about 50% more with no quality gain, so the interviewer runs at low.

## Risks, limitations and open issues

None of the open issues blocks the review; two (judge variance and the small evaluation sample) are the most likely reviewer questions and should be raised proactively.

| Issue | Impact | Mitigation now | Next step |
| --- | --- | --- | --- |
| Small evaluation sample (1 session per persona, 1 application) | P2 / P4 / P5 cannot be ranked | Results doc states the limitation; conclusions limited to what the data supports | At least 3 sessions per persona, more applications, a few human-rated transcripts |
| Lab numbers predate later prompt changes (PRs #26, #28, #33) | The comparison describes slightly older prompts | `docs/05` names the code version of every run and calls the numbers indicative | Re-run the lab on the current prompts |
| Live coaching scores are not calibrated against the final judge | A chip can disagree with the report | Labelled as indicative; the report is the reference | Compare live and final scores on the same answers |
| Judge score variance: the same transcript scored 56.6 and 71.5 on two single runs | Lower now: median of 3 runs | All three scores and their spread are shown; a wide spread is flagged | More runs or a calibrated rubric if the spread stays high |
| Stricter quote checks can under-credit | A paraphrased quote earns 0 for that requirement | The judge is told to quote exactly and may join parts with `...` or `;` (PR #37) | Watch for good answers scored "not demonstrated" in real reports |
| Question stacking still occurs; the follow-up cap is an instruction, not a code check | Less realistic interviews; one lab session asked 10 follow-ups | Shared rule tightened; turns 18–28% shorter | Measure stacking per turn; check the cap in code |
| Partial rubric: red-flag checks (N-items) and logistics (S5) not judged | Overall score omits some penalties | Missing weight redistributed transparently | Add N-items as Jev yes/no checks |
| Latency: about 25 s to start, about a minute for a report | Waiting at two moments | Spinners state the expected wait | Stream the report; cache plans per application |
| DB file permissions can't be enforced on a Docker Desktop bind mount | `data/app.db` may stay readable by other local users | The app logs a warning and keeps running (PR #38); `docs/06-docker.md` explains it | Run `chmod 600 data/app.db` on the host once |
| Cyrillic and other homoglyphs are not canonicalised | A look-alike spelling can slip past the regex rules | Jev still checks every answer no rule caught; documents stay wrapped as data | A confusables table, if such attacks show up |
| Single local user, no login | Anyone who can reach the port can use the app | Bound to 127.0.0.1, locally and through Docker | Add a login only if the app is ever hosted for others |
| Old CV-derived examples remain in git history of the public repo | Minor privacy exposure | Removed from all current files | Owner decision: rewrite history (force-push) or accept |
| `openai/gpt-5` blocked by the account guardrail | The brief's high-capability option unavailable | gpt-5-mini is the recommended default | Optional: allow it in OpenRouter settings |

**Resolved by the audit (PRs #30–#38) and the navigation fix (PR #41)**, each with a regression test:

| Issue | Fixed in | What changed |
| --- | --- | --- |
| A crashed start stayed "preparing" and blocked the page; two interviews could run at once; a double submit or double Continue could add two turns in a row | #30, #37 | Any start failure marks the session failed; a "preparing" session older than 15 minutes is marked failed; one interview at a time; `answer` and `respond` check whose turn it is |
| Anthropic and Gemini rejected the opening request; the last main question could never get a follow-up | #30 | A fixed user cue on the opening request; one follow-up allowed after the last main question |
| Scoring was more generous than the evidence | #30, #37 | An unverified positive rating is "not demonstrated" (0 points); quotes match in order, at least two words, parts joined with `...` or `;` across turns; RF5 needs an evidenced S1 and S4 a candidate-questions exchange; length flags use the main answer; live levels round half up |
| LLM client and judge edge cases | #30, #32 | Empty replies and cut-off replies fail clearly; `judge_max_tokens` (16000); one judge run when over budget; call records flushed in `finally` |
| Config typos ignored; local runs on every interface; Docker and CI not hardened | #32 | Bounds and `extra=forbid`; 127.0.0.1, 5 MB uploads, telemetry off; pinned image, `cap_drop: [ALL]`, no-new-privileges; `docker-build` CI job |
| ReDoS, Unicode bypasses, unbounded guard input, PDF bombs, second-order injection | #33 | Linear-time rules; NFKC canonical text; `max_document_chunks` (20); `pdf_max_stream_bytes` and `pdf_extract_timeout_s`; plan, requirements and interviewer turns wrapped as data |
| Deleted text stayed in the DB file; the file was readable by others | #33, #38 | `secure_delete` on; mode 600, best effort where the mount refuses `chmod` |
| Raw HTML in the report; markdown injection from model and document text; stale or duplicate UI state | #31, #37 | No `unsafe_allow_html`; `safe_md` everywhere; delete warnings and locks; single-click guards; blocked answer returned for editing; cached clients |
| Duplicate decoding code and an import cycle | #35 | `_load_active`, `session_documents`, `session_plan`; no behaviour change |
| A failed lab run blocked every later run; overstated claims in the docs | #36, #37 | Failed runs end their session; superseded turns filtered; I7 wording; claims aligned with the data |
| A deep link right after a server start showed the raw page list instead of the sidebar sections (found during the UX pass) | #41 | `app/pages/` renamed to `app/views/`, so Streamlit's legacy auto-navigation never kicks in |

## Review preparation

The review is graded on explanation as much as on the build; these are the questions to expect and the one-line answer plus the evidence to show for each.

| Likely question | Answer in one line | Show |
| --- | --- | --- |
| Why this interview focus? | Generic question drills don't prepare you for *this* job; grounding in the JD and CV makes the interviewer ask what this role's interviewers would ask | Sample application → interview opening that quotes the CV |
| What prompting techniques did you use? | Five variants, each the zero-shot baseline plus one technique: few-shot, chain-of-thought, role-rich with a chained plan, self-critique | `prompts/` folder; the variant table |
| Which worked best, and how do you know? | Every technique beat zero-shot; the top three are within noise; P4 is the default for its structure | The realism chart; `docs/05-prompt-comparison.md` |
| What do temperature, max tokens and reasoning effort do? | Randomness; output cap (too low truncates the JSON); thinking before answering, traded against latency and cost | Judge at temperature 0; the E8 sweep (2.9 s → 6.0 s, no gain) |
| System vs user vs assistant? | System = instructions and wrapped documents; user = the candidate's wrapped answer; assistant = earlier interviewer turns; a trailing system message carries live status | `interview/prompting.py` docstring |
| What output types do you use? | Structured JSON validated against schemas, Jev's typed probabilities, free text inside JSON fields | `interview/schemas.py`, `evaluation/schemas.py` |
| How is it secured? | Length/turn/spend limits; regex then Jev injection detection on canonical text; spotlighting so documents, answers and model-written text are data, never instructions; escaped UI output; PDF bounds; localhost binding | Paste "ignore all previous instructions" as an answer, live; the audit fixes |
| What are the weaknesses? | Judge variance, small evaluation sample run on older prompts, stacking not fully solved, partial rubric, start-up latency | Risks table |
| What would you improve? | Re-run the lab on current prompts, larger evaluation set, calibrated live scores, code checks for stacking and the follow-up cap | Next steps |

**Demo script (about 6 minutes):**

1. Applications → Load sample application; open the JD and CV tabs.
2. Interview → Hiring manager, standard difficulty, 4 main questions → Start.
3. Give one strong answer, one vague answer (watch the ownership or evidence probe), and paste an injection attempt (watch it blocked).
4. End the interview → Get my feedback report; point at a verified quote and the requirements table.
5. Settings → toggle Developer settings; show the model picker with prices and the open-weight badge; show spend by role.

## Next steps

The next step is not more features: it is for the owner to use the app end to end with one real application and rehearse the review, while two small decisions are closed.

**Decisions needed from the owner (this week)**

- [ ] Rewrite git history to remove the old CV-derived examples from the public repo, or accept them as is
- [ ] Allow `openai/gpt-5` in the OpenRouter guardrail (optional)

**Before the review (Saturday 3 – Thursday 8 October)**

- [ ] `make rebuild` after the audit fixes and open the database inside the container (the PR #38 check); on Docker Desktop, run `chmod 600 data/app.db` on the host once
- [ ] Owner runs one full interview, report and weak-spot drill with a real application and a real CV PDF (documents stay local) and notes anything confusing
- [ ] Try Coaching mode once (an answer, a retry, continue)
- [ ] Look at light and dark mode, and at the Home next-step card with your real data
- [ ] Fix only what those runs reveal; feature freeze otherwise
- [ ] Rehearse the demo script and the question table twice; read `README.md` and `docs/05-prompt-comparison.md` once
- [ ] Submit the repository link and schedule the review

**Review: Friday 9 October** (hard deadline Monday 12 October as buffer)

**After the review, in order of value for long-term use**

1. Re-run the prompt lab on the current prompts (the published numbers predate PRs #26, #28 and #33)
2. A larger evaluation set to calibrate the judge and separate P2, P4 and P5
3. Calibrate the live Jev scores against the final judge
4. The rubric's red-flag checks (N-items) as Jev yes/no questions
5. Code checks on each interviewer turn for the follow-up cap and question stacking
6. Voice: speech-to-text answers and spoken questions
7. DOCX upload and JD import from a URL; interviewer avatars, if still wanted
