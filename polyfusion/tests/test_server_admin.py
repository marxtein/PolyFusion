"""HTTP-layer tests for v1.2 ``/api/admin/*`` routes.

Mirrors ``test_server_history.py``: the autouse ``_fake_supabase`` conftest
fixture handles auth, and ``polyfusion.admin`` is patched per-test so we
exercise the HTTP envelope without touching PostgREST. Underlying module
behaviour is covered by ``test_admin.py``.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import app.server as srv
from polyfusion import admin as admin_mod
from polyfusion.admin import AdminError
from polyfusion.postgrest import PostgrestError
from app.server import Handler


# ---------------------------------------------------------------------------
# In-process server fixture (mirrors test_server_history.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def inproc_server(monkeypatch):
    monkeypatch.setattr(srv, "REQUIRE_AUTH", True)
    srv._RATE_LIMIT.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        srv._RATE_LIMIT.clear()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _port(server) -> int:
    return server.server_port


def _request(server, path, *, method="GET", body=None, headers=None):
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(
        f"http://127.0.0.1:{_port(server)}{path}",
        data=data,
        method=method,
        headers=hdrs,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
            rhdrs = resp.headers
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        status = exc.code
        rhdrs = exc.headers
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = raw
    return status, payload, rhdrs


def _cookies_from_headers(hdrs) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, val in hdrs.items():
        if key.lower() != "set-cookie":
            continue
        first = val.split(";", 1)[0]
        if "=" not in first:
            continue
        name, value = first.split("=", 1)
        out[name.strip()] = value
    return out


def _login_cookie(server, email="admin@example.com", password="password1"):
    _request(
        server,
        "/api/auth/register",
        method="POST",
        body={
            "username": "admin",
            "email": email,
            "password": password,
            "password2": password,
        },
    )
    _, _, hdrs = _request(
        server,
        "/api/auth/login",
        method="POST",
        body={"email": email, "password": password},
    )
    cookies = _cookies_from_headers(hdrs)
    parts = []
    if srv.ACCESS_COOKIE in cookies:
        parts.append(f"{srv.ACCESS_COOKIE}={cookies[srv.ACCESS_COOKIE]}")
    if srv.REFRESH_COOKIE in cookies:
        parts.append(f"{srv.REFRESH_COOKIE}={cookies[srv.REFRESH_COOKIE]}")
    return "; ".join(parts)


class _Recorder:
    def __init__(self, return_value, side_effect=None):
        self.return_value = return_value
        self.side_effect = side_effect
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        if self.side_effect is not None:
            raise self.side_effect
        return self.return_value


@pytest.fixture
def mock_admin(monkeypatch):
    rec = {
        "stats": _Recorder(
            return_value={
                "total_users": 42,
                "new_users_7d": 3,
                "total_computations": 17,
                "top_affiliations": [
                    {"affiliation": "ASIPP", "count": 5},
                    {"affiliation": "IPP", "count": 2},
                ],
            }
        ),
        "list_users": _Recorder(
            return_value=(1, [{"id": "u1", "email": "u1@example.com"}])
        ),
    }
    monkeypatch.setattr(admin_mod, "stats", rec["stats"])
    monkeypatch.setattr(admin_mod, "list_users", rec["list_users"])
    return rec


# ---------------------------------------------------------------------------
# GET /api/admin/stats
# ---------------------------------------------------------------------------


def test_admin_stats_returns_envelope(inproc_server, mock_admin):
    cookie = _login_cookie(inproc_server)
    status, payload, _ = _request(
        inproc_server, "/api/admin/stats", headers={"Cookie": cookie}
    )
    assert status == 200, payload
    assert set(payload.keys()) == {
        "total_users",
        "new_users_7d",
        "total_computations",
        "top_affiliations",
    }
    assert payload["total_users"] == 42
    assert payload["top_affiliations"][0]["affiliation"] == "ASIPP"
    # The handler passes the user's access token positionally.
    assert mock_admin["stats"].calls[-1]["args"][0]


def test_admin_stats_400_on_admin_error(inproc_server, mock_admin):
    mock_admin["stats"].side_effect = AdminError("PostgREST stats fetch failed: 500")
    cookie = _login_cookie(inproc_server)
    status, payload, _ = _request(
        inproc_server, "/api/admin/stats", headers={"Cookie": cookie}
    )
    assert status == 400
    assert "PostgREST" in payload["error"]


def test_admin_stats_500_on_postgrest_error(inproc_server, mock_admin):
    mock_admin["stats"].side_effect = PostgrestError("connection refused")
    cookie = _login_cookie(inproc_server)
    status, _, _ = _request(
        inproc_server, "/api/admin/stats", headers={"Cookie": cookie}
    )
    assert status == 500


# ---------------------------------------------------------------------------
# GET /api/admin/users
# ---------------------------------------------------------------------------


def test_admin_users_returns_envelope(inproc_server, mock_admin):
    cookie = _login_cookie(inproc_server)
    status, payload, _ = _request(
        inproc_server, "/api/admin/users", headers={"Cookie": cookie}
    )
    assert status == 200, payload
    assert set(payload.keys()) == {"total", "limit", "offset", "rows"}
    call = mock_admin["list_users"].calls[-1]
    assert call["kwargs"]["limit"] == admin_mod.DEFAULT_LIMIT
    assert call["kwargs"]["offset"] == 0


def test_admin_users_passes_pagination_params(inproc_server, mock_admin):
    cookie = _login_cookie(inproc_server)
    status, _, _ = _request(
        inproc_server,
        "/api/admin/users?limit=100&offset=25",
        headers={"Cookie": cookie},
    )
    assert status == 200
    call = mock_admin["list_users"].calls[-1]
    assert call["kwargs"]["limit"] == 100
    assert call["kwargs"]["offset"] == 25


def test_admin_users_400_on_admin_error(inproc_server, mock_admin):
    mock_admin["list_users"].side_effect = AdminError("PostgREST list failed: 403")
    cookie = _login_cookie(inproc_server)
    status, _, _ = _request(
        inproc_server, "/api/admin/users", headers={"Cookie": cookie}
    )
    assert status == 400


def test_admin_users_500_on_postgrest_error(inproc_server, mock_admin):
    mock_admin["list_users"].side_effect = PostgrestError("timeout")
    cookie = _login_cookie(inproc_server)
    status, _, _ = _request(
        inproc_server, "/api/admin/users", headers={"Cookie": cookie}
    )
    assert status == 500


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


def test_admin_routes_require_auth(inproc_server, mock_admin):
    status, _, _ = _request(inproc_server, "/api/admin/stats")
    assert status == 401
    status, _, _ = _request(inproc_server, "/api/admin/users")
    assert status == 401
    assert not mock_admin["stats"].calls
    assert not mock_admin["list_users"].calls
