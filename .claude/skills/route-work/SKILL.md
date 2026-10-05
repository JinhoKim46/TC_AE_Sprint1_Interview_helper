---
name: route-work
description: Size a piece of Interview Helper work and route it through the right planning skills — none, grill-with-docs, + to-spec, + to-tickets, or wayfinder first — then have general-purpose agents build it, in parallel wherever the ticket graph allows. Use this whenever the user asks to build, add, change, redesign, migrate or plan something in this repository and has not named a planning skill themselves — even when the request sounds small, because deciding that it is small is this skill's job. Also use it at a phase boundary when the work turns out bigger or smaller than first judged. Not for pure questions, code review, deploys or reading data.
---

# Route work

Pick the lightest route that still leaves no decision silently assumed, say which one in one line, and go. The user should never have to name `/grill-with-docs`, `/to-spec`, `/to-tickets` or `/wayfinder` — choosing between them is this skill's job. If the user does name one, follow theirs.

## How to run a routed skill

`grill-with-docs`, `to-spec`, `to-tickets` and `wayfinder` set `disable-model-invocation`, so the Skill tool refuses them. Run one by reading `.claude/skills/<name>/SKILL.md` and following it exactly, as if it had been invoked. (`grilling` is model-invocable; `grill-with-docs` tells you to call it through the Skill tool, and that works.) This repo has no external issue tracker: specs and tickets are local Markdown files under `docs/specs/<date>-<slug>/` (`spec.md`, `tickets/NN-<name>.md`). Read `CLAUDE.md` and `docs/04-design-spec.md` before the first routed skill runs.

## Size it

Look before judging: an `Explore` sub-agent (or a quick grep) to see which modules, pages and CLAUDE.md architecture rules the request touches. Then take the **first** row that fits.

| Size | Signals | Route |
|---|---|---|
| **Trivial** | The request already decides everything: a typo, UI text the user dictated, one spacing fix, a bug whose cause and fix are obvious. One area, no architecture rule touched. | No planning skill. Build it. |
| **Small** | Fits one session. A few open decisions — behaviour, wording, defaults — but no schema, model-call, prompt, security-guard, rubric or cost change. | `grill-with-docs` → build. The decisions go in the PR body. |
| **Medium** | Still one session's build, but it touches the DB schema, a model call or prompt, the security guards, the rubric, cost/limits, or spans several pages. A reviewer will need the decisions written down. | `grill-with-docs` → `to-spec` → build. |
| **Large** | Will not fit one context window: several vertical slices (e.g. core + prompts + several pages + a new external API), or pieces that can land independently. | `grill-with-docs` → `to-spec` → `to-tickets` → build the ticket graph (see **Large**). |
| **Fog** | The destination itself is unclear, or the decisions depend on each other too deeply to settle in one sitting — a new subsystem, a roadmap item, a migration whose shape nobody knows yet. | `wayfinder` first. When the map clears it hands off to `to-spec` → `to-tickets` → build. |

When two rows seem to fit, take the larger one — an unneeded spec costs minutes; a silently assumed rule (a prompt-injection path, a cost limit) costs a broken review.

## Announce, then go

Open with one line and do not wait for approval:

> Size: **Medium** — grill-with-docs → to-spec → build. Say so if you want a different route.

Then start the first step. Every routed skill already has its own human gate (grilling waits for a confirmed shared understanding, `to-spec` checks its seams, `to-tickets` has the breakdown approved, `wayfinder` resolves one ticket per session), so asking "shall I start?" first is a wasted round.

## Re-route at every phase boundary

The first judgement is a guess. After each phase, look again:

- Grilling surfaced schema, model-call, prompt, guard or cost decisions → step up to **Medium**.
- The spec grew several independently landable parts, or more than one context window of work → step up to **Large** and run `to-tickets`.
- Grilling cannot reach an empty frontier because each answer opens more unknowns than it closes → stop and go **Fog** (`wayfinder`), carrying what is settled into the map's Decisions so far.
- `wayfinder`'s charting finds no fog → it tells you to stop; step down to **Medium** or **Large** and say so.
- Grilling settles in one round and nothing needs a record → finish as **Small**.

Say the change in one line ("Stepping up to **Large** — the TTS service and the length modes can land separately, so to-tickets will split them.") and continue.

Keep grilling → spec → tickets in **one unbroken context**: each builds on the thinking of the one before, so do not compact or hand off in between.

## Build — general-purpose agents

Never `/implement`, `/implement-spec`, `/tdd`, `/code-review` or any `superpowers:*` skill as the build driver: the build is done by the session itself, by the `Agent` tool with `subagent_type: "general-purpose"`, or by a `Workflow` (see **Large**). Design work may additionally load design skills (`frontend-design`, `design-review`, `web-design-guidelines`) inside the agent.

- **Trivial / Small / Medium** — build in this session, or hand the whole spec to one general-purpose agent.
- **Large** — one branch and PR per ticket (or per ticket group that must land together), every ticket in a fresh context. See the next section.

The dispatching session owns verification, not the agent: `uv run ruff check && uv run ruff format --check`, `uv run pytest -m "not live"` (read the pass count), `git diff --check`, a run of the app for any UI change (CLAUDE.md: a feature is done when it was exercised once in the running app), and the PR workflow in CLAUDE.md (worktree per branch, CI green, squash merge, cleanup).

## Large: run the ticket graph, in parallel wherever it allows

**Build the graph first.** After `to-tickets`, write the tickets' `Blocked by` edges as a dependency graph (a small Mermaid `graph LR` in `docs/specs/<slug>/tickets/README.md`). The **frontier** is every ticket whose blockers are all `done`. Re-compute it every time a ticket finishes.

**Never wait on a ticket you don't depend on.** Start every frontier ticket at once, each in its own fresh context and its own git worktree cut from `origin/main` (or from its blocker's merged tip). When a ticket finishes and merges, immediately start any ticket it unblocked — do not wait for the rest of the current wave. The only reason to run two tickets one after the other is a real dependency: a `Blocked by` edge, or two tickets that would rewrite the same function, prompt template or page block (those are dependent even if neither lists the other; add the edge).

**Pick the execution mode per group of tickets:**

- **Independent tickets** (no information needs to flow between them while they run) → one background general-purpose `Agent` per ticket, launched in a single message so they run concurrently. Each works in its own worktree, opens its own PR, and does not merge; the dispatcher reviews, rebases (regenerating generated files such as `reports/code_map.json` instead of hand-merging them), waits for CI and merges.
- **Tickets whose agents must communicate** (a shared interface decided during the build, a producer/consumer pair, an implement → review → fix loop, fan-out results that must be merged or cross-checked) → run them as a `Workflow` (ultracode mode): load the `workflow-authoring` skill, script the ticket graph with `pipeline`/`parallel` so each stage starts as soon as its inputs exist, and pass results between agents through the script, not through the user.

**Dispatcher loop:** start the frontier → on each completion notification, verify and merge that ticket, mark it `done`, recompute the frontier, start what became available → repeat until the graph is empty → run the full suite once on `main`, regenerate the reports if behaviour changed, and report.

Never build two tickets in one context — one ticket, one fresh agent, workflow stage or session.
