"""
XClient — X/Twitter private API client for X automation.

Uses both:
    1. Private GraphQL API (twitter.com/i/api/graphql) — for follow, like,
       retweet, DM, timeline.  Same endpoints as the official X Android app.
    2. Twitter v2 API (api.twitter.com/2) — for search_recent which requires
       a Bearer token tied to the app credentials.

Authentication:
    - auth_token cookie:  session token from the X app (extracted via Companion APK)
    - ct0 cookie:        CSRF token, also sent as X-Csrf-Token header
    - Both must match — X cross-validates them.
    - The Authorization header uses the public Bearer token that X's app uses;
      this value is static and ships with every X Android APK.

Detection notes (fleet-level):
    - x-client-uuid is a per-device UUID that must be stable per device,
      NOT regenerated per request.  Stored in PlatformHeaders.extra["client_uuid"].
    - x-twitter-client-language matches the device locale.
    - x-twitter-active-user: "yes"  (must always be present)
    - kdt cookie: extracted from the installed app.  Length must match the
      real app's value — do NOT pad or truncate.

GraphQL query IDs:
    These are stable per X app version.  They are checked here as of
    X Android 10.x (early 2026).  Update when X rotates them.
"""
from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from typing import Optional, Any

import httpx

from .hybrid_runner import PlatformHeaders


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

X_GRAPHQL_BASE  = "https://twitter.com/i/api/graphql"
X_API_V2_BASE   = "https://api.twitter.com/2"

# Public Bearer token shipped with every X Android APK (stable per major version)
X_APP_BEARER    = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

