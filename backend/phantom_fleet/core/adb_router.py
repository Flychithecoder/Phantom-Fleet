"""
Route Phantom Fleet's adb calls through the Fleet Mirror hub instead of a local adb client.

Why: the farm's phones sit on adb servers owned by other tools (WhiteTiger on :5038, platform-tools on
:5037) and on other PCs. Running a local adb client of a different version restarts the shared server and
drops every phone on it; and a local client can't reach phones on other host PCs at all. The hub reaches
every phone through its agents without touching any adb server.

Turn it on with environment variables (all read at call time):

    FLEET_MIRROR_ADB=1                    route adb calls through the hub (off = old behaviour, local adb)
    FLEET_MIRROR_URL=https://192.168.1.16:22300     (or http://127.0.0.1:22301 on the hub PC)
    FLEET_MIRROR_API_KEY=fm_...           the hub's local API key
    FLEET_MIRROR_CERT_SHA256=EC:12:...    the hub certificate fingerprint (https only)
    FLEET_MIRROR_ADB_FALLBACK=1           commands the hub can't run (adb forward, adb connect) go to the
                                          local adb client; 0 = refuse them with an error (default 1)

What is routed:
    adb -s S shell ...           -> hub shell on that phone (same text adb would run)
    adb -s S install [-r] P      -> upload P to the hub, install on that phone
    adb -s S push LOCAL REMOTE   -> upload, push to /sdcard/Download, then mv to REMOTE on the phone
    adb devices [-l]             -> every online phone on every host PC, in `adb devices` format
Everything else (forward, connect, reverse, ...) is NotRouted -> fallback or error.
"""
from __future__ import annotations

import asyncio
import os
import posixpath
import shlex
from pathlib import Path
from typing import Optional

from ..fleet_mirror_client import FleetMirrorClient, FleetMirrorError


class NotRouted(Exception):
    """The hub can't run this adb command (use the local adb client, if allowed)."""


class AdbRouteError(RuntimeError):
    """The hub ran the command and it failed on the phone (or the hub refused it)."""


_client: Optional[FleetMirrorClient] = None
_client_loop = None


def enabled() -> bool:
    return os.environ.get("FLEET_MIRROR_ADB", "").strip().lower() in ("1", "true", "yes", "on")


def fallback_allowed() -> bool:
    return os.environ.get("FLEET_MIRROR_ADB_FALLBACK", "1").strip().lower() in ("1", "true", "yes", "on")


async def client() -> FleetMirrorClient:
    """One shared client per event loop (httpx clients are loop-bound)."""
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not loop:
        url = os.environ.get("FLEET_MIRROR_URL", "http://127.0.0.1:22301")
        key = os.environ.get("FLEET_MIRROR_API_KEY", "")
        if not key:
            raise AdbRouteError("FLEET_MIRROR_ADB=1 but FLEET_MIRROR_API_KEY is not set")
        _client = FleetMirrorClient(url, api_key=key, cert_sha256=os.environ.get("FLEET_MIRROR_CERT_SHA256", ""))
        _client_loop = loop
    return _client


def _split(args: list[str]) -> tuple[Optional[str], list[str]]:
    """['-s', 'SERIAL', 'shell', ...] -> ('SERIAL', ['shell', ...])"""
    serial = None
    a = list(args)
    while a and a[0] in ("-s", "-t", "-d", "-e", "-H", "-P"):
        if a[0] == "-s" and len(a) > 1:
            serial = a[1]
            a = a[2:]
        else:
            raise NotRouted(f"adb option {a[0]} is not supported through the hub")
    return serial, a


async def route_adb(args: list[str], timeout: float = 30) -> str:
    """Run one adb command (args as for the adb binary) through the hub. Returns stdout text."""
    serial, a = _split([str(x) for x in args])
    if not a:
        raise NotRouted("empty adb command")
    cmd = a[0]
    fm = await client()
    try:
        if cmd == "devices":
            phones = await fm.list_devices()
            lines = ["List of devices attached"]
            for p in phones:
                if p.get("state") == "device":
                    extra = f" model:{p.get('model', '')} host:{p.get('host', '')}" if "-l" in a else ""
                    lines.append(f"{p['serial']}\tdevice{extra}")
            return "\n".join(lines) + "\n"
        if serial is None:
            raise NotRouted(f"adb {cmd} without -s <serial>")
        if cmd == "shell":
            # adb joins the remaining arguments with spaces and hands them to the phone's shell
            command = " ".join(a[1:])
            res = await fm.shell(serial, command, timeout=timeout)
            ok, out = res.get(serial, (False, "phone not found on the hub"))
            if not ok:
                raise AdbRouteError(f"adb -s {serial} shell {command!r} failed via Fleet Mirror: {out}")
            return out
        if cmd == "install":
            apk = [x for x in a[1:] if not x.startswith("-")]
            if len(apk) != 1:
                raise NotRouted("adb install with several files")
            res = await fm.install_apk(serial, apk[0])
            ok, out = res.get(serial, (False, "phone not found on the hub"))
            if not ok:
                raise AdbRouteError(f"install of {apk[0]} on {serial} failed via Fleet Mirror: {out}")
            return out or "Success\n"
        if cmd == "push" and len(a) == 3:
            local, remote = a[1], a[2]
            name = Path(local).name
            fid = await fm.upload(local, name)
            rows = await fm.papi("uploadFile", serial, {"file": fid, "name": name, "isMedia": False, "timeout": max(timeout, 60)})
            row = (rows or [{}])[0]
            if not row.get("ok"):
                raise AdbRouteError(f"push of {local} to {serial} failed via Fleet Mirror: {row.get('out')}")
            staged = f"/sdcard/Download/{name}"
            target = remote if not remote.endswith("/") else posixpath.join(remote, name)
            if posixpath.normpath(target) != staged:
                mv = f"mkdir -p {shlex.quote(posixpath.dirname(target))} && mv -f {shlex.quote(staged)} {shlex.quote(target)}"
                res = await fm.shell(serial, mv, timeout=timeout)
                ok, out = res.get(serial, (False, ""))
                if not ok:
                    raise AdbRouteError(f"moving {staged} to {target} on {serial} failed: {out}")
            return f"{local}: 1 file pushed via Fleet Mirror\n"
    except FleetMirrorError as e:
        raise AdbRouteError(str(e)) from e
    raise NotRouted(f"adb {cmd} is not available through the hub")
