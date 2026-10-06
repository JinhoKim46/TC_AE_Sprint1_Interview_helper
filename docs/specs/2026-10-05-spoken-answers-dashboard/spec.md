# Spec: spoken answers, waits that move, a fresh Interview page, and a progress Dashboard

Status: done · Date: 2026-10-05 · Route: Large (grill-with-docs → to-spec → to-tickets → parallel build)

## Problem Statement

The owner used the app for real interviews and hit five problems. In a Voice interview the interviewer speaks, but the candidate can only type, so it doesn't feel like a spoken interview. Preparing an interview takes about 35 seconds behind one static sentence (planner ~24 s, opening ~5 s, then a second spinner for the voice ~6 s), so it looks stuck. The feedback report takes about 70 seconds with the owner's chosen judge (`openai/gpt-5-mini`, a reasoning model run three times), and the page promises "about a minute" without showing any motion. After an interview with one company ends, its transcript stays on the Interview page until "Start a new interview" is pressed, so coming back later shows an old company's interview, which feels awkward. And there is no single place that shows how practice is going across all companies: History shows progress for one application at a time.

## Solution

**Spoken answers.** In a Voice interview the main input is a microphone. The candidate records an answer, the app transcribes it with a speech-to-text model, and the transcript appears in an edit box with **Send** and **Re-record**. Only the confirmed text is sent: it passes the same guard, is stored, and is judged exactly like a typed answer. The recording is discarded after transcribing. Typing stays possible below the mic. Text interviews are unchanged.

