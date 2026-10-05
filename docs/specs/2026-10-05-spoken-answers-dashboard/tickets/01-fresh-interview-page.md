# 01: Fresh Interview page

**What to build:** Right after an interview finishes or is ended, the Interview page keeps showing its transcript and report (as today). When the candidate leaves the Interview page for another page and comes back, and no interview is active or preparing, the page shows the start form instead of the old company's interview, with a one-line note linking to that last interview in History. A running interview is always resumed. The finished screen offers "Open in History" next to "Start a new interview". The app's entry point remembers the last page shown so the Interview page can tell "just finished" from "came back later".

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] A finished or ended interview stays on screen (with its report) until the candidate leaves the page
- [ ] Coming back from another page shows the start form plus a link to the last interview in History
- [ ] An active or preparing session is always resumed, whatever page the candidate came from
- [ ] "Open in History" on the finished screen opens that session in History
- [ ] AppTest covers: stays after ending; start form after visiting another page; active session resumed; full suite and ruff green; exercised once in the running app
