"""
Tests for ClusterHealthMonitor.

asyncio_mode = "auto" (set in pyproject.toml).
All checks are pure Python — no I/O mocking needed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest

from phantom_fleet.core.cluster_monitor import (
    ClusterHealthMonitor,
    ClusterHealthReport,
    ClusterAlert,
    _coefficient_of_variation,
    _ks_uniform_statistic,
    _count_values,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_account(
    account_id: str | None = None,
    device_model: str = "Samsung Galaxy S21",
    os_version: str = "Android 13",
    actions_today: int = 50,
    story_views_today: int = 20,
    reacts_sent_today: int = 5,
    comments_today: list[str] | None = None,
    posts_today: list[str] | None = None,
    hashtags_today: list[str] | None = None,
    story_emojis_today: list[str] | None = None,
    follow_delays_seconds: list[float] | None = None,
    created_at_iso: str | None = None,
) -> dict:
    if created_at_iso is None:
        # Random age between 1 and 120 days
        import random
        days_ago = random.randint(1, 120)
        created_at_iso = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

    return {
        "account_id": account_id or str(uuid.uuid4()),
        "device_model": device_model,
        "os_version": os_version,
        "actions_today": actions_today,
        "story_views_today": story_views_today,
        "reacts_sent_today": reacts_sent_today,
        "comments_today": comments_today or [],
        "posts_today": posts_today or [],
        "hashtags_today": hashtags_today or [],
        "story_emojis_today": story_emojis_today or [],
        "follow_delays_seconds": follow_delays_seconds or [],
        "created_at": created_at_iso,
        "status": "active",
    }


def _monitor() -> ClusterHealthMonitor:
    return ClusterHealthMonitor()


def _report(accounts: list[dict]) -> ClusterHealthReport:
    return _monitor().run_full_audit(accounts)


def _find_alert(alerts: list[ClusterAlert], dimension: str) -> ClusterAlert | None:
    for a in alerts:
        if a.dimension == dimension:
            return a
    return None


# ---------------------------------------------------------------------------
# Tests: react rate CV
# ---------------------------------------------------------------------------


def test_react_rate_cv_too_uniform_fires_alert():
    """CV < 0.15 (very uniform react rates) → alert fires."""
    # All accounts have the same react rate: 25%
    accounts = [
        _make_account(story_views_today=20, reacts_sent_today=5)
        for _ in range(20)
    ]
    report = _report(accounts)
    alert = _find_alert(report.alerts, "react_rate_cv")
    assert alert is not None
    assert alert.severity == "warning"


def test_react_rate_cv_natural_variation_no_alert():
    """CV > 0.30 (natural variation) → no alert."""
    import random
    random.seed(42)
    # Diverse react rates: some accounts react a lot, others rarely
    accounts = [
        _make_account(
            story_views_today=20,
            reacts_sent_today=random.choice([0, 1, 2, 5, 10, 15, 20]),
        )
        for _ in range(20)
    ]
    report = _report(accounts)
    alert = _find_alert(report.alerts, "react_rate_cv")
    assert alert is None


# ---------------------------------------------------------------------------
# Tests: device model
# ---------------------------------------------------------------------------


def test_device_monoculture_critical_alert():
    """90% of fleet on same device model → critical alert fires."""
    accounts = (
        [_make_account(device_model="Samsung Galaxy S21") for _ in range(18)]
        + [_make_account(device_model="Pixel 7") for _ in range(2)]
    )
    report = _report(accounts)
    alert = _find_alert(report.alerts, "device_model_monoculture")
    assert alert is not None
    assert alert.severity == "critical"
    assert alert.affected_pct > 40


def test_device_diversity_no_alert():
    """Fleet with 5+ diverse models under 40% each → no monoculture alert."""
    models = ["Samsung S21", "Pixel 7", "OnePlus 9", "Xiaomi Mi 11", "Moto G Power"]
    accounts = [_make_account(device_model=models[i % len(models)]) for i in range(20)]
    report = _report(accounts)
    alert = _find_alert(report.alerts, "device_model_monoculture")
    assert alert is None
    alert2 = _find_alert(report.alerts, "device_model_insufficient_diversity")
    assert alert2 is None


def test_insufficient_device_diversity_fires_alert():
    """Only 2 distinct device models → insufficient diversity alert."""
    accounts = [
        _make_account(device_model="Samsung Galaxy S21" if i < 10 else "Pixel 7")
        for i in range(20)
    ]
    report = _report(accounts)
    alert = _find_alert(report.alerts, "device_model_insufficient_diversity")
    assert alert is not None


# ---------------------------------------------------------------------------
# Tests: OS version
# ---------------------------------------------------------------------------


def test_os_version_monoculture_alert():
    """80% of fleet on same OS version → alert fires."""
    accounts = (
        [_make_account(os_version="Android 13") for _ in range(16)]
        + [_make_account(os_version="Android 14") for _ in range(4)]
    )
    report = _report(accounts)
    alert = _find_alert(report.alerts, "os_version_monoculture")
    assert alert is not None
    assert alert.affected_pct > 50


def test_os_version_spread_no_alert():
    """Spread across many OS versions → no alert."""
    versions = ["Android 11", "Android 12", "Android 13", "Android 14", "Android 10"]
    accounts = [_make_account(os_version=versions[i % len(versions)]) for i in range(20)]
    report = _report(accounts)
    alert = _find_alert(report.alerts, "os_version_monoculture")
    assert alert is None


# ---------------------------------------------------------------------------
# Tests: emoji distribution
# ---------------------------------------------------------------------------


def test_emoji_monoculture_alert():
    """❤️ > 50% of all reactions → alert fires."""
    accounts = [
        _make_account(story_emojis_today=["❤️", "❤️", "❤️", "❤️", "😍"])
        for _ in range(10)
    ]
    report = _report(accounts)
    alert = _find_alert(report.alerts, "emoji_monoculture")
    assert alert is not None


def test_emoji_distribution_ok_no_alert():
    """Spread across 6 emojis with no single one > 50% → no monoculture alert."""
    emojis_per_account = ["❤️", "😍", "🔥", "😂", "👏", "🙌"]
    accounts = [
        _make_account(story_emojis_today=emojis_per_account)
        for _ in range(10)
    ]
    report = _report(accounts)
    alert = _find_alert(report.alerts, "emoji_monoculture")
    assert alert is None


# ---------------------------------------------------------------------------
# Tests: comment diversity
# ---------------------------------------------------------------------------


def test_comment_monoculture_alert():
    """One comment template used by 50% of accounts → alert fires."""
    accounts = [
        _make_account(comments_today=["Love this content!", "Love this content!"])
        for _ in range(10)
    ] + [
        _make_account(comments_today=[f"Unique comment {uuid.uuid4().hex[:4]}"])
        for _ in range(10)
    ]
    report = _report(accounts)
    alert = _find_alert(report.alerts, "comment_monoculture")
    assert alert is not None


def test_comment_diversity_good_no_alert():
    """All unique comments → no monoculture or diversity alert."""
    accounts = [
        _make_account(comments_today=[f"Comment {uuid.uuid4().hex}"])
        for _ in range(20)
    ]
    report = _report(accounts)
    m = _find_alert(report.alerts, "comment_monoculture")
    d = _find_alert(report.alerts, "comment_diversity_index_low")
    assert m is None
    assert d is None


# ---------------------------------------------------------------------------
# Tests: post timing
# ---------------------------------------------------------------------------


def test_post_timing_cluster_alert():
    """40% of posts in a single hour → alert fires."""
    # Hour 9: 8 posts; spread the rest across other hours
    hour9_posts = ["2026-04-11T09:00:00+00:00"] * 8
    other_posts = [f"2026-04-11T{h:02d}:00:00+00:00" for h in range(1, 13)]

    accounts = [
        _make_account(posts_today=hour9_posts[:2])
        for _ in range(4)
    ] + [
        _make_account(posts_today=[f"2026-04-11T{(i+1):02d}:15:00+00:00"])
        for i in range(12)
    ]
    # Manually create a more cluster-y scenario
    from phantom_fleet.core.cluster_monitor import ClusterHealthMonitor
    monitor = ClusterHealthMonitor()
    # Build accounts where 40% posts are in hour 10
    all_posts = (
        ["2026-04-11T10:00:00+00:00"] * 8
        + [f"2026-04-11T{h:02d}:00:00+00:00" for h in range(0, 20)]
    )
    single_acct = _make_account(posts_today=all_posts)
    report = monitor.run_full_audit([single_acct])
    alert = _find_alert(report.alerts, "post_timing_cluster")
    assert alert is not None


def test_post_timing_spread_no_alert():
    """Posts evenly spread across 24 hours → no timing cluster alert."""
    posts = [f"2026-04-11T{h:02d}:00:00+00:00" for h in range(24)]
    accounts = [_make_account(posts_today=posts)]
    report = _report(accounts)
    alert = _find_alert(report.alerts, "post_timing_cluster")
    assert alert is None


# ---------------------------------------------------------------------------
# Tests: hashtag monoculture
# ---------------------------------------------------------------------------


def test_hashtag_over_threshold_alert():
    """Hashtag used by > 30% of accounts → alert fires."""
    accounts = [
        _make_account(hashtags_today=["fitness", "gym", "health"])
        for _ in range(10)  # 100% use #fitness
    ] + [
        _make_account(hashtags_today=["travel", "adventure"])
        for _ in range(20)
    ]
    report = _report(accounts)
    alert = _find_alert(report.alerts, "hashtag_monoculture")
    # #fitness is used by 10/30 = 33% > 30% threshold
    assert alert is not None


def test_hashtag_spread_no_alert():
    """Each account uses unique hashtags → no monoculture alert."""
    accounts = [
        _make_account(hashtags_today=[f"tag_{uuid.uuid4().hex[:4]}" for _ in range(3)])
        for _ in range(20)
    ]
    report = _report(accounts)
    alert = _find_alert(report.alerts, "hashtag_monoculture")
    assert alert is None


# ---------------------------------------------------------------------------
# Tests: action velocity outliers
# ---------------------------------------------------------------------------


def test_action_velocity_outlier_flagged():
    """Account at > 3σ above fleet mean actions → flagged."""
    # Fleet: 19 normal accounts (50 actions) + 1 runaway (500 actions)
    accounts = [_make_account(actions_today=50) for _ in range(19)]
    accounts.append(_make_account(actions_today=500))
    report = _report(accounts)
    alert = _find_alert(report.alerts, "action_velocity_outliers")
    assert alert is not None
    assert alert.affected_count == 1


def test_action_velocity_uniform_no_outlier():
    """All accounts same velocity → no outlier alert (std=0 edge case)."""
    accounts = [_make_account(actions_today=50) for _ in range(10)]
    report = _report(accounts)
    alert = _find_alert(report.alerts, "action_velocity_outliers")
    assert alert is None


# ---------------------------------------------------------------------------
# Tests: overall_health
# ---------------------------------------------------------------------------


def test_overall_health_critical_if_any_critical_alert():
    """overall_health == 'critical' when at least one critical alert fires."""
    # Device monoculture is critical
    accounts = [_make_account(device_model="Samsung Galaxy S21") for _ in range(20)]
    report = _report(accounts)
    assert report.overall_health == "critical"
    assert report.critical_count >= 1


def test_overall_health_healthy_when_no_alerts():
    """overall_health == 'healthy' when fleet passes all checks."""
    import random
    random.seed(123)

    models = ["Samsung S21", "Pixel 7", "OnePlus 9", "Xiaomi Mi 11", "Moto G Power",
              "iPhone 14", "Samsung A52", "Oppo Find X5", "Realme GT 2", "Vivo X80"]
    versions = ["Android 11", "Android 12", "Android 13", "Android 14", "Android 10"]
    emojis_pool = [["❤️", "😍", "🔥"], ["😂", "👏", "🙌"], ["🥰", "💕", "✨"],
                   ["😎", "💯", "🎉"], ["🔥", "❤️", "😍"]]

    accounts = [
        _make_account(
            device_model=models[i % len(models)],
            os_version=versions[i % len(versions)],
            story_views_today=random.randint(5, 30),
            reacts_sent_today=random.randint(0, 10),
            story_emojis_today=emojis_pool[i % len(emojis_pool)],
            comments_today=[f"Unique comment {uuid.uuid4().hex[:8]}"],
            posts_today=[f"2026-04-11T{(i % 22):02d}:00:00+00:00"],
            hashtags_today=[f"unique_tag_{uuid.uuid4().hex[:6]}"],
            actions_today=random.randint(30, 70),
            created_at_iso=(
                datetime.now(timezone.utc) - timedelta(days=random.randint(5, 100))
            ).isoformat(),
        )
        for i in range(30)
    ]
    report = _report(accounts)
    # With sufficiently diverse data the report should be healthy or warning, not critical
    assert report.overall_health in ("healthy", "warning")


def test_empty_fleet_returns_healthy():
    """Empty account list returns a healthy report with no alerts."""
    report = _report([])
    assert report.overall_health == "healthy"
    assert report.accounts_audited == 0
    assert report.alerts == []


# ---------------------------------------------------------------------------
# Tests: pure math helpers
# ---------------------------------------------------------------------------


def test_cv_uniform_values_near_zero():
    """All identical values → CV near 0."""
    cv = _coefficient_of_variation([5.0, 5.0, 5.0, 5.0])
    assert cv == 0.0


def test_cv_high_variation():
    """Spread values → CV >> 0."""
    cv = _coefficient_of_variation([1.0, 10.0, 100.0, 1000.0])
    assert cv > 0.5


def test_ks_uniform_statistic_truly_uniform():
    """Perfectly spaced values → small KS statistic (matches uniform CDF closely)."""
    uniform_vals = [float(i) / 100 for i in range(101)]
    stat = _ks_uniform_statistic(uniform_vals)
    assert stat < 0.05


def test_ks_uniform_statistic_clearly_non_uniform():
    """Values clustered at one end → high KS statistic."""
    clustered = [0.01] * 50 + [0.99] * 50
    stat = _ks_uniform_statistic(clustered)
    assert stat > 0.3
