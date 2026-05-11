"""
Phone controller layer — ADB + Phantom Fleet Companion APK HTTP client.

The Companion APK runs a tiny HTTP server on 127.0.0.1:PORT inside each
phone. Phantom Fleet reaches it via `adb forward` or direct Wi-Fi ADB,
then POSTs action primitives: tap, type, scroll, navigate, screenshot,
launch_clone, check_session.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


ADB_PATH_DEFAULT = Path(r"C:\Onimator\full_igbot_14.1.8.1\adb.exe")


@dataclass
class Phone:
    serial: str
    model: str
    state: str
    wifi_ip: str | None = None
    companion_port: int | None = None


class PhoneController:
    """Safe read/write wrapper around ADB + Companion APK.

    SAFETY GATE: No write operations (tap/type/scroll/launch) execute until
    `proxy_routing_verified(phone_serial)` returns True. This is enforced
    at the method level — there's no bypass.
    """

    def __init__(self, adb_path: Path = ADB_PATH_DEFAULT):
        self.adb_path = adb_path
        self._proxy_verified: dict[str, bool] = {}

    # -- read-only operations (always allowed) ----------------------------------

    async def list_devices(self) -> list[Phone]:
        proc = await asyncio.create_subprocess_exec(
            str(self.adb_path), "devices", "-l",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        phones = []
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            if not line or line.startswith("List of"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serial = parts[0]
                model = ""
                for p in parts[2:]:
                    if p.startswith("model:"):
                        model = p.split(":", 1)[1]
                        break
                phones.append(Phone(serial=serial, model=model, state="idle"))
        return phones

    async def shell(self, serial: str, *args: str, timeout: int = 30) -> str:
        proc = await asyncio.create_subprocess_exec(
            str(self.adb_path), "-s", serial, "shell", *args,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return stdout.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            proc.kill()
            return ""

    async def list_ig_clones(self, serial: str) -> list[str]:
        out = await self.shell(serial, "pm", "list", "packages", "com.instagram")
        return sorted(
            line.removeprefix("package:").strip()
            for line in out.splitlines()
            if line.startswith("package:")
        )

    # -- write operations (require proxy verification first) -------------------

    def mark_proxy_verified(self, serial: str, verified: bool = True) -> None:
        self._proxy_verified[serial] = verified

    def _assert_proxy_verified(self, serial: str):
        if not self._proxy_verified.get(serial, False):
            raise RuntimeError(
                f"Phantom Fleet SAFETY GATE: proxy routing not verified for {serial}. "
                f"Refusing to execute any write operation until ProxyOrchestratorAgent "
                f"confirms routing via IPRoyal + ipqualityscore.com reputation check."
            )

    async def launch_clone(self, serial: str, package: str) -> bool:
        self._assert_proxy_verified(serial)
        out = await self.shell(
            serial, "monkey", "-p", package, "-c",
            "android.intent.category.LAUNCHER", "1",
        )
        return "Events injected: 1" in out

    async def tap(self, serial: str, x: int, y: int) -> None:
        self._assert_proxy_verified(serial)
        await self.shell(serial, "input", "tap", str(x), str(y))

    async def type_text(self, serial: str, text: str) -> None:
        self._assert_proxy_verified(serial)
        await self.shell(serial, "input", "text", text.replace(" ", "%s"))

    async def force_stop(self, serial: str, package: str) -> None:
        self._assert_proxy_verified(serial)
        await self.shell(serial, "am", "force-stop", package)
