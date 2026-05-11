"""
Tests for IGAccountReplacementAgent.

asyncio_mode = "auto" (set in pyproject.toml).
All DB and HTTP are mocked — no real network or DB calls.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from phantom_fleet.agents.specialists.ig_account_replacement_agent import (
    IGAccountReplacementAgent,
    DeadAccountRecord,
    SpareCredentialPool,
    ReplacementCycleResult,
    MAX_REPLACEMENTS_PER_CYCLE,
    SPARE_POOL_ESCALATE_THRESHOLD,
    _classify_cause,
    _parse_dt,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stale_iso() -> str:
    """Return an ISO timestamp 80 hours in the past — qualifies as stuck."""
    return (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()


def _make_dead_account(
    account_id: str | None = None,
    status: str = "dead",
    last_action_iso: str | None = None,
    warming_day: int = 5,
    dead_reason: str = "banned",
    replacement_id: str | None = None,
) -> dict:
    return {
        "id": account_id or str(uuid.uuid4()),
        "username": f"user_{uuid.uuid4().hex[:6]}",
        "phone_serial": "ABC123",
        "phone_id": None,
        "clone_package": "com.instagram.android",
        "status": status,
        "day_in_curve": warming_day,
        "warmup_day": warming_day,
        "dead_reason": dead_reason,
        "last_action_at": last_action_iso or _now_iso(),
        "replacement_account_id": replacement_id,
        "created_at": _now_iso(),
    }


def _make_repo(accounts: list[dict]) -> MagicMock:
    repo = MagicMock()
    repo.get_all = AsyncMock(return_value=accounts)
    repo.mark_dead = AsyncMock()
    repo.set_replacement_account_id = AsyncMock()
    return repo


def _make_provisioner(new_id: str | None = None) -> MagicMock:
    prov = MagicMock()
    prov.provision_one = AsyncMock(return_value=new_id or str(uuid.uuid4()))
    return prov


def _make_agent(
    accounts: list[dict],
    new_account_id: str | None = None,
    ping_alive: bool = True,
    funnel_enrollments: list[str] | None = None,
) -> IGAccountReplacementAgent:
    repo = _make_repo(accounts)
    prov = _make_provisioner(new_account_id)

    funnel_repo = MagicMock()
    funnel_repo.get_enrollments_for_account = AsyncMock(
        return_value=[{"enrollment_id": eid} for eid in (funnel_enrollments or [])]
    )
    funnel_repo.transfer_enrollment = AsyncMock()

    ping = AsyncMock(return_value=ping_alive)

    agent = IGAccountReplacementAgent(
        account_repo=repo,
        provisioner=prov,
        funnel_repo=funnel_repo,
        ping_session_fn=ping,
    )
    return agent


# ---------------------------------------------------------------------------
# Tests: detect_dead_accounts
# ---------------------------------------------------------------------------


async def test_dead_status_no_replacement_detected():
    """Accounts with status='dead' and no replacement_account_id are detected."""
    acc = _make_dead_account(status="dead", replacement_id=None)
    agent = _make_agent([acc])
    dead = await agent.detect_dead_accounts()
    assert len(dead) == 1
    assert dead[0].account_id == acc["id"]


async def test_dead_status_with_existing_replacement_skipped():
    """Accounts with status='dead' that already have a replacement are skipped."""
    acc = _make_dead_account(status="dead", replacement_id="already_replaced_id")
    agent = _make_agent([acc])
    dead = await agent.detect_dead_accounts()
    assert len(dead) == 0


async def test_active_account_not_detected():
    """Active, recently-active accounts are not detected as dead."""
    acc = _make_dead_account(status="active", last_action_iso=_now_iso(), warming_day=5)
    agent = _make_agent([acc])
    dead = await agent.detect_dead_accounts()
    assert len(dead) == 0


async def test_stuck_account_detected_on_ping_failure():
    """Account with last_action > 72h ago and failed ping is marked dead and returned."""
    acc = _make_dead_account(
        status="warming",
        last_action_iso=_stale_iso(),
        warming_day=10,
    )
    agent = _make_agent([acc], ping_alive=False)
    dead = await agent.detect_dead_accounts()
    assert len(dead) == 1
    assert dead[0].cause == "action_blocked_72h"
    # repo.mark_dead should have been called
    agent._accounts.mark_dead.assert_called_once()


async def test_stuck_account_still_alive_not_detected():
    """Account stale by timestamp but session still alive is NOT marked dead."""
    acc = _make_dead_account(
        status="warming",
        last_action_iso=_stale_iso(),
        warming_day=5,
    )
    agent = _make_agent([acc], ping_alive=True)
    dead = await agent.detect_dead_accounts()
    assert len(dead) == 0


async def test_warming_day_zero_not_stuck():
    """Accounts with warming_day=0 are never considered stuck (haven't started)."""
    acc = _make_dead_account(
        status="warming",
        last_action_iso=_stale_iso(),
        warming_day=0,
    )
    agent = _make_agent([acc], ping_alive=False)
    dead = await agent.detect_dead_accounts()
    assert len(dead) == 0


async def test_cause_classification():
    """dead_reason is correctly mapped to canonical cause labels."""
    assert _classify_cause("banned") == "banned"
    assert _classify_cause("session expired 401") == "session_expired"
    assert _classify_cause("action_blocked_72h") == "action_blocked_72h"
    assert _classify_cause("checkpoint required") == "checkpoint"
    assert _classify_cause("") == "unknown"
    assert _classify_cause("something_else")  # non-empty returns truncated string


# ---------------------------------------------------------------------------
# Tests: provision_replacement
# ---------------------------------------------------------------------------


async def test_replacement_provisioned_on_same_phone():
    """Replacement is provisioned with the dead account's phone_serial."""
    acc = _make_dead_account(status="dead")
    agent = _make_agent([acc])
    dead_record = DeadAccountRecord(
        account_id=acc["id"],
        username=acc["username"],
        phone_serial="SERIAL_XYZ",
        clone_package="com.instagram.android",
        died_at_iso=_now_iso(),
        cause="banned",
        warming_day=7,
        funnel_enrollments=[],
    )
    spare = {"username": "new_user", "password": "pass123"}
    new_id = await agent.provision_replacement(dead_record, spare)

    # provisioner was called with the dead account's phone_serial
    agent._provisioner.provision_one.assert_called_once()
    call_kwargs = agent._provisioner.provision_one.call_args.kwargs
    assert call_kwargs["phone_serial"] == "SERIAL_XYZ"
    assert isinstance(new_id, str)


async def test_funnel_enrollments_transferred_step_reset():
    """
    Funnel enrollments are transferred to the replacement account.
    transfer_enrollment is called once per enrollment_id.
    """
    enrollment_ids = ["enroll_001", "enroll_002", "enroll_003"]
    acc = _make_dead_account(status="dead")
    agent = _make_agent([acc], funnel_enrollments=enrollment_ids)

    dead_record = DeadAccountRecord(
        account_id=acc["id"],
        username=acc["username"],
        phone_serial="SER",
        clone_package="",
        died_at_iso=_now_iso(),
        cause="banned",
        warming_day=3,
        funnel_enrollments=enrollment_ids,
    )
    spare = {"username": "newu", "password": "p"}
    await agent.provision_replacement(dead_record, spare)

    assert agent._funnel.transfer_enrollment.call_count == len(enrollment_ids)

    # Verify reset_step=True was passed
    for call in agent._funnel.transfer_enrollment.call_args_list:
        assert call.kwargs.get("reset_step") is True


async def test_dead_record_updated_with_replacement_id():
    """After provisioning, set_replacement_account_id is called on the repo."""
    acc = _make_dead_account(status="dead")
    new_id = str(uuid.uuid4())
    agent = _make_agent([acc], new_account_id=new_id)

    dead_record = DeadAccountRecord(
        account_id=acc["id"],
        username=acc["username"],
        phone_serial="",
        clone_package="",
        died_at_iso=_now_iso(),
        cause="banned",
        warming_day=2,
        funnel_enrollments=[],
    )
    result_id = await agent.provision_replacement(dead_record, {"username": "u", "password": "p"})
    assert result_id == new_id
    agent._accounts.set_replacement_account_id.assert_called_once_with(acc["id"], new_id)


# ---------------------------------------------------------------------------
# Tests: run_replacement_cycle
# ---------------------------------------------------------------------------


async def test_replacement_cycle_processes_dead_accounts():
    """Cycle provisions replacements for dead accounts when spares are available."""
    dead_acc = _make_dead_account(status="dead")
    agent = _make_agent([dead_acc])
    pool = SpareCredentialPool(credentials=[{"username": "spare1", "password": "p1"}])
    result = await agent.run_replacement_cycle(pool)
    assert result.accounts_replaced == 1
    assert result.accounts_pending == 0


async def test_replacement_cycle_daily_cap_at_10():
    """Cycle processes at most MAX_REPLACEMENTS_PER_CYCLE accounts per run."""
    dead_accounts = [_make_dead_account(status="dead") for _ in range(15)]
    agent = _make_agent(dead_accounts)
    pool = SpareCredentialPool(
        credentials=[{"username": f"u{i}", "password": "p"} for i in range(15)]
    )
    result = await agent.run_replacement_cycle(pool)
    assert result.accounts_replaced == MAX_REPLACEMENTS_PER_CYCLE
    assert result.accounts_pending == 15 - MAX_REPLACEMENTS_PER_CYCLE


async def test_spare_pool_alert_when_low():
    """Escalation fires and result.escalated_pool_low=True when pool < threshold."""
    dead_acc = _make_dead_account(status="dead")
    agent = _make_agent([dead_acc])
    # Pool has just enough to process the account but drops below threshold
    pool = SpareCredentialPool(
        credentials=[{"username": f"u{i}", "password": "p"} for i in range(SPARE_POOL_ESCALATE_THRESHOLD - 1)],
        min_pool_size=10,
    )
    result = await agent.run_replacement_cycle(pool)
    assert result.escalated_pool_low is True


async def test_spare_pool_healthy_no_escalation():
    """No escalation when spare pool remains healthy after cycle."""
    dead_acc = _make_dead_account(status="dead")
    agent = _make_agent([dead_acc])
    pool = SpareCredentialPool(
        credentials=[{"username": f"u{i}", "password": "p"} for i in range(20)],
        min_pool_size=10,
    )
    result = await agent.run_replacement_cycle(pool)
    assert result.escalated_pool_low is False


async def test_no_spares_accounts_pending():
    """Dead accounts stay pending when spare pool is empty."""
    dead_acc = _make_dead_account(status="dead")
    agent = _make_agent([dead_acc])
    pool = SpareCredentialPool(credentials=[])
    result = await agent.run_replacement_cycle(pool)
    assert result.accounts_replaced == 0
    assert result.accounts_pending == 1


async def test_spare_pool_remaining_count():
    """spare_pool_remaining reflects actual remaining credentials after cycle."""
    dead_accs = [_make_dead_account(status="dead") for _ in range(3)]
    agent = _make_agent(dead_accs)
    initial_spares = 10
    pool = SpareCredentialPool(
        credentials=[{"username": f"u{i}", "password": "p"} for i in range(initial_spares)],
        min_pool_size=10,
    )
    result = await agent.run_replacement_cycle(pool)
    assert result.spare_pool_remaining == initial_spares - 3
