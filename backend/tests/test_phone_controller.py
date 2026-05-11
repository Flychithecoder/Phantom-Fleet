"""Tests for PhoneController and PhoneFleet — all mocked (no real phones needed)."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from phantom_fleet.core.phone_controller import (
    PhoneController,
    PhoneFleet,
    PhoneState,
    CloneSlot,
    ProxyNotVerified,
    ADBCommandFailed,
    _platform_base_package,
    _extract_clone_index,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_phone(serial="192.168.1.42:5555") -> PhoneController:
    return PhoneController(serial=serial)


def proxy_ready_phone(serial="192.168.1.42:5555") -> PhoneController:
    p = make_phone(serial)
    p.state = PhoneState.PROXY_READY
    return p


# ---------------------------------------------------------------------------
# PhoneController — connectivity
# ---------------------------------------------------------------------------

@patch("phantom_fleet.core.phone_controller._run_adb")
async def test_is_online_returns_true_when_pong(mock_adb):
    mock_adb.return_value = "pong\n"
    phone = make_phone()
    result = await phone.is_online()
    assert result is True
    assert phone.state == PhoneState.ONLINE


@patch("phantom_fleet.core.phone_controller._run_adb")
async def test_is_online_returns_false_on_error(mock_adb):
    mock_adb.side_effect = ADBCommandFailed("device offline")
    phone = make_phone()
    result = await phone.is_online()
    assert result is False
    assert phone.state == PhoneState.OFFLINE


@patch("phantom_fleet.core.phone_controller._run_adb")
async def test_connect_success(mock_adb):
    mock_adb.return_value = "connected to 192.168.1.42:5555"
    phone = make_phone()
    result = await phone.connect()
    assert result is True
    assert phone.state == PhoneState.ONLINE


@patch("phantom_fleet.core.phone_controller._run_adb")
async def test_connect_failure(mock_adb):
    mock_adb.return_value = "unable to connect"
    phone = make_phone()
    result = await phone.connect()
    assert result is False


# ---------------------------------------------------------------------------
# Proxy safety gate
# ---------------------------------------------------------------------------

@patch("phantom_fleet.core.phone_controller._run_adb")
async def test_verify_proxy_active(mock_adb):
    mock_adb.return_value = "LISTEN 127.0.0.1:8089"
    phone = make_phone()
    phone.state = PhoneState.ONLINE
    result = await phone.verify_proxy()
    assert result is True
    assert phone.state == PhoneState.PROXY_READY


@patch("phantom_fleet.core.phone_controller._run_adb")
async def test_verify_proxy_inactive(mock_adb):
    mock_adb.return_value = ""   # nothing listening on 8089
    phone = make_phone()
    phone.state = PhoneState.ONLINE
    result = await phone.verify_proxy()
    assert result is False
    assert phone.state == PhoneState.ONLINE   # stays ONLINE, not PROXY_READY


async def test_verify_proxy_offline_returns_false():
    phone = make_phone()
    phone.state = PhoneState.OFFLINE
    result = await phone.verify_proxy()
    assert result is False


def test_require_proxy_raises_when_not_ready():
    phone = make_phone()
    phone.state = PhoneState.ONLINE
    with pytest.raises(ProxyNotVerified):
        phone.require_proxy()


def test_require_proxy_passes_when_ready():
    phone = proxy_ready_phone()
    phone.require_proxy()   # should not raise


# ---------------------------------------------------------------------------
# Clone discovery
# ---------------------------------------------------------------------------

@patch("phantom_fleet.core.phone_controller._run_adb")
async def test_discover_clones_instagram(mock_adb):
    mock_adb.return_value = (
        "package:com.instagram.android\n"
        "package:com.instagram.android.clone1\n"
        "package:com.instagram.android.clone2\n"
        "package:com.tinder\n"
    )
    phone = proxy_ready_phone()
    clones = await phone.discover_clones("instagram")
    assert len(clones) == 3
    assert all(c.platform == "instagram" for c in clones)
    assert any(c.clone_index == 0 for c in clones)
    assert any(c.clone_index == 1 for c in clones)
    assert any(c.clone_index == 2 for c in clones)


async def test_discover_clones_requires_proxy():
    phone = make_phone()
    phone.state = PhoneState.ONLINE
    with pytest.raises(ProxyNotVerified):
        await phone.discover_clones("instagram")


# ---------------------------------------------------------------------------
# Device info
# ---------------------------------------------------------------------------

@patch("phantom_fleet.core.phone_controller._run_adb")
async def test_get_device_info_returns_dict(mock_adb):
    responses = [
        "Samsung Galaxy S10 Lite\n",   # model
        "12\n",                         # android version
        "abc123def456abc1\n",           # android_id
        "T-Mobile\n",                   # carrier
        "310260\n",                     # mcc_mnc
        "en-US\n",                      # locale
    ]
    mock_adb.side_effect = responses
    phone = proxy_ready_phone()
    info = await phone.get_device_info()
    assert info["model"] == "Samsung Galaxy S10 Lite"
    assert info["android_version"] == "12"
    assert info["android_id"] == "abc123def456abc1"
    assert info["phone_serial"] == phone.serial


# ---------------------------------------------------------------------------
# PhoneFleet
# ---------------------------------------------------------------------------

@patch("phantom_fleet.core.phone_controller._run_adb")
async def test_fleet_scan_finds_devices(mock_adb):
    mock_adb.return_value = (
        "List of devices attached\n"
        "192.168.1.42:5555\tdevice\n"
        "192.168.1.43:5555\tdevice\n"
    )
    fleet = PhoneFleet()
    phones = await fleet.scan()
    assert len(phones) == 2
    assert all(p.state == PhoneState.ONLINE for p in phones)


@patch("phantom_fleet.core.phone_controller._run_adb")
async def test_fleet_scan_skips_offline(mock_adb):
    mock_adb.return_value = (
        "List of devices attached\n"
        "192.168.1.42:5555\tdevice\n"
        "192.168.1.99:5555\toffline\n"
    )
    fleet = PhoneFleet()
    phones = await fleet.scan()
    assert len(phones) == 1


async def test_fleet_ready_phones_filters_state():
    fleet = PhoneFleet()
    fleet.register("PHONE_A").state = PhoneState.PROXY_READY
    fleet.register("PHONE_B").state = PhoneState.ONLINE
    fleet.register("PHONE_C").state = PhoneState.OFFLINE
    ready = fleet.ready_phones()
    assert len(ready) == 1
    assert ready[0].serial == "PHONE_A"


async def test_fleet_status_summary():
    fleet = PhoneFleet()
    fleet.register("A").state = PhoneState.PROXY_READY
    fleet.register("B").state = PhoneState.PROXY_READY
    fleet.register("C").state = PhoneState.ONLINE
    fleet.register("D").state = PhoneState.OFFLINE
    summary = fleet.status_summary()
    assert summary["total"] == 4
    assert summary["proxy_ready"] == 2
    assert summary["online"] == 1
    assert summary["offline"] == 1


# ---------------------------------------------------------------------------
# Package helpers
# ---------------------------------------------------------------------------

def test_platform_base_packages():
    assert _platform_base_package("instagram") == "com.instagram.android"
    assert _platform_base_package("tiktok")    == "com.zhiliaoapp.musically"
    assert _platform_base_package("tinder")    == "com.tinder"
    assert _platform_base_package("telegram")  == "org.telegram.messenger"


def test_extract_clone_index():
    assert _extract_clone_index("com.instagram.android") == 0
    assert _extract_clone_index("com.instagram.android.clone1") == 1
    assert _extract_clone_index("com.instagram.android.clone2") == 2
    assert _extract_clone_index("com.instagram.android_clone_3") == 3
