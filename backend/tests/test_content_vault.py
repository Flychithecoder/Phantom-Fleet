"""
Tests for ContentVault (core) and the /api/content-vault routes.

Coverage:
    add_item:    file saved to correct path, metadata indexed
    get_items:   platform filter, persona filter, unused_only filter
    mark_used:   increments used_count, sets last_used_iso
    push endpoint: auth header validated (wrong key → 403), file saved, metadata stored
    deliver endpoint: calls adb_push with correct path
    stats:       correct totals by platform

Run with:
    pytest tests/test_content_vault.py -v
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from phantom_fleet.core.content_vault import (
    ALLOWED_MIME_TYPES,
    ContentVault,
    get_vault,
)
from phantom_fleet.api.routes.content_vault import router as vault_router

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_KEY = "test-contentforge-key-abc123"

# 1x1 white JPEG (smallest valid JPEG, 631 bytes)
TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e\x1d"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04"
    b"\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07"
    b'"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br'
    b"\x82\t\n\x16\x17\x18\x19\x1a%&'()*456789:CDEFGHIJSTUVWXYZ"
    b"cdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95"
    b"\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3"
    b"\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca"
    b"\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7"
    b"\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd2\x8a(\x03\xff\xd9"
)

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def media_dir(tmp_path):
    """Isolated temporary media directory for each test."""
    return str(tmp_path / "vault_media")


@pytest.fixture
def vault(media_dir):
    """A fresh ContentVault instance pointed at an isolated temp dir."""
    return ContentVault(media_dir=media_dir)


@pytest.fixture
def app(media_dir):
    """
    Minimal FastAPI app with the content_vault router mounted.
    Sets CONTENTFORGE_API_KEY and PHANTOM_MEDIA_DIR env vars, and patches
    get_vault() so tests use the same isolated vault instance.
    """
    test_app = FastAPI()
    test_app.include_router(vault_router, prefix="/api/content-vault")

    isolated_vault = ContentVault(media_dir=media_dir)

    with (
        patch.dict(
            os.environ,
            {
                "CONTENTFORGE_API_KEY": FAKE_KEY,
                "PHANTOM_MEDIA_DIR": media_dir,
            },
        ),
        patch(
            "phantom_fleet.api.routes.content_vault.get_vault",
            return_value=isolated_vault,
        ),
    ):
        yield test_app, isolated_vault


@pytest.fixture
async def client(app) -> AsyncGenerator[tuple[AsyncClient, ContentVault], None]:
    test_app, isolated_vault = app
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac, isolated_vault


# ---------------------------------------------------------------------------
# ContentVault core tests
# ---------------------------------------------------------------------------


class TestAddItem:
    async def test_file_saved_to_correct_path(self, vault: ContentVault, media_dir: str):
        """File is written to {media_dir}/{item_id}.jpg."""
        item = await vault.add_item(
            TINY_JPEG,
            {
                "file_type": "image/jpeg",
                "caption": "test caption",
                "platform_tags": ["instagram"],
                "content_tags": ["sfw"],
                "persona_id": None,
                "source": "manual_upload",
            },
        )
        expected_path = os.path.join(media_dir, f"{item.item_id}.jpg")
        assert item.file_path == expected_path
        assert os.path.exists(expected_path)
        assert open(expected_path, "rb").read() == TINY_JPEG

    async def test_metadata_indexed(self, vault: ContentVault):
        """Metadata is persisted in the JSON index and readable back."""
        item = await vault.add_item(
            TINY_JPEG,
            {
                "file_type": "image/jpeg",
                "caption": "hello world",
                "platform_tags": ["instagram", "threads"],
                "content_tags": ["lifestyle"],
                "persona_id": "tatiana_001",
                "source": "contentforge",
            },
        )
        assert item.caption == "hello world"
        assert "instagram" in item.platform_tags
        assert item.persona_id == "tatiana_001"
        assert item.source == "contentforge"
        assert item.used_count == 0
        assert item.last_used_iso is None

        # Re-read from disk (new vault instance pointing at same dir)
        vault2 = ContentVault(media_dir=vault._media_dir)
        items = await vault2.get_items(limit=100)
        ids = {i.item_id for i in items}
        assert item.item_id in ids

    async def test_png_saved_with_correct_extension(self, vault: ContentVault, media_dir: str):
        """PNG files are saved with .png extension."""
        item = await vault.add_item(
            TINY_PNG,
            {"file_type": "image/png", "caption": "", "platform_tags": [], "content_tags": [], "source": "manual_upload"},
        )
        assert item.file_path.endswith(".png")

    async def test_rejects_unsupported_mime(self, vault: ContentVault):
        """add_item raises ValueError for disallowed MIME types."""
        with pytest.raises(ValueError, match="Unsupported file_type"):
            await vault.add_item(b"data", {"file_type": "image/gif", "source": "manual_upload"})

    async def test_rejects_oversized_file(self, vault: ContentVault):
        """add_item raises ValueError when file exceeds 100 MB."""
        big = b"x" * (101 * 1024 * 1024)
        with pytest.raises(ValueError, match="exceeds limit"):
            await vault.add_item(big, {"file_type": "image/jpeg", "source": "manual_upload"})


class TestGetItems:
    async def test_platform_filter(self, vault: ContentVault):
        """get_items(platform=...) returns only items with that platform tag."""
        await vault.add_item(
            TINY_JPEG,
            {"file_type": "image/jpeg", "caption": "ig", "platform_tags": ["instagram"], "content_tags": [], "source": "manual_upload"},
        )
        await vault.add_item(
            TINY_JPEG,
            {"file_type": "image/jpeg", "caption": "tt", "platform_tags": ["tiktok"], "content_tags": [], "source": "manual_upload"},
        )
        items = await vault.get_items(platform="instagram")
        assert all("instagram" in i.platform_tags for i in items)
        assert len(items) == 1
        assert items[0].caption == "ig"

    async def test_persona_filter(self, vault: ContentVault):
        """get_items(persona_id=...) returns persona-specific AND persona=None items."""
        await vault.add_item(
            TINY_JPEG,
            {"file_type": "image/jpeg", "caption": "p1", "platform_tags": [], "content_tags": [], "persona_id": "p1", "source": "manual_upload"},
        )
        await vault.add_item(
            TINY_JPEG,
            {"file_type": "image/jpeg", "caption": "any", "platform_tags": [], "content_tags": [], "persona_id": None, "source": "manual_upload"},
        )
        await vault.add_item(
            TINY_JPEG,
            {"file_type": "image/jpeg", "caption": "p2", "platform_tags": [], "content_tags": [], "persona_id": "p2", "source": "manual_upload"},
        )
        items = await vault.get_items(persona_id="p1")
        captions = {i.caption for i in items}
        # Should include "p1" and "any" (persona=None), but NOT "p2"
        assert "p1" in captions
        assert "any" in captions
        assert "p2" not in captions

    async def test_unused_only_filter(self, vault: ContentVault):
        """get_items(unused_only=True) excludes already-used items."""
        item_a = await vault.add_item(
            TINY_JPEG,
            {"file_type": "image/jpeg", "caption": "a", "platform_tags": [], "content_tags": [], "source": "manual_upload"},
        )
        item_b = await vault.add_item(
            TINY_JPEG,
            {"file_type": "image/jpeg", "caption": "b", "platform_tags": [], "content_tags": [], "source": "manual_upload"},
        )
        await vault.mark_used(item_a.item_id)

        unused = await vault.get_items(unused_only=True)
        ids = {i.item_id for i in unused}
        assert item_a.item_id not in ids
        assert item_b.item_id in ids

    async def test_limit_respected(self, vault: ContentVault):
        """get_items(limit=N) returns at most N items."""
        for _ in range(5):
            await vault.add_item(
                TINY_JPEG,
                {"file_type": "image/jpeg", "caption": "", "platform_tags": [], "content_tags": [], "source": "manual_upload"},
            )
        items = await vault.get_items(limit=3)
        assert len(items) <= 3


class TestMarkUsed:
    async def test_increments_used_count(self, vault: ContentVault):
        """mark_used increments used_count each call."""
        item = await vault.add_item(
            TINY_JPEG,
            {"file_type": "image/jpeg", "caption": "", "platform_tags": [], "content_tags": [], "source": "manual_upload"},
        )
        assert item.used_count == 0
        await vault.mark_used(item.item_id)
        await vault.mark_used(item.item_id)

        # Read back from a fresh vault to confirm persistence
        vault2 = ContentVault(media_dir=vault._media_dir)
        items = await vault2.get_items(limit=100)
        found = next(i for i in items if i.item_id == item.item_id)
        assert found.used_count == 2

    async def test_sets_last_used_iso(self, vault: ContentVault):
        """mark_used sets last_used_iso to a non-None ISO timestamp."""
        item = await vault.add_item(
            TINY_JPEG,
            {"file_type": "image/jpeg", "caption": "", "platform_tags": [], "content_tags": [], "source": "manual_upload"},
        )
        assert item.last_used_iso is None
        await vault.mark_used(item.item_id)

        vault2 = ContentVault(media_dir=vault._media_dir)
        items = await vault2.get_items(limit=100)
        found = next(i for i in items if i.item_id == item.item_id)
        assert found.last_used_iso is not None

    async def test_raises_key_error_unknown_id(self, vault: ContentVault):
        """mark_used raises KeyError for an unknown item_id."""
        with pytest.raises(KeyError):
            await vault.mark_used("nonexistent-id-000")


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


class TestPushEndpoint:
    async def test_correct_key_accepted(self, client):
        ac, vault = client
        data = {
            "caption": "hello from ContentForge",
            "platform_tags": ["instagram"],
            "content_tags": ["sfw"],
            "persona_id": "tatiana_001",
            "source": "contentforge",
        }
        response = await ac.post(
            "/api/content-vault/push",
            headers={"X-ContentForge-Key": FAKE_KEY},
            files={"file": ("test.jpg", TINY_JPEG, "image/jpeg")},
            data={"metadata": json.dumps(data)},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "contentforge"
        assert body["item_id"]

    async def test_wrong_key_returns_403(self, client):
        """Wrong X-ContentForge-Key header must yield 403."""
        ac, _ = client
        response = await ac.post(
            "/api/content-vault/push",
            headers={"X-ContentForge-Key": "wrong-key"},
            files={"file": ("test.jpg", TINY_JPEG, "image/jpeg")},
            data={"metadata": json.dumps({"source": "contentforge"})},
        )
        assert response.status_code == 403

    async def test_missing_key_returns_403(self, client):
        """Missing X-ContentForge-Key header must yield 403."""
        ac, _ = client
        response = await ac.post(
            "/api/content-vault/push",
            files={"file": ("test.jpg", TINY_JPEG, "image/jpeg")},
            data={"metadata": json.dumps({"source": "contentforge"})},
        )
        assert response.status_code == 403

    async def test_file_saved_to_vault(self, client):
        """After /push the item appears in the vault and the file is on disk."""
        ac, vault = client
        response = await ac.post(
            "/api/content-vault/push",
            headers={"X-ContentForge-Key": FAKE_KEY},
            files={"file": ("test.jpg", TINY_JPEG, "image/jpeg")},
            data={"metadata": json.dumps({"caption": "saved check", "platform_tags": ["instagram"], "content_tags": [], "source": "contentforge"})},
        )
        assert response.status_code == 200
        item_id = response.json()["item_id"]

        items = await vault.get_items(limit=100)
        found = next((i for i in items if i.item_id == item_id), None)
        assert found is not None
        assert os.path.exists(found.file_path)

    async def test_metadata_stored_correctly(self, client):
        """Caption and tags from the push metadata are persisted."""
        ac, vault = client
        response = await ac.post(
            "/api/content-vault/push",
            headers={"X-ContentForge-Key": FAKE_KEY},
            files={"file": ("test.jpg", TINY_JPEG, "image/jpeg")},
            data={"metadata": json.dumps({
                "caption": "my contentforge caption",
                "platform_tags": ["instagram", "threads"],
                "content_tags": ["fitness", "sfw"],
                "persona_id": "luna_002",
                "source": "contentforge",
            })},
        )
        assert response.status_code == 200
        item_id = response.json()["item_id"]

        items = await vault.get_items(limit=100)
        found = next(i for i in items if i.item_id == item_id)
        assert found.caption == "my contentforge caption"
        assert "threads" in found.platform_tags
        assert "fitness" in found.content_tags
        assert found.persona_id == "luna_002"

    async def test_disallowed_mime_returns_415(self, client):
        """GIF upload to /push must return 415."""
        ac, _ = client
        response = await ac.post(
            "/api/content-vault/push",
            headers={"X-ContentForge-Key": FAKE_KEY},
            files={"file": ("test.gif", b"GIF89a", "image/gif")},
            data={"metadata": json.dumps({"source": "contentforge"})},
        )
        assert response.status_code == 415


class TestDeliverEndpoint:
    async def test_calls_adb_push_with_correct_path(self, client):
        """
        POST /api/content-vault/{item_id}/deliver must call phone.adb_push
        with the item's local file_path and the expected remote gallery path.
        """
        ac, vault = client

        # Seed an item in the vault
        item = await vault.add_item(
            TINY_JPEG,
            {
                "file_type": "image/jpeg",
                "caption": "deliver me",
                "platform_tags": ["instagram"],
                "content_tags": [],
                "source": "manual_upload",
            },
        )
        filename = os.path.basename(item.file_path)
        expected_remote = f"/sdcard/DCIM/PhantomFleet/{filename}"

        # Build a mock fleet with a mock phone
        mock_phone = MagicMock()
        mock_phone.adb_push = AsyncMock(return_value=None)
        mock_phone.adb_shell = AsyncMock(return_value="")

        mock_fleet = MagicMock()
        mock_fleet.get = MagicMock(return_value=mock_phone)

        mock_ctx = MagicMock()
        mock_ctx.fleet = mock_fleet

        # Patch app.state.ctx
        from phantom_fleet.api.routes import content_vault as cv_module

        app_obj = ac._transport.app  # type: ignore[attr-defined]
        app_obj.state.ctx = mock_ctx

        response = await ac.post(
            f"/api/content-vault/{item.item_id}/deliver",
            params={"phone_serial": "RF8N81XYX4J"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["delivered"] is True
        assert body["remote_path"] == expected_remote

        mock_phone.adb_push.assert_awaited_once_with(item.file_path, expected_remote)

    async def test_unknown_item_returns_404(self, client):
        ac, vault = client

        mock_phone = MagicMock()
        mock_fleet = MagicMock()
        mock_fleet.get = MagicMock(return_value=mock_phone)
        mock_ctx = MagicMock()
        mock_ctx.fleet = mock_fleet
        app_obj = ac._transport.app  # type: ignore[attr-defined]
        app_obj.state.ctx = mock_ctx

        response = await ac.post(
            "/api/content-vault/nonexistent-id-999/deliver",
            params={"phone_serial": "RF8N81XYX4J"},
        )
        assert response.status_code == 404


class TestStatsEndpoint:
    async def test_correct_totals_by_platform(self, client):
        """GET /api/content-vault/stats returns correct per-platform counts."""
        ac, vault = client

        for _ in range(3):
            await vault.add_item(
                TINY_JPEG,
                {"file_type": "image/jpeg", "caption": "", "platform_tags": ["instagram"], "content_tags": [], "source": "manual_upload"},
            )
        await vault.add_item(
            TINY_JPEG,
            {"file_type": "image/jpeg", "caption": "", "platform_tags": ["tiktok"], "content_tags": [], "source": "contentforge"},
        )

        response = await ac.get("/api/content-vault/stats")
        assert response.status_code == 200
        stats = response.json()
        assert stats["total_items"] == 4
        assert stats["by_platform"].get("instagram") == 3
        assert stats["by_platform"].get("tiktok") == 1

    async def test_unused_items_count(self, client):
        """Stats unused_items count is correct after marking some used."""
        ac, vault = client

        items = []
        for _ in range(4):
            item = await vault.add_item(
                TINY_JPEG,
                {"file_type": "image/jpeg", "caption": "", "platform_tags": [], "content_tags": [], "source": "manual_upload"},
            )
            items.append(item)

        await vault.mark_used(items[0].item_id)
        await vault.mark_used(items[1].item_id)

        response = await ac.get("/api/content-vault/stats")
        assert response.status_code == 200
        stats = response.json()
        assert stats["total_items"] == 4
        assert stats["unused_items"] == 2
