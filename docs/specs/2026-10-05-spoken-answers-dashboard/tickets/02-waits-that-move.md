# 02: Waits that move

**What to build:** Preparing an interview shows an animated, step-by-step progress that advances as each step really finishes: "Reading your documents → Planning the questions → Writing the opening question", plus "Recording the voice" in a Voice session, whose opening-question audio is now generated inside the same wait (one wait, not two). The engine's start function takes an optional progress callback (a plain callable; the core stays Streamlit-free). The planner gets a reasoning-effort setting in config (default `low`) passed on the planning call. The report button keeps the current judge and three runs, but shows an honest wait estimate computed in code from the user's recent successful judge calls for the chosen judge model (fallback text when there is none), and the report wait shows motion. Animations come from the design system's stylesheet and respect reduced motion.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Engine test: the progress callback receives the steps in order; a failure stops the steps and marks the session failed as before
- [x] Voice sessions: the opening question's audio is ready when the preparing panel completes; a TTS failure still falls back to text
- [x] Planner reasoning effort is a config setting (default `low`) and is sent on the planning call (unit test on the request)
- [x] Report wait estimate: unit test (no history → fallback; several judge calls → computed estimate)
- [x] Animated indicator for preparing and report waits, honouring `prefers-reduced-motion`
- [x] One live comparison on the committed sample application (old vs `low` planner effort: latency, number of requirements and questions, a short read of the plan) in the PR body
- [x] Full suite and ruff green; exercised once in the running app (a Voice start)
