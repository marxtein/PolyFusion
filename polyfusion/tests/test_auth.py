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
    store.register("alice", "password1")
    assert "alice" in store.list_users()

    token = store.login("alice", "password1")
    assert token
    assert store.validate_session(token) == "alice"


def test_register_duplicate(store):
    store.register("bob", "password1")
    with pytest.raises(auth.AuthError):
        store.register("bob", "otherpass")


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


def test_parse_session_cookie():
    assert auth.parse_session_cookie(None) is None
    assert auth.parse_session_cookie("") is None
    assert auth.parse_session_cookie("polyfusion_session=abc; other=x") == "abc"
    assert auth.parse_session_cookie("foo=bar") is None


def test_verify_password_malformed_hash():
    assert not auth.verify_password("x", "not-a-hash")
    assert not auth.verify_password("x", "bcrypt$1$2$3")
