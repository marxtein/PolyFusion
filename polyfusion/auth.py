"""User authentication and session management for PolyFusion.

This module is a thin adapter over Supabase Auth. Password hashing, email
verification, password reset and JWT issuance are all delegated to Supabase;
the local process stores no password material at all.

Public surface used by ``app/server.py``:
    - ``register(username, email, password, password2) -> dict``
    - ``login(email, password) -> (access_token, refresh_token, user_dict)``
    - ``logout(access_token, refresh_token) -> None``
    - ``get_user(access_token) -> dict | None``
    - ``resend_verification(email) -> None``
    - ``validate_session(access_token, refresh_token=None) -> str | None``
    - ``parse_session_cookie(cookie_header) -> str | None``

The web process only ever reads ``SUPABASE_URL`` and ``SUPABASE_ANON_KEY``.
The service-role key is never imported here; it lives exclusively in the
one-shot migration script.

JWT verification is performed locally (against the Supabase JWKS) so that
each authenticated request does not pay a network round-trip. A near-expiry
access token is refreshed transparently when a refresh token is available.

Test mode: when ``POLYFUSION_TEST_JWT_SECRET`` is set, ``verify_jwt`` decodes
HS256 tokens signed with that secret instead of consulting JWKS. This keeps
production code clean while letting the test suite (which uses ``pyjwt`` to
mint tokens) avoid the asymmetric-key machinery.
"""

from __future__ import annotations

import os
import re
import threading
import time
from email.utils import parseaddr
from typing import Optional

from supabase import Client, create_client
from supabase_auth.errors import AuthApiError, AuthRetryableError

# Optional dependency: only needed for local JWT verification in production.
try:  # pragma: no cover - exercised in tests via monkeypatched secret path
    import jwt as _pyjwt
except Exception:  # pragma: no cover - jwt is required at install time
    _pyjwt = None  # type: ignore[assignment]

try:  # pragma: no cover - httpx always ships with supabase
    import httpx as _httpx
except Exception:  # pragma: no cover
    _httpx = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants & validation helpers
# ---------------------------------------------------------------------------

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")
_MIN_PASSWORD_LEN = 8
MAX_EMAIL_LEN = 254
# Conservative regex: local-part + @ + domain with at least one dot in domain.
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

# Refresh when the access token has less than this many seconds left.
_REFRESH_WINDOW = 5 * 60

# Test-only: when set, verify_jwt decodes HS256 tokens with this secret.
_TEST_SECRET_ENV = "POLYFUSION_TEST_JWT_SECRET"


class AuthError(Exception):
    """Raised for all PolyFusion-side auth failures."""


def validate_username(name: str) -> str:
    if not isinstance(name, str):
        raise AuthError("username must be a string")
    name = name.strip()
    if not _USERNAME_RE.match(name):
        raise AuthError("username must be 3-32 chars of [a-zA-Z0-9_-]")
    return name


def validate_password(pw: str) -> None:
    if not isinstance(pw, str) or len(pw) < _MIN_PASSWORD_LEN:
        raise AuthError(f"password must be at least {_MIN_PASSWORD_LEN} characters")


def validate_email(email: str) -> str:
    """Validate and return the trimmed email string.

    Rejects empty values, null/control characters, over-long addresses, and
    addresses that fail ``email.utils.parseaddr`` plus a conservative syntax
    regex.
    """
    if not isinstance(email, str):
        raise AuthError("invalid email format")
    email = email.strip()
    if not email or len(email) > MAX_EMAIL_LEN:
        raise AuthError("invalid email format")
    if "\x00" in email or any(ord(ch) < 32 or ord(ch) == 127 for ch in email):
        raise AuthError("invalid email format")
    real_name, addr = parseaddr(email)
    if not addr or "@" not in addr:
        raise AuthError("invalid email format")
    if not _EMAIL_RE.match(addr):
        raise AuthError("invalid email format")
    return email


# ---------------------------------------------------------------------------
# Supabase client (lazy singleton)
# ---------------------------------------------------------------------------

_client: Optional[Client] = None
_client_lock = threading.Lock()


def supabase_client() -> Client:
    """Return the process-wide Supabase client, creating it on first use.

    Reads ``SUPABASE_URL`` and ``SUPABASE_ANON_KEY`` from the environment.
    Raises ``AuthError`` when either is missing.
    """
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        url = os.environ.get("SUPABASE_URL", "").strip()
        key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
        if not url or not key:
            raise AuthError("Supabase is not configured")
        try:
            _client = create_client(url, key)
        except Exception as exc:  # pragma: no cover - configuration error
            raise AuthError("service unavailable") from exc
        return _client


def reset_supabase_client_for_tests(client) -> None:
    """Inject a (fake) client; tests only."""
    global _client
    with _client_lock:
        _client = client


# ---------------------------------------------------------------------------
# JWT verification (local, JWKS-cached)
# ---------------------------------------------------------------------------

