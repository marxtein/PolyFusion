"""Stdlib urllib forwarder for Supabase PostgREST profile/admin data.

The web process never uses ``supabase-py`` for profile data access. Instead it
forwards the user's access token — together with the anon ``apikey`` header
Supabase requires — straight to PostgREST via ``urllib``. RLS then sees the real
``auth.uid()`` and enforces isolation in SQL.

Public surface used by ``app/server.py``:
    - ``pg_rest(path, *, access_token, method='GET', query=None, body=None)``
      -> ``(status, payload)`` where ``payload`` is the decoded JSON (list for
      collection GETs, dict for single-row / RPC / error responses).

The module reads ``SUPABASE_URL`` and ``SUPABASE_ANON_KEY`` from the
environment. The service-role key is intentionally NOT supported here.

Error model:
    - Network errors raise ``PostgrestError``.
    - HTTP non-2xx responses are returned as ``(status, payload)`` so the
      caller can map them to HTTP responses without a try/except ladder.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

__all__ = ["pg_rest", "PostgrestError", "PostgrestResponse"]


class PostgrestError(RuntimeError):
    """Raised when PostgREST cannot be reached or returns non-JSON."""


# Type alias for readability: ``(http_status, decoded_json_body)``.
PostgrestResponse = tuple[int, Any]


def _config() -> tuple[str, str]:
    """Return ``(base_url, anon_key)`` from the environment.

    Raises ``PostgrestError`` with a clear message if either is missing, so
    the caller can surface a 500 instead of a confusing AttributeError later.
    """
    base_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if not base_url or not anon_key:
        raise PostgrestError(
            "SUPABASE_URL and SUPABASE_ANON_KEY must both be set in the "
            "environment before calling pg_rest()."
        )
    return base_url, anon_key


def pg_rest(
    path: str,
    *,
    access_token: str,
    method: str = "GET",
    query: Mapping[str, str] | None = None,
    body: Any | None = None,
    base_url: str | None = None,
    apikey: str | None = None,
    timeout: float = 30.0,
    prefer: str | None = None,
) -> PostgrestResponse:
    """Forward one request to Supabase PostgREST with the user's JWT.

    Parameters
    ----------
    path:
        Path suffix starting with ``/`` (e.g. ``"/computations"``). The
        caller is responsible for any PostgREST query string (``?select=``,
        ``?id=eq.``...) — pass it as part of ``path``.
    access_token:
        The end user's Supabase access token. Used as the Bearer credential
        so RLS sees the real user. Never the service-role key.
    method:
        HTTP verb. Defaults to ``GET``.
    query:
        Optional dict of query parameters. Each value is URL-encoded and
        appended to ``path``. Use this for structured params; raw query
        strings should be embedded in ``path`` directly.
    body:
        Optional JSON-serialisable request body (for POST/PATCH/PUT).
    base_url, apikey:
        Override the env-derived Supabase URL / anon key. Tests use these
        to point at a FakeSupabase or local Supabase instance.
    timeout:
        Per-request timeout in seconds. Default 30.
    prefer:
        Optional ``Prefer`` header value (e.g. ``"return=representation"``).
        Defaults to ``"return=representation"`` for mutating methods, ``None``
        for GET/DELETE.

    Returns
    -------
    (status, payload)
        ``status`` is the HTTP status code. ``payload`` is the decoded JSON
        body (list for collection GETs, dict or list for mutations depending
        on the Prefer header, dict for error responses).

    Raises
    ------
    PostgrestError
        Network failure, timeout, or non-JSON response body.
    """
    if not access_token:
        raise PostgrestError("pg_rest() requires a non-empty access_token.")

    base, default_anon = _config()
    base_url = base_url or base
    apikey = apikey or default_anon

    # Build the full URL. ``path`` may already contain a query string; only
    # append ``query`` params when provided.
    url = f"{base_url}/rest/v1{path}"
    if query:
        qs = urllib.parse.urlencode(query)
        url = f"{url}?{qs}" if "?" not in url else f"{url}&{qs}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "apikey": apikey,
        "Accept": "application/json",
    }
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if prefer is not None:
        headers["Prefer"] = prefer
    elif method.upper() in {"POST", "PATCH", "PUT"}:
        headers["Prefer"] = "return=representation"

    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as exc:
        # PostgREST errors are JSON bodies with status 4xx/5xx — surface them
        # to the caller so it can map to its own response code.
        raw = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    except urllib.error.URLError as exc:
        raise PostgrestError(f"network error contacting PostgREST: {exc}") from exc

    if not raw:
        return status, None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PostgrestError(
            f"PostgREST returned non-JSON body (status={status}): {raw[:200]!r}"
        ) from exc
    return status, payload
