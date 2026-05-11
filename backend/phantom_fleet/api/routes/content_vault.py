"""
Content Vault routes — media storage bridge between ContentForge and Phantom Fleet.

Endpoints:
    POST   /api/content-vault/push              — ContentForge integration endpoint (bridge)
    GET    /api/content-vault                   — list items with optional filters
    POST   /api/content-vault/upload            — manual upload from dashboard
    DELETE /api/content-vault/{item_id}         — delete item and its file
    GET    /api/content-vault/stats             — vault statistics
    POST   /api/content-vault/{item_id}/deliver — push item to a phone gallery via ADB
    POST   /api/content-vault/schedule          — assign vault items to accounts for posting

Auth on /push:
    X-ContentForge-Key header must match env var CONTENTFORGE_API_KEY.
    Missing or wrong key → 403.

ContentForge integration (add ONE call after generating media):

    # In ContentForge, after generating media:
    await httpx.post(
        f"{PHANTOM_FLEET_URL}/api/content-vault/push",
        headers={"X-ContentForge-Key": CONTENTFORGE_API_KEY},
        files={"file": open(media_path, "rb")},
        data={"metadata": json.dumps({
            "caption": caption,
            "platform_tags": ["instagram"],
            "content_tags": ["lifestyle", "sfw"],
            "persona_id": persona_id,
            "source": "contentforge",
        })}
    )
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from ...core.content_vault import (
    ALLOWED_MIME_TYPES,
    MAX_FILE_BYTES,
    ContentItem,
    get_vault,
)

log = logging.getLogger("phantom_fleet.api.content_vault")

router = APIRouter()

# ADB remote destination for gallery delivery
_PHONE_GALLERY_PATH = "/sdcard/DCIM/PhantomFleet"


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ContentItemOut(BaseModel):
    item_id: str
    file_path: str
    file_type: str
    caption: str
    platform_tags: list[str]
    content_tags: list[str]
    persona_id: Optional[str]
    source: str
    created_at_iso: str
    used_count: int
    last_used_iso: Optional[str]


class ContentListOut(BaseModel):
    items: list[ContentItemOut]
    total: int


class PushResultOut(BaseModel):
    item_id: str
    file_type: str
    source: str
    message: str = "Content received and stored."


class DeleteResultOut(BaseModel):
    item_id: str
    deleted: bool


class DeliverResultOut(BaseModel):
    item_id: str
    phone_serial: str
    remote_path: str
    delivered: bool


class ScheduleRequestIn(BaseModel):
    account_ids: list[str]
    days_ahead: int = 7
    platform: str = "instagram"
    persona_id: Optional[str] = None
    content_tags: Optional[list[str]] = None


class ScheduleResultOut(BaseModel):
    assignments: int
    accounts: int
    days: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item_out(item: ContentItem) -> ContentItemOut:
    return ContentItemOut(
        item_id=item.item_id,
        file_path=item.file_path,
        file_type=item.file_type,
        caption=item.caption,
        platform_tags=item.platform_tags,
        content_tags=item.content_tags,
        persona_id=item.persona_id,
        source=item.source,
        created_at_iso=item.created_at_iso,
        used_count=item.used_count,
        last_used_iso=item.last_used_iso,
    )


def _check_contentforge_key(key: Optional[str]) -> None:
    """
    Validate the X-ContentForge-Key header against env var CONTENTFORGE_API_KEY.
    Raises 403 if key is missing or does not match.
    """
    expected = os.environ.get("CONTENTFORGE_API_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="CONTENTFORGE_API_KEY is not configured on the server.",
        )
    if key != expected:
        raise HTTPException(
            status_code=403,
            detail="Invalid or missing X-ContentForge-Key header.",
        )


def _validate_upload(file: UploadFile) -> str:
    """
    Validate MIME type from UploadFile.content_type.
    Returns the validated MIME type string.
    Raises 415 if not in ALLOWED_MIME_TYPES.
    """
    content_type = (file.content_type or "").split(";")[0].strip()
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported media type {content_type!r}. "
                f"Allowed: {sorted(ALLOWED_MIME_TYPES)}"
            ),
        )
    return content_type


async def _read_file_checked(file: UploadFile) -> bytes:
    """Read file bytes and enforce max size."""
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File size {len(data):,} bytes exceeds 100 MB limit.",
        )
    return data


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/push", response_model=PushResultOut)
async def push_from_contentforge(
    file: UploadFile = File(...),
    metadata: str = Form(...),
    x_contentforge_key: Optional[str] = Header(None, alias="X-ContentForge-Key"),
) -> PushResultOut:
    """
    ContentForge integration endpoint — the bridge.

    ContentForge calls this after generating new content.
    Accepts multipart/form-data: file (binary) + metadata (JSON string).

    Auth: X-ContentForge-Key header (shared secret from env CONTENTFORGE_API_KEY).

    Metadata JSON shape:
        {
            "caption": "...",
            "platform_tags": ["instagram", "threads"],
            "content_tags": ["lifestyle", "sfw"],
            "persona_id": "tatiana_001",   (optional)
            "source": "contentforge"
        }
    """
    _check_contentforge_key(x_contentforge_key)

    content_type = _validate_upload(file)
    file_data = await _read_file_checked(file)

    try:
        meta: dict = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"metadata JSON parse error: {exc}") from exc

    meta["file_type"] = content_type
    meta.setdefault("source", "contentforge")

    vault = get_vault()
    try:
        item = await vault.add_item(file_data, meta)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    log.info(
        "ContentVault /push: received item %s from ContentForge, persona=%s",
        item.item_id, item.persona_id,
    )
    return PushResultOut(
        item_id=item.item_id,
        file_type=item.file_type,
        source=item.source,
    )


@router.get("", response_model=ContentListOut)
async def list_items(
    platform: Optional[str] = Query(None),
    persona_id: Optional[str] = Query(None),
    content_tags: Optional[str] = Query(None, description="Comma-separated tags, all must match"),
    unused_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
) -> ContentListOut:
    """
    List content vault items with optional filters.

    Query params:
        platform:      filter by platform tag (e.g. "instagram")
        persona_id:    filter by persona (also returns items with persona_id=None)
        content_tags:  comma-separated list of tags that all must be present
        unused_only:   only items that have never been posted
        limit:         max results (default 50, max 500)
    """
    tag_list: Optional[list[str]] = None
    if content_tags:
        tag_list = [t.strip() for t in content_tags.split(",") if t.strip()]

    vault = get_vault()
    items = await vault.get_items(
        platform=platform,
        persona_id=persona_id,
        content_tags=tag_list,
        unused_only=unused_only,
        limit=limit,
    )
    return ContentListOut(items=[_item_out(i) for i in items], total=len(items))


@router.post("/upload", response_model=PushResultOut)
async def manual_upload(
    file: UploadFile = File(...),
    caption: str = Form(""),
    platform_tags: str = Form("instagram", description="Comma-separated platform tags"),
    content_tags: str = Form("", description="Comma-separated content tags"),
    persona_id: Optional[str] = Form(None),
) -> PushResultOut:
    """
    Manual upload from the dashboard (no API key required — internal use).

    Accepts multipart/form-data with the media file plus form fields.
    """
    content_type = _validate_upload(file)
    file_data = await _read_file_checked(file)

    meta = {
        "file_type": content_type,
        "caption": caption,
        "platform_tags": [t.strip() for t in platform_tags.split(",") if t.strip()],
        "content_tags": [t.strip() for t in content_tags.split(",") if t.strip()],
        "persona_id": persona_id or None,
        "source": "manual_upload",
    }

    vault = get_vault()
    try:
        item = await vault.add_item(file_data, meta)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return PushResultOut(
        item_id=item.item_id,
        file_type=item.file_type,
        source=item.source,
        message="Uploaded successfully.",
    )


@router.delete("/{item_id}", response_model=DeleteResultOut)
async def delete_item(item_id: str) -> DeleteResultOut:
    """Delete a content item and its file from disk."""
    vault = get_vault()
    try:
        await vault.delete_item(item_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Item {item_id!r} not found")
    return DeleteResultOut(item_id=item_id, deleted=True)


@router.get("/stats")
async def vault_stats() -> dict:
    """
    Return aggregate vault statistics.

    Response shape:
        {
            "total_items": int,
            "unused_items": int,
            "used_this_week": int,
            "by_platform": {"instagram": N, ...},
            "by_source": {"contentforge": N, ...},
            "by_tag": {"sfw": N, ...},
            "total_file_size_bytes": int,
        }
    """
    vault = get_vault()
    return await vault.get_stats()


@router.post("/{item_id}/deliver", response_model=DeliverResultOut)
async def deliver_to_phone(
    item_id: str,
    request: Request,
    phone_serial: str = Query(..., description="ADB serial of the target phone"),
) -> DeliverResultOut:
    """
    Push a content item from the vault to a phone's gallery via ADB.

    The file is pushed to /sdcard/DCIM/PhantomFleet/ on the device.
    The phone must be registered in the fleet; proxy state is NOT required
    for file delivery (ADB push does not go through the SOCKS5 proxy).

    Raises:
        404 — item or phone not found
        502 — ADB push failed
    """
    vault = get_vault()
    items = await vault.get_items(limit=1)  # cheap way to check existence
    # Load specific item
    all_items = await vault.get_items(limit=10000)
    item_map = {i.item_id: i for i in all_items}

    item = item_map.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Item {item_id!r} not found in vault")

    fleet = request.app.state.ctx.fleet
    phone = fleet.get(phone_serial)
    if phone is None:
        raise HTTPException(
            status_code=404,
            detail=f"Phone {phone_serial!r} not registered in fleet",
        )

    filename = os.path.basename(item.file_path)
    remote_path = f"{_PHONE_GALLERY_PATH}/{filename}"

    try:
        await phone.adb_push(item.file_path, remote_path)
        # Notify MediaScanner so the file appears in the gallery app
        await phone.adb_shell(
            f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
            f"-d file://{remote_path}"
        )
    except Exception as exc:
        log.exception("ADB deliver failed item=%s phone=%s", item_id, phone_serial)
        raise HTTPException(status_code=502, detail=f"ADB push failed: {exc}") from exc

    log.info("ContentVault: delivered %s → %s:%s", item_id, phone_serial, remote_path)
    return DeliverResultOut(
        item_id=item_id,
        phone_serial=phone_serial,
        remote_path=remote_path,
        delivered=True,
    )


@router.post("/schedule", response_model=ScheduleResultOut)
async def auto_schedule(body: ScheduleRequestIn) -> ScheduleResultOut:
    """
    Assign vault items to accounts for scheduled posting over the next N days.

    For each (account, day) pair, picks one unused item from the vault
    that matches the platform/persona/tag filters and calls mark_used().

    This is a lightweight assignment stub — the full dispatch is handled by
    IGContentScheduler when building DailyPostSchedule. This endpoint marks
    items as "reserved" (used_count incremented) so they aren't double-assigned.

    Returns a count of how many (account × day) assignments were made.
    """
    vault = get_vault()
    assignments = 0

    for day_offset in range(body.days_ahead):
        available = await vault.get_items(
            platform=body.platform,
            persona_id=body.persona_id,
            content_tags=body.content_tags,
            unused_only=True,
            limit=len(body.account_ids),
        )
        if not available:
            break  # No more unused items

        for account_id, item in zip(body.account_ids, available):
            try:
                await vault.mark_used(item.item_id)
                assignments += 1
                log.debug(
                    "ContentVault schedule: account=%s day+%d item=%s",
                    account_id, day_offset, item.item_id,
                )
            except KeyError:
                pass  # Item was deleted concurrently — skip

    return ScheduleResultOut(
        assignments=assignments,
        accounts=len(body.account_ids),
        days=body.days_ahead,
    )
