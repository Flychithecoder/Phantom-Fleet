"""
Instagram A/B Test framework — compares growth methods at account level.

Primary test: Follow+Story-only (Group A) vs Follow+Story+DM (Group B).

Metric: follow_back_rate = follows_received / follows_sent
        Proxy for "target saw our profile and found it interesting enough to
        reciprocate."  DMs can boost this by pulling the target into a
        direct conversation.

Variant assignment:
    Stable hash-based: hash(account_id + test_id) % 2
    Same account always gets same variant across runs.
    50/50 split enforced by the modulo.

Significance gate:
    Simple rule: both variants must have >= ABTestConfig.min_sample_size
    follows before we declare a winner.  No p-value math — this is a
    pragmatic operational test, not a statistics paper.

DM dispatch integration:
    When IGFollowStoryOrchestrator runs the afternoon session, it checks
    IGABTestManager.assign_variant() for each account.  If variant B AND
    story session is done AND 4+ hours since last story view, it dispatches
    IGDMChatAgent.  Variant A accounts never get DM dispatch to these targets.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Variant enum
# ---------------------------------------------------------------------------


class ABTestVariant(str, Enum):
    FOLLOW_STORY_ONLY = "follow_story_only"   # Group A: pure non-intrusive
    FOLLOW_STORY_DM   = "follow_story_dm"     # Group B: adds DM after story view


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class ABTestConfig:
    test_id: str
    name: str                            # e.g. "IG Growth Method Test Apr 2026"
    variant_a_account_ids: list[str]     # Follow+Story only
    variant_b_account_ids: list[str]     # Follow+Story+DM
    start_date_iso: str
    end_date_iso: str
    min_sample_size: int = 50            # min follows per account before results are meaningful

    def to_dict(self) -> dict:
        return {
            "test_id":               self.test_id,
            "name":                  self.name,
            "variant_a_account_ids": self.variant_a_account_ids,
            "variant_b_account_ids": self.variant_b_account_ids,
            "start_date_iso":        self.start_date_iso,
            "end_date_iso":          self.end_date_iso,
            "min_sample_size":       self.min_sample_size,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ABTestConfig":
        return cls(
            test_id=d["test_id"],
            name=d["name"],
            variant_a_account_ids=d.get("variant_a_account_ids", []),
            variant_b_account_ids=d.get("variant_b_account_ids", []),
            start_date_iso=d["start_date_iso"],
            end_date_iso=d["end_date_iso"],
            min_sample_size=d.get("min_sample_size", 50),
        )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class ABTestMetrics:
    variant: ABTestVariant
    account_count: int
    total_follows_sent: int
    total_story_views: int
    total_story_reacts: int
    total_dms_sent: int                 # 0 for variant A
    follow_back_rate: float             # follows_received / follows_sent
    dm_reply_rate: float                # dm_replies / dms_sent (0 for variant A)
    # Estimated conversion (follow-back as proxy for profile interest)
    conversion_proxy: float             # follow_back_rate × story_react_rate
    # Statistical significance bookkeeping
    sample_size_a: int
    sample_size_b: int
    is_significant: bool                # True if sample_size >= min_sample_size for both


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class ABTestReport:
    config: ABTestConfig
    metrics_a: ABTestMetrics
    metrics_b: ABTestMetrics
    winner: Optional[ABTestVariant]     # None if not yet significant
    winner_lift_pct: float              # how much better winner is (%)
    recommendation: str                 # plain English recommendation

    def to_dict(self) -> dict:
        return {
            "test_id":     self.config.test_id,
            "name":        self.config.name,
            "metrics_a":   {
                "variant":           self.metrics_a.variant.value,
                "account_count":     self.metrics_a.account_count,
                "total_follows_sent": self.metrics_a.total_follows_sent,
                "total_story_views": self.metrics_a.total_story_views,
                "total_story_reacts": self.metrics_a.total_story_reacts,
                "total_dms_sent":    self.metrics_a.total_dms_sent,
                "follow_back_rate":  self.metrics_a.follow_back_rate,
                "dm_reply_rate":     self.metrics_a.dm_reply_rate,
                "conversion_proxy":  self.metrics_a.conversion_proxy,
                "sample_size":       self.metrics_a.sample_size_a,
                "is_significant":    self.metrics_a.is_significant,
            },
            "metrics_b":   {
                "variant":           self.metrics_b.variant.value,
                "account_count":     self.metrics_b.account_count,
                "total_follows_sent": self.metrics_b.total_follows_sent,
                "total_story_views": self.metrics_b.total_story_views,
                "total_story_reacts": self.metrics_b.total_story_reacts,
                "total_dms_sent":    self.metrics_b.total_dms_sent,
                "follow_back_rate":  self.metrics_b.follow_back_rate,
                "dm_reply_rate":     self.metrics_b.dm_reply_rate,
                "conversion_proxy":  self.metrics_b.conversion_proxy,
                "sample_size":       self.metrics_b.sample_size_b,
                "is_significant":    self.metrics_b.is_significant,
            },
            "winner":          self.winner.value if self.winner else None,
            "winner_lift_pct": self.winner_lift_pct,
            "recommendation":  self.recommendation,
        }


# ---------------------------------------------------------------------------
# Per-account event log entry
# ---------------------------------------------------------------------------


@dataclass
class ABTestEvent:
    test_id: str
    account_id: str
    variant: ABTestVariant
    event_type: str        # "follow", "story_view", "story_react", "follow_back", "dm_sent", "dm_reply"
    target_id: str
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------


def _storage_path(test_id: str) -> Path:
    """Path to the JSON event log for one test."""
    base = Path("/tmp/phantom_fleet/ab_tests")
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{test_id}.jsonl"


def _config_path(test_id: str) -> Path:
    base = Path("/tmp/phantom_fleet/ab_tests")
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{test_id}_config.json"


def _load_config(test_id: str) -> Optional[ABTestConfig]:
    path = _config_path(test_id)
    if not path.exists():
        return None
    try:
        return ABTestConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        log.warning("Could not load AB test config %s: %s", test_id, exc)
        return None


def _save_config(config: ABTestConfig) -> None:
    path = _config_path(config.test_id)
    path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")


def _append_event(event: ABTestEvent) -> None:
    path = _storage_path(event.test_id)
    line = json.dumps({
        "test_id":    event.test_id,
        "account_id": event.account_id,
        "variant":    event.variant.value,
        "event_type": event.event_type,
        "target_id":  event.target_id,
        "timestamp":  event.timestamp,
    })
    with path.open("a", encoding="utf-8") as f:
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
                events.append(json.loads(line))
            except Exception:
                pass
    return events


# ---------------------------------------------------------------------------
# IGABTestManager
# ---------------------------------------------------------------------------


class IGABTestManager:
    """
    Manages A/B tests comparing Instagram growth methods.

    Primary test: Follow+Story-only vs Follow+Story+DM
    Metric: follow_back_rate (proxy for profile interest / conversion)

    All state is persisted to /tmp/phantom_fleet/ab_tests/ as JSONL event
    logs.  In production this should be backed by Postgres — the file-based
    storage here is a clean integration point (swap _append_event/_load_events).

    Thread safety: JSONL append is atomic on Linux (O_APPEND guarantee).
    For multi-process safety, replace with a DB write.
    """

    # ---------------------------------------------------------------------------
    # Test lifecycle
    # ---------------------------------------------------------------------------

    def create_test(
        self,
        name: str,
        account_ids: list[str],
        start_date_iso: str,
        end_date_iso: str,
        min_sample_size: int = 50,
        test_id: Optional[str] = None,
    ) -> ABTestConfig:
        """
        Create a new A/B test.

        Splits account_ids 50/50 into A and B using hash(account_id + test_id) % 2.
        Assignment is stable: same account always in same variant.
        """
        if test_id is None:
            test_id = f"ig_ab_{uuid.uuid4().hex[:8]}"

        variant_a: list[str] = []
        variant_b: list[str] = []
        for account_id in account_ids:
            variant = self._compute_variant(account_id, test_id)
            if variant == ABTestVariant.FOLLOW_STORY_ONLY:
                variant_a.append(account_id)
            else:
                variant_b.append(account_id)

        config = ABTestConfig(
            test_id=test_id,
            name=name,
            variant_a_account_ids=variant_a,
            variant_b_account_ids=variant_b,
            start_date_iso=start_date_iso,
            end_date_iso=end_date_iso,
            min_sample_size=min_sample_size,
        )
        _save_config(config)
        log.info(
            "Created AB test %s: %d accounts (%d A / %d B)",
            test_id, len(account_ids), len(variant_a), len(variant_b),
        )
        return config

    def conclude_test(self, test_id: str) -> Optional[ABTestReport]:
        """Mark test complete and return final report."""
        report = self.generate_report(test_id)
        if report is None:
            return None
        config = _load_config(test_id)
        if config:
            concluded_path = _config_path(test_id).with_suffix(".concluded.json")
            concluded_path.write_text(
                json.dumps({**config.to_dict(), "concluded": True, "report": report.to_dict()}, indent=2),
                encoding="utf-8",
            )
        return report

    # ---------------------------------------------------------------------------
    # Variant assignment
    # ---------------------------------------------------------------------------

    def assign_variant(self, account_id: str, test_id: str) -> ABTestVariant:
        """
        Stable assignment — same account always gets same variant.

        Uses hash(account_id + test_id) % 2.  Variant A = 0, Variant B = 1.
        """
        return self._compute_variant(account_id, test_id)

    def _compute_variant(self, account_id: str, test_id: str) -> ABTestVariant:
        """Deterministic 50/50 split based on SHA-256."""
        digest = hashlib.sha256(f"{account_id}|{test_id}".encode("utf-8")).digest()
        bit = int.from_bytes(digest[:1], "big") % 2
        return ABTestVariant.FOLLOW_STORY_ONLY if bit == 0 else ABTestVariant.FOLLOW_STORY_DM

    # ---------------------------------------------------------------------------
    # Event recording
    # ---------------------------------------------------------------------------

    def record_follow(self, account_id: str, target_id: str, test_id: str) -> None:
        variant = self.assign_variant(account_id, test_id)
        _append_event(ABTestEvent(test_id, account_id, variant, "follow", target_id))

    def record_story_view(self, account_id: str, target_id: str, test_id: str) -> None:
        variant = self.assign_variant(account_id, test_id)
        _append_event(ABTestEvent(test_id, account_id, variant, "story_view", target_id))

    def record_story_react(self, account_id: str, target_id: str, test_id: str) -> None:
        variant = self.assign_variant(account_id, test_id)
        _append_event(ABTestEvent(test_id, account_id, variant, "story_react", target_id))

    def record_follow_back(self, account_id: str, from_target_id: str, test_id: str) -> None:
        variant = self.assign_variant(account_id, test_id)
        _append_event(ABTestEvent(test_id, account_id, variant, "follow_back", from_target_id))

    def record_dm_sent(self, account_id: str, target_id: str, test_id: str) -> None:
        variant = self.assign_variant(account_id, test_id)
        _append_event(ABTestEvent(test_id, account_id, variant, "dm_sent", target_id))

    def record_dm_reply(self, account_id: str, target_id: str, test_id: str) -> None:
        variant = self.assign_variant(account_id, test_id)
        _append_event(ABTestEvent(test_id, account_id, variant, "dm_reply", target_id))

    # ---------------------------------------------------------------------------
    # Report generation
    # ---------------------------------------------------------------------------

    def generate_report(self, test_id: str) -> Optional[ABTestReport]:
        """
        Generate current A/B test results with significance check.

        Returns None if the config cannot be loaded.
        """
        config = _load_config(test_id)
        if config is None:
            log.warning("AB test config not found: %s", test_id)
            return None

        events = _load_events(test_id)

        # Aggregate per-variant counters
        counters: dict[str, dict[str, int]] = {
            ABTestVariant.FOLLOW_STORY_ONLY.value: {
                "follows_sent":  0,
                "story_views":   0,
                "story_reacts":  0,
                "dms_sent":      0,
                "dm_replies":    0,
                "follow_backs":  0,
            },
            ABTestVariant.FOLLOW_STORY_DM.value: {
                "follows_sent":  0,
                "story_views":   0,
                "story_reacts":  0,
                "dms_sent":      0,
                "dm_replies":    0,
                "follow_backs":  0,
            },
        }

        for evt in events:
            v = evt.get("variant", "")
            et = evt.get("event_type", "")
            if v not in counters:
                continue
            mapping = {
                "follow":       "follows_sent",
                "story_view":   "story_views",
                "story_react":  "story_reacts",
                "dm_sent":      "dms_sent",
                "dm_reply":     "dm_replies",
                "follow_back":  "follow_backs",
            }
            key = mapping.get(et)
            if key:
                counters[v][key] += 1

        ca = counters[ABTestVariant.FOLLOW_STORY_ONLY.value]
        cb = counters[ABTestVariant.FOLLOW_STORY_DM.value]

        # Compute rates
        fbr_a = ca["follow_backs"] / ca["follows_sent"] if ca["follows_sent"] > 0 else 0.0
        fbr_b = cb["follow_backs"] / cb["follows_sent"] if cb["follows_sent"] > 0 else 0.0

        dmr_a = 0.0  # variant A never sends DMs
        dmr_b = cb["dm_replies"] / cb["dms_sent"] if cb["dms_sent"] > 0 else 0.0

        srr_a = ca["story_reacts"] / ca["story_views"] if ca["story_views"] > 0 else 0.0
        srr_b = cb["story_reacts"] / cb["story_views"] if cb["story_views"] > 0 else 0.0

        conv_a = fbr_a * srr_a if srr_a > 0 else fbr_a
        conv_b = fbr_b * srr_b if srr_b > 0 else fbr_b

        is_sig = self._is_significant_from_counts(ca["follows_sent"], cb["follows_sent"], config)

        metrics_a = ABTestMetrics(
            variant=ABTestVariant.FOLLOW_STORY_ONLY,
            account_count=len(config.variant_a_account_ids),
            total_follows_sent=ca["follows_sent"],
            total_story_views=ca["story_views"],
            total_story_reacts=ca["story_reacts"],
            total_dms_sent=0,        # Variant A: never sends DMs
            follow_back_rate=fbr_a,
            dm_reply_rate=dmr_a,
            conversion_proxy=conv_a,
            sample_size_a=ca["follows_sent"],
            sample_size_b=cb["follows_sent"],
            is_significant=is_sig,
        )

        metrics_b = ABTestMetrics(
            variant=ABTestVariant.FOLLOW_STORY_DM,
            account_count=len(config.variant_b_account_ids),
            total_follows_sent=cb["follows_sent"],
            total_story_views=cb["story_views"],
            total_story_reacts=cb["story_reacts"],
            total_dms_sent=cb["dms_sent"],
            follow_back_rate=fbr_b,
            dm_reply_rate=dmr_b,
            conversion_proxy=conv_b,
            sample_size_a=ca["follows_sent"],
            sample_size_b=cb["follows_sent"],
            is_significant=is_sig,
        )

        # Determine winner
        winner: Optional[ABTestVariant] = None
        winner_lift_pct: float = 0.0
        recommendation: str = ""

        if is_sig:
            if fbr_a > fbr_b:
                winner = ABTestVariant.FOLLOW_STORY_ONLY
                if fbr_b > 0:
                    winner_lift_pct = (fbr_a - fbr_b) / fbr_b * 100
                else:
                    winner_lift_pct = 100.0
                recommendation = (
                    f"Follow+Story-only (Group A) outperforms Follow+Story+DM by "
                    f"{winner_lift_pct:.1f}% on follow-back rate. "
                    f"The DM may be creating friction. Recommend running A across the full fleet."
                )
            elif fbr_b > fbr_a:
                winner = ABTestVariant.FOLLOW_STORY_DM
                if fbr_a > 0:
                    winner_lift_pct = (fbr_b - fbr_a) / fbr_a * 100
                else:
                    winner_lift_pct = 100.0
                recommendation = (
                    f"Follow+Story+DM (Group B) outperforms Follow+Story-only by "
                    f"{winner_lift_pct:.1f}% on follow-back rate. "
                    f"The DM touchpoint drives additional conversions. "
                    f"Recommend enabling DM for accounts past day 14 of warming."
                )
            else:
                winner = None
                winner_lift_pct = 0.0
                recommendation = (
                    "No significant difference between variants. "
                    "Consider running for more days to accumulate sample."
                )
        else:
            recommendation = (
                f"Test not yet significant. "
                f"Need at least {config.min_sample_size} follows per variant. "
                f"Current: A={ca['follows_sent']}, B={cb['follows_sent']}."
            )

        return ABTestReport(
            config=config,
            metrics_a=metrics_a,
            metrics_b=metrics_b,
            winner=winner,
            winner_lift_pct=winner_lift_pct,
            recommendation=recommendation,
        )

    def _is_significant(
        self,
        metrics_a: ABTestMetrics,
        metrics_b: ABTestMetrics,
        config: ABTestConfig,
    ) -> bool:
        """
        Simple significance check: both variants have >= min_sample_size follows.
        """
        return (
            metrics_a.sample_size_a >= config.min_sample_size
            and metrics_a.sample_size_b >= config.min_sample_size
        )

    def _is_significant_from_counts(
        self,
        follows_a: int,
        follows_b: int,
        config: ABTestConfig,
    ) -> bool:
        """Internal helper used during report generation."""
        return follows_a >= config.min_sample_size and follows_b >= config.min_sample_size

    def list_tests(self) -> list[ABTestConfig]:
        """Return all known test configs."""
        base = Path("/tmp/phantom_fleet/ab_tests")
        if not base.exists():
            return []
        configs: list[ABTestConfig] = []
        for p in base.glob("*_config.json"):
            try:
                configs.append(ABTestConfig.from_dict(json.loads(p.read_text(encoding="utf-8"))))
            except Exception:
                pass
        return configs
