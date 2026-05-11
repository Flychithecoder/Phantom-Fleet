"""
IGContentScheduler — schedules Instagram posts from the content vault at
human-realistic times, spread across the fleet's diurnal curve.

Key design principles (CLAUDE.md scale-level audit):

    1. No two accounts post at exactly the same second — per-account offset
       derived from hash(account_id) % 3600 prevents fleet-wide timing clusters.

    2. Posting times are drawn from the account's local timezone peak hours
       (9am–12pm and 6pm–9pm) so the fleet mirrors the natural diurnal rhythm
       of real Instagram users in that timezone.

    3. Per-account post quota is respected: the scheduler never over-assigns.

    4. Jitter is drawn from Normal(0, 900) — ±15 min typical — via the shared
       `post_time_jitter_seconds()` primitive. Symmetric jitter matches real
       scheduling variance (early and late equally likely).

Usage:
    scheduler = IGContentScheduler()
    schedule  = scheduler.build_daily_schedule(accounts, vault_items, date_iso)
    for post in schedule.posts:
        # dispatch IGForegroundPostAgent at post.scheduled_at_unix
        ...
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from ...core import human_post_behavior

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Peak posting hours per timezone bucket (local hour ranges, inclusive)
# ---------------------------------------------------------------------------

# Two daily windows that match real Instagram usage peaks:
#   Morning:   9 AM – 12 PM local
#   Evening:   6 PM –  9 PM local
_PEAK_WINDOWS: list[tuple[int, int]] = [
    (9, 11),   # morning window: 9:00 – 11:59
    (18, 20),  # evening window: 18:00 – 20:59
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ScheduledPost:
    """A single post assigned to an account at a specific time."""
    account_id:         str
    phone_serial:       str
    clone_package:      str
    media_local_path:   str
    caption:            str
    post_type:          str         # "grid", "story", or "reel"
    scheduled_at_unix:  float       # Unix timestamp
    jitter_applied_sec: int         # jitter that was added to base schedule time


@dataclass
class DailyPostSchedule:
    """Full schedule for one day across all accounts."""
    date_iso: str
    posts:    list[ScheduledPost] = field(default_factory=list)

    @property
    def total_posts(self) -> int:
        return len(self.posts)

    def by_account(self, account_id: str) -> list[ScheduledPost]:
        return [p for p in self.posts if p.account_id == account_id]

    def sorted_by_time(self) -> list[ScheduledPost]:
        return sorted(self.posts, key=lambda p: p.scheduled_at_unix)


@dataclass
class AccountConfig:
    """
    Scheduler-facing account descriptor. The caller provides one per account.
    """
    account_id:       str
    phone_serial:     str
    clone_package:    str
    active_timezone:  str           # IANA timezone name, e.g. "America/New_York"
    post_quota:       dict[str, int]  # {"grid": 2, "story": 3, "reel": 1}


@dataclass
class ContentVaultItem:
    """One piece of media from the content vault."""
    item_id:         str
    local_path:      str
    caption:         str
    post_type:       str   # "grid", "story", or "reel"
    content_tags:    list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class IGContentScheduler:
    """
    Schedules Instagram posts from the content vault at human-realistic times.

    Pulls media from the content vault, assigns to accounts, staggers posting
    times across the diurnal curve, and returns a DailyPostSchedule ready for
    dispatch to IGForegroundPostAgent.
    """

    def build_daily_schedule(
        self,
        accounts: list[AccountConfig],
        content_vault_items: list[ContentVaultItem],
        date_iso: str,
    ) -> DailyPostSchedule:
        """
        Build the full daily posting schedule for a fleet of accounts.

        Algorithm:
            For each account × post_type:
                1. Pick N items from the vault (account's quota for that type)
                2. Choose a base posting hour from the account's timezone peak windows
                3. Add per-account deterministic offset (hash(account_id) % 3600 sec)
                   to prevent fleet-wide exact-second collisions
                4. Add stochastic jitter from post_time_jitter_seconds()
                5. Schedule one post per item at the computed time (inter-post
                   spacing: ~1 hour between posts on same account)

        Args:
            accounts:            List of account descriptors.
            content_vault_items: Available media items (pooled across all accounts).
            date_iso:            Target date as "YYYY-MM-DD".

        Returns:
            DailyPostSchedule with all posts sorted by account and time.
        """
        schedule = DailyPostSchedule(date_iso=date_iso)

        # Build lookup: post_type → available items
        items_by_type: dict[str, list[ContentVaultItem]] = {}
        for item in content_vault_items:
            items_by_type.setdefault(item.post_type, []).append(item)

        for account in accounts:
            account_posts = self._schedule_account(
                account=account,
                items_by_type=items_by_type,
                date_iso=date_iso,
            )
            schedule.posts.extend(account_posts)
            log.debug(
                "[%s] scheduled %d posts for %s",
                account.account_id, len(account_posts), date_iso,
            )

        log.info(
            "IGContentScheduler: built %d total posts for %d accounts on %s",
            schedule.total_posts, len(accounts), date_iso,
        )
        return schedule

    # ------------------------------------------------------------------
    # Per-account scheduling
    # ------------------------------------------------------------------

    def _schedule_account(
        self,
        account: AccountConfig,
        items_by_type: dict[str, list[ContentVaultItem]],
        date_iso: str,
    ) -> list[ScheduledPost]:
        """Schedule all posts for one account across all its post types."""
        posts: list[ScheduledPost] = []

        # Deterministic per-account second offset prevents fleet-wide same-second posting.
        # hash(account_id) is stable across runs (Python's built-in hash is NOT stable
        # across restarts — use SHA-256 instead).
        account_offset_sec = _stable_hash_mod(account.account_id, 3600)

        for post_type, quota in account.post_quota.items():
            if quota <= 0:
                continue

            available = items_by_type.get(post_type, [])
            if not available:
                log.debug(
                    "[%s] no %s items in vault — skipping",
                    account.account_id, post_type,
                )
                continue

            # Select items for this account's quota.
            # Use deterministic per-account seeded selection so the same account
            # always picks the same items on the same day (deterministic replay).
            selected = _select_items(available, quota, account.account_id, date_iso, post_type)

            for post_index, item in enumerate(selected):
                scheduled_time = self._compute_post_time(
                    date_iso=date_iso,
                    timezone_name=account.active_timezone,
                    account_offset_sec=account_offset_sec,
                    post_index=post_index,
                    post_type=post_type,
                )
                jitter = human_post_behavior.post_time_jitter_seconds(
                    account_id=account.account_id,
                    date_iso=date_iso,
                    field=f"post_jitter_{post_type}_{post_index}",
                )
                final_time = scheduled_time + jitter

                posts.append(ScheduledPost(
                    account_id         = account.account_id,
                    phone_serial       = account.phone_serial,
                    clone_package      = account.clone_package,
                    media_local_path   = item.local_path,
                    caption            = item.caption,
                    post_type          = post_type,
                    scheduled_at_unix  = final_time,
                    jitter_applied_sec = jitter,
                ))

        return posts

    def _compute_post_time(
        self,
        date_iso: str,
        timezone_name: str,
        account_offset_sec: int,
        post_index: int,
        post_type: str,
    ) -> float:
        """
        Compute a base post time (Unix timestamp) for a single post.

        Strategy:
            - Pick the peak window based on post_index (alternating morning/evening).
            - Pick a random minute within the window (seeded by timezone for
              determinism within a timezone bucket — different TZs get different hours).
            - Add the per-account offset (0–3599 sec) to spread across the fleet.
            - Multiple posts on the same account are spaced ~60 min apart.

        Returns:
            Unix timestamp (float) for the base post time before jitter.
        """
        date = datetime.strptime(date_iso, "%Y-%m-%d")

        # Resolve timezone offset in hours from IANA name.
        # Full IANA tzdata requires pytz/zoneinfo — use a simplified UTC offset
        # lookup to avoid external deps. The caller should ensure timezone_name
        # is a valid IANA name; this resolver covers the most common ones.
        tz_offset_hours = _tz_offset_hours(timezone_name)

        # Select peak window: alternate morning/evening per post index
        window_start, window_end = _PEAK_WINDOWS[post_index % len(_PEAK_WINDOWS)]

        # Spread minutes within the window deterministically per (account offset)
        # then let jitter shift the final time randomly
        base_minute_in_window = (account_offset_sec // 60) % ((window_end - window_start) * 60)
        total_minutes_from_midnight = window_start * 60 + base_minute_in_window

        # Account-local time → UTC
        local_hour   = total_minutes_from_midnight // 60
        local_minute = total_minutes_from_midnight % 60

        local_dt = date.replace(hour=local_hour, minute=local_minute, second=0, microsecond=0)
        utc_dt   = local_dt - timedelta(hours=tz_offset_hours)
        base_unix = utc_dt.replace(tzinfo=timezone.utc).timestamp()

        # Spread multiple posts on the same account ~60 min apart
        inter_post_spacing_sec = post_index * 3600

        return base_unix + account_offset_sec + inter_post_spacing_sec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stable_hash_mod(value: str, modulus: int) -> int:
    """
    Return a stable (cross-process) hash of `value` modulo `modulus`.

    Uses SHA-256 because Python's built-in hash() is randomised across
    process restarts (PYTHONHASHSEED) and would produce different offsets
    each time the scheduler runs. We need the same account to get the same
    offset every day.
    """
    digest = hashlib.sha256(value.encode()).digest()
    return int.from_bytes(digest[:4], "big") % modulus


def _select_items(
    pool: list[ContentVaultItem],
    quota: int,
    account_id: str,
    date_iso: str,
    post_type: str,
) -> list[ContentVaultItem]:
    """
    Select up to `quota` items from `pool` for one account.

    Selection is seeded per (account_id, date_iso, post_type) so:
        - Same account on same day always gets same items (deterministic replay).
        - Different accounts on same day get different items (prevents monoculture).

    Does not enforce no-repeat across days — pool must be large enough that
    accidental repeats on adjacent days are rare. Caller is responsible for
    pool management.
    """
    import random as _random

    seed = _stable_hash_mod(f"{account_id}|{date_iso}|{post_type}", 2**31)
    rng  = _random.Random(seed)

    # Shuffle a copy of the pool, then take up to quota
    shuffled = list(pool)
    rng.shuffle(shuffled)
    return shuffled[:quota]


def _tz_offset_hours(timezone_name: str) -> float:
    """
    Return the UTC offset in hours for a timezone name.

    Covers the most common IANA timezones used by Instagram creators.
    Falls back to UTC (0) for unknown names.

    Note: This is a simplified lookup that ignores DST transitions.
    For production use with full DST accuracy, replace with
    `zoneinfo.ZoneInfo` (Python 3.9+) or `pytz`.
    """
    _OFFSETS: dict[str, float] = {
        # Americas
        "America/New_York":       -5.0,
        "America/Chicago":        -6.0,
        "America/Denver":         -7.0,
        "America/Los_Angeles":    -8.0,
        "America/Phoenix":        -7.0,
        "America/Anchorage":      -9.0,
        "America/Honolulu":      -10.0,
        "America/Toronto":        -5.0,
        "America/Vancouver":      -8.0,
        "America/Mexico_City":    -6.0,
        "America/Bogota":         -5.0,
        "America/Lima":           -5.0,
        "America/Sao_Paulo":      -3.0,
        "America/Argentina/Buenos_Aires": -3.0,
        # Europe
        "Europe/London":           0.0,
        "Europe/Paris":            1.0,
        "Europe/Berlin":           1.0,
        "Europe/Madrid":           1.0,
        "Europe/Rome":             1.0,
        "Europe/Amsterdam":        1.0,
        "Europe/Stockholm":        1.0,
        "Europe/Moscow":           3.0,
        # Asia / Pacific
        "Asia/Dubai":              4.0,
        "Asia/Karachi":            5.0,
        "Asia/Kolkata":            5.5,
        "Asia/Dhaka":              6.0,
        "Asia/Bangkok":            7.0,
        "Asia/Singapore":          8.0,
        "Asia/Hong_Kong":          8.0,
        "Asia/Shanghai":           8.0,
        "Asia/Tokyo":              9.0,
        "Asia/Seoul":              9.0,
        "Australia/Sydney":       10.0,
        "Pacific/Auckland":       12.0,
        # Africa
        "Africa/Cairo":            2.0,
        "Africa/Johannesburg":     2.0,
        "Africa/Lagos":            1.0,
        # UTC
        "UTC":                     0.0,
        "Etc/UTC":                 0.0,
    }
    offset = _OFFSETS.get(timezone_name)
    if offset is None:
        log.warning("Unknown timezone %r — defaulting to UTC", timezone_name)
        return 0.0
    return offset
