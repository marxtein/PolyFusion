"""HTTP-layer auth tests.

PLACEHOLDER: the original tests here exercised the old scrypt+JSON auth via
``auth.UserStore`` / ``auth.get_store()``, which were removed when
``polyfusion/auth.py`` was rewritten as a Supabase adapter. ``app/server.py``
still uses the legacy auth API and will be rewritten in Phase 3 of the
Supabase migration; at that point this file gets a fresh in-process test
suite (FakeSupabase via conftest, CSRF Origin checks, refresh-cookie flow,
``email_verified`` badge on ``/api/auth/me``, rate limiting, etc.).

Until then we keep the module importable and the collection green with a
single smoke test.
"""


def test_phase3_will_rewrite():
    """Smoke test — real HTTP auth tests return in Phase 3."""
    assert True
