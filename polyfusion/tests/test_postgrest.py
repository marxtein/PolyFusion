"""Unit tests for polyfusion/postgrest.py.

These tests never touch the network — ``urllib.request.urlopen`` is patched
so we can assert on the outgoing Request and synthesise responses. Integration
coverage (real Supabase RLS) lives in ``scripts/kill_switch_rls_test.py``.
"""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from unittest import mock

import pytest

from polyfusion import postgrest


# ---------------------------------------------------------------------------
# Environment fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def supabase_env(monkeypatch):
    """Set the two env vars pg_rest() reads; restore on teardown."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-test-key")
    yield


def _fake_response(body, status=200):
    """Build a context-manager-style fake ``http.client.HTTPResponse``."""
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    resp = mock.MagicMock()
    resp.status = status
    resp.read.return_value = raw
    resp.__enter__ = mock.MagicMock(return_value=resp)
    resp.__exit__ = mock.MagicMock(return_value=False)
    return resp


# ---------------------------------------------------------------------------
# Config / env guards
# ---------------------------------------------------------------------------


def test_pg_rest_requires_env(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    with pytest.raises(postgrest.PostgrestError, match="SUPABASE_URL"):
        postgrest.pg_rest("/foo", access_token="t")


def test_pg_rest_requires_access_token(supabase_env):
    with pytest.raises(postgrest.PostgrestError, match="access_token"):
        postgrest.pg_rest("/foo", access_token="")


# ---------------------------------------------------------------------------
# Header construction
# ---------------------------------------------------------------------------


def test_get_sends_bearer_and_apikey(supabase_env):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["req"] = req
        captured["timeout"] = timeout
        return _fake_response([], status=200)

    with mock.patch.object(
        postgrest.urllib.request, "urlopen", side_effect=fake_urlopen
    ):
        status, payload = postgrest.pg_rest(
            "/profiles?select=id", access_token="user-jwt-123"
        )

    assert status == 200
    assert payload == []
    req = captured["req"]
    assert req.full_url == "https://example.supabase.co/rest/v1/profiles?select=id"
    assert req.get_method() == "GET"
    assert req.headers["Authorization"] == "Bearer user-jwt-123"
    # urllib capitalises header names; apikey may be either case.
    apikey = req.headers.get("apikey") or req.headers.get("Apikey")
    assert apikey == "anon-test-key"
    assert "Prefer" not in req.headers
    assert captured["timeout"] == 30.0


def test_post_adds_prefer_representation(supabase_env):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["req"] = req
        return _fake_response([{"id": "abc"}], status=201)

    with mock.patch.object(
        postgrest.urllib.request, "urlopen", side_effect=fake_urlopen
    ):
        status, payload = postgrest.pg_rest(
            "/computations",
            access_token="t",
            method="POST",
            body={"kind": "run", "inputs": {}},
        )

    assert status == 201
    assert payload == [{"id": "abc"}]
    req = captured["req"]
    assert req.get_method() == "POST"
    assert req.headers["Prefer"] == "return=representation"
    # Body is JSON-encoded UTF-8.
    assert json.loads(req.data.decode("utf-8")) == {"kind": "run", "inputs": {}}
    assert req.headers["Content-type"] == "application/json"


def test_prefer_override(supabase_env):
    """Caller can force a specific Prefer header (e.g. return=minimal)."""
    captured = {}

    def fake_urlopen(req, timeout):
        captured["req"] = req
        return _fake_response(None, status=204)

    with mock.patch.object(
        postgrest.urllib.request, "urlopen", side_effect=fake_urlopen
    ):
        postgrest.pg_rest(
            "/computations",
            access_token="t",
            method="DELETE",
            prefer="return=minimal",
        )

    assert captured["req"].headers["Prefer"] == "return=minimal"


# ---------------------------------------------------------------------------
# Query parameter encoding
# ---------------------------------------------------------------------------


def test_query_dict_is_appended(supabase_env):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["req"] = req
        return _fake_response([], status=200)

    with mock.patch.object(
        postgrest.urllib.request, "urlopen", side_effect=fake_urlopen
    ):
        postgrest.pg_rest(
            "/computations",
            access_token="t",
            query={"select": "id,note", "limit": "10"},
        )

    url = captured["req"].full_url
    # Order is not guaranteed by urlencode; check both params are present.
    assert "select=id%2Cnote" in url
    assert "limit=10" in url


def test_query_is_merged_with_existing_qs(supabase_env):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["req"] = req
        return _fake_response([], status=200)

    with mock.patch.object(
        postgrest.urllib.request, "urlopen", side_effect=fake_urlopen
    ):
        postgrest.pg_rest(
            "/computations?order=created_at.desc",
            access_token="t",
            query={"limit": "5"},
        )

    url = captured["req"].full_url
    assert "order=created_at.desc" in url
    assert "limit=5" in url
    assert url.count("?") == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_http_error_returns_decoded_payload(supabase_env):
    """4xx/5xx PostgREST responses are returned, not raised."""
    err_body = {"code": "42501", "message": "permission denied for table profiles"}

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(
            url=req.full_url,
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=BytesIO(json.dumps(err_body).encode("utf-8")),
        )

    with mock.patch.object(
        postgrest.urllib.request, "urlopen", side_effect=fake_urlopen
    ):
        status, payload = postgrest.pg_rest("/profiles", access_token="t")

    assert status == 403
    assert payload == err_body


def test_urlerror_wrapped_as_postgrest_error(supabase_env):
    def fake_urlopen(req, timeout):
        raise urllib.error.URLError("connection refused")

    with mock.patch.object(
        postgrest.urllib.request, "urlopen", side_effect=fake_urlopen
    ):
        with pytest.raises(postgrest.PostgrestError, match="network error"):
            postgrest.pg_rest("/profiles", access_token="t")


def test_non_json_response_raises(supabase_env):
    def fake_urlopen(req, timeout):
        return _fake_response(None, status=200)

    # Override the read() to return HTML (not JSON).
    resp = _fake_response(None, status=200)
    resp.read.return_value = b"<html>gateway 502</html>"
    with mock.patch.object(postgrest.urllib.request, "urlopen", return_value=resp):
        with pytest.raises(postgrest.PostgrestError, match="non-JSON"):
            postgrest.pg_rest("/profiles", access_token="t")


def test_empty_body_returns_none_payload(supabase_env):
    """204 No Content or empty 200 yields payload=None (no JSON parse)."""
    resp = _fake_response(None, status=204)
    resp.read.return_value = b""
    with mock.patch.object(postgrest.urllib.request, "urlopen", return_value=resp):
        status, payload = postgrest.pg_rest(
            "/computations", access_token="t", method="DELETE"
        )
    assert status == 204
    assert payload is None


# ---------------------------------------------------------------------------
# Override hooks (for tests that point at local Supabase)
# ---------------------------------------------------------------------------


def test_base_url_and_apikey_overrides(supabase_env):
    """Caller can bypass env to point at local Supabase or FakeSupabase."""
    captured = {}

    def fake_urlopen(req, timeout):
        captured["req"] = req
        return _fake_response([], status=200)

    with mock.patch.object(
        postgrest.urllib.request, "urlopen", side_effect=fake_urlopen
    ):
        postgrest.pg_rest(
            "/profiles",
            access_token="t",
            base_url="http://127.0.0.1:54321",
            apikey="local-anon",
        )

    assert captured["req"].full_url == "http://127.0.0.1:54321/rest/v1/profiles"
    apikey = captured["req"].headers.get("apikey") or captured["req"].headers.get(
        "Apikey"
    )
    assert apikey == "local-anon"
