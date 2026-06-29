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


def _post(port: int, path: str, body: dict, cookies=None):
    import urllib.request

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        _base(port) + path, data=data, headers={"Content-Type": "application/json"}
    )
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
        port, "/api/auth/register", {"username": "tester", "password": "password1"}
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

    # /api/auth/me reports the user
    status, body = _get(port, "/api/auth/me", cookies=sess)
    assert status == 200
    assert json.loads(body)["user"] == "tester"

    # protected route now works with cookie
    status, body, _c = _post(port, "/api/run", {"config": "tokamak"}, cookies=sess)
    assert status == 200, body


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
        port, "/api/auth/register", {"username": "shortpw", "password": "x"}
    )
    assert status == 400
    assert "password" in json.loads(body)["error"]


def test_logout_clears_session(server):
    port = server["port"]
    _post(port, "/api/auth/register", {"username": "leaver", "password": "password1"})
    _status, _b, cookie = _post(
        port, "/api/auth/login", {"username": "leaver", "password": "password1"}
    )
    sess = cookie.split(";")[0]
    status, _b, clear_cookie = _post(port, "/api/auth/logout", {}, cookies=sess)
    assert status == 200
    assert "Max-Age=0" in clear_cookie
    # session token no longer validates
    status, body = _get(port, "/api/auth/me", cookies=sess)
    assert json.loads(body)["user"] is None
