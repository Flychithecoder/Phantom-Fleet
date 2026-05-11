"""
TelegramClient — MTProto-compatible client for Telegram automation.

Architecture note:
    Telegram has two API surfaces:
      1. Bot HTTP API (api.telegram.org) — simple REST, requires a bot token.
         Used here as the wirable layer since MTProto requires telethon/pyrogram
         C extensions that aren't available in all environments.
      2. MTProto user API — requires extracted auth_key + dc_id from the installed
         Telegram app's tdata/ session database.  The TelegramSession dataclass
         carries those values so the full MTProto layer can be swapped in later
         without changing the caller interface.

Current implementation:
    All actions call the Bot HTTP API at https://api.telegram.org/bot{token}/…
    The token field in TelegramSession carries the bot token OR the user session
    token (HTTP-API flavour).  When the full MTProto layer is added, only
    _build_client() and the dc_id routing change — all action methods stay identical.

Proxy:
    All requests route through socks5://127.0.0.1:8089 (Companion APK local
    SOCKS → IPRoyal residential), matching the phone's real residential IP.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional, Any

import httpx

from .hybrid_runner import PlatformHeaders


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TELEGRAM_BOT_BASE = "https://api.telegram.org"

# MTProto DC address map — used for future direct MTProto connection
TG_DC_MAP: dict[int, str] = {
    1: "149.154.175.53",
    2: "149.154.167.51",
    3: "149.154.175.100",
    4: "149.154.167.91",
    5: "91.108.56.130",
}


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class TelegramSession:
    """
    Live authenticated session for one Telegram account.

    auth_key: 256-byte MTProto auth key extracted from tdata/ (hex-encoded).
              Used by the full MTProto layer; ignored by the Bot HTTP layer.
    dc_id:    Telegram data-centre index (1-5) the account is homed to.
    token:    Bot token (e.g. "123456:ABC-DEF…") OR user session token for
              the HTTP-API compatibility layer.
    """
    account_id: str
    auth_key:   str          # hex-encoded 256-byte MTProto auth key
    dc_id:      int          # 1-5
    user_id:    str          # Telegram numeric user ID
    username:   str          # e.g. "@johndoe" (without @)
    phone:      str          # E.164 format, e.g. "+12025551234"
    token:      str          # bot token / HTTP-API session token
    headers:    PlatformHeaders
    is_valid:   bool = True


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class TelegramClient:
    """
    Thin async HTTP client for Telegram.

    Uses the Bot HTTP API at api.telegram.org.  One instance per account session.
    Route replacement for full MTProto: swap _build_client() to use pyrogram/telethon
    once the MTProto layer is added; all action methods remain unchanged.

    All requests go through the phone's SOCKS5 proxy at socks5://127.0.0.1:8089.
    """

    def __init__(
        self,
        session: TelegramSession,
        proxy_url: str = "socks5://127.0.0.1:8089",
    ):
        self.session   = session
        self.proxy_url = proxy_url
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def _base_url(self) -> str:
        return f"{TELEGRAM_BOT_BASE}/bot{self.session.token}"

    def _build_client(self) -> httpx.AsyncClient:
        h = self.session.headers
        return httpx.AsyncClient(
            proxy=self.proxy_url,
            headers={
                "User-Agent":      h.user_agent,
                "Accept":          "application/json",
                "Accept-Language": h.locale.replace("_", "-"),
                "Accept-Encoding": "gzip, deflate",
                "Connection":      "keep-alive",
            },
            timeout=httpx.Timeout(20.0),
            follow_redirects=True,
        )

    async def __aenter__(self) -> "TelegramClient":
        self._client = self._build_client()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Core request helpers
    # ------------------------------------------------------------------

    async def _post(self, method: str, payload: dict) -> dict:
        assert self._client, "Use 'async with TelegramClient(...) as c:'"
        resp = await self._client.post(
            f"{self._base_url}/{method}",
            json=payload,
        )
        if resp.status_code == 401:
            self.session.is_valid = False
            raise TelegramSessionExpired(
                f"Session expired for {self.session.username}"
            )
        body = resp.json()
        if not body.get("ok", True):
            error_code = body.get("error_code", 0)
            description = body.get("description", "")
            # Flood wait: {"ok": false, "error_code": 429, "parameters": {"retry_after": N}}
            if error_code == 429:
                retry_after = body.get("parameters", {}).get("retry_after", 60)
                raise TelegramFloodWait(retry_after_sec=retry_after)
            raise TelegramAPIError(f"[{error_code}] {description}")
        resp.raise_for_status()
        return body.get("result", body)

    async def _get(self, method: str, params: dict | None = None) -> dict:
        assert self._client, "Use 'async with TelegramClient(...) as c:'"
        resp = await self._client.get(
            f"{self._base_url}/{method}",
            params=params or {},
        )
        if resp.status_code == 401:
            self.session.is_valid = False
            raise TelegramSessionExpired(
                f"Session expired for {self.session.username}"
            )
        body = resp.json()
        if not body.get("ok", True):
            error_code = body.get("error_code", 0)
            description = body.get("description", "")
            if error_code == 429:
                retry_after = body.get("parameters", {}).get("retry_after", 60)
                raise TelegramFloodWait(retry_after_sec=retry_after)
            raise TelegramAPIError(f"[{error_code}] {description}")
        resp.raise_for_status()
        return body.get("result", body)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def send_dm(self, user_id: str, text: str) -> dict:
        """Send a direct message to a user or chat by ID."""
        return await self._post("sendMessage", {
            "chat_id": user_id,
            "text":    text,
            "parse_mode": "HTML",
        })

    async def join_group(self, invite_link: str) -> dict:
        """
        Join a group via invite link.
        Bot API: joinChat accepts invite links of the form https://t.me/+XXXX
        """
        return await self._post("joinChat", {"chat_id": invite_link})

    async def get_group_members(self, group_id: str, limit: int = 50) -> list[dict]:
        """
        Fetch members of a group/supergroup.
        Bot API: getChatAdministrators (full member list requires getUsersInChat
        which is not available in the standard Bot API).
        Returns admin list as the best available approximation.
        For full member scraping the MTProto layer is required.
        """
        result = await self._get("getChatAdministrators", {"chat_id": group_id})
        # result is a list of ChatMember objects
        members: list[dict] = result if isinstance(result, list) else []
        return members[:limit]

    async def send_channel_post(self, channel_id: str, text: str) -> dict:
        """Post a message to a channel."""
        return await self._post("sendMessage", {
            "chat_id":  channel_id,
            "text":     text,
            "parse_mode": "HTML",
        })

    async def forward_message(
        self,
        from_chat: str,
        to_chat: str,
        message_id: int,
    ) -> dict:
        """Forward a message from one chat to another."""
        return await self._post("forwardMessage", {
            "chat_id":      to_chat,
            "from_chat_id": from_chat,
            "message_id":   message_id,
        })

    async def get_chat(self, chat_id: str) -> dict:
        """Fetch info about a chat/group/channel."""
        return await self._get("getChat", {"chat_id": chat_id})

    async def get_updates(self, offset: int = 0, limit: int = 20) -> list[dict]:
        """
        Poll for new updates (messages, callbacks, etc.).
        Long-poll timeout is set to 0 for non-blocking check.
        """
        result = await self._get("getUpdates", {
            "offset":  offset,
            "limit":   limit,
            "timeout": 0,
        })
        return result if isinstance(result, list) else []

    async def ping_session(self) -> bool:
        """Lightweight session health check via getMe."""
        try:
            result = await self._get("getMe")
            return isinstance(result, dict) and "id" in result
        except (TelegramSessionExpired, httpx.HTTPError):
            return False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TelegramSessionExpired(Exception):
    """Raised when Telegram returns 401 — session token is invalid."""


class TelegramFloodWait(Exception):
    """Raised when Telegram returns 429 — flood wait triggered."""
    def __init__(self, retry_after_sec: int = 60):
        self.retry_after_sec = retry_after_sec
        super().__init__(f"FloodWait: retry after {retry_after_sec}s")


class TelegramAPIError(Exception):
    """Generic Telegram API error (non-auth, non-flood)."""
