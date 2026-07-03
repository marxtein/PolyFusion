from __future__ import annotations

import pytest

from polyfusion import profile


def test_get_profile_filters_current_user(monkeypatch):
    calls = []

    def fake_pg_rest(path, *, access_token, method="GET", query=None, **kwargs):
        calls.append(
            {
                "path": path,
                "access_token": access_token,
                "method": method,
                "query": query,
            }
        )
        return 200, [{"id": "u-1", "affiliation": "ASIPP", "is_admin": True}]

    monkeypatch.setattr(profile, "pg_rest", fake_pg_rest)
    got = profile.get_profile("jwt-1", "u-1")
    assert got == {"id": "u-1", "affiliation": "ASIPP", "is_admin": True}
    assert calls == [
        {
            "path": "/profiles?select=id,username,email,affiliation,is_admin",
            "access_token": "jwt-1",
            "method": "GET",
            "query": {"id": "eq.u-1", "limit": "1"},
        }
    ]


def test_get_profile_none_for_missing_inputs():
    assert profile.get_profile("", "u-1") is None
    assert profile.get_profile("jwt-1", "") is None


def test_get_profile_raises_on_postgrest_failure(monkeypatch):
    monkeypatch.setattr(
        profile, "pg_rest", lambda *args, **kwargs: (500, {"error": "boom"})
    )
    with pytest.raises(profile.ProfileError, match="PostgREST profile fetch failed"):
        profile.get_profile("jwt-1", "u-1")


def test_delete_current_account_calls_rpc(monkeypatch):
    calls = []

    def fake_pg_rest(path, *, access_token, method="GET", body=None, **kwargs):
        calls.append(
            {
                "path": path,
                "access_token": access_token,
                "method": method,
                "body": body,
            }
        )
        return 200, True

    monkeypatch.setattr(profile, "pg_rest", fake_pg_rest)
    profile.delete_current_account("jwt-1")
    assert calls == [
        {
            "path": "/rpc/delete_current_user",
            "access_token": "jwt-1",
            "method": "POST",
            "body": {},
        }
    ]


def test_delete_current_account_raises_on_failure(monkeypatch):
    monkeypatch.setattr(
        profile, "pg_rest", lambda *args, **kwargs: (403, {"error": "no"})
    )
    with pytest.raises(profile.ProfileError, match="PostgREST account delete failed"):
        profile.delete_current_account("jwt-1")
