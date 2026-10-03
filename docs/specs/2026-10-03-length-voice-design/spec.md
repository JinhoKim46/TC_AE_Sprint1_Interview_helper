# Spec: interview Length, Voice channel, and an aligned design

Status: ready-for-agent · Date: 2026-10-03 · Route: Large (grill-with-docs → to-spec → to-tickets → parallel build)

## Problem Statement

Every interview today is a full-length session (about seven main questions with follow-ups, 30–45 minutes), so a quick practice before a call is not possible. The interview is text only, so it doesn't feel like being asked out loud. The UI works but its fields, cards and buttons don't line up or match in size, which makes it look unfinished and harder to scan.

## Solution

Before an interview the candidate picks a **Length** — Quick (a short practice on the core questions), Standard, Full (the real interview) or Custom — and a **Channel** — Text or Voice. In Voice, the interviewer speaks every question (text-to-speech), the newest question plays automatically, and the question text is hidden behind "Show text" so the candidate practises listening; answers are still typed. Every page gets one consistent layout: aligned fields, equal-height cards, matching control sizes, checked for accessibility.

## Glossary (new terms)

- **Length** — how many main questions a session asks and how much ceremony it has: `quick`, `standard`, `full`, `custom`. Breadth, not pressure.
- **Difficulty** — unchanged: pressure and follow-up depth. Orthogonal to Length.
- **Channel** — how the interviewer's questions reach the candidate: `text` or `voice`. Answers are always typed (no speech-to-text).
- **Voice** — the TTS voice id used for a session's interviewer; derived from the persona, overridable in Settings.

## User Stories

1. As a candidate, I want to choose Quick, Standard or Full before an interview, so that I can fit practice into the time I have.
2. As a candidate, I want Quick to skip the warm-up and ask only the core questions, so that ten minutes of practice is spent on what matters most.
3. As a candidate, I want Quick to still ask about the job's top must-have requirement and my motivation, so that even a short session targets this application.
4. As a candidate, I want Full to behave exactly like today's interview, so that I can rehearse the real thing.
5. As a candidate, I want a Custom option that shows the question-count slider, so that I can still pick an exact number.
6. As a candidate, I want Difficulty to keep working independently of Length, so that I can do a short but tough session.
7. As a candidate, I want Quick to limit follow-ups to one per question, so that the session stays short.
8. As a candidate, I want Quick to end with a one-line, skippable "any quick question for me?", so that I still practise asking without a long stage.
9. As a candidate, I want to choose Text or Voice before an interview, so that I can practise reading or listening.
10. As a candidate in Voice, I want each new question to play automatically, so that it feels like a real interviewer speaking.
11. As a candidate in Voice, I want a replay button on every interviewer turn, so that I can hear a question again.
12. As a candidate in Voice, I want the question text hidden behind "Show text", so that I practise listening but can still check a word I missed.
13. As a candidate in Voice, I want the text to appear automatically if the audio fails, so that a TTS problem never blocks my interview.
14. As a candidate, I want the interviewer's voice to match the persona and stay the same through the session, so that it sounds like one person.
15. As a candidate, I want to pick a fixed voice in Settings, so that I can choose one I understand well.
16. As a candidate, I want my default Length and Channel saved in Settings, so that I don't set them every time.
17. As a candidate, I want replays and later views of a session to cost nothing, so that audio is generated once per question.
18. As a candidate, I want the audio of a session deleted when I delete the session or its application, so that no voice files linger.
19. As a candidate, I want TTS cost counted in the session's cost and budget, so that the cost shown is honest.
20. As a candidate, I want the Length and Channel shown as badges on the interview screen, in History and on the report, so that I know what kind of session a score came from.
21. As a candidate, I want my latest and best scores in History to count only Standard and Full sessions, so that a short Quick session doesn't distort my progress.
22. As a candidate, I want Quick sessions marked differently on the score trend, so that I can still see them.
23. As a candidate, I want the start form's fields aligned in a clean grid with matching sizes, so that the form is quick to scan.
24. As a candidate, I want cards on Home, Applications and History to have equal heights and aligned contents, so that the pages look orderly.
25. As a candidate, I want buttons in a row to have the same size and alignment, so that the primary action is obvious.
26. As a candidate using the keyboard or a screen reader, I want visible focus, labelled controls and status not shown by colour alone, so that the app is usable for me.
27. As a candidate on a narrow window, I want layouts to stack cleanly, so that nothing overlaps or scrolls sideways.
28. As the owner, I want the prompt lab to keep running Full sessions only, so that R4 comparisons stay like-for-like.
29. As the owner at the review, I want the reports and README to describe Length and Voice, so that I can explain them.

## Implementation Decisions

