# Build plan (archived 2026-10-07)

The original execution plan from the approved design of 2026-10-02, kept for reference. It is finished and no longer maintained: the current design is in the [design spec](../04-design-spec.md), the decisions since are in the [decision log](../decision-log.md) and the [ADRs](../adr/README.md), and the git workflow in force is the one in `CLAUDE.md`.

## Execution method
**Autonomous**, like a real team. I only stop to ask about decisions that really are the user's to make (product behaviour, privacy, spend). Hybrid: the foundation and the interview engine are built **sequentially**. Independent leaf modules (ingest, pricing, aggregate, avatar, audio, dashboard) go to **2–3 parallel subagents**, each in its own worktree, once their interfaces are fixed. No large Workflow.

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
| 3 | feat/auth-mfa (dropped) | password + TOTP + recovery codes + lockout + login gate + app shell (`st.navigation`) |
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
| 17 | feat/voice | TTS for the interviewer's questions (Voice channel; speech-to-text was dropped on 2026-10-03) |
| 18 | docs/readme-final | README, review notes (prompt choice, settings, problems, improvements) |

## Build order (cut line = what must work for the review)
| When | Work |
|---|---|
| Fri 10/2 – Sat 10/3 | Save the spec, scaffold, config, DB (with User), auth + MFA + login gate (dropped), LLM client + Jev client + pricing + call log, ingest (PDF/paste), Applications page, sample application, tests |
| Sun 10/4 | Plan step, P4 prompt, interview engine, guards (rules + Jev), Interview page (text) → **end-to-end MVP** |
| Mon 10/5 | Jev live scoring + routing, Coaching mode, LLM judge + aggregation + report, History |
| Tue 10/6 | Settings (Developer section, cost), P1/P2/P3/P5 variants, open-weight models (H4), JD from URL, avatar (M8) |
| Wed 10/7 | Candidate simulator + `compare_prompts.py` + `tune_guard.py` runs + write-up, Dashboard, Help |
| **── cut line: review-complete without voice ──** | |
| Thu 10/8 | Voice (TTS playback of the interviewer's questions). Then README (run, architecture, prompt/settings choices, known problems, improvements) and a demo rehearsal |
| Fri 10/9 | Review. Mon 10/12 buffer for fixes before the hard deadline |

## Next step after approval
1. PR 1 (bootstrap): add the privacy .gitignore **before** anything else is staged, then commit the docs + `docs/04-design-spec.md` (this plan).
2. Write a task-level implementation plan (writing-plans) into `docs/plans/`, then execute the PR sequence autonomously.

## Verification
- Auth (dropped, not built): register → enrol TOTP → log out → login needs password + a valid code; a wrong code 5× locks the account; a recovery code works once; pages can't be opened without logging in.
- `uv run pytest` (auth, engine, guards, aggregation against hand-computed rubric examples, ingest, pricing; LLM/Jev mocked) and `uv run ruff check`.
- Manual end-to-end with `samples/demo_application`: import → realistic interview → report → History/Dashboard show the session, its cost and judge agreement.
- Coaching mode: live chips appear within about 1 s of submitting; a retry replaces the scored attempt.
- Guard: `lab/tune_guard.py` reports the catch rate and false-positive rate; injection text in a CV and in an answer gets blocked or flagged.
- `uv run python lab/compare_prompts.py --sessions 3` produces the 5-variant table; the winner is named in the README.
- The same interview runs with an open-weight model (H4).
- Voice: each interviewer question plays as audio with its text behind Show text; a TTS failure shows the text; Text sessions work as before.
