"""
APKClient — async HTTP client for the Phantom Fleet Companion APK.

Each phone runs the APK's Ktor server on port 8090. The PC reaches it via:
    adb -s <serial> forward tcp:<host_port> tcp:8090

Port assignment: deterministic per serial — hash(serial) % 900 + 8100
so phone at 192.168.1.42:5555 always gets the same host port.

Usage:
    client = APKClient(serial="192.168.1.42:5555")
    await client.setup_forward()
    result = await client.ig_follow("someuser", "com.instagram.android")
    await client.teardown_forward()

Or use as async context manager:
    async with APKClient(serial) as client:
        await client.ig_like(media_id, clone_pkg)
"""
from __future__ import annotations

import asyncio
import subprocess
from typing import Optional

import httpx


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class APKCallFailed(RuntimeError):
    """Raised when the Companion APK returns a non-2xx response."""

    def __init__(self, path: str, status: int, body: str) -> None:
        self.path   = path
        self.status = status
        self.body   = body
        super().__init__(f"APK {path} returned HTTP {status}: {body!r}")


# ---------------------------------------------------------------------------
# APKClient
# ---------------------------------------------------------------------------

class APKClient:
    """
    Async HTTP client for one Companion APK instance on one physical phone.

    Port assignment is deterministic per serial so multiple APKClient instances
    for the same phone always resolve to the same forwarded port, and so the
    correct `adb forward` command is always idempotent.

    Args:
        serial:   ADB serial of the phone (e.g. "192.168.1.42:5555").
        adb_path: Path to the adb binary. Default: "adb" (assumes on PATH).
    """

    def __init__(self, serial: str, adb_path: str = "adb") -> None:
        self.serial    = serial
        self.adb_path  = adb_path
        # Deterministic host port: hash(serial) % 900 + 8100  →  [8100, 8999]
        self.host_port = hash(serial) % 900 + 8100
        self._base_url = f"http://127.0.0.1:{self.host_port}"

    # ------------------------------------------------------------------
    # adb forward lifecycle
    # ------------------------------------------------------------------

    async def setup_forward(self) -> None:
        """
        Set up `adb -s <serial> forward tcp:<host_port> tcp:8090`.
        Safe to call multiple times — adb forward is idempotent.
        """
        await _run_adb_cmd(
            self.adb_path,
            "-s", self.serial,
            "forward",
            f"tcp:{self.host_port}",
            "tcp:8090",
        )

    async def teardown_forward(self) -> None:
        """
        Remove the port forward: `adb -s <serial> forward --remove tcp:<host_port>`.
        Silently ignores errors (forward may already be gone).
        """
        try:
            await _run_adb_cmd(
                self.adb_path,
                "-s", self.serial,
                "forward",
                "--remove",
                f"tcp:{self.host_port}",
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "APKClient":
        await self.setup_forward()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.teardown_forward()

    # ------------------------------------------------------------------
    # Device / health
    # ------------------------------------------------------------------

    async def health(self) -> dict:
        """GET /health → { status, serial }"""
        return await self._get("/health")

    async def device_info(self) -> dict:
        """GET /device/info → { model, android_version, android_id, carrier, mcc_mnc, locale, timezone }"""
        return await self._get("/device/info")

    async def gaid(self) -> str:
        """GET /device/gaid → GAID string"""
        resp = await self._get("/device/gaid")
        return resp.get("gaid", "")

    # ------------------------------------------------------------------
    # Instagram engagement
    # ------------------------------------------------------------------

    async def ig_follow(self, username: str, clone_pkg: str) -> dict:
        """
        POST /instagram/engage/follow
        Navigates to the user's profile and taps Follow.
        Returns { success: bool, error: str|null }.
        """
        return await self._post(
            "/instagram/engage/follow",
            {"username": username, "clonePackage": clone_pkg},
        )

    async def ig_unfollow(self, username: str, clone_pkg: str) -> dict:
        """
        POST /instagram/engage/unfollow
        Navigates to profile, taps Following → confirms Unfollow.
        """
        return await self._post(
            "/instagram/engage/unfollow",
            {"username": username, "clonePackage": clone_pkg},
        )

    async def ig_like(self, media_id: str, clone_pkg: str) -> dict:
        """
        POST /instagram/engage/like
        Opens post via deep link and taps the Like heart.
        """
        return await self._post(
            "/instagram/engage/like",
            {"mediaId": media_id, "clonePackage": clone_pkg},
        )

    async def ig_comment(self, media_id: str, text: str, clone_pkg: str) -> dict:
        """
        POST /instagram/engage/comment
        Opens post, taps comment icon, types text with LogNormal+typo, posts.
        """
        return await self._post(
            "/instagram/engage/comment",
            {"mediaId": media_id, "commentText": text, "clonePackage": clone_pkg},
        )

    async def ig_view_stories(
        self, username: str, story_count: int, clone_pkg: str
    ) -> dict:
        """
        POST /instagram/engage/view_stories
        Opens the user's story ring and taps through story_count segments.
        """
        return await self._post(
            "/instagram/engage/view_stories",
            {"username": username, "storyCount": story_count, "clonePackage": clone_pkg},
        )

    async def ig_scroll_reels(self, watch_count: int, clone_pkg: str) -> dict:
        """
        POST /instagram/engage/scroll_reels
        Opens Reels tab and scrolls through watch_count reels with LogNormal dwell.
        """
        return await self._post(
            "/instagram/engage/scroll_reels",
            {"watchCount": watch_count, "clonePackage": clone_pkg},
        )

    async def ig_send_dm(self, username: str, message: str, clone_pkg: str) -> dict:
        """
        POST /instagram/engage/send_dm
        Opens DM inbox, searches for user, opens thread, types and sends message.
        """
        return await self._post(
            "/instagram/engage/send_dm",
            {"username": username, "message": message, "clonePackage": clone_pkg},
        )

    async def ig_check_session(self, clone_pkg: str) -> dict:
        """
        GET /instagram/engage/check_session?clonePackage=<pkg>
        Returns { loggedIn: bool, needsReauth: bool }.
        """
        return await self._get(
            "/instagram/engage/check_session",
            params={"clonePackage": clone_pkg},
        )

    # ------------------------------------------------------------------
    # Instagram posting (grid / story / reel)
    # ------------------------------------------------------------------

    async def ig_post(
        self,
        media_path: str,
        caption: str,
        account_id: str,
        clone_pkg: str,
        post_type: str = "GRID",
    ) -> dict:
        """
        POST /instagram/post
        Posts from gallery with postType=GRID (default), STORY, or REEL.
        """
        return await self._post(
            "/instagram/post",
            {
                "mediaPath":    media_path,
                "caption":      caption,
                "accountId":    account_id,
                "clonePackage": clone_pkg,
                "postType":     post_type.upper(),
            },
        )

    async def ig_story(
        self,
        media_path: str,
        caption: str,
        account_id: str,
        clone_pkg: str,
    ) -> dict:
        """
        POST /instagram/story
        Convenience alias: posts a story from gallery (postType=STORY).
        """
        return await self._post(
            "/instagram/story",
            {
                "mediaPath":    media_path,
                "caption":      caption,
                "accountId":    account_id,
                "clonePackage": clone_pkg,
                "postType":     "STORY",
            },
        )

    async def ig_reel(
        self,
        media_path: str,
        caption: str,
        account_id: str,
        clone_pkg: str,
    ) -> dict:
        """
        POST /instagram/reel
        Convenience alias: posts a reel from gallery (postType=REEL).
        """
        return await self._post(
            "/instagram/reel",
            {
                "mediaPath":    media_path,
                "caption":      caption,
                "accountId":    account_id,
                "clonePackage": clone_pkg,
                "postType":     "REEL",
            },
        )

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------

    async def media_scan(self, path: str) -> dict:
        """
        POST /media/scan
        Triggers Android's MediaScanner on path so gallery sees the new file.
        Call after adb push, before any posting flow.
        """
        return await self._post("/media/scan", {"path": path})

    async def media_transform(
        self,
        input_path: str,
        output_path: str,
        account_id: str,
        post_index: int,
    ) -> dict:
        """
        POST /media/transform
        Applies per-account visual transforms (brightness, crop, hue, noise)
        to prevent content-cluster fingerprinting at fleet scale.
        """
        return await self._post(
            "/media/transform",
            {
                "inputPath":  input_path,
                "outputPath": output_path,
                "accountId":  account_id,
                "postIndex":  post_index,
            },
        )

    # ------------------------------------------------------------------
    # SOCKS5 proxy forwarding (per-phone residential IP for API workers)
    # ------------------------------------------------------------------

    @property
    def socks5_host_port(self) -> int:
        """
        Deterministic host-side port for this phone's SOCKS5 proxy tunnel.
        Range [7100, 7999] — distinct from APK HTTP range [8100, 8999].

        ADB forward maps tcp:<host_port> → tcp:8089 (Companion APK LocalProxyService).
        Once the forward is active, `socks5://127.0.0.1:<host_port>` routes API
        calls through the phone's residential IP.
        """
        return hash(self.serial) % 900 + 7100

    @property
    def socks5_proxy_url(self) -> str:
        """SOCKS5 proxy URL for this phone's residential IP tunnel."""
        return f"socks5://127.0.0.1:{self.socks5_host_port}"

    async def setup_proxy_forward(self) -> None:
        """
        Forward phone's SOCKS5 proxy (port 8089) to the host machine.

        After this call, any httpx/aiohttp client configured with
        `proxies={"all://": socks5_proxy_url}` routes through the phone's
        residential IP — the same IP Reddit sees from the native app.

        Safe to call multiple times — adb forward is idempotent.
        """
        await _run_adb_cmd(
            self.adb_path,
            "-s", self.serial,
            "forward",
            f"tcp:{self.socks5_host_port}",
            "tcp:8089",
        )

    async def teardown_proxy_forward(self) -> None:
        """Remove the SOCKS5 port forward. Silently ignores errors."""
        try:
            await _run_adb_cmd(
                self.adb_path,
                "-s", self.serial,
                "forward",
                "--remove",
                f"tcp:{self.socks5_host_port}",
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Reddit header extraction
    # ------------------------------------------------------------------

    async def reddit_extract_headers(
        self,
        package_name: str = "com.reddit.frontpage",
    ) -> dict:
        """
        Extract live Reddit session from the installed Reddit app on the phone.

        Calls POST /reddit/extract-headers on the Companion APK server.
        The APK extracts everything from the Reddit app's data directory via
        root shell so that every subsequent API call is indistinguishable from
        the real Reddit Android app — same token, same client_id, same UA.

        Args:
            package_name: Reddit's package name (default: com.reddit.frontpage).

        Returns:
            {
                "access_token":  "<live Bearer token from installed app>",
                "refresh_token": "<long-lived refresh token>",
                "token_expiry":  1713000000,      # Unix epoch seconds
                "device_id":     "<32-char lowercase hex>",
                "loid":          "<base64url ~22-24 chars>",
                "client_id":     "ohXpoqrZYxa1Ag",  # official Reddit Android app ID
                "user_agent":    "Reddit/2024.19.0 (Android 13; Samsung SM-G998B)",
                "app_version":   "2024.19.0",
                "android_id":    "<16-char hex>",
            }

        Raises:
            APKCallFailed: if the APK server returns a non-2xx response.

        ── Companion APK endpoint spec ──────────────────────────────────────────
        POST /reddit/extract-headers
        Body: { "packageName": "com.reddit.frontpage" }

        Step 1 — Read SharedPreferences via root shell.
        Reddit splits its data across multiple prefs files. Read them all:

            val result = Runtime.getRuntime().exec(
                arrayOf("su", "-c",
                    "find /data/data/$packageName/shared_prefs/ -name '*.xml' " +
                    "-exec cat {} \\;")
            ).inputStream.bufferedReader().readText()

        Look for these keys across all XML content:
            access_token / accessToken / access-token
            refresh_token / refreshToken / refresh-token
            device_id / deviceId / device-id
            loid / logged_out_id / loggedOutId
            token_expiry / tokenExpiry / expires_at / expiresAt

        On newer Reddit app versions (v2023+) tokens may be in EncryptedSharedPreferences.
        In that case, run as the app's UID so the Keystore key is accessible:

            val uid = Runtime.getRuntime()
                .exec(arrayOf("su", "-c", "stat -c %u /data/data/$packageName"))
                .inputStream.bufferedReader().readText().trim()
            // Then re-exec the cat command prefixed with: su -c "su $uid -c ..."

        Step 2 — Parse XML.
        SharedPreferences XML format:
            <map>
              <string name="access_token">eyJhbGci...</string>
              <string name="refresh_token">eyJhbGci...</string>
              <long   name="token_expiry">1713000000000</long>
              <string name="device_id">a1b2c3d4e5f6...</string>
              <string name="loid">AbCdEfGhIjKlMn</string>
            </map>
        token_expiry is stored as milliseconds — divide by 1000 for Unix seconds.

        Step 3 — App version and User-Agent.
            val versionName = packageManager
                .getPackageInfo(packageName, 0).versionName   // e.g. "2024.19.0"
            val model       = Build.MODEL                      // e.g. "Samsung SM-G998B"
            val sdkInt      = Build.VERSION.SDK_INT            // e.g. 33
            val ua          = "Reddit/$versionName (Android $sdkInt; $model)"

        Step 4 — android_id.
            val androidId = Settings.Secure.getString(
                context.contentResolver, Settings.Secure.ANDROID_ID
            )

        Step 5 — client_id.
        Return the official Reddit Android app client_id. This is the hardcoded
        value embedded in the Reddit APK — it is public knowledge documented in
        Reddit's own API community and every open-source Reddit client:
            "client_id": "ohXpoqrZYxa1Ag"
        The client_secret for an installed app is always an empty string "".

        Step 6 — Return JSON:
            {
              "access_token":  "<token>",
              "refresh_token": "<token>",
              "token_expiry":  <unix_seconds>,
              "device_id":     "<hex>",
              "loid":          "<base64url>",
              "client_id":     "ohXpoqrZYxa1Ag",
              "user_agent":    "<ua string>",
              "app_version":   "<version>",
              "android_id":    "<hex>"
            }

        Return HTTP 500 with { "error": "extraction_failed", "detail": "..." }
        if no token is found — do NOT return a partial result.
        ────────────────────────────────────────────────────────────────────────
        """
        return await self._post(
            "/reddit/extract-headers",
            {"packageName": package_name},
        )

    # ------------------------------------------------------------------
    # Proxy
    # ------------------------------------------------------------------

    async def proxy_status(self, port: int = 8089) -> bool:
        """
        GET /proxy/status?port=<port>
        Returns True if the Companion APK's local SOCKS5 proxy is active.
        """
        try:
            resp = await self._get("/proxy/status", params={"port": str(port)})
            return bool(resp.get("active", False))
        except APKCallFailed:
            return False

    # ------------------------------------------------------------------
    # Private HTTP helpers
    # ------------------------------------------------------------------

    async def _post(self, path: str, body: dict) -> dict:
        """
        POST to path with JSON body. Returns parsed JSON dict.
        Raises APKCallFailed on non-2xx status.
        No retries — callers handle that.
        """
        url = self._base_url + path
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=body)
        if not (200 <= response.status_code < 300):
            raise APKCallFailed(path, response.status_code, response.text)
        return response.json()

    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """
        GET path with optional query params. Returns parsed JSON dict.
        Raises APKCallFailed on non-2xx status.
        """
        url = self._base_url + path
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
        if not (200 <= response.status_code < 300):
            raise APKCallFailed(path, response.status_code, response.text)
        return response.json()


# ---------------------------------------------------------------------------
# ADB helper
# ---------------------------------------------------------------------------

async def _run_adb_cmd(adb_path: str, *args: str) -> str:
    """Run an adb command asynchronously, return stdout."""
    cmd = [adb_path, *args]
    result = await asyncio.to_thread(_run_adb_sync, cmd)
    return result


def _run_adb_sync(cmd: list[str]) -> str:
    """Blocking adb runner — called via asyncio.to_thread."""
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if proc.returncode != 0 and proc.stderr:
        stderr = proc.stderr.strip()
        if stderr and "daemon started" not in stderr.lower():
            raise RuntimeError(f"adb failed: {stderr}")
    return proc.stdout or ""
