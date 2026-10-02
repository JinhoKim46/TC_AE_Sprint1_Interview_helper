"""Auth tests: password + TOTP login, recovery codes, lockout. Time is injected, never slept."""

from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from cryptography.fernet import Fernet
from sqlmodel import select

from interview_app import auth
from interview_app.config import AuthSettings
from interview_app.db import User, session_scope

T0 = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)
PASSWORD = "correct horse battery"
POLICY = AuthSettings()


@pytest.fixture
def cipher():
    return Fernet(Fernet.generate_key())


def code_at(secret: str, when: datetime) -> str:
    return pyotp.TOTP(secret).at(when)


def enrolled(engine, cipher, username="alex"):
    """Register and confirm a user; return the enrollment (holds the secret and recovery codes)."""
    enrollment = auth.start_registration(engine, cipher, username, PASSWORD, POLICY)
    assert auth.confirm_enrollment(engine, cipher, enrollment.user_id, code_at(enrollment.secret, T0), now=T0)
    return enrollment


def login(engine, cipher, code, *, password=PASSWORD, username="alex", now=T0):
    return auth.login(engine, cipher, username, password, code, POLICY, now=now)


# --- registration -----------------------------------------------------------


def test_password_policy():
    assert auth.password_problems("short", POLICY)
    assert auth.password_problems("x" * 11, POLICY)
    assert auth.password_problems(PASSWORD, POLICY) == []


def test_registration_rejects_weak_password(engine, cipher):
    with pytest.raises(auth.AuthError):
        auth.start_registration(engine, cipher, "alex", "short", POLICY)


def test_registration_closes_after_first_confirmed_user(engine, cipher):
    assert auth.registration_open(engine)
    enrolled(engine, cipher)
    assert not auth.registration_open(engine)
    with pytest.raises(auth.AuthError):
        auth.start_registration(engine, cipher, "second", PASSWORD, POLICY)


def test_abandoned_enrollment_can_be_restarted(engine, cipher):
    # Closing the browser before scanning the QR code must not lock the owner out forever.
    auth.start_registration(engine, cipher, "alex", PASSWORD, POLICY)
    assert auth.registration_open(engine)
    again = auth.start_registration(engine, cipher, "alex", PASSWORD, POLICY)
    with session_scope(engine) as s:
        assert len(s.exec(select(User)).all()) == 1
    assert again.user_id


def test_secrets_are_not_stored_in_plain_text(engine, cipher):
    enrollment = enrolled(engine, cipher)
    with session_scope(engine) as s:
        user = s.exec(select(User)).one()
    assert PASSWORD not in user.password_hash
    assert enrollment.secret not in user.totp_secret_enc
    assert len(enrollment.recovery_codes) == POLICY.recovery_code_count


def test_confirm_rejects_wrong_code(engine, cipher):
    enrollment = auth.start_registration(engine, cipher, "alex", PASSWORD, POLICY)
    assert not auth.confirm_enrollment(engine, cipher, enrollment.user_id, "000000", now=T0)
    assert auth.registration_open(engine)


def test_provisioning_uri_and_qr(engine, cipher):
    enrollment = auth.start_registration(engine, cipher, "alex", PASSWORD, POLICY)
    assert enrollment.provisioning_uri.startswith("otpauth://totp/")
    assert auth.qr_png(enrollment.provisioning_uri).startswith(b"\x89PNG")


# --- login ------------------------------------------------------------------


def test_login_with_password_and_totp(engine, cipher):
    e = enrolled(engine, cipher)
    result = login(engine, cipher, code_at(e.secret, T0 + timedelta(minutes=1)), now=T0 + timedelta(minutes=1))
    assert result.ok and result.user_id == e.user_id


def test_login_accepts_previous_time_step_for_clock_drift(engine, cipher):
    e = enrolled(engine, cipher)
    later = T0 + timedelta(minutes=5)
    assert login(engine, cipher, code_at(e.secret, later - timedelta(seconds=30)), now=later).ok


def test_totp_code_cannot_be_replayed(engine, cipher):
    e = enrolled(engine, cipher)
    later = T0 + timedelta(minutes=2)
    code = code_at(e.secret, later)
    assert login(engine, cipher, code, now=later).ok
    assert not login(engine, cipher, code, now=later + timedelta(seconds=5)).ok


def test_wrong_password_and_wrong_code_get_the_same_message(engine, cipher):
    e = enrolled(engine, cipher)
    later = T0 + timedelta(minutes=1)
    bad_password = login(engine, cipher, code_at(e.secret, later), password="wrong password!!", now=later)
    bad_code = login(engine, cipher, "123456", now=later)
    unknown_user = login(engine, cipher, "123456", username="nobody", now=later)
    # Don't reveal which factor was wrong, or whether the username exists.
    assert not bad_password.ok and not bad_code.ok and not unknown_user.ok
    assert bad_password.message == bad_code.message == unknown_user.message


def test_lockout_after_max_failed_attempts(engine, cipher):
    e = enrolled(engine, cipher)
    now = T0 + timedelta(minutes=1)
    for _ in range(POLICY.max_failed_attempts):
        assert not login(engine, cipher, "000000", now=now).ok

    # Even the right code is refused while locked.
    locked = login(engine, cipher, code_at(e.secret, now), now=now)
    assert not locked.ok and "locked" in locked.message.lower()

    after = now + timedelta(minutes=POLICY.lockout_minutes, seconds=1)
    assert login(engine, cipher, code_at(e.secret, after), now=after).ok


def test_successful_login_resets_failed_attempts(engine, cipher):
    e = enrolled(engine, cipher)
    now = T0 + timedelta(minutes=1)
    for _ in range(POLICY.max_failed_attempts - 1):
        login(engine, cipher, "000000", now=now)
    assert login(engine, cipher, code_at(e.secret, now), now=now).ok
    later = now + timedelta(minutes=1)
    login(engine, cipher, "000000", now=later)
    assert login(engine, cipher, code_at(e.secret, later + timedelta(seconds=30)), now=later + timedelta(seconds=30)).ok


def test_recovery_code_works_once(engine, cipher):
    e = enrolled(engine, cipher)
    code = e.recovery_codes[0]
    first = login(engine, cipher, code)
    assert first.ok and first.used_recovery_code
    assert not login(engine, cipher, code).ok
    assert login(engine, cipher, e.recovery_codes[1].upper()).ok  # case and spacing don't matter


def test_unconfirmed_user_cannot_log_in(engine, cipher):
    enrollment = auth.start_registration(engine, cipher, "alex", PASSWORD, POLICY)
    assert not login(engine, cipher, code_at(enrollment.secret, T0)).ok


def test_wrong_secret_key_fails_clearly(engine, cipher):
    e = enrolled(engine, cipher)
    other = Fernet(Fernet.generate_key())
    with pytest.raises(auth.AuthError):
        auth.login(engine, other, "alex", PASSWORD, code_at(e.secret, T0), POLICY, now=T0)


# --- helpers ----------------------------------------------------------------


def test_make_cipher_requires_a_valid_key():
    with pytest.raises(auth.AuthError):
        auth.make_cipher("")
    with pytest.raises(auth.AuthError):
        auth.make_cipher("not-a-fernet-key")
    assert auth.make_cipher(Fernet.generate_key().decode())


def test_session_idle_timeout():
    assert not auth.session_expired(T0, T0 + timedelta(minutes=29), POLICY)
    assert auth.session_expired(T0, T0 + timedelta(minutes=31), POLICY)