_JWKS_CACHE: dict[str, dict] = {}
_JWKS_LOCK = threading.Lock()


def _jwks_url() -> str:
    base = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    return f"{base}/auth/v1/.well-known/jwks.json"


def _fetch_jwks() -> dict:
    """Fetch the Supabase JWKS document with a thread-safe cache.

    Returns a dict shaped like ``{"keys": [ {kid, kty, ...}, ... ]}``.
    """
    with _JWKS_LOCK:
        if _JWKS_CACHE:
            return _JWKS_CACHE
        url = _jwks_url()
        try:
            if _httpx is None:  # pragma: no cover
                raise RuntimeError("httpx unavailable")
            resp = _httpx.get(url, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise AuthError("service unavailable") from exc
        if not isinstance(data, dict) or "keys" not in data:
            raise AuthError("service unavailable")
        _JWKS_CACHE.clear()
        _JWKS_CACHE.update(data)
        return _JWKS_CACHE


def _refresh_jwks() -> dict:
    """Force a JWKS refresh (used when a kid is unknown)."""
    with _JWKS_LOCK:
        _JWKS_CACHE.clear()
    return _fetch_jwks()


def verify_jwt(token: str) -> Optional[dict]:
    """Verify a Supabase access token locally.

    Returns the claims dict if the signature is valid and the token has not
    expired, otherwise ``None``. ``exp`` is enforced by pyjwt.

    Test mode: when ``POLYFUSION_TEST_JWT_SECRET`` is set, tokens are decoded
    as HS256 with that secret, bypassing JWKS — this is how the test suite
    (which mints its own tokens) exercises the local-verify path without an
    asymmetric keypair.
    """
    if not token or _pyjwt is None:
        return None

    test_secret = os.environ.get(_TEST_SECRET_ENV)
    if test_secret:
        try:
            return _pyjwt.decode(
                token, test_secret, algorithms=["HS256"], options={"verify_aud": False}
            )
        except Exception:
            return None

    try:
        unverified_header = _pyjwt.get_unverified_header(token)
    except Exception:
        return None
    kid = unverified_header.get("kid")

    jwks = _fetch_jwks()
    keys = jwks.get("keys", []) or []
    key_obj = next((k for k in keys if k.get("kid") == kid), None)
    if key_obj is None:
        # kid rotation: refresh once and try again.
        jwks = _refresh_jwks()
        keys = jwks.get("keys", []) or []
        key_obj = next((k for k in keys if k.get("kid") == kid), None)
        if key_obj is None:
            return None

    try:
        from jwt import PyJWK  # local import; pyjwt is required

        public_key = PyJWK(key_obj).key
        # Supabase JWKS publish ES256 (EC P-256) keys for projects created
        # after ~2023; older projects may still use RS256. Whitelist both so
        # the project's actual key type is accepted. PyJWT still verifies the
        # signature with the key's native algorithm — an EC key cannot verify
        # an RSA signature (and vice versa), so the whitelist cannot weaken
        # the check.
        return _pyjwt.decode(
            token,
            public_key,
            algorithms=["RS256", "ES256"],
            options={"verify_aud": False},
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _translate_supabase_error(exc: Exception) -> AuthError:
    """Map network/retryable errors to a generic 'service unavailable' message.

    AuthApiError with already-registered semantics is also folded into a
    generic 'registration failed' to prevent user enumeration.
    """
    if isinstance(exc, AuthRetryableError):
        return AuthError("service unavailable")
    if isinstance(exc, AuthApiError):
        code = (exc.code or "").lower() if exc.code else ""
        message = (exc.message or "").lower()
        if (
            "user_already" in code
            or "already registered" in message
            or "already been registered" in message
            or "unique" in code
        ):
            return AuthError("registration failed")
        # Other auth errors: surface a generic message; the underlying detail
        # is not user-facing.
        return AuthError("authentication failed")
    if _httpx is not None and isinstance(exc, _httpx.HTTPError):
        return AuthError("service unavailable")
    return AuthError("service unavailable")


def _already_registered(exc: Exception) -> bool:
    """True if ``exc`` indicates the email/username is already taken."""
    if not isinstance(exc, AuthApiError):
        return False
    code = (exc.code or "").lower() if exc.code else ""
    message = (exc.message or "").lower()
    return (
        "user_already" in code
        or "already registered" in message
        or "already been registered" in message
        or "unique" in code
    )


def _user_dict(user) -> dict:
    """Normalize a Supabase User object into our public shape."""
    metadata = getattr(user, "user_metadata", None) or {}
    email_confirmed = getattr(user, "email_confirmed_at", None)
    return {
        "user_id": getattr(user, "id", None),
        "username": metadata.get("username"),
        "email": getattr(user, "email", None),
        "email_verified": bool(email_confirmed),
    }


def register(username: str, email: str, password: str, password2: str) -> dict:
    """Register a new user via Supabase Auth.

    Returns ``{"user_id", "username", "email", "email_verification_sent"}``.
    Raises ``AuthError`` on validation failure or any Supabase-side error.
    Duplicate-email / already-registered errors are translated to a generic
    ``AuthError("registration failed")`` to prevent enumeration.
    """
    username = validate_username(username)
    email = validate_email(email)
    validate_password(password)
    if password2 != password:
        raise AuthError("passwords do not match")

    client = supabase_client()
    try:
        resp = client.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {"data": {"username": username}},
            }
        )
    except Exception as exc:
        raise _translate_supabase_error(exc) from exc

    user = getattr(resp, "user", None)
    if user is None:
        # Should not happen for a successful sign_up, but stay defensive.
        raise AuthError("registration failed")
    user_id = getattr(user, "id", None)
    # Supabase sets confirmation_sent_at when "Confirm email" is ON; that's our
    # signal that a verification email was dispatched.
    verification_sent = bool(getattr(user, "confirmation_sent_at", None))
    return {
        "user_id": user_id,
        "username": username,
        "email": email,
        "email_verification_sent": verification_sent,
    }


