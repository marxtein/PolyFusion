"""Minimal local web server for the PolyFusion (option A, confirmed stack).

Stdlib only (no Flask): serves a single Plotly page and exposes the
config-agnostic compute core over a narrow JSON API.  Works for every
configuration in ``polyfusion.configs.REGISTRY`` (tokamak, mirror, …).

    python app/server.py            # then open http://127.0.0.1:8765

Optional request logging for AI/automated testing, controlled by env var
``POLYFUSION_LOG``: unset/``0``/``off`` (default, quiet), ``1``/``stdout``,
``stderr``, or any other string treated as a file path to append JSONL.
Each line is one JSON record with ``ts``, ``event``, ``method``, ``path``,
``status``, ``duration_ms`` and (for /api/run, /api/scan) semantic fields
like ``config``, ``preset``, ``valid``, ``Qfus``, ``n_invalid``.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import unquote, urlparse

# Cap BLAS threads BEFORE numpy loads.  On this Windows numpy build the OpenBLAS
# threaded path is pathologically slow for medium matrices — a 121x121
# linalg.solve (near-axis r2) took ~0.6 s multi-threaded vs ~0.4 ms
# single-threaded (~1300x).  Every matrix here is tiny, so single-threaded BLAS
# is strictly faster and numerically identical.  setdefault keeps any user override.
for _v in (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from polyfusion.io import run_case, list_configs  # noqa: E402
from polyfusion.configs.base import get, REGISTRY  # noqa: E402
from polyfusion.scan import scan2d, best_region_mask  # noqa: E402
from polyfusion.equilibrium_import import (  # noqa: E402
    MAX_FILE_BYTES,
    parse_equilibrium_bytes,
)
from polyfusion import eqdsk  # noqa: E402
from polyfusion import auth as auth_mod  # noqa: E402
from polyfusion.auth import AuthError  # noqa: E402
from polyfusion.docs_generator import generate_manual  # noqa: E402
from polyfusion.report_generator import generate_report  # noqa: E402
from polyfusion import history as history_mod  # noqa: E402
from polyfusion import admin as admin_mod  # noqa: E402
from polyfusion.history import HistoryError  # noqa: E402
from polyfusion.admin import AdminError  # noqa: E402
from polyfusion.postgrest import PostgrestError  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8765))

REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "1") != "0"
USE_HTTPS = os.environ.get("USE_HTTPS", "0") == "1"
# When True (default), unauthenticated callers are treated as "guests" on
# compute routes and subject to a stricter per-IP quota. When False, those
# routes 401 as before. Auth-only routes (/api/history, /api/admin) ignore
# this and always require a real session.
GUEST_MODE = os.environ.get("GUEST_MODE", "1") == "1"

# Two-cookie session design:
#   - ACCESS_COOKIE  is sent on every request (Path=/) and validated locally
#                    via JWT; Max-Age matches Supabase's default 1h access TTL.
#   - REFRESH_COOKIE is scoped to Path=/api/auth so it only travels on auth
#                    endpoints, where ``validate_session`` may use it to mint
#                    a new access token near expiry.
ACCESS_COOKIE = "polyfusion_session"
REFRESH_COOKIE = "polyfusion_refresh"
ACCESS_COOKIE_MAX_AGE = 3600

# Simple in-memory rate limiting.
#   - auth mutation endpoints (/api/auth/*): keyed by IP, _RATE_LIMIT_MAX / min
#   - compute endpoints (/api/run, /api/scan, /api/tokamak/parse_eqdsk):
#     tiered — authenticated users get USER_COMPUTE_LIMIT/min keyed by user_id,
#     guests get GUEST_COMPUTE_LIMIT/min keyed by IP (stricter).
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW = 60  # seconds
GUEST_COMPUTE_LIMIT = 20
USER_COMPUTE_LIMIT = 60
_RATE_LIMIT: dict[str, tuple[int, float]] = {}
_RATE_LIMIT_LOCK = threading.Lock()

# Report bodies carry 1-3 base64 PNGs; cap at 20 MiB to keep the service
# responsive (matches the equilibrium import ceiling's order of magnitude).
MAX_REPORT_BYTES = 20 * 1024 * 1024

# Optional JSONL request log for AI/automated testing.
#   POLYFUSION_LOG=              -> silent (default)
#   POLYFUSION_LOG=1|true|stdout -> stdout
#   POLYFUSION_LOG=stderr        -> stderr
#   POLYFUSION_LOG=<path>        -> append JSONL to that file
_LOG_RAW = os.environ.get("POLYFUSION_LOG", "").strip()
_LOG_DEST_LC = _LOG_RAW.lower()
_LOG_OFF = _LOG_DEST_LC in ("", "0", "off", "false", "no")


def _log(event, **fields):
    """Emit one JSONL record when POLYFUSION_LOG is enabled; else no-op."""
    if _LOG_OFF:
        return
    rec = {"ts": round(time.time(), 6), "event": event, **fields}
    line = json.dumps(rec, default=str, ensure_ascii=False) + "\n"
    try:
        if _LOG_DEST_LC in ("1", "true", "yes", "stdout"):
            sys.stdout.write(line)
            sys.stdout.flush()
        elif _LOG_DEST_LC == "stderr":
            sys.stderr.write(line)
            sys.stderr.flush()
        else:
            with open(_LOG_RAW, "a", encoding="utf-8") as fh:
                fh.write(line)
    except OSError:
        pass


PROTECTED_PATHS = {
    "/api/run",
    "/api/scan",
    "/api/tokamak/parse_eqdsk",
}

# Refresh cookie has the same charset contract as the access cookie (both are
# opaque token strings supplied by Supabase).
_COOKIE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.\-]{8,4096}$")


def _cookie_for_tokens(access: str, refresh: str) -> tuple[str, str]:
    """Build the two Set-Cookie headers for a freshly issued session."""
    access_flags = (
        f"{ACCESS_COOKIE}={access}; Path=/; HttpOnly; SameSite=Lax; "
        f"Max-Age={ACCESS_COOKIE_MAX_AGE}"
    )
    refresh_flags = (
        f"{REFRESH_COOKIE}={refresh}; Path=/api/auth; HttpOnly; SameSite=Strict; "
        f"Max-Age={7 * 24 * 3600}"
    )
    if USE_HTTPS:
        access_flags += "; Secure"
        refresh_flags += "; Secure"
    return access_flags, refresh_flags


def _clear_auth_cookies() -> list[str]:
    """Set-Cookie headers that wipe both auth cookies from the browser."""
    access_flags = f"{ACCESS_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
    refresh_flags = (
        f"{REFRESH_COOKIE}=; Path=/api/auth; HttpOnly; SameSite=Strict; Max-Age=0"
    )
    if USE_HTTPS:
        access_flags += "; Secure"
        refresh_flags += "; Secure"
    return [access_flags, refresh_flags]


def _parse_refresh_cookie(cookie_header: Optional[str]) -> Optional[str]:
    """Return the ``polyfusion_refresh`` cookie value or ``None``."""
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        k, v = part.strip().split("=", 1)
        if k == REFRESH_COOKIE and _COOKIE_TOKEN_RE.match(v):
            return v
    return None


def _check_origin(headers) -> bool:
    """Same-host CSRF gate for POST requests.

    Returns True when the request is same-site (or has no Origin/Referer at
    all, which is the case for non-browser clients and direct HTTP calls).
    Returns False only when an explicit cross-site Origin or Referer header
    is present and does not match the request's Host.
    """
    host = headers.get("Host")
    if not host:
        return True
    for name in ("Origin", "Referer"):
        val = headers.get(name)
        if not val:
            continue
        # Strip scheme; tolerate leading "://" if scheme is missing.
        rest = val
        if "://" in rest:
            rest = rest.split("://", 1)[1]
        # Everything up to the first '/' or '?' or '#' is host[:port].
        host_part = rest
        for ch in ("/", "?", "#"):
            idx = host_part.find(ch)
            if idx != -1:
                host_part = host_part[:idx]
        # userinfo '@' would precede host; drop it.
        if "@" in host_part:
            host_part = host_part.rsplit("@", 1)[1]
        if host_part == host:
            continue
        return False
    return True


def _check_rate_limit(
    key: str,
    limit: int = _RATE_LIMIT_MAX,
    window: int = _RATE_LIMIT_WINDOW,
) -> bool:
    """Return True if the caller (identified by ``key``) may proceed.

    ``key`` is the rate-limit bucket — typically a client IP for unauthenticated
    traffic or a user_id for authenticated traffic. ``limit`` / ``window``
    default to the auth-mutation quota (10/min/IP); compute routes pass
    explicit values for the tiered quotas.
    """
    now = time.time()
    with _RATE_LIMIT_LOCK:
        # Lazy cleanup of expired entries.
        expired = [k for k, (count, reset) in _RATE_LIMIT.items() if now > reset]
        for k in expired:
            del _RATE_LIMIT[k]
        count, reset = _RATE_LIMIT.get(key, (0, now + window))
        if now > reset:
            count = 0
            reset = now + window
        if count >= limit:
            return False
        _RATE_LIMIT[key] = (count + 1, reset)
    return True


def _client_ip(headers) -> str:
    """Best-effort client IP for rate limiting."""
    forwarded = headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return headers.get("X-Real-Ip") or "unknown"


def _floatify(d: dict) -> dict:
    """Coerce incoming numerics to float (keep icase int).

    JS serialises large values like 6.81e19 as integer literals; Python's json
    parses those as arbitrary-precision ints exceeding int64, which makes numpy
    build object-dtype arrays and breaks float ops.  Cast at the boundary.
    """
    out = {}
    for k, v in (d or {}).items():
        if k == "icase":
            out[k] = int(v)
        elif isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def _do_scan(req: dict) -> dict:
    config = req.get("config", "tokamak")
    spec = get(config)
    base = dict(spec.presets[req["preset"]]) if req.get("preset") else {}
    base.update(_floatify(req.get("overrides")))
    xk, yk = req["xkey"], req["ykey"]
    xv = np.linspace(float(req["xmin"]), float(req["xmax"]), int(req["nx"]))
    yv = np.linspace(float(req["ymin"]), float(req["ymax"]), int(req["ny"]))
    g = scan2d(spec, base, xk, yk, xv, yv)
    win = req.get("window")
    if win and (win.get("ge") or win.get("le")):
        ge = {k: float(v) for k, v in (win.get("ge") or {}).items()}
        le = {k: float(v) for k, v in (win.get("le") or {}).items()}
        mask = best_region_mask(g, ge=ge, le=le)
    else:
        mask = best_region_mask(g, **spec.best_window)
    fields = [c["f"] for c in spec.contour_spec if c["f"] in g]

    def _jsonsafe(arr):
        """NaN/inf -> null: invalid points render as holes, and strict JSON
        parsers (the browser) do not choke on bare NaN tokens."""
        a = np.real(np.asarray(arr, dtype=float))
        return np.where(np.isfinite(a), a.astype(object), None).tolist()

    n_invalid = int(np.sum(np.asarray(g["valid"]) < 0.5)) if "valid" in g else 0
    return {
        "config": config,
        "xkey": xk,
        "ykey": yk,
        "x": xv.tolist(),
        "y": yv.tolist(),
        # transpose (nx,ny)->(ny,nx) so Plotly reads z[y][x]
        "fields": {k: _jsonsafe(g[k].T) for k in fields},
        "best": mask.T.astype(int).tolist(),
        "valid": _jsonsafe(g["valid"].T) if "valid" in g else None,
        "n_invalid": n_invalid,
        "scan_errors": g.get("scan_errors", {}),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    # ---- response helpers -------------------------------------------------

    def _begin_request(self):
        """Mark request start (for timing) and reset the API summary."""
        self._t0 = time.time()
        self._api_summary = {}

    def _send(
        self,
        code,
        body,
        ctype="application/json",
        cache_control="no-store, max-age=0",
        set_cookie=None,
    ):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache_control)
        if set_cookie:
            # ``set_cookie`` may be a single string or a list of strings; emit
            # one Set-Cookie header per entry so both auth cookies can be
            # written in a single response.
            cookies = [set_cookie] if isinstance(set_cookie, str) else set_cookie
            for c in cookies:
                if c:
                    self.send_header("Set-Cookie", c)
        self.end_headers()
        self.wfile.write(data)
        _log(
            "http",
            method=getattr(self, "command", "?"),
            path=self.path,
            status=code,
            bytes=len(data),
            duration_ms=round(
                (time.time() - getattr(self, "_t0", time.time())) * 1000, 3
            ),
            **getattr(self, "_api_summary", {}),
        )

    def _send_file(
        self, fpath, ctype=None, cache_control="public, max-age=31536000, immutable"
    ):
        with open(fpath, "rb") as fh:
            data = fh.read()
        return self._send(
            200,
            data,
            ctype or mimetypes.guess_type(fpath)[0] or "application/octet-stream",
            cache_control=cache_control,
        )

    # ---- auth helpers -----------------------------------------------------

    def _current_user(self) -> Optional[str]:
        """Return the authenticated user id (``__anon__`` when auth is off).

        When the session is valid, both tokens are cached on the handler
        instance so ``/api/auth/logout`` can revoke them without re-parsing
        the cookie jar.
        """
        if not REQUIRE_AUTH:
            return "__anon__"
        cookie = self.headers.get("Cookie")
        access = auth_mod.parse_session_cookie(cookie)
        refresh = _parse_refresh_cookie(cookie)
        user_id = auth_mod.validate_session(access, refresh)
        if user_id:
            self._access_token = access
            self._refresh_token = refresh
            return user_id
        return None

    def _require_auth(self):
        """Return the authenticated username, or send 401 and return None."""
        user = self._current_user()
        if not user:
            self._send(
                401,
                json.dumps({"error": "unauthorized", "auth_required": True}),
            )
            return None
        return user

    def _principal(self):
        """Return ``(principal, role)`` for compute-route authorization.

        - Authenticated caller → ``(user_id, "user")``
        - Unauthenticated caller + GUEST_MODE → ``("__guest__", "guest")``
        - Unauthenticated caller + no GUEST_MODE → ``(None, None)``

        Always consults ``_current_user`` so a valid session's
        ``_access_token`` is cached for downstream handlers.
        """
        user = self._current_user()
        if user:
            return user, "user"
        if GUEST_MODE:
            return "__guest__", "guest"
        return None, None

    # ---- GET --------------------------------------------------------------

    def do_GET(self):
        self._begin_request()
        if self.path in ("/", "/index.html"):
            return self._send_file(
                os.path.join(HERE, "index.html"),
                "text/html; charset=utf-8",
                cache_control="no-cache",
            )
        if self.path.startswith("/vendor/"):
            name = os.path.basename(unquote(self.path))
            fpath = os.path.join(HERE, "vendor", name)
            if os.path.isfile(fpath):
                return self._send_file(fpath)
            return self._send(404, json.dumps({"error": "vendor asset not found"}))
        if self.path == "/api/meta":
            return self._send(
                200,
                json.dumps(
                    {
                        "configs": list_configs(),
                        "auth_required": REQUIRE_AUTH,
                        "guest_mode": GUEST_MODE,
                    }
                ),
            )
        if self.path == "/api/auth/me":
            if not REQUIRE_AUTH:
                return self._send(
                    200,
                    json.dumps(
                        {
                            "user": "__anon__",
                            "email": None,
                            "email_verified": False,
                        }
                    ),
                )
            cookie = self.headers.get("Cookie")
            access = auth_mod.parse_session_cookie(cookie)
            info = auth_mod.get_user(access)
            if info is None:
                return self._send(401, json.dumps({"error": "unauthorized"}))
            return self._send(
                200,
                json.dumps(
                    {
                        "user": info.get("username"),
                        "email": info.get("email"),
                        "email_verified": bool(info.get("email_verified")),
                    }
                ),
            )
        # Strip the query string before matching — GET /api/history?limit=...
        # arrives here as a single ``self.path`` and would otherwise miss an
        # equality check against the bare path.
        _path_only = urlparse(self.path).path
        if _path_only == "/api/history" or _path_only.startswith("/api/history/"):
            return self._handle_history_get()
        if _path_only == "/api/admin/stats":
            return self._handle_admin_stats()
        if _path_only == "/api/admin/users":
            return self._handle_admin_users()
        if self.path.startswith("/api/manual"):
            return self._handle_manual()
        if self.path == "/api/equilibria":
            # manifest of bundled real equilibrium files, keyed by config+preset
            mpath = os.path.join(HERE, "equilibria", "manifest.json")
            if os.path.isfile(mpath):
                return self._send_file(mpath, cache_control="no-cache")
            return self._send(200, json.dumps({}))
        if self.path.startswith("/equilibria/"):
            if not REQUIRE_AUTH or self._current_user():
                # serve a bundled equilibrium file (binary). Restrict to the two
                # known config subdirs + a plain basename to block path traversal.
                parts = unquote(self.path).strip("/").split("/")
                if len(parts) == 3 and parts[1] in ("tokamak", "stellarator"):
                    name = os.path.basename(parts[2])
                    fpath = os.path.join(HERE, "equilibria", parts[1], name)
                    if os.path.isfile(fpath) and os.path.commonpath(
                        [os.path.realpath(fpath), os.path.join(HERE, "equilibria")]
                    ) == os.path.realpath(os.path.join(HERE, "equilibria")):
                        return self._send_file(fpath, "application/octet-stream")
            return self._send(404, json.dumps({"error": "equilibrium not found"}))
        return self._send(404, json.dumps({"error": "not found"}))

    # ---- POST -------------------------------------------------------------

    def do_POST(self):
        self._begin_request()
        # CSRF gate: every POST must come from the same host (or carry no
        # Origin/Referer at all, which is the case for non-browser clients).
        if not _check_origin(self.headers):
            return self._send(403, json.dumps({"error": "cross-site blocked"}))

        n = int(self.headers.get("Content-Length", 0))

        # --- auth routes (always public) ---
        if self.path == "/api/auth/register":
            return self._handle_auth_register(n)
        if self.path == "/api/auth/login":
            return self._handle_auth_login(n)
        if self.path == "/api/auth/logout":
            return self._handle_auth_logout()
        if self.path == "/api/auth/resend":
            return self._handle_auth_resend(n)

        if self.path == "/api/stellarator/equilibrium/preview":
            if not self._require_auth():
                return None
            if n > MAX_FILE_BYTES:
                limit_mib = MAX_FILE_BYTES // (1024 * 1024)
                return self._send(
                    413,
                    json.dumps(
                        {"error": f"equilibrium file exceeds {limit_mib} MiB limit"}
                    ),
                )
            filename = unquote(self.headers.get("X-Filename", ""))
            try:
                out = parse_equilibrium_bytes(self.rfile.read(n), filename)
                body = json.dumps(out)
            except Exception as e:
                return self._send(
                    400, json.dumps({"error": f"{type(e).__name__}: {e}"})
                )
            return self._send(200, body)

        if self.path == "/api/report":
            # auth gate: report embeds user's compute results
            user = self._require_auth()
            if not user:
                return None
            if n > MAX_REPORT_BYTES:
                limit_mib = MAX_REPORT_BYTES // (1024 * 1024)
                return self._send(
                    413,
                    json.dumps({"error": f"report body exceeds {limit_mib} MiB limit"}),
                )
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
                req.setdefault("user", user)
                html_body = generate_report(req)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                return self._send(400, json.dumps({"error": f"bad json: {e}"}))
            except Exception as e:
                return self._send(
                    400, json.dumps({"error": f"{type(e).__name__}: {e}"})
                )
            return self._send(
                200,
                html_body,
                ctype="text/html; charset=utf-8",
                cache_control="no-store, max-age=0",
            )

        if self.path == "/api/history":
            return self._handle_history_post(n)

        # --- protected compute routes (allow guest when GUEST_MODE is on) ---
        if self.path in PROTECTED_PATHS:
            principal, role = self._principal()
            if principal is None:
                return self._send(
                    401,
                    json.dumps({"error": "unauthorized", "auth_required": True}),
                )
            # Tiered rate limit: authenticated → user_id bucket; guest → IP bucket.
            if role == "guest":
                bucket = f"guest:{_client_ip(self.headers)}"
                quota = GUEST_COMPUTE_LIMIT
            else:
                bucket = f"user:{principal}"
                quota = USER_COMPUTE_LIMIT
            if not _check_rate_limit(bucket, quota, _RATE_LIMIT_WINDOW):
                return self._send(
                    429,
                    json.dumps(
                        {
                            "error": "rate limit exceeded",
                            "role": role,
                            "quota_per_min": quota,
                        }
                    ),
                )

        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return self._send(400, json.dumps({"error": f"bad json: {e}"}))
        try:
            if self.path == "/api/tokamak/parse_eqdsk":
                g = eqdsk.parse_geqdsk(req.get("eqdsk") or "")
                out = {"config": "tokamak", "eq": eqdsk.equilibrium_geometry(g)}
                self._api_summary = {"config": "tokamak", "kind": "eqdsk"}
            elif self.path == "/api/run":
                out = run_case(
                    _floatify(req.get("overrides")),
                    preset=req.get("preset"),
                    config=req.get("config", "tokamak"),
                )
                outs = out.get("outputs") or {}
                self._api_summary = {
                    "config": out.get("config"),
                    "preset": req.get("preset"),
                    "valid": outs.get("valid"),
                    "Qfus": outs.get("Qfus"),
                    "had_errors": bool(out.get("errors")),
                }
            elif self.path == "/api/scan":
                out = _do_scan(req)
                self._api_summary = {
                    "config": out.get("config"),
                    "preset": req.get("preset"),
                    "n_invalid": out.get("n_invalid"),
                    "field_count": len(out.get("fields") or {}),
                }
            else:
                return self._send(404, json.dumps({"error": "not found"}))
            # numpy-safe: serialise inside the try so any encoding bug -> 400, not a crash
            body = json.dumps(
                out, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)
            )
        except Exception as e:
            return self._send(400, json.dumps({"error": f"{type(e).__name__}: {e}"}))
        return self._send(200, body)

    # ---- DELETE -----------------------------------------------------------

    def do_DELETE(self):
        self._begin_request()
        # CSRF gate: DELETE mutates server state, same origin policy as POST.
        if not _check_origin(self.headers):
            return self._send(403, json.dumps({"error": "cross-site blocked"}))

        if self.path.startswith("/api/history/"):
            return self._handle_history_delete()
        return self._send(404, json.dumps({"error": "not found"}))

    # ---- history handlers -------------------------------------------------

    def _history_access_token(self):
        """Return ``(access_token, user_id)`` after enforcing auth.

        Sets a 401/500 response on the wire and returns ``None`` on failure so
        handlers can early-return.
        """
        user = self._require_auth()
        if not user:
            return None
        token = getattr(self, "_access_token", None)
        if not token:
            return self._send(500, json.dumps({"error": "session token missing"}))
        return token, user

    def _handle_history_get(self):
        """GET /api/history (list) or /api/history/{id} (single row)."""
        creds = self._history_access_token()
        if creds is None:
            return None
        token, _user = creds

        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        # Strip the leading "/api/history/" prefix to extract the id, if any.
        suffix = (
            parsed.path[len("/api/history/") :] if parsed.path != "/api/history" else ""
        )
        if suffix:
            try:
                row = history_mod.get_history(token, suffix)
            except (HistoryError, PostgrestError) as e:
                return self._send(
                    500 if isinstance(e, PostgrestError) else 400,
                    json.dumps({"error": str(e)}),
                )
            if row is None:
                return self._send(404, json.dumps({"error": "not found"}))
            return self._send(200, json.dumps(row, default=str))

        try:
            limit = int(qs.get("limit", ["20"])[0])
        except ValueError:
            limit = history_mod.DEFAULT_LIMIT
        try:
            offset = int(qs.get("offset", ["0"])[0])
        except ValueError:
            offset = 0
        kind = qs.get("kind", [None])[0]

        try:
            total, rows = history_mod.list_history(
                token, limit=limit, offset=offset, kind=kind
            )
        except (HistoryError, PostgrestError) as e:
            return self._send(
                500 if isinstance(e, PostgrestError) else 400,
                json.dumps({"error": str(e)}),
            )
        return self._send(
            200,
            json.dumps(
                {"total": total, "limit": limit, "offset": offset, "rows": rows},
                default=str,
            ),
        )

    def _handle_history_post(self, n: int):
        """POST /api/history — save a run/scan computation."""
        creds = self._history_access_token()
        if creds is None:
            return None
        token, _user = creds
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return self._send(400, json.dumps({"error": f"bad json: {e}"}))

        try:
            row = history_mod.save_history(
                token,
                kind=req.get("kind"),
                config=req.get("config"),
                inputs=req.get("inputs") or {},
                preset=req.get("preset"),
                label=req.get("label"),
                summary=req.get("summary"),
                user_id=_user
                if isinstance(_user, str) and _user != "__anon__"
                else None,
            )
        except (HistoryError, PostgrestError) as e:
            return self._send(
                500 if isinstance(e, PostgrestError) else 400,
                json.dumps({"error": str(e)}),
            )
        return self._send(201, json.dumps(row, default=str))

    def _handle_history_delete(self):
        """DELETE /api/history/{id}."""
        creds = self._history_access_token()
        if creds is None:
            return None
        token, _user = creds
        from urllib.parse import urlparse

        path = urlparse(self.path).path
        comp_id = path[len("/api/history/") :]
        if not comp_id:
            return self._send(400, json.dumps({"error": "computation id required"}))
        try:
            deleted = history_mod.delete_history(token, comp_id)
        except (HistoryError, PostgrestError) as e:
            return self._send(
                500 if isinstance(e, PostgrestError) else 400,
                json.dumps({"error": str(e)}),
            )
        if not deleted:
            return self._send(404, json.dumps({"error": "not found"}))
        return self._send(200, json.dumps({"ok": True}))

    # ---- admin handlers ---------------------------------------------------

    def _handle_admin_stats(self):
        """GET /api/admin/stats — aggregate counts visible to the caller.

        RLS: admins see full counts; non-admins see only their own row
        reflected (treated as noise). Python does NOT branch on admin-ness.
        """
        creds = self._history_access_token()
        if creds is None:
            return None
        token, _user = creds
        try:
            out = admin_mod.stats(token)
        except (AdminError, PostgrestError) as e:
            return self._send(
                500 if isinstance(e, PostgrestError) else 400,
                json.dumps({"error": str(e)}),
            )
        return self._send(200, json.dumps(out, default=str))

    def _handle_admin_users(self):
        """GET /api/admin/users?limit=&offset= — paginated user list.

        Same RLS posture as stats: admins get every profile; non-admins get
        only their own (silently — no 403 to avoid existence leak).
        """
        creds = self._history_access_token()
        if creds is None:
            return None
        token, _user = creds
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(self.path).query)
        try:
            limit = int(qs.get("limit", [str(admin_mod.DEFAULT_LIMIT)])[0])
        except ValueError:
            limit = admin_mod.DEFAULT_LIMIT
        try:
            offset = int(qs.get("offset", ["0"])[0])
        except ValueError:
            offset = 0
        try:
            total, rows = admin_mod.list_users(token, limit=limit, offset=offset)
        except (AdminError, PostgrestError) as e:
            return self._send(
                500 if isinstance(e, PostgrestError) else 400,
                json.dumps({"error": str(e)}),
            )
        return self._send(
            200,
            json.dumps(
                {"total": total, "limit": limit, "offset": offset, "rows": rows},
                default=str,
            ),
        )

    # ---- auth handlers ----------------------------------------------------

    def _handle_auth_register(self, n: int):
        client_ip = _client_ip(self.headers)
        if not _check_rate_limit(client_ip, _RATE_LIMIT_MAX, _RATE_LIMIT_WINDOW):
            return self._send(429, json.dumps({"error": "rate limit exceeded"}))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return self._send(400, json.dumps({"error": f"bad json: {e}"}))

        username = req.get("username", "")
        password = req.get("password", "")
        password2 = req.get("password2", "")
        email = (req.get("email") or "").strip()

        # Require all four fields explicitly — Supabase auth is email-based, so
        # the legacy "username-only" fallback no longer applies.
        if not username or not email or not password or not password2:
            return self._send(
                400,
                json.dumps(
                    {"error": "username, email, password and password2 are required"}
                ),
            )

        try:
            result = auth_mod.register(username, email, password, password2)
        except AuthError as e:
            return self._send(400, json.dumps({"error": str(e)}))
        return self._send(
            200,
            json.dumps(
                {
                    "user": result.get("username"),
                    "email_verification_sent": bool(
                        result.get("email_verification_sent")
                    ),
                }
            ),
        )

    def _handle_auth_login(self, n: int):
        client_ip = _client_ip(self.headers)
        if not _check_rate_limit(client_ip, _RATE_LIMIT_MAX, _RATE_LIMIT_WINDOW):
            return self._send(429, json.dumps({"error": "rate limit exceeded"}))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return self._send(400, json.dumps({"error": f"bad json: {e}"}))
        email = (req.get("email") or "").strip()
        password = req.get("password", "")
        try:
            access, refresh, user = auth_mod.login(email, password)
        except AuthError as e:
            return self._send(401, json.dumps({"error": str(e)}))
        access_cookie, refresh_cookie = _cookie_for_tokens(access, refresh)
        return self._send(
            200,
            json.dumps({"ok": True, "user": user.get("username")}),
            set_cookie=[access_cookie, refresh_cookie],
        )

    def _handle_auth_logout(self):
        client_ip = _client_ip(self.headers)
        if not _check_rate_limit(client_ip, _RATE_LIMIT_MAX, _RATE_LIMIT_WINDOW):
            return self._send(429, json.dumps({"error": "rate limit exceeded"}))
        access = getattr(self, "_access_token", None) or auth_mod.parse_session_cookie(
            self.headers.get("Cookie")
        )
        refresh = getattr(self, "_refresh_token", None) or _parse_refresh_cookie(
            self.headers.get("Cookie")
        )
        # Best-effort: never block cookie cleanup on a Supabase outage.
        try:
            auth_mod.logout(access, refresh)
        except Exception:
            pass
        return self._send(
            200,
            json.dumps({"ok": True}),
            set_cookie=_clear_auth_cookies(),
        )

    def _handle_auth_resend(self, n: int):
        client_ip = _client_ip(self.headers)
        if not _check_rate_limit(client_ip, _RATE_LIMIT_MAX, _RATE_LIMIT_WINDOW):
            return self._send(429, json.dumps({"error": "rate limit exceeded"}))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return self._send(400, json.dumps({"error": f"bad json: {e}"}))
        email = (req.get("email") or "").strip()
        try:
            auth_mod.resend_verification(email)
        except AuthError as e:
            return self._send(400, json.dumps({"error": str(e)}))
        return self._send(200, json.dumps({"ok": True}))

    def _handle_manual(self):
        # /api/manual?config=tokamak&lang=zh  — public so docs render pre-login
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(self.path).query)
        config = (qs.get("config") or ["tokamak"])[0]
        lang = (qs.get("lang") or ["zh"])[0]
        if config not in REGISTRY:
            return self._send(404, json.dumps({"error": f"unknown config: {config}"}))
        if lang not in ("zh", "en"):
            lang = "zh"
        out = generate_manual(config, lang)
        return self._send(200, json.dumps(out, ensure_ascii=False))


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"PolyFusion serving at http://{HOST}:{PORT}  (Ctrl+C to stop)")
    _log("start", host=HOST, port=PORT, auth_required=REQUIRE_AUTH)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
