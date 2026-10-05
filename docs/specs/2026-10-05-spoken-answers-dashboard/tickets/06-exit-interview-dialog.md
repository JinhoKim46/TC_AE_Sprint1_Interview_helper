# 06: Exit interview dialog

**What to build:** Owner request (2026-10-05): "during the interview, when leave the page, pop up alert save or discard. and during the interview, there is no button to exit." A visible **Exit interview** button sits in the session header panel at the top of the Interview page while an interview is active. It opens a dialog with four choices: **Save & exit** (the interview stays in progress, every answer is already stored, the candidate goes to Home and can resume it later), **End & get feedback** (today's End interview, then the finished screen with "Get my feedback report"), **Discard** (deletes the interview and its turns and audio with `history.delete_session`, after a confirmation step inside the dialog, then shows the start form) and **Cancel** (nothing changes). The sidebar's End interview button goes; the sidebar keeps the "Cost so far" metric. While an interview is active or preparing, the page navigation is hidden (`st.navigation(pages, position="hidden")`) so the dialog is the way out; "Save & exit" brings it back until the interview is resumed. The decision uses one small query (`engine.active_session_id`, no turns loaded). A page reached another way mid-interview (a bookmark) shows a note with "Back to the interview"; Home keeps its "Resume the interview" button. A tiny inline `beforeunload` script, drawn only during an active interview, makes the browser ask "Leave site?" on tab close or reload; it contains no user or model text.

**Blocked by:** 01, 03

**Status:** done

- [x] "Exit interview" button in the session header during an active interview; the dialog offers Save & exit, End & get feedback, Discard (with confirmation) and Cancel
- [x] Save & exit keeps the status active and leaves the page; coming back resumes it
- [x] End & get feedback sets `ended_early` and shows the feedback button
- [x] Discard removes the session and its turns (core test: deleting an active session works); Cancel changes nothing
- [x] Navigation hidden during an active interview and shown otherwise (and after Save & exit); another page reached mid-interview links back to it
- [x] The beforeunload script is only drawn during an active interview
- [x] README user flow updated
- [x] AppTest covers every choice, the navigation position and the leave-site script; full suite and ruff green; exercised once in the running app