def login(email: str, password: str) -> tuple[str, str, dict]:
    """Log in with email + password.

    Returns ``(access_token, refresh_token, user_dict)``. Raises ``AuthError``
    on any failure (invalid credentials, network, etc.).
    """
    email = validate_email(email)
    if not isinstance(password, str) or not password:
        raise AuthError("invalid credentials")
    client = supabase_client()
    try:
        resp = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:
        raise _translate_supabase_error(exc) from exc

    session = getattr(resp, "session", None)
    user = getattr(resp, "user", None)
    if session is None or user is None:
        raise AuthError("invalid credentials")
    access_token = getattr(session, "access_token", None)
    refresh_token = getattr(session, "refresh_token", None)
    if not access_token or not refresh_token:
        raise AuthError("invalid credentials")
    return access_token, refresh_token, _user_dict(user)


def logout(access_token: Optional[str], refresh_token: Optional[str] = None) -> None:
    """Best-effort sign-out. Network errors are swallowed so cookie cleanup on
    the caller side is never blocked.
    """
    if not access_token:
        return
    client = supabase_client()
    try:
        client.auth.sign_out(access_token)
    except Exception:
        # Best effort: caller always clears its own cookies regardless.
        return


def get_user(access_token: Optional[str]) -> Optional[dict]:
    """Return the public-shape user dict for ``access_token`` or ``None``."""
    if not access_token:
        return None
    client = supabase_client()
    try:
        resp = client.auth.get_user(access_token)
    except Exception:
        return None
    user = getattr(resp, "user", None) if resp is not None else None
    if user is None:
        return None
    return _user_dict(user)


def resend_verification(email: str) -> None:
    """Trigger a new signup confirmation email via Supabase.

    Raises ``AuthError`` on network/service failure. A missing user is not an
    error here (Supabase is opaque by design to avoid enumeration).
    """
    email = validate_email(email)
    client = supabase_client()
    try:
        client.auth.resend({"email": email, "type": "signup"})
    except Exception as exc:
        raise _translate_supabase_error(exc) from exc


def validate_session(
    access_token: Optional[str], refresh_token: Optional[str] = None
) -> Optional[str]:
    """Validate a session locally and return the user id (``sub``) or None.

    The access token is verified locally via ``verify_jwt``. When it is valid
    but expiring within ``_REFRESH_WINDOW`` seconds and a ``refresh_token`` is
    available, a refresh attempt is made; if that succeeds the new session is
    still considered valid (returning the same user id).
    """
    if not access_token:
        return None
    claims = verify_jwt(access_token)
    if claims is None:
        return None
    sub = claims.get("sub")
    if not sub:
        return None

    exp = claims.get("exp")
    now = int(time.time())
    near_expiry = isinstance(exp, (int, float)) and exp - now < _REFRESH_WINDOW
    if near_expiry and refresh_token:
        client = supabase_client()
        try:
            client.auth.refresh_session(refresh_token)
        except Exception:
            # The current token is still technically valid until exp; if the
            # refresh fails we keep the user logged in until the natural
            # expiry rather than forcing an immediate logout.
            pass
    return sub


# ---------------------------------------------------------------------------
# Cookie parsing (kept compatible with the old API name)
# ---------------------------------------------------------------------------

_COOKIE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.\-]{8,4096}$")


def parse_session_cookie(cookie_header: Optional[str]) -> Optional[str]:
    """Return the ``polyfusion_session`` cookie value or ``None``.

    The cookie value is now a JWT, but we treat it as an opaque string here
    and only do a minimal length/charset sanity check before handing it to
    ``verify_jwt`` / Supabase. This guards the lookup path against malformed
    or hostile values while keeping the function's contract identical to the
    pre-Supabase version.
    """
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        k, v = part.strip().split("=", 1)
        if k == "polyfusion_session" and _COOKIE_TOKEN_RE.match(v):
            return v
    return None
