"""Time machine HTTP surface — moonshot #8.

Exposes core.time_machine as four POST/GET endpoints the Staffroom MCP
server proxies. Read-only against the live DB; only writes new files.

Endpoints:
  POST /api/time_machine/snapshot        {reason?}
  GET  /api/time_machine/snapshots
  POST /api/time_machine/fork_from       {unix_ms, note?}
  GET  /api/time_machine/forks
  POST /api/time_machine/prune           {keep_last?, warn_mb?}

The fork_from response names the file path of the fork. The API will
NEVER swap a fork back into the live DB — that is a manual operator
step (documented in docs/staffroom/time-machine.md).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core import time_machine as tm

router = APIRouter(prefix="/api/time_machine", tags=["time-machine"])


class _SnapshotIn(BaseModel):
    reason: str = Field(default="manual", pattern=r"^[a-z0-9_-]{1,40}$")


class _ForkIn(BaseModel):
    unix_ms: int = Field(..., gt=0)
    note: str = Field(default="", max_length=200)


class _PruneIn(BaseModel):
    keep_last: int = Field(default=48, ge=1, le=1000)
    warn_mb: int = Field(default=500, ge=1, le=100_000)


@router.post("/snapshot")
async def snapshot(body: _SnapshotIn) -> dict:
    import asyncio
    try:
        return await asyncio.to_thread(tm.take_snapshot, body.reason)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/snapshots")
async def snapshots() -> dict:
    return tm.list_snapshots()


@router.post("/fork_from")
async def fork_from(body: _ForkIn) -> dict:
    import asyncio
    try:
        return await asyncio.to_thread(tm.fork_from, body.unix_ms, body.note)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/forks")
async def forks() -> dict:
    return tm.list_forks()


@router.post("/prune")
async def prune(body: _PruneIn) -> dict:
    return tm.prune_snapshots(keep_last=body.keep_last, warn_mb=body.warn_mb)
