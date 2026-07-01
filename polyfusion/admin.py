"""Admin-only read APIs for v1.2.

Routes in ``app/server.py`` delegate here for ``/api/admin/stats`` and
``/api/admin/users``. Both forward to Supabase PostgREST using the caller's
access token; the schema's ``profiles_select_admin`` /
``computations_select_admin`` RLS policies ensure non-admin callers get only
their own rows (effectively a no-op for admin purposes). The Python layer
does NOT decide admin-ness — that is the architectural stance from the v1.2
synthesis review (A4): "admin 判定下沉 SQL".

Counting note: PostgREST can return exact counts via ``Prefer: count=exact``
+ the ``Content-Range`` header, but ``pg_rest`` returns only ``(status,
payload)``. For the initial admin dashboard we cap user-list / computation
queries at ``STATS_LIMIT`` (1000) rows and count locally — fine for early
deployments. If real user counts exceed the cap, switch these to a
``SECURITY DEFINER`` aggregate RPC.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from polyfusion.postgrest import pg_rest

__all__ = [
    "AdminError",
    "list_users",
    "stats",
    "MAX_LIMIT",
    "DEFAULT_LIMIT",
    "STATS_LIMIT",
    "TOP_AFFILIATIONS_N",
]

MAX_LIMIT = 200
DEFAULT_LIMIT = 50
STATS_LIMIT = 1000
TOP_AFFILIATIONS_N = 10


class AdminError(ValueError):
    """Raised for caller-side validation failures (bad pagination params).

    The HTTP layer maps these to 400 responses.
    """


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if limit < 1:
        return 1
    return min(limit, MAX_LIMIT)


def list_users(
    access_token: str,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[int, list[dict]]:
    """List users visible to the caller (admin → all; non-admin → own row).

    Returns ``(total, rows)``. ``total`` is the number of rows RLS returned
    on this call — i.e. the visible-user count, not a global count (which
    would require an aggregate RPC).
    """
    limit = _clamp_limit(limit)
    if offset < 0:
        offset = 0

    status, payload = pg_rest(
        "/profiles?select=id,username,email,affiliation,is_admin,created_at"
        "&order=created_at.desc",
        access_token=access_token,
        method="GET",
        query={"limit": str(limit), "offset": str(offset)},
    )
    if status != 200:
        raise AdminError(f"PostgREST list failed: {status} {payload}")
    rows = payload if isinstance(payload, list) else []
    return len(rows), rows


def stats(access_token: str) -> dict[str, Any]:
    """Aggregate platform stats visible to the caller.

    Returns a dict shaped as::

        {
            "total_users": int,
            "new_users_7d": int,
            "total_computations": int,
            "top_affiliations": [{"affiliation": str, "count": int}, ...],
        }

    Non-admin callers see only their own row reflected in the counts (an
    artefact of RLS). The architecture stance is: forward, do not branch on
    admin-ness in Python.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    # Reusable closure to keep the three calls below readable. Each runs
    # independently; a failure in any one surfaces as AdminError.
    def _count(path: str) -> list[dict]:
        status, payload = pg_rest(
            path,
            access_token=access_token,
            method="GET",
        )
        if status != 200:
            raise AdminError(f"PostgREST stats fetch failed: {status} {payload}")
        return payload if isinstance(payload, list) else []

    all_profiles = _count(f"/profiles?select=id,affiliation&limit={STATS_LIMIT}")
    new_profiles = _count(
        f"/profiles?select=id&created_at=gte.{cutoff}&limit={STATS_LIMIT}"
    )
    computations = _count(f"/computations?select=id&limit={STATS_LIMIT}")

    # Aggregate affiliations locally — PostgREST doesn't expose GROUP BY
    # without an RPC. ``None`` affiliation (older rows) is bucketed as "".
    aff_counter: Counter[str] = Counter()
    for row in all_profiles:
        aff = row.get("affiliation") or ""
        aff_counter[aff] += 1
    top = [
        {"affiliation": aff, "count": n}
        for aff, n in aff_counter.most_common(TOP_AFFILIATIONS_N)
    ]

    return {
        "total_users": len(all_profiles),
        "new_users_7d": len(new_profiles),
        "total_computations": len(computations),
        "top_affiliations": top,
    }
