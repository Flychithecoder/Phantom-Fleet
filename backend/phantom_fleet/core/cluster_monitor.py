"""
ClusterHealthMonitor — fleet-scale fingerprinting drift detection.

Runs the "20K account cluster analysis" thought experiment from CLAUDE.md
continuously against the live account fleet.  Every check is a SQL-style
cohort query across ALL accounts — not per-request validation.

Design goals:
    - < 5 seconds for 1,000 accounts on pure Python (no I/O in hot path).
    - No heavy ML libraries; scipy or pure Python only.
    - Each check produces zero or more ClusterAlerts.
    - ClusterHealthReport is the top-level summary consumed by the API.

The 10 checks implemented:
    1.  Story react rate — CV must be > 0.30 (bell curve expected)
    2.  Follow timing — inter-follow delays must NOT be uniform (KS test)
    3.  Device model — no single model > 40%; at least 5 distinct models
    4.  OS version — no single version > 50% of fleet
    5.  Story react emoji — ❤️ not > 50%; at least 4 distinct emojis
    6.  Comment template diversity — no template > 5%; diversity index > 0.6
    7.  Post timing — no hour > 30% of daily posts
    8.  Hashtag monoculture — no single hashtag used by > 30% of accounts
    9.  Account age distribution — not suspiciously uniform (CV check)
    10. Action velocity outliers — flag accounts at > 3σ from fleet mean
"""
from __future__ import annotations

import math
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ClusterAlert:
    """A single finding from one cluster health check."""

    alert_id: str
    severity: str           # "warning" | "critical"
    dimension: str          # which check produced this alert
    finding: str            # human-readable explanation of what was found
    affected_count: int     # number of accounts affected
    affected_pct: float     # percentage of fleet
    recommendation: str     # what to do to fix it
    detected_at_iso: str
    resolved: bool = False


@dataclass
class ClusterHealthReport:
    """Top-level report produced by run_full_audit()."""

    generated_at_iso: str
    accounts_audited: int
    alerts: list[ClusterAlert]
    critical_count: int
    warning_count: int
    overall_health: str         # "healthy" | "warning" | "critical"
    next_audit_recommended_iso: str


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


