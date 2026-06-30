"""Tests for scripts/migrate_users_to_supabase.py.

The script is imported and ``main()`` is called in-process so we can
monkeypatch its ``_admin_client()`` factory with a fake admin that records
calls in memory. No subprocess, no network.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from supabase_auth.errors import AuthApiError, AuthRetryableError

# Make ``scripts/`` importable. The package is a single module with no
# __init__.py by design (it is a standalone CLI), so we add the directory
# itself to sys.path.
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import migrate_users_to_supabase as mig  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _AttrBag:
    """Generic attribute bag mimicking a pydantic response object."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeAdmin:
    """In-memory stand-in for ``client.auth.admin``.

    Records every call and lets a test inject the next error to raise from
    ``create_user`` (or a per-email error override). Network-flavoured errors
    are surfaced as ``AuthRetryableError``; "already registered" errors are
    surfaced as ``AuthApiError`` with the canonical code.
    """

    def __init__(self) -> None:
        self.create_calls: list[dict] = []
        self.link_calls: list[dict] = []
        self.users: dict[str, str] = {}
        self.next_error: Exception | None = None
        # Per-email error to raise from create_user. Takes precedence over
        # next_error so a single config drives the whole test.
        self.create_errors: dict[str, Exception] = {}
        # Number of consecutive AuthRetryableError failures before success.
        self.transient_failures_remaining: dict[str, int] = {}
        # Counts retries per email so we can assert the ladder fired.
        self.transient_attempts: dict[str, int] = {}

    def create_user(self, attributes: dict) -> _AttrBag:
        self.create_calls.append(attributes)
        email = attributes["email"]

        if email in self.transient_failures_remaining:
            self.transient_attempts[email] = self.transient_attempts.get(email, 0) + 1
            if self.transient_failures_remaining[email] > 0:
                self.transient_failures_remaining[email] -= 1
                raise AuthRetryableError("transient network error", 500)

        if email in self.create_errors:
            raise self.create_errors.pop(email)
        if self.next_error is not None:
            raise self.next_error

        if email in self.users:
            raise AuthApiError(
                "User already registered",
                400,
                "user_already_exists",
            )
        user_id = f"uid-{email}"
        self.users[email] = user_id
        return _AttrBag(user=_AttrBag(id=user_id, email=email))

    def generate_link(self, params: dict) -> _AttrBag:
        self.link_calls.append(params)
        email = params["email"]
        return _AttrBag(
            properties=_AttrBag(
                action_link=f"https://example.supabase.co/verify?type=recovery&email={email}",
                email_otp="123456",
                hashed_token="hashed",
                redirect_to="http://121.36.110.12:8765",
                verification_type="recovery",
            ),
            user=_AttrBag(id=self.users.get(email, "uid"), email=email),
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_admin(monkeypatch):
    admin = FakeAdmin()
    monkeypatch.setattr(mig, "_admin_client", lambda: admin)
    return admin


@pytest.fixture
def env(monkeypatch):
    """Provide the SUPABASE_* env vars the script reads at startup."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")
    return monkeypatch


@pytest.fixture
def users_json(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps(
            {
                "alice": {"email": "alice@example.com"},
                "bob": {"email": "bob@example.com"},
                "carol": {"email": "carol@example.com"},
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "migration_state.json"


def _run(users_json: Path, state_path: Path, *extra: str) -> int:
    return mig.main(
        [
            "--users-json",
            str(users_json),
            "--state",
            str(state_path),
            # Batching is verified separately; disable the inter-batch sleep so
            # the test suite does not stall on the 30-minute free-tier pause.
            "--batch-size",
            "0",
            *extra,
        ]
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_migrates_all_users(fake_admin, env, users_json, state_path):
    rc = _run(users_json, state_path)

    assert rc == 0
    assert len(fake_admin.create_calls) == 3
    assert len(fake_admin.link_calls) == 3

    # Each create_user got email_confirm=True and a 32-byte random password.
    for call in fake_admin.create_calls:
        assert call["email_confirm"] is True
        assert len(call["password"]) >= 32

    # generate_link used the recovery type.
    for call in fake_admin.link_calls:
        assert call["type"] == "recovery"

    # State file written with one entry per email.
    state = json.loads(state_path.read_text(encoding="utf-8"))
    migrated = state["migrated"]
    assert set(migrated) == {
        "alice@example.com",
        "bob@example.com",
        "carol@example.com",
    }
    for rec in migrated.values():
        assert rec["user_id"]
        assert rec["migrated_at"] <= time.time()


def test_user_without_email_is_skipped(fake_admin, env, tmp_path, state_path):
    users = tmp_path / "users.json"
    users.write_text(
        json.dumps(
            {
                "alice": {"email": "alice@example.com"},
                "legacy_user": {"email": None},
                "nobody": {},
            }
        ),
        encoding="utf-8",
    )

    rc = _run(users, state_path)

    assert rc == 0
    # Only alice got migrated.
    assert len(fake_admin.create_calls) == 1
    assert fake_admin.create_calls[0]["email"] == "alice@example.com"


def test_idempotent_second_run_makes_zero_calls(
    fake_admin, env, users_json, state_path
):
    rc1 = _run(users_json, state_path)
    assert rc1 == 0
    assert len(fake_admin.create_calls) == 3

    # Second run: state short-circuits every email.
    rc2 = _run(users_json, state_path)
    assert rc2 == 0
    assert len(fake_admin.create_calls) == 3  # unchanged
    assert len(fake_admin.link_calls) == 3  # unchanged


def test_already_registered_recorded_as_skipped_existing(
    fake_admin, env, users_json, state_path
):
    # Pre-seed Supabase with bob so create_user raises user_already_exists.
    fake_admin.users["bob@example.com"] = "uid-bob"

    rc = _run(users_json, state_path)

    assert rc == 0  # already-registered is not a failure
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "bob@example.com" in state["skipped_existing"]
    assert "alice@example.com" in state["migrated"]
    assert "carol@example.com" in state["migrated"]


def test_network_error_retried_then_logged_exit_code_2(
    fake_admin, env, users_json, state_path, monkeypatch
):
    # Force alice to fail 4 times (> retry ladder of 3) so the run is partial.
    fake_admin.transient_failures_remaining["alice@example.com"] = 4
    # Speed up the retry ladder so the test does not actually sleep 7 seconds.
    monkeypatch.setattr(mig, "RETRY_BACKOFFS", (0.0, 0.0, 0.0))

    rc = _run(users_json, state_path)

    assert rc == 2
    # alice attempted 4 times (initial + 3 retries).
    assert fake_admin.transient_attempts["alice@example.com"] == 4
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "alice@example.com" in state["errors"]
    # bob and carol still migrated despite alice failing.
    assert "bob@example.com" in state["migrated"]
    assert "carol@example.com" in state["migrated"]


def test_dry_run_makes_zero_supabase_calls(fake_admin, env, users_json, state_path):
    rc = _run(users_json, state_path, "--dry-run")

    assert rc == 0
    assert fake_admin.create_calls == []
    assert fake_admin.link_calls == []

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(state["migrated"]) == {
        "alice@example.com",
        "bob@example.com",
        "carol@example.com",
    }
    for rec in state["migrated"].values():
        assert rec["dry_run"] is True


def test_missing_env_var_raises_systemexit(tmp_path, monkeypatch):
    # Wipe the env vars so _admin_client() raises before any network call.
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    users = tmp_path / "users.json"
    users.write_text(
        json.dumps({"alice": {"email": "alice@example.com"}}), encoding="utf-8"
    )
    state = tmp_path / "state.json"

    # Do NOT use the fake_admin fixture here — we want the real factory.
    with pytest.raises(SystemExit) as excinfo:
        mig.main(["--users-json", str(users), "--state", str(state)])

    assert "SUPABASE_URL" in str(excinfo.value)
    assert "SUPABASE_SERVICE_ROLE_KEY" in str(excinfo.value)
