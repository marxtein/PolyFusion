"""User computation history API for v1.2.

Routes in ``app/server.py`` delegate here for list / get / save / delete
operations on ``public.computations``. Each call takes the user's access
token and forwards to Supabase PostgREST via ``polyfusion.postgrest.pg_rest``;
RLS ensures the calling user only sees / mutates their own rows.

Required fields for save (validated here so we surface a clean 400 instead
of a PostgREST constraint error):
    kind    ∈ {'run', 'scan'}
    config  non-empty string (config name, e.g. 'tokamak')
    inputs  JSON-serialisable dict of run/scan inputs
Optional:
    preset  preset name when the run was launched from a preset
    label   user-facing label
    summary JSON-serialisable dict of run/scan summary metrics
"""

from __future__ import annotations

from typing import Any

from polyfusion.postgrest import pg_rest

__all__ = [
    "HistoryError",
    "list_history",
    "get_history",
    "save_history",
    "delete_history",
    "MAX_LIMIT",
]

MAX_LIMIT = 100
DEFAULT_LIMIT = 20
VALID_KINDS = {"run", "scan"}


class HistoryError(ValueError):
    """Raised for caller-side validation failures (bad kind, missing fields).

    The HTTP layer maps these to 400 responses.
    """


def _validate_kind(kind: str | None) -> str:
    if kind is None:
        return kind  # caller treats None as "no filter"
    if kind not in VALID_KINDS:
        raise HistoryError(f"kind must be one of {sorted(VALID_KINDS)}, got {kind!r}")
    return kind


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if limit < 1:
        return 1
    return min(limit, MAX_LIMIT)


def list_history(
    access_token: str,
    *,
    limit: int | None = None,
    offset: int = 0,
    kind: str | None = None,
) -> tuple[int, list[dict]]:
    """List the caller's computation history, newest first.

    Returns ``(total_count, rows)``. ``total_count`` comes from PostgREST's
    ``Content-Range`` / ``Prefer: count=exact`` header — we request it via
    the ``Prefer: count=exact`` header (passed as ``prefer``); when absent
    (e.g. on a mocked call), ``total_count`` falls back to ``len(rows)``.
    """
    kind = _validate_kind(kind)
    limit = _clamp_limit(limit)
    if offset < 0:
        offset = 0

    # Build PostgREST query. Select only the columns the UI needs; let RLS
    # filter by user_id automatically.
    path = "/computations?select=id,kind,config,preset,label,inputs,summary,created_at&order=created_at.desc"
    query: dict[str, str] = {
        "limit": str(limit),
        "offset": str(offset),
    }
    if kind is not None:
        # PostgREST filter syntax: ``kind=eq.<value>``.
        query["kind"] = f"eq.{kind}"

    status, payload = pg_rest(
        path,
        access_token=access_token,
        method="GET",
        query=query,
        prefer="count=exact",
    )
    if status != 200:
        # Map PostgREST error to a clean signal; details propagate as-is so
        # logs have something to grep on.
        raise HistoryError(f"PostgREST list failed: {status} {payload}")
    rows = payload if isinstance(payload, list) else []
    return len(rows), rows


def get_history(access_token: str, computation_id: str) -> dict | None:
    """Return one computation row by id, or ``None`` if not found / not owned.

    RLS guarantees a row that does not belong to the caller is invisible, so
    "not owned" and "does not exist" are indistinguishable to the caller —
    both surface as ``None``.
    """
    if not computation_id:
        raise HistoryError("computation_id is required")
    status, payload = pg_rest(
        "/computations",
        access_token=access_token,
        method="GET",
        query={
            "select": "id,kind,config,preset,label,inputs,summary,created_at",
            "id": f"eq.{computation_id}",
            "limit": "1",
        },
    )
    if status != 200:
        raise HistoryError(f"PostgREST get failed: {status} {payload}")
    if not isinstance(payload, list) or not payload:
        return None
    return payload[0]


def save_history(
    access_token: str,
    *,
    kind: str,
    config: str,
    inputs: dict[str, Any],
    preset: str | None = None,
    label: str | None = None,
    summary: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> dict:
    """Insert one row into ``public.computations``.

    ``user_id`` is optional — when provided, it is sent in the body so the
    insert RLS policy ``computations_insert_own`` (which checks
    ``auth.uid() = user_id``) can match. When omitted, the column defaults
    to ``auth.uid()`` via the request JWT (RLS still checks the match).
    """
    if kind not in VALID_KINDS:
        raise HistoryError(f"kind must be one of {sorted(VALID_KINDS)}, got {kind!r}")
    if not config or not isinstance(config, str):
        raise HistoryError("config is required (non-empty string)")
    if not isinstance(inputs, dict):
        raise HistoryError("inputs must be a JSON object")

    body: dict[str, Any] = {
        "kind": kind,
        "config": config,
        "inputs": inputs,
    }
    if preset is not None:
        body["preset"] = preset
    if label is not None:
        body["label"] = label
    if summary is not None:
        body["summary"] = summary
    if user_id is not None:
        body["user_id"] = user_id

    status, payload = pg_rest(
        "/computations",
        access_token=access_token,
        method="POST",
        body=body,
    )
    if status not in (200, 201):
        raise HistoryError(f"PostgREST insert failed: {status} {payload}")
    # With Prefer: return=representation (default for POST in pg_rest), the
    # response is a list containing the inserted row.
    if isinstance(payload, list) and payload:
        return payload[0]
    if isinstance(payload, dict):
        return payload
    return {"ok": True}


def delete_history(access_token: str, computation_id: str) -> bool:
    """Delete one row. Returns ``True`` if a row was deleted, ``False`` if the
    row did not exist (or was not owned by the caller — RLS makes these
    indistinguishable).
    """
    if not computation_id:
        raise HistoryError("computation_id is required")
    status, payload = pg_rest(
        "/computations",
        access_token=access_token,
        method="DELETE",
        query={"id": f"eq.{computation_id}"},
        prefer="return=representation",
    )
    if status not in (200, 204):
        raise HistoryError(f"PostgREST delete failed: {status} {payload}")
    if status == 204 or payload is None:
        # No body returned — assume deleted (caller can verify with a follow-up
        # GET if it matters).
        return True
    # return=representation yields a list of deleted rows; empty list means
    # nothing matched (RLS-filtered).
    return isinstance(payload, list) and len(payload) > 0
