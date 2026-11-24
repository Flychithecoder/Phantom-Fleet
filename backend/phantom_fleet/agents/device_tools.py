"""
Device-control tools for Phantom Fleet agents, through the Fleet Mirror hub.

Every phone on every host PC is reachable through the hub, with the hub's **agents** key
(FLEET_MIRROR_AGENTS_API_KEY_FILE, falling back to the UI key). That key has its own "may control" list
on the hub: phones outside it are view-only for agents (list / screenshot / screen size / ui dump only
on phones it may control), and any other call is refused with FleetMirrorError code 10004.

Usage (same conventions as the other agents: keyword-only async tools, dotted names, allowlist):

    from phantom_fleet.agents.device_tools import build_device_tool_registry, DEVICE_TOOLS

    class MyAgent(Agent):
        config = AgentConfig(name="my_agent", allowed_tools=("device.list", "device.screenshot", "device.tap"))

    agent = MyAgent(tool_registry=build_device_tool_registry())
    await agent.tool("device.tap", serial="R5CRC08L4QM", x=540, y=1200, unit="px")

For LLM tool use (Anthropic/OpenAI style), `llm_tool_specs()` returns name / description / JSON schema for
every tool (dots become underscores in the name), and `call_llm_tool(name, args)` runs one.

Timing: tap / swipe / long_press use exactly the points and delays the caller supplies (draw them from
core.distributions); the hub adds no randomness.
"""
from __future__ import annotations

import base64
import os
from typing import Any, Awaitable, Callable

from ..fleet_mirror_client import FleetMirrorClient, FleetMirrorError, api_key_from_env

_client: FleetMirrorClient | None = None


def _agents_client() -> FleetMirrorClient:
    global _client
    if _client is None:
        key = api_key_from_env("FLEET_MIRROR_AGENTS") or api_key_from_env("FLEET_MIRROR")
        if not key:
            raise FleetMirrorError(401, "no Fleet Mirror key: set FLEET_MIRROR_AGENTS_API_KEY_FILE", "device_tools")
        _client = FleetMirrorClient(os.environ.get("FLEET_MIRROR_URL", "http://127.0.0.1:22301"), api_key=key,
                                    cert_sha256=os.environ.get("FLEET_MIRROR_CERT_SHA256", ""))
    return _client


def build_device_tool_registry(client_factory: Callable[[], FleetMirrorClient] = _agents_client) -> dict[str, Callable[..., Awaitable[Any]]]:
    def c() -> FleetMirrorClient:
        return client_factory()

    async def list_devices() -> list[dict]:
        """Every phone: serial, host PC, number, name, model, state, and whether these agents may control it."""
        rows = await c().list_devices()
        return [{k: p.get(k) for k in ("serial", "host", "number", "name", "model", "release", "state", "ip", "tags", "api_control")}
                for p in rows]

    async def screen_size(*, serial: str) -> dict:
        w, h = (await c().screen_size(serial))[serial]
        return {"width": w, "height": h}

    async def screenshot(*, serial: str) -> dict:
        png = await c().screenshot(serial)
        return {"mime": "image/png", "base64": base64.b64encode(png).decode(), "bytes": len(png)}

    async def ui_dump(*, serial: str) -> dict:
        return {"xml": await c().ui_dump(serial)}

    async def tap(*, serial: str, x: float, y: float, unit: str = "percent") -> dict:
        return {"sent": await c().tap(serial, x, y, unit)}

    async def swipe(*, serial: str, points: list[list[float]], durations_ms: list[float], hold_ms: float = 0,
                    unit: str = "percent") -> dict:
        return {"sent": await c().swipe(serial, points, durations_ms, hold_ms, unit)}

    async def long_press(*, serial: str, x: float, y: float, duration_ms: float, unit: str = "percent") -> dict:
        return {"sent": await c().long_press(serial, x, y, duration_ms, unit)}

    async def key(*, serial: str, key: str | int) -> dict:
        return {"sent": await c().key(serial, key)}

    async def text(*, serial: str, text: str) -> dict:
        r = await c().text(serial, text)
        return {"ok": all(x.get("ok") for x in r)}

    async def clipboard_set(*, serial: str, text: str) -> dict:
        r = await c().set_clipboard(serial, text)
        return {"ok": all(x.get("ok") for x in r)}

    async def clipboard_get(*, serial: str) -> dict:
        return {"text": (await c().get_clipboard(serial)).get(serial, "")}

    async def shell(*, serial: str, command: str, timeout: float = 120) -> dict:
        ok, out = (await c().shell(serial, command, timeout=timeout)).get(serial, (False, "not found"))
        return {"ok": ok, "output": out}

    async def apps(*, serial: str, system: bool = False) -> dict:
        rows = await c().papi("apkList", serial, {"system": system})
        return {"packages": (rows[0].get("data") if rows else []) or []}

    async def app_install(*, serial: str, apk_path: str) -> dict:
        ok, out = (await c().install_apk(serial, apk_path)).get(serial, (False, ""))
        return {"ok": ok, "output": out}

    async def app_start(*, serial: str, package: str) -> dict:
        r = await c().start_app(serial, package)
        return {"ok": all(x.get("ok") for x in r)}

    async def app_stop(*, serial: str, package: str) -> dict:
        r = await c().stop_app(serial, package)
        return {"ok": all(x.get("ok") for x in r)}

    async def file_push(*, serial: str, local_path: str, media: bool = False) -> dict:
        ok, out = (await c().push_file(serial, local_path, media)).get(serial, (False, ""))
        return {"ok": ok, "output": out}

    async def file_pull(*, serial: str, path: str) -> dict:
        data = await c().pull_file(serial, path)
        return {"base64": base64.b64encode(data).decode(), "bytes": len(data)}

    async def task_run(*, serials: list[str], action_id: str | None = None, script_id: str | None = None,
                       loop_count: int = 1, loop_interval: list[float] | None = None, device_interval: float = 0) -> dict:
        return await c().run_task(serials, action_id=action_id, script_id=script_id, loop_count=loop_count,
                                  loop_interval=tuple(loop_interval or (0, 0)), device_interval=device_interval)

    async def task_status(*, task_id: str) -> dict:
        return await c().task_status(task_id)

    async def task_stop(*, task_id: str) -> dict:
        return await c().task_op(task_id, "stop")

    return {
        "device.list": list_devices, "device.screen_size": screen_size, "device.screenshot": screenshot,
        "device.ui_dump": ui_dump, "device.tap": tap, "device.swipe": swipe, "device.long_press": long_press,
        "device.key": key, "device.text": text, "device.clipboard_set": clipboard_set,
        "device.clipboard_get": clipboard_get, "device.shell": shell, "device.apps": apps,
        "device.app_install": app_install, "device.app_start": app_start, "device.app_stop": app_stop,
        "device.file_push": file_push, "device.file_pull": file_pull, "device.task_run": task_run,
        "device.task_status": task_status, "device.task_stop": task_stop,
    }


