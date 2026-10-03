# 01: Length + Channel settings

**What to build:** Before an interview the candidate can choose a Length (Quick, Standard, Full, Custom) and a Channel (Text, Voice). The choice is stored with the session, shown as badges on the interview screen, in History rows and on the report header, and the defaults can be saved in Settings. Custom reveals the existing question-count slider; the other lengths take their question count from config presets. This ticket only stores and shows the settings: Quick's special behaviour is ticket 03 and the voice itself is ticket 04 (Voice sessions still run as text after this ticket).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `SessionConfig` has `length` and `channel` enums; `main_questions` comes from a `LengthPresets` config group (quick 3, standard 5, full 7, quick follow-up cap 1) unless length is custom
- [ ] Sessions stored before this change load as full + text
- [ ] Start form: Length segmented control (Custom shows the slider, bounds from `Limits`), Channel control; defaults from preferences
- [ ] Settings saves default Length and Channel (preferences)
- [ ] Badges "Quick · Voice" style on the interview screen, History rows and the report header
- [ ] Tests at the engine/config seam and AppTest for the form, Settings and badges; full non-live suite and ruff green
