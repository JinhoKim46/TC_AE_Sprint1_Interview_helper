# 05: Alignment + accessibility pass on all pages

**What to build:** Apply the design system from ticket 02 to the rest of the app — the start form (with the new Length and Channel controls), the interview screen (including the Voice player and "Show text"), the feedback report, History and Settings — so every page has aligned fields, equal-height cards and matching control sizes. Then audit every page with `design-review` and `web-design-guidelines` against screenshots at 1440 px and 420 px in light and dark mode, and fix what they find (focus visibility, labels, colour-only signals, contrast, overlap).

**Blocked by:** 02, 03, 04

**Status:** ready-for-agent

- [ ] Start form fields in an aligned grid with matching sizes; button rows match
- [ ] Interview screen, report, History and Settings use the shared helpers; no one-off sizes
- [ ] Audit findings fixed, or listed with a reason in the PR
- [ ] No dynamic content in CSS; no `unsafe_allow_html`; all untrusted text through `safe_md`
- [ ] AppTest suite and ruff green; before/after screenshots; the app exercised once
