# Tickets: Length, Voice channel, aligned design

Spec: `../spec.md`. Run as a graph: start every ticket whose blockers are all `done`; never wait on a ticket you don't depend on.

```mermaid
graph LR
  01[01 Length + Channel settings] --> 03[03 Length behaviour]
  01 --> 04[04 Voice channel - TTS]
  02[02 Design system + Home/Applications] --> 05[05 Alignment + a11y pass]
  03 --> 05
  04 --> 05
  05 --> 06[06 Docs + reports]
```

| # | Ticket | Blocked by | Status |
|---|---|---|---|
| 01 | Length + Channel settings | — | ready-for-agent |
| 02 | Design system + Home/Applications | — | ready-for-agent |
| 03 | Length behaviour | 01 | ready-for-agent |
| 04 | Voice channel (TTS) | 01 | ready-for-agent |
| 05 | Alignment + accessibility pass on all pages | 02, 03, 04 | ready-for-agent |
| 06 | Docs + reports | 05 | ready-for-agent |
