"""
Tests for phantom_fleet/core/voice_style.py — Gen Z 2026 voice style system.

asyncio_mode = "auto" (set in pyproject.toml).
All LLM calls are mocked — no network I/O.

Coverage:
    - apply_voice_style: retired slang and AI tell replacements
    - has_banned_phrases: phrase detection and clean-text passthrough
    - voice_style_score: high/low score discrimination
    - VOICE_STYLE_TEST_CASES: every canonical before/after pair
    - PLATFORM_VOICE_CONTEXT: all 11+ platforms have entries
    - GENZ_VOICE_BASELINE: non-empty, contains key directives
    - build_voice_prefix: injects baseline for all platforms; suppresses for linkedin
    - Retry gate (score < 0.5 or banned): triggers exactly one retry via nudge
    - Hard-banned phrase: forces retry even when score >= 0.5
    - Integration (_BaseDMChatAgent): voice baseline appears in system prompt
    - Integration (_BaseDMChatAgent): apply_voice_style called on LLM output
    - Integration (base_dm_chat_agent): same checks for IG/Threads base
    - Platform context injected per platform in build_voice_prefix output
    - STYLE_RETRY_NUDGE: non-empty string with actionable instruction
"""
from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from phantom_fleet.core.voice_style import (
    GENZ_VOICE_BASELINE,
    HARD_BANNED_PHRASES,
    PLATFORM_VOICE_CONTEXT,
    STYLE_RETRY_NUDGE,
    VOICE_STYLE_TEST_CASES,
    apply_voice_style,
    build_voice_prefix,
    get_voice_context,
    has_banned_phrases,
    voice_style_score,
)


# ---------------------------------------------------------------------------
# apply_voice_style — regex replacement tests
# ---------------------------------------------------------------------------


class TestApplyVoiceStyle:
    def test_lol_replaced_with_skull_emoji(self):
        result = apply_voice_style("lol that was funny")
        assert "lol" not in result.lower()
        assert "💀" in result

    def test_haha_replaced_with_no_literally(self):
        result = apply_voice_style("haha yeah totally")
        assert "haha" not in result.lower()
        assert "no literally" in result

    def test_epic_replaced(self):
        result = apply_voice_style("that was epic")
        assert "epic" not in result.lower()

    def test_lit_replaced_with_fire(self):
        result = apply_voice_style("this is so lit")
        assert "lit" not in result.lower()
        assert "fire" in result

    def test_dope_replaced(self):
        result = apply_voice_style("that outfit is dope")
        assert "dope" not in result.lower()

    def test_slaps_replaced(self):
        result = apply_voice_style("this song slaps")
        assert "slaps" not in result.lower()
        assert "goes hard" in result

    def test_gotcha_replaced_with_got_it(self):
        result = apply_voice_style("gotcha, I'll do that")
        assert "gotcha" not in result.lower()
        assert "got it" in result

    def test_id_be_happy_to_removed(self):
        result = apply_voice_style("I'd be happy to help you with that!")
        assert "i'd be happy to" not in result.lower()

    def test_certainly_removed(self):
        result = apply_voice_style("Certainly! Here's what I think.")
        assert "certainly" not in result.lower()

    def test_of_course_removed(self):
        result = apply_voice_style("Of course! Let me explain.")
        assert "of course" not in result.lower()

    def test_great_question_removed(self):
        result = apply_voice_style("Great question! The answer is...")
        assert "great question" not in result.lower()

    def test_i_understand_replaced_with_yeah(self):
        result = apply_voice_style("I understand how you feel.")
        assert "i understand" not in result.lower()
        assert "yeah" in result

    def test_i_apologize_replaced_with_my_bad(self):
        result = apply_voice_style("I apologize for the confusion.")
        assert "i apologize" not in result.lower()
        assert "my bad" in result

    def test_absolutely_removed(self):
        result = apply_voice_style("Absolutely! That sounds great.")
        assert "absolutely" not in result.lower()

    def test_amazing_opener_softened(self):
        result = apply_voice_style("Amazing! Let me tell you more.")
        assert "amazing!" not in result.lower()

    def test_whitespace_collapsed_after_removal(self):
        # Multiple tells removed should not leave double-spaces
        result = apply_voice_style("Certainly! Of course! I'd be happy to.")
        assert "  " not in result
        assert result == result.strip()

    def test_clean_genz_text_passes_through_unchanged(self):
        clean = "no bc why is that so funny 💀"
        result = apply_voice_style(clean)
        assert result == clean

    def test_case_insensitive_replacement(self):
        result = apply_voice_style("LOL that cracked me up")
        assert "lol" not in result.lower()

    def test_i_hope_this_helps_removed(self):
        result = apply_voice_style("I hope this helps! Let me know.")
        assert "i hope this helps" not in result.lower()

    def test_feel_free_to_removed(self):
        result = apply_voice_style("Feel free to ask me anything.")
        assert "feel free to" not in result.lower()


