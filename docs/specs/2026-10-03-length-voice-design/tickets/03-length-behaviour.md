# 03: Length behaviour

**What to build:** Quick sessions behave like a short practice: the interviewer opens with one sentence and no warm-up, asks the core questions (motivation, the job's top must-have requirement, one type-specific question), allows at most one follow-up per question (min of the difficulty cap and the Quick cap), and closes with a one-line, skippable "any quick question for me?" that satisfies the never-close-without-candidate-questions rule. Standard and Full keep today's flow. History's latest/best metrics count only Standard and Full; the trend marks Quick points differently. The prompt lab keeps running Full only.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Directive and follow-up cap computed in code from the Length (no counts in prompts)
- [ ] Quick closing offer counts as the candidate-questions stage; S4 stays null when nothing was asked
- [ ] Latest/best metrics ignore quick sessions; quick points marked on the trend
- [ ] Lab sessions are Full
- [ ] Engine tests with the scripted SDK for each length; AppTest for the History metrics; full suite and ruff green
