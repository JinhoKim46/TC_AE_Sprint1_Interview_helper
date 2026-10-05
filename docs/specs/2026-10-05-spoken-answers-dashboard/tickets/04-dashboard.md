# 04: Dashboard page

**What to build:** A new **Dashboard** page in the Practise group of the sidebar gives the cross-company overview. A new core function computes everything from stored rows in one pass, with no model calls: overall KPIs (interviews done, time practised = sum of first-to-last-turn time per session, average and best score, total cost), the overall score over time with one line per application, one row per application (interviews, latest and best score, trend, last practised, weakest skill, a link that opens it in History), and the rubric skills averaged across all scored sessions, weakest first. It reuses the History module's rules (which sessions count towards scores, how trends and skill means are computed) and never copies rubric items or weights. Charts follow the `dataviz` skill and the design system tokens; every chart has a table or text alternative. A helpful empty state shows when there are no applications or no interviews yet.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Core tests on seeded sessions and evaluations across two applications: KPIs, Quick sessions excluded from scores, per-application rows, trend, skill means, empty state
- [ ] Page: KPI row, score-over-time chart (one line per company), per-company table with a link to History, skills across companies; empty state
- [ ] AppTest: renders with data and with none; opening it makes no model call
- [ ] Full suite and ruff green; exercised once in the running app
