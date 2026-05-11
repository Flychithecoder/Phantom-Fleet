"""Test the source scorer classifies correctly."""
from phantom_fleet.core.source_scorer import (
    CandidateSource,
    classify_female,
    classify_us,
    score_source,
)


def test_classify_female_positive():
    c = CandidateSource(
        username="bellaxoxo",
        full_name="Bella Johnson",
        bio="NYC girl 💕 she/her",
    )
    is_female, conf, _ = classify_female(c)
    assert is_female
    assert conf >= 0.5


def test_classify_female_negative():
    c = CandidateSource(
        username="johnsmithnyc",
        full_name="John Smith",
        bio="NYC dude · he/him · hiking",
    )
    is_female, _, _ = classify_female(c)
    assert not is_female


def test_classify_us_positive():
    c = CandidateSource(
        username="test",
        bio="NYC 🇺🇸 content creator · y'all know me",
    )
    is_us, _, _ = classify_us(c)
    assert is_us


def test_high_score_source():
    c = CandidateSource(
        username="emilyxo",
        full_name="Emily Jane",
        bio="NYC creator 💖 she/her",
        follower_count=50_000,
        following_count=800,
        avg_likes_last_12=3500,
        avg_comments_last_12=180,
        days_since_last_post=1,
        follower_growth_30d=400,
    )
    result = score_source(c)
    assert result.approved
    assert result.score >= 65


def test_rejected_male_source():
    c = CandidateSource(
        username="johnsmith123",
        full_name="John Smith",
        bio="NYC fitness coach",
        follower_count=50_000,
        following_count=800,
        avg_likes_last_12=3500,
        avg_comments_last_12=180,
        days_since_last_post=1,
    )
    result = score_source(c)
    assert not result.approved
    assert "not_female" in result.reasons


def test_rejected_low_engagement():
    c = CandidateSource(
        username="emilyxo",
        full_name="Emily Jane",
        bio="NYC creator 💖",
        follower_count=50_000,
        following_count=500,
        avg_likes_last_12=100,      # <1% engagement
        avg_comments_last_12=5,
        days_since_last_post=1,
    )
    result = score_source(c)
    assert not result.approved
