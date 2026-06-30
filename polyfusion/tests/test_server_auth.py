"""HTTP-layer auth tests against app/server.py via urllib.

We start the real server on a random port with REQUIRE_AUTH=1 and a temp
POLYFUSION_HOME, then exercise register/login/protected-route/cookie flow.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"server on :{port} did not come up")


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    home = tmp_path_factory.mktemp("polyfusion_home")
    port = _free_port()
    env = {
        "PATH": __import__("os").environ.get("PATH", ""),
        "POLYFUSION_HOME": str(home),
        "REQUIRE_AUTH": "1",
        "PORT": str(port),
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "app" / "server.py")],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for(port)
        yield {"port": port, "home": home}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _base(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _post(port: int, path: str, body: dict, cookies=None, headers=None):
    import urllib.request

    data = json.dumps(body).encode()
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(_base(port) + path, data=data, headers=h)
    if cookies:
        req.add_header("Cookie", cookies)
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status, resp.read().decode(), resp.headers.get("Set-Cookie")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers.get("Set-Cookie")


def _get(port: int, path: str, cookies=None):
    import urllib.request

    req = urllib.request.Request(_base(port) + path)
    if cookies:
        req.add_header("Cookie", cookies)
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_meta_reports_auth_required(server):
    port = server["port"]
    status, body = _get(port, "/api/meta")
    assert status == 200
    assert json.loads(body)["auth_required"] is True


def test_protected_run_without_auth_returns_401(server):
    port = server["port"]
    status, _body, _c = _post(port, "/api/run", {"config": "tokamak"})
    assert status == 401


def test_register_login_protected_flow(server):
    port = server["port"]

    status, _b, _c = _post(
        port,
        "/api/auth/register",
        {
            "username": "tester",
            "password": "password1",
            "email": "tester@example.com",
            "password2": "password1",
        },
    )
    assert status == 200

    status, _body, cookie = _post(
        port, "/api/auth/login", {"username": "tester", "password": "password1"}
    )
    assert status == 200
    assert cookie and "polyfusion_session=" in cookie
    assert "HttpOnly" in cookie

    # extract just the cookie pair for re-sending
    sess = cookie.split(";")[0]

    # /api/auth/me reports the user and email fields
    status, body = _get(port, "/api/auth/me", cookies=sess)
    assert status == 200
    data = json.loads(body)
    assert data["user"] == "tester"
    assert data["email"] == "tester@example.com"
    assert data["email_verified"] is False

    # protected route now works with cookie
    status, body, _c = _post(port, "/api/run", {"config": "tokamak"}, cookies=sess)
    assert status == 200, body


def test_register_requires_all_fields(server):
    port = server["port"]
    base = {
        "username": "missingfields",
        "password": "password1",
        "email": "missing@example.com",
        "password2": "password1",
    }
    for key in base:
        body = {k: v for k, v in base.items() if k != key}
        status, resp, _c = _post(
            port,
            "/api/auth/register",
            body,
            headers={"X-Forwarded-For": f"10.0.0.{hash(key) % 256}"},
        )
        assert status == 400, f"missing {key} should return 400"
        assert "error" in json.loads(resp)


def test_login_wrong_password_returns_401(server):
    port = server["port"]
    _post(port, "/api/auth/register", {"username": "badpw", "password": "password1"})
    status, _body, cookie = _post(
        port, "/api/auth/login", {"username": "badpw", "password": "wrong"}
    )
    assert status == 401
    # failed login must NOT set a session cookie
    assert (
        cookie is None
        or "polyfusion_session=" not in cookie
        or "Max-Age=0" in (cookie or "")
    )


def test_register_rejects_short_password(server):
    port = server["port"]
    status, body, _c = _post(
        port,
        "/api/auth/register",
        {
            "username": "shortpw",
            "password": "x",
            "email": "shortpw@example.com",
            "password2": "x",
        },
        headers={"X-Forwarded-For": "10.0.0.2"},
    )
    assert status == 400
    assert "password" in json.loads(body)["error"]


def test_register_rejects_invalid_email(server):
    port = server["port"]
    status, body, _c = _post(
        port,
        "/api/auth/register",
        {
            "username": "bademail",
            "password": "password1",
            "email": "not-an-email",
            "password2": "password1",
        },
        headers={"X-Forwarded-For": "10.0.0.3"},
    )
    assert status == 400
    assert "email" in json.loads(body)["error"]


def test_register_rejects_password_mismatch(server):
    port = server["port"]
    status, body, _c = _post(
        port,
        "/api/auth/register",
        {
            "username": "mismatch",
            "password": "password1",
            "email": "mismatch@example.com",
            "password2": "different",
        },
        headers={"X-Forwarded-For": "10.0.0.4"},
    )
    assert status == 400
    assert "password" in json.loads(body)["error"]


def test_register_duplicate_returns_generic_error(server):
    port = server["port"]
    _post(
        port,
        "/api/auth/register",
        {
            "username": "dupuser",
            "password": "password1",
            "email": "dup@example.com",
            "password2": "password1",
        },
        headers={"X-Forwarded-For": "10.0.0.5"},
    )
    status, body, _c = _post(
        port,
        "/api/auth/register",
        {
            "username": "dupuser2",
            "password": "password1",
            "email": "dup@example.com",
            "password2": "password1",
        },
        headers={"X-Forwarded-For": "10.0.0.5"},
    )
    assert status == 400
    error = json.loads(body)["error"].lower()
    assert "username" not in error
    assert "email" not in error


def test_register_rate_limit(server):
    port = server["port"]
    # Use a unique client IP so earlier tests in the module do not exhaust the
    # shared in-memory rate limit bucket for this endpoint.
    extra_headers = {"X-Forwarded-For": "10.0.0.1"}

    for i in range(11):
        status, body, _c = _post(
            port,
            "/api/auth/register",
            {
                "username": f"rate{i}",
                "password": "password1",
                "email": f"rate{i}@example.com",
                "password2": "password1",
            },
            headers=extra_headers,
        )
        if i < 10:
            assert status == 200, body
        else:
            assert status == 429, body


def test_anonymous_mode_me_returns_null_email(tmp_path_factory):
    home = tmp_path_factory.mktemp("polyfusion_home_anon")
    port = _free_port()
    env = {
        "PATH": __import__("os").environ.get("PATH", ""),
        "POLYFUSION_HOME": str(home),
        "REQUIRE_AUTH": "0",
        "PORT": str(port),
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "app" / "server.py")],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for(port)
        status, body = _get(port, "/api/auth/me")
        assert status == 200
        data = json.loads(body)
        assert data["user"] == "__anon__"
        assert data["email"] is None
        assert data["email_verified"] is False
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_logout_clears_session(server):
    port = server["port"]
    _post(
        port,
        "/api/auth/register",
        {
            "username": "leaver",
            "password": "password1",
            "email": "leaver@example.com",
            "password2": "password1",
        },
        headers={"X-Forwarded-For": "10.0.0.6"},
    )
    _status, _b, cookie = _post(
        port,
        "/api/auth/login",
        {"username": "leaver", "password": "password1"},
        headers={"X-Forwarded-For": "10.0.0.6"},
    )
    sess = cookie.split(";")[0]
    status, _b, clear_cookie = _post(port, "/api/auth/logout", {}, cookies=sess)
    assert status == 200
    assert "Max-Age=0" in clear_cookie
    # session token no longer validates
    status, body = _get(port, "/api/auth/me", cookies=sess)
    assert json.loads(body)["user"] is None
