"""
DiscordClient — REST API client for Discord automation.

Uses the Discord REST API v10 (discord.com/api/v10).
This client operates with a USER token (not a Bot token) — the raw account
token extracted from the Discord app's leveldb via DPAPI + AES-GCM.

Authorization header format: "{token}"  (NO "Bot " prefix — user tokens)

ToS note:
    Discord's ToS prohibits self-bots (automation with user tokens).
    The agent manager gates this platform explicitly; only enable for accounts
    provisioned specifically for automation.

Detection notes:
    - Discord's anti-automation fingerprints the X-Super-Properties header,
      which is a base64-encoded JSON blob containing the client's build number,
      OS version, browser version, and device info.
    - The super_properties value in PlatformHeaders.extra must be extracted
      verbatim from the installed Discord app (not generated synthetically).
    - The X-Discord-Locale header should match the account's locale.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Optional

import httpx

from .hybrid_runner import PlatformHeaders


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DISCORD_API_BASE = "https://discord.com/api/v10"


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class DiscordSession:
    """Live authenticated session for one Discord account."""
    account_id:     str
    token:          str        # raw user auth token (no "Bot " prefix)
    user_id:        str        # Discord snowflake user ID
    username:       str        # e.g. "phantom_user"
    discriminator:  str        # e.g. "0" (legacy: "1234")
    headers:        PlatformHeaders
    is_valid:       bool = True


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class DiscordClient:
    """
    Thin async HTTP client for the Discord REST API v10.

    One instance per account session.

    All requests route through socks5://127.0.0.1:8089 (Companion APK SOCKS
    → IPRoyal residential).

    X-Super-Properties must be extracted from the real Discord Android app
    installed on the physical phone — synthetic generation creates a fingerprint.
    """

    def __init__(
        self,
        session: DiscordSession,
        proxy_url: str = "socks5://127.0.0.1:8089",
    ):
        self.session   = session
        self.proxy_url = proxy_url
        self._client: Optional[httpx.AsyncClient] = None

    def _build_client(self) -> httpx.AsyncClient:
        h = self.session.headers
        # X-Super-Properties: base64(JSON) from the installed Discord Android app
        super_props = h.extra.get("super_properties", "")
        return httpx.AsyncClient(
            proxy=self.proxy_url,
            headers={
                "User-Agent":           h.user_agent,
                "Authorization":        self.session.token,
                "Accept":               "*/*",
                "Accept-Language":      h.locale.replace("_", "-"),
                "Accept-Encoding":      "gzip, deflate",
                "Connection":           "keep-alive",
                "Content-Type":         "application/json",
                "X-Super-Properties":   super_props,
                "X-Discord-Locale":     h.locale.replace("_", "-"),
                "X-Discord-Timezone":   h.timezone,
            },
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        )

    async def __aenter__(self) -> "DiscordClient":
        self._client = self._build_client()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Core request helpers
    # ------------------------------------------------------------------

    async def _get(self, endpoint: str, params: dict | None = None) -> dict | list:
        assert self._client, "Use 'async with DiscordClient(...) as c:'"
        resp = await self._client.get(
            f"{DISCORD_API_BASE}/{endpoint}",
            params=params or {},
        )
        self._check_response(resp)
        return resp.json()

    async def _post(self, endpoint: str, payload: dict | None = None) -> dict | list:
        assert self._client, "Use 'async with DiscordClient(...) as c:'"
        resp = await self._client.post(
            f"{DISCORD_API_BASE}/{endpoint}",
            json=payload or {},
        )
        self._check_response(resp)
        # 204 No Content: return empty dict
        if resp.status_code == 204:
            return {}
        return resp.json()

    async def _put(self, endpoint: str, payload: dict | None = None) -> dict:
        assert self._client, "Use 'async with DiscordClient(...) as c:'"
        resp = await self._client.put(
            f"{DISCORD_API_BASE}/{endpoint}",
            json=payload or {},
        )
        self._check_response(resp)
        if resp.status_code == 204:
            return {}
        return resp.json()

    def _check_response(self, resp: httpx.Response) -> None:
        if resp.status_code == 401:
            self.session.is_valid = False
            raise DiscordSessionExpired(
                f"Session expired for {self.session.username}"
            )
        if resp.status_code == 429:
            retry_after_ms = 1000
            try:
                retry_after_ms = int(
                    resp.json().get("retry_after", 1.0) * 1000
                )
            except Exception:
                pass
            raise DiscordRateLimited(retry_after_sec=retry_after_ms // 1000 or 1)
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def send_message(self, channel_id: str, content: str) -> dict:
        """Send a message to a channel."""
        return await self._post(f"channels/{channel_id}/messages", {
            "content": content,
        })

    async def join_server(self, invite_code: str) -> dict:
        """Join a server via invite code (accepts both full URL and bare code)."""
        code = invite_code.split("/")[-1]   # strip https://discord.gg/ prefix
        return await self._post(f"invites/{code}", {})

    async def get_guild_members(
        self,
        guild_id: str,
        limit: int = 100,
        after: str = "0",
    ) -> list[dict]:
        """
        List members of a guild.
        Requires GUILD_MEMBERS intent on bot accounts; user tokens can access
        this on servers where the account is a member.
        """
        result = await self._get(
            f"guilds/{guild_id}/members",
            params={"limit": min(limit, 1000), "after": after},
        )
        return result if isinstance(result, list) else []

    async def react_to_message(
        self,
        channel_id: str,
        message_id: str,
        emoji: str,
    ) -> dict:
        """
        Add a reaction to a message.
        emoji: URL-encoded emoji, e.g. "%F0%9F%91%8D" for 👍, or "name:id" for custom.
        """
        return await self._put(
            f"channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me"
        )

    async def get_dm_channel(self, user_id: str) -> dict:
        """
        Open (or fetch) a DM channel with a user.
        Returns a Channel object with .id for use in send_message.
        """
        return await self._post("users/@me/channels", {
            "recipient_id": user_id,
        })

    async def send_dm(self, user_id: str, content: str) -> dict:
        """
        Send a DM to a user.
        Opens the DM channel first if needed, then sends.
        """
        channel = await self.get_dm_channel(user_id)
        channel_id = channel["id"]
        return await self.send_message(channel_id, content)

    async def get_me(self) -> dict:
        """Fetch the authenticated account's user object."""
        return await self._get("users/@me")

    async def get_guilds(self) -> list[dict]:
        """Fetch the list of guilds the account is in."""
        result = await self._get("users/@me/guilds")
        return result if isinstance(result, list) else []

    async def ping_session(self) -> bool:
        """Lightweight session health check."""
        try:
            result = await self.get_me()
            return isinstance(result, dict) and "id" in result
        except (DiscordSessionExpired, httpx.HTTPError):
            return False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DiscordSessionExpired(Exception):
    """Raised when Discord returns 401 — token is invalid or revoked."""


class DiscordRateLimited(Exception):
    """Raised when Discord returns 429 — rate limited."""
    def __init__(self, retry_after_sec: int = 1):
        self.retry_after_sec = retry_after_sec
        super().__init__(f"RateLimited: retry after {retry_after_sec}s")
