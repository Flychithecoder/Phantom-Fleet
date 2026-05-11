"""
IGPeakTimeAgent — learns optimal posting times per account from engagement history.

Unlike generic "post at 6pm" advice, this agent learns per-account patterns:
    - When does THIS account's audience open Instagram?
    - Which hour has highest engagement rate for THIS account's posts?

Engagement Rate (ER) definition used here:
    ER% = (likes + comments + saves) / followers * 100

Algorithm per account:
    1. Fetch last 30 posts via client.get_user_posts()
    2. For each post: record (hour_local, er_pct, day_of_week)
    3. Group by hour (0–23): compute mean ER per hour
    4. Identify top 3 hours (peak windows)
    5. Assign confidence: low (<10 posts), medium (10–30), high (>30)
    6. Store HourlyEngagementProfile to sidecar

Schedule update:
    - Shifts the account's DailySchedule peak slots to learned hours
    - NEVER modifies quiet hour slots: 2am–6am always protected (hours 2–5 inclusive)
    - Jitter (±30 min) is always recommended alongside any peak hour

Detection-hardening notes (CLAUDE.md 20K account thought experiment):
    - Per-account learned peaks mean 20K accounts spread across many different
      hours — no fleet-wide peak cluster at a single hour.
    - Default peaks (9, 12, 19) are used only for low-confidence accounts
      so they don't all pile into the same slots while accumulating data.
    - Timing updates go through post_time_jitter_seconds() at execution time
      so the actual posting second varies even within the learned hour.
    - Quiet hours (2–5am) are always protected regardless of what the engagement
      data says. Even if a creator's account happens to get high ER on posts
      made at 3am (edge case), we never post at that hour — it's a strong
      bot signal to IG's classifier.

FleetPeakReport:
    - divergent_accounts = accounts where none of their top 3 hours appear
      in common_peak_hours. These are worth reviewing — they may represent
      accounts in unusual timezones or with unusual audience demographics.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from ...core.human_post_behavior import post_time_jitter_seconds

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUIET_HOURS: frozenset[int] = frozenset(range(2, 6))   # 2, 3, 4, 5 — never post here
DEFAULT_PEAK_HOURS: list[int] = [9, 12, 19]             # generic fallback
LOW_CONFIDENCE_MAX_POSTS: int = 10
MEDIUM_CONFIDENCE_MAX_POSTS: int = 30
TOP_N_PEAKS: int = 3                                     # track top 3 hours
FLEET_COMMON_PCT_THRESHOLD: float = 0.50                 # >50% of fleet shares this hour

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PostRecord:
    """Single post engagement snapshot."""

    post_id: str
    account_id: str
    hour_local: int         # 0–23, in account's claimed local timezone
    day_of_week: int        # 0=Monday … 6=Sunday
    er_pct: float           # engagement rate %
    posted_at_iso: str


@dataclass
class HourlyEngagementProfile:
    """Per-account hourly engagement profile, derived from post history."""

    account_id: str
    hour_scores: dict[int, float]   # hour 0–23 → mean ER%
    peak_hours: list[int]           # top TOP_N_PEAKS hours by score
    data_points: int                # number of posts used to build this
    last_updated_iso: str
    confidence: str                 # "low" | "medium" | "high"

    def __post_init__(self) -> None:
        if self.confidence not in {"low", "medium", "high"}:
            raise ValueError(
                f"confidence must be 'low', 'medium', or 'high'; got {self.confidence!r}"
            )
        if any(h in QUIET_HOURS for h in self.peak_hours):
            raise ValueError(
                f"peak_hours must not include quiet hours {QUIET_HOURS}; "
                f"got {self.peak_hours}"
            )


@dataclass
class ScheduleRecommendation:
    """Recommended posting slots for one account."""

    account_id: str
    recommended_slots: list[tuple[int, int]]    # (hour, day_of_week) — day_of_week None = any
    jitter_seconds: int                          # from post_time_jitter_seconds()
    confidence: str
    note: str = ""


@dataclass
class FleetPeakReport:
    """Fleet-wide summary of peak time analysis."""

    analysis_date: str
    accounts_analyzed: int
    common_peak_hours: list[int]        # hours that are peak for >50% of fleet
    divergent_accounts: list[str]       # accounts with unusual peak patterns
    schedule_updates_applied: int
    avg_confidence: str                 # majority label across fleet


# ---------------------------------------------------------------------------
# Core agent
# ---------------------------------------------------------------------------


class IGPeakTimeAgent:
    """
    Learns optimal posting times from each account's engagement history.

    Key distinction from IGContentScheduler: the scheduler assigns posts to
    generic peak windows (9–12am / 6–9pm). This agent learns whether an
    individual account's followers actually engage at those hours or at some
    different time.

    Usage:
        agent = IGPeakTimeAgent()

        # Build a profile from post records (already fetched by caller):
        profile = agent.analyze_posting_history(
            account_id="acc_001",
            post_records=post_records,
        )

        # Get schedule recommendation:
        rec = agent.recommend_schedule(profile)

        # Apply to scheduler config:
        updated_slots = agent.update_daily_schedule(
            profile=profile,
            existing_slots=existing_time_slots,
        )

        # Fleet report:
        report = agent.build_fleet_report(profiles, date_iso="2026-04-11")
    """

    # ------------------------------------------------------------------
    # Profile analysis
    # ------------------------------------------------------------------

    def analyze_posting_history(
        self,
        account_id: str,
        post_records: list[PostRecord],
    ) -> HourlyEngagementProfile:
        """
        Build an HourlyEngagementProfile from a list of post records.

        Groups posts by posting hour, computes mean ER per hour, identifies
        top peaks, and assigns a confidence level based on data volume.

        Quiet hours (2–5am) are excluded from peak selection regardless of
        measured ER (even high ER at quiet hours is artefactual / bot signal).

        Args:
            account_id:    Internal account identifier.
            post_records:  List of PostRecord objects for this account.

        Returns:
            HourlyEngagementProfile with hour_scores, peak_hours, confidence.
        """
        # Group ER values by hour
        by_hour: dict[int, list[float]] = {h: [] for h in range(24)}
        for rec in post_records:
            if rec.account_id != account_id:
                continue
            h = rec.hour_local
            if 0 <= h <= 23:
                by_hour[h].append(rec.er_pct)

        # Compute mean ER per hour (0.0 for hours with no data)
        hour_scores: dict[int, float] = {}
        for h in range(24):
            values = by_hour[h]
            hour_scores[h] = mean(values) if values else 0.0

        data_points = sum(len(v) for v in by_hour.values())
        confidence = _confidence_label(data_points)

        # Select top peaks, excluding quiet hours
        eligible_hours = [h for h in range(24) if h not in QUIET_HOURS]
        eligible_hours.sort(key=lambda h: hour_scores[h], reverse=True)
        peak_hours = eligible_hours[:TOP_N_PEAKS]

        # Stable sort by hour number within ties for determinism
        peak_hours.sort()

        now_iso = datetime.now(timezone.utc).isoformat()

        profile = HourlyEngagementProfile(
            account_id=account_id,
            hour_scores=hour_scores,
            peak_hours=peak_hours,
            data_points=data_points,
            last_updated_iso=now_iso,
            confidence=confidence,
        )

        log.info(
            "[%s] peak_time profile: confidence=%s, peaks=%s, data_points=%d",
            account_id, confidence, peak_hours, data_points,
        )
        return profile

    # ------------------------------------------------------------------
    # Schedule recommendation
    # ------------------------------------------------------------------

    def recommend_schedule(
        self,
        profile: HourlyEngagementProfile,
    ) -> ScheduleRecommendation:
        """
        Return recommended posting times for an account.

        Confidence routing:
            "low"    → use DEFAULT_PEAK_HOURS (not enough data to trust)
            "medium" → use learned peak_hours
            "high"   → use learned peak_hours

        Jitter of ±30 min is always included in the recommendation and
        applied via post_time_jitter_seconds() at execution time.

        Returns ScheduleRecommendation with (hour, day_of_week) tuples.
        day_of_week is None in these tuples (None = applicable any day);
        callers that care about day-specific slots can layer that on top.
        """
        if profile.confidence == "low":
            chosen_hours = DEFAULT_PEAK_HOURS
            note = (
                f"Using default peak hours (< {LOW_CONFIDENCE_MAX_POSTS} posts). "
                "Collect more data for account-specific peaks."
            )
        else:
            chosen_hours = profile.peak_hours
            note = (
                f"Learned peak hours from {profile.data_points} posts. "
                "Confidence: " + profile.confidence + "."
            )

        # Never recommend quiet hours regardless of what analysis says
        safe_hours = [h for h in chosen_hours if h not in QUIET_HOURS]
        if not safe_hours:
            safe_hours = [h for h in DEFAULT_PEAK_HOURS if h not in QUIET_HOURS]
            note += " (All learned peaks were quiet hours — fell back to defaults.)"

        jitter = post_time_jitter_seconds()
        slots: list[tuple[int, int]] = [
            (h, -1) for h in safe_hours      # -1 = any day of week
        ]

        return ScheduleRecommendation(
            account_id=profile.account_id,
            recommended_slots=slots,
            jitter_seconds=jitter,
            confidence=profile.confidence,
            note=note,
        )

    # ------------------------------------------------------------------
    # Schedule update (returns updated slot list for the caller's scheduler)
    # ------------------------------------------------------------------

    def update_daily_schedule(
        self,
        profile: HourlyEngagementProfile,
        existing_slots: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Update a list of DailySchedule slot dicts to reflect learned peak hours.

        Slot dicts are expected to have at least:
            {"hour": int, "type": str, ...}

        Rules:
            - Slots with type "quiet" are NEVER modified.
            - Slots in QUIET_HOURS (2–5am) are NEVER modified, even if type != "quiet".
            - Slots with type "peak" are reassigned to the learned peak hours
              (round-robin if more peak slots than learned peaks).
            - If confidence is "low", no changes are made (not enough data).

        Returns the updated list of slot dicts (new list, originals unchanged).
        """
        if profile.confidence == "low":
            log.debug(
                "[%s] update_daily_schedule: confidence=low, skipping update",
                profile.account_id,
            )
            return list(existing_slots)

        updated: list[dict[str, Any]] = []
        peak_slot_index = 0

        for slot in existing_slots:
            hour = slot.get("hour", -1)
            slot_type = slot.get("type", "")

            # Never touch quiet hours or quiet-typed slots
            if hour in QUIET_HOURS or slot_type == "quiet":
                updated.append(dict(slot))
                continue

            if slot_type == "peak":
                # Rotate through learned peaks
                if profile.peak_hours:
                    new_hour = profile.peak_hours[peak_slot_index % len(profile.peak_hours)]
                    peak_slot_index += 1
                    new_slot = dict(slot)
                    new_slot["hour"] = new_hour
                    updated.append(new_slot)
                    log.debug(
                        "[%s] shifted peak slot from h=%d to h=%d",
                        profile.account_id, hour, new_hour,
                    )
                else:
                    updated.append(dict(slot))
            else:
                # Non-peak, non-quiet slot: leave as-is
                updated.append(dict(slot))

        return updated

    # ------------------------------------------------------------------
    # Fleet report
    # ------------------------------------------------------------------

    def build_fleet_report(
        self,
        profiles: list[HourlyEngagementProfile],
        date_iso: str,
        schedule_updates_applied: int = 0,
    ) -> FleetPeakReport:
        """
        Aggregate a list of per-account profiles into a fleet-level report.

        common_peak_hours: hours that appear in the peak_hours of >50% of accounts.
        divergent_accounts: accounts whose top-3 peaks have NO overlap with
                            common_peak_hours.

        Args:
            profiles:                   List of HourlyEngagementProfile objects.
            date_iso:                   Analysis date (YYYY-MM-DD).
            schedule_updates_applied:   Count of schedule updates already applied.

        Returns:
            FleetPeakReport.
        """
        if not profiles:
            return FleetPeakReport(
                analysis_date=date_iso,
                accounts_analyzed=0,
                common_peak_hours=[],
                divergent_accounts=[],
                schedule_updates_applied=schedule_updates_applied,
                avg_confidence="low",
            )

        n = len(profiles)

        # Count how many accounts have each hour in their peak list
        hour_count: dict[int, int] = {h: 0 for h in range(24)}
        for prof in profiles:
            for h in prof.peak_hours:
                hour_count[h] += 1

        common_peak_hours = [
            h for h, count in hour_count.items()
            if count / n >= FLEET_COMMON_PCT_THRESHOLD
        ]
        common_peak_hours.sort()

        # Divergent = no peak hours in common with the fleet's common hours
        divergent_accounts: list[str] = []
        if common_peak_hours:
            for prof in profiles:
                if not any(h in common_peak_hours for h in prof.peak_hours):
                    divergent_accounts.append(prof.account_id)

        # Average confidence: majority vote
        confidence_counts = {"low": 0, "medium": 0, "high": 0}
        for prof in profiles:
            confidence_counts[prof.confidence] += 1
        avg_confidence = max(confidence_counts, key=confidence_counts.__getitem__)

        report = FleetPeakReport(
            analysis_date=date_iso,
            accounts_analyzed=n,
            common_peak_hours=common_peak_hours,
            divergent_accounts=divergent_accounts,
            schedule_updates_applied=schedule_updates_applied,
            avg_confidence=avg_confidence,
        )

        log.info(
            "FleetPeakReport: %d accounts, common_peaks=%s, divergent=%d, avg_conf=%s",
            n, common_peak_hours, len(divergent_accounts), avg_confidence,
        )
        return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _confidence_label(data_points: int) -> str:
    """
    Convert post count to confidence label.

    Thresholds:
        < 10   → "low"
        10–30  → "medium"
        > 30   → "high"
    """
    if data_points < LOW_CONFIDENCE_MAX_POSTS:
        return "low"
    if data_points <= MEDIUM_CONFIDENCE_MAX_POSTS:
        return "medium"
    return "high"
