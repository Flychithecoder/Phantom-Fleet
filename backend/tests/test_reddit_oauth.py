"""
Tests for phantom_fleet.core.reddit_oauth

Covers:
    - generate_device_id: format (32 hex chars), stability (same input → same output),
      uniqueness (different accounts → different IDs)
    - generate_loid: format (~22-24 base64url chars), stability, uniqueness
    - _basic_auth: correct base64url encoding
    - OAuthTokens dataclass construction
    - password_grant: correct request structure (mocked httpx), error handling
    - refresh_access_token: correct request structure, rotation handling
    - Fleet-scale checks: device_id and loid distributions across 1000 accounts
"""
from __future__ import annotations

import base64
import re
import time
from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from phantom_fleet.core.reddit_oauth import (
    OAuthTokens,
    _basic_auth,
    _fetch_user_id,
    generate_device_id,
    generate_loid,
    get_client_id,
    get_client_secret,
    password_grant,
    refresh_access_token,
)


# ---------------------------------------------------------------------------
# generate_device_id
# ---------------------------------------------------------------------------

class TestGenerateDeviceId:

    def test_format_32_hex_chars(self):
        did = generate_device_id("account_abc123")
        assert len(did) == 32, f"Expected 32 chars, got {len(did)}"
        assert re.fullmatch(r"[0-9a-f]{32}", did), f"Not lowercase hex: {did}"

    def test_stable_same_input(self):
        did1 = generate_device_id("account_xyz")
        did2 = generate_device_id("account_xyz")
        assert did1 == did2

    def test_unique_different_accounts(self):
        ids = {generate_device_id(f"account_{i}") for i in range(100)}
        assert len(ids) == 100, "Collision detected in device IDs"

    def test_fleet_distribution_no_monoculture(self):
        """1000 accounts must not share a device_id — no monoculture."""
        ids = [generate_device_id(f"acct_{i}") for i in range(1000)]
        unique = len(set(ids))
        assert unique == 1000, f"Only {unique}/1000 unique device IDs — monoculture detected"

    def test_no_common_prefix(self):
        """First 4 chars should vary across accounts — no fixed prefix."""
        prefixes = {generate_device_id(f"acct_{i}")[:4] for i in range(50)}
        assert len(prefixes) > 10, "Too few distinct prefixes — possible fixed prefix bug"


# ---------------------------------------------------------------------------
# generate_loid
# ---------------------------------------------------------------------------

class TestGenerateLoid:

    def test_format_base64url(self):
        loid = generate_loid("account_abc123")
        # base64url: A-Z a-z 0-9 - _ (no padding =)
        assert re.fullmatch(r"[A-Za-z0-9_\-]+", loid), f"Not valid base64url: {loid}"

    def test_length_reasonable(self):
        loid = generate_loid("account_abc")
        # 18 bytes → 24 base64 chars before stripping padding
        assert 20 <= len(loid) <= 28, f"Unexpected loid length: {len(loid)}"

    def test_stable(self):
        loid1 = generate_loid("test_account")
        loid2 = generate_loid("test_account")
        assert loid1 == loid2

    def test_unique_per_account(self):
        loids = {generate_loid(f"account_{i}") for i in range(100)}
        assert len(loids) == 100

    def test_fleet_no_monoculture(self):
        loids = [generate_loid(f"acct_{i}") for i in range(1000)]
        assert len(set(loids)) == 1000


# ---------------------------------------------------------------------------
# _basic_auth
# ---------------------------------------------------------------------------

class TestBasicAuth:

    def test_format(self):
        header = _basic_auth("my_client_id", "my_secret")
        assert header.startswith("Basic ")
        encoded = header[len("Basic "):]
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "my_client_id:my_secret"

    def test_empty_secret(self):
        """Installed apps use empty client_secret — must still produce valid header."""
        header = _basic_auth("client_id", "")
        encoded = header[len("Basic "):]
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "client_id:"


# ---------------------------------------------------------------------------
# OAuthTokens dataclass
# ---------------------------------------------------------------------------

