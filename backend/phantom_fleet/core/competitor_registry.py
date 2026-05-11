"""
CompetitorRegistry — persists and manages the list of competitor accounts
to harvest followers from.

Cooldown: a competitor is not re-harvested until at least `cooldown_days`
(default 7) have passed since the last harvest. This prevents the fleet from
hammering a single account's followers endpoint repeatedly.

Storage: JSON file on disk. Simple and portable — no DB dependency for what
is essentially a small config file. Load at startup, save after mutations.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CompetitorEntry:
    """One competitor account tracked for follower harvesting."""
    handle:              str
    user_id:             Optional[str]    # resolved IG numeric ID; None until first harvest
    niche:               str              # "fitness" | "lifestyle" | "nsfw_adjacent" | "of_creator"
    follower_count:      int              # last known follower count (informational)
    last_harvested_iso:  Optional[str]    # ISO date of last harvest, or None
    harvest_count:       int              # total followers harvested from this account


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class CompetitorRegistry:
    """
    Manages the list of competitor accounts to harvest from.

    Operations:
        add()                — register a new competitor
        get_due_for_harvest() — return entries whose cooldown has elapsed
        mark_harvested()     — record a harvest event (updates last_harvested_iso)
        load()               — deserialize from a JSON file
        save()               — serialize to a JSON file
    """

    def __init__(self) -> None:
        self._entries: dict[str, CompetitorEntry] = {}  # handle → entry

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, handle: str, niche: str, follower_count: int = 0) -> CompetitorEntry:
        """
        Register a new competitor. If the handle already exists the existing
        entry is returned unchanged (idempotent — safe to call on every startup).
        """
        handle = handle.lstrip("@").lower()
        if handle not in self._entries:
            entry = CompetitorEntry(
                handle             = handle,
                user_id            = None,
                niche              = niche,
                follower_count     = follower_count,
                last_harvested_iso = None,
                harvest_count      = 0,
            )
            self._entries[handle] = entry
            log.debug("[CompetitorRegistry] Added %s (niche=%s)", handle, niche)
        return self._entries[handle]

    def set_user_id(self, handle: str, user_id: str) -> None:
        """Store the resolved IG numeric user_id for a handle."""
        handle = handle.lstrip("@").lower()
        if handle in self._entries:
            self._entries[handle].user_id = user_id

    def mark_harvested(self, handle: str, count: int) -> None:
        """
        Record that `count` followers were harvested from `handle` today.
        Updates last_harvested_iso to today (UTC) and increments harvest_count.
        """
        handle = handle.lstrip("@").lower()
        if handle not in self._entries:
            log.warning("[CompetitorRegistry] mark_harvested: unknown handle %s", handle)
            return
        entry                     = self._entries[handle]
        entry.last_harvested_iso  = date.today().isoformat()
        entry.harvest_count       += count
        log.debug(
            "[CompetitorRegistry] Marked %s harvested (+%d, total=%d)",
            handle, count, entry.harvest_count,
        )

    def update_follower_count(self, handle: str, follower_count: int) -> None:
        """Update the cached follower count for a competitor."""
        handle = handle.lstrip("@").lower()
        if handle in self._entries:
            self._entries[handle].follower_count = follower_count

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, handle: str) -> Optional[CompetitorEntry]:
        """Return the entry for a handle, or None if not registered."""
        return self._entries.get(handle.lstrip("@").lower())

    def all(self) -> list[CompetitorEntry]:
        """Return all registered competitors, sorted by handle."""
        return sorted(self._entries.values(), key=lambda e: e.handle)

    def get_due_for_harvest(self, cooldown_days: int = 7) -> list[CompetitorEntry]:
        """
        Return competitors whose last_harvested_iso is either None (never
        harvested) or more than `cooldown_days` ago.

        Sorted by (last_harvested_iso ASC, handle ASC) so the oldest-harvested
        accounts are processed first.
        """
        today   = date.today()
        cutoff  = today - timedelta(days=cooldown_days)
        due: list[CompetitorEntry] = []

        for entry in self._entries.values():
            if entry.last_harvested_iso is None:
                due.append(entry)
            else:
                try:
                    last = date.fromisoformat(entry.last_harvested_iso)
                except ValueError:
                    due.append(entry)   # malformed date → treat as never harvested
                    continue
                if last <= cutoff:
                    due.append(entry)

        due.sort(key=lambda e: (e.last_harvested_iso or "0000-00-00", e.handle))
        return due

    def is_due(self, handle: str, cooldown_days: int = 7) -> bool:
        """Return True if the given handle is due for a harvest."""
        entry = self.get(handle)
        if entry is None:
            return False
        due = {e.handle for e in self.get_due_for_harvest(cooldown_days)}
        return entry.handle in due

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, path: str) -> None:
        """
        Deserialize registry from a JSON file.
        Silently creates an empty registry if the file does not exist.
        Existing in-memory entries are REPLACED.
        """
        p = Path(path)
        if not p.exists():
            log.info("[CompetitorRegistry] No registry file at %s — starting empty", path)
            self._entries = {}
            return

        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.error("[CompetitorRegistry] Failed to load %s: %s", path, exc)
            return

        entries: dict[str, CompetitorEntry] = {}
        for item in data.get("competitors", []):
            try:
                entry = CompetitorEntry(
                    handle             = item["handle"],
                    user_id            = item.get("user_id"),
                    niche              = item.get("niche", "unknown"),
                    follower_count     = int(item.get("follower_count", 0)),
                    last_harvested_iso = item.get("last_harvested_iso"),
                    harvest_count      = int(item.get("harvest_count", 0)),
                )
                entries[entry.handle] = entry
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("[CompetitorRegistry] Skipping malformed entry %r: %s", item, exc)

        self._entries = entries
        log.info("[CompetitorRegistry] Loaded %d entries from %s", len(self._entries), path)

    def save(self, path: str) -> None:
        """
        Serialize registry to a JSON file (atomic write via temp file rename).
        Creates parent directories if they don't exist.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "competitors": [asdict(e) for e in self.all()],
        }

        tmp = p.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(p)
            log.info("[CompetitorRegistry] Saved %d entries to %s", len(self._entries), path)
        except OSError as exc:
            log.error("[CompetitorRegistry] Failed to save %s: %s", path, exc)
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return f"CompetitorRegistry({len(self._entries)} entries)"
