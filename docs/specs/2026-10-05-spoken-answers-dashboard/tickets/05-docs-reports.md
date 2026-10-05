# 05: Docs + reports

**What to build:** The docs describe the app as it now behaves. The design spec's decision log records that speech-to-text was reinstated as speak-then-confirm (reversing 2026-10-03) and why the earlier objections no longer apply; the channel row and feature list mention spoken answers and the Dashboard. The README covers spoken answers (model, cost, privacy: recordings discarded), the faster preparation, the Dashboard, and one plain sentence on what a blocked answer is. The code map and reports are regenerated.

**Blocked by:** 01, 02, 03, 04

**Status:** ready-for-agent

- [ ] Design spec decision log, channel row and feature list updated
- [ ] README updated (spoken answers, Dashboard, blocked answers, preparation)
- [ ] `reports/code_map.json` and the generated reports rebuilt; their tests green
- [ ] Spec and ticket statuses set to done
