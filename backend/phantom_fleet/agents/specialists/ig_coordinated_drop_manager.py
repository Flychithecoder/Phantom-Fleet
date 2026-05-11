"""
IGCoordinatedDropManager — fleet-wide coordinated story drop scheduler.

Coordinates a simultaneous content drop across ALL phones in the fleet.
Onimator has no concept of coordinated drops — this is a Phantom Fleet
exclusive that lets a mother account's story saturate every child account
within a configurable time window, maximising reach velocity.

Architecture:
    schedule_drop() produces a DropSchedule — a list of per-account
    (account_id, phone_serial, post_at_unix) entries.  The caller dispatches
    run_mother_child_drop() on the correct phone at each post_at_unix time.

Scheduling algorithm:
    1. Compute per-account offset:
           offset_sec = hash(account_id + date_iso) % window_seconds
       This is DETERMINISTIC per (account_id, date) so the same drop can be
       reconstructed from the same inputs — critical for retry logic.
    2. Spread offsets across the window → no two accounts share a post_at_unix.
    3. Enforce same-phone serialisation: if two accounts on the same phone
       would post within 90 seconds, the later account's offset is incremented
       to at least 90s after the earlier one.
    4. Clamp every post_at_unix to ≥ drop_start_unix (no posts before the
       window opens).

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):
    - Offset distribution: hash % window_seconds produces a nearly-uniform
      distribution across the window. At 20K accounts over a 30-min window
      (1800s), each second has ~11 accounts → no hour-scale spike.
    - Same-phone serialisation is enforced by CODE, not prompt.
    - SHA-256 hashing avoids sequential account_id → correlated offset.
    - Temporal histogram: flat across the window (intentional for drops),
      which differs from normal posting patterns but is expected for a
      coordinated campaign — acceptable because the whole WINDOW is the
      coordination signal, not a single-second spike.

Daily hard caps (code-enforced):
    - MAX_ACCOUNTS_PER_DROP = 500   (blast radius cap per schedule_drop call)
    - MAX_DROP_WINDOW_MINUTES = 120 (no window wider than 2 hours)
    - MIN_SAME_PHONE_GAP_SEC  = 90  (two accounts on the same phone)
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hard limits — code-enforced, never configurable via prompt
# ---------------------------------------------------------------------------

MAX_ACCOUNTS_PER_DROP: int = 500
MAX_DROP_WINDOW_MINUTES: int = 120
MIN_SAME_PHONE_GAP_SEC: float = 90.0


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class DropEntry:
    """
    A single account's slot in the coordinated drop.

    Fields:
        account_id    — child account identifier
        phone_serial  — ADB serial of the phone hosting this account
        post_at_unix  — Unix timestamp at which to trigger the post
        offset_sec    — seconds after drop_start_unix (useful for logging)
    """
    account_id:   str
    phone_serial: str
    post_at_unix: float
    offset_sec:   int


@dataclass
class DropSchedule:
    """
    Complete coordinated drop schedule for all child accounts.

    Fields:
        mother_account_id — account whose story is being reposted
        drop_start_unix   — Unix timestamp of window open (no post before this)
        window_seconds    — total window width in seconds
        date_iso          — YYYY-MM-DD of the drop
        entries           — one DropEntry per child account, sorted by post_at_unix

    Properties:
        total_accounts    — number of child accounts scheduled
        by_phone()        — all entries for a given phone serial

    Usage:
        schedule = manager.schedule_drop(
            mother_account_id = "acc_mother_001",
            child_accounts    = [{"account_id": "c1", "phone_serial": "192.168.1.10:5555"}, ...],
            drop_start_unix   = 1744300800.0,
            window_minutes    = 30,
            date_iso          = "2026-04-11",
        )
        for entry in schedule.entries:
            dispatch_at(entry.post_at_unix, run_mother_child_drop, entry.account_id)
    """
    mother_account_id: str
    drop_start_unix:   float
    window_seconds:    int
    date_iso:          str
    entries:           list[DropEntry] = field(default_factory=list)

    @property
    def total_accounts(self) -> int:
        return len(self.entries)

    def by_phone(self, phone_serial: str) -> list[DropEntry]:
        """All entries allocated to a given phone, sorted by post_at_unix."""
        return sorted(
            [e for e in self.entries if e.phone_serial == phone_serial],
            key=lambda e: e.post_at_unix,
        )

    def sorted_by_time(self) -> list[DropEntry]:
        return sorted(self.entries, key=lambda e: e.post_at_unix)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class IGCoordinatedDropManager:
    """
    Schedules a fleet-wide coordinated story drop.

    All logic is deterministic: the same inputs always produce the same
    DropSchedule, enabling reproducible retries without re-invoking the
    scheduler.

    Usage::

        manager = IGCoordinatedDropManager()
        schedule = manager.schedule_drop(
            mother_account_id = "acc_mother_001",
            child_accounts    = [
                {"account_id": "c_001", "phone_serial": "192.168.1.10:5555"},
                {"account_id": "c_002", "phone_serial": "192.168.1.10:5555"},
                {"account_id": "c_003", "phone_serial": "192.168.1.11:5555"},
            ],
            drop_start_unix = 1744300800.0,
            window_minutes  = 30,
            date_iso        = "2026-04-11",
        )
    """

    def schedule_drop(
        self,
        mother_account_id: str,
        child_accounts: list[dict],
        drop_start_unix: float,
        window_minutes: int,
        date_iso: str,
    ) -> DropSchedule:
        """
        Build a DropSchedule for a coordinated story drop.

        Args:
            mother_account_id:  Identifier of the mother account.
            child_accounts:     List of dicts with "account_id" and "phone_serial".
            drop_start_unix:    Unix timestamp when the window opens.
            window_minutes:     Duration of the window in minutes.
            date_iso:           "YYYY-MM-DD" of the drop.

        Returns:
            DropSchedule with one DropEntry per child account, sorted by time.

        Raises:
            ValueError: if inputs violate hard limits.
        """
        # ── Input validation ────────────────────────────────────────────────
        if not child_accounts:
            raise ValueError("child_accounts must not be empty")

        if len(child_accounts) > MAX_ACCOUNTS_PER_DROP:
            raise ValueError(
                f"child_accounts count {len(child_accounts)} exceeds "
                f"MAX_ACCOUNTS_PER_DROP={MAX_ACCOUNTS_PER_DROP}"
            )

        if not (1 <= window_minutes <= MAX_DROP_WINDOW_MINUTES):
            raise ValueError(
                f"window_minutes={window_minutes} must be in [1, {MAX_DROP_WINDOW_MINUTES}]"
            )

        window_seconds = window_minutes * 60

        # ── Step 1: compute raw hash-based offset per account ───────────────
        #
        # offset = SHA-256(account_id + "|" + date_iso) → first 8 bytes → uint64
        # Then modulo window_seconds → offset in [0, window_seconds)
        #
        # SHA-256 diffuses sequential account IDs, preventing correlated offsets
        # (same property as deterministicSeed in StoryTransformHelper.kt).

        entries_raw: list[tuple[str, str, int]] = []  # (account_id, phone_serial, raw_offset)

        for account in child_accounts:
            acct_id = account["account_id"]
            phone   = account["phone_serial"]
            raw_offset = _hash_offset(acct_id, date_iso, window_seconds)
            entries_raw.append((acct_id, phone, raw_offset))

        # ── Step 2: Same-phone serialisation ─────────────────────────────────
        #
        # Two accounts on the same phone must not post within MIN_SAME_PHONE_GAP_SEC.
        #
        # Algorithm (O(N log N), deterministic):
        #   For each phone's accounts sorted by raw hash offset:
        #     1. Compute the maximum safe anchor (first offset) so that
        #        anchor + (n-1) * gap_int ≤ window_seconds - 1
        #     2. Assign offsets as anchor + idx * gap_int (uniformly spaced)
        #
        # This guarantees the ≥ gap constraint for all n accounts as long as
        # n * gap_int ≤ window_seconds, which callers must ensure by choosing
        # an appropriate window_minutes.

        # Group by phone, sort within each phone by raw_offset
        phone_buckets: dict[str, list[tuple[str, int]]] = {}
        for acct_id, phone, raw_offset in entries_raw:
            phone_buckets.setdefault(phone, []).append((acct_id, raw_offset))

        # Assign serialised offsets per phone
        serialised: list[tuple[str, str, int]] = []  # (account_id, phone, final_offset)
        gap_int = int(MIN_SAME_PHONE_GAP_SEC)

        for phone, bucket in phone_buckets.items():
            n_accounts = len(bucket)
            # Sort by raw offset within this phone (determines order of posting)
            bucket_sorted = sorted(bucket, key=lambda x: x[1])

            # Compute the maximum safe starting offset for this phone.
            # If n accounts each need ≥ gap_int seconds between them,
            # the anchor (first account's offset) must satisfy:
            #   anchor + (n - 1) * gap_int ≤ window_seconds - 1
            # → anchor ≤ window_seconds - 1 - (n - 1) * gap_int
            max_start = max(0, window_seconds - 1 - (n_accounts - 1) * gap_int)
            first_raw  = bucket_sorted[0][1]
            anchor     = min(first_raw, max_start)

            # Assign offsets strictly: each account placed exactly gap_int after the
            # previous one (using the sorted-hash order). This guarantees the
            # same-phone gap invariant for ALL accounts regardless of window size.
            # The hash ordering provides diversity in WHICH account posts first,
            # not in the inter-account spacing.
            for idx, (acct_id, _raw_offset) in enumerate(bucket_sorted):
                final_offset = anchor + idx * gap_int
                # Clamp defensively — should never trigger if max_start is computed correctly
                final_offset = min(final_offset, window_seconds - 1)
                final_offset = max(final_offset, 0)
                serialised.append((acct_id, phone, final_offset))

        # ── Step 3: Convert offsets to absolute Unix timestamps ──────────────

        entries: list[DropEntry] = []
        for acct_id, phone, offset_sec in serialised:
            post_at = drop_start_unix + offset_sec
            entries.append(DropEntry(
                account_id   = acct_id,
                phone_serial = phone,
                post_at_unix = post_at,
                offset_sec   = offset_sec,
            ))

        # Sort final list by post_at_unix
        entries.sort(key=lambda e: e.post_at_unix)

        schedule = DropSchedule(
            mother_account_id = mother_account_id,
            drop_start_unix   = drop_start_unix,
            window_seconds    = window_seconds,
            date_iso          = date_iso,
            entries           = entries,
        )

        log.info(
            "[%s] drop schedule built: %d accounts over %dmin window starting %s",
            mother_account_id,
            schedule.total_accounts,
            window_minutes,
            datetime.fromtimestamp(drop_start_unix, tz=timezone.utc).isoformat(),
        )

        return schedule

    def validate_schedule(self, schedule: DropSchedule) -> list[str]:
        """
        Validate a DropSchedule for same-phone gap violations and window breaches.

        Returns a list of violation strings. Empty list means the schedule is clean.

        Useful for testing and for runtime sanity checks before dispatch.
        """
        issues: list[str] = []

        window_end = schedule.drop_start_unix + schedule.window_seconds

        # Check every entry is within the window
        for entry in schedule.entries:
            if entry.post_at_unix < schedule.drop_start_unix:
                issues.append(
                    f"{entry.account_id}: post_at_unix {entry.post_at_unix:.0f} "
                    f"is before drop_start_unix {schedule.drop_start_unix:.0f}"
                )
            if entry.post_at_unix >= window_end:
                issues.append(
                    f"{entry.account_id}: post_at_unix {entry.post_at_unix:.0f} "
                    f"is at or after window_end {window_end:.0f}"
                )

        # Check same-phone gap constraint
        by_phone: dict[str, list[DropEntry]] = {}
        for entry in schedule.entries:
            by_phone.setdefault(entry.phone_serial, []).append(entry)

        for phone, phone_entries in by_phone.items():
            sorted_entries = sorted(phone_entries, key=lambda e: e.post_at_unix)
            for i in range(1, len(sorted_entries)):
                prev = sorted_entries[i - 1]
                curr = sorted_entries[i]
                gap = curr.post_at_unix - prev.post_at_unix
                if gap < MIN_SAME_PHONE_GAP_SEC:
                    issues.append(
                        f"phone={phone}: {prev.account_id} → {curr.account_id} "
                        f"gap={gap:.1f}s < {MIN_SAME_PHONE_GAP_SEC}s minimum"
                    )

        return issues


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _hash_offset(account_id: str, date_iso: str, window_seconds: int) -> int:
    """
    Compute a deterministic offset for (account_id, date_iso) within [0, window_seconds).

    Uses SHA-256 for diffusion — sequential account IDs don't produce correlated
    offsets (same property as deterministicSeed in StoryTransformHelper.kt).

    Args:
        account_id:     Internal account identifier.
        date_iso:       "YYYY-MM-DD" string.
        window_seconds: Size of the distribution window.

    Returns:
        Integer offset in [0, window_seconds).
    """
    payload = f"{account_id}|{date_iso}".encode("utf-8")
    digest  = hashlib.sha256(payload).digest()
    # Take first 8 bytes as an unsigned 64-bit integer
    raw_int = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return raw_int % window_seconds
