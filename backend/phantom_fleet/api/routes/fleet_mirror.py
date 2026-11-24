"""
Fleet Mirror (live phone screens + phone control through the Fleet Mirror hub).

    GET /api/fleet-mirror/status          is the hub reachable, which PCs and how many phones
    GET /api/fleet-mirror/embed?serial=…  single-use link (2 min) for the FleetMirrorView iframe

The hub's API key stays on this server; the browser only ever sees the one-time embed link.
Configuration: FLEET_MIRROR_URL, FLEET_MIRROR_API_KEY_FILE, FLEET_MIRROR_CERT_SHA256 (see core/adb_router.py).
"""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, HTTPException, Query

from ...fleet_mirror_client import FleetMirrorClient, FleetMirrorError, api_key_from_env

router = APIRouter()
_SERIAL = re.compile(r"^[A-Za-z0-9._:-]{4,64}$")


def _client() -> FleetMirrorClient:
    key = api_key_from_env()
    if not key:
        raise HTTPException(503, "Fleet Mirror is not configured (FLEET_MIRROR_API_KEY_FILE)")
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
async def fleet_mirror_embed(serial: str = Query(...), control: int = 0, minutes: int = 60, theme: str = "phantom"):
    if not _SERIAL.match(serial):
        raise HTTPException(400, "bad serial")
    try:
        async with _client() as fm:
            r = await fm.embed_url(serial, control=bool(control), minutes=max(1, min(720, minutes)),
                                   theme="phantom" if theme == "phantom" else "")
    except FleetMirrorError as e:
        raise HTTPException(502, f"Fleet Mirror: {e.msg}")
    except OSError as e:
        raise HTTPException(502, f"Fleet Mirror unreachable: {e}")
    return {"url": r["url"], "expires": r["ticket_expires"], "perm": r["perm"]}


@router.get("/embed-wall")
async def fleet_mirror_embed_wall(minutes: int = 480):
    """One-time link (2 min) to the whole Fleet Mirror wall in Phantom Fleet's style, acting for the UI key:
    every phone visible, control only on the phones that key may control."""
    try:
        async with _client() as fm:
            r = await fm.embed_wall(minutes=max(5, min(1440, minutes)), theme="phantom")
    except FleetMirrorError as e:
        raise HTTPException(502, f"Fleet Mirror: {e.msg}")
    except OSError as e:
        raise HTTPException(502, f"Fleet Mirror unreachable: {e}")
    return {"url": r["url"], "expires": r["ticket_expires"], "session_expires": r["session_expires"]}


@router.get("/access")
async def fleet_mirror_access():
    """Which phones Phantom Fleet's screens (UI key) and its agents (agents key) may control."""
    from ...fleet_mirror_client import api_key_from_env as _k
    out = {}
    for role, prefix in (("ui", "FLEET_MIRROR"), ("agents", "FLEET_MIRROR_AGENTS")):
        key = _k(prefix)
        if not key:
            out[role] = {"configured": False}
            continue
        try:
            async with FleetMirrorClient(os.environ.get("FLEET_MIRROR_URL", "http://127.0.0.1:22301"), api_key=key,
                                         cert_sha256=os.environ.get("FLEET_MIRROR_CERT_SHA256", ""), timeout=20) as fm:
                rows = await fm.list_devices()
            out[role] = {"configured": True, "phones": len(rows),
                         "may_control": sorted(p["serial"] for p in rows if p.get("api_control"))}
        except (FleetMirrorError, OSError) as e:
            out[role] = {"configured": True, "error": str(e)}
    return out