- **Session settings:** `SessionConfig` gains `length` (enum quick/standard/full/custom, default from preferences, else standard) and `channel` (enum text/voice, default from preferences, else voice). `main_questions` is derived from the length preset unless the length is custom. Old sessions without the fields load as full + text (backward compatible).
- **Presets in config:** a `LengthPresets` settings group holds main questions per length (quick 3, standard 5, full 7) and Quick's follow-up cap (1). No counts in code or prompts.
- **Quick behaviour is code-computed:** the directive tells the interviewer to open with one sentence and no warm-up, and closes with a one-line skippable candidate-question offer. The core-question choice (motivation, top must-have requirement, one type-specific question) is an instruction in the directive, which already carries the target. Follow-up cap = min(difficulty cap, Quick cap). The "never close without candidate questions" guarantee is satisfied by the one-line offer in Quick.
- **Comparability:** a small pure function in the core (`journey` or `history`) filters latest/best metrics to standard/full; the trend chart marks quick points. The judge is unchanged; S4 stays null when no candidate questions were asked.
- **Voice is one core module** (`voice`): `speak(turn)` returns stored audio for an interviewer turn, generating it once. It calls OpenRouter's `/audio/speech` through the LLM gateway (a `speech` method on the client, so the call is logged as an `LLMCall` with role `tts`, model, latency and an estimated cost from the price catalog). The model is `google/gemini-3.8-flash-lite-tts` (the only TTS model this account's guardrail allows, checked 2026-10-03). It returns raw PCM only (`audio/pcm;rate=24000;channels=1`), which the module wraps into WAV.
- **Voices:** a config table maps persona → voice id from the model's `supported_voices` (e.g. Charon, Puck, Kore, Aoede); a Settings override (preference) forces one voice. The voice is stored in the session so it stays fixed.
- **Storage:** audio files under `data/audio/<user_id>/<session_id>/<turn_idx>.wav` (gitignored), recorded in a new `TurnAudio` table (user_id, session_id, turn idx, path, voice, model) or columns on `Turn` — the builder picks the simpler one and documents it. Deleting a session or application deletes its audio files and rows.
- **Budget:** TTS cost is part of the session cost, so `must_close` and the judge's budget check see it. When over budget, TTS is skipped (text only) rather than closing early.
- **Failure:** any TTS error is logged and the turn is shown as text with a short notice; the interview never fails because of voice.
- **UI:** the start form gets Length (segmented control; Custom reveals the slider) and Channel. In Voice, the newest interviewer turn auto-plays (`st.audio` with autoplay) and every interviewer turn has a player and a "Show text" toggle; if audio is missing, the text shows. Coaching tips and scores are never spoken. Settings gets default Length, default Channel and a voice override.
- **Design system:** one static stylesheet file in the app folder, loaded once by a helper; it contains no user or model text (it must never be built with f-strings from data). Helpers in `ui_common` for equal-height card rows, aligned form rows and button rows. The theme stays indigo; contrast is AA or better in light and dark.
- **Security unchanged:** no `unsafe_allow_html` with any dynamic content; all untrusted text through `safe_md`; TTS input is the interviewer's own message (model output already shown on screen), sent as data, never as instructions.
- **Speech-to-text is dropped** from the design: remove STT from the docs and plans.

## Testing Decisions

- Test external behaviour at the highest seam: the engine's public functions with the scripted fake SDK (prior art: `tests/test_engine.py`), the voice module with a fake SDK and a temp data dir (prior art: `tests/test_llm_client.py`, `tests/test_history.py`), the UI with AppTest and a temp DB (prior art: `tests/test_app_ui.py`).
- Length: the stored config, `main_questions` per preset, Custom keeping the slider value, the Quick directive and follow-up cap, Quick's one-line closing offer satisfying the candidate-questions rule, old sessions loading as full/text, metrics ignoring quick sessions.
- Voice: audio generated once and reused, an `LLMCall` row with role tts and a cost, the PCM→WAV wrapper (header and length), persona→voice mapping and the Settings override, a TTS failure leaving the turn readable, deletion removing files, budget exhaustion skipping TTS.
- UI: start-form controls and Custom slider, badges, Voice "Show text" default and the automatic text fallback, Settings defaults saved.
- Design: no unit tests; screenshots at 1440 px and 420 px, light and dark, reviewed with `design-review` and `web-design-guidelines`; the AppTest suite must stay green.
- One cheap live test (`@pytest.mark.live`) synthesises a short sentence with the configured TTS model.

## Out of Scope

- Speech-to-text answers (dropped, not deferred).
- Streaming or real-time audio; voice for the coaching tips or the report.
- Changing the judge, rubric or prompt variants beyond Quick's directive.
- Making Quick scores comparable to Full by any adjustment.

## Further Notes

- Ticket graph and order: `tickets/README.md`. 01 and 02 start at once; 03 and 04 start when 01 merges; 05 when 02, 03 and 04 merge; 06 last.
- The reports (`reports/interview-helper-report.html`, `reports/code-flow-report.html`, `reports/2026-10-02-project-report.md`) are updated in ticket 06.
