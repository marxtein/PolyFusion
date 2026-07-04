"""Saved report cache backed by local SQLite storage."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

__all__ = ["ReportCacheError", "get_report", "save_report"]

MAX_CACHE_KEY_LEN = 128
MAX_HTML_CHARS = 25 * 1024 * 1024


class ReportCacheError(ValueError):
    pass


def _report_cache_db_path() -> Path:
    path = os.environ.get("POLYFUSION_REPORT_CACHE_DB", "").strip()
    if path:
        return Path(path).expanduser()
    return Path.home() / ".polyfusion" / "report_cache.sqlite3"


def _conn() -> sqlite3.Connection:
    db_path = _report_cache_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode=WAL")
    conn.execute(
        """
        create table if not exists reports (
          id text primary key,
          user_id text not null,
          cache_key text not null,
          config text not null,
          preset text,
          label text,
          inputs text not null,
          summary text,
          html text not null,
          ai_analysis text,
          markdown text,
          created_at real not null,
          updated_at real not null,
          unique (user_id, cache_key)
        )
        """
    )
    conn.execute(
        """
        create index if not exists reports_user_updated_idx
        on reports (user_id, updated_at desc)
        """
    )
    return conn


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def _validate_user_id(user_id: str | None) -> str:
    if not isinstance(user_id, str):
        raise ReportCacheError("user_id is required")
    user_id = user_id.strip()
    if not user_id:
        raise ReportCacheError("user_id is invalid")
    return user_id


def _validate_cache_key(cache_key: str | None) -> str:
    if not isinstance(cache_key, str):
        raise ReportCacheError("cache_key is required")
    cache_key = cache_key.strip()
    if not cache_key or len(cache_key) > MAX_CACHE_KEY_LEN:
        raise ReportCacheError("cache_key is invalid")
    return cache_key


def _row_to_report(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "cache_key": row["cache_key"],
        "config": row["config"],
        "preset": row["preset"],
        "label": row["label"],
        "inputs": _json_loads(row["inputs"]),
        "summary": _json_loads(row["summary"]),
        "html": row["html"],
        "ai_analysis": row["ai_analysis"],
        "markdown": row["markdown"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_report(user_id: str, cache_key: str) -> dict | None:
    user_id = _validate_user_id(user_id)
    cache_key = _validate_cache_key(cache_key)
    with _conn() as conn:
        row = conn.execute(
            """
            select id, cache_key, config, preset, label, inputs, summary, html,
                   ai_analysis, markdown, created_at, updated_at
            from reports
            where user_id = ? and cache_key = ?
            limit 1
            """,
            (user_id, cache_key),
        ).fetchone()
    if row is None:
        return None
    return _row_to_report(row)


def save_report(
    user_id: str,
    *,
    cache_key: str,
    config: str,
    inputs: dict[str, Any],
    html: str,
    preset: str | None = None,
    label: str | None = None,
    summary: dict[str, Any] | None = None,
    ai_analysis: str | None = None,
    markdown: str | None = None,
) -> dict:
    user_id = _validate_user_id(user_id)
    cache_key = _validate_cache_key(cache_key)
    if not config or not isinstance(config, str):
        raise ReportCacheError("config is required")
    if not isinstance(inputs, dict):
        raise ReportCacheError("inputs must be a JSON object")
    if summary is not None and not isinstance(summary, dict):
        raise ReportCacheError("summary must be a JSON object")
    if not isinstance(html, str) or not html.startswith("<!DOCTYPE html>"):
        raise ReportCacheError("html report is required")
    if len(html) > MAX_HTML_CHARS:
        raise ReportCacheError("html report is too large")

    now = time.time()
    report_id = str(uuid.uuid4())
    inputs_json = _json_dumps(inputs)
    summary_json = _json_dumps(summary) if summary is not None else None
    with _conn() as conn:
        conn.execute(
            """
            insert into reports (
              id, user_id, cache_key, config, preset, label, inputs, summary,
              html, ai_analysis, markdown, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(user_id, cache_key) do update set
              config = excluded.config,
              preset = excluded.preset,
              label = excluded.label,
              inputs = excluded.inputs,
              summary = excluded.summary,
              html = excluded.html,
              ai_analysis = excluded.ai_analysis,
              markdown = excluded.markdown,
              updated_at = excluded.updated_at
            """,
            (
                report_id,
                user_id,
                cache_key,
                config,
                preset,
                label,
                inputs_json,
                summary_json,
                html,
                ai_analysis,
                markdown,
                now,
                now,
            ),
        )
        row = conn.execute(
            """
            select id, cache_key, config, preset, label, inputs, summary, html,
                   ai_analysis, markdown, created_at, updated_at
            from reports
            where user_id = ? and cache_key = ?
            limit 1
            """,
            (user_id, cache_key),
        ).fetchone()
    if row is None:
        raise ReportCacheError("report save failed")
    return _row_to_report(row)
