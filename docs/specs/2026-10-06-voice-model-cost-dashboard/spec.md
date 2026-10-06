# Spec: a Voice model picker, and cost tracking on the Dashboard

Status: ready-for-agent · Date: 2026-10-06 · Route: Medium (grill → spec → two parallel builds)

## Problem Statement

The owner can choose the interviewer's **voice** in Settings but not the **voice model**: the TTS model is fixed in config, because on 2026-10-03 only one TTS model passed the account's OpenRouter guardrail. A re-check on 2026-10-05 found a second allowed model. Separately, the Dashboard shows only one "total cost" number, so the owner can't see which company, which day or which part of the app the money goes to.

## Solution

**Voice model picker.** Settings gets a **Voice model** dropdown next to "Interviewer voice", listing the TTS models allowed by the guardrail, each with a short plain-words note. The choice is saved as a preference, stored with each new Voice interview when it starts (like the voice) and used for every spoken question of that interview. The default stays the current model.

**Cost on the Dashboard.** The Dashboard adds a **Cost** section: a Cost column (and the average cost per interview) in the per-company table; a spend-over-time chart stacked by purpose; and a breakdown by purpose (interviewer, planning, report, live scoring, voice, transcription, guard), as a bar with a table version.

## User Stories

1. As a candidate, I want to choose the voice model in Settings, so that I can pick a more natural voice or the cheaper one.
2. As a candidate, I want each model's option to say briefly what it is good for and how its price compares, so that I can choose without looking up prices.
3. As a candidate, I want my voice-model choice to stay the same for the whole interview, so that the interviewer never changes sound mid-interview.
4. As a candidate, I want my saved voice (e.g. Puck) to work with either model, so that changing the model doesn't reset my voice.
5. As the owner, I want the list of allowed voice models in config, so that I can add one after checking it against the guardrail without code changes.
6. As the owner, I want an interview whose stored model was later removed from config to fall back to the default model, so that old sessions still play.
7. As the owner, I want every TTS call recorded with the model that actually spoke and a cost estimated from that model's price, so that cost tracking stays correct.
8. As a candidate, I want to see how much each company's practice cost, so that I know where my spend goes.
9. As a candidate, I want the average cost per interview, so that I can predict what the next one will cost.
10. As a candidate, I want a chart of spend over time, stacked by purpose, so that I can see when I spent and on what.
11. As a candidate, I want a breakdown of total spend by purpose (interviewer, planning, report, live scoring, voice, transcription, guard), so that I know which feature costs the most.
12. As a candidate, I want every cost chart to have a table version, so that I can read exact numbers and the page stays accessible.
13. As a candidate, I want spend that belongs to no interview (e.g. checking an uploaded document) included in the totals and over time, so that the totals match Settings' usage table.
14. As a candidate, I want the Dashboard's cost numbers to agree with the Settings usage table, so that I can trust both.
15. As a candidate, I want the cost section to cost nothing to open, so that I can check it any time.

## Implementation Decisions

- **Allowed TTS models** (checked 2026-10-05 with one tiny call each; the other 21 listed TTS models return "blocked by guardrail"): `google/gemini-3.8-flash-lite-tts` (current default; audio $6 per M tokens) and `google/gemini-3.8-flash-tts` (audio $9 per M tokens). Both return 24 kHz mono PCM and support the same 30 voices, so the PCM → WAV path and the voice list are shared.
- **Config:** the TTS settings section gains a list of available models (id plus a short label), with a validator that the default model is in the list. The model ids live only in config.
- **Preference and session:** a voice-model preference (empty = the config default) next to the voice preference; a Voice session stores its TTS model in its config when it starts (the same place the voice is stored), and the voice module uses the session's model if it is still in the allowed list, else the default. The TTS audio row already records the model; keep that the session's model.
- **Cost estimate:** the speech call's cost is estimated from the price catalog for the model actually used (the catalog already lists speech models); add a test that the second model's price is used.
- **Settings UI:** a select box labelled "Voice model" beside "Interviewer voice", in the same form row, saved with the other defaults.
- **Cost purposes:** a display mapping from call-log role to a plain-words purpose lives in one place in code: interviewer → Interviewer, planner → Planning, judge → Report, live_score → Live scoring, tts → Voice, stt → Transcription, guard → Guard; any other role (e.g. lab roles) → Other. This is a label map, not a rubric or a limit.
- **Cost aggregation in core**, done by the database (SUM … GROUP BY, as the Settings usage table does), never by a model: per application (through the call's session), per day and purpose, and per purpose. Calls without a session count in totals, over time and by purpose, but not in any company row. The Dashboard's total equals the Settings total for the same user.
- **Spend over time:** daily buckets; when the data spans more than 60 days, weekly buckets. A stacked bar chart following the `dataviz` skill and the design-system tokens, with a table version in an expander.
- **No schema change.**

## Testing Decisions

- High seams: the config and preference functions, the voice module's speak path with a fake SDK, the Dashboard core function with an in-memory SQLite engine, and AppTest for the two pages. No network in unit tests.
- **Voice model:** config validation (default in the list; unknown model rejected); a preference round trip; a Voice session started with the second model speaks with it (fake SDK sees the model id; the TurnAudio row and the LLMCall row record it; the cost uses its price); a stored model no longer in config falls back to the default. AppTest: Settings shows the dropdown and saves the choice. One cheap `@pytest.mark.live` TTS call with the second model. Prior art: `tests/test_voice.py`, the voice-override Settings AppTest.
- **Cost:** seeded calls across two applications, several roles, two days and a session-less guard call: per-company cost and average, purposes, buckets (daily, and weekly past 60 days), and totals equal to `usage_summary`. AppTest: the Cost section renders with data and with none; opening it makes no model call. Prior art: `tests/test_dashboard.py`, `tests/test_usage*` if present.

## Out of Scope

- Choosing the transcription model (only `openai/whisper-large-v3-turbo` passes the guardrail).
- A monthly budget or spend alerts.
- Previewing a voice model's sound in Settings.
- Changing the per-interview budget limit.

## Further Notes

- A typical spoken question (~20 s of audio) costs about $0.004 with the lite model and $0.006 with the standard one.