class TestOAuthTokens:

    def test_construction(self):
        tokens = OAuthTokens(
            access_token="abc123",
            refresh_token="refresh_xyz",
            user_id="t2_abc",
            expires_at=time.time() + 3600,
        )
        assert tokens.access_token == "abc123"
        assert tokens.refresh_token == "refresh_xyz"
        assert tokens.user_id == "t2_abc"
        assert tokens.expires_at > time.time()

    def test_has_all_fields(self):
        field_names = {f.name for f in fields(OAuthTokens)}
        assert {"access_token", "refresh_token", "user_id", "expires_at"} <= field_names


# ---------------------------------------------------------------------------
# get_client_id / get_client_secret
# ---------------------------------------------------------------------------

class TestEnvHelpers:

    def test_get_client_id_missing_raises(self, monkeypatch):
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        with pytest.raises(RuntimeError, match="REDDIT_CLIENT_ID"):
            get_client_id()

    def test_get_client_id_from_env(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID", "test_cid")
        assert get_client_id() == "test_cid"

    def test_get_client_secret_defaults_empty(self, monkeypatch):
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
        assert get_client_secret() == ""

    def test_get_client_secret_from_env(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test_sec")
        assert get_client_secret() == "test_sec"


# ---------------------------------------------------------------------------
# password_grant (mocked HTTP)
# ---------------------------------------------------------------------------

def _mock_token_response(access_token="tok_abc", refresh_token="ref_xyz"):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "token_type":    "bearer",
        "expires_in":    3600,
        "scope":         "identity submit",
    }
    return resp


def _mock_me_response(user_id="abc123"):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"id": user_id, "name": "test_user"}
    return resp


@pytest.mark.asyncio
class TestPasswordGrant:

    async def test_returns_oauth_tokens(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID",     "test_cid")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test_sec")

        mock_post = AsyncMock(return_value=_mock_token_response())
        mock_get  = AsyncMock(return_value=_mock_me_response("u123"))

        with patch("phantom_fleet.core.reddit_oauth.httpx.AsyncClient") as mock_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__  = AsyncMock(return_value=False)
            mock_ctx.post = mock_post
            mock_ctx.get  = mock_get
            mock_cls.return_value = mock_ctx

            tokens = await password_grant("test_user", "test_pass")

        assert tokens.access_token  == "tok_abc"
        assert tokens.refresh_token == "ref_xyz"
        assert tokens.expires_at    >  time.time()

    async def test_raises_on_401(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID",     "test_cid")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test_sec")

        bad_resp = MagicMock()
        bad_resp.status_code = 401
        bad_resp.headers = {}
        bad_resp.text = "Unauthorized"

        with patch("phantom_fleet.core.reddit_oauth.httpx.AsyncClient") as mock_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__  = AsyncMock(return_value=False)
            mock_ctx.post = AsyncMock(return_value=bad_resp)
            mock_cls.return_value = mock_ctx

            with pytest.raises(RuntimeError, match="401"):
                await password_grant("user", "wrong_pass")

    async def test_raises_on_error_field(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID",     "test_cid")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test_sec")

        err_resp = MagicMock()
        err_resp.status_code = 200
        err_resp.json.return_value = {"error": "invalid_grant"}

        with patch("phantom_fleet.core.reddit_oauth.httpx.AsyncClient") as mock_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__  = AsyncMock(return_value=False)
            mock_ctx.post = AsyncMock(return_value=err_resp)
            mock_cls.return_value = mock_ctx

            with pytest.raises(RuntimeError, match="invalid_grant"):
                await password_grant("user", "pass")

    async def test_raises_on_rate_limit(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID",     "test_cid")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test_sec")

        rl_resp = MagicMock()
        rl_resp.status_code = 429
        rl_resp.headers = {"Retry-After": "60"}
        rl_resp.text = "Too Many Requests"

        with patch("phantom_fleet.core.reddit_oauth.httpx.AsyncClient") as mock_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__  = AsyncMock(return_value=False)
            mock_ctx.post = AsyncMock(return_value=rl_resp)
            mock_cls.return_value = mock_ctx

            with pytest.raises(RuntimeError, match="rate limited"):
                await password_grant("user", "pass")

    async def test_missing_client_id_raises(self, monkeypatch):
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        with pytest.raises(RuntimeError, match="REDDIT_CLIENT_ID"):
            await password_grant("user", "pass")


