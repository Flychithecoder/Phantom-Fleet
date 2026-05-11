"""
BlueSky A/B Test framework — compares engagement strategies across account cohorts.

Primary test: Follow+Like-only (Group A) vs Follow+Like+DM (Group B).

Metric: follow_back_rate = follows_received / follows_sent
        Proxy for "target saw our profile and found it compelling enough
        to reciprocate."  DMs pull the target into conversation before
        they've decided — raising follow-back rate when it works.

Secondary metrics:
    dm_reply_rate        = dm_replies / dms_sent (Group B only)
    post_engagement_rate = (likes_received + reposts_received) / posts_made

Variant assignment:
    Stable hash: sha256(account_id + "|" + test_id) % num_variants
    Same account always gets same variant across restarts.

Significance gate:
    Both variants must have >= min_sample_size follows_sent.
    No p-value math — pragmatic operational threshold.

Extended test dimensions (optional, via BlueSkyABVariant.params dict):
    post_strategy:   "native_only" | "crosspost_only" | "mixed"
    follow_source:   "search" | "scraped_pool" | "timeline"
    hashtag_rate:    float 0.0–1.0 (fraction of posts receiving a hashtag)
    timing_strategy: "morning_burst" | "distributed" | "peak_hours"
    like_feed:       "timeline" | "search" | "feed_uri"

Fleet-scale notes:
    - Each test variant targets <= 50% of the cohort. With 2 variants that
      means 50/50. With 4 variants that means 25% each. No single variant
      should dominate the cohort before the test concludes.
    - Events are appended to a JSONL file per test_id. The structure is
      identical to ig_ab_test.py — swap _append_event/_load_events with
      Postgres writes for production.
    - Storage dir: /tmp/phantom_fleet/bluesky_ab_tests/
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

# Module-level lock: prevents concurrent in-process JSONL writes from interleaving.
# Multiple threads/coroutines writing to the same file without a lock can corrupt
# JSONL on Windows (no O_APPEND atomicity guarantee) and cause data loss.
_FILE_LOCK = threading.Lock()

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Variant strategy enum
# ---------------------------------------------------------------------------


class BlueSkyEngagementVariant(str, Enum):
    FOLLOW_LIKE_ONLY = "follow_like_only"      # A: Follow + Like, no DM
    FOLLOW_LIKE_DM   = "follow_like_dm"        # B: Follow + Like + DM chat
    FOLLOW_ONLY      = "follow_only"           # C: bare follow, no extra touch
    FOLLOW_POST_DM   = "follow_post_dm"        # D: Follow + native post reply + DM


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class BlueSkyABVariant:
    """One variant in a BlueSky A/B test."""

    variant_id:          str
    label:               str                    # Human-readable e.g. "A: Follow+Like"
    engagement_strategy: BlueSkyEngagementVariant
    params:              dict = field(default_factory=dict)
    # Extended params keys understood by the manager:
    #   post_strategy:   str  — "native_only" | "crosspost_only" | "mixed"
    #   follow_source:   str  — "search" | "scraped_pool" | "timeline"
    #   hashtag_rate:    float
    #   timing_strategy: str  — "morning_burst" | "distributed" | "peak_hours"
    #   like_feed:       str  — "timeline" | "search" | "feed_uri"

    assigned_account_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "variant_id":           self.variant_id,
            "label":                self.label,
            "engagement_strategy":  self.engagement_strategy.value,
            "params":               self.params,
            "assigned_account_ids": self.assigned_account_ids,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BlueSkyABVariant":
        return cls(
            variant_id=d["variant_id"],
            label=d.get("label", d["variant_id"]),
            engagement_strategy=BlueSkyEngagementVariant(d["engagement_strategy"]),
            params=d.get("params", {}),
            assigned_account_ids=d.get("assigned_account_ids", []),
        )


@dataclass
class BlueSkyABSpec:
    """Full configuration for one BlueSky A/B test."""

    test_id:           str
    name:              str
    variants:          list[BlueSkyABVariant]
    cohort_account_ids: list[str]
    start_date_iso:    str
    end_date_iso:      str
    min_sample_size:   int = 50          # min follows_sent per variant
    niche:             str = ""          # persona niche — for LLM context
    status:            str = "running"   # running | concluded | insufficient_data

    def to_dict(self) -> dict:
        return {
            "test_id":            self.test_id,
            "name":               self.name,
            "variants":           [v.to_dict() for v in self.variants],
            "cohort_account_ids": self.cohort_account_ids,
            "start_date_iso":     self.start_date_iso,
            "end_date_iso":       self.end_date_iso,
            "min_sample_size":    self.min_sample_size,
            "niche":              self.niche,
            "status":             self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BlueSkyABSpec":
        return cls(
            test_id=d["test_id"],
            name=d["name"],
            variants=[BlueSkyABVariant.from_dict(v) for v in d.get("variants", [])],
            cohort_account_ids=d.get("cohort_account_ids", []),
            start_date_iso=d["start_date_iso"],
            end_date_iso=d["end_date_iso"],
            min_sample_size=d.get("min_sample_size", 50),
            niche=d.get("niche", ""),
            status=d.get("status", "running"),
        )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class BlueSkyABMetrics:
    """Aggregated per-variant counters for reporting."""

    variant_id:          str
    follows_sent:        int = 0
    follow_backs:        int = 0
    likes_given:         int = 0
    dms_sent:            int = 0
    dm_replies:          int = 0
    posts_made:          int = 0
    likes_received:      int = 0    # on own posts
    reposts_received:    int = 0    # on own posts

    @property
    def follow_back_rate(self) -> float:
        return self.follow_backs / self.follows_sent if self.follows_sent else 0.0

    @property
    def dm_reply_rate(self) -> float:
        return self.dm_replies / self.dms_sent if self.dms_sent else 0.0

    @property
    def post_engagement_rate(self) -> float:
        if not self.posts_made:
            return 0.0
        return (self.likes_received + self.reposts_received) / self.posts_made

    def to_dict(self) -> dict:
        return {
            "variant_id":          self.variant_id,
            "follows_sent":        self.follows_sent,
            "follow_backs":        self.follow_backs,
            "likes_given":         self.likes_given,
            "dms_sent":            self.dms_sent,
            "dm_replies":          self.dm_replies,
            "posts_made":          self.posts_made,
            "likes_received":      self.likes_received,
            "reposts_received":    self.reposts_received,
            "follow_back_rate":    round(self.follow_back_rate, 4),
            "dm_reply_rate":       round(self.dm_reply_rate, 4),
            "post_engagement_rate": round(self.post_engagement_rate, 4),
        }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class BlueSkyABReport:
    """Results of a test at a given snapshot in time."""

    spec:             BlueSkyABSpec
    metrics:          list[BlueSkyABMetrics]    # one per variant
    winner_id:        Optional[str]             # None = not yet significant
    winner_lift_pct:  float
    is_significant:   bool
    recommendation:   str                       # plain English from LLM or built-in

    def to_dict(self) -> dict:
        return {
            "test_id":          self.spec.test_id,
            "name":             self.spec.name,
            "is_significant":   self.is_significant,
            "winner_id":        self.winner_id,
            "winner_lift_pct":  round(self.winner_lift_pct, 2),
            "recommendation":   self.recommendation,
            "metrics":          [m.to_dict() for m in self.metrics],
        }


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------


@dataclass
class BlueSkyABEvent:
    """One atomic action recorded against a test."""

    test_id:    str
    account_id: str
    variant_id: str
    event_type: str     # follow | follow_back | like | dm_sent | dm_reply |
                        # post_made | like_received | repost_received
    target_id:  str = ""
    timestamp:  float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Storage helpers (JSONL file-based — swap for Postgres at scale)
# ---------------------------------------------------------------------------

_STORAGE_BASE = Path("/tmp/phantom_fleet/bluesky_ab_tests")


def _ensure_storage() -> None:
    _STORAGE_BASE.mkdir(parents=True, exist_ok=True)


def _storage_path(test_id: str) -> Path:
    _ensure_storage()
    return _STORAGE_BASE / f"{test_id}.jsonl"


def _config_path(test_id: str) -> Path:
    _ensure_storage()
    return _STORAGE_BASE / f"{test_id}_spec.json"


def _load_spec(test_id: str) -> Optional[BlueSkyABSpec]:
    path = _config_path(test_id)
    if not path.exists():
        return None
    try:
        return BlueSkyABSpec.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        log.warning("Could not load BlueSky AB spec %s: %s", test_id, exc)
        return None


def _save_spec(spec: BlueSkyABSpec) -> None:
    with _FILE_LOCK:
        _config_path(spec.test_id).write_text(
            json.dumps(spec.to_dict(), indent=2), encoding="utf-8"
        )


def _append_event(event: BlueSkyABEvent) -> None:
    line = json.dumps({
        "test_id":    event.test_id,
        "account_id": event.account_id,
        "variant_id": event.variant_id,
        "event_type": event.event_type,
        "target_id":  event.target_id,
        "timestamp":  event.timestamp,
    })
    with _FILE_LOCK:
        with _storage_path(event.test_id).open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _load_events(test_id: str) -> list[dict]:
    path = _storage_path(test_id)
    if not path.exists():
        return []
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                obj = json.loads(line)
                # Guard: only accept dicts — a non-dict value (list, int, etc.)
                # would cause AttributeError when callers call obj.get() on it.
                if isinstance(obj, dict):
                    events.append(obj)
            except Exception:
                pass
    return events


def _stable_hash_mod(account_id: str, test_id: str, modulus: int) -> int:
    """Deterministic, stable account→variant mapping per test. Never randomised.

    Including test_id ensures an account enrolled in two concurrent tests is
    independently assigned to variants in each one — eliminating cross-test
    correlation bias that would occur if only account_id were hashed.
    """
    key = f"{account_id}|{test_id}"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % modulus


# ---------------------------------------------------------------------------
# BlueSkyABManager
# ---------------------------------------------------------------------------


class BlueSkyABManager:
    """
    Manages A/B tests comparing BlueSky engagement strategies.

    Typical lifecycle:
        1. manager.create_test(name, account_ids, variants, ...)
        2. During daily runs, each specialist agent calls manager.record_event(...)
        3. Periodically: manager.generate_report(test_id)
        4. When significant: BlueSkyABTestAgent calls manager.conclude_test(test_id)
        5. manager.get_winning_params(test_id) → params to roll out fleet-wide

    Thread safety: JSONL append is atomic on Linux (O_APPEND guarantee).
    For multi-process safety at scale, replace with DB writes.
    """

    # ------------------------------------------------------------------
    # Test lifecycle
    # ------------------------------------------------------------------

    def create_test(
        self,
        name:             str,
        account_ids:      list[str],
        variants:         list[BlueSkyABVariant],
        start_date_iso:   str,
        end_date_iso:     str,
        min_sample_size:  int = 50,
        niche:            str = "",
        test_id:          Optional[str] = None,
    ) -> BlueSkyABSpec:
        """
        Create a new BlueSky A/B test.

        Assigns each account_id to a variant via stable hash, then saves
        the spec.  The same account always maps to the same variant —
        variant switching mid-test contaminates the metric.
        """
        if not variants:
            raise ValueError("At least one variant required")
        if len(variants) > 8:
            raise ValueError("Max 8 variants per test (more is impractical)")
        ids = [v.variant_id for v in variants]
        if len(set(ids)) < len(ids):
            raise ValueError(f"Duplicate variant_ids would corrupt metric aggregation: {ids}")

        if test_id is None:
            test_id = f"bsky_ab_{uuid.uuid4().hex[:8]}"

        n = len(variants)
        for v in variants:
            v.assigned_account_ids = []

        for account_id in account_ids:
            idx = _stable_hash_mod(account_id, test_id, n)
            variants[idx].assigned_account_ids.append(account_id)

        spec = BlueSkyABSpec(
            test_id=test_id,
            name=name,
            variants=variants,
            cohort_account_ids=account_ids,
            start_date_iso=start_date_iso,
            end_date_iso=end_date_iso,
            min_sample_size=min_sample_size,
            niche=niche,
            status="running",
        )
        _save_spec(spec)

        log.info(
            "[bsky_ab] Created test %s '%s': %d accounts across %d variants",
            test_id, name, len(account_ids), n,
        )
        for v in variants:
            log.info(
                "[bsky_ab]   variant %s '%s': %d accounts",
                v.variant_id, v.label, len(v.assigned_account_ids),
            )
        return spec

    def conclude_test(self, test_id: str, recommendation: str = "") -> Optional[BlueSkyABReport]:
        """Mark test concluded and write final report file.

        Write order (crash-safe):
            1. Generate the report from live event data.
            2. Write .concluded.json (durable artifact) — if we crash here the
               spec is still "active" so the next call retries cleanly.
            3. Update spec status to "concluded" — only after the file is on disk.
        """
        report = self.generate_report(test_id, recommendation=recommendation)
        if report is None:
            return None
        spec = _load_spec(test_id)
        if spec:
            # Step 2: write the durable artifact first
            concluded = _config_path(test_id).with_suffix(".concluded.json")
            concluded.write_text(
                json.dumps({"spec": spec.to_dict(), "report": report.to_dict()}, indent=2),
                encoding="utf-8",
            )
            # Step 3: only now mark the spec as concluded
            spec.status = "concluded"
            _save_spec(spec)
        return report

    # ------------------------------------------------------------------
    # Variant assignment (lookup for existing tests)
    # ------------------------------------------------------------------

    def get_variant_for_account(
        self, account_id: str, spec: BlueSkyABSpec
    ) -> Optional[BlueSkyABVariant]:
        """Return the variant this account is assigned to in the given test."""
        if not spec.variants:
            return None  # guard: corrupted spec with 0 variants → ZeroDivisionError otherwise
        idx = _stable_hash_mod(account_id, spec.test_id, len(spec.variants))
        return spec.variants[idx]

    # ------------------------------------------------------------------
    # Event recording
    # ------------------------------------------------------------------

    def record_follow(self, test_id: str, account_id: str, variant_id: str, target_id: str) -> None:
        _append_event(BlueSkyABEvent(test_id, account_id, variant_id, "follow", target_id))

    def record_follow_back(self, test_id: str, account_id: str, variant_id: str, from_did: str) -> None:
        _append_event(BlueSkyABEvent(test_id, account_id, variant_id, "follow_back", from_did))

    def record_like(self, test_id: str, account_id: str, variant_id: str, post_uri: str) -> None:
        _append_event(BlueSkyABEvent(test_id, account_id, variant_id, "like", post_uri))

    def record_dm_sent(self, test_id: str, account_id: str, variant_id: str, target_id: str) -> None:
        _append_event(BlueSkyABEvent(test_id, account_id, variant_id, "dm_sent", target_id))

    def record_dm_reply(self, test_id: str, account_id: str, variant_id: str, target_id: str) -> None:
        _append_event(BlueSkyABEvent(test_id, account_id, variant_id, "dm_reply", target_id))

    def record_post_made(self, test_id: str, account_id: str, variant_id: str, post_uri: str) -> None:
        _append_event(BlueSkyABEvent(test_id, account_id, variant_id, "post_made", post_uri))

    def record_like_received(self, test_id: str, account_id: str, variant_id: str, post_uri: str) -> None:
        _append_event(BlueSkyABEvent(test_id, account_id, variant_id, "like_received", post_uri))

    def record_repost_received(self, test_id: str, account_id: str, variant_id: str, post_uri: str) -> None:
        _append_event(BlueSkyABEvent(test_id, account_id, variant_id, "repost_received", post_uri))

    # ------------------------------------------------------------------
    # Metrics aggregation
    # ------------------------------------------------------------------

    def aggregate_metrics(self, test_id: str, spec: BlueSkyABSpec) -> list[BlueSkyABMetrics]:
        """Aggregate all events into per-variant metric counters."""
        events = _load_events(test_id)

        # Index variants
        metrics_map: dict[str, BlueSkyABMetrics] = {
            v.variant_id: BlueSkyABMetrics(variant_id=v.variant_id)
            for v in spec.variants
        }

        _event_to_field = {
            "follow":          "follows_sent",
            "follow_back":     "follow_backs",
            "like":            "likes_given",
            "dm_sent":         "dms_sent",
            "dm_reply":        "dm_replies",
            "post_made":       "posts_made",
            "like_received":   "likes_received",
            "repost_received": "reposts_received",
        }

        for evt in events:
            vid = evt.get("variant_id", "")
            et  = evt.get("event_type", "")
            if vid not in metrics_map:
                continue
            fld = _event_to_field.get(et)
            if fld:
                setattr(metrics_map[vid], fld, getattr(metrics_map[vid], fld) + 1)

        return list(metrics_map.values())

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_report(
        self,
        test_id:        str,
        recommendation: str = "",
    ) -> Optional[BlueSkyABReport]:
        """
        Generate current A/B test results.

        winner_id is None if not yet significant.
        recommendation is passed through from the caller (typically the
        AI agent) or left as an empty string.
        """
        spec = _load_spec(test_id)
        if spec is None:
            log.warning("[bsky_ab] Spec not found for test %s", test_id)
            return None

        metrics = self.aggregate_metrics(test_id, spec)

        # Significance: all variants must have >= min_sample_size follows_sent.
        # Guard against empty metrics (e.g. corrupted spec with 0 variants) —
        # all() on an empty iterable vacuously returns True, which would falsely
        # mark a data-free test as significant.
        is_significant = bool(metrics) and all(
            m.follows_sent >= spec.min_sample_size for m in metrics
        )

        winner_id: Optional[str] = None
        winner_lift_pct: float = 0.0

        if is_significant and len(metrics) >= 2:
            sorted_by_fbr = sorted(metrics, key=lambda m: m.follow_back_rate, reverse=True)
            best  = sorted_by_fbr[0]
            worst = sorted_by_fbr[-1]

            if best.follow_back_rate > worst.follow_back_rate:
                winner_id = best.variant_id
                if worst.follow_back_rate > 0:
                    winner_lift_pct = (
                        (best.follow_back_rate - worst.follow_back_rate)
                        / worst.follow_back_rate * 100
                    )
                else:
                    winner_lift_pct = 100.0

        if not recommendation:
            if not is_significant:
                min_follows = min((m.follows_sent for m in metrics), default=0)
                recommendation = (
                    f"Not yet significant. "
                    f"Min follows sent across variants: {min_follows} "
                    f"(need {spec.min_sample_size} each)."
                )
            elif winner_id:
                recommendation = (
                    f"Variant '{winner_id}' wins with "
                    f"{winner_lift_pct:.1f}% lift on follow_back_rate. "
                    f"Roll out params to full cohort."
                )
            else:
                recommendation = (
                    "No clear winner — variants are tied. Extend test duration."
                    if len(metrics) >= 2
                    else "Test has only one active variant — add a second variant to compare."
                )

        return BlueSkyABReport(
            spec=spec,
            metrics=metrics,
            winner_id=winner_id,
            winner_lift_pct=winner_lift_pct,
            is_significant=is_significant,
            recommendation=recommendation,
        )

    def get_winning_params(self, test_id: str) -> Optional[dict]:
        """
        Return the params dict of the winning variant, or None if no winner yet.

        This is what the manager uses to reconfigure non-test accounts once
        the test concludes.
        """
        report = self.generate_report(test_id)
        if report is None or report.winner_id is None:
            return None
        spec = _load_spec(test_id)
        if spec is None:
            return None
        for v in spec.variants:
            if v.variant_id == report.winner_id:
                return {
                    "engagement_strategy": v.engagement_strategy.value,
                    **v.params,
                }
        return None

    def list_tests(self) -> list[BlueSkyABSpec]:
        """Return all known test specs from storage."""
        _ensure_storage()
        specs: list[BlueSkyABSpec] = []
        for p in _STORAGE_BASE.glob("*_spec.json"):
            if ".concluded." in p.name:
                continue
            try:
                specs.append(BlueSkyABSpec.from_dict(json.loads(p.read_text(encoding="utf-8"))))
            except Exception:
                pass
        return specs

    def list_active_tests(self) -> list[BlueSkyABSpec]:
        """Return only tests with status == 'running'."""
        return [s for s in self.list_tests() if s.status == "running"]

    def get_followed_dids_in_test(
        self, test_id: str, account_id: str
    ) -> set[str]:
        """
        Return the set of target DIDs that `account_id` has followed in
        this test (from recorded 'follow' events). Used by the follow-back
        reconciliation agent to know who to look for in the followers list.
        """
        events = _load_events(test_id)
        return {
            e["target_id"]
            for e in events
            if e.get("account_id") == account_id
            and e.get("event_type") == "follow"
            and e.get("target_id")
        }

    def get_already_recorded_followbacks(
        self, test_id: str, account_id: str
    ) -> set[str]:
        """
        Return the set of DIDs already recorded as follow_back events for
        `account_id` in this test. Prevents double-counting on repeated
        reconciliation runs.
        """
        events = _load_events(test_id)
        return {
            e["target_id"]
            for e in events
            if e.get("account_id") == account_id
            and e.get("event_type") == "follow_back"
            and e.get("target_id")
        }

    def get_follow_reconciliation_sets(
        self, test_id: str, account_id: str
    ) -> tuple[set[str], set[str]]:
        """
        Return (followed_dids, already_recorded_followbacks) in ONE event-log read.

        Replaces two separate calls to get_followed_dids_in_test +
        get_already_recorded_followbacks, halving the file I/O per
        reconciliation run.
        """
        events = _load_events(test_id)
        followed: set[str] = set()
        recorded: set[str] = set()
        for e in events:
            if e.get("account_id") != account_id:
                continue
            target = e.get("target_id", "")
            if not target:
                continue
            et = e.get("event_type", "")
            if et == "follow":
                followed.add(target)
            elif et == "follow_back":
                recorded.add(target)
        return followed, recorded

    def get_active_test_for_account(
        self, account_id: str
    ) -> Optional[tuple[BlueSkyABSpec, BlueSkyABVariant]]:
        """
        Return (spec, variant) for the first active test that includes
        `account_id`, or None if not in any running test.

        Used by the manager to inject A/B metadata into specialist ctx dicts
        without the manager needing to iterate tests itself.
        """
        for spec in self.list_active_tests():
            if account_id in spec.cohort_account_ids:
                variant = self.get_variant_for_account(account_id, spec)
                if variant:
                    return (spec, variant)
        return None
