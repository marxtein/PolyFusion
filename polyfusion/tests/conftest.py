"""Shared pytest fixtures for the PolyFusion test suite.

Provides an in-memory ``FakeSupabase`` so the auth unit tests and (Phase 3)
HTTP auth tests can drive ``polyfusion.auth`` without hitting the network.

The fake issues real pyjwt-signed HS256 tokens; ``polyfusion.auth.verify_jwt``
honors the ``POLYFUSION_TEST_JWT_SECRET`` environment variable to decode those
tokens, which is how local JWT verification is exercised in tests.
"""

from __future__ import annotations

import os
import sys
import time
import uuid

import jwt as pyjwt
import pytest
from supabase_auth.errors import AuthApiError, AuthRetryableError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion import auth  # noqa: E402

# Capture the unpatched implementation before any test monkeypatches the
# module-level symbol. ``test_auth.py`` uses this to exercise the missing-env
# error path directly.
_ORIGINAL_SUPABASE_CLIENT = auth.supabase_client

TEST_JWT_SECRET = "polyfusion-test-secret-32bytes-or-more-0123456789"


class FakeAuthApiError(AuthApiError):
    """In-test stand-in for ``supabase_auth.errors.AuthApiError``.

    Subclasses the real error so ``auth._translate_supabase_error``'s
    ``isinstance`` checks fire correctly. The real constructor signature is
    ``(message, status, code)``; we expose the more readable
    ``(message, code=..., status=...)`` and forward in the right order.
    """

    def __init__(self, message: str, code=None, status: int = 400):
        super().__init__(message, status, code)
        # Real AuthApiError already sets self.code / self.message / self.status.


class FakeAuthRetryableError(AuthRetryableError):
    """Mimics ``AuthRetryableError`` (network/5xx).

    Inherits from the real ``AuthRetryableError`` so ``isinstance`` checks in
    ``auth._translate_supabase_error`` fire. ``AuthRetryableError.__init__``
    takes ``(message, status)``; ``code`` is accepted and ignored for
    call-site convenience.
    """

    def __init__(self, message: str, code=None, status: int = 500):
        super().__init__(message, status)


