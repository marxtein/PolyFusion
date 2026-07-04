"""User computation history backed by local SQLite storage."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

__all__ = [
    "HistoryError",
    "list_history",
    "get_history",
    "save_history",
    "delete_history",
    "delete_user_history",
    "count_history",
    "MAX_LIMIT",
]

MAX_LIMIT = 100
DEFAULT_LIMIT = 20
VALID_KINDS = {"run", "scan"}


class HistoryError(ValueError):
    """Raised for caller-side validation failures."""


def _history_db_path() -> Path:
    path = os.environ.get("POLYFUSION_HISTORY_DB", "").strip()
    if path:
        return Path(path).expanduser()
    return Path.home() / ".polyfusion" / "history.sqlite3"


def _conn() -> sqlite3.Connection:
    db_path = _history_db_path()
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


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def _validate_user_id(user_id: str | None) -> str:
    if not isinstance(user_id, str):
        raise HistoryError("user_id is required")
    user_id = user_id.strip()
    if not user_id:
        raise HistoryError("user_id is invalid")
    return user_id


def _validate_kind(kind: str | None) -> str | None:
    if kind is None:
        return kind
    if kind not in VALID_KINDS:
        raise HistoryError(f"kind must be one of {sorted(VALID_KINDS)}, got {kind!r}")
    return kind


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if limit < 1:
        return 1
    return min(limit, MAX_LIMIT)


def _row_to_history(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "config": row["config"],
        "preset": row["preset"],
        "label": row["label"],
        "inputs": _json_loads(row["inputs"]),
        "summary": _json_loads(row["summary"]),
        "created_at": row["created_at"],
    }


def list_history(
    user_id: str,
    *,
    limit: int | None = None,
    offset: int = 0,
    kind: str | None = None,
) -> tuple[int, list[dict]]:
    """List one user's computation history, newest first."""
    user_id = _validate_user_id(user_id)
    kind = _validate_kind(kind)
    limit = _clamp_limit(limit)
    if offset < 0:
        offset = 0

    where = "where user_id = ?"
    params: list[Any] = [user_id]
    if kind is not None:
        where += " and kind = ?"
        params.append(kind)

    with _conn() as conn:
        total = conn.execute(
            f"select count(*) as n from computations {where}", params
        ).fetchone()["n"]
        rows = conn.execute(
            f"""
            select id, kind, config, preset, label, inputs, summary, created_at
            from computations
            {where}
            order by created_at desc
            limit ? offset ?
            """,
            [*params, limit, offset],
        ).fetchall()
    return int(total), [_row_to_history(row) for row in rows]


def get_history(user_id: str, computation_id: str) -> dict | None:
    """Return one computation row by id, or None if missing or not owned."""
    user_id = _validate_user_id(user_id)
    if not computation_id:
        raise HistoryError("computation_id is required")
    with _conn() as conn:
        row = conn.execute(
            """
            select id, kind, config, preset, label, inputs, summary, created_at
            from computations
            where user_id = ? and id = ?
            limit 1
            """,
            (user_id, computation_id),
        ).fetchone()
    if row is None:
        return None
    return _row_to_history(row)


def save_history(
    user_id: str,
    *,
    kind: str,
    config: str,
    inputs: dict[str, Any],
    preset: str | None = None,
    label: str | None = None,
    summary: dict[str, Any] | None = None,
) -> dict:
    """Insert one computation history row for a user."""
    user_id = _validate_user_id(user_id)
    if kind not in VALID_KINDS:
        raise HistoryError(f"kind must be one of {sorted(VALID_KINDS)}, got {kind!r}")
    if not config or not isinstance(config, str):
        raise HistoryError("config is required (non-empty string)")
    if not isinstance(inputs, dict):
        raise HistoryError("inputs must be a JSON object")
    if summary is not None and not isinstance(summary, dict):
        raise HistoryError("summary must be a JSON object")

    computation_id = str(uuid.uuid4())
    created_at = time.time()
    with _conn() as conn:
        conn.execute(
            """
            insert into computations (
              id, user_id, kind, config, preset, label, inputs, summary, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                computation_id,
                user_id,
                kind,
                config,
                preset,
                label,
                _json_dumps(inputs),
                _json_dumps(summary) if summary is not None else None,
                created_at,
            ),
        )
        row = conn.execute(
            """
            select id, kind, config, preset, label, inputs, summary, created_at
            from computations
            where user_id = ? and id = ?
            limit 1
            """,
            (user_id, computation_id),
        ).fetchone()
    if row is None:
        raise HistoryError("history save failed")
    return _row_to_history(row)


def delete_history(user_id: str, computation_id: str) -> bool:
    """Delete one owned row. Returns True if a row was deleted."""
    user_id = _validate_user_id(user_id)
    if not computation_id:
        raise HistoryError("computation_id is required")
    with _conn() as conn:
        cur = conn.execute(
            "delete from computations where user_id = ? and id = ?",
            (user_id, computation_id),
        )
    return cur.rowcount > 0


def delete_user_history(user_id: str) -> int:
    """Delete all computation history rows for one user."""
    user_id = _validate_user_id(user_id)
    with _conn() as conn:
        cur = conn.execute("delete from computations where user_id = ?", (user_id,))
    return cur.rowcount


def count_history() -> int:
    """Return total locally stored computation rows."""
    with _conn() as conn:
        row = conn.execute("select count(*) as n from computations").fetchone()
    return int(row["n"])
