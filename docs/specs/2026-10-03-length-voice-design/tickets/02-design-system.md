# 02: Design system + Home/Applications

**What to build:** A small design system that makes fields, cards and buttons line up and match in size, applied first to Home and Applications. One static stylesheet file in the app folder (no user or model text, never built from data) loaded once by a `ui_common` helper; helpers for equal-height card rows, aligned form rows and same-size button rows; the indigo theme tuned for AA contrast in light and dark. Use the `frontend-design` skill to drive the visual decisions and `web-design-guidelines` for accessibility. Do not touch the interview, report, History or Settings pages (other tickets change them in parallel; ticket 05 applies the system there).

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Static stylesheet + loader helper; a test proves the stylesheet contains no template placeholders and is loaded without user text
- [x] Card rows on Home and Applications have equal heights and aligned contents; button rows match in size; form fields on Applications align in a grid
- [x] Layout stacks cleanly at 420 px with no horizontal scroll; light and dark both pass AA contrast
- [x] Before/after screenshots (1440 px and 420 px, light and dark) reviewed with `design-review`; findings fixed or listed
- [x] AppTest suite and ruff green; the app exercised once
