"""HTTP tests for v1.2 guest mode + tiered compute rate limits.

Covers the P0 backend slice: when ``GUEST_MODE`` is on, unauthenticated
callers reach ``/api/run`` / ``/api/scan`` / ``/api/tokamak/parse_eqdsk``
as guests under a stricter per-IP quota, while auth-only routes
(/api/history, /api/admin) still 401. Authenticated callers get the larger
per-user quota.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import app.server as srv
from app.server import Handler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def guest_server(monkeypatch):
    """Server with both REQUIRE_AUTH and GUEST_MODE on (the v1.2 default)."""
    monkeypatch.setattr(srv, "REQUIRE_AUTH", True)
    monkeypatch.setattr(srv, "GUEST_MODE", True)
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


@pytest.fixture
def strict_server(monkeypatch):
    """Server with GUEST_MODE off — pre-v1.2 strict auth posture."""
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
# HTTP helpers (trimmed from test_server_history.py)
# ---------------------------------------------------------------------------


def _port(server) -> int:
    return server.server_port


def _post(server, path, body, headers=None):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{_port(server)}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
            hdrs = resp.headers
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        status = exc.code
        hdrs = exc.headers
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = raw
    return status, payload, hdrs


def _get(server, path, headers=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{_port(server)}{path}",
        method="GET",
        headers=dict(headers or {}),
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
            hdrs = resp.headers
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        status = exc.code
        hdrs = exc.headers
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = raw
    return status, payload, hdrs


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


def _login_cookie(server, email="guest-test@example.com", password="password1"):
    _post(
        server,
        "/api/auth/register",
        body={
            "username": "guesttest",
            "email": email,
            "password": password,
            "password2": password,
        },
    )
    _, _, hdrs = _post(
        server,
        "/api/auth/login",
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
# /api/meta
# ---------------------------------------------------------------------------


def test_meta_reports_guest_mode_on(guest_server):
    status, payload, _ = _get(guest_server, "/api/meta")
    assert status == 200
    assert payload["guest_mode"] is True
    assert payload["auth_required"] is True


def test_meta_reports_guest_mode_off(strict_server):
    status, payload, _ = _get(strict_server, "/api/meta")
    assert status == 200
    assert payload["guest_mode"] is False


def test_guest_mode_me_returns_guest_identity(guest_server):
    status, payload, _ = _get(guest_server, "/api/auth/me")
    assert status == 200
    assert payload == {
        "user_id": "__guest__",
        "user": "__guest__",
        "email": None,
        "email_verified": False,
        "affiliation": None,
        "is_admin": False,
    }


# ---------------------------------------------------------------------------
# Strict mode (GUEST_MODE off): no cookie → 401
# ---------------------------------------------------------------------------


def test_strict_mode_run_401_without_cookie(strict_server):
    status, payload, _ = _post(strict_server, "/api/run", {"config": "tokamak"})
    assert status == 401
    assert payload.get("auth_required") is True


# ---------------------------------------------------------------------------
# Guest mode: compute allowed without cookie; auth-only routes still 401
# ---------------------------------------------------------------------------


def test_guest_mode_run_allowed_without_cookie(guest_server):
    """Guests can hit /api/run — they get a real computation back."""
    status, payload, _ = _post(
        guest_server,
        "/api/run",
        {"config": "tokamak", "preset": "ITER"},
    )
    assert status == 200, payload
    # Sanity: it's a real tokamak output, not an auth error.
    assert isinstance(payload, dict)
    assert payload.get("config") == "tokamak"


def test_guest_mode_scan_admits_guest(guest_server):
    """Guests pass the principal gate on /api/scan (no 401).

    Body shape isn't important — the rate-limit + auth gate runs before
    compute. We assert the call is NOT 401 (guest admitted) rather than
    chasing a valid scan body.
    """
    status, _, _ = _post(
        guest_server,
        "/api/scan",
        {"config": "tokamak"},
    )
    assert status != 401, "guest should pass the auth gate"


def test_guest_mode_history_still_requires_auth(guest_server):
    """Auth-only routes do NOT admit guests — /api/history still 401."""
    status, _, _ = _get(guest_server, "/api/history")
    assert status == 401
    status, _, _ = _post(
        guest_server, "/api/history", {"kind": "run", "config": "x", "inputs": {}}
    )
    assert status == 401


def test_guest_mode_admin_still_requires_auth(guest_server):
    status, _, _ = _get(guest_server, "/api/admin/stats")
    assert status == 401
    status, _, _ = _get(guest_server, "/api/admin/users")
    assert status == 401


# ---------------------------------------------------------------------------
# Tiered rate limits
# ---------------------------------------------------------------------------


def test_guest_compute_rate_limit_kicks_in(guest_server):
    """Guests hit GUEST_COMPUTE_LIMIT/min and get 429 on the next call."""
    body = {"config": "tokamak", "preset": "ITER"}
    for i in range(srv.GUEST_COMPUTE_LIMIT):
        status, _, _ = _post(guest_server, "/api/run", body)
        assert status == 200, f"call {i} should succeed, got {status}"
    status, payload, _ = _post(guest_server, "/api/run", body)
    assert status == 429
    assert payload["role"] == "guest"
    assert payload["quota_per_min"] == srv.GUEST_COMPUTE_LIMIT


def test_authenticated_compute_rate_limit_is_higher(guest_server):
    """Logged-in users get USER_COMPUTE_LIMIT/min — strictly more than guest."""
    cookie = _login_cookie(guest_server)
    body = {"config": "tokamak", "preset": "ITER"}
    # Exhaust the guest quota, then prove the authenticated bucket is separate.
    for _ in range(srv.GUEST_COMPUTE_LIMIT):
        _post(guest_server, "/api/run", body)  # guest bucket
    # Authenticated caller should still be well under their quota.
    status, _, _ = _post(guest_server, "/api/run", body, headers={"Cookie": cookie})
    assert status == 200
    # And driving past GUEST_COMPUTE_LIMIT as guest stays blocked.
    status, payload, _ = _post(guest_server, "/api/run", body)
    assert status == 429
    assert payload["role"] == "guest"


def test_authenticated_compute_rate_limit_kicks_in(guest_server):
    """Eventually the authenticated bucket also fills up."""
    cookie = _login_cookie(guest_server)
    body = {"config": "tokamak", "preset": "ITER"}
    for i in range(srv.USER_COMPUTE_LIMIT):
        status, _, _ = _post(guest_server, "/api/run", body, headers={"Cookie": cookie})
        assert status == 200, f"call {i} should succeed, got {status}"
    status, payload, _ = _post(
        guest_server, "/api/run", body, headers={"Cookie": cookie}
    )
    assert status == 429
    assert payload["role"] == "user"
    assert payload["quota_per_min"] == srv.USER_COMPUTE_LIMIT


def test_auth_mutation_rate_limit_unchanged(guest_server):
    """Auth endpoints still use _RATE_LIMIT_MAX=10/min/IP (independent of guest/user)."""
    for i in range(srv._RATE_LIMIT_MAX):
        status, _, _ = _post(
            guest_server,
            "/api/auth/resend",
            {"email": f"victim{i}@example.com"},
        )
        assert status == 200, f"attempt {i} should be allowed"
    status, payload, _ = _post(
        guest_server,
        "/api/auth/resend",
        {"email": "overflow@example.com"},
    )
    assert status == 429
    assert payload == {"error": "rate limit exceeded"}
