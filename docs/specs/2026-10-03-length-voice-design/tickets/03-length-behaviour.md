# 03: Length behaviour

**What to build:** Quick sessions behave like a short practice: the interviewer opens with one sentence and no warm-up, asks the core questions (motivation, the job's top must-have requirement, one type-specific question), allows at most one follow-up per question (min of the difficulty cap and the Quick cap), and closes with a one-line, skippable "any quick question for me?" that satisfies the never-close-without-candidate-questions rule. Standard and Full keep today's flow. History's latest/best metrics count only Standard and Full; the trend marks Quick points differently. The prompt lab keeps running Full only.

**Blocked by:** 01

**Status:** done

- [x] Directive and follow-up cap computed in code from the Length (no counts in prompts)
- [x] Quick closing offer counts as the candidate-questions stage; S4 stays null when nothing was asked
- [x] Latest/best metrics ignore quick sessions; quick points marked on the trend
- [x] Lab sessions are Full
- [x] Engine tests with the scripted SDK for each length; AppTest for the History metrics; full suite and ruff green

**Decisions made while building:**

- The Quick directives live in `interview/engine.py` (`followup_cap`, `next_directive`, `close_correction`); P4's planner gets a Quick note from `prompting.QUICK_PLAN_NOTE`. No counts are written into prompts: the status block shows the target and the cap the code computed.
- A weak-spot drill (`interview/drill.drill_config`) is stored as `Length.CUSTOM`: it sizes itself from its targets, so it is neither labelled Full nor run with Quick's short flow. Custom sessions, like Quick, are practice: `history.counts_towards_scores` (Standard and Full only) leaves them out of latest/best, and the trend draws them as separate points.
- A skipped Quick question offer is not scored: the judge is unchanged, but `aggregate(..., cq_optional=True)` drops S4 at its lowest level ("asked no questions") for Quick sessions, so declining a skippable line is not a weakness. An asked question is still rated.
- The prompt lab refuses non-Full configs (`lab.runner.run_session`).
