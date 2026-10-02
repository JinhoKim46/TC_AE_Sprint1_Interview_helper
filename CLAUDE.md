# CLAUDE.md — Interview Helper

Rules for anyone (human or agent) changing this repo. The design is in `docs/04-design-spec.md`; read it
before starting a feature. The course brief and grading criteria are in `docs/00-project-objective.md`.

## What this is

A local, single-user Streamlit app for mock job interviews. Upload a JD + CV (cover letter optional) →
an LLM interviewer runs a grounded multi-turn interview → Jev (decision model) scores each answer live →
an LLM judge writes the final rubric report. It is a Sprint 1 capstone (review Fri 2026-10-09) **and** a
tool the owner keeps using afterwards.

## Commands

```bash
uv sync                                   # install
uv run streamlit run app/main.py          # run the app
uv run pytest -m "not live"               # unit tests (no network) — what CI runs
uv run pytest -m live                     # real-API tests, needs .env
uv run ruff check && uv run ruff format --check
uv add <pkg>    /    uv add --dev <pkg>   # never pip install
```

## Git workflow (mandatory)

1. Never commit on `main`. Every change: `git worktree add .worktrees/<type>-<name> -b <type>/<name> origin/main`
   (types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`).
2. Conventional Commit messages; small, focused commits; end each with the `Co-Authored-By:` line.
3. Push, then `gh pr create --base main` with **Summary** and **Test plan** sections.
4. Merge only when CI is green: `gh pr merge <n> --squash`. Then `git push origin --delete <branch>`,
   `git worktree remove .worktrees/<dir>`, `git branch -D <branch>`, and `git pull --ff-only` on `main`.
   (`gh pr merge --delete-branch` fails here because `main` is checked out in the main folder.)
5. Before opening a PR: review your own diff, and scan it for secrets and personal data.

## Privacy (the repo is PUBLIC)

- Never commit: `docs/applications/` (real CVs, cover letters), `references/app_design/` (third-party
  screenshots), `data/` (DB, uploads, audio, avatars), `.env`. They are gitignored; never force-add them.
- Tests and the committed sample (`samples/`) use **fictional** people and companies only.
- Never log API keys, passwords, TOTP secrets or full document text.

## Architecture rules

- `src/interview_app/` is the core and must **not import Streamlit**. `app/` is a thin UI that calls the core.
  This keeps the core testable and lets the UI be replaced later.
- All settings live in `config.py` (`Settings`, read from `.env`). No hard-coded model ids, limits or paths
  elsewhere.
- All model calls go through `llm/client.py` (chat) or `llm/decide.py` (Jev). Every call is recorded as an
  `LLMCall` row (role, model, tokens, cost, latency). No direct `openai`/`httpx` calls to model APIs from
  other modules.
- Every owned DB row has a `user_id`. Add a table in the PR that first needs it.
- `docs/rubric.json` is the single source of truth for rubric items and weights. Don't copy them into code
  or prompts.
- **The model judges, code computes.** Counting, timing, weighting, thresholds and limits are done in code.
- Untrusted text (JD, CV, cover letter, notes, answers) is always wrapped as data in prompts and passes the
  guard (`security/`) first. It is never concatenated into instructions.
- Structured outputs are pydantic models; validate every model response and retry once with a repair
  message before failing.

## Code style

- Python 3.12, type hints everywhere, ruff (line length 110).
- Readable over clever: plain functions and small classes, flat modules, no frameworks the task doesn't need.
  The owner is learning, so comments explain **why** (a design reason or an API quirk), not what.
- Fail clearly: friendly messages in the UI, and full errors in logs (no secrets).

## Testing

- TDD for core logic: write the failing test, then the code.
- Unit tests never touch the network. Mock the LLM/Jev layer; use an in-memory SQLite engine.
- Tests that call real APIs are marked `@pytest.mark.live` and stay cheap (tiny prompts, cheapest models).
- A feature is done when its tests pass, ruff is clean, and it was exercised once in the running app.

## Models and API facts (checked 2026-10-02)

- OpenRouter chat: `https://openrouter.ai/api/v1` (OpenAI-compatible). The response `usage.cost` holds the
  real USD cost; `GET /api/v1/models` gives the per-token prices (used to estimate cost).
- Jev decisions: `POST https://openrouter.ai/api/alpha/decisions`, model `typesafe/jev-1.13-20260917`.
  Pin exact builds, not `-latest` aliases. Question types: `noul` (yes/no probability), `score`, `choice`.
- Defaults: interviewer `openai/gpt-5-mini` (course requirement), judge `anthropic/claude-haiku-4.5`,
  candidate simulator `google/gemini-2.5-flash`, open-weight option `google/gemma-4-31b-it`.
- This account's OpenRouter guardrail blocks some providers (e.g. DeepSeek). Check a model with a tiny call
  before making it a default.

## Course requirements to keep visible

R4 needs 5 interviewer system prompts using different techniques (zero-shot, few-shot, CoT plan-first,
role-rich, self-critique), compared with the `lab/` harness. R5 needs at least one security guard. At the
review the owner must explain the prompting techniques, model settings, message roles, output types, the
app's weaknesses and possible improvements, so keep the README and `docs/` current when behaviour changes.