**Waits that move.** Preparing shows an animated, step-by-step progress ("Reading your documents → Planning the questions → Writing the opening question → Recording the voice" for Voice) that advances as each step really finishes, and the opening question's voice is generated inside that same wait (one wait, not two). The planner runs with low reasoning effort, which was already `low` in code (see Implementation Decisions). The report wait keeps the current judge and three runs (owner's decision), but says honestly how long it takes (an estimate computed from this user's recent judge calls) and shows motion while it runs.

**A fresh Interview page.** A finished interview is shown with its report right after it ends. When the candidate leaves the Interview page and comes back, the page shows the start form again, with a small note linking to the last interview in History.

**Dashboard.** A new **Dashboard** page shows overall KPIs (interviews done, time practised, average and best score, total cost), the overall score over time with one line per company, a per-company table (interviews, latest and best score, trend, last practised, weakest skill, link to History), and the rubric skills averaged across all companies, weakest first.

## Glossary (new terms)

- **Spoken answer** — an answer recorded with the microphone, transcribed, and confirmed (optionally edited) by the candidate before it is sent. Once sent it is an ordinary answer: same guard, same storage, same judging.
- **Transcript draft** — the editable text produced from a recording, not yet sent. It lives only in the UI session; it is never stored and never reaches the interviewer or the judge until the candidate presses Send.
- **Channel** (changed) — `voice` now means the interviewer speaks *and* the candidate may answer by speaking. Typing remains available in both channels.
- **Preparation step** — one named stage of starting an interview (documents, plan, opening question, voice), reported by the engine as it finishes so the UI can show real progress.
- **Dashboard** — the cross-company overview page. History stays the place for one session's transcript and report, and for one application's detailed progress.

## User Stories

1. As a candidate in a Voice interview, I want to answer by speaking, so that the practice feels like a real spoken interview.
2. As a candidate, I want to see the transcript of my spoken answer before it is sent, so that a transcription mistake never ends up in my interview or my report.
3. As a candidate, I want to edit the transcript before sending, so that I can fix a misheard word or a company name.
4. As a candidate, I want a Re-record button, so that I can start my answer again if I stumbled.
5. As a candidate, I want to still be able to type in a Voice interview, so that I can answer in a noisy place or when the mic doesn't work.
6. As a candidate, I want spoken answers to work for coaching retries too, so that retrying an answer works the same way as answering it.
7. As a candidate, I want a clear message when transcription fails or the recording is silent, so that I know to record again or type instead.
8. As a candidate, I want a spoken answer that the guard blocks to come back in the same edit box as a blocked typed answer, so that I can fix it the same way.
9. As a candidate, I want my voice recordings not to be stored, so that less personal data is kept about me.
10. As a candidate, I want a recording that is too long to be refused with a clear message, so that I don't wait for a transcription that will fail.
11. As a candidate, I want transcription to stop when the interview budget is used up, with a message that I can still type, so that cost limits never block the interview.
12. As the owner, I want transcription calls recorded like every other model call (role, model, cost, latency), so that the session cost and the budget stay correct.
13. As the owner, I want the speech-to-text model set in config and checked against the guardrail, so that it can be changed without code changes.
14. As a candidate, I want the preparing screen to show which step it is on and visibly move, so that I can tell it is working and not stuck.
15. As a candidate, I want each preparation step marked done as it finishes, so that I can see progress, not just a timer.
16. As a candidate in a Voice interview, I want the opening question's voice prepared within the same wait, so that there is one wait instead of two.
17. As a candidate, I want preparation to be faster, so that I can start practising sooner.
18. As the owner, I want the planner's reasoning effort to be a config setting, so that I can trade speed for plan quality without code changes.
19. As the owner, I want the faster planner checked once against the old one on the sample application, so that I know plan quality didn't drop.
20. As a candidate, I want the report button to tell me honestly how long the report takes, so that a 70-second wait is expected, not alarming.
21. As a candidate, I want the report wait to show motion, so that I know it is still working.
22. As a candidate, I want the wait estimate to come from my real recent reports, so that it stays right when I change the judge model.
23. As a candidate, I want a finished interview and its report to stay on screen right after it ends, so that I can read my feedback at once.
24. As a candidate, I want the Interview page to show the start form when I come back to it later, so that an old company's interview doesn't greet me.
25. As a candidate, I want a link to my last interview when the start form is shown, so that I can still find its report quickly.
26. As a candidate, I want a running interview to still be resumed when I come back, so that leaving the page never loses an interview in progress.
27. As a candidate, I want an "Open in History" action next to "Start a new interview" after an interview, so that the next step is obvious.
28. As a candidate, I want a Dashboard page in the sidebar, so that I see my overall interview progress in one place.
29. As a candidate, I want KPIs for interviews done, time practised, average score, best score and total cost, so that I know how much I have practised and how well.
30. As a candidate, I want a chart of my scores over time with one line per company, so that I can see whether I am improving for each application.
31. As a candidate, I want a table with one row per company (interviews, latest and best score, trend, last practised, weakest skill), so that I can see which application needs more practice.
32. As a candidate, I want to jump from a company's row to its History, so that I can read the details.
33. As a candidate, I want the rubric skills averaged across all companies, weakest first, so that I know what to practise next in general.
34. As a candidate, I want the Dashboard to follow the same scoring rules as History (Quick sessions don't count towards scores), so that the numbers agree everywhere.
35. As a new user, I want a helpful empty state on the Dashboard, so that I know to add an application and do an interview first.
36. As a candidate, I want the Dashboard to cost nothing to open, so that I can check it as often as I like.
37. As the owner, I want README and docs updated for spoken answers and the Dashboard, so that I can explain them at the review.

## Implementation Decisions

- **Speech-to-text is reinstated** (reverses the 2026-10-03 decision), as speak-then-confirm. The reasons it was dropped (guard, the judge's quote checks, exact transcript) are kept by design: the guard and the judge only ever see the confirmed text, exactly like a typed answer. Record the reversal in the design spec's decision log.
- **Model:** `openai/whisper-large-v3-turbo` via OpenRouter `POST /api/v1/audio/transcriptions`. It is the only one of the 24 listed transcription models this account's guardrail allows (checked 2026-10-05 with a 4-second clip: HTTP 200, 0.34 s, $0.00011). The model id, a language hint (`en`), the maximum recording length and the maximum upload size live in a new STT section of the settings, next to the TTS section.
- **Client:** a new transcription method on the LLM client, alongside its speech method. The endpoint is **not** OpenAI-compatible (JSON body with base64 audio under `input_audio: {data, format}`), so it uses a plain HTTP request inside the client, not the SDK. It records an `LLMCall` with role `stt`, the real `usage.cost` from the response, and latency; it uses the shared timeout and retry rules. No other module calls the endpoint.
- **Core:** the voice module gains a transcribe function that takes the recorded WAV bytes and returns the text or a short notice (never raises), like `speak`. It checks the session budget first (over budget → a notice, typing still works), refuses a recording over the length/size limit before calling the model, and treats an empty transcript as "nothing heard". It never writes the audio to disk and never logs the transcript.
- **Security:** the transcript is untrusted text like any answer. It is not guarded at transcription time; it is guarded when the candidate presses Send, through the existing answer path (rules + Jev), so a blocked spoken answer reuses the blocked-answer editor. The audio goes only to the transcription model, which follows no instructions.
- **UI (Voice sessions only):** the mic (Streamlit's audio input, 16 kHz WAV) is the main input; a new recording is transcribed once and the transcript draft is shown in an edit box with Send and Re-record; the chat text box stays available below. The same applies when retrying an answer in Coaching mode. Text sessions show no mic. The draft lives in the UI session state only.
- **Preparation progress:** the engine's start function accepts an optional progress callback (a plain callable, so the core stays Streamlit-free) and calls it with each preparation step as it finishes. The UI shows the steps in a status panel with a progress bar that advances per step and an animated indicator (CSS from the design system's stylesheet, respecting reduced motion). For a Voice session the opening question's voice is generated as the last step inside the same panel.
- **Planner speed:** a planner reasoning-effort setting (default `low`) is passed on the planning call. Before merging, one live comparison on the committed sample application (old vs new effort: latency, number of requirements and questions, a read of the plan) goes in the PR body. *Built (PR #54):* the planning call already sent `low` in code (the call log doesn't record the effort, so the spec misread it as unset); the setting is now `PLANNER_REASONING_EFFORT` in config. Measured on the sample: no effort sent 34 s, `low` 26 s, `minimal` 12 s but with a weaker plan (an over-rated coverage, a dropped motivation probe), so `low` stays and the start gets no faster from this; the fix for "stuck" is the visible step progress and the single Voice wait.
- **Report wait:** the judge model and three runs stay as they are (owner's decision). The button text shows an estimate computed in code from the user's recent successful judge calls for the chosen model (the slowest run decides the wait), with a fixed fallback when there is no history. The status panel shows motion while it runs.
- **Fresh Interview page:** the app's entry point remembers the last page shown; when the Interview page is entered from another page and there is no active session, the remembered finished session is cleared, so the start form shows. A running (active or preparing) session is always resumed. The start form shows a one-line note with a link to the last interview in History. The finished screen gets "Open in History" next to "Start a new interview".
- **Dashboard:** a new page in the Practise group. A new core function computes everything from stored rows in one pass (no model calls): KPIs, trend points per application, one row per application, and skill means across all scored sessions. It reuses the History module's rules (which sessions count towards scores, how a trend is computed, how skill means are computed); it does not copy rubric items or weights (they come from `docs/rubric.json`). "Time practised" is the sum, over sessions, of the time from the first to the last turn. Charts follow the `dataviz` skill and the design system tokens; every chart has a table or text alternative.
- **No schema change** is needed: spoken answers are stored as ordinary turns; the dashboard reads existing tables.

## Testing Decisions

- Good tests check behaviour at the highest seam: the public core functions and the pages through Streamlit's AppTest, with a fake LLM/HTTP layer and an in-memory SQLite engine. No network in unit tests.
- **Transcription:** the client method with a fake HTTP transport (request shape: base64 under `input_audio`, model and language; the `LLMCall` row with role `stt` and the reported cost; error → `LLMError`). The voice transcribe function: success, empty transcript, too long, over budget, model failure (notice, no exception), and no file written. One cheap `@pytest.mark.live` test with a generated tone or the TTS output of a short sentence. Prior art: the TTS tests (`speak`, PCM → WAV) and the live TTS test.
- **Interview page:** AppTest for a Voice session (mic shown; a fake transcript fills the draft box; Send stores an answer; a blocked transcript returns to the blocked editor; a Text session shows no mic). AppTest for the fresh-page rule (a finished session stays right after ending; after visiting another page the start form shows; an active session is always resumed). Prior art: `tests/test_app_ui.py`.
- **Preparation:** an engine test that the progress callback receives the steps in order, and that a failure stops the steps and marks the session failed as today. Prior art: `tests/test_engine.py`.
- **Report estimate:** a unit test for the estimate (no history → fallback; several judge calls → the computed value).
- **Dashboard:** core tests on seeded sessions and evaluations across two applications (KPIs, Quick sessions excluded from scores, per-company rows, trend, skill means, the empty state). An AppTest that the page renders with data and with none. Prior art: `tests/test_history.py`.

## Out of Scope

- Streaming or live (word-by-word) transcription, and voice activity detection: the candidate presses record and stop.
- Storing or replaying the candidate's recordings.
- A mic in Text interviews.
- Changing the judge model, the number of judge runs, or the rubric to speed up the report.
- A TTS model picker (only one TTS model passes the guardrail; the voice is already selectable in Settings).
- Pronunciation, pace or filler-word feedback from the audio.
- Dashboard export, goals or reminders.

## Further Notes

- The owner's reported "interview stuck" was the preparing screen (confirmed 2026-10-05); the DB shows no failed or hung model call, so the fix is visible progress plus a faster planner, not a timeout change.
- Answer to "what are blocked answers?": answers the prompt-injection guard (or the empty/too-long limits) refused before storing; they are never saved and come back in an edit box. Worth one sentence in the README's user-facing part, since the owner had to ask.
- Spoken answers add a model call per answer (cost about $0.0001 per few seconds of audio at the checked price) and a failure point; both fall back to typing.
