# Code-flow reports compared: the existing report vs the code-flow-report skill

Written 2026-10-03 · source at `dc9879e` (main) · the skill report was built without opening the existing `reports/`, then compared · §1.3 re-measured with skill v0.5.0.

| | Existing report (`reports/code-flow-report.html`) | Skill report (`reports/code-flow-skill/code-flow-report.html`) |
|---|---|---|
| How it is made | Repo-specific tooling: `build_code_map.py` (1,633 lines), `build_code_flow_html.py` (498), a template (1,193), a hand-written narrative (831). Refined over PRs #27–#42 | The generic skill, v0.5.0. Zero repo-specific code: one config line (leave `reports/` out of the scan) plus a narrative TOML |
| Effort | Several days, many PRs | One session. Seven writer agents (2 journeys, 1 boundaries, 1 data, 3 module notes), 3–7 minutes each |
| Language · reader | English, no stated reader | English (Korean switch on the page), written for someone learning the code |

## 1. What each one counts — the scopes are not the same

Both maps were diffed item by item (`reports/code_map.json` against `docs/code-flow/code_map.json`).

### 1.1 Where they agree

| Item | Existing | Skill | Measured agreement |
|---|---|---|---|
| Functions and methods | 253 (function 204, nested 8, method 34, property 7) | 253 (function 204, nested 8, method 41 — properties are methods) | **identical set**, 0 differences either way |
| Classes | 103 | 103 | identical |
| Call + construct edges (unique caller → callee) | 587 | 584 | **575 shared**; 12 only in the existing map, 9 only in the skill's |
| Table writers / deleters | per table | per table | **identical** for all 8 tables |

So the core call graph is the same picture. The headline numbers differ because of what each tool puts around it.

### 1.2 Where the scopes differ

| Item | Existing counts | Skill counts | Effect |
|---|---|---|---|
| **"Resolved" rate** | 94.6% = internal resolved ÷ (internal resolved + calls that *look internal* but were not found): 742 ÷ 784. Library and builtin calls are outside the denominator | 93.0% = everything with a known target ÷ **all** 2,187 call sites (library, builtin and unknown method calls included). Graph coverage 93.5% excludes builtins and value-method-looking calls | Not comparable. The existing "unresolved" (42) is narrow; the skill's (154) includes any `x.get()` / `x.strip()` whose receiver type is unknown |
| Call sites in total | 2,058 | 2,187 | The skill also counts calls in class bodies (pydantic field defaults: `Settings → Features`, 7 edges) |
| **Top-level page code** | 12 `<module>` pseudo-symbols (`app.views.interview:<module>` …) — page scripts are graph nodes | `<module>` is an edge source only, not a symbol | The skill cannot start a journey or a graph node at a page's top-level code (one journey had to name the module instead) |
| **Injected callables** | `deps.make_llm(...)` is a call to the field `EngineDeps.make_llm`, and a "binds" edge links the field to the function assigned at construction (`ui_common:engine_deps.make_llm`, `lab.compare:make_lab.make_llm`) | not followed (6 of the 12 existing-only edges) | The skill's graph stops at the `EngineDeps` field on the exact path every journey takes to build its LLM client |
| Script-folder imports | `import ui_common` in a Streamlit page resolves to `app/ui_common.py` (Streamlit puts the script folder on `sys.path`) | the import resolves; the 4 calls through `ui_common.x()` do not (5 existing-only edges) | Minor |
| **Reference edges** | 27 — a function passed as a value (callbacks) | 241 — any name reference to an internal symbol, type annotations included | The skill's "ref" mixes "passed as a callback" with "mentioned as a type"; the graph is noisier |
| **Table readers** | 32 reader functions: `select(T)` anywhere, `session.get`, joins; a function that reads and then writes counts as both | 24: a read needs an ORM session call in the same function, and a table the function writes is not also listed as read | The skill misses read-then-write functions (`users:ensure_local_user` reads `user` before inserting it) |
| **Model calls** | 9 call sites to the repo's own gateways (`LLMClient.chat_json` / `chat`, `DecisionClient.decide`), 7 roles, each with the `role` label, the `Settings.models.<x>` field, the schema, message builders, and Jev question types | 1: the SDK call inside the gateway (`openai.OpenAI().chat.completions.create` in `LLMClient.chat`) | The skill's LLM profile sees the *provider* boundary, not the *roles*. The 8 model cards had to be written by hand |
| Prompt templates | 12 templates, `{% include %}` tree, variables used vs passed (StrictUndefined) | 4 "Jinja" external sites | No template catalogue |
| Config | 6 settings classes, their fields, fields nothing reads | nothing | No "unread setting" check; config locations are written by hand on cards |
| Tests | scanned for callers only: functions **only tests** call, functions **nothing** calls | tests are excluded entirely | The skill cannot say "only tests call this" |
| Findings | 15 curated, each with a Python check that drops it once fixed (10 already dropped) + 15 "fixed since" with PR numbers + 6 generated templates | hand-written findings; only `check = "no_callers"` re-checks itself; 2 generated (import cycle, coverage) | The existing page reports *current state*; the skill's findings go stale unless rewritten |

