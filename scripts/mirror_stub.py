"""
Phantom Fleet Mirror — dev stub.

A minimal FastAPI server that implements the §9 MVP checklist from
docs/architecture/MIRROR_CONTRACT.md:

    - GET  /devices
    - GET  /devices/{serial}
    - GET  /health
    - POST /devices/{serial}/adb/acquire
    - POST /devices/{serial}/adb/release
    - WS   /events

It serves 19 synthetic Galaxy S21 FE 5G devices (matching the connected farm).
One of them uses the REAL serial (R5CRC0J6CGT) so the backend can tell the
stub apart from the actual ADB-reachable phone when debugging.

Run:
    python scripts/mirror_stub.py
    (or: uvicorn scripts.mirror_stub:app --port 8765)

This is for UI / integration work only — it does NOT perform real screen
mirroring, USB enumeration, or ADB claim handoff. The acquire/release
endpoints are no-ops that return success so the panel's claim_adb()
context manager exercises the happy path.

Never ship this to prod. The hard-rule §8 of the contract (stable serials,
no fingerprint homogenisation, etc.) is enforced here by design, but the
stub generates fingerprints deterministically so the fleet LOOKS clean to
the panel while there is no real phone diversity.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect


# ---------------------------------------------------------------------------
# Synthetic fleet
# ---------------------------------------------------------------------------

# One real + 18 synthetic serials. The real one lets us correlate the stub's
# /devices output against the live `adb devices` list during manual testing.
_REAL_SERIAL = "R5CRC0J6CGT"
_SERIAL_POOL = [_REAL_SERIAL] + [
    # Samsung-style serials: alphanumeric, 10-11 chars. Deterministic from
    # the index so a reboot of the stub serves the same fleet.
    f"R5CRC{i:05d}XP"
    for i in range(1, 19)
]


def _hex_id(seed: str, length: int = 16) -> str:
    """Deterministic hex id from a seed. Stable across restarts."""
    return hashlib.sha256(seed.encode()).hexdigest()[:length]


def _make_device(idx: int, serial: str) -> dict[str, Any]:
    """Build a MirrorDevice-shaped dict per CONTRACT.md §1.1 + §2."""
    model = "SM-G990U1"                         # Galaxy S21 FE 5G US
    # S21 FE 5G shipped with Android 12, OTA'd through 14. Pick within range
    # so the persona factory's MODEL_OS_RANGES pair-check passes. Rotating
    # by index avoids all 19 claiming the same OS (cluster-detection tell).
    android_versions = ["12", "13", "14"]
    build_ids = {
        "12": "SP1A.210812.016",
        "13": "TP1A.220624.014",
        "14": "UP1A.231005.007",
    }
    android_version = android_versions[idx % len(android_versions)]
    battery_pct = 30 + (idx * 7) % 70            # 30..100, deterministic
    connected = (idx != 4)                        # idx 4 = tile 05 "disconnected"

    return {
        "serial": serial,
        "state": "online" if connected else "offline",
        "connection": "usb",
        "mirror_slot": idx + 1,
        "model": model,
        "product": "r9quew",
        "device_codename": "r9q",
        "android_version": android_version,
        "build_id": build_ids[android_version],
        "wifi_ip": f"192.168.1.{40 + idx}" if connected else None,
        "battery_pct": battery_pct,
        "screen_on": connected and (idx % 3 != 0),
        "disconnected_reason": None if connected else "usb_cable_removed",
        "adb_claim": {"holder": "mirror", "released_until": None},
        "hw": {
            "manufacturer": "samsung",
            "brand": "samsung",
            "device": "r9q",
            "fingerprint": (
                f"samsung/r9quew/r9q:{android_version}/"
                f"{build_ids[android_version]}/"
                f"G990U1UES4GWC{idx}:user/release-keys"
            ),
            # Every id below MUST be unique per device (contract §2 hard rule).
            "advertising_id": _hex_id(f"gaid:{serial}", 32),
            "android_id":     _hex_id(f"aid:{serial}",  16),
            "gsf_id":         _hex_id(f"gsf:{serial}",  16),
            "imei":           None,
            "wifi_mac":       f"02:00:{serial[-6:-4]}:{serial[-4:-2]}:{serial[-2:]}:aa",
            "bluetooth_mac":  f"02:00:{serial[-6:-4]}:{serial[-4:-2]}:{serial[-2:]}:bb",
            "serialno_prop":  serial,
            "spoofed":        serial != _REAL_SERIAL,   # flag stub entries
        },
    }


_DEVICES: dict[str, dict[str, Any]] = {
    s: _make_device(i, s) for i, s in enumerate(_SERIAL_POOL)
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


_subscribers: set[asyncio.Queue] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Drain all WS queues on shutdown
    for q in _subscribers:
        try:
            q.put_nowait(None)
        except Exception:
            pass


app = FastAPI(title="Phantom Fleet Mirror (stub)", lifespan=lifespan)


@app.get("/health")
async def health():
    online = sum(1 for d in _DEVICES.values() if d["state"] == "online")
    return {
        "status": "ok",
        "uptime_sec": 0,              # stub doesn't track
        "devices_total": len(_DEVICES),
        "devices_online": online,
        "adb_server_pid": 0,
    }


@app.get("/devices")
async def list_devices():
    return {
        "schema_version": 1,
        "host_id": "phantom-fleet-mirror-stub",
        "server_time": _now(),
        "devices": list(_DEVICES.values()),
    }


@app.get("/devices/{serial}")
async def get_device(serial: str):
    dev = _DEVICES.get(serial)
    if dev is None:
        raise HTTPException(status_code=404, detail="unknown serial")
    return dev


@app.post("/devices/{serial}/adb/acquire")
async def acquire(serial: str, body: dict[str, Any]):
    if serial not in _DEVICES:
        raise HTTPException(status_code=404, detail="unknown serial")
    ttl = int(body.get("ttl_sec", 60))
    holder = str(body.get("holder", ""))
    # Broadcast the handoff so WS subscribers see it (mirrors real behaviour).
    await _broadcast({
        "ts": _now(),
        "type": "adb.released",
        "serial": serial,
        "holder": holder,
        "ttl_sec": ttl,
    })
    return {
        "granted": True,
        "released_until": _now(),      # stub always grants immediately
        "adb_server_port": 5037,
    }


@app.post("/devices/{serial}/adb/release")
async def release(serial: str, body: dict[str, Any]):
    if serial not in _DEVICES:
        raise HTTPException(status_code=404, detail="unknown serial")
    await _broadcast({
        "ts": _now(),
        "type": "adb.reclaimed",
        "serial": serial,
        "holder": "mirror",
    })
    return {"released": True}


# ---------------------------------------------------------------------------
# WS /events
# ---------------------------------------------------------------------------


async def _broadcast(event: dict[str, Any]) -> None:
    dead: list[asyncio.Queue] = []
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.discard(q)


@app.websocket("/events")
async def events(ws: WebSocket):
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _subscribers.add(q)
    try:
        # Prime the new subscriber with the current fleet state.
        for dev in _DEVICES.values():
            await ws.send_text(json.dumps({
                "ts": _now(),
                "type": "device.connected" if dev["state"] == "online"
                        else "device.disconnected",
                "serial": dev["serial"],
            }))
        while True:
            event = await q.get()
            if event is None:
                break
            await ws.send_text(json.dumps(event))
    except WebSocketDisconnect:
        pass
    finally:
        _subscribers.discard(q)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