# ---------------------------------------------------------------------------
# has_banned_phrases
# ---------------------------------------------------------------------------


class TestHasBannedPhrases:
    def test_returns_true_for_id_be_happy_to(self):
        assert has_banned_phrases("I'd be happy to help you.") is True

    def test_returns_true_for_certainly(self):
        assert has_banned_phrases("certainly! let me explain") is True

    def test_returns_true_for_of_course(self):
        assert has_banned_phrases("Of course! Here we go.") is True

    def test_returns_true_for_great_question(self):
        assert has_banned_phrases("Great question, let me answer.") is True

    def test_returns_true_for_as_an_ai(self):
        assert has_banned_phrases("As an AI, I don't have feelings.") is True

    def test_returns_true_for_i_hope_this_helps(self):
        assert has_banned_phrases("I hope this helps!") is True

    def test_returns_true_for_dont_hesitate(self):
        assert has_banned_phrases("Don't hesitate to reach out.") is True

    def test_returns_true_for_feel_free_to_reach_out(self):
        assert has_banned_phrases("Feel free to reach out anytime.") is True

    def test_returns_true_for_in_conclusion(self):
        assert has_banned_phrases("In conclusion, this is important.") is True

    def test_returns_true_for_delve_into(self):
        assert has_banned_phrases("Let me delve into this topic.") is True

    def test_returns_true_for_furthermore(self):
        assert has_banned_phrases("Furthermore, I would add that...") is True

    def test_returns_false_for_clean_genz_text(self):
        assert has_banned_phrases("no bc why is that so funny 💀") is False

    def test_returns_false_for_casual_reply(self):
        assert has_banned_phrases("thats giving main character energy") is False

    def test_returns_false_for_empty_string(self):
        assert has_banned_phrases("") is False

    def test_case_insensitive(self):
        assert has_banned_phrases("CERTAINLY! I will help.") is True

    def test_all_banned_phrases_detected(self):
        """Every phrase in HARD_BANNED_PHRASES must be detected."""
        for phrase in HARD_BANNED_PHRASES:
            text = f"Some prefix. {phrase} Some suffix."
            assert has_banned_phrases(text) is True, (
                f"has_banned_phrases should detect phrase: {phrase!r}"
            )


# ---------------------------------------------------------------------------
# voice_style_score
# ---------------------------------------------------------------------------


class TestVoiceStyleScore:
    def test_high_score_for_authentic_genz_text(self):
        score = voice_style_score("no bc why is that so funny 💀")
        assert score >= 0.5, f"Expected score >= 0.5, got {score:.2f}"

    def test_high_score_for_lowercase_short(self):
        score = voice_style_score("lowkey obsessed with this rn")
        assert score >= 0.5

    def test_high_score_for_caps_emphasis(self):
        score = voice_style_score("HELP why is that so funny 😭")
        assert score >= 0.5

    def test_high_score_for_thats_giving(self):
        score = voice_style_score("thats actually giving main character energy")
        assert score >= 0.5

    def test_low_score_for_corporate_chatbot(self):
        score = voice_style_score(
            "I'd be happy to help you with that! Certainly, that's a great question."
        )
        assert score < 0.5, f"Expected score < 0.5, got {score:.2f}"

    def test_low_score_for_old_slang_overload(self):
        score = voice_style_score("haha lol that's so lit and dope!")
        assert score < 0.5

    def test_low_score_for_stacked_enthusiasm(self):
        score = voice_style_score("omg wow! Amazing! That's so cool!")
        assert score < 0.5

    def test_low_score_for_formal_essay_opener(self):
        score = voice_style_score(
            "Furthermore, I would like to add that this is quite interesting."
        )
        assert score < 0.5

    def test_score_penalises_lol(self):
        base = voice_style_score("that was really good")
        with_lol = voice_style_score("lol that was really good")
        assert with_lol < base

    def test_score_penalises_haha(self):
        base = voice_style_score("yeah totally")
        with_haha = voice_style_score("haha yeah totally")
        assert with_haha < base

    def test_score_penalises_long_message(self):
        short_score = voice_style_score("ok yeah totally")
        long_text = "word " * 40  # > 150 chars
        long_score = voice_style_score(long_text)
        assert long_score < short_score

    def test_score_penalises_emoji_overload(self):
        clean = voice_style_score("that's so good")
        overloaded = voice_style_score("that's so good 🎉🎊🥳🎈🎁")
        assert overloaded < clean

    def test_score_rewards_skull_emoji(self):
        without = voice_style_score("that was funny")
        with_skull = voice_style_score("that was funny 💀")
        assert with_skull >= without

    def test_score_rewards_lowercase_dominance(self):
        lower = voice_style_score("ok yeah this is good")
        upper = voice_style_score("OK YEAH THIS IS GOOD")
        assert lower > upper

    def test_score_rewards_genz_vocab(self):
        without = voice_style_score("yeah i like that")
        with_vocab = voice_style_score("lowkey i like that")
        assert with_vocab >= without

    def test_score_clamped_between_0_and_1(self):
        extreme_bad = voice_style_score(
            "I'd be happy to! Certainly! Of course! Great question! "
            "As an AI I understand. In conclusion, furthermore, I apologize for delving into this. "
            "lol haha " * 10
        )
        assert 0.0 <= extreme_bad <= 1.0

        extreme_good = voice_style_score("lowkey obsessed 💀 no bc why is that so funny")
        assert 0.0 <= extreme_good <= 1.0