class ClusterHealthMonitor:
    """
    Monitors the entire account fleet for fingerprinting drift.

    All check methods are pure functions of the input list — no I/O occurs
    inside this class.  Callers are responsible for loading account data
    from the DB and passing it in as plain Python dicts.

    Expected keys per account dict (any subset; missing keys are skipped
    gracefully to avoid crashing on schema evolution):
        account_id, username, status, day_in_curve, created_at,
        last_action_at, device_model, os_version,
        actions_today (int), story_views_today (int), reacts_sent_today (int),
        comments_today (list[str]),          # comment texts
        posts_today (list[str|datetime]),    # post timestamps ISO
        hashtags_today (list[str]),
        story_emojis_today (list[str]),
        follow_delays_seconds (list[float]), # inter-follow delay samples
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_full_audit(self, accounts: list[dict]) -> ClusterHealthReport:
        """
        Run all 10 checks and return a ClusterHealthReport.

        Pure Python, no async, no I/O.  Designed to complete in < 5s for
        1,000 accounts on a standard laptop.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        n = len(accounts)

        alerts: list[ClusterAlert] = []

        if n == 0:
            return ClusterHealthReport(
                generated_at_iso=now_iso,
                accounts_audited=0,
                alerts=[],
                critical_count=0,
                warning_count=0,
                overall_health="healthy",
                next_audit_recommended_iso=now_iso,
            )

        alerts.extend(self._check_react_rate_cv(accounts, n, now_iso))
        alerts.extend(self._check_follow_timing(accounts, n, now_iso))
        alerts.extend(self._check_device_model(accounts, n, now_iso))
        alerts.extend(self._check_os_version(accounts, n, now_iso))
        alerts.extend(self._check_emoji_distribution(accounts, n, now_iso))
        alerts.extend(self._check_comment_diversity(accounts, n, now_iso))
        alerts.extend(self._check_post_timing(accounts, n, now_iso))
        alerts.extend(self._check_hashtag_monoculture(accounts, n, now_iso))
        alerts.extend(self._check_account_age(accounts, n, now_iso))
        alerts.extend(self._check_action_velocity_outliers(accounts, n, now_iso))

        critical = sum(1 for a in alerts if a.severity == "critical")
        warnings = sum(1 for a in alerts if a.severity == "warning")

        if critical > 0:
            health = "critical"
        elif warnings > 0:
            health = "warning"
        else:
            health = "healthy"

        return ClusterHealthReport(
            generated_at_iso=now_iso,
            accounts_audited=n,
            alerts=alerts,
            critical_count=critical,
            warning_count=warnings,
            overall_health=health,
            next_audit_recommended_iso=now_iso,
        )

    # ------------------------------------------------------------------
    # Check 1 — Story react rate CV
    # ------------------------------------------------------------------

    def _check_react_rate_cv(
        self,
        accounts: list[dict],
        n: int,
        now_iso: str,
    ) -> list[ClusterAlert]:
        """
        Compute per-account react rate: reacts_sent / story_views * 100.
        CV < 0.15 → suspiciously uniform → alert.
        """
        rates: list[float] = []
        for acc in accounts:
            views = acc.get("story_views_today", 0) or 0
            reacts = acc.get("reacts_sent_today", 0) or 0
            if views > 0:
                rates.append(reacts / views * 100.0)

        if len(rates) < 5:
            return []

        cv = _coefficient_of_variation(rates)
        if cv < 0.15:
            return [ClusterAlert(
                alert_id=_new_id(),
                severity="warning",
                dimension="react_rate_cv",
                finding=(
                    f"Story react rates are suspiciously uniform across {len(rates)} accounts "
                    f"(CV={cv:.3f}, expected >0.30). "
                    "A flat histogram is a statistical fingerprint."
                ),
                affected_count=len(rates),
                affected_pct=len(rates) / n * 100,
                recommendation=(
                    "Introduce log-normal jitter on react_probability per account. "
                    "Each account should have a personal baseline sampled at creation."
                ),
                detected_at_iso=now_iso,
            )]
        return []

    # ------------------------------------------------------------------
    # Check 2 — Follow timing distribution
    # ------------------------------------------------------------------

    def _check_follow_timing(
        self,
        accounts: list[dict],
        n: int,
        now_iso: str,
    ) -> list[ClusterAlert]:
        """
        Pool all inter-follow delay samples across the fleet.
        Run a Kolmogorov-Smirnov test against a Uniform distribution.
        High KS statistic (low p-value by rough threshold) → good (not uniform).
        Low KS statistic (delays look uniform) → alert.

        We use a pure-Python approximate KS test against Uniform(min, max).
        """
        delays: list[float] = []
        for acc in accounts:
            d = acc.get("follow_delays_seconds") or []
            delays.extend(float(x) for x in d if x is not None)

        if len(delays) < 10:
            return []

        ks_stat = _ks_uniform_statistic(delays)
        # KS stat near 0 → empirical CDF matches uniform CDF → uniform distribution
        # We flag if KS stat < 0.05 (very close to uniform)
        if ks_stat < 0.05:
            return [ClusterAlert(
                alert_id=_new_id(),
                severity="warning",
                dimension="follow_timing_distribution",
                finding=(
                    f"Follow inter-delay distribution appears uniform (KS stat={ks_stat:.4f}). "
                    "Natural human follow timing follows a log-normal distribution, not uniform."
                ),
                affected_count=n,
                affected_pct=100.0,
                recommendation=(
                    "Replace uniform delay sampling with LogNormal(mu, sigma) where mu and "
                    "sigma are sampled per-account at creation. "
                    "Use secrets.SystemRandom for sampling, not math.random."
                ),
                detected_at_iso=now_iso,
            )]
        return []

    # ------------------------------------------------------------------
    # Check 3 — Device model distribution
    # ------------------------------------------------------------------

    def _check_device_model(
        self,
        accounts: list[dict],
        n: int,
        now_iso: str,
    ) -> list[ClusterAlert]:
        """No single model > 40%; at least 5 distinct models."""
        models: list[str] = []
        for acc in accounts:
            m = acc.get("device_model") or acc.get("device_profile", {}).get("model")
            if m:
                models.append(str(m))

        if len(models) < 5:
            return []

        counts = _count_values(models)
        total = len(models)
        alerts: list[ClusterAlert] = []

        top_model, top_count = max(counts.items(), key=lambda kv: kv[1])
        top_pct = top_count / total * 100

        if top_pct > 40:
            alerts.append(ClusterAlert(
                alert_id=_new_id(),
                severity="critical",
                dimension="device_model_monoculture",
                finding=(
                    f"Device model '{top_model}' appears on {top_count}/{total} accounts "
                    f"({top_pct:.1f}%). Threshold: 40%. "
                    "A real installed-base has long tails with many older/budget models."
                ),
                affected_count=top_count,
                affected_pct=top_pct,
                recommendation=(
                    "Reseed device profiles using a weighted distribution matching "
                    "real-world Android market share data. "
                    "Flagship phones should be at most 15-20% of fleet."
                ),
                detected_at_iso=now_iso,
            ))

        distinct = len(counts)
        if distinct < 5:
            alerts.append(ClusterAlert(
                alert_id=_new_id(),
                severity="critical",
                dimension="device_model_insufficient_diversity",
                finding=(
                    f"Only {distinct} distinct device model(s) across {total} accounts. "
                    "Minimum 5 required to avoid cohort-query fingerprinting."
                ),
                affected_count=total,
                affected_pct=100.0,
                recommendation=(
                    "Expand the device profile pool to include at least 15 models "
                    "spanning flagship, mid-range, and budget tiers."
                ),
                detected_at_iso=now_iso,
            ))

        return alerts

    # ------------------------------------------------------------------
    # Check 4 — OS version distribution
    # ------------------------------------------------------------------

    def _check_os_version(
        self,
        accounts: list[dict],
        n: int,
        now_iso: str,
    ) -> list[ClusterAlert]:
        """No single OS version > 50% of fleet."""
        versions: list[str] = []
        for acc in accounts:
            v = acc.get("os_version") or acc.get("device_profile", {}).get("os_version")
            if v:
                versions.append(str(v))

        if len(versions) < 5:
            return []

        counts = _count_values(versions)
        total = len(versions)
        top_ver, top_count = max(counts.items(), key=lambda kv: kv[1])
        top_pct = top_count / total * 100

        if top_pct > 50:
            return [ClusterAlert(
                alert_id=_new_id(),
                severity="warning",
                dimension="os_version_monoculture",
                finding=(
                    f"OS version '{top_ver}' appears on {top_count}/{total} accounts "
                    f"({top_pct:.1f}%). Threshold: 50%. "
                    "A real population spans many minor OS patch releases."
                ),
                affected_count=top_count,
                affected_pct=top_pct,
                recommendation=(
                    "Spread OS version assignments across several adjacent patch versions "
                    "matching the real-world OS adoption curve for each Android major version."
                ),
                detected_at_iso=now_iso,
            )]
        return []

    # ------------------------------------------------------------------
    # Check 5 — Emoji distribution
    # ------------------------------------------------------------------

    def _check_emoji_distribution(
        self,
        accounts: list[dict],
        n: int,
        now_iso: str,
    ) -> list[ClusterAlert]:
        """❤️ not > 50%; at least 4 distinct emojis used."""
        all_emojis: list[str] = []
        for acc in accounts:
            emojis = acc.get("story_emojis_today") or []
            all_emojis.extend(str(e) for e in emojis)

        if len(all_emojis) < 4:
            return []

        counts = _count_values(all_emojis)
        total = len(all_emojis)
        alerts: list[ClusterAlert] = []

        heart_count = counts.get("❤️", 0) + counts.get("\u2764\ufe0f", 0)
        heart_pct = heart_count / total * 100 if total else 0

        if heart_pct > 50:
            alerts.append(ClusterAlert(
                alert_id=_new_id(),
                severity="warning",
                dimension="emoji_monoculture",
                finding=(
                    f"❤️ accounts for {heart_count}/{total} reactions ({heart_pct:.1f}%). "
                    "Threshold: 50%. Single-emoji dominance is a detectable pattern."
                ),
                affected_count=int(heart_count),
                affected_pct=heart_pct,
                recommendation=(
                    "Implement weighted random emoji selection with ❤️ capped at 30%. "
                    "Distribute weight across at least 6 reaction emojis."
                ),
                detected_at_iso=now_iso,
            ))

        distinct = len(counts)
        if distinct < 4:
            alerts.append(ClusterAlert(
                alert_id=_new_id(),
                severity="warning",
                dimension="emoji_insufficient_diversity",
                finding=(
                    f"Only {distinct} distinct emoji(s) used across all story reactions today. "
                    "Minimum 4 required."
                ),
                affected_count=total,
                affected_pct=100.0,
                recommendation=(
                    "Expand the REACTION_POOL to at least 8 emojis with a "
                    "weighted probability distribution."
                ),
                detected_at_iso=now_iso,
            ))

        return alerts

    # ------------------------------------------------------------------
    # Check 6 — Comment template diversity
    # ------------------------------------------------------------------

    def _check_comment_diversity(
        self,
        accounts: list[dict],
        n: int,
        now_iso: str,
    ) -> list[ClusterAlert]:
        """No single template text > 5%; diversity index > 0.6."""
        all_comments: list[str] = []
        for acc in accounts:
            comments = acc.get("comments_today") or []
            all_comments.extend(str(c).strip() for c in comments if c)

        if len(all_comments) < 5:
            return []

        counts = _count_values(all_comments)
        total = len(all_comments)
        alerts: list[ClusterAlert] = []

        top_template, top_count = max(counts.items(), key=lambda kv: kv[1])
        top_pct = top_count / total * 100

        if top_pct > 5:
            alerts.append(ClusterAlert(
                alert_id=_new_id(),
                severity="warning",
                dimension="comment_monoculture",
                finding=(
                    f"Comment template '{top_template[:60]}...' used "
                    f"{top_count}/{total} times ({top_pct:.1f}%). "
                    "Threshold: 5%. Repeated identical comments are trivially detectable."
                ),
                affected_count=top_count,
                affected_pct=top_pct,
                recommendation=(
                    "Scale the comment template pool proportional to fleet size. "
                    "Rule of thumb: pool_size >= total_daily_comments / 0.05."
                ),
                detected_at_iso=now_iso,
            ))

        unique_count = len(counts)
        diversity_index = unique_count / total if total else 0.0
        if diversity_index < 0.6:
            alerts.append(ClusterAlert(
                alert_id=_new_id(),
                severity="warning",
                dimension="comment_diversity_index_low",
                finding=(
                    f"Comment diversity index is {diversity_index:.2f} "
                    f"({unique_count} unique / {total} total). "
                    "Threshold: 0.60."
                ),
                affected_count=total,
                affected_pct=100.0,
                recommendation=(
                    "Use generative variation (LLM paraphrase) rather than a static pool, "
                    "or expand the pool to at least 3× the expected daily comment volume."
                ),
                detected_at_iso=now_iso,
            ))

        return alerts

    # ------------------------------------------------------------------
    # Check 7 — Post timing distribution
    # ------------------------------------------------------------------

    def _check_post_timing(
        self,
        accounts: list[dict],
        n: int,
        now_iso: str,
    ) -> list[ClusterAlert]:
        """No single hour > 30% of today's posts."""
        hour_counts: dict[int, int] = {h: 0 for h in range(24)}
        total_posts = 0

        for acc in accounts:
            posts = acc.get("posts_today") or []
            for p in posts:
                hour = _extract_hour(p)
                if hour is not None:
                    hour_counts[hour] += 1
                    total_posts += 1

        if total_posts < 5:
            return []

        peak_hour = max(hour_counts, key=lambda h: hour_counts[h])
        peak_count = hour_counts[peak_hour]
        peak_pct = peak_count / total_posts * 100

        if peak_pct > 30:
            return [ClusterAlert(
                alert_id=_new_id(),
                severity="warning",
                dimension="post_timing_cluster",
                finding=(
                    f"{peak_count}/{total_posts} posts ({peak_pct:.1f}%) "
                    f"were published in hour {peak_hour:02d}:00 UTC. "
                    "Threshold: 30%. Concentrated post bursts create timing fingerprints."
                ),
                affected_count=peak_count,
                affected_pct=peak_pct,
                recommendation=(
                    "Spread posts across a diurnal curve matching the claimed geographic "
                    "distribution of accounts. Use per-account peak-time profiles to "
                    "scatter publish times."
                ),
                detected_at_iso=now_iso,
            )]
        return []

    # ------------------------------------------------------------------
    # Check 8 — Hashtag monoculture
    # ------------------------------------------------------------------

    def _check_hashtag_monoculture(
        self,
        accounts: list[dict],
        n: int,
        now_iso: str,
    ) -> list[ClusterAlert]:
        """No single hashtag used by > 30% of accounts."""
        hashtag_accounts: dict[str, set[str]] = {}

        for acc in accounts:
            account_id = acc.get("account_id") or acc.get("id") or str(id(acc))
            tags = acc.get("hashtags_today") or []
            for tag in tags:
                t = str(tag).strip().lstrip("#").lower()
                if t:
                    hashtag_accounts.setdefault(t, set()).add(account_id)

        if not hashtag_accounts:
            return []

        top_tag = max(hashtag_accounts, key=lambda t: len(hashtag_accounts[t]))
        top_acct_count = len(hashtag_accounts[top_tag])
        top_pct = top_acct_count / n * 100

        if top_pct > 30:
            return [ClusterAlert(
                alert_id=_new_id(),
                severity="warning",
                dimension="hashtag_monoculture",
                finding=(
                    f"Hashtag '#{top_tag}' used by {top_acct_count}/{n} accounts "
                    f"({top_pct:.1f}%). Threshold: 30%. "
                    "Concentrated hashtag use across the fleet creates a cluster signal."
                ),
                affected_count=top_acct_count,
                affected_pct=top_pct,
                recommendation=(
                    "Rotate hashtag sets per account using IGHashtagTrackerAgent. "
                    "No hashtag should appear in more than 1 in 3 accounts on the same day."
                ),
                detected_at_iso=now_iso,
            )]
        return []

    # ------------------------------------------------------------------
    # Check 9 — Account age distribution
    # ------------------------------------------------------------------

    def _check_account_age(
        self,
        accounts: list[dict],
        n: int,
        now_iso: str,
    ) -> list[ClusterAlert]:
        """
        Account creation dates should NOT be perfectly uniform.
        Natural fleets have clusters (batches created over days/weeks).
        A perfectly uniform distribution of ages is a statistical fingerprint.
        CV should be > 0.20 — if it's near 0, the fleet was created all at once.
        """
        now = datetime.now(timezone.utc)
        ages_days: list[float] = []

        for acc in accounts:
            raw = acc.get("created_at") or acc.get("imported_at")
            if raw:
                try:
                    dt = datetime.fromisoformat(str(raw))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age = (now - dt).total_seconds() / 86400.0
                    if age >= 0:
                        ages_days.append(age)
                except (ValueError, TypeError):
                    pass

        if len(ages_days) < 5:
            return []

        cv = _coefficient_of_variation(ages_days)
        if cv < 0.10:
            return [ClusterAlert(
                alert_id=_new_id(),
                severity="warning",
                dimension="account_age_uniformity",
                finding=(
                    f"Account age distribution is suspiciously uniform (CV={cv:.3f}, "
                    "expected >0.20). Suggests all accounts were created in a single batch. "
                    "Platforms can query cohort_created_at and identify fleet-scale creation events."
                ),
                affected_count=n,
                affected_pct=100.0,
                recommendation=(
                    "Stagger account creation across multiple days/weeks. "
                    "Import accounts in smaller batches with realistic delays between batches."
                ),
                detected_at_iso=now_iso,
            )]
        return []

    # ------------------------------------------------------------------
    # Check 10 — Action velocity outliers
    # ------------------------------------------------------------------

    def _check_action_velocity_outliers(
        self,
        accounts: list[dict],
        n: int,
        now_iso: str,
    ) -> list[ClusterAlert]:
        """
        Flag any account whose actions_today is > 3 standard deviations
        above the fleet mean.  These accounts are acting too fast relative
        to peers.
        """
        velocities: list[tuple[str, float]] = []

        for acc in accounts:
            account_id = acc.get("account_id") or acc.get("id") or ""
            v = acc.get("actions_today", 0) or 0
            velocities.append((account_id, float(v)))

        if len(velocities) < 3:
            return []

        values = [v for _, v in velocities]
        mean = statistics.mean(values)

        if len(values) < 2:
            return []

        std = statistics.stdev(values)
        if std == 0:
            return []

        outliers = [
            (aid, v) for aid, v in velocities
            if (v - mean) / std > 3.0
        ]

        if outliers:
            outlier_ids = [aid for aid, _ in outliers[:5]]
            return [ClusterAlert(
                alert_id=_new_id(),
                severity="warning",
                dimension="action_velocity_outliers",
                finding=(
                    f"{len(outliers)} account(s) are acting at >3σ above the fleet mean "
                    f"({mean:.1f} actions/day, σ={std:.1f}). "
                    f"Sample outlier IDs: {outlier_ids}. "
                    "Outlier accounts draw disproportionate attention from ML detectors."
                ),
                affected_count=len(outliers),
                affected_pct=len(outliers) / n * 100,
                recommendation=(
                    "Cap daily actions per account using the warming curve limits. "
                    "Ensure no account's daily budget can exceed mean + 2σ of the fleet."
                ),
                detected_at_iso=now_iso,
            )]
        return []


