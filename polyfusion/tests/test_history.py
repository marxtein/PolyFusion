"""Unit tests for polyfusion/history.py.

All tests mock ``polyfusion.history.pg_rest`` so no network calls are made.
The mock returns canned ``(status, payload)`` tuples and records the call
kwargs so assertions can verify path / method / query / body construction.
"""

from __future__ import annotations


import pytest

from polyfusion import history


@pytest.fixture
def pg(monkeypatch):
    """Patch ``pg_rest`` and return a recorder."""
    calls: list[dict] = []

    def fake_pg_rest(
        path,
        *,
        access_token,
        method="GET",
        query=None,
        body=None,
        base_url=None,
        apikey=None,
        timeout=30.0,
        prefer=None,
    ):
        calls.append(
            {
                "path": path,
                "access_token": access_token,
                "method": method,
                "query": dict(query) if query else None,
                "body": body,
                "prefer": prefer,
                # Return a deferred result so each test can specify its own response.
            }
        )
        return fake_pg_rest.next_response

    fake_pg_rest.next_response = (200, [])
    fake_pg_rest.calls = calls
    monkeypatch.setattr(history, "pg_rest", fake_pg_rest)
    return fake_pg_rest


# ---------------------------------------------------------------------------
# list_history
# ---------------------------------------------------------------------------


def test_list_history_default_limit_and_order(pg):
    pg.next_response = (200, [{"id": "a"}, {"id": "b"}])
    total, rows = history.list_history("tok", offset=0)
    assert total == 2
    assert rows == [{"id": "a"}, {"id": "b"}]
    call = pg.calls[-1]
    assert call["method"] == "GET"
    assert "order=created_at.desc" in call["path"]
    assert call["query"]["limit"] == "20"
    assert call["query"]["offset"] == "0"
    assert call["prefer"] == "count=exact"


def test_list_history_clamps_limit(pg):
    pg.next_response = (200, [])
    history.list_history("tok", limit=999)
    assert pg.calls[-1]["query"]["limit"] == str(history.MAX_LIMIT)


def test_list_history_filters_by_kind(pg):
    pg.next_response = (200, [])
    history.list_history("tok", kind="scan")
    assert pg.calls[-1]["query"]["kind"] == "eq.scan"


def test_list_history_rejects_bad_kind(pg):
    with pytest.raises(history.HistoryError, match="kind"):
        history.list_history("tok", kind="bogus")


def test_list_history_raises_on_postgrest_error(pg):
    pg.next_response = (403, {"message": "rls blocked"})
    with pytest.raises(history.HistoryError, match="PostgREST list failed"):
        history.list_history("tok")


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------


def test_get_history_returns_row(pg):
    pg.next_response = (200, [{"id": "abc", "kind": "run"}])
    row = history.get_history("tok", "abc")
    assert row == {"id": "abc", "kind": "run"}
    call = pg.calls[-1]
    assert call["query"]["id"] == "eq.abc"
    assert call["query"]["limit"] == "1"


def test_get_history_returns_none_when_empty(pg):
    pg.next_response = (200, [])
    assert history.get_history("tok", "missing") is None


def test_get_history_requires_id():
    with pytest.raises(history.HistoryError, match="computation_id"):
        history.get_history("tok", "")


# ---------------------------------------------------------------------------
# save_history
# ---------------------------------------------------------------------------


def test_save_history_minimal_body(pg):
    pg.next_response = (201, [{"id": "new"}])
    row = history.save_history(
        "tok",
        kind="run",
        config="tokamak",
        inputs={"q95": 3.0},
    )
    assert row == {"id": "new"}
    call = pg.calls[-1]
    assert call["method"] == "POST"
    body = call["body"]
    assert body["kind"] == "run"
    assert body["config"] == "tokamak"
    assert body["inputs"] == {"q95": 3.0}
    assert "preset" not in body
    assert "label" not in body
    assert "summary" not in body
    assert "user_id" not in body  # caller may rely on auth.uid()


def test_save_history_with_optional_fields(pg):
    pg.next_response = (201, [{"id": "new"}])
    history.save_history(
        "tok",
        kind="scan",
        config="stellarator",
        inputs={"r": 0.5},
        preset="w7x",
        label="my run",
        summary={"best_qfus": 10},
        user_id="uid-123",
    )
    body = pg.calls[-1]["body"]
    assert body["preset"] == "w7x"
    assert body["label"] == "my run"
    assert body["summary"] == {"best_qfus": 10}
    assert body["user_id"] == "uid-123"


def test_save_history_rejects_bad_kind(pg):
    with pytest.raises(history.HistoryError, match="kind"):
        history.save_history("tok", kind="bogus", config="x", inputs={})


def test_save_history_rejects_empty_config(pg):
    with pytest.raises(history.HistoryError, match="config"):
        history.save_history("tok", kind="run", config="", inputs={})


def test_save_history_rejects_non_dict_inputs(pg):
    with pytest.raises(history.HistoryError, match="inputs"):
        history.save_history("tok", kind="run", config="x", inputs=[1, 2, 3])


def test_save_history_raises_on_postgrest_error(pg):
    pg.next_response = (400, {"message": "constraint violation"})
    with pytest.raises(history.HistoryError, match="PostgREST insert failed"):
        history.save_history("tok", kind="run", config="x", inputs={})


# ---------------------------------------------------------------------------
# delete_history
# ---------------------------------------------------------------------------


def test_delete_history_returns_true_when_row_deleted(pg):
    pg.next_response = (200, [{"id": "abc"}])
    assert history.delete_history("tok", "abc") is True
    call = pg.calls[-1]
    assert call["method"] == "DELETE"
    assert call["query"]["id"] == "eq.abc"
    assert call["prefer"] == "return=representation"


def test_delete_history_returns_false_when_nothing_matched(pg):
    pg.next_response = (200, [])
    assert history.delete_history("tok", "missing") is False


def test_delete_history_returns_true_on_204(pg):
    pg.next_response = (204, None)
    assert history.delete_history("tok", "abc") is True


def test_delete_history_requires_id():
    with pytest.raises(history.HistoryError, match="computation_id"):
        history.delete_history("tok", "")


def test_delete_history_raises_on_postgrest_error(pg):
    pg.next_response = (500, {"message": "boom"})
    with pytest.raises(history.HistoryError, match="PostgREST delete failed"):
        history.delete_history("tok", "abc")
