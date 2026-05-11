"""
ContentVault — stores and manages media content for posting.

Architecture:
    - ContentForge pushes media here via POST /api/content-vault/push
    - IGContentScheduler pulls items when building DailyPostSchedule
    - ADB delivery (deliver endpoint) pushes files to phone galleries

Storage layout:
    {PHANTOM_MEDIA_DIR}/
        {item_id}.jpg    ← actual media file
        ...
    {PHANTOM_MEDIA_DIR}/index.json  ← all ContentItem metadata, keyed by item_id

Thread safety: asyncio.Lock wraps every write to the JSON index.
File writes are atomic: written to .tmp then os.replace() to prevent
partial-read corruption if the process is killed mid-write.

ContentForge integration (add this to ContentForge after generating media):

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

import asyncio
import json
import logging
import mimetypes
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("phantom_fleet.core.content_vault")

# ---------------------------------------------------------------------------
# Allowed MIME types
# ---------------------------------------------------------------------------

ALLOWED_MIME_TYPES: frozenset[str] = frozenset({
    "image/jpeg",
    "image/png",
    "video/mp4",
})

_EXT_MAP: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png":  "png",
    "video/mp4":  "mp4",
}

MAX_FILE_BYTES: int = 100 * 1024 * 1024  # 100 MB


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ContentItem:
    item_id:        str                  # UUID
    file_path:      str                  # absolute local path on Phantom Fleet server
    file_type:      str                  # "image/jpeg" | "image/png" | "video/mp4"
    caption:        str
    platform_tags:  list[str]           # ["instagram", "threads", "tiktok"]
    content_tags:   list[str]           # ["sfw", "lifestyle", "fitness"] etc.
    persona_id:     Optional[str]       # which persona this is for (None = any)
    source:         str                  # "contentforge" | "manual_upload" | "recycled"
    created_at_iso: str
    used_count:     int = 0             # how many times posted
    last_used_iso:  Optional[str] = None


# ---------------------------------------------------------------------------
# Vault
# ---------------------------------------------------------------------------

class ContentVault:
    """
    Stores and manages media content for posting.

    ContentForge pushes to here via API.
    IGContentScheduler pulls from here when building daily plans.
    ADB delivery pushes from here to phone galleries.
    """

    def __init__(self, media_dir: Optional[str] = None) -> None:
        self._media_dir: str = media_dir or os.environ.get("PHANTOM_MEDIA_DIR", "./media")
        self._index_path: str = os.path.join(self._media_dir, "index.json")
        self._lock: asyncio.Lock = asyncio.Lock()
        self._cache: Optional[dict[str, ContentItem]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def add_item(self, file_data: bytes, metadata: dict) -> ContentItem:
        """
        Save file_data to disk and register metadata in the index.

        Args:
            file_data: Raw bytes of the media file.
            metadata: Dict with keys: caption, platform_tags, content_tags,
                      persona_id, source, file_type.
                      file_type must be one of ALLOWED_MIME_TYPES.

        Returns:
            The newly created ContentItem.

        Raises:
            ValueError: If file_type is not allowed or file exceeds MAX_FILE_BYTES.
        """
        file_type = metadata.get("file_type", "image/jpeg")
        if file_type not in ALLOWED_MIME_TYPES:
            raise ValueError(
                f"Unsupported file_type {file_type!r}. "
                f"Allowed: {sorted(ALLOWED_MIME_TYPES)}"
            )
        if len(file_data) > MAX_FILE_BYTES:
            raise ValueError(
                f"File size {len(file_data):,} bytes exceeds limit "
                f"of {MAX_FILE_BYTES:,} bytes (100 MB)."
            )

        item_id = str(uuid.uuid4())
        ext = _EXT_MAP[file_type]
        file_path = os.path.join(self._media_dir, f"{item_id}.{ext}")

        # Ensure directory exists
        os.makedirs(self._media_dir, exist_ok=True)

        # Write file atomically
        tmp_path = file_path + ".tmp"
        with open(tmp_path, "wb") as fh:
            fh.write(file_data)
        os.replace(tmp_path, file_path)

        item = ContentItem(
            item_id=item_id,
            file_path=file_path,
            file_type=file_type,
            caption=metadata.get("caption", ""),
            platform_tags=list(metadata.get("platform_tags", [])),
            content_tags=list(metadata.get("content_tags", [])),
            persona_id=metadata.get("persona_id"),
            source=metadata.get("source", "manual_upload"),
            created_at_iso=datetime.now(timezone.utc).isoformat(),
        )

        async with self._lock:
            index = await self._load_index()
            index[item_id] = item
            await self._save_index(index)

        log.info(
            "ContentVault: added item %s source=%s type=%s size=%d bytes",
            item_id, item.source, file_type, len(file_data),
        )
        return item

    async def get_items(
        self,
        platform: Optional[str] = None,
        persona_id: Optional[str] = None,
        content_tags: Optional[list[str]] = None,
        unused_only: bool = False,
        limit: int = 10,
    ) -> list[ContentItem]:
        """
        Query the vault with optional filters.

        Args:
            platform:     If set, only items whose platform_tags include this value.
            persona_id:   If set, only items whose persona_id matches OR is None.
            content_tags: If set, only items that have ALL of these tags.
            unused_only:  If True, only items with used_count == 0.
            limit:        Max items to return (default 10).

        Returns:
            Filtered list of ContentItem, newest first.
        """
        async with self._lock:
            index = await self._load_index()

        items = list(index.values())

        if platform is not None:
            items = [i for i in items if platform in i.platform_tags]

        if persona_id is not None:
            items = [i for i in items if i.persona_id is None or i.persona_id == persona_id]

        if content_tags:
            tag_set = set(content_tags)
            items = [i for i in items if tag_set.issubset(set(i.content_tags))]

        if unused_only:
            items = [i for i in items if i.used_count == 0]

        # Sort newest first
        items.sort(key=lambda x: x.created_at_iso, reverse=True)
        return items[:limit]

    async def mark_used(self, item_id: str) -> None:
        """
        Increment used_count and set last_used_iso to now.

        Raises:
            KeyError: If item_id does not exist in the vault.
        """
        async with self._lock:
            index = await self._load_index()
            if item_id not in index:
                raise KeyError(f"ContentItem {item_id!r} not found in vault")
            item = index[item_id]
            item.used_count += 1
            item.last_used_iso = datetime.now(timezone.utc).isoformat()
            await self._save_index(index)

        log.debug("ContentVault: marked item %s used (count=%d)", item_id, index[item_id].used_count)

    async def delete_item(self, item_id: str) -> None:
        """
        Remove an item from the index and delete its file from disk.

        Raises:
            KeyError: If item_id does not exist.
        """
        async with self._lock:
            index = await self._load_index()
            if item_id not in index:
                raise KeyError(f"ContentItem {item_id!r} not found in vault")
            item = index.pop(item_id)
            await self._save_index(index)

        # Delete file outside the lock (IO can be slow)
        if os.path.exists(item.file_path):
            try:
                os.remove(item.file_path)
                log.info("ContentVault: deleted file %s for item %s", item.file_path, item_id)
            except OSError as exc:
                log.warning("ContentVault: could not delete file %s: %s", item.file_path, exc)

    async def get_stats(self) -> dict:
        """
        Return aggregate statistics about the vault.

        Returns:
            {
                "total_items": int,
                "unused_items": int,
                "used_this_week": int,       # items with used_count >= 1 and last_used within 7 days
                "by_platform": {"instagram": N, ...},
                "by_source": {"contentforge": N, ...},
                "by_tag": {"sfw": N, "lifestyle": N, ...},
                "total_file_size_bytes": int,
            }
        """
        async with self._lock:
            index = await self._load_index()

        items = list(index.values())
        now = datetime.now(timezone.utc)

        by_platform: dict[str, int] = {}
        by_source: dict[str, int] = {}
        by_tag: dict[str, int] = {}
        total_size = 0
        used_this_week = 0

        for item in items:
            # Platform counts
            for tag in item.platform_tags:
                by_platform[tag] = by_platform.get(tag, 0) + 1
            # Source counts
            by_source[item.source] = by_source.get(item.source, 0) + 1
            # Content tag counts
            for tag in item.content_tags:
                by_tag[tag] = by_tag.get(tag, 0) + 1
            # File size
            if os.path.exists(item.file_path):
                try:
                    total_size += os.path.getsize(item.file_path)
                except OSError:
                    pass
            # Used this week
            if item.last_used_iso:
                try:
                    last_used = datetime.fromisoformat(item.last_used_iso)
                    if (now - last_used).days < 7:
                        used_this_week += 1
                except ValueError:
                    pass

        return {
            "total_items": len(items),
            "unused_items": sum(1 for i in items if i.used_count == 0),
            "used_this_week": used_this_week,
            "by_platform": by_platform,
            "by_source": by_source,
            "by_tag": by_tag,
            "total_file_size_bytes": total_size,
        }

    # ------------------------------------------------------------------
    # Internal index helpers
    # ------------------------------------------------------------------

    async def _load_index(self) -> dict[str, ContentItem]:
        """
        Load the JSON index from disk, returning a dict[item_id → ContentItem].
        Returns empty dict if the index file does not exist yet.
        Caller must hold self._lock.
        """
        if self._cache is not None:
            return self._cache

        if not os.path.exists(self._index_path):
            self._cache = {}
            return self._cache

        try:
            with open(self._index_path, "r", encoding="utf-8") as fh:
                raw: dict = json.load(fh)
            self._cache = {
                item_id: _dict_to_item(item_dict)
                for item_id, item_dict in raw.items()
            }
        except (json.JSONDecodeError, KeyError) as exc:
            log.error("ContentVault: corrupt index at %s: %s — starting fresh", self._index_path, exc)
            self._cache = {}

        return self._cache

    async def _save_index(self, index: dict[str, ContentItem]) -> None:
        """
        Atomically write the JSON index to disk.
        Caller must hold self._lock.
        """
        os.makedirs(self._media_dir, exist_ok=True)

        raw = {item_id: asdict(item) for item_id, item in index.items()}
        tmp_path = self._index_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(raw, fh, indent=2)
        os.replace(tmp_path, self._index_path)
        # Update cache
        self._cache = index


# ---------------------------------------------------------------------------
# Module-level singleton (shared across all routes)
# ---------------------------------------------------------------------------

_vault_instance: Optional[ContentVault] = None


def get_vault() -> ContentVault:
    """Return the module-level ContentVault singleton."""
    global _vault_instance
    if _vault_instance is None:
        _vault_instance = ContentVault()
    return _vault_instance


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _dict_to_item(d: dict) -> ContentItem:
    return ContentItem(
        item_id=d["item_id"],
        file_path=d["file_path"],
        file_type=d["file_type"],
        caption=d.get("caption", ""),
        platform_tags=d.get("platform_tags", []),
        content_tags=d.get("content_tags", []),
        persona_id=d.get("persona_id"),
        source=d.get("source", "manual_upload"),
        created_at_iso=d.get("created_at_iso", ""),
        used_count=d.get("used_count", 0),
        last_used_iso=d.get("last_used_iso"),
    )
