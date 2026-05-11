"""Test the platform-context chat tier system."""
import pytest

from phantom_fleet.core.chat_modes import (
    ChatTier,
    CHAT_MODE_CATALOG,
    PLATFORM_ALLOWED_MODES,
    ChatTierViolation,
    validate_mode_for_platform,
    reject_content,
    LINKEDIN_PROFESSIONAL,
    GRINDR_NSFW,
    INSTAGRAM_FLIRTY,
    TIKTOK_CASUAL,
    TELEGRAM_VIP_NSFW,
)


def test_all_modes_registered():
    assert len(CHAT_MODE_CATALOG) == 16
    for name, profile in CHAT_MODE_CATALOG.items():
        assert profile.name == name
        assert isinstance(profile.tier, ChatTier)


def test_tier_order():
    assert ChatTier.PROFESSIONAL < ChatTier.CASUAL_SFW
    assert ChatTier.CASUAL_SFW < ChatTier.FLIRTY_SFW
    assert ChatTier.FLIRTY_SFW < ChatTier.MIXED
    assert ChatTier.MIXED < ChatTier.NSFW


def test_linkedin_professional_profile_exists():
    # LinkedIn chat mode profile is preserved for the general brand build
    assert LINKEDIN_PROFESSIONAL.tier == ChatTier.PROFESSIONAL
    assert LINKEDIN_PROFESSIONAL.name == "linkedin_professional"
    # LinkedIn is excluded from OFM PLATFORM_ALLOWED_MODES — general brand only


def test_grindr_nsfw_only():
    assert GRINDR_NSFW.tier == ChatTier.NSFW
    validate_mode_for_platform("dating", "grindr_nsfw")
    with pytest.raises(ChatTierViolation):
        validate_mode_for_platform("dating", "instagram_flirty")


def test_instagram_is_flirty_sfw_only():
    assert INSTAGRAM_FLIRTY.tier == ChatTier.FLIRTY_SFW
    validate_mode_for_platform("instagram", "instagram_flirty")
    with pytest.raises(ChatTierViolation):
        validate_mode_for_platform("instagram", "grindr_nsfw")


def test_tiktok_casual_sfw():
    assert TIKTOK_CASUAL.tier == ChatTier.CASUAL_SFW
    validate_mode_for_platform("tiktok", "tiktok_casual")
    with pytest.raises(ChatTierViolation):
        validate_mode_for_platform("tiktok", "grindr_nsfw")


def test_reject_banned_phrase():
    rejected, reason = reject_content(LINKEDIN_PROFESSIONAL, "Let me delve into the opportunity")
    assert rejected
    assert "delve into" in reason


def test_reject_hashtag():
    rejected, reason = reject_content(INSTAGRAM_FLIRTY, "love your vibe #queen")
    assert rejected
    assert reason == "hashtag_banned"


def test_reject_emoji_in_linkedin():
    rejected, reason = reject_content(LINKEDIN_PROFESSIONAL, "Impressive work 👏")
    assert rejected
    assert reason == "emoji_in_professional"


def test_reject_word_count_exceeded():
    very_long = " ".join(["word"] * 100)
    rejected, reason = reject_content(TIKTOK_CASUAL, very_long)
    assert rejected
    assert reason.startswith("word_count:")


def test_grindr_allows_nsfw_content():
    text = "hey handsome looking for someone tonight"
    rejected, _ = reject_content(GRINDR_NSFW, text)
    assert not rejected  # NSFW tier allows this


def test_telegram_vip_allows_voice_messages():
    assert TELEGRAM_VIP_NSFW.voice_msgs_allowed
    assert "voice" in TELEGRAM_VIP_NSFW.allowed_media


def test_linkedin_no_voice_messages():
    assert not LINKEDIN_PROFESSIONAL.voice_msgs_allowed


def test_platform_coverage():
    """Every platform in the PLATFORM_META should have a chat mode."""
    from phantom_fleet.agents.managers import PLATFORM_META
    for platform_key in PLATFORM_META.keys():
        assert platform_key in PLATFORM_ALLOWED_MODES, (
            f"platform {platform_key} has no chat mode registered"
        )
        modes = PLATFORM_ALLOWED_MODES[platform_key]
        assert len(modes) >= 1, f"platform {platform_key} has empty chat mode list"
        for mode_name in modes:
            assert mode_name in CHAT_MODE_CATALOG, (
                f"mode {mode_name} referenced by {platform_key} but not in catalog"
            )
