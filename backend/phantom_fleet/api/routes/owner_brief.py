"""Owner Decision Brief HTTP surface — moonshot #9."""

from __future__ import annotations

from fastapi import APIRouter

from ...core.owner_brief import owner_brief

router = APIRouter(prefix="/api/owner_brief", tags=["owner-brief"])


@router.get("")
async def brief() -> dict:
    import asyncio
    return await asyncio.to_thread(owner_brief)
