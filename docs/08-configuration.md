# Configuration and costs

All settings live in `src/interview_app/config.py` and can be changed in `.env` (nested groups use `__`; a typo in a nested key fails at start-up). The length, voice and speech settings:

| Setting | Default | What it does |
|---|---|---|
| `LENGTH_PRESETS__QUICK` | 3 | Main questions in a Quick session (2–15, at most Standard) |
| `LENGTH_PRESETS__STANDARD` | 5 | Main questions in a Standard session (2–15) |
| `LENGTH_PRESETS__QUICK_MAX_FOLLOWUPS` | 1 | Follow-up cap per main question in Quick; the session uses min(difficulty cap, this) |
| `TTS__MODEL` | `google/gemini-3.8-flash-lite-tts` | The default text-to-speech model (returns raw PCM, wrapped into WAV); must be one of `TTS__AVAILABLE_MODELS` |
| `TTS__AVAILABLE_MODELS` | `google/gemini-3.8-flash-lite-tts`, `google/gemini-3.8-flash-tts` | JSON list of `{"id", "label"}` offered in the Settings "Voice model" picker; check a model against the guardrail before adding it |
| `TTS__VOICES` | one voice per interview type | JSON map of interview type → voice, e.g. `'{"hiring_manager": "Puck"}'` |
| `TTS__DEFAULT_VOICE` | `Charon` | Voice for an interview type missing from `TTS__VOICES` |
| `TTS__AUDIO_TOKENS_PER_SECOND` | 32 | Audio tokens per second used for the TTS cost estimate |
| `TTS__MAX_CHARS` | 2000 | A longer question is cut before speaking (OWASP LLM10) |
| `STT__MODEL` | `openai/whisper-large-v3-turbo` | The speech-to-text model for spoken answers |
| `STT__LANGUAGE` | `en` | Language hint for the transcription |
| `STT__MAX_SECONDS` | 180 | A longer recording is refused before any model call (OWASP LLM10) |
| `STT__MAX_BYTES` | 6000000 | Upload size cap for one recording (16 kHz mono WAV is 32 KB per second) |

**TTS cost:** OpenRouter's speech response carries no usage, so a `tts` call's cost is **estimated** from the catalog prices: input tokens ≈ characters / 4, output tokens = audio seconds × `TTS__AUDIO_TOKENS_PER_SECOND` (deliberately conservative). The estimate is logged as an `LLMCall` row with role `tts` and counts towards the session cost and budget. In testing, a two-turn Quick · Voice session cost about $0.014 in total (the two spoken questions about $0.003 and $0.0016). The estimate uses the price of the model that actually spoke (the session's voice model). Only `google/gemini-3.8-flash-lite-tts` (audio $6 per M tokens) and `google/gemini-3.8-flash-tts` (audio $9 per M tokens) are allowed by this account's OpenRouter guardrail (checked 2026-10-05; the other 21 listed TTS models return 404); a spoken question of about 20 s costs roughly $0.004 or $0.006. Audio is generated once per question and stored under `data/audio/<user>/<session>/`, so replays and later views cost nothing; deleting a session or its application deletes the files.

**STT cost:** a spoken answer is one `stt` call to OpenRouter's `/audio/transcriptions` (not OpenAI-compatible: JSON with base64 audio, so `LLMClient.transcribe` sends it as a plain HTTP request with the shared retry rules). Its response reports the real charged cost (`usage.cost`), logged as an `LLMCall` row with role `stt` that counts towards the session cost and budget: about $0.0001 for a few seconds of audio. Only `openai/whisper-large-v3-turbo` passes this account's guardrail (checked 2026-10-05; the other 23 listed transcription models return 404). The transcript is never logged and the audio is never written to disk.

Everything runs locally: a SQLite database in `data/`, model calls through OpenRouter.
