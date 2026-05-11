"""
Groups routes — campaign / model organisation.

Endpoints:
    POST   /api/groups/register           — HQ model registry (idempotent upsert)
    GET    /api/groups                    — list all groups with account count
    POST   /api/groups                    — create group
    PATCH  /api/groups/{id}               — update group fields
    DELETE /api/groups/{id}               — delete group
    POST   /api/groups/{id}/assign        — assign account IDs to group
    POST   /api/groups/{id}/unassign      — remove account IDs from group
    GET    /api/groups/{id}/accounts      — list accounts in group
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("phantom_fleet.api.groups")
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RegisterGroupRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    hq_model_id: str

class CreateGroupRequest(BaseModel):
    name: str
    color: str = "#7c3aed"
    description: Optional[str] = None
    mother_account: Optional[str] = None
    link_in_bio: Optional[str] = None
    bio_template: Optional[str] = None
    sister_account_id: Optional[str] = None
    target_accounts: list[str] = []
    target_hashtags: list[str] = []
    target_keywords: list[str] = []
    settings: dict = {}

class UpdateGroupRequest(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    mother_account: Optional[str] = None
    link_in_bio: Optional[str] = None
    bio_template: Optional[str] = None
    sister_account_id: Optional[str] = None
    target_accounts: Optional[list[str]] = None
    target_hashtags: Optional[list[str]] = None
    target_keywords: Optional[list[str]] = None
    settings: Optional[dict] = None

class AssignRequest(BaseModel):
    account_ids: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "Database unavailable")
    return pool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/register")
async def register_group(body: RegisterGroupRequest, request: Request):
    """HQ model registry — idempotent upsert by hq_model_id."""
    import json
    async with _pool(request).acquire() as conn:
        # Check by hq_model_id first
        row = await conn.fetchrow("SELECT * FROM groups WHERE hq_model_id = $1", body.hq_model_id)
        if row:
            if row["name"] != body.name:
                await conn.execute("UPDATE groups SET name=$1 WHERE id=$2", body.name, row["id"])
            return {"group_id": row["id"], "name": body.name, "hq_model_id": body.hq_model_id, "action": "existing"}

        # Fallback: check by name
        row = await conn.fetchrow("SELECT * FROM groups WHERE name = $1", body.name)
        if row:
            await conn.execute(
                "UPDATE groups SET hq_model_id=$1, slug=$2 WHERE id=$3",
                body.hq_model_id, body.slug, row["id"],
            )
            return {"group_id": row["id"], "name": body.name, "hq_model_id": body.hq_model_id, "action": "existing"}

        # Create new
        gid = await conn.fetchval(
            """
            INSERT INTO groups (name, slug, hq_model_id, color)
            VALUES ($1, $2, $3, '#7c3aed')
            RETURNING id
            """,
            body.name, body.slug, body.hq_model_id,
        )
        log.info("Group created for model: %s", body.name)
        return {"group_id": gid, "name": body.name, "hq_model_id": body.hq_model_id, "action": "created"}


@router.get("")
async def list_groups(request: Request):
    import json
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch("""
            SELECT g.*,
                   COUNT(a.id) AS account_count,
                   sa.username AS sister_username
            FROM groups g
            LEFT JOIN accounts a ON a.group_id = g.id
            LEFT JOIN accounts sa ON sa.id = g.sister_account_id
            GROUP BY g.id, sa.username
            ORDER BY g.created_at ASC
        """)
        result = []
        for r in rows:
            d = dict(r)
            # JSONB fields come back as strings from asyncpg — normalise
            for field in ("target_accounts", "target_hashtags", "target_keywords", "settings"):
                if isinstance(d.get(field), str):
                    try:
                        d[field] = json.loads(d[field])
                    except Exception:
                        pass
            result.append(d)
        return result


@router.post("")
async def create_group(body: CreateGroupRequest, request: Request):
    import json
    async with _pool(request).acquire() as conn:
        gid = await conn.fetchval(
            """
            INSERT INTO groups
                (name, color, description, mother_account, link_in_bio, bio_template,
                 sister_account_id, target_accounts, target_hashtags, target_keywords, settings)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb,$10::jsonb,$11::jsonb)
            RETURNING id
            """,
            body.name.strip(), body.color, body.description, body.mother_account,
            body.link_in_bio, body.bio_template, body.sister_account_id,
            json.dumps(body.target_accounts),
            json.dumps(body.target_hashtags),
            json.dumps(body.target_keywords),
            json.dumps(body.settings),
        )
        log.info("Group created: %s", body.name)
        return {"id": gid, "name": body.name}


@router.patch("/{group_id}")
async def update_group(group_id: str, body: UpdateGroupRequest, request: Request):
    import json
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM groups WHERE id=$1", group_id)
        if not row:
            raise HTTPException(404, "Group not found")

        sets, vals = [], []
        idx = 1
        simple_fields = {
            "name": body.name, "color": body.color, "description": body.description,
            "mother_account": body.mother_account, "link_in_bio": body.link_in_bio,
            "bio_template": body.bio_template, "sister_account_id": body.sister_account_id,
        }
        for col, val in simple_fields.items():
            if val is not None:
                sets.append(f"{col}=${idx}")
                vals.append(val)
                idx += 1

        for col in ("target_accounts", "target_hashtags", "target_keywords", "settings"):
            val = getattr(body, col)
            if val is not None:
                sets.append(f"{col}=${idx}::jsonb")
                vals.append(json.dumps(val))
                idx += 1

        if not sets:
            raise HTTPException(400, "Nothing to update")

        vals.append(group_id)
        await conn.execute(f"UPDATE groups SET {', '.join(sets)} WHERE id=${idx}", *vals)
        return {"success": True}


@router.delete("/{group_id}")
async def delete_group(group_id: str, request: Request):
    async with _pool(request).acquire() as conn:
        await conn.execute("DELETE FROM groups WHERE id=$1", group_id)
        return {"success": True}


@router.post("/{group_id}/assign")
async def assign_accounts(group_id: str, body: AssignRequest, request: Request):
    if not body.account_ids:
        raise HTTPException(400, "account_ids required")
    async with _pool(request).acquire() as conn:
        async with conn.transaction():
            for aid in body.account_ids:
                await conn.execute("UPDATE accounts SET group_id=$1 WHERE id=$2", group_id, aid)
        log.info("Assigned %d accounts to group %s", len(body.account_ids), group_id)
        return {"assigned": len(body.account_ids)}


@router.post("/{group_id}/unassign")
async def unassign_accounts(group_id: str, body: AssignRequest, request: Request):
    async with _pool(request).acquire() as conn:
        async with conn.transaction():
            for aid in body.account_ids:
                await conn.execute("UPDATE accounts SET group_id=NULL WHERE id=$1", aid)
        return {"unassigned": len(body.account_ids)}


@router.get("/{group_id}/accounts")
async def group_accounts(group_id: str, request: Request):
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch("""
            SELECT a.*, p.host AS proxy_host, p.port AS proxy_port
            FROM accounts a
            LEFT JOIN proxies p ON a.proxy_id = p.id
            WHERE a.group_id = $1
            ORDER BY a.created_at DESC
        """, group_id)
        return [dict(r) for r in rows]
