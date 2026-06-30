"""Unit tests for polyfusion.auth (Supabase adapter).

The conftest auto-injects a FakeSupabase client and an HS256 test secret so
``verify_jwt`` can be exercised end-to-end without an asymmetric keypair.
"""

from __future__ import annotations

import os
import sys
import time

import jwt as pyjwt
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion import auth  # noqa: E402
from polyfusion.tests.conftest import (  # noqa: E402
    FakeAuthApiError,
    FakeAuthRetryableError,
    TEST_JWT_SECRET,
    _ORIGINAL_SUPABASE_CLIENT,
)


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


def test_register_success_returns_dict_with_username(fake):
    result = auth.register("alice", "alice@example.com", "password1", "password1")
    assert result["username"] == "alice"
    assert result["email"] == "alice@example.com"
    assert result["user_id"]
    assert isinstance(result["email_verification_sent"], bool)


def test_register_sets_email_verification_sent_when_confirm_on(fake):
    fake.auth.confirm_email_on = True
    result = auth.register("alice", "alice@example.com", "password1", "password1")
    assert result["email_verification_sent"] is True


def test_register_no_verification_sent_when_confirm_off(fake):
    fake.auth.confirm_email_on = False
    result = auth.register("alice", "alice@example.com", "password1", "password1")
    assert result["email_verification_sent"] is False


def test_register_puts_username_into_options_data(fake):
    auth.register("alice", "alice@example.com", "password1", "password1")
    rec = fake.auth.users["alice@example.com"]
    assert rec["username"] == "alice"


def test_register_rejects_password_mismatch(fake):
    with pytest.raises(auth.AuthError, match="password"):
        auth.register("alice", "alice@example.com", "password1", "different")


def test_register_rejects_invalid_email(fake):
    with pytest.raises(auth.AuthError):
        auth.register("alice", "not-an-email", "password1", "password1")


def test_register_rejects_short_password(fake):
    with pytest.raises(auth.AuthError):
        auth.register("alice", "alice@example.com", "short", "short")


def test_register_rejects_bad_username(fake):
    with pytest.raises(auth.AuthError):
        auth.register("ab", "alice@example.com", "password1", "password1")


def test_register_translates_already_registered_to_generic_error(fake):
    auth.register("alice", "alice@example.com", "password1", "password1")
    with pytest.raises(auth.AuthError) as exc_info:
        auth.register("alice2", "alice@example.com", "password1", "password1")
    msg = str(exc_info.value).lower()
    # Anti-enumeration: must NOT leak which field collided.
    assert "username" not in msg
    assert "email" not in msg
    assert "registration failed" in msg or "already" not in msg


def test_register_translates_code_user_already_exists(fake):
    # First user, then attempt again with the trigger-style error.
    auth.register("alice", "alice@example.com", "password1", "password1")
    fake.auth.next_error = FakeAuthApiError(
        "User already registered", code="user_already_exists", status=400
    )
    with pytest.raises(auth.AuthError) as exc_info:
        auth.register("alice2", "alice2@example.com", "password1", "password1")
    assert "registration failed" in str(exc_info.value).lower()


def test_register_translates_message_already_been_registered(fake):
    fake.auth.next_error = FakeAuthApiError(
        "For security purposes, you can only request this after 1 second.",
        code="user_already_exists",
        status=400,
    )
    # Different message variant to confirm the message-branch check works.
    fake.auth.next_error = FakeAuthApiError(
        "User already been registered", code="weak_password", status=400
    )
    with pytest.raises(auth.AuthError) as exc_info:
        auth.register("alice", "alice@example.com", "password1", "password1")
    assert "registration failed" in str(exc_info.value).lower()


def test_register_translates_retryable_error(fake):
    fake.auth.next_error = FakeAuthRetryableError(
        "timeout", code="over_request_rate_limit", status=500
    )
    with pytest.raises(auth.AuthError, match="service unavailable"):
        auth.register("alice", "alice@example.com", "password1", "password1")


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


def test_login_returns_tokens_and_user_dict(fake):
    fake.auth.confirm_email_on = False
    auth.register("alice", "alice@example.com", "password1", "password1")
    access, refresh, user = auth.login("alice@example.com", "password1")
    assert access
    assert refresh
    assert user["username"] == "alice"
    assert user["email"] == "alice@example.com"
    assert user["email_verified"] is False
    assert user["user_id"]


def test_login_invalid_credentials_raises(fake):
    fake.auth.confirm_email_on = False
    auth.register("alice", "alice@example.com", "password1", "password1")
    with pytest.raises(auth.AuthError):
        auth.login("alice@example.com", "wrong")


def test_login_retryable_error_is_service_unavailable(fake):
    fake.auth.next_error = FakeAuthRetryableError("net", status=503)
    with pytest.raises(auth.AuthError, match="service unavailable"):
        auth.login("alice@example.com", "password1")


# ---------------------------------------------------------------------------
# validate_session (local JWT verification)
# ---------------------------------------------------------------------------


def _make_token(secret: str, sub: str = "user-123", exp_in: int = 3600) -> str:
    payload = {"sub": sub, "exp": int(time.time()) + exp_in, "iat": int(time.time())}
    return pyjwt.encode(payload, secret, algorithm="HS256")


def test_validate_session_returns_sub_on_valid_jwt(fake):
    token = _make_token(TEST_JWT_SECRET)
    assert auth.validate_session(token) == "user-123"