# GraphQL query IDs (X Android 10.x, 2026)
GQL_FOLLOW          = "wlmEwG2qGHELMRinr0WEoA/FavoriteTweetMutation"  # placeholder name
GQL_FOLLOW_ID       = "wlmEwG2qGHELMRinr0WEoA"
GQL_UNFOLLOW_ID     = "iSicc7LrzWGBgDPL0tM_TQ"
GQL_LIKE_ID         = "lI07N6Otwv1PhnEgXILM7A"
GQL_UNLIKE_ID       = "ZYKSe-w7KEslx3JhSIk5LA"
GQL_RETWEET_ID      = "ojPdsZsimiJrUGLR1sjUtA"
GQL_HOME_TIMELINE   = "HJFjzBgCs16TqxewQOeLNg"
GQL_CREATE_DM       = "oBwyQ0_xVbAQ8FAyG0pCRA"
GQL_GET_DM_INBOX    = "oPzEOvCFGPH1sINqhEAXEQ"


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class XSession:
    """Live authenticated session for one X account."""
    account_id:  str
    auth_token:  str        # auth_token cookie — extracted from X Android app
    ct0_csrf:    str        # ct0 CSRF cookie + header value
    user_id:     str        # X numeric user ID
    username:    str        # handle without @
    headers:     PlatformHeaders
    is_valid:    bool = True


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class XClient:
    """
    Thin async HTTP client for X's private GraphQL + v2 REST API.

    One instance per account session.

    All requests route through socks5://127.0.0.1:8089 (Companion APK SOCKS
    → IPRoyal residential), carrying the phone's real residential IP.

    Cookie + CSRF handling:
        X cross-validates the ct0 cookie against the X-Csrf-Token header.
        Both must carry the same value at all times.
    """

    def __init__(
        self,
        session: XSession,
        proxy_url: str = "socks5://127.0.0.1:8089",
    ):
        self.session   = session
        self.proxy_url = proxy_url
        self._client: Optional[httpx.AsyncClient] = None

    def _build_client(self) -> httpx.AsyncClient:
        h = self.session.headers
        kdt      = h.extra.get("kdt", "")
        twid     = urllib.parse.quote(f"u%3D{self.session.user_id}")
        guest_id = h.extra.get("guest_id", "")
        cookie   = (
            f"auth_token={self.session.auth_token}; "
            f"ct0={self.session.ct0_csrf}; "
            f"twid={twid}; "
        )
        if kdt:
            cookie += f"kdt={kdt}; "
        if guest_id:
            cookie += f"guest_id={guest_id}; "

        return httpx.AsyncClient(
            proxy=self.proxy_url,
            headers={
                "User-Agent":              h.user_agent,
                "Authorization":           f"Bearer {X_APP_BEARER}",
                "X-Csrf-Token":            self.session.ct0_csrf,
                "Cookie":                  cookie,
                "Accept":                  "*/*",
                "Accept-Language":         h.locale.replace("_", "-"),
                "Accept-Encoding":         "gzip, deflate, br",
                "Connection":              "keep-alive",
                "Content-Type":            "application/json",
                "x-twitter-auth-type":     "OAuth2Session",
                "x-twitter-active-user":   "yes",
                "x-twitter-client-language": h.locale.split("_")[0],
                "x-client-uuid":           h.extra.get("client_uuid", h.device_id),
                "x-twitter-client-deviceid": h.device_id,
            },
            timeout=httpx.Timeout(20.0),
            follow_redirects=True,
        )

    async def __aenter__(self) -> "XClient":
        self._client = self._build_client()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Core request helpers
    # ------------------------------------------------------------------

    async def _graphql_post(
        self,
        query_id: str,
        variables: dict,
        features: dict | None = None,
    ) -> dict:
        assert self._client, "Use 'async with XClient(...) as c:'"
        payload: dict[str, Any] = {"variables": variables}
        if features is not None:
            payload["features"] = features
        resp = await self._client.post(
            f"{X_GRAPHQL_BASE}/{query_id}",
            json=payload,
        )
        self._check_response(resp)
        return resp.json()

    async def _graphql_get(
        self,
        query_id: str,
        variables: dict,
        features: dict | None = None,
    ) -> dict:
        assert self._client, "Use 'async with XClient(...) as c:'"
        params: dict[str, Any] = {
            "variables": json.dumps(variables, separators=(",", ":")),
        }
        if features is not None:
            params["features"] = json.dumps(features, separators=(",", ":"))
        resp = await self._client.get(
            f"{X_GRAPHQL_BASE}/{query_id}",
            params=params,
        )
        self._check_response(resp)
        return resp.json()

    async def _v2_get(self, endpoint: str, params: dict | None = None) -> dict:
        assert self._client, "Use 'async with XClient(...) as c:'"
        resp = await self._client.get(
            f"{X_API_V2_BASE}/{endpoint}",
            params=params or {},
        )
        self._check_response(resp)
        return resp.json()

    def _check_response(self, resp: httpx.Response) -> None:
        if resp.status_code == 401:
            self.session.is_valid = False
            raise XSessionExpired(
                f"Session expired for @{self.session.username}"
            )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("x-rate-limit-reset", "60"))
            raise XRateLimited(retry_after_sec=retry_after)
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def follow_user(self, user_id: str) -> dict:
        """Follow a user by their numeric user ID."""
        return await self._graphql_post(
            f"{GQL_FOLLOW_ID}/FollowUser",
            variables={
                "userId":      user_id,
                "displayName": "",
            },
        )

    async def unfollow_user(self, user_id: str) -> dict:
        """Unfollow a user by their numeric user ID."""
        return await self._graphql_post(
            f"{GQL_UNFOLLOW_ID}/UnfollowUser",
            variables={"userId": user_id},
        )

    async def like_tweet(self, tweet_id: str) -> dict:
        """Like a tweet by its numeric tweet ID."""
        return await self._graphql_post(
            f"{GQL_LIKE_ID}/FavoriteTweet",
            variables={"tweet_id": tweet_id},
        )

    async def unlike_tweet(self, tweet_id: str) -> dict:
        """Remove a like from a tweet."""
        return await self._graphql_post(
            f"{GQL_UNLIKE_ID}/UnfavoriteTweet",
            variables={"tweet_id": tweet_id},
        )

    async def retweet(self, tweet_id: str) -> dict:
        """Retweet a tweet by ID."""
        return await self._graphql_post(
            f"{GQL_RETWEET_ID}/CreateRetweet",
            variables={
                "tweet_id":       tweet_id,
                "dark_request":   False,
            },
        )

    async def send_dm(self, recipient_id: str, text: str) -> dict:
        """
        Send a DM to a user.
        Uses the GraphQL DM creation endpoint.
        """
        return await self._graphql_post(
            f"{GQL_CREATE_DM}/SendDMByParticipants",
            variables={
                "message": {
                    "message_data": {
                        "text": text,
                    }
                },
                "participants": [{"user_id": recipient_id}],
                "requestContext": "PREFETCH",
            },
        )

    async def get_timeline(self, count: int = 20, cursor: str = "") -> dict:
        """
        Fetch the home timeline (For You / Following).
        Returns raw GraphQL timeline response.
        """
        variables: dict[str, Any] = {
            "count":                      count,
            "includePromotedContent":     True,
            "latestControlAvailable":     True,
            "requestContext":             "launch",
            "withCommunity":              True,
            "seenTweetIds":               [],
        }
        if cursor:
            variables["cursor"] = cursor
        return await self._graphql_get(
            f"{GQL_HOME_TIMELINE}/HomeTimeline",
            variables=variables,
            features={
                "rweb_lists_timeline_redesign_enabled":                        True,
                "responsive_web_graphql_exclude_directive_enabled":            True,
                "verified_phone_label_enabled":                                False,
                "creator_subscriptions_tweet_preview_api_enabled":             True,
                "responsive_web_graphql_timeline_navigation_enabled":          True,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                "tweetypie_unmention_optimization_enabled":                    True,
                "responsive_web_edit_tweet_api_enabled":                       True,
                "graphql_is_translatable_rweb_tweet_is_translatable_enabled":  True,
                "view_counts_everywhere_api_enabled":                          True,
                "longform_notetweets_consumption_enabled":                     True,
                "tweet_awards_web_tipping_enabled":                            False,
                "freedom_of_speech_not_reach_fetch_enabled":                   True,
                "standardized_nudges_misinfo":                                 True,
                "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": False,
                "interactive_text_enabled":                                    True,
                "responsive_web_text_conversations_enabled":                   False,
                "longform_notetweets_rich_text_read_enabled":                  True,
                "longform_notetweets_inline_media_enabled":                    False,
                "responsive_web_enhance_cards_enabled":                        False,
            },
        )

    async def search_recent(self, query: str, count: int = 20) -> dict:
        """
        Search for recent tweets via the v2 REST API.
        Returns: {"data": [tweet_objects], "meta": {...}}
        """
        return await self._v2_get("tweets/search/recent", params={
            "query":        query,
            "max_results":  min(count, 100),
            "tweet.fields": "created_at,author_id,text",
        })

    async def ping_session(self) -> bool:
        """Lightweight session health check via v2 /users/me."""
        try:
            result = await self._v2_get("users/me", params={
                "user.fields": "id,name,username"
            })
            return "data" in result and "id" in result["data"]
        except (XSessionExpired, httpx.HTTPError):
            return False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class XSessionExpired(Exception):
    """Raised when X returns 401 — auth_token/ct0 are invalid."""


class XRateLimited(Exception):
    """Raised when X returns 429 — rate limit hit."""
    def __init__(self, retry_after_sec: int = 60):
        self.retry_after_sec = retry_after_sec
        super().__init__(f"RateLimited: retry after {retry_after_sec}s")
