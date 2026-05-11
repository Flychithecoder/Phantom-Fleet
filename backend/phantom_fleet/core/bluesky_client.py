"""
BlueSkyClient — AT Protocol client for Bluesky automation.

Uses the AT Protocol XRPC API at bsky.social.

AT Protocol notes:
    - Every account is identified by a DID (Decentralised Identifier).
    - Authentication: com.atproto.server.createSession → returns accessJwt +
      refreshJwt.  accessJwt expires in ~2h; refreshJwt is used to renew.
    - All write operations (post, follow, like, repost) use com.atproto.repo.*
      and require the actor's DID + a repo record key (rkey).
    - Read operations (timeline, search) use app.bsky.* lexicon.

Detection notes:
    Bluesky's API is fully open with no proprietary signing — it is the most
    bot-tolerant platform in the fleet.  Standard rate limits apply but there
    is no mobile-app header requirement.  The device UA is sent anyway for
    consistency with the phone fingerprint anchor.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Any

import httpx

from .hybrid_runner import PlatformHeaders


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BSKY_BASE = "https://bsky.social/xrpc"


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class BlueSkySession:
    """Live authenticated session for one Bluesky account."""
    account_id:  str
    did:         str        # e.g. "did:plc:abc123xyz"
    access_jwt:  str        # short-lived (expires ~2h)
    refresh_jwt: str        # long-lived refresh token
    handle:      str        # e.g. "phantom.bsky.social"
    headers:     PlatformHeaders
    is_valid:    bool = True


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class BlueSkyClient:
    """
    Thin async HTTP client for the AT Protocol / Bluesky XRPC API.

    All requests route through socks5://127.0.0.1:8089.
    """

    def __init__(
        self,
        session: BlueSkySession,
        proxy_url: str = "socks5://127.0.0.1:8089",
    ):
        self.session   = session
        self.proxy_url = proxy_url
        self._client: Optional[httpx.AsyncClient] = None

    def _build_client(self) -> httpx.AsyncClient:
        h = self.session.headers
        return httpx.AsyncClient(
            proxy=self.proxy_url,
            headers={
                "User-Agent":      h.user_agent,
                "Authorization":   f"Bearer {self.session.access_jwt}",
                "Accept":          "application/json",
                "Accept-Language": h.locale.replace("_", "-"),
                "Accept-Encoding": "gzip, deflate",
                "Connection":      "keep-alive",
                "Content-Type":    "application/json",
            },
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        )

    async def __aenter__(self) -> "BlueSkyClient":
        self._client = self._build_client()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Core request helpers
    # ------------------------------------------------------------------

    async def _get(
        self,
        lexicon: str,
        params: dict | None = None,
        base_url: str = BSKY_BASE,
    ) -> dict:
        assert self._client, "Use 'async with BlueSkyClient(...) as c:'"
        resp = await self._client.get(
            f"{base_url}/{lexicon}",
            params=params or {},
        )
        self._check_response(resp)
        return resp.json()

    async def _post(
        self,
        lexicon: str,
        payload: dict | None = None,
        base_url: str = BSKY_BASE,
    ) -> dict:
        assert self._client, "Use 'async with BlueSkyClient(...) as c:'"
        resp = await self._client.post(
            f"{base_url}/{lexicon}",
            json=payload or {},
        )
        self._check_response(resp)
        return resp.json()

    def _check_response(self, resp: httpx.Response) -> None:
        if resp.status_code in (401, 400):
            # AT Proto 400 with "ExpiredToken" or "InvalidToken" = session expired
            try:
                body = resp.json()
                error = body.get("error", "")
                if error in ("ExpiredToken", "InvalidToken") or resp.status_code == 401:
                    self.session.is_valid = False
                    raise BlueSkySessionExpired(
                        f"Session expired for {self.session.handle}: {error}"
                    )
            except BlueSkySessionExpired:
                raise
            except Exception:
                pass
            if resp.status_code == 401:
                self.session.is_valid = False
                raise BlueSkySessionExpired(
                    f"Session expired for {self.session.handle}"
                )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise BlueSkyRateLimited(retry_after_sec=retry_after)
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # AT Protocol helpers
    # ------------------------------------------------------------------

    def _now_iso(self) -> str:
        """Return current UTC time as ISO 8601 string with Z suffix."""
        return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create_post(
        self,
        text: str,
        reply_to: dict | None = None,
    ) -> dict:
        """
        Create a new post (skeet).
        reply_to: {"root": {"uri": ..., "cid": ...}, "parent": {"uri": ..., "cid": ...}}
        Returns: {"uri": "at://...", "cid": "..."}
        """
        record: dict[str, Any] = {
            "$type":     "app.bsky.feed.post",
            "text":      text,
            "createdAt": self._now_iso(),
        }
        if reply_to:
            record["reply"] = reply_to
        return await self._post("com.atproto.repo.createRecord", {
            "repo":       self.session.did,
            "collection": "app.bsky.feed.post",
            "record":     record,
        })

    async def follow_user(self, did: str) -> dict:
        """
        Follow a user by their DID.
        Returns the follow record: {"uri": ..., "cid": ...}
        """
        return await self._post("com.atproto.repo.createRecord", {
            "repo":       self.session.did,
            "collection": "app.bsky.graph.follow",
            "record": {
                "$type":     "app.bsky.graph.follow",
                "subject":   did,
                "createdAt": self._now_iso(),
            },
        })

    async def unfollow_user(self, follow_rkey: str) -> dict:
        """
        Unfollow a user by deleting the follow record.
        follow_rkey: the rkey portion of the follow record URI
                     (e.g. from "at://did:plc:xxx/app.bsky.graph.follow/rkey")
        """
        return await self._post("com.atproto.repo.deleteRecord", {
            "repo":       self.session.did,
            "collection": "app.bsky.graph.follow",
            "rkey":       follow_rkey,
        })

    async def like_post(self, uri: str, cid: str) -> dict:
        """
        Like a post by its AT URI + CID.
        Returns: {"uri": ..., "cid": ...}
        """
        return await self._post("com.atproto.repo.createRecord", {
            "repo":       self.session.did,
            "collection": "app.bsky.feed.like",
            "record": {
                "$type":     "app.bsky.feed.like",
                "subject":   {"uri": uri, "cid": cid},
                "createdAt": self._now_iso(),
            },
        })

    async def repost(self, uri: str, cid: str) -> dict:
        """
        Repost a post by its AT URI + CID.
        Returns: {"uri": ..., "cid": ...}
        """
        return await self._post("com.atproto.repo.createRecord", {
            "repo":       self.session.did,
            "collection": "app.bsky.feed.repost",
            "record": {
                "$type":     "app.bsky.feed.repost",
                "subject":   {"uri": uri, "cid": cid},
                "createdAt": self._now_iso(),
            },
        })

    async def get_timeline(
        self,
        limit: int = 20,
        cursor: str = "",
    ) -> dict:
        """
        Fetch the home timeline.
        Returns: {"feed": [...], "cursor": "..."}
        """
        params: dict[str, Any] = {"limit": limit, "algorithm": "reverse-chronological"}
        if cursor:
            params["cursor"] = cursor
        return await self._get("app.bsky.feed.getTimeline", params=params)

    async def search_posts(self, query: str, limit: int = 25) -> dict:
        """
        Search for posts.
        Returns: {"posts": [...], "hitsTotal": N}
        """
        return await self._get("app.bsky.feed.searchPosts", params={
            "q":     query,
            "limit": limit,
        })

    async def get_profile(self, actor: str) -> dict:
        """Fetch a user's profile by DID or handle."""
        return await self._get("app.bsky.actor.getProfile", params={"actor": actor})

    async def get_follows(
        self,
        actor: str,
        limit: int = 50,
        cursor: str = "",
    ) -> dict:
        """
        Fetch the list of accounts that `actor` follows.
        actor: DID or handle
        Returns: {"follows": [{did, handle, displayName, ...}], "cursor": "..."}

        Each follow record includes the AT URI of the follow record itself
        under the key "viewer.following" which encodes the rkey needed for
        unfollow_user(). Format: at://did:plc:xxx/app.bsky.graph.follow/rkey
        """
        params: dict[str, Any] = {"actor": actor, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._get("app.bsky.graph.getFollows", params=params)

    async def get_followers(
        self,
        actor: str,
        limit: int = 50,
        cursor: str = "",
    ) -> dict:
        """
        Fetch the list of accounts that follow `actor`.
        actor: DID or handle (use session.did for self)
        Returns: {"followers": [{did, handle, displayName, ...}], "cursor": "..."}
        """
        params: dict[str, Any] = {"actor": actor, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._get("app.bsky.graph.getFollowers", params=params)

    async def get_feed(
        self,
        feed_uri: str,
        limit: int = 20,
        cursor: str = "",
    ) -> dict:
        """
        Fetch posts from a custom feed generator.
        feed_uri: AT URI of the feed generator record
                  e.g. "at://did:plc:xxx/app.bsky.feed.generator/my-feed"
        Returns: {"feed": [...], "cursor": "..."}
        """
        params: dict[str, Any] = {"feed": feed_uri, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._get("app.bsky.feed.getFeed", params=params)

    async def unlike_post(self, like_rkey: str) -> dict:
        """
        Remove a like by deleting the like record.
        like_rkey: the rkey portion of the like record URI
                   (e.g. from "at://did:plc:xxx/app.bsky.feed.like/rkey")
        """
        return await self._post("com.atproto.repo.deleteRecord", {
            "repo":       self.session.did,
            "collection": "app.bsky.feed.like",
            "rkey":       like_rkey,
        })

    async def put_record(
        self,
        collection: str,
        rkey: str,
        record: dict,
    ) -> dict:
        """
        Create or replace a record by rkey (upsert).
        Used for feed generator and labeler records that have a stable rkey.
        """
        return await self._post("com.atproto.repo.putRecord", {
            "repo":       self.session.did,
            "collection": collection,
            "rkey":       rkey,
            "record":     record,
        })

    async def ping_session(self) -> bool:
        """Lightweight session health check."""
        try:
            result = await self.get_profile(self.session.handle)
            return "did" in result
        except (BlueSkySessionExpired, httpx.HTTPError):
            return False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class BlueSkySessionExpired(Exception):
    """Raised when the access JWT is expired or invalid."""


class BlueSkyRateLimited(Exception):
    """Raised when the AT Protocol API returns 429."""
    def __init__(self, retry_after_sec: int = 60):
        self.retry_after_sec = retry_after_sec
        super().__init__(f"RateLimited: retry after {retry_after_sec}s")
