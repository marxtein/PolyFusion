"""Current-user profile lookup via Supabase PostgREST."""

from __future__ import annotations

from polyfusion.postgrest import pg_rest

__all__ = ["ProfileError", "delete_current_account", "get_profile"]


class ProfileError(ValueError):
    """Raised when the profile lookup returns an unexpected response."""


def get_profile(access_token: str, user_id: str) -> dict | None:
    if not access_token or not user_id:
        return None
    status, payload = pg_rest(
        "/profiles?select=id,username,email,affiliation,is_admin",
        access_token=access_token,
        method="GET",
        query={"id": f"eq.{user_id}", "limit": "1"},
    )
    if status != 200:
        raise ProfileError(f"PostgREST profile fetch failed: {status} {payload}")
    rows = payload if isinstance(payload, list) else []
    return rows[0] if rows else None


def delete_current_account(access_token: str) -> None:
    if not access_token:
        raise ProfileError("session token missing")
    status, payload = pg_rest(
        "/rpc/delete_current_user",
        access_token=access_token,
        method="POST",
        body={},
    )
    if status not in (200, 204):
        raise ProfileError(f"PostgREST account delete failed: {status} {payload}")
    if payload is False:
        raise ProfileError("account delete failed")