DEVICE_TOOLS = tuple(build_device_tool_registry(lambda: None).keys())   # names, for AgentConfig.allowed_tools

_S = {"type": "string"}
_N = {"type": "number"}
_SER = {"serial": {"type": "string", "description": "Phone serial, e.g. R5CRC08L4QM (see device.list)"}}
_UNIT = {"unit": {"type": "string", "enum": ["percent", "px"], "description": "Coordinates as % of the screen (default) or pixels"}}
SPECS: dict[str, tuple[str, dict, list[str]]] = {
    "device.list": ("List every phone on every host PC (serial, host, model, state, api_control = may these agents control it).", {}, []),
    "device.screen_size": ("Screen width and height in pixels.", _SER, ["serial"]),
    "device.screenshot": ("PNG screenshot of the phone (base64).", _SER, ["serial"]),
    "device.ui_dump": ("UI hierarchy XML of the current screen (texts, resource ids, bounds) to find what to tap.", _SER, ["serial"]),
    "device.tap": ("Tap at a point.", {**_SER, "x": _N, "y": _N, **_UNIT}, ["serial", "x", "y"]),
    "device.swipe": ("Swipe through points with the given per-segment delays (ms). Supply human-like timing yourself.",
                     {**_SER, "points": {"type": "array", "items": {"type": "array", "items": _N, "minItems": 2, "maxItems": 2}},
                      "durations_ms": {"type": "array", "items": _N}, "hold_ms": _N, **_UNIT}, ["serial", "points", "durations_ms"]),
    "device.long_press": ("Press and hold at a point.", {**_SER, "x": _N, "y": _N, "duration_ms": _N, **_UNIT}, ["serial", "x", "y", "duration_ms"]),
    "device.key": ("Press a key: home, back, recents, menu, power, volup, voldown, or an Android keycode.",
                   {**_SER, "key": {"type": ["string", "integer"]}}, ["serial", "key"]),
    "device.text": ("Type text into the focused field.", {**_SER, "text": _S}, ["serial", "text"]),
    "device.clipboard_set": ("Set the phone's clipboard.", {**_SER, "text": _S}, ["serial", "text"]),
    "device.clipboard_get": ("Read the phone's clipboard.", _SER, ["serial"]),
    "device.shell": ("Run an adb shell command on the phone.", {**_SER, "command": _S, "timeout": _N}, ["serial", "command"]),
    "device.apps": ("Installed app packages.", {**_SER, "system": {"type": "boolean"}}, ["serial"]),
    "device.app_install": ("Install an APK from a path on the Phantom Fleet server.", {**_SER, "apk_path": _S}, ["serial", "apk_path"]),
    "device.app_start": ("Start an app by package name.", {**_SER, "package": _S}, ["serial", "package"]),
    "device.app_stop": ("Force-stop an app by package name.", {**_SER, "package": _S}, ["serial", "package"]),
    "device.file_push": ("Copy a server file to the phone's Download folder (media=true: DCIM/Camera).",
                         {**_SER, "local_path": _S, "media": {"type": "boolean"}}, ["serial", "local_path"]),
    "device.file_pull": ("Fetch a file from the phone (base64).", {**_SER, "path": _S}, ["serial", "path"]),
    "device.task_run": ("Run a recorded action or saved script (Fleet Mirror automation) on phones.",
                        {"serials": {"type": "array", "items": _S}, "action_id": _S, "script_id": _S, "loop_count": {"type": "integer"},
                         "loop_interval": {"type": "array", "items": _N}, "device_interval": _N}, ["serials"]),
    "device.task_status": ("Status of a task.", {"task_id": _S}, ["task_id"]),
    "device.task_stop": ("Stop a running task.", {"task_id": _S}, ["task_id"]),
}


def llm_tool_specs() -> list[dict]:
    """Tool definitions for LLM tool use ("device_tap" etc.; input_schema = JSON schema)."""
    return [{"name": n.replace(".", "_"), "description": d, "input_schema": {"type": "object", "properties": p, "required": r}}
            for n, (d, p, r) in SPECS.items()]


async def call_llm_tool(name: str, args: dict, registry: dict | None = None) -> Any:
    """Run a tool called by an LLM ("device_tap" or "device.tap"). Errors come back as {"error": ...}."""
    reg = registry or build_device_tool_registry()
    fn = reg.get(name if name in reg else name.replace("_", ".", 1))
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        return await fn(**(args or {}))
    except FleetMirrorError as e:
        return {"error": str(e), "code": e.code}
