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


def test_register_without_email_confirmation_uses_local_store(
    fake, monkeypatch, tmp_path
):
    monkeypatch.setenv("POLYFUSION_REQUIRE_EMAIL_CONFIRMATION", "0")
    monkeypatch.setenv("POLYFUSION_LOCAL_AUTH_DB", str(tmp_path / "auth.sqlite3"))

    result = auth.register(
        "localuser",
        "local@example.com",
        "password1",
        "password1",
        affiliation="ASIPP",
    )

    assert result["email_verification_sent"] is False
    assert result["auth_provider"] == "local"
    assert "local@example.com" not in fake.auth.users

    access, refresh, user = auth.login("local@example.com", "password1")
    assert access
    assert refresh.startswith("local-")
    assert user["username"] == "localuser"
    assert user["affiliation"] == "ASIPP"
    assert user["auth_provider"] == "local"
    assert auth.validate_session(access) == result["user_id"]
    assert auth.get_user(access)["email"] == "local@example.com"


def test_register_puts_username_into_options_data(fake):
    auth.register("alice", "alice@example.com", "password1", "password1")
    rec = fake.auth.users["alice@example.com"]
    assert rec["username"] == "alice"


def test_register_puts_affiliation_into_options_data(fake):
    auth.register(
        "alice",
        "alice@example.com",
        "password1",
        "password1",
        affiliation="ASIPP",
    )
    rec = fake.auth.users["alice@example.com"]
    assert rec["affiliation"] == "ASIPP"


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
    auth.register(
        "alice",
        "alice@example.com",
        "password1",
        "password1",
        affiliation="ASIPP",
    )
    fake.auth.users["alice@example.com"]["is_admin"] = True
    access, refresh, user = auth.login("alice@example.com", "password1")
    assert access
    assert refresh
    assert user["username"] == "alice"
    assert user["email"] == "alice@example.com"
    assert user["email_verified"] is False
    assert user["user_id"]
    assert user["affiliation"] == "ASIPP"
    assert user["is_admin"] is False


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


def test_verify_jwt_accepts_es256_supabase_token(monkeypatch):
    """Regression: real Supabase projects publish ES256 (EC P-256) JWKS keys,
    not RS256. ``verify_jwt`` must accept ES256-signed tokens — the prior
    RS256-only whitelist silently rejected every Supabase-issued access token,
    which presented as "every protected API returns 401 / redirects to login".

    The autouse fixture sets ``POLYFUSION_TEST_JWT_SECRET`` (HS256 path) and
    patches ``_fetch_jwks`` to return no keys; this test undoes both so the
    real JWKS+algorithm code path actually runs.
    """
    import time as _time
    from base64 import urlsafe_b64encode

    import jwt as _pyjwt
    from cryptography.hazmat.primitives.asymmetric import ec

    monkeypatch.delenv(auth._TEST_SECRET_ENV, raising=False)

    priv = ec.generate_private_key(ec.SECP256R1())
    pub_numbers = priv.public_key().public_numbers()

    def _b64u(n: int) -> str:
        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

    kid = "regression-es256-kid"
    jwk = {
        "kid": kid,
        "kty": "EC",
        "alg": "ES256",
        "crv": "P-256",
        "x": _b64u(pub_numbers.x),
        "y": _b64u(pub_numbers.y),
    }
    monkeypatch.setattr(auth, "_fetch_jwks", lambda: {"keys": [jwk]})

    token = _pyjwt.encode(
        {"sub": "user-es256", "exp": int(_time.time()) + 3600},
        priv,
        algorithm="ES256",
        headers={"kid": kid},
    )

    claims = auth.verify_jwt(token)
    assert claims is not None, "ES256 token was rejected — algorithm whitelist?"
    assert claims["sub"] == "user-es256"


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


# ---------------------------------------------------------------------------
# SMTP verification path (POLYFUSION_REQUIRE_EMAIL_CONFIRMATION=1 + SMTP on)
# ---------------------------------------------------------------------------


def _smtp_env(monkeypatch, tmp_path):
    """Activate the SMTP verification path with a fresh local DB."""
    monkeypatch.setenv("POLYFUSION_REQUIRE_EMAIL_CONFIRMATION", "1")
    monkeypatch.setenv("POLYFUSION_SMTP_ENABLED", "1")
    monkeypatch.setenv("POLYFUSION_LOCAL_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://vsc.example.cn")
    monkeypatch.setenv("POLYFUSION_SMTP_HOST", "smtp.example.cn")
    monkeypatch.setenv("POLYFUSION_SMTP_PORT", "465")
    monkeypatch.setenv("POLYFUSION_SMTP_USER", "veloalpha@mail.example.cn")
    monkeypatch.setenv("POLYFUSION_SMTP_PASSWORD", "test-pwd")