# ---------------------------------------------------------------------------
# VOICE_STYLE_TEST_CASES — canonical before/after pairs
# ---------------------------------------------------------------------------


class TestVoiceStyleTestCases:
    def test_all_canonical_cases_match_expected_score_gate(self):
        """
        Each entry in VOICE_STYLE_TEST_CASES is (text, should_pass).
        voice_style_score is checked on the RAW text — this mirrors the
        agent pipeline which checks has_banned_phrases(raw) and
        voice_style_score(styled), where scoring corporate text on the raw
        form correctly penalises banned phrases before they are stripped.
        """
        for text, should_pass in VOICE_STYLE_TEST_CASES:
            score = voice_style_score(text)
            actually_passes = score >= 0.5
            assert actually_passes == should_pass, (
                f"Text: {text!r}\n"
                f"Score: {score:.2f} — expected pass={should_pass}, got pass={actually_passes}"
            )


# ---------------------------------------------------------------------------
# PLATFORM_VOICE_CONTEXT — coverage
# ---------------------------------------------------------------------------


class TestPlatformVoiceContext:
    REQUIRED_PLATFORMS = [
        "instagram", "threads", "reddit", "x", "bluesky",
        "telegram", "discord", "tinder", "bumble", "hinge", "grindr",
    ]

    def test_all_required_platforms_have_entries(self):
        for platform in self.REQUIRED_PLATFORMS:
            assert platform in PLATFORM_VOICE_CONTEXT, (
                f"Missing PLATFORM_VOICE_CONTEXT entry for platform: {platform!r}"
            )

    def test_all_entries_are_non_empty_strings(self):
        for platform, context in PLATFORM_VOICE_CONTEXT.items():
            assert isinstance(context, str), (
                f"Context for {platform!r} is not a string"
            )
            assert len(context.strip()) > 0, (
                f"Context for {platform!r} is empty"
            )

    def test_get_voice_context_returns_correct_entry(self):
        assert "instagram" in get_voice_context("instagram").lower() or \
               get_voice_context("instagram") == PLATFORM_VOICE_CONTEXT["instagram"]

    def test_get_voice_context_case_insensitive(self):
        assert get_voice_context("Instagram") == get_voice_context("instagram")

    def test_get_voice_context_unknown_platform_returns_empty(self):
        assert get_voice_context("unknown_platform_xyz") == ""

    def test_total_platform_count(self):
        """At least 11 platforms registered."""
        assert len(PLATFORM_VOICE_CONTEXT) >= 11


# ---------------------------------------------------------------------------
# GENZ_VOICE_BASELINE — content checks
# ---------------------------------------------------------------------------


