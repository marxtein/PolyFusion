from __future__ import annotations

import pytest

from polyfusion import auth


@pytest.fixture
def local_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("POLYFUSION_LOCAL_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("POLYFUSION_REQUIRE_EMAIL_CONFIRMATION", "1")
    monkeypatch.setenv("POLYFUSION_SMTP_ENABLED", "0")
    monkeypatch.setenv("POLYFUSION_LEGACY_SUPABASE_AUTH", "0")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setattr(
        auth,
        "supabase_client",
        lambda: pytest.fail("public auth must not call Supabase"),
    )


def test_default_registration_and_login_are_local(local_auth):
    registered = auth.register(
        "localuser",
        "local@example.com",
        "password1",
        "password1",
        affiliation="VeloAlpha",
    )
    assert registered["auth_provider"] == "local"
    assert registered["email_verification_sent"] is False

    access, refresh, user = auth.login("local@example.com", "password1")
    assert access and refresh
    assert user["username"] == "localuser"
    assert user["email"] == "local@example.com"
    assert auth.get_user(access)["user_id"] == user["user_id"]
    assert auth.validate_session(access, refresh) == user["user_id"]


def test_unknown_local_email_never_falls_through_to_supabase(local_auth):
    with pytest.raises(auth.AuthError, match="invalid credentials"):
        auth.login("missing@example.com", "password1")


def test_duplicate_email_is_rejected_by_local_database(local_auth):
    auth.register("firstuser", "same@example.com", "password1", "password1")
    with pytest.raises(auth.AuthError, match="registration failed"):
        auth.register("seconduser", "same@example.com", "password1", "password1")
