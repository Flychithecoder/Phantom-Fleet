"""
A/B Tests routes — split-test strategies, openers, CTAs, personas.

Hash-based variant assignment: `SHA256(account_id + test_id) % 100 < traffic_split`
→ variant A, otherwise → variant B. Deterministic, no DB write per assignment.

Endpoints:
    GET    /api/ab-tests                   — list tests (filterable by group_id, status)
    POST   /api/ab-tests                   — create test
    GET    /api/ab-tests/{id}              — get test detail
    PATCH  /api/ab-tests/{id}             — update test
    POST   /api/ab-tests/{id}/start        — set status=running
    POST   /api/ab-tests/{id}/pause        — set status=paused
    POST   /api/ab-tests/{id}/end          — set status=ended, record winner
    DELETE /api/ab-tests/{id}              — delete test
    GET    /api/ab-tests/{id}/results      — test results with statistical summary
    POST   /api/ab-tests/{id}/assign       — get variant for an account (A or B)
    POST   /api/ab-tests/{id}/event        — record a conversion event for a variant
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("phantom_fleet.api.ab_tests")
router = APIRouter()

ALLOWED_TYPES = {
    "strategy", "model", "opener_style", "persona",
    "cta_timing", "cta_link", "reply_style", "bait_tone", "custom",
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateTestRequest(BaseModel):
    name: str
    group_id: Optional[str] = None
    test_type: str = "strategy"
    variant_a: dict[str, Any] = {}
    variant_b: dict[str, Any] = {}
    traffic_split: int = 50   # % going to variant A

class UpdateTestRequest(BaseModel):
    name: Optional[str] = None
    test_type: Optional[str] = None
    variant_a: Optional[dict[str, Any]] = None
    variant_b: Optional[dict[str, Any]] = None
    traffic_split: Optional[int] = None

class EndTestRequest(BaseModel):
    winner: Optional[str] = None  # 'a' / 'b' / None

class EventRequest(BaseModel):
    variant: str          # 'a' or 'b'
    event_type: str       # 'follow', 'click', 'dm', 'reply', 'convert'
    value: float = 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "Database unavailable")
    return pool


def _get_variant(account_id: str, test_id: str, traffic_split: int) -> str:
    """
    Deterministic variant assignment. No DB write needed.
    SHA256(account_id + "|" + test_id) → 0-99 → A or B.
    """
    key = f"{account_id}|{test_id}"
    digest = hashlib.sha256(key.encode()).digest()
    bucket = int.from_bytes(digest[:4], "big") % 100
    return "a" if bucket < traffic_split else "b"


def _parse_jsonb(val) -> dict:
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {}
    return val or {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
async def list_tests(request: Request, group_id: Optional[str] = None, status: Optional[str] = None):
    async with _pool(request).acquire() as conn:
        conditions = ["1=1"]
        params: list = []
        idx = 1
        if group_id:
            conditions.append(f"group_id=${idx}")
            params.append(group_id)
            idx += 1
        if status:
            conditions.append(f"status=${idx}")
            params.append(status)
            idx += 1

        rows = await conn.fetch(
            f"SELECT * FROM ab_tests WHERE {' AND '.join(conditions)} ORDER BY created_at DESC",
            *params,
        )
        result = []
        for r in rows:
            d = dict(r)
            for field in ("variant_a", "variant_b", "events_a", "events_b"):
                d[field] = _parse_jsonb(d.get(field))
            result.append(d)
        return result


@router.post("")
async def create_test(body: CreateTestRequest, request: Request):
    if not body.name:
        raise HTTPException(400, "name required")
    if body.test_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"test_type must be one of {sorted(ALLOWED_TYPES)}")
    if not (0 < body.traffic_split < 100):
        raise HTTPException(400, "traffic_split must be 1-99")

    async with _pool(request).acquire() as conn:
        test_id = await conn.fetchval(
            """
            INSERT INTO ab_tests
                (name, group_id, test_type, traffic_split, variant_a, variant_b)
            VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb)
            RETURNING id
            """,
            body.name, body.group_id, body.test_type, body.traffic_split,
            json.dumps(body.variant_a), json.dumps(body.variant_b),
        )
        return {"id": test_id, "name": body.name, "status": "draft"}


@router.get("/{test_id}")
async def get_test(test_id: str, request: Request):
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM ab_tests WHERE id=$1", test_id)
        if not row:
            raise HTTPException(404, "Test not found")
        d = dict(row)
        for field in ("variant_a", "variant_b", "events_a", "events_b"):
            d[field] = _parse_jsonb(d.get(field))
        return d


@router.patch("/{test_id}")
async def update_test(test_id: str, body: UpdateTestRequest, request: Request):
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM ab_tests WHERE id=$1", test_id)
        if not row:
            raise HTTPException(404, "Test not found")
        if row["status"] == "running":
            raise HTTPException(400, "Cannot edit a running test — pause it first")

        sets, vals, idx = [], [], 1
        if body.name is not None:          sets.append(f"name=${idx}");          vals.append(body.name); idx+=1
        if body.test_type is not None:
            if body.test_type not in ALLOWED_TYPES:
                raise HTTPException(400, f"Invalid test_type")
            sets.append(f"test_type=${idx}"); vals.append(body.test_type); idx+=1
        if body.variant_a is not None:     sets.append(f"variant_a=${idx}::jsonb"); vals.append(json.dumps(body.variant_a)); idx+=1
        if body.variant_b is not None:     sets.append(f"variant_b=${idx}::jsonb"); vals.append(json.dumps(body.variant_b)); idx+=1
        if body.traffic_split is not None:
            if not (0 < body.traffic_split < 100):
                raise HTTPException(400, "traffic_split must be 1-99")
            sets.append(f"traffic_split=${idx}"); vals.append(body.traffic_split); idx+=1

        if not sets:
            raise HTTPException(400, "Nothing to update")

        vals.append(test_id)
        await conn.execute(f"UPDATE ab_tests SET {', '.join(sets)} WHERE id=${idx}", *vals)
        return {"success": True}


@router.post("/{test_id}/start")
async def start_test(test_id: str, request: Request):
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM ab_tests WHERE id=$1", test_id)
        if not row:
            raise HTTPException(404, "Test not found")
        await conn.execute(
            "UPDATE ab_tests SET status='running', started_at=now() WHERE id=$1", test_id
        )
        return {"success": True, "status": "running"}


@router.post("/{test_id}/pause")
async def pause_test(test_id: str, request: Request):
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM ab_tests WHERE id=$1", test_id)
        if not row:
            raise HTTPException(404, "Test not found")
        await conn.execute("UPDATE ab_tests SET status='paused' WHERE id=$1", test_id)
        return {"success": True, "status": "paused"}


@router.post("/{test_id}/end")
async def end_test(test_id: str, body: EndTestRequest, request: Request):
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM ab_tests WHERE id=$1", test_id)
        if not row:
            raise HTTPException(404, "Test not found")
        await conn.execute(
            "UPDATE ab_tests SET status='ended', ended_at=now(), winner=$1 WHERE id=$2",
            body.winner, test_id,
        )
        return {"success": True, "status": "ended", "winner": body.winner}


@router.delete("/{test_id}")
async def delete_test(test_id: str, request: Request):
    async with _pool(request).acquire() as conn:
        await conn.execute("DELETE FROM ab_tests WHERE id=$1", test_id)
        return {"ok": True}


@router.get("/{test_id}/results")
async def test_results(test_id: str, request: Request):
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM ab_tests WHERE id=$1", test_id)
        if not row:
            raise HTTPException(404, "Test not found")

    d = dict(row)
    events_a = _parse_jsonb(d.get("events_a"))
    events_b = _parse_jsonb(d.get("events_b"))

    total_a = sum(events_a.values()) if events_a else 0
    total_b = sum(events_b.values()) if events_b else 0

    def _rate(events: dict) -> float:
        follows = events.get("follow", 0)
        clicks  = events.get("click",  0)
        total   = follows + clicks
        converts = events.get("convert", 0)
        return (converts / total * 100) if total > 0 else 0.0

    return {
        "test_id":      test_id,
        "name":         d["name"],
        "status":       d["status"],
        "winner":       d["winner"],
        "traffic_split": d["traffic_split"],
        "variant_a": {
            "config":      _parse_jsonb(d.get("variant_a")),
            "events":      events_a,
            "total_events": total_a,
            "convert_rate": _rate(events_a),
        },
        "variant_b": {
            "config":      _parse_jsonb(d.get("variant_b")),
            "events":      events_b,
            "total_events": total_b,
            "convert_rate": _rate(events_b),
        },
        "started_at": d.get("started_at"),
        "ended_at":   d.get("ended_at"),
    }


@router.post("/{test_id}/assign")
async def assign_variant(test_id: str, request: Request, account_id: str):
    """Return which variant (a/b) this account is assigned to."""
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow("SELECT traffic_split, status FROM ab_tests WHERE id=$1", test_id)
        if not row:
            raise HTTPException(404, "Test not found")
        if row["status"] not in ("running", "paused"):
            raise HTTPException(400, f"Test is not running (status={row['status']})")

    variant = _get_variant(account_id, test_id, row["traffic_split"])
    return {"account_id": account_id, "test_id": test_id, "variant": variant}


@router.post("/{test_id}/event")
async def record_event(test_id: str, body: EventRequest, request: Request):
    """Record a conversion/engagement event for variant A or B."""
    if body.variant not in ("a", "b"):
        raise HTTPException(400, "variant must be 'a' or 'b'")

    column = "events_a" if body.variant == "a" else "events_b"

    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow(f"SELECT {column} FROM ab_tests WHERE id=$1", test_id)
        if not row:
            raise HTTPException(404, "Test not found")

        events = _parse_jsonb(row[column])
        events[body.event_type] = events.get(body.event_type, 0) + body.value

        await conn.execute(
            f"UPDATE ab_tests SET {column}=$1::jsonb WHERE id=$2",
            json.dumps(events), test_id,
        )
    return {"success": True, "variant": body.variant, "event_type": body.event_type}
