# 04: Voice channel (TTS)

**What to build:** In a Voice session the interviewer speaks each question. A core `voice` module turns an interviewer turn into stored audio, once: it calls OpenRouter `/audio/speech` through a new `speech` method on the LLM client (logged as an `LLMCall` with role `tts` and an estimated cost from the price catalog), model `google/gemini-3.8-flash-lite-tts` from config (it returns raw PCM 24 kHz mono, so the module wraps it as WAV). The voice comes from a persona → voice table in config, with a Settings override, and is fixed for the session. Files live under `data/audio/<user_id>/<session_id>/` and are deleted with the session or application. The interview screen auto-plays the newest question, shows a player on every interviewer turn, hides the text behind "Show text" by default, and shows the text automatically if audio is missing. TTS is skipped when the session budget is exhausted, and any TTS failure leaves the turn readable with a short notice. Coaching tips and scores are never spoken.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `speech` on the LLM client + `voice` module; PCM → WAV wrapper tested (header, length)
- [ ] Audio generated once and reused; replays and History cost nothing
- [ ] Persona → voice mapping and Settings override; voice stored with the session
- [ ] Deleting a session or application removes its audio files and rows
- [ ] Budget exhaustion skips TTS; a TTS error falls back to text with a notice
- [ ] Interview screen: autoplay newest, player per interviewer turn, "Show text" hidden by default, automatic text fallback
- [ ] Unit tests with a fake SDK and temp data dir; AppTest for the Voice UI; one cheap `@pytest.mark.live` TTS test; full suite and ruff green; exercised once in the running app (a real voice session of 2–3 turns)
