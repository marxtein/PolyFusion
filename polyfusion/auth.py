"""User authentication and session management for PolyFusion.

Stdlib-only implementation:
- Password hashing: ``hashlib.scrypt`` with per-user random salt.
- Storage: JSON files under ``~/.polyfusion`` (path overridable via
  ``POLYFUSION_HOME``). Atomic writes via ``tempfile`` + ``os.replace``.
- Sessions: tokens kept in memory and persisted to disk; 24h sliding TTL
  so server restarts during development do not force re-login for live
  sessions.
- Thread safety: every mutating access is guarded by a re-entrant lock
  because ``ThreadingHTTPServer`` dispatches each request on its own
  thread.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
# OpenSSL caps scrypt at 32 MiB by default (maxmem=0); our N·r·p needs ~32 MiB
# for the working set plus overhead, so bump to 128 MiB to clear the limit
# across OpenSSL versions.
SCRYPT_MAXMEM = 128 * 1024 * 1024

SESSION_TTL = 24 * 3600  # 24 hours, sliding renewal on access

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")
MIN_PASSWORD_LEN = 8


class AuthError(Exception):
    """Raised on registration/login/validation failure."""


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.scrypt(
        pw.encode(),
        salt=salt.encode(),
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_MAXMEM,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, hex_dk = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    try:
        dklen = len(bytes.fromhex(hex_dk))
        dk = hashlib.scrypt(
            pw.encode(),
            salt=salt.encode(),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=dklen,
            maxmem=SCRYPT_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(dk.hex(), hex_dk)


def validate_username(name: str) -> str:
    if not isinstance(name, str):
        raise AuthError("username must be a string")
    name = name.strip()
    if not _USERNAME_RE.match(name):
        raise AuthError("username must be 3-32 chars of [a-zA-Z0-9_-]")
    return name


def validate_password(pw: str) -> None:
    if not isinstance(pw, str) or len(pw) < MIN_PASSWORD_LEN:
        raise AuthError(f"password must be at least {MIN_PASSWORD_LEN} characters")


def _data_dir(override: Optional[str] = None) -> Path:
    base = (
        override
        or os.environ.get("POLYFUSION_HOME")
        or str(Path.home() / ".polyfusion")
    )
    d = Path(base)
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


class UserStore:
    """Thread-safe user + session store backed by JSON files."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._dir = data_dir or _data_dir()
        self._users_path = self._dir / "users.json"
        self._sessions_path = self._dir / "sessions.json"
        self._lock = threading.RLock()
        self._users: dict[str, dict] = self._load_json(self._users_path, {})
        self._sessions: dict[str, dict] = self._load_json(self._sessions_path, {})

    @staticmethod
    def _load_json(path: Path, default):
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    def _save(self) -> None:
        self._atomic_write(self._users_path, self._users)
        self._atomic_write(self._sessions_path, self._sessions)

    def _atomic_write(self, path: Path, data: dict) -> None:
        fd, tmp = tempfile.mkstemp(
            dir=str(self._dir), prefix=path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except OSError:
                pass

    def register(self, username: str, password: str) -> str:
        username = validate_username(username)
        validate_password(password)
        with self._lock:
            if username in self._users:
                raise AuthError("username already exists")
            self._users[username] = {
                "hash": hash_password(password),
                "created": time.time(),
            }
            self._save()
        return username

    def login(self, username: str, password: str) -> str:
        username = validate_username(username)
        with self._lock:
            rec = self._users.get(username)
            if not rec or not verify_password(password, rec.get("hash", "")):
                raise AuthError("invalid credentials")
            return self.create_session(username)

    def create_session(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._sessions[token] = {
                "user": username,
                "created": now,
                "expires": now + SESSION_TTL,
            }
            self._prune_expired(now)
            self._save()
        return token

    def validate_session(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        now = time.time()
        with self._lock:
            rec = self._sessions.get(token)
            if not rec:
                return None
            if rec.get("expires", 0) < now:
                self._sessions.pop(token, None)
                self._save()
                return None
            rec["expires"] = now + SESSION_TTL  # sliding renewal
            self._save()
            return rec["user"]

    def delete_session(self, token: Optional[str]) -> None:
        if not token:
            return
        with self._lock:
            if self._sessions.pop(token, None) is not None:
                self._save()

    def _prune_expired(self, now: float) -> None:
        expired = [t for t, r in self._sessions.items() if r.get("expires", 0) < now]
        for t in expired:
            self._sessions.pop(t, None)

    def has_users(self) -> bool:
        with self._lock:
            return bool(self._users)

    def list_users(self) -> list[str]:
        """For tests/admin only — never expose password hashes."""
        with self._lock:
            return sorted(self._users.keys())


# Module-level singleton, lazily initialised so tests can point POLYFUSION_HOME
# at a temp directory before the first call.
_store: Optional[UserStore] = None
_store_lock = threading.Lock()


def get_store() -> UserStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = UserStore()
    return _store


def reset_store_for_tests(store: UserStore) -> None:
    """Inject a store backed by a temp dir; tests only."""
    global _store
    with _store_lock:
        _store = store


def parse_session_cookie(cookie_header: Optional[str]) -> Optional[str]:
    """Extract the ``polyfusion_session`` token from a Cookie header."""
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        k, v = part.strip().split("=", 1)
        if k == "polyfusion_session":
            return v
    return None