# ---------------------------------------------------------------------------
# refresh_access_token (mocked HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRefreshAccessToken:

    async def test_returns_new_token(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID",     "test_cid")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test_sec")

        refresh_resp = MagicMock()
        refresh_resp.status_code = 200
        refresh_resp.json.return_value = {
            "access_token": "new_tok_xyz",
            "token_type":   "bearer",
            "expires_in":   3600,
        }

        with patch("phantom_fleet.core.reddit_oauth.httpx.AsyncClient") as mock_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__  = AsyncMock(return_value=False)
            mock_ctx.post = AsyncMock(return_value=refresh_resp)
            mock_cls.return_value = mock_ctx

            tokens = await refresh_access_token(
                refresh_token="old_refresh",
                username="test_user",
            )

        assert tokens.access_token == "new_tok_xyz"
        # When Reddit doesn't rotate the refresh token, we keep the old one
        assert tokens.refresh_token == "old_refresh"

    async def test_rotates_refresh_token_if_provided(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID",     "test_cid")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test_sec")

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "access_token":  "new_access",
            "refresh_token": "new_refresh",
            "expires_in":    3600,
        }

        with patch("phantom_fleet.core.reddit_oauth.httpx.AsyncClient") as mock_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__  = AsyncMock(return_value=False)
            mock_ctx.post = AsyncMock(return_value=resp)
            mock_cls.return_value = mock_ctx

            tokens = await refresh_access_token("old_ref", "user")

        assert tokens.refresh_token == "new_refresh"

    async def test_raises_on_revoked_token(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID",     "test_cid")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test_sec")

        bad = MagicMock()
        bad.status_code = 401
        bad.headers = {}
        bad.text = "Unauthorized"

        with patch("phantom_fleet.core.reddit_oauth.httpx.AsyncClient") as mock_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__  = AsyncMock(return_value=False)
            mock_ctx.post = AsyncMock(return_value=bad)
            mock_cls.return_value = mock_ctx

            with pytest.raises(RuntimeError, match="invalid or revoked"):
                await refresh_access_token("bad_ref", "user")


# ---------------------------------------------------------------------------
# Fleet-scale distribution checks
# ---------------------------------------------------------------------------

class TestFleetScaleDistributions:
    """
    Verify that device_id and loid distributions across a simulated fleet
    show no monoculture, no fixed prefixes, and adequate entropy.
    Follows CLAUDE.md 20K-account cluster analysis rules.
    """

    FLEET_SIZE = 1000

    def test_device_id_no_shared_prefix_4chars(self):
        """First 4 hex chars should vary — fixed prefix = cluster fingerprint."""
        prefixes = [generate_device_id(f"fleet_acct_{i}")[:4] for i in range(self.FLEET_SIZE)]
        unique_prefixes = len(set(prefixes))
        # With 65536 possible 4-char hex prefixes, 1000 accounts should produce ~620+ unique
        assert unique_prefixes > 200, (
            f"Only {unique_prefixes} unique 4-char prefixes across {self.FLEET_SIZE} accounts "
            "— suspicious fixed-prefix pattern"
        )

    def test_loid_no_shared_prefix_4chars(self):
        prefixes = [generate_loid(f"fleet_acct_{i}")[:4] for i in range(self.FLEET_SIZE)]
        unique_prefixes = len(set(prefixes))
        assert unique_prefixes > 100, (
            f"Only {unique_prefixes} unique loid prefixes — suspicious pattern"
        )

    def test_device_id_entropy_all_unique(self):
        ids = [generate_device_id(f"fleet_acct_{i}") for i in range(self.FLEET_SIZE)]
        assert len(set(ids)) == self.FLEET_SIZE

    def test_loid_entropy_all_unique(self):
        loids = [generate_loid(f"fleet_acct_{i}") for i in range(self.FLEET_SIZE)]
        assert len(set(loids)) == self.FLEET_SIZE

    def test_device_id_and_loid_are_independent(self):
        """device_id and loid for the same account must differ."""
        for i in range(50):
            account_id = f"acct_{i}"
            did  = generate_device_id(account_id)
            loid = generate_loid(account_id)
            # They should not be equal (different seeds)
            assert did[:16] != loid[:16], (
                f"device_id and loid share prefix for {account_id} — same seed bug"
            )
