# 01: Length + Channel settings

**What to build:** Before an interview the candidate can choose a Length (Quick, Standard, Full, Custom) and a Channel (Text, Voice). The choice is stored with the session, shown as badges on the interview screen, in History rows and on the report header, and the defaults can be saved in Settings. Custom reveals the existing question-count slider; the other lengths take their question count from config presets. This ticket only stores and shows the settings: Quick's special behaviour is ticket 03 and the voice itself is ticket 04 (Voice sessions still run as text after this ticket).

**Blocked by:** None (can start immediately)

**Status:** done

- [x] `SessionConfig` has `length` and `channel` enums; `main_questions` comes from a `LengthPresets` config group (quick 3, standard 5, quick follow-up cap 1; Full keeps the type's realistic count) unless length is custom
- [x] Sessions stored before this change load as full + text
- [x] Start form: Length segmented control (Custom shows the slider, bounds from `Limits`), Channel control; defaults from preferences
- [x] Settings saves default Length and Channel (preferences)
- [x] Badges "Quick · Voice" style on the interview screen, History rows and the report header
- [x] Tests at the engine/config seam and AppTest for the form, Settings and badges; full non-live suite and ruff green
