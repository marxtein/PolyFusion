"""Unit tests for polyfusion.auth (user store, hashing, sessions)."""

from __future__ import annotations

import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion import auth  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Fresh UserStore backed by a temp dir for each test."""
    monkeypatch.setenv("POLYFUSION_HOME", str(tmp_path))
    s = auth.UserStore(data_dir=tmp_path)
    auth.reset_store_for_tests(s)
    yield s
    auth.reset_store_for_tests(auth.UserStore(data_dir=tmp_path))


def test_hash_and_verify_password(store):
    h = auth.hash_password("hunter222")
    assert h.startswith("scrypt$")
    assert auth.verify_password("hunter222", h)
    assert not auth.verify_password("wrong", h)


def test_hash_uses_random_salt(store):
    a = auth.hash_password("same-password")
    b = auth.hash_password("same-password")
    assert a != b  # per-user salt


def test_validate_username_rejects_bad(store):
    with pytest.raises(auth.AuthError):
        auth.validate_username("ab")  # too short
    with pytest.raises(auth.AuthError):
        auth.validate_username("x" * 40)  # too long
    with pytest.raises(auth.AuthError):
        auth.validate_username("bad space!")
    assert auth.validate_username("good_name-1") == "good_name-1"


def test_validate_password_min_length(store):
    with pytest.raises(auth.AuthError):
        auth.validate_password("short")
    auth.validate_password("longenough")


def test_register_and_login(store):
    store.register(
        "alice", "password1", email="alice@example.com", password2="password1"
    )
    assert "alice" in store.list_users()
    rec = store._users["alice"]
    assert rec["email"] == "alice@example.com"
    assert rec["email_normalized"] == "alice@example.com"
    assert rec["email_verified"] is False

    token = store.login("alice", "password1")
    assert token
    assert store.validate_session(token) == "alice"


def test_register_and_login_legacy_no_email(store):
    # Backward compatibility: old callers may omit email/password2.
    store.register("alice_legacy", "password1")
    assert "alice_legacy" in store.list_users()
    rec = store._users["alice_legacy"]
    assert rec["email"] is None
    assert rec["email_normalized"] is None
    assert rec["email_verified"] is False

    token = store.login("alice_legacy", "password1")
    assert store.validate_session(token) == "alice_legacy"


def test_register_duplicate(store):
    store.register("bob", "password1", email="bob@example.com", password2="password1")
    with pytest.raises(auth.AuthError):
        store.register(
            "bob", "otherpass", email="bob2@example.com", password2="otherpass"
        )


def test_login_wrong_password(store):
    store.register("carol", "password1")
    with pytest.raises(auth.AuthError):
        store.login("carol", "nope")


def test_session_unknown_token(store):
    assert store.validate_session("does-not-exist") is None
    assert store.validate_session(None) is None
    assert store.validate_session("") is None


def test_logout_invalidates_session(store):
    store.register("dave", "password1")
    token = store.login("dave", "password1")
    assert store.validate_session(token) == "dave"
    store.delete_session(token)
    assert store.validate_session(token) is None


def test_sessions_persist_across_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYFUSION_HOME", str(tmp_path))
    s1 = auth.UserStore(data_dir=tmp_path)
    s1.register("erin", "password1")
    token = s1.login("erin", "password1")

    # new instance loading from the same JSON files should restore the session
    s2 = auth.UserStore(data_dir=tmp_path)
    assert s2.validate_session(token) == "erin"


def test_expired_session_is_evicted(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYFUSION_HOME", str(tmp_path))
    s = auth.UserStore(data_dir=tmp_path)
    s.register("frank", "password1")
    token = s.login("frank", "password1")

    # tamper: backdate the session so it is past TTL
    with s._lock:
        s._sessions[token]["expires"] = time.time() - 1
        s._save()

    assert s.validate_session(token) is None


def test_users_file_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYFUSION_HOME", str(tmp_path))
    s = auth.UserStore(data_dir=tmp_path)
    s.register("gina", "password1")
    users_path = tmp_path / "users.json"
    mode = users_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_password_hash_not_stored_in_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYFUSION_HOME", str(tmp_path))
    s = auth.UserStore(data_dir=tmp_path)
    s.register("henry", "supersecret")
    raw = json.loads((tmp_path / "users.json").read_text())
    assert raw["henry"]["hash"].startswith("scrypt$")
    assert "supersecret" not in json.dumps(raw)


def test_concurrent_registration_is_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYFUSION_HOME", str(tmp_path))
    s = auth.UserStore(data_dir=tmp_path)
    errors: list[Exception] = []
    success: list[str] = []

    def register(idx):
        try:
            s.register(f"user{idx}", "password1")
            success.append(f"user{idx}")
        except auth.AuthError as e:
            errors.append(e)

    threads = [threading.Thread(target=register, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(success) == 10
    assert len(s.list_users()) == 10


def test_concurrent_registration_same_email_allows_one(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYFUSION_HOME", str(tmp_path))
    s = auth.UserStore(data_dir=tmp_path)
    errors: list[Exception] = []
    success: list[str] = []

    def register(idx):
        try:
            s.register(
                f"user{idx}",
                "password1",
                email="shared@example.com",
                password2="password1",
            )
            success.append(f"user{idx}")
        except auth.AuthError as e:
            errors.append(e)

    threads = [threading.Thread(target=register, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(success) == 1
    assert len(errors) == 9
    assert len(s.list_users()) == 1


def test_register_rejects_invalid_email(store):
    invalid_emails = [
        "not-an-email",
        "missing-at.example.com",
        "spaces in@example.com",
        "bad\x00null@example.com",
        "bad\x01ctrl@example.com",
        "bad\x7fctrl@example.com",
        "",
        "a" * 250 + "@example.com",  # >254 chars
    ]
    for email in invalid_emails:
        with pytest.raises(auth.AuthError):
            store.register("newuser", "password1", email=email, password2="password1")


def test_register_rejects_password_mismatch(store):
    with pytest.raises(auth.AuthError, match="password"):
        store.register(
            "newuser", "password1", email="new@example.com", password2="different"
        )


def test_register_duplicate_email_case_insensitive(store):
    store.register(
        "first", "password1", email="User@Example.com", password2="password1"
    )
    with pytest.raises(auth.AuthError):
        store.register(
            "second", "password1", email="user@example.com", password2="password1"
        )


def test_register_duplicate_error_is_generic(store):
    store.register("orig", "password1", email="orig@example.com", password2="password1")
    with pytest.raises(auth.AuthError) as exc_info:
        store.register(
            "orig", "password1", email="new@example.com", password2="password1"
        )
    msg = str(exc_info.value).lower()
    assert "username" not in msg
    assert "email" not in msg

    with pytest.raises(auth.AuthError) as exc_info:
        store.register(
            "newname", "password1", email="orig@example.com", password2="password1"
        )
    msg = str(exc_info.value).lower()
    assert "username" not in msg
    assert "email" not in msg


def test_legacy_user_migration(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYFUSION_HOME", str(tmp_path))
    users_path = tmp_path / "users.json"
    legacy = {
        "legacy_user": {
            "hash": auth.hash_password("password1"),
            "created": time.time(),
        }
    }
    users_path.write_text(json.dumps(legacy))

    s = auth.UserStore(data_dir=tmp_path)
    rec = s._users["legacy_user"]
    assert rec["email"] is None
    assert rec["email_normalized"] is None
    assert rec["email_verified"] is False

    # Login still works after migration.
    token = s.login("legacy_user", "password1")
    assert s.validate_session(token) == "legacy_user"


def test_legacy_backup_created_on_first_write(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYFUSION_HOME", str(tmp_path))
    users_path = tmp_path / "users.json"
    legacy = {
        "legacy_user": {
            "hash": auth.hash_password("password1"),
            "created": time.time(),
        }
    }
    users_path.write_text(json.dumps(legacy))

    s = auth.UserStore(data_dir=tmp_path)
    assert not (tmp_path / "users.json.bak").exists()
    s.register("newbie", "password1", email="newbie@example.com", password2="password1")
    assert (tmp_path / "users.json.bak").exists()
    assert json.loads((tmp_path / "users.json.bak").read_text()) == legacy


def test_parse_session_cookie():
    assert auth.parse_session_cookie(None) is None
    assert auth.parse_session_cookie("") is None
    assert auth.parse_session_cookie("polyfusion_session=abc; other=x") is None
    # only URL-safe base64-ish tokens of reasonable length are accepted
    valid = "abcd1234-_abcd1234-_abcd1234-_abcd1234"
    assert auth.parse_session_cookie(f"polyfusion_session={valid}; other=x") == valid
    assert auth.parse_session_cookie("foo=bar") is None
    # over-long / malformed tokens rejected
    assert auth.parse_session_cookie("polyfusion_session=<script>") is None
    assert auth.parse_session_cookie("polyfusion_session=" + "x" * 200) is None


def test_verify_password_malformed_hash():
    assert not auth.verify_password("x", "not-a-hash")
    assert not auth.verify_password("x", "bcrypt$1$2$3")
