# Interview Helper

A mock-interview practice app (Turing College AE, Sprint 1 capstone). Upload a job description and CV
(cover letter optional), run a realistic interview with an LLM interviewer grounded in those documents, get
live per-answer scores from a fast decision model (Jev), and receive a full rubric-based report from an LLM judge.

> Status: under active development. See [`docs/04-design-spec.md`](docs/04-design-spec.md) for the design.

## Quick start

```bash
uv sync
cp .env.example .env   # add your OPENROUTER_API_KEY and APP_SECRET_KEY
uv run streamlit run app/main.py
```

## Development

```bash
uv run ruff check && uv run ruff format --check
uv run pytest -m "not live"   # unit tests (no API calls)
uv run pytest -m live         # real-API tests (needs .env)
```

Every change goes through a branch + PR to `main`; CI runs lint and tests.

## Docs

| File | What it is |
|---|---|
| [`docs/00-project-objective.md`](docs/00-project-objective.md) | The course brief and my understanding of every requirement |
| [`docs/04-design-spec.md`](docs/04-design-spec.md) | The approved design |
| [`docs/05-prompt-comparison.md`](docs/05-prompt-comparison.md) | The five interviewer prompts compared with the `lab/` harness (R4/H5) and the reasoning-effort sweep (E8); winner: P4 |
| [`docs/README.md`](docs/README.md) | Guide to the interviewer / evaluator reference docs |
