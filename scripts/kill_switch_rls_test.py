#!/usr/bin/env python3
"""Kill-switch experiment for A6: urllib + user JWT + Supabase RLS.

This script verifies that a stdlib urllib request to Supabase PostgREST,
with headers:
    Authorization: Bearer <user_access_token>
    apikey:        <SUPABASE_ANON_KEY>
actually enforces Row Level Security using the real user identity.

It creates two test users and checks that each user can only read their own
row from the existing ``public.profiles`` table (RLS policy
``profiles_select_own``). No DDL or extra RPC is required, so the experiment
is safe to run against the live Supabase project.

Environment (read from shell or .env.subabase):
    SUPABASE_URL
    SUPABASE_ANON_KEY
    SUPABASE_SERVICE_ROLE_KEY

Run:
    python scripts/kill_switch_rls_test.py

Exit codes:
    0 = RLS isolation works (green light for v1.2 P2/P3)
    1 = any check failed (red light, rethink data access layer)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

# Allow the script to live one directory above polyfusion/.
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load_env(path: str) -> None:
    """Load KEY=VALUE pairs from a simple env file into os.environ."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            # Some env files have values that look like JWTs with no key=val
            # format; skip lines that don't parse as key=val cleanly.
            k, v = line.split("=", 1)
            k = k.strip()
            if k and k not in os.environ:
                os.environ[k] = v.strip().strip('"')


_load_env(os.path.join(ROOT, ".env"))
_load_env(os.path.join(ROOT, ".env.subabase"))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

if not SUPABASE_URL or not ANON_KEY or not SERVICE_ROLE_KEY:
    print("FATAL: SUPABASE_URL, SUPABASE_ANON_KEY and SUPABASE_SERVICE_ROLE_KEY required")
    sys.exit(1)

# Try to import supabase for admin/user-management helpers only.
# The actual kill-switch HTTP calls use stdlib urllib.
try:
    from supabase import Client, create_client
except Exception as exc:  # pragma: no cover
    print(f"FATAL: supabase python client required for test setup: {exc}")
    sys.exit(1)

TEST_TABLE = "profiles"  # existing RLS-protected table


def _pg_rest_url(path: str) -> str:
    return f"{SUPABASE_URL}/rest/v1{path}"


def _auth_url(path: str) -> str:
    return f"{SUPABASE_URL}/auth/v1{path}"


def _request(
    url: str,
    *,
    token: str | None = None,
    method: str = "GET",
    body: dict | None = None,
    headers: dict | None = None,
    key: str | None = None,
) -> tuple[int, dict | list]:
    """Make a stdlib urllib request and return (status, json)."""
    req_headers = {
        "apikey": key or ANON_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        req_headers["Authorization"] = f"Bearer {token}"
    if headers:
        req_headers.update(headers)

    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(
        url, data=data, headers=req_headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body_text)
        except Exception:
            payload = {"raw": body_text}
        return exc.code, payload


def create_user(admin: Client, email: str, password: str, username: str) -> str:
    """Create a confirmed user via admin API and return user id."""
    resp = admin.auth.admin.create_user(
        {
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"username": username},
        }
    )
    return resp.user.id


