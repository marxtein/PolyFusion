"""Unit tests for polyfusion/admin.py.

``pg_rest`` is patched with a recorder so we can assert on profile query
construction and inject canned responses per-test. Computation totals are read
from local history storage and patched separately.
"""

from __future__ import annotations

import pytest

from polyfusion import admin


@pytest.fixture
def pg(monkeypatch):
    """Patch ``pg_rest`` with a path-aware recorder.

    Tests populate ``pg.responses`` as a list of ``(path_substring, response)``
    tuples; each call pops the head and verifies the path contains the
    substring. A simpler ``next_response`` is used as a fallback when the
    test only sets one response.
    """
    calls: list[dict] = []
    responses: list[tuple[str, tuple]] = []

    def fake_pg_rest(path, *, access_token, **kwargs):
        calls.append({"path": path, "access_token": access_token, **kwargs})
        if responses:
            sub, resp = responses.pop(0)
            assert sub in path, f"expected path containing {sub!r}, got {path!r}"
            return resp
        return fake_pg_rest.next_response

    fake_pg_rest.next_response = (200, [])
    fake_pg_rest.calls = calls
    fake_pg_rest.responses = responses
    monkeypatch.setattr(admin, "pg_rest", fake_pg_rest)
    monkeypatch.setattr(admin.history_mod, "count_history", lambda: 3)
    return fake_pg_rest


# ---------------------------------------------------------------------------
# list_users
# ---------------------------------------------------------------------------


def test_list_users_default_limit_and_order(pg):
    pg.next_response = (200, [{"id": "a"}, {"id": "b"}])
    total, rows = admin.list_users("tok", offset=0)
    assert total == 2
    assert rows == [{"id": "a"}, {"id": "b"}]
    call = pg.calls[-1]
    assert call["access_token"] == "tok"
    assert "order=created_at.desc" in call["path"]
    assert "affiliation" in call["path"]
    assert "is_admin" in call["path"]
    assert call["query"]["limit"] == str(admin.DEFAULT_LIMIT)
    assert call["query"]["offset"] == "0"


def test_list_users_clamps_limit(pg):
    pg.next_response = (200, [])
    admin.list_users("tok", limit=999)
    assert pg.calls[-1]["query"]["limit"] == str(admin.MAX_LIMIT)


def test_list_users_clamps_negative_offset(pg):
    pg.next_response = (200, [])
    admin.list_users("tok", offset=-5)
    assert pg.calls[-1]["query"]["offset"] == "0"


def test_list_users_raises_on_postgrest_error(pg):
    pg.next_response = (403, {"message": "rls blocked"})
    with pytest.raises(admin.AdminError, match="PostgREST list failed"):
        admin.list_users("tok")


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


def test_stats_aggregates_three_calls(pg):
    pg.responses.extend(
        [
            (
                "/profiles?select=id,affiliation",
                (
                    200,
                    [
                        {"id": "1", "affiliation": "ASIPP"},
                        {"id": "2", "affiliation": "ASIPP"},
                        {"id": "3", "affiliation": "IPP"},
                        {"id": "4", "affiliation": None},
                    ],
                ),
            ),
            ("/profiles?select=id&created_at=gte.", (200, [{"id": "2"}])),
        ]
    )

    out = admin.stats("tok")

    assert out == {
        "total_users": 4,
        "new_users_7d": 1,
        "total_computations": 3,
        "top_affiliations": [
            {"affiliation": "ASIPP", "count": 2},
            {"affiliation": "IPP", "count": 1},
            {"affiliation": "", "count": 1},
        ],
    }
    assert len(pg.calls) == 2
    assert pg.calls[0]["access_token"] == "tok"


def test_stats_truncates_top_affiliations(pg, monkeypatch):
    monkeypatch.setattr(admin, "TOP_AFFILIATIONS_N", 2)
    pg.responses.extend(
        [
            (
                "/profiles?select=id,affiliation",
                (200, [{"id": str(i), "affiliation": f"aff{i % 3}"} for i in range(9)]),
            ),
            ("/profiles?select=id&created_at=gte.", (200, [])),
        ]
    )
    out = admin.stats("tok")
    assert len(out["top_affiliations"]) == 2
    # Each affiliation appears 3 times; ordering is stable across the first 2.
    assert out["top_affiliations"][0]["count"] == 3


def test_stats_uses_iso8601_7day_cutoff(pg):
    pg.responses.extend(
        [
            ("/profiles?select=id,affiliation", (200, [])),
            ("/profiles?select=id&created_at=gte.", (200, [])),
        ]
    )
    admin.stats("tok")
    # The 7d cutoff path should contain an ISO-8601 timestamp (T separator).
    cutoff_call = pg.calls[1]
    assert "created_at=gte." in cutoff_call["path"]
    # The timestamp is everything after "created_at=gte." up to "&limit" or end.
    tail = cutoff_call["path"].split("created_at=gte.", 1)[1]
    ts = tail.split("&", 1)[0]
    assert "T" in ts  # ISO-8601


def test_stats_raises_if_any_call_fails(pg):
    pg.responses.extend(
        [
            ("/profiles?select=id,affiliation", (500, {"message": "boom"})),
        ]
    )
    with pytest.raises(admin.AdminError, match="PostgREST stats fetch failed"):
        admin.stats("tok")


def test_stats_handles_non_list_payload(pg):
    """A dict payload (e.g. PostgREST error body) is treated as no rows."""
    pg.responses.extend(
        [
            ("/profiles?select=id,affiliation", (200, {"message": "weird"})),
            ("/profiles?select=id&created_at=gte.", (200, [])),
        ]
    )
    out = admin.stats("tok")
    assert out["total_users"] == 0
    assert out["top_affiliations"] == []
