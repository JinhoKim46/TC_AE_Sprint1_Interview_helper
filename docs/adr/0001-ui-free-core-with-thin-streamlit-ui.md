---
status: accepted
date: 2026-10-02
---

# A UI-free core package with a thin Streamlit UI

The course brief requires Streamlit (or Next.js), but the owner keeps using the app after the review and may want a different front end later, and Streamlit's rerun model makes logic written inside pages hard to test. So all real work lives in `src/interview_app/`, which never imports Streamlit, and `app/` is a thin layer that draws pages and calls the core.

## Considered Options

- **Logic inside the Streamlit pages:** fastest to start, but every rule would only be testable through `AppTest`, and a UI change would touch business logic.
- **Flask + HTML/CSS** (the original brainstorm): rejected because the brief requires Streamlit or Next.js and the reviewer checks it.
- **FastAPI core + a JavaScript front end:** the cleanest split, but too much for a one-week sprint.

## Consequences

- The core is unit-tested with plain pytest, a mocked LLM layer and in-memory SQLite; `AppTest` is only needed for the pages.
- Replacing the UI means rewriting `app/` only. That is the escape hatch if Streamlit's rerun model blocks streaming replies or real-time voice.
- UI state (`st.session_state`, reruns, dialogs) must stay in `app/`; anything that has to survive a refresh is stored in the database by the core.
