"""Tests for local saved report cache helpers."""

from __future__ import annotations

import pytest

from polyfusion import report_cache


def _cache_db(monkeypatch, tmp_path):
    db_path = tmp_path / "report_cache.sqlite3"
    monkeypatch.setenv("POLYFUSION_REPORT_CACHE_DB", str(db_path))
    return db_path


def test_get_report_returns_none_on_miss(monkeypatch, tmp_path):
    _cache_db(monkeypatch, tmp_path)
    assert report_cache.get_report("user-1", "pf-report-v1-a") is None


def test_save_report_returns_cached_row(monkeypatch, tmp_path):
    _cache_db(monkeypatch, tmp_path)
    row = report_cache.save_report(
        "user-1",
        cache_key="pf-report-v1-a",
        config="tokamak",
        inputs={"config": "tokamak"},
        summary={"Pfus": 500.0},
        html="<!DOCTYPE html><html></html>",
        ai_analysis="ok",
        markdown="# Report",
    )
    assert row["id"]
    assert row["cache_key"] == "pf-report-v1-a"
    assert row["inputs"] == {"config": "tokamak"}
    assert row["summary"] == {"Pfus": 500.0}
    assert row["ai_analysis"] == "ok"

    cached = report_cache.get_report("user-1", "pf-report-v1-a")
    assert cached == row


def test_save_report_upserts_by_user_and_cache_key(monkeypatch, tmp_path):
    _cache_db(monkeypatch, tmp_path)
    first = report_cache.save_report(
        "user-1",
        cache_key="pf-report-v1-a",
        config="tokamak",
        inputs={"config": "tokamak"},
        html="<!DOCTYPE html><html>old</html>",
        ai_analysis="old",
    )
    second = report_cache.save_report(
        "user-1",
        cache_key="pf-report-v1-a",
        config="tokamak",
        inputs={"config": "tokamak", "R0": 5.5},
        html="<!DOCTYPE html><html>new</html>",
        ai_analysis="new",
    )
    assert second["id"] == first["id"]
    assert second["html"] == "<!DOCTYPE html><html>new</html>"
    assert second["ai_analysis"] == "new"
    assert second["inputs"] == {"config": "tokamak", "R0": 5.5}
    assert second["updated_at"] >= first["updated_at"]


def test_report_cache_is_isolated_by_user(monkeypatch, tmp_path):
    _cache_db(monkeypatch, tmp_path)
    report_cache.save_report(
        "user-1",
        cache_key="pf-report-v1-a",
        config="tokamak",
        inputs={"config": "tokamak"},
        html="<!DOCTYPE html><html>user1</html>",
    )
    report_cache.save_report(
        "user-2",
        cache_key="pf-report-v1-a",
        config="tokamak",
        inputs={"config": "tokamak"},
        html="<!DOCTYPE html><html>user2</html>",
    )
    assert report_cache.get_report("user-1", "pf-report-v1-a")["html"].endswith(
        "user1</html>"
    )
    assert report_cache.get_report("user-2", "pf-report-v1-a")["html"].endswith(
        "user2</html>"
    )


def test_save_report_rejects_bad_html(monkeypatch, tmp_path):
    _cache_db(monkeypatch, tmp_path)
    with pytest.raises(report_cache.ReportCacheError):
        report_cache.save_report(
            "user-1",
            cache_key="pf-report-v1-a",
            config="tokamak",
            inputs={},
            html="<html></html>",
        )


def test_report_cache_rejects_missing_user_id(monkeypatch, tmp_path):
    _cache_db(monkeypatch, tmp_path)
    with pytest.raises(report_cache.ReportCacheError):
        report_cache.get_report(None, "pf-report-v1-a")
    with pytest.raises(report_cache.ReportCacheError):
        report_cache.save_report(
            "",
            cache_key="pf-report-v1-a",
            config="tokamak",
            inputs={},
            html="<!DOCTYPE html><html></html>",
        )