def test_smtp_register_sends_email_and_leaves_unverified(fake, monkeypatch, tmp_path):
    _smtp_env(monkeypatch, tmp_path)
    captured = []

    def stub_sender(to_email, verify_url, **kwargs):
        captured.append((to_email, verify_url))

    monkeypatch.setattr(auth.email_send, "send_verification_email", stub_sender)

    result = auth.register("bob", "bob@example.com", "password1", "password1")

    assert result["email_verification_sent"] is True
    assert len(captured) == 1
    assert captured[0][0] == "bob@example.com"
    assert "token=" in captured[0][1]
    assert "vsc.example.cn" in captured[0][1]
    # The new row must start unverified.
    with auth._local_conn() as conn:
        row = conn.execute(
            "SELECT email_verified FROM local_users WHERE email = ?",
            ("bob@example.com",),
        ).fetchone()
    assert dict(row)["email_verified"] == 0


def test_smtp_register_rolls_back_on_email_failure(fake, monkeypatch, tmp_path):
    _smtp_env(monkeypatch, tmp_path)

    def raising_sender(*args, **kwargs):
        raise auth.email_send.EmailSendError("smtp boom")

    monkeypatch.setattr(auth.email_send, "send_verification_email", raising_sender)

    with pytest.raises(auth.AuthError):
        auth.register("carol", "carol@example.com", "password1", "password1")

    # No orphan row should remain.
    with auth._local_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM local_users WHERE email = ?",
            ("carol@example.com",),
        ).fetchone()
    assert row is None


def test_smtp_verify_email_token_success_flips_flag(fake, monkeypatch, tmp_path):
    _smtp_env(monkeypatch, tmp_path)
    issued = []

    def capture(to_email, verify_url, **kwargs):
        issued.append(verify_url)

    monkeypatch.setattr(auth.email_send, "send_verification_email", capture)
    auth.register("dave", "dave@example.com", "password1", "password1")
    token = issued[0].split("token=", 1)[1]

    result = auth.verify_email_token(token)

    assert result["ok"] is True
    assert result["reason"] == "success"
    with auth._local_conn() as conn:
        row = conn.execute(
            "SELECT email_verified, verify_token_jti FROM local_users WHERE email = ?",
            ("dave@example.com",),
        ).fetchone()
    rec = dict(row)
    assert rec["email_verified"] == 1
    assert rec["verify_token_jti"] is None


def test_smtp_verify_email_token_already_verified(fake, monkeypatch, tmp_path):
    _smtp_env(monkeypatch, tmp_path)
    issued = []

    def capture(to_email, verify_url, **kwargs):
        issued.append(verify_url)

    monkeypatch.setattr(auth.email_send, "send_verification_email", capture)
    auth.register("erin", "erin@example.com", "password1", "password1")
    token = issued[0].split("token=", 1)[1]
    first = auth.verify_email_token(token)
    second = auth.verify_email_token(token)
    assert first["reason"] == "success"
    assert second["reason"] == "already_verified"
    assert second["ok"] is True


def test_smtp_verify_email_token_expired(fake, monkeypatch, tmp_path):
    _smtp_env(monkeypatch, tmp_path)
    issued = []

    def capture(to_email, verify_url, **kwargs):
        issued.append(verify_url)

    monkeypatch.setattr(auth.email_send, "send_verification_email", capture)
    auth.register("frank", "frank@example.com", "password1", "password1")

    # Backdate the issued token by minting an expired one with the same jti.
    with auth._local_conn() as conn:
        row = auth._local_row_by_email(conn, "frank@example.com")
        jti = row["verify_token_jti"]
        now = int(time.time())
        expired_token = pyjwt.encode(
            {
                "iss": auth._LOCAL_VERIFY_ISSUER,
                "provider": auth._LOCAL_VERIFY_PROVIDER,
                "sub": row["user_id"],
                "email": "frank@example.com",
                "jti": jti,
                "purpose": "verify-email",
                "iat": now - 2 * auth._LOCAL_VERIFY_TTL,
                "exp": now - auth._LOCAL_VERIFY_TTL,
            },
            auth._local_secret(conn),
            algorithm="HS256",
        )

    result = auth.verify_email_token(expired_token)
    assert result["ok"] is False
    assert result["reason"] == "expired"
    with auth._local_conn() as conn:
        row = conn.execute(
            "SELECT email_verified FROM local_users WHERE email = ?",
            ("frank@example.com",),
        ).fetchone()
    assert dict(row)["email_verified"] == 0


