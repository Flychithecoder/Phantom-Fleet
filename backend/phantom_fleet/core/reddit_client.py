"""
RedditClient — OAuth API client for Reddit automation.

Uses the official Reddit OAuth API (oauth.reddit.com).
All requests carry the device headers extracted from the Reddit mobile app
on the physical phone, routed through the phone's SOCKS5 proxy.

Reddit-specific rules:
    - User-Agent MUST be "phantom_fleet:v1.0 (by /u/{username})"
      Reddit's API blocks generic or missing UAs aggressively.
    - The Authorization header carries "Bearer {access_token}".
    - access_token expires in 1h; refresh_token is used to obtain a new one
      (caller — WarmingAgent — handles token refresh on RedditSessionExpired).
    - x-reddit-device-id and x-reddit-loid are device/session identifiers
      extracted from the installed Reddit app and stored in PlatformHeaders.extra.

Detection notes:
    - Reddit's anti-automation is header-hash based and rate-limit based.
    - The loid (logged-out identifier) must match the device's installed app.
    - Do NOT share loid values across accounts — each phone has one loid per app install.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Any

import httpx

from .hybrid_runner import PlatformHeaders


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REDDIT_API_BASE    = "https://oauth.reddit.com"
REDDIT_TOKEN_URL   = "https://www.reddit.com/api/v1/access_token"

# Imported here so callers can reference it without touching reddit_oauth directly
from .reddit_oauth import REDDIT_OFFICIAL_CLIENT_ID, REDDIT_OFFICIAL_CLIENT_SECRET


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class RedditSession:
    """Live authenticated session for one Reddit account."""
    account_id:    str
    access_token:  str        # OAuth Bearer token (expires ~1h)
    refresh_token: str        # OAuth refresh token (long-lived)
    user_id:       str        # Reddit t2_ prefixed ID
    username:      str        # e.g. "phantom_user_42"
    headers:       PlatformHeaders
    is_valid:      bool = True
    # client_id used for token refresh.
    # Phone-backed accounts use REDDIT_OFFICIAL_CLIENT_ID ("ohXpoqrZYxa1Ag") so
    # the refresh request is indistinguishable from the real Reddit Android app.
    # Developer-app accounts leave this empty and fall back to REDDIT_CLIENT_ID env var.
    client_id:     str = ""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class RedditClient:
    """
    Thin async HTTP client for the Reddit OAuth API.

    One instance per account session.  Constructed by the account provisioner
    after OAuth flow, stored in the account's DB row.

    All requests route through socks5://127.0.0.1:8089 (Companion APK SOCKS
    → IPRoyal residential) so Reddit sees the phone's real residential IP.
    """

    def __init__(
        self,
        session: RedditSession,
        proxy_url: str = "socks5://127.0.0.1:8089",
    ):
        self.session   = session
        self.proxy_url = proxy_url
        self._client: Optional[httpx.AsyncClient] = None

    def _build_client(self) -> httpx.AsyncClient:
        h = self.session.headers

        # Phone-backed: use the exact UA string extracted from the installed Reddit app.
        # Developer-app: fall back to the script UA Reddit expects for personal apps.
        user_agent = (
            h.user_agent
            if h.user_agent
            else f"phantom_fleet:v1.0 (by /u/{self.session.username})"
        )

        return httpx.AsyncClient(
            proxy=self.proxy_url,
            headers={
                "User-Agent":         user_agent,
                "Authorization":      f"Bearer {self.session.access_token}",
                "Accept":             "application/json",
                "Accept-Language":    h.locale.replace("_", "-") or "en-US",
                "Accept-Encoding":    "gzip, deflate",
                "Connection":         "keep-alive",
                # Device identifiers from the installed Reddit Android app
                "x-reddit-device-id": h.extra.get("reddit_device_id", h.device_id),
                "x-reddit-loid":      h.extra.get("loid", ""),
                "x-reddit-session":   h.extra.get("reddit_session", ""),
            },
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        )

    async def __aenter__(self) -> "RedditClient":
        self._client = self._build_client()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Core request helpers
    # ------------------------------------------------------------------

    async def _get(self, endpoint: str, params: dict | None = None) -> dict:
        assert self._client, "Use 'async with RedditClient(...) as c:'"
        resp = await self._client.get(
            f"{REDDIT_API_BASE}/{endpoint}",
            params=params or {},
        )
        self._check_response(resp)
        return resp.json()

    async def _post(self, endpoint: str, data: dict | None = None) -> dict:
        assert self._client, "Use 'async with RedditClient(...) as c:'"
        resp = await self._client.post(
            f"{REDDIT_API_BASE}/{endpoint}",
            data=data or {},
        )
        self._check_response(resp)
        return resp.json()

    def _check_response(self, resp: httpx.Response) -> None:
        if resp.status_code == 401:
            self.session.is_valid = False
            raise RedditSessionExpired(
                f"Session expired for {self.session.username}"
            )
        if resp.status_code == 403:
            raise RedditForbidden(
                f"Action forbidden for {self.session.username}: {resp.text[:200]}"
            )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise RedditRateLimited(retry_after_sec=retry_after)
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def subscribe_subreddit(self, subreddit: str, unsub: bool = False) -> dict:
        """
        Subscribe (or unsubscribe) to a subreddit.
        action: "sub" or "unsub"
        """
        return await self._post("api/subscribe", {
            "action":     "unsub" if unsub else "sub",
            "sr_name":    subreddit,
            "skip_initial_defaults": "true",
        })

    async def upvote(self, post_id: str, direction: int = 1) -> dict:
        """
        Vote on a post or comment.
        direction: 1 = upvote, -1 = downvote, 0 = remove vote
        """
        return await self._post("api/vote", {
            "id":  post_id,   # e.g. "t3_abc123" or "t1_xyz789"
            "dir": str(direction),
        })

    async def comment(self, post_id: str, text: str) -> dict:
        """
        Post a comment on a submission or reply to a comment.
        post_id: "t3_abc123" for submission, "t1_xyz789" for comment
        """
        return await self._post("api/comment", {
            "thing_id": post_id,
            "text":     text,
            "api_type": "json",
        })

    async def submit_post(
        self,
        subreddit: str,
        title: str,
        text: str,
        kind: str = "self",
        url: str = "",
        nsfw: bool = False,
    ) -> dict:
        """
        Submit a new post to a subreddit.
        kind: "self" for text post, "link" for link post
        nsfw: mark the post as NSFW (required for NSFW subreddits)
        """
        payload: dict[str, Any] = {
            "sr":       subreddit,
            "title":    title,
            "kind":     kind,
            "api_type": "json",
            "resubmit": "true",
            "nsfw":     "true" if nsfw else "false",
            "spoiler":  "false",
        }
        if kind == "self":
            payload["text"] = text
        else:
            payload["url"] = url or text
        return await self._post("api/submit", payload)

    async def get_me_karma(self) -> dict:
        """
        Return karma breakdown for the authenticated account.
        Convenience wrapper around get_me() that extracts just karma fields.

        Returns:
            {
                "comment_karma": int,
                "link_karma":    int,
                "awardee_karma": int,
                "total_karma":   int,
            }
        """
        data = await self.get_me()
        return {
            "comment_karma": int(data.get("comment_karma", 0)),
            "link_karma":    int(data.get("link_karma", 0)),
            "awardee_karma": int(data.get("awardee_karma", 0)),
            "total_karma":   int(data.get("total_karma", 0)),
        }

    async def get_rising_posts(
        self,
        subreddit: str,
        limit: int = 25,
    ) -> dict:
        """
        Fetch rising posts from a subreddit.
        Convenience wrapper — equivalent to get_subreddit_posts(sort="rising").
        Used by karma farming agent for stage-2 comment targets.
        """
        return await self.get_subreddit_posts(subreddit, limit=limit, sort="rising")

    async def get_subreddit_posts(
        self,
        subreddit: str,
        limit: int = 25,
        after: str = "",
        sort: str = "hot",
    ) -> dict:
        """
        Fetch posts from a subreddit feed.
        sort: "hot", "new", "top", "rising"
        Returns standard Reddit listing object.
        """
        params: dict[str, Any] = {"limit": limit}
        if after:
            params["after"] = after
        return await self._get(f"r/{subreddit}/{sort}", params=params)

    async def send_pm(
        self,
        username: str,
        subject: str,
        text: str,
    ) -> dict:
        """Send a private message to a user."""
        return await self._post("api/compose", {
            "to":       username,
            "subject":  subject,
            "text":     text,
            "api_type": "json",
        })

    async def get_inbox(self, mark_read: bool = False) -> dict:
        """
        Fetch the DM/notification inbox.
        mark_read: if True, marks fetched messages as read.
        """
        data = await self._get("message/inbox", params={"mark": str(mark_read).lower()})
        return data

    async def get_me(self) -> dict:
        """Fetch the authenticated account's profile."""
        return await self._get("api/v1/me")

    async def refresh_access_token(
        self,
        proxy_url:     str | None = None,
        client_id:     str | None = None,
        client_secret: str | None = None,
    ) -> str:
        """
        Exchange the stored refresh_token for a new access_token.

        Updates self.session.access_token and rebuilds the underlying httpx
        client so subsequent calls use the new token.

        Args:
            proxy_url:     Override the proxy URL for the token request.
            client_id:     Override REDDIT_CLIENT_ID env var.
            client_secret: Override REDDIT_CLIENT_SECRET env var.

        Returns:
            The new access_token string.

        Raises:
            RuntimeError if the refresh_token is invalid or revoked.
        """
        from .reddit_oauth import refresh_access_token as _do_refresh

        # Phone-backed sessions carry the official app client_id on the session.
        # This makes the refresh request look identical to the Reddit app refreshing
        # its own token. Developer-app sessions fall back to the env var.
        effective_client_id     = client_id     if client_id     is not None else (self.session.client_id or None)
        effective_client_secret = client_secret if client_secret is not None else (
            REDDIT_OFFICIAL_CLIENT_SECRET if self.session.client_id == REDDIT_OFFICIAL_CLIENT_ID else None
        )

        tokens = await _do_refresh(
            refresh_token=self.session.refresh_token,
            username=self.session.username,
            proxy_url=proxy_url or self.proxy_url,
            client_id=effective_client_id,
            client_secret=effective_client_secret,
            user_agent=self.session.headers.user_agent,
        )
        self.session.access_token = tokens.access_token
        if tokens.refresh_token:
            self.session.refresh_token = tokens.refresh_token
        self.session.is_valid = True

        # Rebuild the live httpx client if we're inside an async with block
        if self._client:
            await self._client.aclose()
            self._client = self._build_client()

        return tokens.access_token

    async def ping_session(self) -> bool:
        """Lightweight session health check."""
        try:
            result = await self.get_me()
            return "name" in result
        except (RedditSessionExpired, httpx.HTTPError):
            return False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RedditSessionExpired(Exception):
    """Raised when Reddit returns 401 — token needs refresh."""


class RedditRateLimited(Exception):
    """Raised when Reddit returns 429 — back off and retry."""
    def __init__(self, retry_after_sec: int = 60):
        self.retry_after_sec = retry_after_sec
        super().__init__(f"RateLimited: retry after {retry_after_sec}s")


class RedditForbidden(Exception):
    """Raised when Reddit returns 403 — action not permitted for this account."""
