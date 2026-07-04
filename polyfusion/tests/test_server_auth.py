"""HTTP-layer auth tests for the Supabase-adapter server routes.

Drives ``app/server.py`` through an in-process ``ThreadingHTTPServer`` so the
autouse ``FakeSupabase`` fixture from ``conftest.py`` (which patches
``polyfusion.auth.supabase_client`` in this very process) is visible to the
handler threads. A subprocess would defeat the monkeypatch.

Coverage:
    - ``/api/auth/register`` 4-field requirement + success envelope.
    - ``/api/auth/login`` sets both access and refresh cookies.
    - ``/api/auth/me`` honours the cookie and returns the user shape.
    - ``/api/auth/logout`` clears both cookies.
    - ``/api/auth/resend`` succeeds for a known email.
    - CSRF: a cross-site ``Origin`` header is rejected with 403.
    - Rate limit: the 11th call within the window is throttled with 429.
    - ``REQUIRE_AUTH=0`` exposes an anonymous ``/api/auth/me``.
    - A protected compute route (``/api/run``) 401s without a cookie.
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
# In-process server fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def inproc_server(monkeypatch):
    """Spin up the real handler against a ThreadingHTTPServer bound to :0.

    The autouse ``_fake_supabase`` conftest fixture already installs the
    FakeSupabase client into ``polyfusion.auth``, so handler threads see it
    via the lazy ``supabase_client()`` singleton. The rate-limit bucket is
    reset between tests so the global state doesn't leak.

    GUEST_MODE is forced off here so this file's pre-guest-mode assertions
    (e.g. ``/api/run`` 401s without a cookie) still hold; guest behaviour
    lives in ``test_server_guest.py``.
    """
    # Force the auth gate on for these tests; individual tests opt back out.
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


def _post(server, path, body, headers=None):
    """POST JSON. Returns (status, parsed_json_or_text, header_dict)."""
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
    """GET. Returns (status, parsed_json_or_text, header_dict)."""
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
    """Collect every Set-Cookie value into a name->value dict."""
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


def _register_and_login(server, email="alice@example.com", password="password1"):
    """Register then log in, returning the Cookie header value for the session."""
    _post(
        server,
        "/api/auth/register",
        {
            "username": "alice",
            "email": email,
            "password": password,
            "password2": password,
        },
    )
    _, _, hdrs = _post(
        server,
        "/api/auth/login",
        {"email": email, "password": password},
    )
    cookies = _cookies_from_headers(hdrs)
    parts = []
    if srv.ACCESS_COOKIE in cookies:
        parts.append(f"{srv.ACCESS_COOKIE}={cookies[srv.ACCESS_COOKIE]}")
    if srv.REFRESH_COOKIE in cookies:
        parts.append(f"{srv.REFRESH_COOKIE}={cookies[srv.REFRESH_COOKIE]}")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


def test_register_requires_all_four_fields(inproc_server):
    base = {
        "username": "bob",
        "email": "bob@example.com",
        "password": "pw1",
        "password2": "pw1",
    }
    for missing in ("username", "email", "password", "password2"):
        body = dict(base)
        body.pop(missing)
        status, payload, _ = _post(inproc_server, "/api/auth/register", body)
        assert status == 400, (
            f"missing {missing} should be 400, got {status}: {payload}"
        )
        assert isinstance(payload, dict) and "error" in payload


def test_register_success_returns_user_and_verification_flag(inproc_server):
    status, payload, _ = _post(
        inproc_server,
        "/api/auth/register",
        {
            "username": "carol",
            "email": "carol@example.com",
            "password": "supersecret",
            "password2": "supersecret",
        },
    )
    assert status == 200, payload
    assert payload["user"] == "carol"
    assert isinstance(payload["email_verification_sent"], bool)


def test_register_accepts_affiliation(inproc_server, fake):
    status, payload, _ = _post(
        inproc_server,
        "/api/auth/register",
        {
            "username": "affuser",
            "email": "aff@example.com",
            "password": "supersecret",
            "password2": "supersecret",
            "affiliation": "ASIPP",
        },
    )
    assert status == 200, payload
    assert fake.auth.users["aff@example.com"]["affiliation"] == "ASIPP"


def test_register_without_email_confirmation_allows_login(
    inproc_server, fake, monkeypatch, tmp_path
):
    monkeypatch.setenv("POLYFUSION_REQUIRE_EMAIL_CONFIRMATION", "0")
    monkeypatch.setenv("POLYFUSION_LOCAL_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    status, payload, _ = _post(
        inproc_server,
        "/api/auth/register",
        {
            "username": "localweb",
            "email": "localweb@example.com",
            "password": "supersecret",
            "password2": "supersecret",
            "affiliation": "ASIPP",
        },
    )
    assert status == 200, payload
    assert payload["email_verification_sent"] is False
    assert "localweb@example.com" not in fake.auth.users

    status, payload, hdrs = _post(
        inproc_server,
        "/api/auth/login",
        {"email": "localweb@example.com", "password": "supersecret"},
    )
    assert status == 200, payload
    cookies = _cookies_from_headers(hdrs)
    cookie_header = f"{srv.ACCESS_COOKIE}={cookies[srv.ACCESS_COOKIE]}"
    status, me, _ = _get(
        inproc_server,
        "/api/auth/me",
        headers={"Cookie": cookie_header},
    )
    assert status == 200, me
    assert me["user"] == "localweb"
    assert me["affiliation"] == "ASIPP"


def test_debug_register_hidden_by_default(inproc_server):
    status, payload, _ = _post(
        inproc_server,
        "/api/debug/auth/register",
        {
            "username": "debuguser",
            "email": "debug@example.com",
            "password": "supersecret",
            "password2": "supersecret",
        },
    )
    assert status == 404
    assert payload == {"error": "not found"}


def test_debug_register_creates_verified_session(inproc_server, fake, monkeypatch):
    monkeypatch.setattr(srv, "DEBUG_AUTH", True)

    def fake_debug_register(username, email, password, password2, *, affiliation=None):
        old = fake.auth.confirm_email_on
        fake.auth.confirm_email_on = False
        try:
            return srv.auth_mod.register(
                username,
                email,
                password,
                password2,
                affiliation=affiliation,
            )
        finally:
            fake.auth.confirm_email_on = old

    monkeypatch.setattr(srv.auth_mod, "debug_create_verified_user", fake_debug_register)
    status, payload, hdrs = _post(
        inproc_server,
        "/api/debug/auth/register",
        {
            "username": "debuguser",
            "email": "debug@example.com",
            "password": "supersecret",
            "password2": "supersecret",
            "affiliation": "ASIPP",
        },
    )
    assert status == 200, payload
    assert payload["ok"] is True
    assert payload["debug"] is True
    assert payload["email_verification_sent"] is False
    cookies = _cookies_from_headers(hdrs)
    cookie_header = f"{srv.ACCESS_COOKIE}={cookies[srv.ACCESS_COOKIE]}"
    status, me, _ = _get(
        inproc_server,
        "/api/auth/me",
        headers={"Cookie": cookie_header},
    )
    assert status == 200, me
    assert me["user"] == "debuguser"
    assert me["email"] == "debug@example.com"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_sets_both_cookies(inproc_server):
    cookie_header = _register_and_login(inproc_server)
    assert srv.ACCESS_COOKIE in cookie_header
    assert srv.REFRESH_COOKIE in cookie_header


def test_login_returns_ok_and_username(inproc_server):
    _post(
        inproc_server,
        "/api/auth/register",
        {
            "username": "dave",
            "email": "dave@example.com",
            "password": "supersecret",
            "password2": "supersecret",
        },
    )
    status, payload, hdrs = _post(
        inproc_server,
        "/api/auth/login",
        {"email": "dave@example.com", "password": "supersecret"},
    )
    assert status == 200, payload
    assert payload == {"ok": True, "user": "dave"}
    cookies = _cookies_from_headers(hdrs)
    assert srv.ACCESS_COOKIE in cookies
    assert srv.REFRESH_COOKIE in cookies


def test_login_wrong_password_returns_401(inproc_server):
    _post(
        inproc_server,
        "/api/auth/register",
        {
            "username": "erin",
            "email": "erin@example.com",
            "password": "supersecret",
            "password2": "supersecret",
        },
    )
    status, payload, _ = _post(
        inproc_server,
        "/api/auth/login",
        {"email": "erin@example.com", "password": "wrong-password"},
    )
    assert status == 401
    assert "error" in payload


# ---------------------------------------------------------------------------
# /api/auth/me
# ---------------------------------------------------------------------------


def test_me_without_cookie_returns_401(inproc_server):
    status, payload, _ = _get(inproc_server, "/api/auth/me")
    assert status == 401
    assert "error" in payload


def test_me_with_cookie_returns_user_info(inproc_server):
    cookie_header = _register_and_login(inproc_server, email="frank@example.com")
    status, payload, _ = _get(
        inproc_server,
        "/api/auth/me",
        headers={"Cookie": cookie_header},
    )
    assert status == 200, payload
    assert payload["user_id"]
    assert payload["user"] == "alice"
    assert payload["email"] == "frank@example.com"
    assert "email_verified" in payload
    assert payload["affiliation"] is None
    assert payload["is_admin"] is False


def test_me_returns_affiliation(inproc_server):
    _post(
        inproc_server,
        "/api/auth/register",
        {
            "username": "ivan",
            "email": "ivan@example.com",
            "password": "supersecret",
            "password2": "supersecret",
            "affiliation": "ASIPP",
        },
    )
    _, _, hdrs = _post(
        inproc_server,
        "/api/auth/login",
        {"email": "ivan@example.com", "password": "supersecret"},
    )
    cookies = _cookies_from_headers(hdrs)
    cookie_header = f"{srv.ACCESS_COOKIE}={cookies[srv.ACCESS_COOKIE]}"
    status, payload, _ = _get(
        inproc_server,
        "/api/auth/me",
        headers={"Cookie": cookie_header},
    )
    assert status == 200, payload
    assert payload["affiliation"] == "ASIPP"


def test_me_uses_profile_row_for_admin_flag(inproc_server, monkeypatch):
    cookie_header = _register_and_login(inproc_server, email="admin@example.com")
    calls = []

    def fake_get_profile(access_token, user_id):
        calls.append((access_token, user_id))
        return {"affiliation": "ASIPP Admin", "is_admin": True}

    monkeypatch.setattr(srv.profile_mod, "get_profile", fake_get_profile)
    status, payload, _ = _get(
        inproc_server,
        "/api/auth/me",
        headers={"Cookie": cookie_header},
    )
    assert status == 200, payload
    assert calls and calls[0][1] == payload["user_id"]
    assert payload["affiliation"] == "ASIPP Admin"
    assert payload["is_admin"] is True


def test_me_anonymous_when_require_auth_off(inproc_server, monkeypatch):
    monkeypatch.setattr(srv, "REQUIRE_AUTH", False)
    status, payload, _ = _get(inproc_server, "/api/auth/me")
    assert status == 200
    assert payload == {
        "user_id": "__anon__",
        "user": "__anon__",
        "email": None,
        "email_verified": False,
        "affiliation": None,
        "is_admin": False,
    }


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def test_logout_clears_both_cookies(inproc_server):
    cookie_header = _register_and_login(inproc_server, email="gina@example.com")
    status, payload, hdrs = _post(
        inproc_server,
        "/api/auth/logout",
        {},
        headers={"Cookie": cookie_header},
    )
    assert status == 200, payload
    assert payload == {"ok": True}
    # Both cookies must be present in the response with Max-Age=0; the
    # name->value helper drops attributes, so assert on the raw header lines.
    raw = hdrs.get_all("Set-Cookie") or []
    joined = "\n".join(raw)
    assert srv.ACCESS_COOKIE in joined
    assert srv.REFRESH_COOKIE in joined
    assert "Max-Age=0" in joined


def test_delete_account_removes_user_and_clears_cookies(
    inproc_server, fake, monkeypatch
):
    cookie_header = _register_and_login(inproc_server, email="deleteme@example.com")

    def fake_delete_current_account(access_token):
        resp = fake.auth.get_user(access_token)
        assert resp and resp.user
        del fake.auth.users[resp.user.email]

    monkeypatch.setattr(
        srv.profile_mod, "delete_current_account", fake_delete_current_account
    )
    status, payload, hdrs = _post(
        inproc_server,
        "/api/auth/delete",
        {},
        headers={"Cookie": cookie_header},
    )
    assert status == 200, payload
    assert payload == {"ok": True}
    raw = "\n".join(hdrs.get_all("Set-Cookie") or [])
    assert srv.ACCESS_COOKIE in raw
    assert srv.REFRESH_COOKIE in raw
    assert "Max-Age=0" in raw

    status, payload, _ = _post(
        inproc_server,
        "/api/auth/login",
        {"email": "deleteme@example.com", "password": "password1"},
    )
    assert status == 401
    assert "error" in payload


# ---------------------------------------------------------------------------
# Resend
# ---------------------------------------------------------------------------


def test_resend_returns_ok_for_known_email(inproc_server):
    _register_and_login(inproc_server, email="hank@example.com")
    status, payload, _ = _post(
        inproc_server,
        "/api/auth/resend",
        {"email": "hank@example.com"},
    )
    assert status == 200, payload
    assert payload == {"ok": True}


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


def test_cross_site_origin_blocked(inproc_server):
    status, payload, _ = _post(
        inproc_server,
        "/api/auth/login",
        {"email": "x@example.com", "password": "x"},
        headers={
            "Origin": "http://evil.example.com",
            "Host": f"127.0.0.1:{_port(inproc_server)}",
        },
    )
    assert status == 403
    assert payload == {"error": "cross-site blocked"}


def test_same_site_origin_allowed(inproc_server):
    """A same-host Origin must not trip the CSRF gate (regression guard)."""
    port = _port(inproc_server)
    status, _, _ = _post(
        inproc_server,
        "/api/auth/login",
        {"email": "x@example.com", "password": "x"},
        headers={
            "Origin": f"http://127.0.0.1:{port}",
            "Host": f"127.0.0.1:{port}",
        },
    )
    # Auth fails with 401 (no such user) — but NOT 403.
    assert status == 401


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


def test_rate_limit_kicks_in_after_window_quota(inproc_server):
    """The 11th auth POST inside the 60s window is throttled with 429."""
    for i in range(10):
        status, _, _ = _post(
            inproc_server,
            "/api/auth/resend",
            {"email": f"victim{i}@example.com"},
        )
        assert status == 200, f"attempt {i} should be allowed"
    status, payload, _ = _post(
        inproc_server,
        "/api/auth/resend",
        {"email": "overflow@example.com"},
    )
    assert status == 429
    assert payload == {"error": "rate limit exceeded"}


# ---------------------------------------------------------------------------
# Protected compute route
# ---------------------------------------------------------------------------


def test_protected_run_route_401_without_cookie(inproc_server):
    status, payload, _ = _post(
        inproc_server,
        "/api/run",
        {"config": "tokamak"},
    )
    assert status == 401
    assert payload.get("auth_required") is True