class _AttrBag:
    """Generic attribute bag used to mimic Supabase response/User/Session."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeSupabaseAuth:
    """In-memory stand-in for the SyncSupabaseAuthClient.

    Stores users keyed by email. ``sign_up`` returns an object exposing
    ``.user`` (with ``id``, ``email``, ``user_metadata``, ``email_confirmed_at``,
    ``confirmation_sent_at``) and ``.session`` (with ``access_token`` /
    ``refresh_token``) — matching the real ``AuthResponse`` shape.
    """

    def __init__(self):
        self.users: dict[str, dict] = {}
        # Records of calls for assertions.
        self.resend_calls: list[dict] = []
        self.sign_out_calls: list[str] = []
        self.refresh_calls: list[str] = []
        # If True, the next sign_up behaves as if "Confirm email" is ON.
        self.confirm_email_on = True
        # If set, the next call raises this exception.
        self.next_error: FakeAuthApiError | None = None

    # -- helpers --------------------------------------------------------
    def _mint_session(self, user_id: str, email: str) -> _AttrBag:
        access = self._mint_jwt(user_id, email=email)
        refresh = f"refresh-{uuid.uuid4().hex}"
        return _AttrBag(access_token=access, refresh_token=refresh, expires_in=3600)

    @staticmethod
    def _mint_jwt(user_id: str, *, email: str | None = None, exp_in: int = 3600) -> str:
        payload = {
            "sub": user_id,
            "exp": int(time.time()) + exp_in,
            "iat": int(time.time()),
            "email": email if email is not None else f"{user_id}@example.com",
        }
        return pyjwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")

    def _user_bag(self, rec: dict, *, confirm_sent: bool) -> _AttrBag:
        return _AttrBag(
            id=rec["user_id"],
            email=rec["email"],
            user_metadata={
                "username": rec["username"],
                "affiliation": rec.get("affiliation"),
                "is_admin": rec.get("is_admin", False),
            },
            email_confirmed_at=rec.get("email_confirmed_at"),
            confirmation_sent_at=rec.get("confirmation_sent_at"),
        )

    # -- public API mirroring supabase-py ------------------------------
    def sign_up(self, credentials: dict) -> _AttrBag:
        if self.next_error is not None:
            err = self.next_error
            self.next_error = None
            raise err
        email = credentials["email"]
        password = credentials["password"]
        options = credentials.get("options") or {}
        data = options.get("data") or {}
        username = data.get("username")
        if email in self.users:
            raise FakeAuthApiError(
                "User already registered", code="user_already_exists", status=400
            )
        user_id = str(uuid.uuid4())
        confirmation_sent_at = time.time() if self.confirm_email_on else None
        rec = {
            "user_id": user_id,
            "email": email,
            "username": username,
            "affiliation": data.get("affiliation"),
            "is_admin": bool(data.get("is_admin")),
            "password": password,
            "email_confirmed_at": None,
            "confirmation_sent_at": confirmation_sent_at,
        }
        self.users[email] = rec
        user = self._user_bag(rec, confirm_sent=bool(confirmation_sent_at))
        # When Confirm email is ON, Supabase does not return a session.
        session = None if self.confirm_email_on else self._mint_session(user_id, email)
        return _AttrBag(user=user, session=session)

    def sign_in_with_password(self, credentials: dict) -> _AttrBag:
        if self.next_error is not None:
            err = self.next_error
            self.next_error = None
            raise err
        email = credentials["email"]
        password = credentials["password"]
        rec = self.users.get(email)
        if rec is None or rec["password"] != password:
            raise FakeAuthApiError(
                "Invalid credentials", code="invalid_credentials", status=400
            )
        user = self._user_bag(rec, confirm_sent=False)
        session = self._mint_session(rec["user_id"], email)
        return _AttrBag(user=user, session=session)

    def get_user(self, jwt: str | None = None):  # noqa: A002 (mirror SDK name)
        if not jwt:
            return None
        try:
            claims = pyjwt.decode(
                jwt,
                TEST_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        except Exception:
            return None
        email = claims.get("email")
        rec = self.users.get(email) if email else None
        if rec is None:
            return None
        return _AttrBag(user=self._user_bag(rec, confirm_sent=False))

    def sign_out(self, access_token: str | None = None) -> None:
        self.sign_out_calls.append(access_token or "")
        return None

    def refresh_session(self, refresh_token: str | None = None) -> _AttrBag:
        self.refresh_calls.append(refresh_token or "")
        # Mint a fresh session for some user; details don't matter to callers.
        if self.users:
            rec = next(iter(self.users.values()))
            session = self._mint_session(rec["user_id"], rec["email"])
            user = self._user_bag(rec, confirm_sent=False)
            return _AttrBag(user=user, session=session)
        raise FakeAuthApiError("no users", status=400)

    def resend(self, credentials: dict) -> _AttrBag:
        if self.next_error is not None:
            err = self.next_error
            self.next_error = None
            raise err
        self.resend_calls.append(
            {"email": credentials.get("email"), "type": credentials.get("type")}
        )
        return _AttrBag()

    def reset_password_for_email(self, email: str, options=None) -> None:
        return None


class FakeSupabase:
    def __init__(self):
        self.auth = FakeSupabaseAuth()


@pytest.fixture(autouse=True)
def _fake_supabase(monkeypatch, tmp_path):
    """Auto-injected fake client + HS256 test-secret for every test.

    Tests that need to assert on the fake's stored users should add
    ``fake`` as an explicit argument to receive this fixture's value.
    """
    fake = FakeSupabase()
    monkeypatch.setattr(auth, "supabase_client", lambda: fake)
    monkeypatch.setattr(auth, "_fetch_jwks", lambda: {"keys": []})
    monkeypatch.setenv(auth._TEST_SECRET_ENV, TEST_JWT_SECRET)
    monkeypatch.setenv(auth._EMAIL_CONFIRM_ENV, "1")
    # SMTP path must be explicitly opted-in per test; otherwise .env leakage
    # would route register/login through the local SQLite+SMTP branch and
    # break every Supabase-path test.
    monkeypatch.setenv("POLYFUSION_SMTP_ENABLED", "0")
    monkeypatch.setenv("POLYFUSION_HISTORY_DB", str(tmp_path / "history.sqlite3"))
    auth.reset_supabase_client_for_tests(fake)
    yield fake
    # Restore a clean module-level client so other tests rebuild it.
    auth.reset_supabase_client_for_tests(None)


@pytest.fixture
def fake(_fake_supabase) -> FakeSupabase:
    """Explicit alias for tests that want to inspect/steer the fake."""
    return _fake_supabase