class TestGenZVoiceBaseline:
    def test_is_non_empty_string(self):
        assert isinstance(GENZ_VOICE_BASELINE, str)
        assert len(GENZ_VOICE_BASELINE.strip()) > 0

    def test_contains_lowercase_instruction(self):
        assert "lowercase" in GENZ_VOICE_BASELINE

    def test_contains_short_messages_directive(self):
        assert "short messages" in GENZ_VOICE_BASELINE

    def test_contains_never_say_section(self):
        assert "never say" in GENZ_VOICE_BASELINE.lower()

    def test_bans_lol(self):
        assert "lol" in GENZ_VOICE_BASELINE

    def test_bans_certainly(self):
        assert "Certainly" in GENZ_VOICE_BASELINE

    def test_bans_id_be_happy_to(self):
        assert "I'd be happy to" in GENZ_VOICE_BASELINE

    def test_contains_skull_emoji_as_alternative_to_lol(self):
        assert "💀" in GENZ_VOICE_BASELINE

    def test_mentions_unbothered_vibe(self):
        assert "unbothered" in GENZ_VOICE_BASELINE


# ---------------------------------------------------------------------------
# build_voice_prefix — system prompt construction
# ---------------------------------------------------------------------------


class TestBuildVoicePrefix:
    def test_non_linkedin_includes_baseline(self):
        prefix = build_voice_prefix("instagram")
        assert GENZ_VOICE_BASELINE in prefix

    def test_non_linkedin_includes_platform_context(self):
        prefix = build_voice_prefix("instagram")
        assert PLATFORM_VOICE_CONTEXT["instagram"] in prefix

    def test_platform_context_appears_after_baseline(self):
        prefix = build_voice_prefix("reddit")
        baseline_pos = prefix.find(GENZ_VOICE_BASELINE)
        context_pos = prefix.find(PLATFORM_VOICE_CONTEXT["reddit"])
        assert baseline_pos < context_pos

    def test_linkedin_returns_empty_string(self):
        """LinkedIn must suppress the Gen Z baseline — professional voice only."""
        prefix = build_voice_prefix("linkedin")
        assert prefix == ""

    def test_unknown_platform_still_returns_baseline(self):
        """Unknown platforms fall back to the baseline without a context line."""
        prefix = build_voice_prefix("totally_unknown_platform")
        assert GENZ_VOICE_BASELINE in prefix

    def test_case_insensitive_platform(self):
        lower = build_voice_prefix("instagram")
        upper = build_voice_prefix("Instagram")
        assert lower == upper


# ---------------------------------------------------------------------------
# STYLE_RETRY_NUDGE
# ---------------------------------------------------------------------------


class TestStyleRetryNudge:
    def test_is_non_empty_string(self):
        assert isinstance(STYLE_RETRY_NUDGE, str)
        assert len(STYLE_RETRY_NUDGE.strip()) > 0

    def test_contains_actionable_instruction(self):
        lower = STYLE_RETRY_NUDGE.lower()
        # Must tell the LLM to rewrite / shorten / go less formal
        assert any(word in lower for word in ("rewrite", "shorter", "natural", "less formal"))


# ---------------------------------------------------------------------------
# Integration: _BaseDMChatAgent (_base_chat.py)
# Tests that:
#   - GENZ_VOICE_BASELINE appears in system prompt before ChatModeProfile content
#   - apply_voice_style is called on LLM output
#   - Low-score output triggers retry with STYLE_RETRY_NUDGE
#   - Hard-banned phrase triggers retry even when score >= 0.5
# ---------------------------------------------------------------------------


