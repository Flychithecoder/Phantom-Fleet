"""
Profile builder routes — AI bio generation, bulk bio/PFP update, pin post.

Endpoints:
    POST   /api/profiles/generate-bio       — AI generate bio variants
    POST   /api/profiles/update-bio         — bulk update biography + external URL
    POST   /api/profiles/update-pfp         — bulk update profile photo (with per-account uniquification)
    POST   /api/profiles/pin-post           — bulk pin a post across accounts
    GET    /api/profiles/{account_id}/posts — fetch recent posts (for pin picker)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("phantom_fleet.api.profiles")
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GenerateBioRequest(BaseModel):
    niche: str = "lifestyle"
    tone: str = "playful, confident"
    mother_account: Optional[str] = None
    link_in_bio: Optional[str] = None
    count: int = 5

class UpdateBioRequest(BaseModel):
    account_ids: Optional[list[str]] = None
    group_id: Optional[str] = None
    biography: str
    full_name: Optional[str] = None
    external_url: Optional[str] = None      # Telegram channel URL — never OnlyFans direct
    concurrency: int = 3

class UpdatePfpRequest(BaseModel):
    account_ids: Optional[list[str]] = None
    group_id: Optional[str] = None
    image_base64: str
    concurrency: int = 3

class PinPostRequest(BaseModel):
    account_ids: Optional[list[str]] = None
    group_id: Optional[str] = None
    media_id: str
    concurrency: int = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "Database unavailable")
    return pool


async def _resolve_accounts(pool, account_ids: Optional[list[str]], group_id: Optional[str]) -> list[dict]:
    async with pool.acquire() as conn:
        if account_ids:
            rows = await conn.fetch(
                "SELECT * FROM accounts WHERE id = ANY($1::text[]) AND status='active'",
                account_ids,
            )
        elif group_id:
            rows = await conn.fetch(
                "SELECT * FROM accounts WHERE group_id=$1 AND status='active'", group_id
            )
        else:
            return []
    return [dict(r) for r in rows]


async def _get_openrouter_key(pool) -> str:
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM settings WHERE key='openrouter_api_key'")
            if row and row["value"]:
                return row["value"]
    except Exception:
        pass
    return os.getenv("OPENROUTER_API_KEY", "")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/generate-bio")
async def generate_bio(body: GenerateBioRequest, request: Request):
    pool = _pool(request)
    api_key = await _get_openrouter_key(pool)
    if not api_key:
        # Return template bios as fallback
        return {"bios": _fallback_bios(body.niche, body.count)}

    funnel = body.link_in_bio or "link in bio"
    mother = f"Sister account: @{body.mother_account}" if body.mother_account else ""

    system = (
        "You write short Instagram/Threads bios for model/influencer accounts. "
        "Max 150 characters each. Sound real, not corporate. "
        "Never mention OnlyFans — use 'Telegram', 'link in bio', or similar. "
        "Return ONLY a JSON array of strings. No markdown, no numbering."
    )
    user = (
        f"Write {body.count} different bios for a {body.niche} creator. "
        f"Tone: {body.tone}. "
        f"Funnel: {funnel}. "
        f"{mother}"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model":       "anthropic/claude-haiku-4-5-20251001",
                    "temperature": 0.85,
                    "max_tokens":  500,
                    "messages":    [{"role": "system", "content": system}, {"role": "user", "content": user}],
                },
            )
            resp.raise_for_status()
            import re, json
            text = resp.json()["choices"][0]["message"]["content"].strip()
            clean = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
            bios = json.loads(clean)
            if not isinstance(bios, list):
                bios = [bios]
            return {"bios": [str(b)[:150] for b in bios[:body.count]]}
    except Exception as exc:
        log.warning("Bio generation failed: %s", exc)
        return {"bios": _fallback_bios(body.niche, body.count)}


def _fallback_bios(niche: str, count: int) -> list[str]:
    templates = [
        f"living my best {niche} life ✨ | link in bio",
        f"content creator | {niche} | everything in my bio link",
        f"just a girl obsessed with {niche} 🔥",
        f"behind the camera & in front of it | {niche}",
        f"your favorite {niche} creator → link below",
    ]
    return (templates * ((count // len(templates)) + 1))[:count]


@router.post("/update-bio")
async def update_bio(body: UpdateBioRequest, request: Request):
    pool = _pool(request)
    accounts = await _resolve_accounts(pool, body.account_ids, body.group_id)
    if not accounts:
        raise HTTPException(400, "No active accounts found")

    import asyncio
    sem = asyncio.Semaphore(body.concurrency)
    results = {"success": 0, "failed": 0, "errors": []}

    async def _update_one(acc: dict) -> None:
        async with sem:
            try:
                from ...core.instagram_client import IGSession
                from ...core.threads_client import ThreadsClient

                proxy_url = await _get_proxy_url(pool, acc.get("proxy_id"))
                session = _make_session(acc)

                async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
                    await client.update_profile(
                        bio=body.biography,
                        display_name=body.full_name or "",
                        external_url=body.external_url or "",
                    )

                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO activity_log (account_id, action, status, message)
                        VALUES ($1, 'update_bio', 'success', $2)
                        """,
                        acc["id"], f"Bio updated: {body.biography[:50]}",
                    )
                results["success"] += 1
            except Exception as exc:
                results["failed"] += 1
                results["errors"].append(f"{acc.get('username', acc['id'])}: {exc}")
                log.warning("Update bio %s: %s", acc.get("username"), exc)

    await asyncio.gather(*[_update_one(a) for a in accounts])
    return {**results, "total": len(accounts)}


