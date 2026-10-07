---
status: accepted
date: 2026-10-02
---

# A local single-user app on SQLite, with no login but a `user_id` on every row

The app holds real CVs and cover letters, has one user, and runs on that user's machine. So it binds to `127.0.0.1` only, stores everything in a local SQLite file through SQLModel (owner-only file mode, `secure_delete`), and runs as one built-in local user (`users.LOCAL_USERNAME`) with no login. Every owned table still carries a `user_id`, so a multi-user version needs authentication and a database URL, not a schema rewrite.

## Considered Options

- **Supabase (hosted Postgres + auth)** from the brainstorm: rejected because real CVs should not leave the machine, and hosting adds cost and setup for one user.
- **Local password + TOTP MFA:** designed and specified as tests in PR #4, then parked (closed unmerged). It was not graded, and on a localhost-only app a login protects little against someone who already has the machine.

## Consequences

- Anyone with access to the computer (or the `data/` folder) can see the data; there is no encryption at rest beyond the OS.
- Only one interview can be active at a time, which keeps the state rules simple.
- Moving to several users means: revive the PR #4 auth, switch the database URL to Postgres, and check that every query filters by `user_id` (they already do).