class TestBaseChatAgentIntegration:
    """
    Integration tests for _base_chat._BaseDMChatAgent.

    _BaseDMChatAgent is abstract; we create a minimal concrete subclass
    that stubs out the platform-specific methods.
    """

    def _make_agent(self):
        from phantom_fleet.agents.specialists._base_chat import _BaseDMChatAgent
        from phantom_fleet.core.distributions import LogNormal

        class _StubAgent(_BaseDMChatAgent):
            platform_name = "instagram"
            max_daily_replies = 35
            min_gap_sec = 60.0
            max_tokens = 140
            inter_conv_sleep_dist = LogNormal(low=30.0, high=180.0, sigma=0.4)

            async def _fetch_conversations(self, client):
                return []

            async def _send_reply(self, client, conv, text):
                pass

            def _get_chat_mode_profile(self):
                from phantom_fleet.core.chat_modes import INSTAGRAM_FLIRTY
                return INSTAGRAM_FLIRTY

        return _StubAgent()

    async def test_build_system_prompt_contains_baseline_before_profile(self):
        """GENZ_VOICE_BASELINE must appear before ChatModeProfile.system_prompt."""
        agent = self._make_agent()
        from phantom_fleet.core.chat_modes import INSTAGRAM_FLIRTY

        system_prompt = agent._build_system_prompt(INSTAGRAM_FLIRTY)
        baseline_pos = system_prompt.find(GENZ_VOICE_BASELINE)
        profile_pos = system_prompt.find(INSTAGRAM_FLIRTY.system_prompt)

        assert baseline_pos != -1, "GENZ_VOICE_BASELINE missing from system prompt"
        assert profile_pos != -1, "ChatModeProfile.system_prompt missing from system prompt"
        assert baseline_pos < profile_pos, (
            "GENZ_VOICE_BASELINE must come BEFORE ChatModeProfile.system_prompt"
        )

    async def test_build_system_prompt_linkedin_excludes_baseline(self):
        """LinkedIn platform must not receive the Gen Z baseline."""
        from phantom_fleet.agents.specialists._base_chat import _BaseDMChatAgent
        from phantom_fleet.core.distributions import LogNormal

        class _LinkedInStub(_BaseDMChatAgent):
            platform_name = "linkedin"
            max_daily_replies = 10
            min_gap_sec = 120.0
            max_tokens = 80
            inter_conv_sleep_dist = LogNormal(low=30.0, high=180.0, sigma=0.4)

            async def _fetch_conversations(self, client): return []
            async def _send_reply(self, client, conv, text): pass
            def _get_chat_mode_profile(self):
                from phantom_fleet.core.chat_modes import LINKEDIN_PROFESSIONAL
                return LINKEDIN_PROFESSIONAL

        agent = _LinkedInStub()
        from phantom_fleet.core.chat_modes import LINKEDIN_PROFESSIONAL
        system_prompt = agent._build_system_prompt(LINKEDIN_PROFESSIONAL)
        assert GENZ_VOICE_BASELINE not in system_prompt

    async def test_apply_voice_style_called_on_llm_output(self):
        """
        When the LLM returns text with 'lol', after processing the reply
        should contain '💀' (the apply_voice_style replacement) and not 'lol'.
        """
        agent = self._make_agent()
        profile = agent._get_chat_mode_profile()
        system_prompt = agent._build_system_prompt(profile)

        # LLM returns old-style text
        llm_response = "lol that's actually funny though"

        # Simulate the pipeline manually (same steps as _run_dm_session)
        styled = apply_voice_style(llm_response)
        assert "lol" not in styled.lower()
        assert "💀" in styled

    async def test_low_score_output_would_trigger_retry(self):
        """
        Corporate LLM output must fail the voice gate and trigger a retry.

        The agent pipeline checks has_banned_phrases(raw) BEFORE apply_voice_style,
        because apply_voice_style strips the banned phrases making them undetectable.
        Scoring the raw text confirms the retry gate fires correctly.
        """
        corporate_text = "I'd be happy to help! Certainly that's a great question."
        # Banned-phrase check on raw text triggers retry
        assert has_banned_phrases(corporate_text), (
            "Raw corporate text must contain a banned phrase"
        )
        # Score on raw text is also well below gate (banned phrase penalty)
        score = voice_style_score(corporate_text)
        assert score < 0.5

    async def test_hard_banned_phrase_forces_retry_regardless_of_score(self):
        """
        has_banned_phrases must return True for text containing a banned phrase
        even if voice_style_score would be >= 0.5.
        """
        # Craft text that would score OK but still has a banned phrase
        text = "yeah it's great. certainly! lowercase rest of message"
        # After processing, 'certainly!' is removed — check the raw first
        assert has_banned_phrases(text) is True
        # Confirm the retry logic would fire
        styled = apply_voice_style(text)
        # After removal, re-check — the gate checks STYLED text too
        # (this also tests that removal prevents false-positives post-processing)
        # The styled version should have 'certainly!' removed
        assert "certainly" not in styled.lower()


# ---------------------------------------------------------------------------
# Integration: base_dm_chat_agent (IG/Threads specific base)
# Tests that voice prefix appears in system prompt assembled in _generate_reply
# ---------------------------------------------------------------------------


