"""
Reddit OAuth helper — password grant, token refresh, device identity generation.

Used by:
    - RedditRegistrationAgent (initial token acquisition after account creation)
    - Background tasks in reddit.py routes (auto-refresh on 401)
    - RedditClient.refresh_access_token()

OAuth app setup:
    Register a "script" app at https://www.reddit.com/prefs/apps
    App type must be "script" (personal use / installed on server).
    Required env vars:
        REDDIT_CLIENT_ID      — from reddit.com/prefs/apps
        REDDIT_CLIENT_SECRET  — from reddit.com/prefs/apps

Token lifetime:
    Reddit access tokens expire after 1 hour (3600s).
    refresh_token is long-lived (doesn't expire unless revoked).

Device identity:
    Reddit's mobile API sends x-reddit-device-id and x-reddit-loid headers.
    - device_id: 32-char lowercase hex, stable per-account (simulates one app install)
    - loid:      ~24-char base64url, stable per-account (logged-out identifier)
    Both are seeded by account_id so they're stable across token refreshes
    but unique per account — matching real Android device behaviour.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

REDDIT_TOKEN_URL       = "https://www.reddit.com/api/v1/access_token"
TOKEN_LIFETIME_SECONDS = 3600

# Official Reddit Android app client_id — embedded in the Reddit APK.
# Publicly documented in Reddit's API community and every open-source Reddit client.
# Installed apps use an empty client_secret.
REDDIT_OFFICIAL_CLIENT_ID = "ohXpoqrZYxa1Ag"
REDDIT_OFFICIAL_CLIENT_SECRET = ""


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class OAuthTokens:
    """Access + refresh token pair returned by Reddit OAuth."""
    access_token:  str
    refresh_token: str
    user_id:       str    # t2_XXXXX, populated by password_grant; empty on refresh
    expires_at:    float  # Unix epoch seconds when access_token expires


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------

def get_client_id() -> str:
    v = os.getenv("REDDIT_CLIENT_ID", "")
    if not v:
        raise RuntimeError(
            "REDDIT_CLIENT_ID is not set. "
            "Register a 'script' app at https://www.reddit.com/prefs/apps "
            "and set REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET."
        )
    return v


def get_client_secret() -> str:
    """Client secret is required for script apps. Empty string for installed apps."""
    return os.getenv("REDDIT_CLIENT_SECRET", "")


def _basic_auth(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}"
    return "Basic " + base64.b64encode(raw.encode()).decode()


def _user_agent(username: str, override: str = "") -> str:
    """
    Return the User-Agent string for Reddit OAuth requests.

    For phone-backed accounts pass the UA extracted from the installed app
    (e.g. "Reddit/2024.19.0 (Android 13; Samsung SM-G998B)") as `override`.
    For developer-app accounts falls back to the script UA.
    """
    return override if override else f"phantom_fleet:v1.0 (by /u/{username})"


# ---------------------------------------------------------------------------
# OAuth flows
# ---------------------------------------------------------------------------

async def password_grant(
    username:      str,
    password:      str,
    proxy_url:     str | None = None,
    client_id:     str | None = None,
    client_secret: str | None = None,
) -> OAuthTokens:
    """
    Exchange username + password for access_token + refresh_token.

    Uses Reddit's OAuth2 Resource Owner Password Credentials grant.
    Works for both script apps (client_id + client_secret) and installed
    apps (client_id only, empty secret).

    Args:
        username:      Reddit username, no /u/ prefix.
        password:      Reddit account password.
        proxy_url:     SOCKS5/HTTP proxy URL (optional; routes through phone proxy).
        client_id:     Override REDDIT_CLIENT_ID env var.
        client_secret: Override REDDIT_CLIENT_SECRET env var.

    Returns:
        OAuthTokens with access_token, refresh_token, user_id, expires_at.

    Raises:
        RuntimeError on auth failure, rate limit, or missing env vars.
    """
    cid  = client_id     or get_client_id()
    csec = client_secret or get_client_secret()

    headers = {
        "Authorization":  _basic_auth(cid, csec),
        "User-Agent":     _user_agent(username),
        "Content-Type":   "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "password",
        "username":   username,
        "password":   password,
        "scope":      (
            "identity edit flair history modconfig modflair modlog modposts modwiki "
            "mysubreddits privatemessages read report save submit subscribe vote wikiedit wikiread"
        ),
    }

    client_kwargs: dict = {"headers": headers, "timeout": httpx.Timeout(20.0)}
    if proxy_url:
        client_kwargs["proxy"] = proxy_url

    async with httpx.AsyncClient(**client_kwargs) as client:
        resp = await client.post(REDDIT_TOKEN_URL, data=data)

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", "60"))
        raise RuntimeError(
            f"Reddit OAuth rate limited — retry after {retry_after}s"
        )
    if resp.status_code == 401:
        raise RuntimeError(
            f"Reddit OAuth 401 for u/{username} — wrong credentials or app not authorised"
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Reddit OAuth password grant HTTP {resp.status_code}: {resp.text[:300]}"
        )

    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"Reddit OAuth error: {body['error']}")

    access_token  = body.get("access_token", "")
    refresh_token = body.get("refresh_token", "")

    if not access_token:
        raise RuntimeError(f"Reddit OAuth: no access_token in response: {body}")

    # Fetch t2_ user_id via /api/v1/me
    user_id = await _fetch_user_id(access_token, username, proxy_url)
    log.info("Reddit OAuth password grant succeeded for u/%s (user_id=%s)", username, user_id)

    return OAuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=user_id,
        expires_at=time.time() + TOKEN_LIFETIME_SECONDS,
    )


async def refresh_access_token(
    refresh_token: str,
    username:      str,
    proxy_url:     str | None = None,
    client_id:     str | None = None,
    client_secret: str | None = None,
    user_agent:    str = "",
) -> OAuthTokens:
    """
    Exchange a refresh_token for a new access_token.

    Called automatically by background tasks when RedditSessionExpired (401)
    is raised during agent execution.

    For phone-backed accounts, pass:
        client_id     = REDDIT_OFFICIAL_CLIENT_ID  ("ohXpoqrZYxa1Ag")
        client_secret = ""
        user_agent    = extracted UA from the Reddit app ("Reddit/2024.X.Y ...")

    This makes the refresh request look identical to the official Reddit app
    refreshing its own token — Reddit's backend sees no difference.

    Args:
        refresh_token: The long-lived refresh token.
        username:      Reddit username (for User-Agent header).
        proxy_url:     Optional proxy URL.
        client_id:     Override client_id. Use REDDIT_OFFICIAL_CLIENT_ID for phone-backed.
        client_secret: Override client_secret. Empty string for installed app flow.
        user_agent:    Real UA from phone extraction. Omit for developer-app flow.

    Returns:
        OAuthTokens. user_id will be empty — caller already has it.

    Raises:
        RuntimeError if the refresh token is invalid/revoked.
    """
    cid  = client_id     if client_id     is not None else get_client_id()
    csec = client_secret if client_secret is not None else get_client_secret()

    headers = {
        "Authorization": _basic_auth(cid, csec),
        "User-Agent":    _user_agent(username, user_agent),
        "Content-Type":  "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
    }

    client_kwargs: dict = {"headers": headers, "timeout": httpx.Timeout(20.0)}
    if proxy_url:
        client_kwargs["proxy"] = proxy_url

    async with httpx.AsyncClient(**client_kwargs) as client:
        resp = await client.post(REDDIT_TOKEN_URL, data=data)

    if resp.status_code == 401:
        raise RuntimeError(
            "Reddit OAuth refresh failed — refresh_token is invalid or revoked"
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Reddit OAuth refresh HTTP {resp.status_code}: {resp.text[:300]}"
        )

    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"Reddit OAuth refresh error: {body['error']}")

    new_access  = body.get("access_token", "")
    # Reddit may or may not rotate the refresh token
    new_refresh = body.get("refresh_token", refresh_token)

    if not new_access:
        raise RuntimeError(f"Reddit OAuth refresh: no access_token in response: {body}")

    log.info("Reddit OAuth token refreshed for u/%s", username)

    return OAuthTokens(
        access_token=new_access,
        refresh_token=new_refresh,
        user_id="",
        expires_at=time.time() + TOKEN_LIFETIME_SECONDS,
    )


# ---------------------------------------------------------------------------
# Device identity generators
# ---------------------------------------------------------------------------

def generate_device_id(account_id: str) -> str:
    """
    Generate a stable, account-specific Reddit device ID.

    Format: 32-char lowercase hex — matches the UUID-without-dashes format
    used by the Reddit Android app's x-reddit-device-id header.

    Seeded by account_id so the same account always gets the same device ID
    across token refreshes, matching a real Android device (one install,
    one stable device ID).
    """
    digest = hashlib.sha256(f"reddit_device_id_v1:{account_id}".encode()).hexdigest()
    return digest[:32]


def generate_loid(account_id: str) -> str:
    """
    Generate a stable Reddit logged-out identifier (loid).

    The loid is sent in x-reddit-loid and represents the device's anonymous
    identity before login. Reddit uses it for session continuity between
    logged-out and logged-in states.

    Real loid format: ~22-24 chars of base64url-encoded bytes.
    """
    raw = hashlib.sha256(f"reddit_loid_v1:{account_id}".encode()).digest()[:18]
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _fetch_user_id(
    access_token: str,
    username:     str,
    proxy_url:    str | None,
) -> str:
    """Fetch the authenticated account's t2_ user ID via /api/v1/me."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent":    _user_agent(username),
        "Accept":        "application/json",
    }
    client_kwargs: dict = {"headers": headers, "timeout": httpx.Timeout(15.0)}
    if proxy_url:
        client_kwargs["proxy"] = proxy_url

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get("https://oauth.reddit.com/api/v1/me")
        if resp.status_code == 200:
            data = resp.json()
            uid = data.get("id", "")
            if uid:
                return f"t2_{uid}" if not uid.startswith("t2_") else uid
    except Exception as exc:
        log.warning("Could not fetch Reddit user_id for u/%s: %s", username, exc)

    return ""