def test_smtp_verify_email_token_purpose_mismatch_rejected(fake, monkeypatch, tmp_path):
    _smtp_env(monkeypatch, tmp_path)
    # Mint a SESSION token (provider=local, not local-verify) and try to use
    # it as a verify token — must be rejected.
    with auth._local_conn() as conn:
        secret = auth._local_secret(conn)
    session_token = pyjwt.encode(
        {
            "iss": auth._LOCAL_AUTH_ISSUER,
            "provider": "local",
            "sub": "local-whatever",
            "email": "x@example.com",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        },
        secret,
        algorithm="HS256",
    )
    result = auth.verify_email_token(session_token)
    assert result["ok"] is False
    assert result["reason"] == "invalid"


def test_smtp_login_unverified_user_returns_session_marked_unverified(
    fake, monkeypatch, tmp_path
):
    _smtp_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        auth.email_send,
        "send_verification_email",
        lambda *a, **k: None,
    )
    auth.register("grace", "grace@example.com", "password1", "password1")
    access, refresh, user = auth.login("grace@example.com", "password1")
    assert access
    assert user["email_verified"] is False


def test_smtp_resend_verification_is_noop_for_missing_user(fake, monkeypatch, tmp_path):
    _smtp_env(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(
        auth.email_send,
        "send_verification_email",
        lambda *a, **k: sent.append(a),
    )
    # Missing user — must not raise, must not send.
    auth.resend_verification("nobody@example.com")
    assert sent == []


def test_smtp_request_password_reset_sends_one_hour_link(fake, monkeypatch, tmp_path):
    _smtp_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        auth.email_send, "send_verification_email", lambda *a, **k: None
    )
    auth.register("resetuser", "reset@example.com", "password1", "password1")
    sent = []

    def capture(to_email, reset_url, **kwargs):
        sent.append((to_email, reset_url))

    monkeypatch.setattr(auth.email_send, "send_password_reset_email", capture)

    auth.request_password_reset("reset@example.com")

    assert sent
    assert sent[0][0] == "reset@example.com"
    assert "/vsc/?reset_token=" in sent[0][1]
    token = sent[0][1].split("reset_token=", 1)[1]
    claims = pyjwt.decode(token, options={"verify_signature": False})
    assert claims["provider"] == auth._LOCAL_RESET_PROVIDER
    assert claims["purpose"] == "reset-password"
    assert claims["exp"] - claims["iat"] == auth._LOCAL_RESET_TTL


def test_smtp_reset_password_token_updates_password(fake, monkeypatch, tmp_path):
    _smtp_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        auth.email_send, "send_verification_email", lambda *a, **k: None
    )
    auth.register("resetok", "resetok@example.com", "password1", "password1")
    sent = []
    monkeypatch.setattr(
        auth.email_send,
        "send_password_reset_email",
        lambda to_email, reset_url, **kwargs: sent.append(reset_url),
    )
    auth.request_password_reset("resetok@example.com")
    token = sent[0].split("reset_token=", 1)[1]

    result = auth.reset_password(token, "newpass1", "newpass1")

    assert result["ok"] is True
    with pytest.raises(auth.AuthError, match="invalid credentials"):
        auth.login("resetok@example.com", "password1")
    access, _, user = auth.login("resetok@example.com", "newpass1")
    assert access
    assert user["email"] == "resetok@example.com"
    with auth._local_conn() as conn:
        row = auth._local_row_by_email(conn, "resetok@example.com")
    assert row["reset_token_jti"] is None


def test_smtp_reset_password_expired_token_rejected(fake, monkeypatch, tmp_path):
    _smtp_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        auth.email_send, "send_verification_email", lambda *a, **k: None
    )
    auth.register("resetexp", "resetexp@example.com", "password1", "password1")
    with auth._local_conn() as conn:
        row = auth._local_row_by_email(conn, "resetexp@example.com")
        token = auth._local_issue_password_reset_token(conn, row)
        claims = pyjwt.decode(token, options={"verify_signature": False})
        expired = pyjwt.encode(
            {**claims, "iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600},
            auth._local_secret(conn),
            algorithm="HS256",
        )

    with pytest.raises(auth.AuthError, match="reset link expired"):
        auth.reset_password(expired, "newpass1", "newpass1")
    auth.login("resetexp@example.com", "password1")


def test_smtp_change_password_requires_current_password(fake, monkeypatch, tmp_path):
    _smtp_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        auth.email_send, "send_verification_email", lambda *a, **k: None
    )
    auth.register("changeuser", "change@example.com", "password1", "password1")
    access, _, _ = auth.login("change@example.com", "password1")

    with pytest.raises(auth.AuthError, match="invalid credentials"):
        auth.change_password(access, "wrongpass", "newpass1", "newpass1")

    assert auth.change_password(access, "password1", "newpass1", "newpass1") == {
        "ok": True
    }
    with pytest.raises(auth.AuthError, match="invalid credentials"):
        auth.login("change@example.com", "password1")
    auth.login("change@example.com", "newpass1")
