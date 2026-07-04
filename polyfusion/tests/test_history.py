"""Unit tests for local computation history storage."""

from __future__ import annotations

import pytest

from polyfusion import history


@pytest.fixture
def history_db(monkeypatch, tmp_path):
    db_path = tmp_path / "history.sqlite3"
    monkeypatch.setenv("POLYFUSION_HISTORY_DB", str(db_path))
    return db_path


def test_list_history_default_limit_and_order(history_db):
    first = history.save_history(
        "user-1", kind="run", config="tokamak", inputs={"q95": 3.0}
    )
    second = history.save_history(
        "user-1", kind="scan", config="mirror", inputs={"x": "R0"}
    )
    total, rows = history.list_history("user-1", offset=0)
    assert total == 2
    assert [row["id"] for row in rows] == [second["id"], first["id"]]


def test_list_history_clamps_limit(history_db):
    for idx in range(3):
        history.save_history(
            "user-1", kind="run", config="tokamak", inputs={"idx": idx}
        )
    total, rows = history.list_history("user-1", limit=999)
    assert total == 3
    assert len(rows) == 3


def test_list_history_filters_by_kind(history_db):
    history.save_history("user-1", kind="run", config="tokamak", inputs={})
    scan = history.save_history("user-1", kind="scan", config="tokamak", inputs={})
    total, rows = history.list_history("user-1", kind="scan")
    assert total == 1
    assert rows[0]["id"] == scan["id"]


def test_list_history_isolated_by_user(history_db):
    history.save_history("user-1", kind="run", config="tokamak", inputs={})
    history.save_history("user-2", kind="run", config="mirror", inputs={})
    total, rows = history.list_history("user-1")
    assert total == 1
    assert rows[0]["config"] == "tokamak"


def test_list_history_rejects_bad_kind(history_db):
    with pytest.raises(history.HistoryError, match="kind"):
        history.list_history("user-1", kind="bogus")


def test_get_history_returns_owned_row(history_db):
    row = history.save_history("user-1", kind="run", config="tokamak", inputs={})
    assert history.get_history("user-1", row["id"]) == row


def test_get_history_returns_none_when_empty_or_other_user(history_db):
    row = history.save_history("user-1", kind="run", config="tokamak", inputs={})
    assert history.get_history("user-1", "missing") is None
    assert history.get_history("user-2", row["id"]) is None


def test_get_history_requires_id(history_db):
    with pytest.raises(history.HistoryError, match="computation_id"):
        history.get_history("user-1", "")


def test_save_history_with_optional_fields(history_db):
    row = history.save_history(
        "user-1",
        kind="scan",
        config="stellarator",
        inputs={"r": 0.5},
        preset="w7x",
        label="my run",
        summary={"best_qfus": 10},
    )
    assert row["id"]
    assert row["kind"] == "scan"
    assert row["config"] == "stellarator"
    assert row["inputs"] == {"r": 0.5}
    assert row["preset"] == "w7x"
    assert row["label"] == "my run"
    assert row["summary"] == {"best_qfus": 10}
    assert row["created_at"] > 0


def test_save_history_rejects_bad_kind(history_db):
    with pytest.raises(history.HistoryError, match="kind"):
        history.save_history("user-1", kind="bogus", config="x", inputs={})


def test_save_history_rejects_empty_config(history_db):
    with pytest.raises(history.HistoryError, match="config"):
        history.save_history("user-1", kind="run", config="", inputs={})


def test_save_history_rejects_non_dict_inputs(history_db):
    with pytest.raises(history.HistoryError, match="inputs"):
        history.save_history("user-1", kind="run", config="x", inputs=[1, 2, 3])


def test_save_history_rejects_non_dict_summary(history_db):
    with pytest.raises(history.HistoryError, match="summary"):
        history.save_history("user-1", kind="run", config="x", inputs={}, summary=[])


def test_history_rejects_missing_user_id(history_db):
    with pytest.raises(history.HistoryError, match="user_id"):
        history.list_history("")
    with pytest.raises(history.HistoryError, match="user_id"):
        history.save_history(None, kind="run", config="x", inputs={})


def test_delete_history_returns_true_when_row_deleted(history_db):
    row = history.save_history("user-1", kind="run", config="tokamak", inputs={})
    assert history.delete_history("user-1", row["id"]) is True
    assert history.get_history("user-1", row["id"]) is None


def test_delete_history_returns_false_when_nothing_matched(history_db):
    row = history.save_history("user-1", kind="run", config="tokamak", inputs={})
    assert history.delete_history("user-2", row["id"]) is False
    assert history.delete_history("user-1", "missing") is False


def test_delete_history_requires_id(history_db):
    with pytest.raises(history.HistoryError, match="computation_id"):
        history.delete_history("user-1", "")


def test_delete_user_history_and_count(history_db):
    history.save_history("user-1", kind="run", config="tokamak", inputs={})
    history.save_history("user-1", kind="scan", config="tokamak", inputs={})
    history.save_history("user-2", kind="run", config="mirror", inputs={})
    assert history.count_history() == 3
    assert history.delete_user_history("user-1") == 2
    assert history.count_history() == 1
    total, rows = history.list_history("user-1")
    assert total == 0
    assert rows == []
