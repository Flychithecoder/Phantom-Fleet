"""Test that all random values come from typed distributions and are replayable."""
from phantom_fleet.core.distributions import (
    LogNormal,
    Normal,
    Bimodal,
    WeightedCategorical,
    sample_int_range,
    sample_daily_intensity,
    sample_action_mix,
    seed_for,
)


def test_seed_is_deterministic():
    a = seed_for("account1", "2026-04-11", "follows")
    b = seed_for("account1", "2026-04-11", "follows")
    assert a == b


def test_different_accounts_get_different_seeds():
    a = seed_for("account1", "2026-04-11", "follows")
    b = seed_for("account2", "2026-04-11", "follows")
    assert a != b


def test_different_dates_get_different_seeds():
    a = seed_for("account1", "2026-04-11", "follows")
    b = seed_for("account1", "2026-04-12", "follows")
    assert a != b


def test_lognormal_sample_in_range():
    for _ in range(100):
        v = sample_int_range(5, 20, "test_account", "2026-04-11", "follows")
        assert 5 <= v <= 20


def test_lognormal_sample_replayable():
    v1 = sample_int_range(5, 20, "test_account", "2026-04-11", "follows")
    v2 = sample_int_range(5, 20, "test_account", "2026-04-11", "follows")
    assert v1 == v2


def test_daily_intensity_distribution():
    counts = {"minimal": 0, "light": 0, "normal": 0, "heavy": 0}
    for i in range(10_000):
        level, _ = sample_daily_intensity(f"account{i}", "2026-04-11")
        counts[level] += 1
    # Rough sanity check — distribution should match the weights
    assert 1000 < counts["minimal"] < 2000  # ~15%
    assert 2000 < counts["light"] < 3000    # ~25%
    assert 4000 < counts["normal"] < 5000   # ~45%
    assert 1000 < counts["heavy"] < 2000    # ~15%


def test_action_mix_sums_to_one():
    mix = sample_action_mix(
        categories=("follow", "like", "story", "comment"),
        alphas=(4.0, 8.0, 5.0, 1.0),
        account_id="test",
        date_iso="2026-04-11",
        field="mix_test",
    )
    assert abs(sum(mix.values()) - 1.0) < 0.001


def test_weighted_categorical():
    dist = WeightedCategorical(choices=[("a", 1.0), ("b", 3.0)])
    import random as _random
    rng = _random.Random(42)
    counts = {"a": 0, "b": 0}
    for _ in range(1000):
        counts[dist._draw(rng)] += 1
    # b should be roughly 3x a
    assert counts["b"] > counts["a"] * 2
