"""
PhoneController — WiFi ADB bridge between Phantom Fleet and physical phones.

Every action that touches a phone goes through this controller. It is the
single enforcement point for the proxy safety gate: if a phone has no verified
proxy, NOTHING executes on it. No exceptions.

Architecture:
    - WiFi ADB (no USB hubs required): phones connect on port 5555
    - One PhoneController instance per phone serial
    - PhoneFleet manages the full set of connected phones
    - ADB commands are issued via subprocess (adb binary must be on PATH)
    - All calls are async — ADB I/O is blocking but wrapped in asyncio.to_thread

Phone states:
    OFFLINE      — not reachable via ADB
    ONLINE       — reachable, no proxy verified
    PROXY_READY  — reachable + proxy confirmed active (ONLY state that allows actions)
    BUSY         — currently executing an automation task
    ERROR        — last command failed, needs investigation

Proxy safety gate (CRITICAL):
    Before ANY action executes, verify_proxy() must return True.
    If it returns False, raise ProxyNotVerified — never silently skip.
    This prevents actions firing on an unprotected residential IP that would
    expose the real farm IP to Instagram's backend.

WiFi ADB setup (one-time per phone):
    1. On phone: Settings → Developer options → Wireless debugging → ON
    2. Note the IP:port shown (e.g. 192.168.1.42:41234)
    3. Run: adb pair 192.168.1.42:41234 <pairing-code>
    4. Run: adb connect 192.168.1.42:5555
    After pairing once, phones reconnect automatically on the same LAN.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .apk_client import APKClient, APKCallFailed


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProxyNotVerified(RuntimeError):
    """Raised when an action is attempted without a verified proxy."""

class DeviceOffline(RuntimeError):
    """Raised when an ADB command targets an offline device."""

class ADBCommandFailed(RuntimeError):
    """Raised when an ADB command returns a non-zero exit code."""


# ---------------------------------------------------------------------------
# Phone state
# ---------------------------------------------------------------------------

class PhoneState(str, Enum):
    OFFLINE     = "offline"
    ONLINE      = "online"
    PROXY_READY = "proxy_ready"
    BUSY        = "busy"
    ERROR       = "error"


# ---------------------------------------------------------------------------
# Clone inventory entry
# ---------------------------------------------------------------------------

@dataclass
class CloneSlot:
    """One installed app clone on a physical phone."""
    serial:       str         # phone ADB serial
    package_name: str         # e.g. com.instagram.android_clone_01
    clone_index:  int         # 0-based index of this clone
    platform:     str         # "instagram", "tiktok", etc.
    account_id:   Optional[str] = None   # assigned account, None if empty
    active:       bool = False


# ---------------------------------------------------------------------------
# Phone controller
# ---------------------------------------------------------------------------

@dataclass
class PhoneController:
    """
    Controls one physical Android phone via WiFi ADB.

    Usage:
        phone = PhoneController(serial="192.168.1.42:5555")
        if await phone.is_online():
            if await phone.verify_proxy():
                await phone.launch_clone("com.instagram.android_clone_01")
    """
    serial:     str                         # ADB serial (IP:port or USB serial)
    state:      PhoneState = PhoneState.OFFLINE
    proxy_host: str = "127.0.0.1"
    proxy_port: int = 8089                  # Companion APK local SOCKS5 port
    clones:     list[CloneSlot] = field(default_factory=list)
    _last_error: Optional[str] = None
    # Device identifiers — populated by get_device_info() + get_advertising_id()
    # and stored here so start-warming can build PlatformHeaders without extra DB calls.
    metadata:   dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    async def is_online(self) -> bool:
        """Check if the device is reachable via ADB."""
        try:
            result = await self._adb("shell", "echo", "pong", timeout=5)
            online = result.strip() == "pong"
            self.state = PhoneState.ONLINE if online else PhoneState.OFFLINE
            return online
        except (ADBCommandFailed, asyncio.TimeoutError):
            self.state = PhoneState.OFFLINE
            return False

    async def connect(self) -> bool:
        """
        Issue `adb connect <serial>` for WiFi ADB.
        Returns True if connected. Safe to call repeatedly.
        """
        try:
            result = await _run_adb("connect", self.serial, timeout=10)
            connected = "connected" in result.lower()
            if connected:
                self.state = PhoneState.ONLINE
            return connected
        except ADBCommandFailed:
            self.state = PhoneState.OFFLINE
            return False

    # ------------------------------------------------------------------
    # Proxy safety gate — MUST pass before any action
    # ------------------------------------------------------------------

    async def verify_proxy(self) -> bool:
        """
        Verify the Companion APK's local SOCKS5 proxy is active on the phone.

        Checks that port 8089 is listening on 127.0.0.1 (the APK's
        LocalProxyService). If not active, the phone must NOT execute
        any platform actions.
        """
        if self.state == PhoneState.OFFLINE:
            return False
        try:
            # Check if port 8089 is bound (LocalProxyService listening)
            result = await self._adb(
                "shell", "ss", "-tlnp", "sport", "=", ":8089",
                timeout=6,
            )
            active = "8089" in result
            if active:
                self.state = PhoneState.PROXY_READY
            else:
                self.state = PhoneState.ONLINE  # online but proxy not ready
            return active
        except ADBCommandFailed:
            return False

    def require_proxy(self) -> None:
        """
        Hard gate — call before dispatching any action.
        Raises ProxyNotVerified if state is not PROXY_READY.
        """
        if self.state != PhoneState.PROXY_READY:
            raise ProxyNotVerified(
                f"Phone {self.serial} proxy not verified "
                f"(state={self.state.value}). "
                "Run verify_proxy() before executing any platform actions."
            )

    # ------------------------------------------------------------------
    # Clone management
    # ------------------------------------------------------------------

    async def list_installed_packages(self) -> list[str]:
        """Return all installed package names on the device."""
        self.require_proxy()
        result = await self._adb("shell", "pm", "list", "packages", timeout=15)
        packages = []
        for line in result.splitlines():
            if line.startswith("package:"):
                packages.append(line.replace("package:", "").strip())
        return packages

    async def discover_clones(self, platform: str) -> list[CloneSlot]:
        """
        Scan installed packages for clones of a platform's app.
        Clone packages follow the naming convention:
            com.instagram.android        → original
            com.instagram.android.clone1 → clone 1
            com.instagram.android.clone2 → clone 2
            (varies by cloner: NomixCloner uses _clone_N suffix)
        """
        self.require_proxy()
        packages = await self.list_installed_packages()
        base_pkg  = _platform_base_package(platform)
        found: list[CloneSlot] = []

        for pkg in packages:
            if base_pkg in pkg:
                idx = _extract_clone_index(pkg)
                found.append(CloneSlot(
                    serial=self.serial,
                    package_name=pkg,
                    clone_index=idx,
                    platform=platform,
                ))

        self.clones = [c for c in self.clones if c.platform != platform] + found
        return found

    async def launch_clone(self, package_name: str) -> bool:
        """Bring a clone to foreground via monkey launcher."""
        self.require_proxy()
        try:
            await self._adb(
                "shell", "monkey",
                "-p", package_name,
                "-c", "android.intent.category.LAUNCHER",
                "1",
                timeout=10,
            )
            return True
        except ADBCommandFailed:
            return False

    async def force_stop_clone(self, package_name: str) -> None:
        """Force-stop a clone (releases foreground slot)."""
        try:
            await self._adb("shell", "am", "force-stop", package_name, timeout=8)
        except ADBCommandFailed:
            pass

    # ------------------------------------------------------------------
    # Device info
    # ------------------------------------------------------------------

    async def get_device_info(self) -> dict:
        """
        Read hardware identifiers needed for DeviceProfile.
        Returns a dict ready to construct a DeviceProfile.
        """
        self.require_proxy()

        async def prop(key: str) -> str:
            try:
                return (await self._adb("shell", "getprop", key, timeout=5)).strip()
            except ADBCommandFailed:
                return ""

        model       = await prop("ro.product.model")
        android_ver = await prop("ro.build.version.release")
        android_id_raw = await self._adb(
            "shell", "settings", "get", "secure", "android_id", timeout=5
        )
        android_id  = android_id_raw.strip()
        carrier     = await prop("gsm.operator.alpha")
        mcc_mnc     = await prop("gsm.operator.numeric")
        locale_raw  = await self._adb(
            "shell", "getprop", "persist.sys.locale", timeout=5
        )
        locale      = locale_raw.strip() or "en-US"

        info = {
            "phone_serial":    self.serial,
            "model":           model,
            "android_version": android_ver,
            "android_id":      android_id,
            "carrier_name":    carrier,
            "carrier_mcc_mnc": mcc_mnc,
            "locale":          locale.replace("-", "_"),
        }
        # Cache on self so start-warming can build PlatformHeaders without re-reading
        self.metadata.update({k: v for k, v in info.items() if v})
        return info

    async def get_advertising_id(self) -> str:
        """
        Read GAID (Google Advertising ID) from the device.
        Requires the Companion APK's GAIDProvider to be running.
        Calls the APK's local HTTP endpoint.
        """
        self.require_proxy()
        try:
            result = await self._adb(
                "shell", "curl", "-s",
                "http://127.0.0.1:8090/device/gaid",
                timeout=8,
            )
            gaid = result.strip()
            if gaid:
                self.metadata["advertising_id"] = gaid
            return gaid
        except ADBCommandFailed:
            return ""

    # ------------------------------------------------------------------
    # APK client integration
    # ------------------------------------------------------------------

    @property
    def apk_client(self) -> APKClient:
        """
        Returns an APKClient for this phone.

        Creates a new instance on each access (stateless, cheap).
        The APKClient computes the forwarded host_port deterministically
        from self.serial so it is always consistent.

        Use as an async context manager to manage adb forward lifetime:
            async with self.apk_client as client:
                await client.ig_follow(...)
        """
        return APKClient(serial=self.serial)

    async def execute_ig_action(self, action: str, **kwargs) -> dict:
        """
        Route an Instagram engagement or posting action to the Companion APK.

        Enforces the proxy safety gate before opening the APK connection.
        Routes the ``action`` string to the correct ``APKClient`` method.

        Supported actions:
            follow, unfollow, like, comment, view_stories, scroll_reels,
            send_dm, check_session, post, story, reel

        Required kwargs depend on the action (see APKClient docstrings).
        ``clone_pkg`` is always required.

        Raises:
            ProxyNotVerified:  proxy gate not passed.
            APKCallFailed:     APK returned non-2xx.
            KeyError:          required kwarg missing.
            ValueError:        unknown action string.
        """
        self.require_proxy()

        async with self.apk_client as client:
            if action == "follow":
                return await client.ig_follow(
                    username=kwargs["username"],
                    clone_pkg=kwargs["clone_pkg"],
                )
            elif action == "unfollow":
                return await client.ig_unfollow(
                    username=kwargs["username"],
                    clone_pkg=kwargs["clone_pkg"],
                )
            elif action == "like":
                return await client.ig_like(
                    media_id=kwargs["media_id"],
                    clone_pkg=kwargs["clone_pkg"],
                )
            elif action == "comment":
                return await client.ig_comment(
                    media_id=kwargs["media_id"],
                    text=kwargs["text"],
                    clone_pkg=kwargs["clone_pkg"],
                )
            elif action == "view_stories":
                return await client.ig_view_stories(
                    username=kwargs["username"],
                    story_count=kwargs.get("story_count", 5),
                    clone_pkg=kwargs["clone_pkg"],
                )
            elif action == "scroll_reels":
                return await client.ig_scroll_reels(
                    watch_count=kwargs.get("watch_count", 5),
                    clone_pkg=kwargs["clone_pkg"],
                )
            elif action == "send_dm":
                return await client.ig_send_dm(
                    username=kwargs["username"],
                    message=kwargs["message"],
                    clone_pkg=kwargs["clone_pkg"],
                )
            elif action == "check_session":
                return await client.ig_check_session(
                    clone_pkg=kwargs["clone_pkg"],
                )
            elif action == "post":
                return await client.ig_post(
                    media_path=kwargs["media_path"],
                    caption=kwargs.get("caption", ""),
                    account_id=kwargs["account_id"],
                    clone_pkg=kwargs["clone_pkg"],
                    post_type=kwargs.get("post_type", "GRID"),
                )
            elif action == "story":
                return await client.ig_story(
                    media_path=kwargs["media_path"],
                    caption=kwargs.get("caption", ""),
                    account_id=kwargs["account_id"],
                    clone_pkg=kwargs["clone_pkg"],
                )
            elif action == "reel":
                return await client.ig_reel(
                    media_path=kwargs["media_path"],
                    caption=kwargs.get("caption", ""),
                    account_id=kwargs["account_id"],
                    clone_pkg=kwargs["clone_pkg"],
                )
            else:
                raise ValueError(
                    f"Unknown IG action: {action!r}. "
                    "Valid: follow, unfollow, like, comment, view_stories, "
                    "scroll_reels, send_dm, check_session, post, story, reel"
                )

    async def verify_proxy_via_apk(self) -> bool:
        """
        Check proxy health via the Companion APK's HTTP endpoint instead of
        raw ADB ss command. Falls back to the ADB-based verify_proxy() if the
        APK is not reachable (e.g. APK not yet running).

        Sets self.state to PROXY_READY if the proxy is confirmed active.

        Returns:
            True if the local SOCKS5 proxy on port 8089 is active.
        """
        if self.state == PhoneState.OFFLINE:
            return False

        # Try APK first — faster and doesn't shell into the device
        try:
            client = self.apk_client
            await client.setup_forward()
            try:
                active = await client.proxy_status(port=self.proxy_port)
            finally:
                await client.teardown_forward()

            if active:
                self.state = PhoneState.PROXY_READY
            else:
                self.state = PhoneState.ONLINE
            return active

        except (APKCallFailed, OSError, Exception):
            # APK not reachable yet — fall back to ADB ss command
            return await self.verify_proxy()

    # ------------------------------------------------------------------
    # File transfer
    # ------------------------------------------------------------------

    async def adb_push(self, local_path: str, remote_path: str) -> None:
        """
        Push a file from the host machine to the device via ADB.

        Used by IGForegroundPostAgent to stage media in the phone's DCIM
        folder before the Companion APK's AccessibilityService posts it.

        Args:
            local_path:  Absolute host-side path to the file, e.g.
                         /tmp/phantom/abc123.jpg
            remote_path: Absolute device-side destination, e.g.
                         /sdcard/DCIM/PhantomFleet/abc123.jpg

        Raises:
            ADBCommandFailed: if adb push returns non-zero exit code.
        """
        await _run_adb("-s", self.serial, "push", local_path, remote_path, timeout=60)

    async def adb_shell(self, command: str) -> str:
        """
        Run an arbitrary shell command on the device and return its stdout.

        Used for ad-hoc operations such as deleting staging files after
        a post completes (success or failure).

        Args:
            command: Shell command string, e.g. "rm /sdcard/DCIM/PhantomFleet/abc.jpg"

        Returns:
            stdout of the command (may be empty).

        Raises:
            ADBCommandFailed: if the command returns non-zero exit code.
        """
        return await _run_adb("-s", self.serial, "shell", command, timeout=30)

    # ------------------------------------------------------------------
    # Internal ADB runner
    # ------------------------------------------------------------------

    async def _adb(self, *args: str, timeout: float = 30) -> str:
        """Run an ADB command targeting this specific device."""
        return await _run_adb("-s", self.serial, *args, timeout=timeout)


# ---------------------------------------------------------------------------
# Fleet manager
# ---------------------------------------------------------------------------

@dataclass
class PhoneFleet:
    """
    Manages all physical phones in the farm.

    At startup, call scan() to discover all connected ADB devices.
    The fleet is keyed by ADB serial (IP:port for WiFi ADB).
    """
    _phones: dict[str, PhoneController] = field(default_factory=dict)

    def register(self, serial: str, **kwargs) -> PhoneController:
        """Register a phone by its ADB serial."""
        if serial not in self._phones:
            self._phones[serial] = PhoneController(serial=serial, **kwargs)
        return self._phones[serial]

    async def scan(self) -> list[PhoneController]:
        """
        Run `adb devices` and register all currently connected devices.
        Returns list of PhoneController instances (all states).
        """
        try:
            raw = await _run_adb("devices", timeout=10)
        except ADBCommandFailed:
            return []

        controllers = []
        for line in raw.splitlines()[1:]:   # skip "List of devices attached"
            if not line.strip() or "offline" in line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] in ("device", "unauthorized"):
                serial = parts[0]
                ctrl   = self.register(serial)
                ctrl.state = PhoneState.ONLINE
                controllers.append(ctrl)
        return controllers

    async def verify_all_proxies(self) -> dict[str, bool]:
        """Verify proxy on all registered phones concurrently."""
        results = await asyncio.gather(
            *[phone.verify_proxy() for phone in self._phones.values()],
            return_exceptions=True,
        )
        return {
            serial: (res if isinstance(res, bool) else False)
            for serial, res in zip(self._phones.keys(), results)
        }

    def ready_phones(self) -> list[PhoneController]:
        """Return phones in PROXY_READY state only."""
        return [p for p in self._phones.values() if p.state == PhoneState.PROXY_READY]

    def all_phones(self) -> list[PhoneController]:
        return list(self._phones.values())

    def get(self, serial: str) -> Optional[PhoneController]:
        return self._phones.get(serial)

    def status_summary(self) -> dict:
        counts = {s.value: 0 for s in PhoneState}
        for phone in self._phones.values():
            counts[phone.state.value] += 1
        return {
            "total":       len(self._phones),
            "proxy_ready": counts[PhoneState.PROXY_READY.value],
            "online":      counts[PhoneState.ONLINE.value],
            "offline":     counts[PhoneState.OFFLINE.value],
            "busy":        counts[PhoneState.BUSY.value],
            "error":       counts[PhoneState.ERROR.value],
        }


# ---------------------------------------------------------------------------
# ADB subprocess helpers
# ---------------------------------------------------------------------------

async def _run_adb(*args: str, timeout: float = 30) -> str:
    """
    Run an adb command asynchronously.
    Raises ADBCommandFailed on non-zero exit or stderr output.
    Raises asyncio.TimeoutError if the command hangs.
    """
    cmd = ["adb", *args]
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_run_adb_sync, cmd),
            timeout=timeout,
        )
        return result
    except asyncio.TimeoutError:
        raise


def _run_adb_sync(cmd: list[str]) -> str:
    """Blocking ADB call — runs in a thread pool via asyncio.to_thread."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0 and proc.stderr:
            # Some ADB commands write to stderr even on success — only fail
            # if returncode is non-zero AND stderr has a real error message
            stderr = proc.stderr.strip()
            if stderr and "daemon started" not in stderr.lower():
                raise ADBCommandFailed(
                    f"adb {' '.join(cmd[1:])} failed: {stderr}"
                )
        return proc.stdout or ""
    except FileNotFoundError:
        raise ADBCommandFailed(
            "adb binary not found. Install Android Platform Tools and ensure "
            "adb is on your system PATH."
        )


# ---------------------------------------------------------------------------
# Package name helpers
# ---------------------------------------------------------------------------

_PLATFORM_PACKAGES: dict[str, str] = {
    "instagram": "com.instagram.android",
    "threads":   "com.instagram.barcelona",
    "tiktok":    "com.zhiliaoapp.musically",
    "telegram":  "org.telegram.messenger",
    "discord":   "com.discord",
    "reddit":    "com.reddit.frontpage",
    "x":         "com.twitter.android",
    "bluesky":   "xyz.blueskyweb.app",
    "tinder":    "com.tinder",
    "bumble":    "com.bumble.app",
    "hinge":     "co.hinge.app",
    "grindr":    "com.grindr.android",
}


def _platform_base_package(platform: str) -> str:
    return _PLATFORM_PACKAGES.get(platform, f"com.{platform}")


def _extract_clone_index(package_name: str) -> int:
    """Extract clone index from a package name. Returns 0 for the base app."""
    match = re.search(r"[._]clone[._]?(\d+)$|[._](\d+)$", package_name)
    if match:
        return int(match.group(1) or match.group(2))
    return 0
