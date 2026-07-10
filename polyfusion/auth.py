"""User authentication and session management for PolyFusion.

This module is normally a thin adapter over Supabase Auth. When
``POLYFUSION_REQUIRE_EMAIL_CONFIRMATION=0``, registration/login use a local
SQLite auth store so the web process can avoid confirmation emails without
loading a Supabase service-role key.

Public surface used by ``app/server.py``:
    - ``register(username, email, password, password2) -> dict``
    - ``login(email, password) -> (access_token, refresh_token, user_dict)``
    - ``logout(access_token, refresh_token) -> None``
    - ``get_user(access_token) -> dict | None``
    - ``resend_verification(email) -> None``
    - ``validate_session(access_token, refresh_token=None) -> str | None``
    - ``parse_session_cookie(cookie_header) -> str | None``

The normal web process only reads ``SUPABASE_URL`` and ``SUPABASE_ANON_KEY``.
A service-role key is accepted only by the explicit local debug registration
path, which ``app/server.py`` hides unless ``POLYFUSION_DEBUG_AUTH=1``.

JWT verification is performed locally (against the Supabase JWKS) so that
each authenticated request does not pay a network round-trip. A near-expiry
access token is refreshed transparently when a refresh token is available.

Test mode: when ``POLYFUSION_TEST_JWT_SECRET`` is set, ``verify_jwt`` decodes
HS256 tokens signed with that secret instead of consulting JWKS. This keeps
production code clean while letting the test suite (which uses ``pyjwt`` to
mint tokens) avoid the asymmetric-key machinery.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from email.utils import parseaddr
from pathlib import Path
from typing import Optional

from supabase import Client, create_client
from supabase_auth.errors import AuthApiError, AuthRetryableError

from polyfusion import email_send

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

_EMAIL_CONFIRM_ENV = "POLYFUSION_REQUIRE_EMAIL_CONFIRMATION"
_LOCAL_AUTH_DB_ENV = "POLYFUSION_LOCAL_AUTH_DB"
_LOCAL_AUTH_ISSUER = "polyfusion-local-auth"
_LOCAL_VERIFY_ISSUER = "polyfusion-local-auth-verify"
_LOCAL_VERIFY_PROVIDER = "local-verify"
_LOCAL_VERIFY_TTL = 86_400  # 24 hours
_LOCAL_RESET_PROVIDER = "local-password-reset"
_LOCAL_RESET_TTL = 3_600  # 1 hour
_LOCAL_AUTH_ITERATIONS = 210_000
_PUBLIC_BASE_URL_ENV = "PUBLIC_BASE_URL"


class AuthError(Exception):
    """Raised for all PolyFusion-side auth failures."""


def email_confirmation_required() -> bool:
    return os.environ.get(_EMAIL_CONFIRM_ENV, "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _local_auth_db_path() -> Path:
    raw = os.environ.get(_LOCAL_AUTH_DB_ENV, "").strip()
    return (
        Path(raw).expanduser() if raw else Path.home() / ".polyfusion" / "auth.sqlite3"
    )


def _local_conn() -> sqlite3.Connection:
    path = _local_auth_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS local_users (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            affiliation TEXT,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS local_auth_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    # Idempotent schema migrations for the SMTP verification path. Adding a
    # column with ALTER TABLE only runs if the column is missing, so existing
    # huawei/dev databases upgrade transparently on first connect. The default
    # is 1 because pre-migration rows were all created under the no-confirm
    # local path and must stay verified; new SMTP-path registrations insert
    # email_verified=0 explicitly.
    existing_cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(local_users)")
    }
    if "email_verified" not in existing_cols:
        conn.execute(
            "ALTER TABLE local_users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 1"
        )
    if "verify_token_jti" not in existing_cols:
        conn.execute("ALTER TABLE local_users ADD COLUMN verify_token_jti TEXT")
    if "reset_token_jti" not in existing_cols:
        conn.execute("ALTER TABLE local_users ADD COLUMN reset_token_jti TEXT")
    conn.commit()
    return conn


def _local_secret(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT value FROM local_auth_meta WHERE key = 'jwt_secret'"
    ).fetchone()
    if row:
        return str(row["value"])
    secret = secrets.token_urlsafe(48)
    conn.execute(
        "INSERT INTO local_auth_meta(key, value) VALUES('jwt_secret', ?)",
        (secret,),
    )
    conn.commit()
    return secret


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _LOCAL_AUTH_ITERATIONS
    ).hex()


def _local_email_verified(row: sqlite3.Row) -> bool:
    """Read the ``email_verified`` column with None/missing-safe default.

    Rows created before the SMTP migration (or under the no-confirm local
    path) default to verified so existing users are not locked out.
    """
    try:
        return bool(row["email_verified"])
    except (IndexError, KeyError):
        return True


def smtp_verification_active() -> bool:
    """True when the in-app SMTP verification path should be used.

    Requires both email confirmation and SMTP to be enabled; otherwise the
    no-confirm local path or the Supabase path applies.
    """
    return email_confirmation_required() and email_send.smtp_enabled()


def _local_user_dict(row: sqlite3.Row) -> dict:
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "email": row["email"],
        "email_verified": _local_email_verified(row),
        "affiliation": row["affiliation"],
        "is_admin": False,
        "auth_provider": "local",
    }


def _local_register(
    username: str,
    email: str,
    password: str,
    *,
    affiliation: str | None = None,
) -> dict:
    salt = secrets.token_bytes(16)
    user_id = f"local-{uuid.uuid4()}"
    try:
        with _local_conn() as conn:
            conn.execute(
                """
                INSERT INTO local_users(
                    user_id, username, email, salt, password_hash, affiliation, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    username,
                    email,
                    salt.hex(),
                    _hash_password(password, salt),
                    affiliation,
                    time.time(),
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise AuthError("registration failed") from exc
    except sqlite3.Error as exc:
        raise AuthError("service unavailable") from exc
    return {
        "user_id": user_id,
        "username": username,
        "email": email,
        "email_verification_sent": False,
        "auth_provider": "local",
    }


def _public_base_url() -> str:
    """Public base URL for verification links.

    Reads ``PUBLIC_BASE_URL``; falls back to localhost so dev/test flows do
    not need it set. The server may override this per-request by setting the
    env var before dispatching to ``register``.
    """
    raw = (os.environ.get(_PUBLIC_BASE_URL_ENV) or "").strip().rstrip("/")
    return raw or "http://localhost:8765"


def _build_verify_url(token: str) -> str:
    return f"{_public_base_url()}/api/auth/verify-email?token={token}"


def _build_password_reset_url(token: str) -> str:
    return f"{_public_base_url()}/vsc/?reset_token={token}"


def _local_issue_verify_token(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    """Mint a short-lived HS256 JWT bound to ``(user_id, jti)``.

    ``provider`` is ``local-verify`` (distinct from session tokens' ``local``)
    so ``_local_claims`` rejects verify tokens if presented as session tokens.
    The ``jti`` is also stored on the user row so a successful verify can
    invalidate any outstanding tokens for that user (single-use semantics).
    """
    if _pyjwt is None:
        raise AuthError("service unavailable")
    jti = secrets.token_urlsafe(16)
    conn.execute(
        "UPDATE local_users SET verify_token_jti = ? WHERE user_id = ?",
        (jti, row["user_id"]),
    )
    conn.commit()
    now = int(time.time())
    return _pyjwt.encode(
        {
            "iss": _LOCAL_VERIFY_ISSUER,
            "provider": _LOCAL_VERIFY_PROVIDER,
            "sub": row["user_id"],
            "email": row["email"],
            "jti": jti,
            "purpose": "verify-email",
            "iat": now,
            "exp": now + _LOCAL_VERIFY_TTL,
        },
        _local_secret(conn),
        algorithm="HS256",
    )


def _local_issue_password_reset_token(
    conn: sqlite3.Connection, row: sqlite3.Row
) -> str:
    if _pyjwt is None:
        raise AuthError("service unavailable")
    jti = secrets.token_urlsafe(16)
    conn.execute(
        "UPDATE local_users SET reset_token_jti = ? WHERE user_id = ?",
        (jti, row["user_id"]),
    )
    conn.commit()
    now = int(time.time())
    return _pyjwt.encode(
        {
            "iss": _LOCAL_VERIFY_ISSUER,
            "provider": _LOCAL_RESET_PROVIDER,
            "sub": row["user_id"],
            "email": row["email"],
            "jti": jti,
            "purpose": "reset-password",
            "iat": now,
            "exp": now + _LOCAL_RESET_TTL,
        },
        _local_secret(conn),
        algorithm="HS256",
    )


def _local_row_by_id(conn: sqlite3.Connection, user_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM local_users WHERE user_id = ?", (user_id,)
    ).fetchone()


def _local_row_by_email(conn: sqlite3.Connection, email: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM local_users WHERE email = ?", (email,)
    ).fetchone()


def _local_register_with_verification(
    username: str,
    email: str,
    password: str,
    *,
    affiliation: str | None = None,
    sender: email_send.Sender | None = None,
) -> dict:
    """Register a local user and dispatch a verification email via SMTP.

    On any email-delivery failure the freshly-inserted row is deleted so the
    caller can surface a clean error and the user can retry without an orphan
    account blocking the email.
    """
    salt = secrets.token_bytes(16)
    user_id = f"local-{uuid.uuid4()}"
    try:
        with _local_conn() as conn:
            conn.execute(
                """
                INSERT INTO local_users(
                    user_id, username, email, salt, password_hash,
                    affiliation, created_at, email_verified
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    user_id,
                    username,
                    email,
                    salt.hex(),
                    _hash_password(password, salt),
                    affiliation,
                    time.time(),
                ),
            )
            row = _local_row_by_id(conn, user_id)
            if row is None:
                raise AuthError("registration failed")
            token = _local_issue_verify_token(conn, row)
    except AuthError:
        raise
    except sqlite3.IntegrityError as exc:
        raise AuthError("registration failed") from exc
    except sqlite3.Error as exc:
        raise AuthError("service unavailable") from exc

    verify_url = _build_verify_url(token)
    try:
        email_send.send_verification_email(email, verify_url, sender=sender)
    except email_send.EmailSendError as exc:
        # Roll back the orphan row so the user can retry without an
        # unverified account blocking the email.
        with _local_conn() as conn:
            conn.execute("DELETE FROM local_users WHERE user_id = ?", (user_id,))
            conn.commit()
        raise AuthError("verification email could not be sent") from exc
    return {
        "user_id": user_id,
        "username": username,
        "email": email,
        "email_verification_sent": True,
        "auth_provider": "local",
    }


def verify_email_token(token: str) -> dict:
    """Validate a verify-email JWT and flip the user's verified flag.

    Returns ``{"ok": bool, "already_verified": bool, "user_id": str | None,
    "reason": str}``. Reasons: ``"success"`` / ``"already_verified"`` /
    ``"expired"`` / ``"invalid"``.
    """
    if not token or _pyjwt is None:
        return {
            "ok": False,
            "already_verified": False,
            "user_id": None,
            "reason": "invalid",
        }
    try:
        unverified = _pyjwt.decode(token, options={"verify_signature": False})
    except Exception:
        return {
            "ok": False,
            "already_verified": False,
            "user_id": None,
            "reason": "invalid",
        }
    if (
        unverified.get("provider") != _LOCAL_VERIFY_PROVIDER
        or unverified.get("iss") != _LOCAL_VERIFY_ISSUER
        or unverified.get("purpose") != "verify-email"
    ):
        return {
            "ok": False,
            "already_verified": False,
            "user_id": None,
            "reason": "invalid",
        }
    user_id = unverified.get("sub") or ""
    jti = unverified.get("jti") or ""
    if not user_id or not jti:
        return {
            "ok": False,
            "already_verified": False,
            "user_id": None,
            "reason": "invalid",
        }
    try:
        with _local_conn() as conn:
            row = _local_row_by_id(conn, user_id)
            if row is None:
                return {
                    "ok": False,
                    "already_verified": False,
                    "user_id": None,
                    "reason": "invalid",
                }
            try:
                claims = _pyjwt.decode(
                    token,
                    _local_secret(conn),
                    algorithms=["HS256"],
                    issuer=_LOCAL_VERIFY_ISSUER,
                    options={"verify_aud": False},
                )
            except getattr(_pyjwt, "ExpiredSignatureError", ()):
                return {
                    "ok": False,
                    "already_verified": False,
                    "user_id": user_id,
                    "reason": "expired",
                }
            except _pyjwt.PyJWTError:
                return {
                    "ok": False,
                    "already_verified": False,
                    "user_id": user_id,
                    "reason": "invalid",
                }
            if claims.get("jti") != jti:
                return {
                    "ok": False,
                    "already_verified": False,
                    "user_id": user_id,
                    "reason": "invalid",
                }
            if bool(row["email_verified"]):
                return {
                    "ok": True,
                    "already_verified": True,
                    "user_id": user_id,
                    "reason": "already_verified",
                }
            stored_jti = (
                row["verify_token_jti"] if "verify_token_jti" in row.keys() else None
            )
            if stored_jti != jti:
                return {
                    "ok": False,
                    "already_verified": False,
                    "user_id": user_id,
                    "reason": "invalid",
                }
            conn.execute(
                "UPDATE local_users SET email_verified = 1, verify_token_jti = NULL "
                "WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()
    except sqlite3.Error:
        return {
            "ok": False,
            "already_verified": False,
            "user_id": user_id,
            "reason": "invalid",
        }
    return {
        "ok": True,
        "already_verified": False,
        "user_id": user_id,
        "reason": "success",
    }


def _local_resend_verification(
    email: str, *, sender: email_send.Sender | None = None
) -> None:
    """Mint a fresh verify token and re-send the email.

    Anti-enumeration: silently no-ops when the user is missing or already
    verified, mirroring Supabase's opaque behavior.
    """
    try:
        with _local_conn() as conn:
            row = _local_row_by_email(conn, email)
            if row is None or bool(row["email_verified"]):
                return
            token = _local_issue_verify_token(conn, row)
    except sqlite3.Error:
        # Treat DB failure as "user not found" to avoid leaking state.
        return
    verify_url = _build_verify_url(token)
    try:
        email_send.send_verification_email(email, verify_url, sender=sender)
    except email_send.EmailSendError as exc:
        raise AuthError("verification email could not be sent") from exc


def _local_request_password_reset(
    email: str, *, sender: email_send.Sender | None = None
) -> None:
    try:
        with _local_conn() as conn:
            row = _local_row_by_email(conn, email)
            if row is None:
                return
            token = _local_issue_password_reset_token(conn, row)
    except sqlite3.Error:
        return
    reset_url = _build_password_reset_url(token)
    try:
        email_send.send_password_reset_email(email, reset_url, sender=sender)
    except email_send.EmailSendError as exc:
        raise AuthError("password reset email could not be sent") from exc


def _local_reset_password(token: str, password: str, password2: str) -> dict:
    validate_password(password)
    if password2 != password:
        raise AuthError("passwords do not match")
    if not token or _pyjwt is None:
        raise AuthError("invalid reset link")
    try:
        unverified = _pyjwt.decode(token, options={"verify_signature": False})
    except Exception as exc:
        raise AuthError("invalid reset link") from exc
    if (
        unverified.get("provider") != _LOCAL_RESET_PROVIDER
        or unverified.get("iss") != _LOCAL_VERIFY_ISSUER
        or unverified.get("purpose") != "reset-password"
    ):
        raise AuthError("invalid reset link")
    user_id = unverified.get("sub") or ""
    jti = unverified.get("jti") or ""
    if not user_id or not jti:
        raise AuthError("invalid reset link")
    try:
        with _local_conn() as conn:
            row = _local_row_by_id(conn, user_id)
            if row is None:
                raise AuthError("invalid reset link")
            try:
                claims = _pyjwt.decode(
                    token,
                    _local_secret(conn),
                    algorithms=["HS256"],
                    issuer=_LOCAL_VERIFY_ISSUER,
                    options={"verify_aud": False},
                )
            except getattr(_pyjwt, "ExpiredSignatureError", ()) as exc:
                raise AuthError("reset link expired") from exc
            except _pyjwt.PyJWTError as exc:
                raise AuthError("invalid reset link") from exc
            if claims.get("jti") != jti:
                raise AuthError("invalid reset link")
            stored_jti = (
                row["reset_token_jti"] if "reset_token_jti" in row.keys() else None
            )
            if stored_jti != jti:
                raise AuthError("invalid reset link")
            salt = secrets.token_bytes(16)
            conn.execute(
                "UPDATE local_users SET salt = ?, password_hash = ?, "
                "reset_token_jti = NULL WHERE user_id = ?",
                (salt.hex(), _hash_password(password, salt), user_id),
            )
            conn.commit()
            return {"ok": True, "email": row["email"]}
    except AuthError:
        raise
    except sqlite3.Error as exc:
        raise AuthError("service unavailable") from exc


def _local_change_password(
    access_token: str, current_password: str, password: str, password2: str
) -> dict:
    validate_password(password)
    if password2 != password:
        raise AuthError("passwords do not match")
    if not isinstance(current_password, str) or not current_password:
        raise AuthError("invalid credentials")
    claims = _local_claims(access_token)
    if claims is None:
        raise AuthError("unauthorized")
    try:
        with _local_conn() as conn:
            row = _local_row_by_id(conn, claims.get("sub") or "")
            if row is None:
                raise AuthError("unauthorized")
            expected = _hash_password(current_password, bytes.fromhex(row["salt"]))
            if not hmac.compare_digest(expected, row["password_hash"]):
                raise AuthError("invalid credentials")
            salt = secrets.token_bytes(16)
            conn.execute(
                "UPDATE local_users SET salt = ?, password_hash = ?, "
                "reset_token_jti = NULL WHERE user_id = ?",
                (salt.hex(), _hash_password(password, salt), row["user_id"]),
            )
            conn.commit()
            return {"ok": True}
    except AuthError:
        raise
    except sqlite3.Error as exc:
        raise AuthError("service unavailable") from exc


def _local_issue_session(
    conn: sqlite3.Connection, row: sqlite3.Row
) -> tuple[str, str, dict]:
    if _pyjwt is None:
        raise AuthError("service unavailable")
    now = int(time.time())
    access = _pyjwt.encode(
        {
            "iss": _LOCAL_AUTH_ISSUER,
            "provider": "local",
            "sub": row["user_id"],
            "email": row["email"],
            "iat": now,
            "exp": now + 3600,
        },
        _local_secret(conn),
        algorithm="HS256",
    )
    refresh = f"local-{secrets.token_urlsafe(32)}"
    return access, refresh, _local_user_dict(row)


def _local_login(email: str, password: str) -> tuple[str, str, dict] | None:
    try:
        with _local_conn() as conn:
            row = conn.execute(
                "SELECT * FROM local_users WHERE email = ?", (email,)
            ).fetchone()
            if row is None:
                return None
            expected = _hash_password(password, bytes.fromhex(row["salt"]))
            if not hmac.compare_digest(expected, row["password_hash"]):
                raise AuthError("invalid credentials")
            return _local_issue_session(conn, row)
    except AuthError:
        raise
    except sqlite3.Error as exc:
        raise AuthError("service unavailable") from exc


def _local_claims(token: str) -> Optional[dict]:
    if not token or _pyjwt is None:
        return None
    try:
        unverified = _pyjwt.decode(token, options={"verify_signature": False})
    except Exception:
        return None
    if (
        unverified.get("provider") != "local"
        or unverified.get("iss") != _LOCAL_AUTH_ISSUER
    ):
        return None
    try:
        with _local_conn() as conn:
            return _pyjwt.decode(
                token,
                _local_secret(conn),
                algorithms=["HS256"],
                issuer=_LOCAL_AUTH_ISSUER,
                options={"verify_aud": False},
            )
    except Exception:
        return None


def _local_get_user(access_token: str) -> Optional[dict]:
    claims = _local_claims(access_token)
    if claims is None:
        return None
    try:
        with _local_conn() as conn:
            row = conn.execute(
                "SELECT * FROM local_users WHERE user_id = ?", (claims.get("sub"),)
            ).fetchone()
    except sqlite3.Error:
        return None
    return _local_user_dict(row) if row else None


def is_local_token(access_token: Optional[str]) -> bool:
    return bool(
        (not email_confirmation_required() or smtp_verification_active())
        and access_token
        and _local_claims(access_token) is not None
    )


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
            pass

    if not email_confirmation_required() or smtp_verification_active():
        local = _local_claims(token)
        if local is not None:
            return local

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
        "affiliation": metadata.get("affiliation"),
        "is_admin": False,
    }


def register(
    username: str,
    email: str,
    password: str,
    password2: str,
    *,
    affiliation: str | None = None,
) -> dict:
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

    if not email_confirmation_required():
        return _local_register(
            username,
            email,
            password,
            affiliation=affiliation.strip() if affiliation else None,
        )

    if smtp_verification_active():
        return _local_register_with_verification(
            username,
            email,
            password,
            affiliation=affiliation.strip() if affiliation else None,
        )

    client = supabase_client()
    try:
        data = {"username": username}
        if affiliation:
            data["affiliation"] = affiliation.strip()
        resp = client.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {"data": data},
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


def debug_create_verified_user(
    username: str,
    email: str,
    password: str,
    password2: str,
    *,
    affiliation: str | None = None,
) -> dict:
    username = validate_username(username)
    email = validate_email(email)
    validate_password(password)
    if password2 != password:
        raise AuthError("passwords do not match")

    base_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    service_key = (
        os.environ.get("POLYFUSION_DEBUG_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or ""
    ).strip()
    if not base_url or not service_key:
        raise AuthError("debug auth is not configured")

    metadata = {"username": username}
    if affiliation:
        metadata["affiliation"] = affiliation.strip()
    body = {
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": metadata,
    }
    request = urllib.request.Request(
        f"{base_url}/auth/v1/admin/users",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {service_key}",
            "apikey": service_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace").lower()
        if exc.code in (400, 409, 422) and (
            "already" in body_text or "duplicate" in body_text
        ):
            raise AuthError("registration failed") from exc
        raise AuthError("debug registration failed") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AuthError("debug registration failed") from exc

    user_id = payload.get("id") if isinstance(payload, dict) else None
    return {
        "user_id": user_id,
        "username": username,
        "email": email,
        "email_verification_sent": False,
    }


def login(email: str, password: str) -> tuple[str, str, dict]:
    """Log in with email + password.

    Returns ``(access_token, refresh_token, user_dict)``. Raises ``AuthError``
    on any failure (invalid credentials, network, etc.).
    """
    email = validate_email(email)
    if not isinstance(password, str) or not password:
        raise AuthError("invalid credentials")
    if not email_confirmation_required() or smtp_verification_active():
        local = _local_login(email, password)
        if local is not None:
            return local
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
    if (
        not email_confirmation_required() or smtp_verification_active()
    ) and _local_claims(access_token) is not None:
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
    if not email_confirmation_required() or smtp_verification_active():
        local = _local_get_user(access_token)
        if local is not None:
            return local
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
    """Trigger a new signup confirmation email.

    Dispatches to the SMTP local path when active, otherwise to Supabase.
    A missing user is not an error on either path (anti-enumeration).
    """
    email = validate_email(email)
    if smtp_verification_active():
        _local_resend_verification(email)
        return
    client = supabase_client()
    try:
        client.auth.resend({"email": email, "type": "signup"})
    except Exception as exc:
        raise _translate_supabase_error(exc) from exc


def request_password_reset(email: str) -> None:
    email = validate_email(email)
    if smtp_verification_active():
        _local_request_password_reset(email)
        return
    client = supabase_client()
    try:
        client.auth.reset_password_for_email(email)
    except Exception as exc:
        raise _translate_supabase_error(exc) from exc


def reset_password(token: str, password: str, password2: str) -> dict:
    if smtp_verification_active():
        return _local_reset_password(token, password, password2)
    raise AuthError("password reset unavailable")


def change_password(
    access_token: Optional[str], current_password: str, password: str, password2: str
) -> dict:
    if not access_token:
        raise AuthError("unauthorized")
    if smtp_verification_active() and _local_claims(access_token) is not None:
        return _local_change_password(
            access_token, current_password, password, password2
        )
    raise AuthError("password change unavailable")


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