# ---------------------------------------------------------------------------
# Pure math helpers (no I/O, no dependencies beyond stdlib)
# ---------------------------------------------------------------------------


def _coefficient_of_variation(values: list[float]) -> float:
    """CV = std / mean.  Returns 0 if mean is zero or fewer than 2 values."""
    if len(values) < 2:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    std = statistics.stdev(values)
    return std / mean


def _count_values(items: list[str]) -> dict[str, int]:
    """Frequency map for a list of strings."""
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts


def _ks_uniform_statistic(values: list[float]) -> float:
    """
    Compute the Kolmogorov-Smirnov statistic against Uniform(min, max).

    KS statistic = max |F_empirical(x) - F_uniform(x)| over all sample points.

    A statistic near 0 means the data looks uniform.
    A statistic near 0.5+ means the data is clearly non-uniform.

    This is a pure-Python implementation that does not require scipy.
    """
    if len(values) < 2:
        return 0.5  # can't test, assume non-uniform (safe default)

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    lo = sorted_vals[0]
    hi = sorted_vals[-1]

    if hi == lo:
        return 0.0  # all identical → maximally uniform

    ks_stat = 0.0
    for i, x in enumerate(sorted_vals):
        # Empirical CDF at x: (i+1)/n
        empirical = (i + 1) / n
        # Uniform CDF at x: (x - lo) / (hi - lo)
        uniform = (x - lo) / (hi - lo)
        diff = abs(empirical - uniform)
        if diff > ks_stat:
            ks_stat = diff

    return ks_stat


def _extract_hour(post: Any) -> int | None:
    """Extract UTC hour (0-23) from an ISO timestamp string or datetime object."""
    if isinstance(post, datetime):
        return post.hour
    if isinstance(post, str):
        try:
            dt = datetime.fromisoformat(post)
            return dt.hour
        except (ValueError, TypeError):
            pass
    return None


def _new_id() -> str:
    """Generate a short unique alert ID."""
    return uuid.uuid4().hex[:12]
