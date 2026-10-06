# 03: Spoken answers (STT)

**What to build:** In a Voice interview the candidate can answer by speaking. The mic (Streamlit's audio input, 16 kHz WAV) is the main input; a new recording is transcribed once with `openai/whisper-large-v3-turbo` (the only transcription model the account's guardrail allows, checked 2026-10-05) and the transcript draft appears in an edit box with Send and Re-record; typing stays available below. Send goes through the existing answer path (guard, storage, judging), so a blocked transcript reuses the blocked-answer editor. Coaching retries work the same way. A new transcription method on the LLM client calls OpenRouter `POST /api/v1/audio/transcriptions` (not OpenAI-compatible: JSON with base64 audio under `input_audio: {data, format}`, plus `language`), using a plain HTTP request inside the client with the shared timeout/retry rules, and records an `LLMCall` with role `stt`, the response's `usage.cost` and latency. A core transcribe function in the voice module returns text or a short notice (never raises): budget check first, refuses recordings over the configured length/size before calling the model, treats an empty transcript as "nothing heard", never writes audio to disk and never logs the transcript. Model id, language, max seconds and max bytes live in a new STT settings section. Text sessions are unchanged.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] STT settings section in config (model, language, max seconds, max bytes); config test
- [x] Client transcription method: request shape, `LLMCall` row with role `stt` and reported cost, errors → `LLMError` (fake HTTP transport)
- [x] Core transcribe: success, empty transcript, too long/too big, over budget, model failure → notice; no file written
- [x] Voice session UI: mic first, transcript draft with Send / Re-record, typing still possible, coaching retry, blocked transcript → blocked editor; Text session shows no mic (AppTest with a fake transcriber)
- [x] One cheap `@pytest.mark.live` transcription test (e.g. TTS output of a short fictional sentence)
- [x] Full suite and ruff green; exercised once in the running app (one spoken answer in a Voice session)
