#!/usr/bin/env python3
"""Migrate legacy local users.json into Supabase Auth.

For each legacy user (email may be null — those are skipped with a warning):
1. ``admin.create_user({email, email_confirm: True, password: <random 32 bytes>})``
   — creates the auth.users row with a throwaway password the user will never
   use, and marks the email verified so Supabase does not send a confirmation
   email at this step.
2. ``admin.generate_link({type: "recovery", email})`` — triggers Supabase to
   send the user a "Reset Password" email using the project's configured
   template. The user clicks the link and chooses their own password; the
   throwaway password is then discarded by Supabase.

State is recorded per email in ``migration_state.json`` so re-runs are
idempotent: a user already present in the state file is skipped, and a user
that already existed in Supabase is recorded as ``skipped_existing``.

The script reads ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY`` from the
environment. The service-role key is the only privileged credential in the
project and is loaded **exclusively** by this one-shot process — never by
``app/server.py`` or any module under ``polyfusion/``. Importing this module
from the web process is forbidden by project policy; see ``CLAUDE.md`` and
``supabase/README.md``.

Exit codes:
    0 — every emailable user was migrated (or already recorded in state).
    2 — partial failure; see stderr / the log lines for details.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any, Iterable

# Supabase + errors. These imports are intentionally top-level: this script is
# the one place that talks to the admin API, and a missing dependency should
# fail fast with a clear message rather than a deferred AttributeError.
from supabase import Client, create_client
from supabase_auth.errors import AuthApiError, AuthRetryableError

# httpx is shipped transitively with supabase-py; imported for the network
# error branch of the retry ladder.
try:
    import httpx as _httpx
except Exception:  # pragma: no cover - httpx always present with supabase
    _httpx = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Free-tier Supabase auth email cap is ~3 / hour. We migrate in batches: after
# every ``BATCH_THRESHOLD`` users we sleep ``BATCH_SLEEP_SECONDS`` so the next
# batch falls outside the rolling 1-hour window.
BATCH_THRESHOLD = 3
BATCH_SLEEP_SECONDS = 1800

# Retry ladder for retryable errors (network / 5xx). 1s, 2s, 4s.
RETRY_BACKOFFS = (1.0, 2.0, 4.0)

# Where the legacy users.json lives by default. Resolved lazily so tests can
# pass an explicit path.
DEFAULT_USERS_JSON = Path.home() / ".polyfusion" / "users.json"
DEFAULT_STATE_PATH = Path("migration_state.json")

LOG = logging.getLogger("migrate_users")


# ---------------------------------------------------------------------------
# Admin client construction
# ---------------------------------------------------------------------------


def _admin_client() -> Any:
    """Build a Supabase admin client from the service-role key in env.

    This is the ONLY construction site for the admin client. Tests monkeypatch
    this function to inject a fake admin without touching the network.

    Raises ``SystemExit`` with a clear message if either env var is missing.
    """
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must both be set in the "
            "environment. The service-role key is loaded ONLY by this script — "
            "never put it in /root/polyfusion.env or app/server.py."
        )
    client: Client = create_client(url, key)
    return client.auth.admin


# ---------------------------------------------------------------------------
# Legacy users.json parsing
# ---------------------------------------------------------------------------


def _iter_legacy_users(raw: Any) -> Iterable[dict]:
    """Yield user record dicts from the legacy users.json payload.

    Supports two on-disk shapes so the script is robust to how the legacy
    ``UserStore`` (or any hand-edited file) laid users out:

    - A dict keyed by username/email whose values are user dicts, e.g.
      ``{"alice": {"email": "a@x", "hash": "..."}, ...}``. The key itself is
      treated as the username when the value does not already carry one.
    - A bare list of user dicts.

    Records that are not dicts are skipped with a warning.
    """
    if isinstance(raw, dict):
        # Heuristic: if every value is itself a dict, treat as a keyed user map.
        if all(isinstance(v, dict) for v in raw.values()):
            for key, value in raw.items():
                rec = dict(value)
                rec.setdefault("username", key)
                yield rec
        else:
            # A flat user record stored at top level (single user). Rare but
            # worth tolerating.
            yield raw
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                yield item
            else:
                LOG.warning("skipping non-dict entry in users list: %r", item)
    else:
        LOG.warning("users.json is not a dict or list; nothing to migrate")


# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"migrated": {}, "skipped_existing": {}, "errors": {}}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"state file {path} is unreadable: {exc}")
    data.setdefault("migrated", {})
    data.setdefault("skipped_existing", {})
    data.setdefault("errors", {})
    return data


def _save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _is_done(state: dict, email: str) -> bool:
    return email in state.get("migrated", {}) or email in state.get(
        "skipped_existing", {}
    )


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


def _is_already_registered(exc: Exception) -> bool:
    """True when ``exc`` is an AuthApiError signalling the user already exists.

    Supabase surfaces this as ``code == 'user_already_exists'`` /
    ``user_already_registered`` or as a message containing the same phrases.
    """
    if not isinstance(exc, AuthApiError):
        return False
    code = (getattr(exc, "code", "") or "").lower()
    message = (getattr(exc, "message", "") or "").lower()
    return (
        "user_already" in code
        or "already registered" in message
        or "already been registered" in message
        or "unique" in code
    )


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, AuthRetryableError):
        return True
    if _httpx is not None and isinstance(exc, _httpx.HTTPError):
        return True
    return False


# ---------------------------------------------------------------------------
# Migration core
# ---------------------------------------------------------------------------


def _migrate_one(
    admin: Any,
    email: str,
    *,
    dry_run: bool,
) -> dict:
    """Migrate a single email. Returns the state record fragment.

    On dry run, returns ``{"dry_run": True}`` without calling Supabase. The
    caller still records the email so the dry-run state file matches a real
    run's state file shape (useful for diffing).
    """
    if dry_run:
        LOG.info("[dry-run] would create_user + generate_link for %s", email)
        return {"dry_run": True}

    password = secrets.token_urlsafe(32)
    resp = admin.create_user(
        {
            "email": email,
            "password": password,
            "email_confirm": True,
        }
    )
    user = getattr(resp, "user", None)
    user_id = getattr(user, "id", None) if user is not None else None

    # create_user does NOT send any email. generate_link with type=recovery
    # causes Supabase to send the project's "Reset Password" template, which is
    # what the user actually needs to choose their own password.
    admin.generate_link({"type": "recovery", "email": email})

    return {
        "user_id": user_id,
        "migrated_at": time.time(),
    }


def _migrate_one_with_retry(
    admin: Any,
    email: str,
    *,
    dry_run: bool,
) -> dict:
    """Wrap ``_migrate_one`` with the retry ladder for retryable errors.

    Returns the state fragment. Raises only on non-retryable, non-already-
    registered errors (the caller decides how to record those).
    """
    if dry_run:
        return _migrate_one(admin, email, dry_run=True)

    last_exc: Exception | None = None
    for attempt, backoff in enumerate((0.0, *RETRY_BACKOFFS), start=1):
        if backoff:
            time.sleep(backoff)
        try:
            return _migrate_one(admin, email, dry_run=False)
        except Exception as exc:  # noqa: BLE001 - classified below
            last_exc = exc
            if _is_already_registered(exc):
                # Not retryable; bubble up so caller records skipped_existing.
                raise
            if _is_retryable(exc) and attempt <= len(RETRY_BACKOFFS):
                LOG.warning(
                    "attempt %d for %s failed (%s); retrying",
                    attempt,
                    email,
                    exc,
                )
                continue
            # Non-retryable, non-already-registered: bubble up.
            raise
    # Should be unreachable; the loop either returns or raises.
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def migrate(
    users: Iterable[dict],
    *,
    admin: Any,
    state: dict,
    dry_run: bool,
    batch_threshold: int,
    batch_sleep: float,
) -> int:
    """Migrate an iterable of user dicts, mutating ``state`` in place.

    Returns the number of users that failed (0 means a clean run).
    """
    failures = 0
    processed_since_sleep = 0
    emailable = [u for u in users if isinstance(u, dict) and u.get("email")]
    total_emailable = len(emailable)
    # Index of the next emailable user in iteration order, used to decide
    # whether a post-batch sleep is worthwhile (no point sleeping if no more
    # users remain in this run).
    emailable_index = 0

    if not dry_run and batch_threshold > 0 and len(emailable) > batch_threshold:
        LOG.warning(
            "%d users to migrate exceeds the free-tier batch threshold of %d; "
            "the script will sleep %.0fs after every %d users to respect the "
            "Supabase ~3 emails/hour limit. Upgrade to Pro or pass "
            "--batch-size 0 to disable.",
            len(emailable),
            batch_threshold,
            batch_sleep,
            batch_threshold,
        )

    for rec in emailable:
        emailable_index += 1
        email = rec["email"]
        if not isinstance(email, str) or not email.strip():
            LOG.warning("skipping entry with non-string email: %r", rec)
            continue
        email = email.strip()
        if _is_done(state, email):
            LOG.info("skip (already in state): %s", email)
            continue

        try:
            fragment = _migrate_one_with_retry(admin, email, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 - recorded, not raised
            if _is_already_registered(exc):
                LOG.info("already exists in Supabase, skipping: %s", email)
                state["skipped_existing"][email] = {
                    "noticed_at": time.time(),
                    "message": str(exc)[:200],
                }
            else:
                failures += 1
                LOG.error("failed to migrate %s after retries: %s", email, exc)
                state["errors"][email] = {
                    "failed_at": time.time(),
                    "message": str(exc)[:200],
                }
            continue

        if dry_run:
            state.setdefault("migrated", {})[email] = fragment
        else:
            state["migrated"][email] = fragment
            LOG.info("migrated: %s", email)

        processed_since_sleep += 1
        more_remaining = emailable_index < total_emailable
        if (
            not dry_run
            and batch_threshold > 0
            and processed_since_sleep >= batch_threshold
            and more_remaining
        ):
            LOG.warning(
                "batch threshold reached; sleeping %.0fs before next batch",
                batch_sleep,
            )
            time.sleep(batch_sleep)
            processed_since_sleep = 0

    return failures


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Migrate legacy ~/.polyfusion/users.json into Supabase Auth."
    )
    p.add_argument(
        "--users-json",
        type=Path,
        default=DEFAULT_USERS_JSON,
        help=f"Path to legacy users.json (default: {DEFAULT_USERS_JSON}).",
    )
    p.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help=(
            "Path to migration_state.json. The state file makes the run "
            f"idempotent (default: {DEFAULT_STATE_PATH})."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the actions that would be taken; make no Supabase calls.",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Alias for the default behaviour: the state file is always read, "
            "so re-running the script automatically resumes. Accepted for UX."
        ),
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_THRESHOLD,
        metavar="N",
        help=(
            "Migrate in batches of N users, sleeping --batch-sleep between "
            f"batches to respect Supabase's free-tier email limit (default: "
            f"{BATCH_THRESHOLD}). Pass 0 to disable batching."
        ),
    )
    p.add_argument(
        "--batch-sleep",
        type=float,
        default=BATCH_SLEEP_SECONDS,
        metavar="SECONDS",
        help=(f"Seconds to sleep between batches (default: {BATCH_SLEEP_SECONDS})."),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _build_parser().parse_args(argv)

    users_path: Path = args.users_json
    state_path: Path = args.state

    if not users_path.exists():
        LOG.error("users.json not found at %s", users_path)
        return 2

    try:
        with users_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        LOG.error("could not read users.json: %s", exc)
        return 2

    state = _load_state(state_path)

    # Build the admin client (or fail fast with a clear message). In tests this
    # factory is monkeypatched.
    admin = _admin_client()

    users = list(_iter_legacy_users(raw))
    # Distinguish "skipped (no email)" from "real users". The latter is what
    # we count against the batch threshold.
    no_email = [u for u in users if not (isinstance(u, dict) and u.get("email"))]
    for rec in no_email:
        username = rec.get("username") if isinstance(rec, dict) else None
        LOG.warning("skipping user without email: %s", username or rec)

    if args.dry_run:
        emailable = [u for u in users if isinstance(u, dict) and u.get("email")]
        LOG.info(
            "[dry-run] %d users would be migrated; %d skipped (no email).",
            len(emailable),
            len(no_email),
        )

    failures = migrate(
        users,
        admin=admin,
        state=state,
        dry_run=args.dry_run,
        batch_threshold=args.batch_size,
        batch_sleep=args.batch_sleep,
    )

    _save_state(state_path, state)

    if failures:
        LOG.error(
            "migration finished with %d failure(s); see state file %s.",
            failures,
            state_path,
        )
        return 2

    LOG.info("migration complete; state written to %s", state_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
