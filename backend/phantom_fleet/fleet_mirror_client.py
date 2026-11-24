"""Fleet Mirror client for Phantom Fleet's backend (async, httpx).

Drives every phone on every host PC through the Fleet Mirror hub's local API (/papi), so Phantom Fleet
never has to run its own adb client against a shared adb server (a different adb version restarts the
server and drops every phone on it).

    from fleet_mirror_client import FleetMirrorClient

    async with FleetMirrorClient("https://192.168.1.16:22300", api_key=KEY,
                                 cert_sha256="EC:12:...:8B:37") as fm:
        phones = await fm.list_devices()
        await fm.swipe("R5CRC08L4QM", [[540, 1600], [540, 900], [540, 400]], [140, 90], unit="px")
        png = await fm.screenshot("R5CRC08L4QM")

Timing: tap/swipe/long_press take the exact points and delays the caller computed (Phantom Fleet's
LogNormal/Normal/Bimodal distributions). Nothing here adds randomness.

Certificate: the hub uses a self-signed certificate. Pass its SHA-256 fingerprint (shown in the hub log
and in Fleet Mirror's Add PC dialog); the client checks it and then trusts exactly that certificate.
On the hub PC itself you can use http://127.0.0.1:22301 instead (no TLS, this PC only).

Every input action (tap, swipe, keys, text, install, tasks) only reaches phones whose control is enabled
in the hub config (control_enabled + control_serials); others are skipped and not listed in "sent".
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import ssl
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit

import httpx

Devices = str | Sequence[str]   # "all", one serial, or a list of serials


def api_key_from_env() -> str:
    """FLEET_MIRROR_API_KEY, or the contents of the file named by FLEET_MIRROR_API_KEY_FILE.
    Prefer the file: keep the key out of .env files that are committed to git."""
    import os
    key = os.environ.get("FLEET_MIRROR_API_KEY", "").strip()
    if key:
        return key
    path = os.environ.get("FLEET_MIRROR_API_KEY_FILE", "").strip()
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


class FleetMirrorError(RuntimeError):
    def __init__(self, code: int, msg: str, action: str = ""):
        super().__init__(f"{action or 'papi'}: {msg} (code {code})")
        self.code, self.msg, self.action = code, msg, action


def norm_fp(fp: str) -> str:
    return "".join(c for c in str(fp) if c in "0123456789abcdefABCDEF").upper()


def pem_fingerprint(pem: str) -> str:
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest().upper()


async def pinned_ssl_context(host: str, port: int, cert_sha256: str) -> ssl.SSLContext:
    """Fetch the server certificate, check its SHA-256, then trust exactly that certificate."""
    pem = await asyncio.to_thread(ssl.get_server_certificate, (host, port))
    got = pem_fingerprint(pem)
    if got != norm_fp(cert_sha256):
        raise FleetMirrorError(495, f"hub certificate fingerprint mismatch: got {got}, expected {norm_fp(cert_sha256)}")
    ctx = ssl.create_default_context(cadata=pem)
    ctx.check_hostname = False   # the pinned certificate itself is the trust anchor
    return ctx


def _devices(d: Devices) -> Any:
    if isinstance(d, str):
        return d   # "all" or "SERIAL" or "S1,S2"
    return list(d)


class FleetMirrorClient:
    def __init__(self, hub_url: str = "http://127.0.0.1:22301", *, api_key: str, cert_sha256: str = "",
                 timeout: float = 120.0, transport: httpx.AsyncBaseTransport | None = None):
        self.hub_url = hub_url.rstrip("/")
        self.api_key = api_key
        self.cert_sha256 = cert_sha256
        self.timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "FleetMirrorClient":
        await self.open()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def open(self) -> None:
        if self._client:
            return
        verify: Any = True
        u = urlsplit(self.hub_url)
        if u.scheme == "https" and self._transport is None:
            if not self.cert_sha256:
                raise FleetMirrorError(495, "https hub needs cert_sha256 (the hub certificate fingerprint)")
            verify = await pinned_ssl_context(u.hostname or "", u.port or 443, self.cert_sha256)
        self._client = httpx.AsyncClient(base_url=self.hub_url, timeout=self.timeout, verify=verify,
                                         headers={"X-Api-Key": self.api_key}, transport=self._transport)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ---------------- core ----------------
    async def papi(self, action: str, devices: Devices = "all", data: dict | None = None) -> Any:
        """One Panda-compatible API call. Returns its "data"; raises FleetMirrorError on failure."""
        await self.open()
        r = await self._client.post("/papi", json={"action": action, "devices": _devices(devices), "data": data or {}})
        if r.status_code == 401:
            raise FleetMirrorError(401, "missing or wrong API key", action)
        r.raise_for_status()
        body = r.json()
        if body.get("code") != 10000:
            raise FleetMirrorError(int(body.get("code", 10003)), str(body.get("msg")), action)
        return body.get("data")

    async def upload(self, path: str | Path, name: str | None = None) -> str:
        """Upload a file to the hub; returns its file id (for install_apk / push_file)."""
        await self.open()
        p = Path(path)
        r = await self._client.post("/papi", params={"upload": "1", "name": name or p.name}, content=p.read_bytes())
        r.raise_for_status()
        body = r.json()
        if body.get("code") != 10000:
            raise FleetMirrorError(int(body.get("code", 10003)), str(body.get("msg")), "upload")
        return body["data"]["file"]

    @staticmethod
    def by_serial(rows: Iterable[dict]) -> dict[str, dict]:
        return {r["serial"]: r for r in rows or []}

    # ---------------- inventory ----------------
    async def list_devices(self) -> list[dict]:
        return await self.papi("list")

    async def list_hosts(self) -> list[dict]:
        return await self.papi("host")

    async def screen_size(self, devices: Devices = "all") -> dict[str, tuple[int, int]]:
        return {r["serial"]: (r["width"], r["height"]) for r in await self.papi("screenSize", devices)}

    # ---------------- input (caller-supplied timing) ----------------
    async def tap(self, devices: Devices, x: float, y: float, unit: str = "percent") -> list[str]:
        return (await self.papi("tap", devices, {"x": x, "y": y, "unit": unit}))["sent"]

    async def swipe(self, devices: Devices, points: Sequence[Sequence[float]], durations_ms: Sequence[float],
                    hold_ms: float = 0, unit: str = "percent") -> list[str]:
        """points: [[x, y], ...] (2-500); durations_ms: one delay per segment, applied exactly."""
        return (await self.papi("swipe", devices, {"points": [list(p) for p in points],
                                                   "durations_ms": list(durations_ms), "hold_ms": hold_ms,
                                                   "unit": unit}))["sent"]

    async def long_press(self, devices: Devices, x: float, y: float, duration_ms: float, unit: str = "percent") -> list[str]:
        return (await self.papi("longPress", devices, {"x": x, "y": y, "duration_ms": duration_ms, "unit": unit}))["sent"]

    async def key(self, devices: Devices, key: str | int) -> list[str]:
        """key: back, home, recents, menu, power, volup, voldown, or an Android keycode."""
        data = {"keycode": key} if isinstance(key, int) else {"key": key}
        return (await self.papi("pushEvent", devices, data))["sent"]

    async def text(self, devices: Devices, text: str) -> list[dict]:
        return await self.papi("inputText", devices, {"content": text})

    async def set_clipboard(self, devices: Devices, text: str) -> list[dict]:
        return await self.papi("writeClipboard", devices, {"content": text})

    async def get_clipboard(self, devices: Devices) -> dict[str, str]:
        return {r["serial"]: r.get("out", "") for r in await self.papi("getClipboard", devices)}

    # ---------------- adb-style operations ----------------
    async def shell(self, devices: Devices, command: str, timeout: float = 120) -> dict[str, tuple[bool, str]]:
        rows = await self.papi("adb", devices, {"command": command, "timeout": timeout})
        return {r["serial"]: (bool(r.get("ok")), r.get("out", "")) for r in rows}

    async def install_apk(self, devices: Devices, apk_path: str | Path) -> dict[str, tuple[bool, str]]:
        fid = await self.upload(apk_path)
        rows = await self.papi("installApk", devices, {"file": fid, "timeout": 300})
        return {r["serial"]: (bool(r.get("ok")), r.get("out", "")) for r in rows}

    async def uninstall_apk(self, devices: Devices, package: str) -> dict[str, tuple[bool, str]]:
        rows = await self.papi("uninstallApk", devices, {"package": package})
        return {r["serial"]: (bool(r.get("ok")), r.get("out", "")) for r in rows}

    async def start_app(self, devices: Devices, package: str) -> list[dict]:
        return await self.papi("startApk", devices, {"package": package})

    async def stop_app(self, devices: Devices, package: str) -> list[dict]:
        return await self.papi("stopApk", devices, {"package": package})

    async def screenshot(self, serial: str) -> bytes:
        rows = await self.papi("screen", serial, {"base64": True})
        row = rows[0] if rows else {}
        if not row.get("ok") or not row.get("png_base64"):
            raise FleetMirrorError(10003, row.get("out") or "no screenshot", "screen")
        return base64.b64decode(row["png_base64"])

    # ---------------- automation ----------------
    async def list_actions(self) -> list[dict]:
        return await self.papi("listActions")

    async def list_scripts(self) -> list[dict]:
        return await self.papi("listScripts")

    async def run_task(self, devices: Devices, *, action_id: str | None = None, script_id: str | None = None,
                       loop_count: int = 1, loop_interval: tuple[float, float] = (0, 0), device_interval: float = 0,
                       start_at: float = 0, speed: float = 1.0, name: str = "") -> dict:
        """Run a recorded action or a saved script as a task; returns {id, phones, skipped_busy_or_no_control}."""
        if bool(action_id) == bool(script_id):
            raise ValueError("give exactly one of action_id or script_id")
        data = {"type": "action" if action_id else "script", "action": action_id, "script": script_id,
                "loop_count": loop_count, "loop_interval": list(loop_interval), "device_interval": device_interval,
                "start_at": start_at, "speed": speed, "name": name}
        return await self.papi("runTask", devices, data)

    async def task_status(self, task_id: str) -> dict:
        return await self.papi("taskStatus", data={"id": task_id})

    async def task_op(self, task_id: str, op: str, serials: Sequence[str] | None = None) -> dict:
        """op: pause, continue or stop."""
        return await self.papi("taskOp", data={"id": task_id, "op": op, "serials": list(serials or [])})

    async def wait_task(self, task_id: str, timeout: float = 600, every: float = 1.0) -> dict:
        end = asyncio.get_running_loop().time() + timeout
        while True:
            t = await self.task_status(task_id)
            if t["status"] not in ("scheduled", "running", "paused"):
                return t
            if asyncio.get_running_loop().time() > end:
                raise TimeoutError(f"task {task_id} still {t['status']}")
            await asyncio.sleep(every)

    # ---------------- live view ----------------
    async def embed_url(self, devices: Devices, control: bool = False, minutes: float = 60, base: str = "",
                        theme: str = "phantom") -> dict:
        """A single-use link (valid 2 minutes) for an <iframe>: the phone's live screen (and control if asked).
        Mint a new one each time the page renders. theme "phantom" = Phantom Fleet's look (dark, neon accent,
        transparent page); "" = Fleet Mirror's own look."""
        data = {"control": control, "minutes": minutes, "theme": theme}
        if base:
            data["base"] = base
        return await self.papi("embedLink", devices, data)