def login_user(email: str, password: str) -> str:
    """Login via anon API and return access_token."""
    req = urllib.request.Request(
        _auth_url("/token?grant_type=password"),
        data=json.dumps({"email": email, "password": password}).encode("utf-8"),
        headers={
            "apikey": ANON_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["access_token"]


def list_profiles(user_token: str) -> list[dict]:
    """List profiles visible to the given user token via stdlib urllib."""
    status, body = _request(
        _pg_rest_url(f"/{TEST_TABLE}?select=id,username,email"),
        token=user_token,
    )
    if status != 200:
        print(f"FATAL: select failed: {status} {body}")
        sys.exit(1)
    return body if isinstance(body, list) else []


def cleanup(admin: Client, user_a: str, user_b: str) -> None:
    """Delete test users (profile rows cascade)."""
    for uid in (user_a, user_b):
        try:
            admin.auth.admin.delete_user(uid)
        except Exception:
            pass


def main() -> int:
    print("=" * 60)
    print("Kill-switch experiment: urllib + user JWT + Supabase RLS")
    print("=" * 60)

    admin = create_client(SUPABASE_URL, SERVICE_ROLE_KEY)

    print("\n[PREFLIGHT] Checking that public.profiles exists...")
    status_pf, body_pf = _request(
        _pg_rest_url(f"/{TEST_TABLE}?select=id&limit=1"),
        token=SERVICE_ROLE_KEY,
    )
    if status_pf == 404:
        print(
            "FATAL: public.profiles is missing from the Supabase project.\n"
            "       Apply supabase/schema.sql in the Supabase Dashboard SQL Editor,\n"
            "       then re-run this experiment."
        )
        return 1
    if status_pf not in (200, 401, 403):
        print(f"FATAL: preflight check failed: {status_pf} {body_pf}")
        return 1
    print("       public.profiles is present.")

    suffix = uuid.uuid4().hex[:8]
    email_a = f"ks_a_{suffix}@example.com"
    email_b = f"ks_b_{suffix}@example.com"
    username_a = f"ks_a_{suffix}"
    username_b = f"ks_b_{suffix}"
    password = "KillSwitch123!"

    user_a = user_b = ""
    try:
        print("\n[1/5] Creating test users (with usernames)...")
        user_a = create_user(admin, email_a, password, username_a)
        user_b = create_user(admin, email_b, password, username_b)
        print(f"       user_a={user_a}")
        print(f"       user_b={user_b}")
        # Give the trigger a moment to provision profile rows.
        time.sleep(0.5)

        print("[2/5] Logging in test users (stdlib urllib)...")
        token_a = login_user(email_a, password)
        token_b = login_user(email_b, password)
        print("       token_a and token_b obtained")

        print("[3/5] Querying profiles via stdlib urllib...")
        rows_a = list_profiles(token_a)
        rows_b = list_profiles(token_b)

        usernames_a = {r.get("username") for r in rows_a}
        usernames_b = {r.get("username") for r in rows_b}

        print(f"       user_a sees: {usernames_a}")
        print(f"       user_b sees: {usernames_b}")

        print("[4/5] Checking isolation...")
        ok = True
        if username_b in usernames_a:
            print(f"FAIL: user_a can see user_b's profile ({username_b})")
            ok = False
        if username_a in usernames_b:
            print(f"FAIL: user_b can see user_a's profile ({username_a})")
            ok = False
        if username_a not in usernames_a:
            print("FAIL: user_a cannot see their own profile")
            ok = False
        if username_b not in usernames_b:
            print("FAIL: user_b cannot see their own profile")
            ok = False

        # Anonymous / no token requests must not leak any rows. Supabase has two
        # acceptable behaviours depending on the project's auth config:
        #   * strict:  401/403 (anon role rejected at the API gateway), or
        #   * lax:     200 with an empty array (anon role reaches Postgres, but
        #              RLS policies `to authenticated` filter everything out).
        # Both are safe as long as no rows are returned.
        status_noauth, body_noauth = _request(
            _pg_rest_url(f"/{TEST_TABLE}?select=id,username,email"), token=None
        )
        noauth_rows = body_noauth if isinstance(body_noauth, list) else None
        if status_noauth in (401, 403):
            print(f"       unauthenticated request rejected ({status_noauth})")
        elif status_noauth == 200 and noauth_rows == []:
            print("       unauthenticated request returned 200 with empty list (anon RLS filter)")
        else:
            print(f"FAIL: unauthenticated request returned {status_noauth}: {body_noauth}")
            ok = False

        print("[5/5] Checking service-role key bypasses RLS...")
        status_sr, body_sr = _request(
            _pg_rest_url(f"/{TEST_TABLE}?select=id,username,email"),
            token=SERVICE_ROLE_KEY,
        )
        if status_sr != 200:
            print(f"WARN: service-role select returned {status_sr}: {body_sr}")
            print("      (this is informational; service-role bypass is expected)")
        else:
            sr_rows = body_sr if isinstance(body_sr, list) else []
            print(f"       service-role sees {len(sr_rows)} profile rows (expected: ≥2)")

        if ok:
            print("\nPASS: RLS isolation works with stdlib urllib + user JWT.")
            print("A6 path is GREEN. Proceed with v1.2 P2/P3 implementation.")
            return 0
        else:
            print("\nFAIL: RLS isolation broken.")
            print("A6 path is RED. Do not proceed with urllib+JWT architecture.")
            return 1

    finally:
        print("\n[CLEANUP] Removing test users...")
        cleanup(admin, user_a, user_b)
        print("       done")


if __name__ == "__main__":
    sys.exit(main())