@router.post("/update-pfp")
async def update_pfp(body: UpdatePfpRequest, request: Request):
    """
    Bulk update PFP. Each account gets a slightly modified version of the image
    (metadata variation) to avoid fleet-wide image hash fingerprint.
    """
    pool = _pool(request)
    accounts = await _resolve_accounts(pool, body.account_ids, body.group_id)
    if not accounts:
        raise HTTPException(400, "No active accounts found")

    import asyncio
    import base64
    sem = asyncio.Semaphore(body.concurrency)
    results = {"success": 0, "failed": 0, "errors": []}

    raw_bytes = base64.b64decode(body.image_base64)

    async def _update_one(acc: dict, img_bytes: bytes) -> None:
        async with sem:
            try:
                from ...core.instagram_client import IGSession
                from ...core.threads_client import ThreadsClient

                proxy_url = await _get_proxy_url(pool, acc.get("proxy_id"))
                session = _make_session(acc)

                async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
                    await client.update_profile_photo(img_bytes)

                async with pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO activity_log (account_id, action, status) VALUES ($1, 'update_pfp', 'success')",
                        acc["id"],
                    )
                results["success"] += 1
            except Exception as exc:
                results["failed"] += 1
                results["errors"].append(f"{acc.get('username', acc['id'])}: {exc}")

    # Give each account slightly varied bytes (append account-id-derived salt as comment)
    # This varies the image hash at fleet level without visible change
    tasks = []
    for acc in accounts:
        acc_salt = acc["id"][-4:].encode()
        varied = raw_bytes + b"\xff\xfe" + acc_salt  # harmless trailing bytes for JPEG
        tasks.append(_update_one(acc, varied))

    await asyncio.gather(*tasks)
    return {**results, "total": len(accounts)}


@router.post("/pin-post")
async def pin_post(body: PinPostRequest, request: Request):
    pool = _pool(request)
    accounts = await _resolve_accounts(pool, body.account_ids, body.group_id)
    if not accounts:
        raise HTTPException(400, "No active accounts found")

    import asyncio
    sem = asyncio.Semaphore(body.concurrency)
    results = {"success": 0, "failed": 0, "errors": []}

    async def _pin_one(acc: dict) -> None:
        async with sem:
            try:
                from ...core.threads_client import ThreadsClient
                proxy_url = await _get_proxy_url(pool, acc.get("proxy_id"))
                session = _make_session(acc)
                async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
                    await client.pin_post(body.media_id)
                async with pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO activity_log (account_id, action, target, status) VALUES ($1, 'pin_post', $2, 'success')",
                        acc["id"], body.media_id,
                    )
                results["success"] += 1
            except Exception as exc:
                results["failed"] += 1
                results["errors"].append(f"{acc.get('username', acc['id'])}: {exc}")

    await asyncio.gather(*[_pin_one(a) for a in accounts])
    return {**results, "total": len(accounts)}


@router.get("/{account_id}/posts")
async def get_account_posts(account_id: str, request: Request, limit: int = 12):
    pool = _pool(request)
    async with pool.acquire() as conn:
        acc = await conn.fetchrow("SELECT * FROM accounts WHERE id=$1", account_id)
    if not acc:
        raise HTTPException(404, "Account not found")

    acc = dict(acc)
    try:
        from ...core.threads_client import ThreadsClient
        proxy_url = await _get_proxy_url(pool, acc.get("proxy_id"))
        session = _make_session(acc)
        async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
            feed = await client.get_user_feed(acc.get("user_id", ""))
            items = feed.get("items", []) or feed.get("feed_items", [])
            posts = []
            for item in items[:limit]:
                media = item.get("media_or_ad") or item.get("media") or item
                cap_obj = media.get("caption")
                caption = cap_obj.get("text", "") if isinstance(cap_obj, dict) else (cap_obj or "")
                posts.append({
                    "media_id": media.get("pk") or media.get("id"),
                    "caption": caption[:100],
                    "like_count": media.get("like_count", 0),
                    "taken_at": media.get("taken_at"),
                })
            return {"posts": posts}
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _get_proxy_url(pool, proxy_id: Optional[str]) -> Optional[str]:
    if not proxy_id:
        return None
    try:
        async with pool.acquire() as conn:
            proxy = await conn.fetchrow("SELECT * FROM proxies WHERE id=$1", proxy_id)
            if proxy:
                return f"socks5://{proxy['host']}:{proxy['port']}"
    except Exception:
        pass
    return None


def _make_session(acc: dict):
    from ...core.instagram_client import IGSession
    from ...core.hybrid_runner import PlatformHeaders
    return IGSession(
        account_id=acc.get("id", ""),
        ig_user_id=acc.get("user_id", ""),
        username=acc.get("username", ""),
        session_id=acc.get("sessionid", ""),
        csrftoken=acc.get("csrftoken", ""),
        mid=acc.get("mid", ""),
        ds_user_id=acc.get("user_id", ""),
        headers=PlatformHeaders(),
    )