### 1.3 After closing the gap (skill v0.5.0, same source)

Improvements 1–5 and 10 below were built into the skill and the report regenerated. Same measures, same commit:

| Measure | Existing report | Skill, first run | Skill v0.5.0 |
|---|---|---|---|
| Model call sites (gateway calls with role, model, schema, prompt builder) | 9 sites, 7 roles | 1 (the SDK call only) | **9 sites, 7 roles** + the 2 gateways — same set |
| Injected callables ("binds") | 3 | 0 | **3** — same set |
| Call + construct edges shared with the existing map | — | 575 (12 existing-only) | **580** (7 existing-only: 6 are the existing map's edges *to a field*, which the skill records as edges to the bound function; 1 missed: `coaching_choice → respond`) |
| Table readers / writers / deleters | 32 / 12 / 3 | 24 / 12 / 3 | **33 / 12 / 3** — every existing reader found, plus one |
| Functions only tests call | 1 (`PriceCatalog.models`) | — (tests not read) | **1** — same |
| Functions nothing calls | 0 | 0 | 0 |
| Findings that re-check themselves | 15 curated (Python checks) | 0 of 6 | 2 of 6 hand-written + all generated; a fixed one moves to a "Fixed" list |
| Resolved (all call sites) | — | 93.0% | **94.2%** (graph coverage 95.1%) |

The skill now drafts the existing report's agent table by itself (one card per role, prefilled with the schema, the prompt builder and the model setting) — with no repo-specific code.

## 2. How to improve the skill from those differences

Done in v0.5.0: **1, 2, 3, 4, 5, 10** (results in §1.3). Still open: 6, 7, 8, 9, 11, 12.

Ordered by value for any Python repo, not only this one. "Core" changes apply everywhere; "profile" changes switch on by import, like the existing `llm` / `jobs` / `ui` profiles.

| # | Improvement | Kind | What it fixes here | Why it generalises |
|---|---|---|---|---|
| 1 | **Follow model-call gateways.** Any internal function that (transitively) wraps an SDK call becomes a gateway; record every call site *to* it with its literal keyword arguments (`role=`, `model=`, the schema/`response_model`, the messages builder) | profile `llm` | 1 → 9 model call sites; the 8 model cards draft themselves with role, model field and schema | Nearly every LLM app wraps the SDK in its own client; the SDK call alone says "OpenAI" and nothing about who asks what |
| 2 | **Injected callables.** A dataclass / pydantic / `__init__` field typed `Callable[...]` gets "binds" edges to the functions passed for it at construction; a call through the field resolves to those | core | the 6 `deps.make_llm` / `make_decider` edges; journeys reach the client factory | Dependency injection through a deps object is the standard testable-core pattern |
| 3 | **Reads and writes both count.** Stop dropping a table from `read` when the same function writes it; count `select(T)` built in one function and executed in another as that function's read | core (ORM) | readers 24 → ~32 | Read-then-write (upsert, "create if missing") is the most common ORM shape |
| 4 | **Callers from tests, without scanning tests as code.** A second, cheap pass over `tests/` records only who calls what; "only tests call this" and "nothing calls this" become generated findings that re-check themselves | core | `PriceCatalog.models` (test-only) appears; dead-code findings stop needing a person | Every repo has tests; excluding them hides exactly this signal |
| 5 | **Self-retiring findings.** More `check` kinds beside `no_callers`: `symbol_missing` (fixed when a symbol is gone), `text_in` (fixed when a pattern leaves a function's source), `calls` / `not_calls`; a fixed finding moves to a "Fixed" list instead of failing the build | narrative | the existing page's best habit — 10 of its 15 findings retired themselves | Findings are the part of a report that goes stale fastest |
| 6 | **Top-level code as a symbol.** `pkg.mod:<module>` becomes a real symbol (kind `module`, its line range) when the module has calls at top level | core | Streamlit pages, CLI scripts and notebooks-as-scripts get graph nodes and journey steps | Script-style code is common outside web frameworks |
| 7 | **Split reference edges.** `ref` = passed as a value (callback, registry, `Depends(fn)`); annotations become a separate, hidden-by-default kind | core | 241 refs → ~27 meaningful + the rest as "type use" | A graph is only useful if an edge means one thing |
| 8 | **Settings profile** (`pydantic_settings`, `environs`, `dynaconf`): settings classes, their env names, which code reads each field (`settings.models.judge`), and an "unread setting" finding | profile `settings` | config locations on cards fill themselves; unread fields flagged | Configuration is where "who decides" lives (people, via config) |
| 9 | **Prompt / template profile** (`jinja2`, `string.Template`, `.md` / `.txt` prompt files): template files, include tree, variables used vs passed, which function renders each | profile `templates` | the 12-template catalogue and the missing-variable check | Prompt files are the "code" of LLM apps, and server-rendered web apps have the same shape |
| 10 | **Script-folder imports.** When `import X` matches no module, try the importing file's own folder (what `streamlit run` / `python dir/x.py` put on `sys.path`) | core | 4 `ui_common.x()` edges | Any repo with runnable script folders |
| 11 | **Path finder on the page.** From → To shortest call path, both directions | page | "how does the chat box reach the model?" in one click | Pure UI over data the page already has |
| 12 | **Comparable resolution numbers.** Also print the existing report's definition (internal resolved ÷ internal candidates) | core | numbers line up across tools | Prevents the 94.6 vs 93.0 confusion |

Not worth copying as is: rendering a real prompt from sample data (it executes the target's code, which the skill deliberately never does), and the Mermaid sequences (the journeys already carry the same steps with payloads).

## 3. What each report does better today

**The existing report is deeper on the prompt pipeline:** a 17-step animated turn with the real rendered prompt, the template tree, and findings that retire themselves with a "fixed since" history.

**The skill report is wider on the code flow:**
- six journeys end to end (61 steps with what each step receives, returns and stores) against one;
- 53 written module notes (purpose, does, flow; 35 with a note) against docstrings;
- 14 decisions (code / people / model);
- 4 untrusted-input paths, including one the guard does not cover (company and role names are only cleaned, never injection-checked);
- 8 layer rules re-checked on every build, including the CLAUDE.md rules "the core never imports Streamlit" and "only the LLM layer imports openai / httpx" (0 violations);
- a "UI triggers" table (24 widgets → the code they run);
- a build that fails when the narrative names something the code no longer has.

## 4. Findings — none overlap

| Found by the skill | Severity | How it was checked |
|---|---|---|
| Deleting the newest interview lets the next one reuse its id and inherit its LLM cost (`InterviewSession.id` has no AUTOINCREMENT, `LLMCall.session_id` has no foreign key, `session_cost` sums by id). Cost shown is wrong, `must_close` can end the interview early, the report can drop to one judge run | medium | reproduced on an in-memory engine with the real models; re-read in code |
| One module-level import cycle | medium (generated) | code map |
| Raising the question-count limit above 12 in `.env` and saving 13–15 makes the next load fail validation, and every saved preference silently resets to defaults (`Preferences` 3–12 vs `Limits` 2–15; `model_copy` does not validate) | low | code |
| The design spec says deleting an application removes its "calls and audio"; the code keeps the call rows on purpose and there is no audio | low | spec sentence + functions |
| The spec's architecture tree lists modules, pages and tables that do not exist (`models.py`, `llm/image.py`, Dashboard, `LiveScore` …) | low | spec + code map |
| The RF5 penalty text hard-codes "(−5)" while the amount comes from `rubric.json` (they agree today) | info | code |
| The parked MFA login columns are still on the user table and nothing reads them | info | code |

The existing report's live findings are all `info` and the skill did not find them: the question-counting rule duplicated in `lab/judge.py`, a computed metric nobody reads, new API clients on every click, test-only functions (improvement 4), and template variables passed but unused (improvement 9).

## 5. Fixed in the skill while doing this (v0.5.0)

| Problem | Effect | Fix |
|---|---|---|
| No entry points in a Streamlit app — the only journey candidates were two lab CLIs | the app's main flows missing | `ui` profile: buttons, chat input, uploads and callbacks are entry points; "UI triggers" table |
| SQLModel `s.add` / `s.delete` not counted as writes — every journey said "writes –" | where data lands was invisible | ORM session calls → tables, naming the exact model (constructed, typed, or assigned from `select(M)`) |
| `with f() as s` on a `@contextmanager` returning `Iterator[Session]` left `s` untyped | 89.3% resolved | 93.0% (+80 calls) |
| pydantic `SecretStr.get_secret_value()` reported as AWS Secrets Manager | a false card | AWS only in modules that import boto3 |
| Layer rules saw internal modules only | "the core never imports Streamlit" could not be written | per-module `packages`; `forbid = ["streamlit"]` |
| Parallel writers could overwrite each other through `merge`; re-merging duplicated id-less entries | layer rules and decisions tripled | `merge --check`; text/title as the key when there is no id; `drop = true` removes a wrong drafted entry |
| `python -m lab.compare_prompts` suggested for a folder without `__init__.py` | a command that does not run | `python lab/compare_prompts.py` |
| `examples/` scanned by default | sample code diluted the map | `init` leaves examples, samples, benchmarks … out |

## 6. Conclusion

- The two tools see **the same core graph** (identical symbols, 575 shared call edges, identical table writers). The different headline numbers come from different counting scopes, not from one tool seeing more of the code.
- The existing report counts **this app's own machinery**: its gateways, prompts, settings, and tests. That makes it deep on the prompt pipeline. The skill counts **generic shapes** (calls, ORM, widgets, SDKs), which makes it wide and reusable, but blind to a repo's own gateway layer.
- Most of that gap closed with generic rules rather than repo-specific code (§1.3): gateway-following, injected callables, read-then-write, test-only callers and self-retiring findings. The skill now matches the existing map on model calls, binds, table access and test-only functions, while keeping its journeys, decisions, input paths and rules. What remains is the existing report's prompt depth: the template tree with variable checks (improvement 9) and the rendered prompt walk-through, which needs running the app's code.
