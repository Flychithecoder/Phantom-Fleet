"""
Settings routes — global KV store for panel configuration.

Endpoints:
    GET    /api/settings              — list all settings (api key redacted)
    GET    /api/settings/{key}        — get single setting
    POST   /api/settings              — upsert a setting (or batch)
    DELETE /api/settings/{key}        — delete a setting
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("phantom_fleet.api.settings")
router = APIRouter()

_REDACTED_KEYS = {"openrouter_api_key", "api_key", "secret", "password", "token"}


class UpsertRequest(BaseModel):
    key: Optional[str] = None
    value: Optional[str] = None
    # OR batch mode
    settings: Optional[dict[str, str]] = None


def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "Database unavailable")
    return pool


def _maybe_redact(key: str, value: str) -> str:
    if any(k in key.lower() for k in _REDACTED_KEYS):
        return ("••••••••" + value[-4:]) if value and len(value) > 4 else "••••••••"
    return value


@router.get("")
async def list_settings(request: Request):
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch("SELECT key, value, updated_at FROM settings ORDER BY key")
        return [
            {
                "key": r["key"],
                "value": _maybe_redact(r["key"], r["value"] or ""),
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]


@router.get("/{key}")
async def get_setting(key: str, request: Request):
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow("SELECT key, value, updated_at FROM settings WHERE key=$1", key)
        if not row:
            raise HTTPException(404, f"Setting '{key}' not found")
        return {
            "key": row["key"],
            "value": _maybe_redact(row["key"], row["value"] or ""),
            "updated_at": row["updated_at"],
        }


@router.post("")
async def upsert_settings(body: UpsertRequest, request: Request):
    async with _pool(request).acquire() as conn:
        upsert_sql = """
            INSERT INTO settings (key, value)
            VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()
        """
        if body.settings:
            async with conn.transaction():
                for k, v in body.settings.items():
                    await conn.execute(upsert_sql, k, str(v))
            return {"saved": len(body.settings)}
        elif body.key and body.value is not None:
            await conn.execute(upsert_sql, body.key, body.value)
            return {"saved": 1}
        else:
            raise HTTPException(400, "Provide 'key'+'value' or 'settings' dict")


@router.delete("/{key}")
async def delete_setting(key: str, request: Request):
    async with _pool(request).acquire() as conn:
        await conn.execute("DELETE FROM settings WHERE key=$1", key)
        return {"success": True}
