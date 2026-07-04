#!/usr/bin/env python3
"""Migrate Supabase public.computations rows into local history SQLite."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

SELECT_COLUMNS = "id,user_id,kind,config,preset,label,inputs,summary,created_at"


def _history_db_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env_path = os.environ.get("POLYFUSION_HISTORY_DB", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    return Path.home() / ".polyfusion" / "history.sqlite3"


def _conn(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode=WAL")
    conn.execute(
        """
        create table if not exists computations (
          id text primary key,
          user_id text not null,
          kind text not null check (kind in ('run', 'scan')),
          config text not null,
          preset text,
          label text,
          inputs text not null,
          summary text,
          created_at real not null
        )
        """
    )
    conn.execute(
        """
        create index if not exists computations_user_created_idx
        on computations (user_id, created_at desc)
        """
    )
    conn.execute(
        """
        create index if not exists computations_user_kind_created_idx
        on computations (user_id, kind, created_at desc)
        """
    )
    return conn


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _created_at(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value:
        return time.time()
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return time.time()


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fetch_page(base_url: str, service_key: str, limit: int, offset: int) -> list[dict]:
    query = urllib.parse.urlencode(
        {
            "select": SELECT_COLUMNS,
            "order": "created_at.asc",
            "limit": str(limit),
            "offset": str(offset),
        }
    )
    url = f"{base_url.rstrip('/')}/rest/v1/computations?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Supabase HTTP {exc.code}: {body}") from exc
    if not isinstance(payload, list):
        raise SystemExit(f"Unexpected Supabase payload: {payload!r}")
    return payload


def _insert_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    inserted = 0
    for row in rows:
        if not row.get("id") or not row.get("user_id"):
            continue
        conn.execute(
            """
            insert into computations (
              id, user_id, kind, config, preset, label, inputs, summary, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(id) do update set
              user_id = excluded.user_id,
              kind = excluded.kind,
              config = excluded.config,
              preset = excluded.preset,
              label = excluded.label,
              inputs = excluded.inputs,
              summary = excluded.summary,
              created_at = excluded.created_at
            """,
            (
                str(row["id"]),
                str(row["user_id"]),
                row.get("kind") or "run",
                row.get("config") or "unknown",
                row.get("preset"),
                row.get("label"),
                _json_text(row.get("inputs") or {}),
                _json_text(row.get("summary")),
                _created_at(row.get("created_at")),
            ),
        )
        inserted += 1
    conn.commit()
    return inserted


def migrate(db_path: Path, *, page_size: int) -> int:
    base_url = _required_env("SUPABASE_URL")
    service_key = _required_env("SUPABASE_SERVICE_ROLE_KEY")
    total = 0
    offset = 0
    with _conn(db_path) as conn:
        while True:
            rows = _fetch_page(base_url, service_key, page_size, offset)
            if not rows:
                break
            total += _insert_rows(conn, rows)
            offset += len(rows)
            if len(rows) < page_size:
                break
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="destination SQLite path")
    parser.add_argument("--page-size", type=int, default=500)
    args = parser.parse_args(argv)
    if args.page_size < 1:
        parser.error("--page-size must be >= 1")
    db_path = _history_db_path(args.db)
    total = migrate(db_path, page_size=args.page_size)
    print(f"migrated {total} computation rows into {db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
