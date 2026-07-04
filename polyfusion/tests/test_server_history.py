"""HTTP-layer tests for the v1.2 ``/api/history`` CRUD routes.

Same in-process server pattern as ``test_server_auth.py``: the autouse
``_fake_supabase`` conftest fixture already patches ``polyfusion.auth``, so
the handler threads see a working auth pipeline. ``polyfusion.history`` is
patched here per test so we exercise the HTTP envelope; the underlying local
SQLite storage module has its own unit tests.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import app.server as srv
from polyfusion import history as history_mod
from polyfusion.history import HistoryError
from app.server import Handler


# ---------------------------------------------------------------------------
# In-process server fixture (mirrors test_server_auth.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def inproc_server(monkeypatch):
    monkeypatch.setattr(srv, "REQUIRE_AUTH", True)
    monkeypatch.setattr(srv, "GUEST_MODE", False)
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
    """Issue a request and return ``(status, parsed_json_or_text, hdrs)``."""
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


def _login_cookie(server, email="hist@example.com", password="password1"):
    """Register + log in, returning the Cookie header for the session."""
    _request(
        server,
        "/api/auth/register",
        method="POST",
        body={
            "username": "hist",
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


# ---------------------------------------------------------------------------
# Recording mock factory
# ---------------------------------------------------------------------------


class _Recorder:
    """Records each call so tests can assert on kwargs + controls the return."""

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
def mock_history(monkeypatch):
    """Patch the four history module functions used by the routes.

    Each function starts with a sensible default; tests rewire individual
    ``.return_value`` / ``.side_effect`` attributes as needed.
    """
    rec = {
        "list": _Recorder(return_value=(2, [{"id": "a"}, {"id": "b"}])),
        "get": _Recorder(return_value={"id": "abc", "kind": "run"}),
        "save": _Recorder(return_value={"id": "new", "kind": "run"}),
        "delete": _Recorder(return_value=True),
    }
    monkeypatch.setattr(history_mod, "list_history", rec["list"])
    monkeypatch.setattr(history_mod, "get_history", rec["get"])
    monkeypatch.setattr(history_mod, "save_history", rec["save"])
    monkeypatch.setattr(history_mod, "delete_history", rec["delete"])
    return rec


# ---------------------------------------------------------------------------
# GET /api/history (list)
# ---------------------------------------------------------------------------


def test_history_list_returns_envelope(inproc_server, mock_history):
    cookie = _login_cookie(inproc_server)
    status, payload, _ = _request(
        inproc_server, "/api/history", headers={"Cookie": cookie}
    )
    assert status == 200, payload
    assert set(payload.keys()) == {"total", "limit", "offset", "rows"}
    assert payload["total"] == 2
    assert payload["rows"] == [{"id": "a"}, {"id": "b"}]
    assert payload["limit"] == 20
    assert payload["offset"] == 0
    call = mock_history["list"].calls[-1]
    assert call["kwargs"]["limit"] == 20
    assert call["kwargs"]["offset"] == 0
    assert call["kwargs"]["kind"] is None
    assert call["args"][0]


def test_history_list_passes_query_params(inproc_server, mock_history):
    cookie = _login_cookie(inproc_server)
    status, _, _ = _request(
        inproc_server,
        "/api/history?limit=5&offset=10&kind=scan",
        headers={"Cookie": cookie},
    )
    assert status == 200
    call = mock_history["list"].calls[-1]
    assert call["kwargs"]["limit"] == 5
    assert call["kwargs"]["offset"] == 10
    assert call["kwargs"]["kind"] == "scan"


def test_history_list_400_on_caller_error(inproc_server, mock_history):
    mock_history["list"].side_effect = HistoryError(
        "kind must be one of ['run', 'scan']"
    )
    cookie = _login_cookie(inproc_server)
    status, payload, _ = _request(
        inproc_server, "/api/history?kind=bogus", headers={"Cookie": cookie}
    )
    assert status == 400
    assert "kind" in payload["error"]


def test_history_list_400_on_storage_error(inproc_server, mock_history):
    mock_history["list"].side_effect = HistoryError("storage unavailable")
    cookie = _login_cookie(inproc_server)
    status, payload, _ = _request(
        inproc_server, "/api/history", headers={"Cookie": cookie}
    )
    assert status == 400
    assert "storage unavailable" in payload["error"]


# ---------------------------------------------------------------------------
# GET /api/history/{id}
# ---------------------------------------------------------------------------


def test_history_get_returns_row(inproc_server, mock_history):
    mock_history["get"].return_value = {"id": "abc", "kind": "scan"}
    cookie = _login_cookie(inproc_server)
    status, payload, _ = _request(
        inproc_server, "/api/history/abc", headers={"Cookie": cookie}
    )
    assert status == 200, payload
    assert payload == {"id": "abc", "kind": "scan"}
    assert mock_history["get"].calls[-1]["args"][1] == "abc"


def test_history_get_404_when_missing(inproc_server, mock_history):
    mock_history["get"].return_value = None
    cookie = _login_cookie(inproc_server)
    status, payload, _ = _request(
        inproc_server, "/api/history/missing", headers={"Cookie": cookie}
    )
    assert status == 404
    assert payload == {"error": "not found"}


def test_history_get_400_on_storage_error(inproc_server, mock_history):
    mock_history["get"].side_effect = HistoryError("storage unavailable")
    cookie = _login_cookie(inproc_server)
    status, payload, _ = _request(
        inproc_server, "/api/history/abc", headers={"Cookie": cookie}
    )
    assert status == 400
    assert "storage unavailable" in payload["error"]


# ---------------------------------------------------------------------------
# POST /api/history
# ---------------------------------------------------------------------------


def test_history_post_creates_row(inproc_server, mock_history):
    mock_history["save"].return_value = {"id": "new", "kind": "run"}
    cookie = _login_cookie(inproc_server)
    body = {
        "kind": "run",
        "config": "tokamak",
        "inputs": {"q95": 3.0},
        "preset": "iter_like",
        "label": "my run",
        "summary": {"Qfus": 10.2},
    }
    status, payload, _ = _request(
        inproc_server,
        "/api/history",
        method="POST",
        body=body,
        headers={"Cookie": cookie},
    )
    assert status == 201, payload
    assert payload == {"id": "new", "kind": "run"}
    call = mock_history["save"].calls[-1]
    assert call["kwargs"]["kind"] == "run"
    assert call["kwargs"]["config"] == "tokamak"
    assert call["kwargs"]["inputs"] == {"q95": 3.0}
    assert call["kwargs"]["preset"] == "iter_like"
    assert call["kwargs"]["label"] == "my run"
    assert call["kwargs"]["summary"] == {"Qfus": 10.2}


def test_history_post_400_on_caller_error(inproc_server, mock_history):
    mock_history["save"].side_effect = HistoryError("inputs must be a JSON object")
    cookie = _login_cookie(inproc_server)
    status, payload, _ = _request(
        inproc_server,
        "/api/history",
        method="POST",
        body={"kind": "run", "config": "x", "inputs": {}},
        headers={"Cookie": cookie},
    )
    assert status == 400
    assert "inputs" in payload["error"]


def test_history_post_400_on_bad_json(inproc_server, mock_history):
    cookie = _login_cookie(inproc_server)
    # Raw broken JSON — bypass _request's json encoding.
    req = urllib.request.Request(
        f"http://127.0.0.1:{_port(inproc_server)}/api/history",
        data=b"{not json",
        method="POST",
        headers={"Cookie": cookie, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8")
    assert status == 400
    payload = json.loads(raw)
    assert "bad json" in payload["error"]
    assert not mock_history["save"].calls  # short-circuited before save


# ---------------------------------------------------------------------------
# DELETE /api/history/{id}
# ---------------------------------------------------------------------------


def test_history_delete_returns_ok(inproc_server, mock_history):
    cookie = _login_cookie(inproc_server)
    status, payload, _ = _request(
        inproc_server,
        "/api/history/abc",
        method="DELETE",
        headers={"Cookie": cookie},
    )
    assert status == 200, payload
    assert payload == {"ok": True}
    assert mock_history["delete"].calls[-1]["args"][1] == "abc"


def test_history_delete_404_when_missing(inproc_server, mock_history):
    mock_history["delete"].return_value = False
    cookie = _login_cookie(inproc_server)
    status, payload, _ = _request(
        inproc_server,
        "/api/history/missing",
        method="DELETE",
        headers={"Cookie": cookie},
    )
    assert status == 404
    assert payload == {"error": "not found"}


def test_history_delete_400_on_caller_error(inproc_server, mock_history):
    mock_history["delete"].side_effect = HistoryError("computation_id is required")
    cookie = _login_cookie(inproc_server)
    status, _, _ = _request(
        inproc_server,
        "/api/history/abc",
        method="DELETE",
        headers={"Cookie": cookie},
    )
    assert status == 400


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


def test_history_routes_require_auth(inproc_server, mock_history):
    """Every history verb 401s without a session cookie."""
    status, _, _ = _request(inproc_server, "/api/history")
    assert status == 401
    status, _, _ = _request(inproc_server, "/api/history/abc")
    assert status == 401
    status, _, _ = _request(
        inproc_server, "/api/history", method="POST", body={"kind": "run"}
    )
    assert status == 401
    status, _, _ = _request(inproc_server, "/api/history/abc", method="DELETE")
    assert status == 401
    # No history function should have been called.
    assert not mock_history["list"].calls
    assert not mock_history["get"].calls
    assert not mock_history["save"].calls
    assert not mock_history["delete"].calls


# ---------------------------------------------------------------------------
# CSRF gate
# ---------------------------------------------------------------------------


def test_history_post_cross_site_origin_blocked(inproc_server, mock_history):
    cookie = _login_cookie(inproc_server)
    status, payload, _ = _request(
        inproc_server,
        "/api/history",
        method="POST",
        body={"kind": "run"},
        headers={
            "Cookie": cookie,
            "Origin": "http://evil.example.com",
            "Host": f"127.0.0.1:{_port(inproc_server)}",
        },
    )
    assert status == 403
    assert payload == {"error": "cross-site blocked"}
    assert not mock_history["save"].calls
