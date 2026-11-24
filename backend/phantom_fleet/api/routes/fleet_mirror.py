"""
Fleet Mirror (live phone screens + phone control through the Fleet Mirror hub).

    GET /api/fleet-mirror/status          is the hub reachable, which PCs and how many phones
    GET /api/fleet-mirror/embed?serial=…  single-use link (2 min) for the FleetMirrorView iframe

The hub's API key stays on this server; the browser only ever sees the one-time embed link.
Configuration: FLEET_MIRROR_URL, FLEET_MIRROR_API_KEY, FLEET_MIRROR_CERT_SHA256 (see core/adb_router.py).
"""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, HTTPException, Query

from ...fleet_mirror_client import FleetMirrorClient, FleetMirrorError

router = APIRouter()
_SERIAL = re.compile(r"^[A-Za-z0-9._:-]{4,64}$")


def _client() -> FleetMirrorClient:
    key = os.environ.get("FLEET_MIRROR_API_KEY", "")
    if not key:
        raise HTTPException(503, "Fleet Mirror is not configured (FLEET_MIRROR_API_KEY)")
    return FleetMirrorClient(os.environ.get("FLEET_MIRROR_URL", "http://127.0.0.1:22301"), api_key=key,
                             cert_sha256=os.environ.get("FLEET_MIRROR_CERT_SHA256", ""), timeout=20)


@router.get("/status")
async def fleet_mirror_status():
    try:
        async with _client() as fm:
            hosts = await fm.list_hosts()
            phones = await fm.list_devices()
    except (FleetMirrorError, OSError) as e:
        return {"reachable": False, "error": str(e)}
    return {"reachable": True, "adb_routed": os.environ.get("FLEET_MIRROR_ADB", "") in ("1", "true", "yes", "on"),
            "hosts": [{k: h.get(k) for k in ("host", "connected", "phones", "online", "version")} for h in hosts],
            "phones": len(phones), "online": sum(1 for p in phones if p.get("state") == "device")}


@router.get("/embed")
async def fleet_mirror_embed(serial: str = Query(...), control: int = 0, minutes: int = 60):
    if not _SERIAL.match(serial):
        raise HTTPException(400, "bad serial")
    try:
        async with _client() as fm:
            r = await fm.embed_url(serial, control=bool(control), minutes=max(1, min(720, minutes)))
    except FleetMirrorError as e:
        raise HTTPException(502, f"Fleet Mirror: {e.msg}")
    except OSError as e:
        raise HTTPException(502, f"Fleet Mirror unreachable: {e}")
    return {"url": r["url"], "expires": r["ticket_expires"], "perm": r["perm"]}