def test_validate_session_none_on_missing_token(fake):
    assert auth.validate_session(None) is None
    assert auth.validate_session("") is None


def test_validate_session_none_on_invalid_token(fake):
    assert auth.validate_session("garbage.payload.here") is None


def test_validate_session_none_on_wrong_signature(fake, monkeypatch):
    token = _make_token("some-other-secret-at-least-32-bytes-long")
    assert auth.validate_session(token) is None


def test_validate_session_none_on_expired(fake):
    # exp in the past -> verify_jwt returns None.
    payload = {"sub": "user-123", "exp": int(time.time()) - 10}
    token = pyjwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")
    assert auth.validate_session(token) is None


def test_validate_session_refreshes_when_near_expiry(fake):
    # Expiring in 60s (within the 5-minute window) + refresh token present.
    token = _make_token(TEST_JWT_SECRET, exp_in=60)
    assert auth.validate_session(token, refresh_token="r-1") == "user-123"
    assert fake.auth.refresh_calls == ["r-1"]


def test_validate_session_no_refresh_near_expiry_still_returns_sub(fake):
    # Valid token even when near expiry; refresh simply not attempted.
    token = _make_token(TEST_JWT_SECRET, exp_in=60)
    assert auth.validate_session(token) == "user-123"
    assert fake.auth.refresh_calls == []


def test_validate_session_far_from_expiry_does_not_refresh(fake):
    token = _make_token(TEST_JWT_SECRET, exp_in=3600)
    assert auth.validate_session(token, refresh_token="r-1") == "user-123"
    assert fake.auth.refresh_calls == []


# ---------------------------------------------------------------------------
# logout / get_user / resend
# ---------------------------------------------------------------------------


def test_logout_calls_sign_out(fake):
    fake.auth.confirm_email_on = False
    auth.register("alice", "alice@example.com", "password1", "password1")
    access, refresh, _u = auth.login("alice@example.com", "password1")
    auth.logout(access, refresh)
    assert fake.auth.sign_out_calls == [access]


def test_logout_swallows_network_errors(fake):
    # Inject a client whose auth.sign_out always raises.
    class BadAuth:
        def sign_out(self, token):
            raise RuntimeError("boom")

    class BadClient:
        def __init__(self):
            self.auth = BadAuth()

    auth.reset_supabase_client_for_tests(BadClient())
    # Should not raise.
    auth.logout("some-access", "some-refresh")
    auth.reset_supabase_client_for_tests(fake)


def test_logout_noop_without_token(fake):
    auth.logout(None, None)
    assert fake.auth.sign_out_calls == []


def test_get_user_returns_dict_for_valid_token(fake):
    fake.auth.confirm_email_on = False
    auth.register("alice", "alice@example.com", "password1", "password1")
    access, _r, expected = auth.login("alice@example.com", "password1")
    got = auth.get_user(access)
    assert got is not None
    assert got["username"] == expected["username"]
    assert got["email"] == expected["email"]
    assert got["user_id"] == expected["user_id"]


def test_get_user_none_for_missing_token(fake):
    assert auth.get_user(None) is None
    assert auth.get_user("") is None


def test_get_user_none_for_garbage_token(fake):
    assert auth.get_user("not.a.jwt") is None


def test_resend_verification_calls_supabase(fake):
    auth.resend_verification("alice@example.com")
    assert fake.auth.resend_calls == [{"email": "alice@example.com", "type": "signup"}]


def test_resend_verification_rejects_bad_email(fake):
    with pytest.raises(auth.AuthError):
        auth.resend_verification("not-an-email")


def test_resend_verification_translates_retryable(fake):
    fake.auth.next_error = FakeAuthRetryableError("net", status=503)
    with pytest.raises(auth.AuthError, match="service unavailable"):
        auth.resend_verification("alice@example.com")


# ---------------------------------------------------------------------------
# supabase_client configuration
# ---------------------------------------------------------------------------


def test_supabase_client_raises_when_url_missing(monkeypatch):
    """The real ``supabase_client`` raises AuthError without env config."""
    # The autouse fixture patches the module-level symbol with a lambda; call
    # the original implementation captured at conftest import time instead.
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    auth.reset_supabase_client_for_tests(None)
    with pytest.raises(auth.AuthError):
        _ORIGINAL_SUPABASE_CLIENT()
    auth.reset_supabase_client_for_tests(None)


def test_supabase_client_raises_when_key_missing(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    auth.reset_supabase_client_for_tests(None)
    with pytest.raises(auth.AuthError):
        _ORIGINAL_SUPABASE_CLIENT()
    auth.reset_supabase_client_for_tests(None)


# ---------------------------------------------------------------------------
# parse_session_cookie (now JWT-tolerant)
# ---------------------------------------------------------------------------


def test_parse_session_cookie_jwt_shape():
    token = _make_token(TEST_JWT_SECRET)
    assert auth.parse_session_cookie(f"polyfusion_session={token}") == token


def test_parse_session_cookie_none_when_absent():
    assert auth.parse_session_cookie(None) is None
    assert auth.parse_session_cookie("") is None
    assert auth.parse_session_cookie("other=value") is None


def test_parse_session_cookie_rejects_garbage():
    assert auth.parse_session_cookie("polyfusion_session=<script>") is None