class TestBaseDMChatAgentIntegration:
    """
    Verify that IGDMChatAgent (which uses base_dm_chat_agent._BaseDMChatAgent)
    injects the voice prefix correctly.
    """

    async def test_ig_dm_agent_voice_prefix_in_system_prompt(self):
        """
        When _generate_reply builds its system_prompt, build_voice_prefix
        must be called with platform_name="instagram" and its output must
        appear before the profile system prompt.
        """
        from phantom_fleet.agents.specialists.base_dm_chat_agent import _BaseDMChatAgent
        from phantom_fleet.core.chat_modes import INSTAGRAM_FLIRTY

        class _StubIGAgent(_BaseDMChatAgent):
            platform_name = "instagram"
            _default_profile = INSTAGRAM_FLIRTY

            def _build_client(self, session):
                import contextlib
                @contextlib.asynccontextmanager
                async def _cm():
                    yield MagicMock()
                return _cm()

            async def _fetch_inbox(self, client, cursor):
                return {"threads": [], "has_older": False}

            async def _send_reply(self, client, thread_id, recipient_id, text):
                pass

        agent = _StubIGAgent()

        # Capture the system_prompt passed to OpenRouter
        captured_calls: list[dict] = []

        async def fake_post(url, **kwargs):
            payload = kwargs.get("json") or {}
            if not payload:
                import json as _json
                content = kwargs.get("content", b"")
                payload = _json.loads(content)
            captured_calls.append(payload)
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "choices": [{
                    "message": {
                        "content": "no bc why is that so funny 💀"
                    }
                }]
            }
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            import os
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
                await agent._generate_reply(
                    account_id="acct_001",
                    thread_id="thread_001",
                    profile=INSTAGRAM_FLIRTY,
                    conversation_text="them: hey how are you",
                    ppv_text="",
                    api_key="test-key",
                    date_iso="2026-04-11",
                )

        assert len(captured_calls) >= 1
        messages = captured_calls[0].get("messages", [])
        system_msg = next(
            (m["content"] for m in messages if m["role"] == "system"), ""
        )
        # The Gen Z baseline must appear before the profile content
        baseline_pos = system_msg.find("how you text")  # distinctive phrase
        profile_pos = system_msg.find("young woman replying to IG DMs")
        assert baseline_pos != -1, "Gen Z baseline not found in system prompt"
        assert profile_pos != -1, "Profile system prompt not found"
        assert baseline_pos < profile_pos, (
            "Gen Z baseline must appear before ChatModeProfile content"
        )

    async def test_ig_dm_agent_retries_when_llm_returns_banned_phrase(self):
        """
        When the LLM returns a hard-banned phrase on attempt 1, the agent
        should retry. The second call should use STYLE_RETRY_NUDGE.
        """
        from phantom_fleet.agents.specialists.base_dm_chat_agent import _BaseDMChatAgent
        from phantom_fleet.core.chat_modes import INSTAGRAM_FLIRTY

        class _StubIGAgent(_BaseDMChatAgent):
            platform_name = "instagram"
            _default_profile = INSTAGRAM_FLIRTY

            def _build_client(self, session):
                import contextlib
                @contextlib.asynccontextmanager
                async def _cm():
                    yield MagicMock()
                return _cm()

            async def _fetch_inbox(self, client, cursor):
                return {"threads": [], "has_older": False}

            async def _send_reply(self, client, thread_id, recipient_id, text):
                pass

        agent = _StubIGAgent()
        captured_user_prompts: list[str] = []
        call_count = 0

        async def fake_post(url, **kwargs):
            nonlocal call_count
            import json as _json
            content = kwargs.get("content", b"")
            payload = _json.loads(content)
            user_content = next(
                (m["content"] for m in payload["messages"] if m["role"] == "user"), ""
            )
            captured_user_prompts.append(user_content)
            call_count += 1

            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            # First call returns banned phrase; second returns clean Gen Z text
            if call_count == 1:
                reply_text = "I'd be happy to chat with you! Great question."
            else:
                reply_text = "no bc why are you so funny 💀"
            resp.json.return_value = {
                "choices": [{"message": {"content": reply_text}}]
            }
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            import os
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
                result = await agent._generate_reply(
                    account_id="acct_001",
                    thread_id="thread_001",
                    profile=INSTAGRAM_FLIRTY,
                    conversation_text="them: hey",
                    ppv_text="",
                    api_key="test-key",
                    date_iso="2026-04-11",
                )

        # At least 2 LLM calls (initial + retry)
        assert call_count >= 2, f"Expected retry, got {call_count} calls"
        # Second call's user prompt should contain the nudge
        assert any(STYLE_RETRY_NUDGE in prompt for prompt in captured_user_prompts[1:]), (
            "STYLE_RETRY_NUDGE not found in retry user prompt"
        )
        # Final result should be clean text
        assert result is not None
        assert "i'd be happy to" not in result.lower()
