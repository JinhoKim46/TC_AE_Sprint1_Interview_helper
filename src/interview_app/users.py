"""The local user.

The app is single-user and runs on the owner's machine, so for now there is no login: everything
belongs to one built-in "local" user. Tables still carry `user_id`, so real accounts (the parked
MFA work, draft PR #4) can be added later without migrating data.
"""

from sqlalchemy.engine import Engine
from sqlmodel import select

from interview_app.db import User, session_scope

LOCAL_USERNAME = "local"


def ensure_local_user(engine: Engine) -> int:
    """Return the local user's id, creating the user on first run."""
    with session_scope(engine) as s:
        user = s.exec(select(User).where(User.username == LOCAL_USERNAME)).first()
        if user is None:
            # "!" is not a valid hash, so nobody can ever log in as this user with a password.
            user = User(username=LOCAL_USERNAME, password_hash="!", totp_secret_enc="")
            s.add(user)
            s.flush()
        return user.id
