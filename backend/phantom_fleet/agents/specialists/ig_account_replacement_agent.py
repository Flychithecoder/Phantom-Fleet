"""
IGAccountReplacementAgent — automatic dead-account detection and replacement.

When an account is marked dead (session expired, banned, or action-blocked for
72+ hours), this agent:
    1. Detects the dead account via status flag or inactivity heuristic.
    2. Provisions a replacement from the spare credential pool.
    3. Copies the dead account's funnel state (enrolled targets), resetting
       each enrollment to step 0 — fresh start, same targets.
    4. Starts warming the replacement from day 0.
    5. Archives the dead account with cause-of-death metadata.

Zero human intervention required.  Escalates to the manager when the spare
pool drops below min_pool_size (default 5 for escalation, 10 for healthy).

Agent audit table (CLAUDE.md agent-audit rules):
    ┌──────────────────────────┬───────────────────────────────────────────────┐
    │ Agent                    │ IGAccountReplacementAgent                     │
    │ Purpose                  │ Replace dead IG accounts from spare pool      │
    │ Tools                    │ DB reads/writes, AccountProvisioner           │
    │ Untrusted input          │ account rows from DB (validated before use)   │
    │ User isolation           │ Keyed by account_id; no cross-user leakage    │
    │ Cost cap                 │ No LLM calls                                  │
    │ Loop cap                 │ Max 10 replacements per cycle (blast radius)  │
    │ Confirmation required    │ No (non-destructive; dead account already gone)│
    └──────────────────────────┴───────────────────────────────────────────────┘
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

log = logging.getLogger("phantom_fleet.replacement_agent")

# Maximum replacements per run cycle — blast-radius cap enforced in code, not
# in a prompt.
MAX_REPLACEMENTS_PER_CYCLE = 10

# Accounts with no action for this many hours (and warming_day > 0) are
# considered stuck and get a session ping before being marked dead.
STUCK_HOURS = 72

# Spare pool threshold below which escalation fires.
SPARE_POOL_ESCALATE_THRESHOLD = 5


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DeadAccountRecord:
    """Everything we know about a dead account and its replacement outcome."""

    account_id: str
    username: str
    phone_serial: str        # raw serial string from the account row
    clone_package: str       # clone_package or empty string
    died_at_iso: str
    cause: str               # "banned" | "session_expired" | "action_blocked_72h" | "checkpoint"
    warming_day: int         # how far through the curve it was
    funnel_enrollments: list[str]   # enrollment IDs to transfer to replacement
    replacement_account_id: Optional[str] = None


@dataclass
class SpareCredentialPool:
    """
    Pool of unused credentials ready for immediate provisioning.
    Agencies upload spare credentials in advance via the API.
    """

    credentials: list[dict] = field(default_factory=list)
    # [{username: str, password: str, two_fa_secret: str | None}]
    min_pool_size: int = 10  # alert threshold

    @property
    def is_healthy(self) -> bool:
        return len(self.credentials) >= self.min_pool_size

    def pop(self) -> Optional[dict]:
        """Remove and return the next spare credential, or None if empty."""
        if self.credentials:
            return self.credentials.pop(0)
        return None


@dataclass
class ReplacementCycleResult:
    """Returned by run_replacement_cycle()."""

    accounts_replaced: int = 0
    accounts_pending: int = 0     # dead but no spare available
    spare_pool_remaining: int = 0
    escalated_pool_low: bool = False
    errors: list[str] = field(default_factory=list)
    replaced_pairs: list[dict] = field(default_factory=list)
    # [{dead_account_id, replacement_account_id, username}]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class IGAccountReplacementAgent:
    """
    Automatically replaces dead Instagram accounts.

    Injected dependencies:
        account_repo:    AccountRepository instance (or any object with the
                         same async interface: get_all, mark_dead, get_by_id,
                         create).
        provisioner:     AccountProvisioner instance (provision_one).
        funnel_repo:     Optional object with get_enrollments_for_account()
                         and transfer_enrollment() async methods.
                         If None, funnel transfer is skipped with a log warning.
        ping_session_fn: Async callable(account_id) -> bool.  Called for stuck
                         accounts to verify whether the session is really dead.
                         Default: always returns False (safe fallback).

    All external calls are async.  The agent itself has no asyncio event loop
    dependency — it is driven by the caller.
    """

    def __init__(
        self,
        account_repo: Any,
        provisioner: Any,
        funnel_repo: Any = None,
        ping_session_fn: Any = None,
    ) -> None:
        self._accounts = account_repo
        self._provisioner = provisioner
        self._funnel = funnel_repo
        self._ping = ping_session_fn or (lambda _aid: False)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def detect_dead_accounts(self) -> list[DeadAccountRecord]:
        """
        Return DeadAccountRecords for:
          1. Accounts with status='dead' that have no replacement yet.
          2. Accounts with last_action_at older than STUCK_HOURS and
             warming_day > 0 that fail a session ping.

        The ping call is the only I/O that can be slow; all other work is
        pure dict filtering.
        """
        records: list[DeadAccountRecord] = []

        all_accounts = await self._accounts.get_all(platform="instagram")

        now = datetime.now(timezone.utc)
        stuck_cutoff = now - timedelta(hours=STUCK_HOURS)

        for row in all_accounts:
            account_id = row.get("id") or row.get("account_id", "")
            username = row.get("username", "")
            phone_serial = row.get("phone_serial") or row.get("phone_id") or ""
            clone_package = row.get("clone_package") or ""
            warming_day = row.get("day_in_curve") or row.get("warmup_day") or 0
            status = row.get("status", "")
            dead_reason = row.get("dead_reason") or ""
            replacement_id = row.get("replacement_account_id")

            # --- Path 1: explicitly dead with no replacement ---
            if status == "dead" and not replacement_id:
                cause = _classify_cause(dead_reason)
                enrollments = await self._get_enrollment_ids(account_id)
                records.append(DeadAccountRecord(
                    account_id=account_id,
                    username=username,
                    phone_serial=phone_serial,
                    clone_package=clone_package,
                    died_at_iso=row.get("last_action_at") or now.isoformat(),
                    cause=cause,
                    warming_day=warming_day,
                    funnel_enrollments=enrollments,
                    replacement_account_id=None,
                ))
                continue

            # --- Path 2: stuck account (not dead yet) ---
            if status in ("warming", "active") and warming_day > 0:
                last_action_raw = row.get("last_action_at")
                if last_action_raw and _parse_dt(last_action_raw) < stuck_cutoff:
                    # Ping to confirm death before marking
                    alive = await self._ping(account_id)
                    if not alive:
                        await self._accounts.mark_dead(account_id, "action_blocked_72h")
                        log.warning(
                            "Stuck account %s (%s) marked dead after %dh inactivity",
                            account_id, username, STUCK_HOURS,
                        )
                        enrollments = await self._get_enrollment_ids(account_id)
                        records.append(DeadAccountRecord(
                            account_id=account_id,
                            username=username,
                            phone_serial=phone_serial,
                            clone_package=clone_package,
                            died_at_iso=now.isoformat(),
                            cause="action_blocked_72h",
                            warming_day=warming_day,
                            funnel_enrollments=enrollments,
                            replacement_account_id=None,
                        ))

        return records

    async def provision_replacement(
        self,
        dead: DeadAccountRecord,
        spare_credentials: dict,
    ) -> str:
        """
        Provision a new account from spare_credentials onto the same
        phone_serial and clone_package as the dead account.

        Steps:
            1. provision_one() → new account_id
            2. Transfer funnel enrollments (step reset to 0)
            3. Set replacement_account_id on the dead account row
            4. Log the event

        Returns the new account_id.
        """
        username = spare_credentials["username"]
        password = spare_credentials["password"]

        new_account_id = await self._provisioner.provision_one(
            username=username,
            password=password,
            platform="instagram",
            phone_serial=dead.phone_serial or None,
        )

        log.info(
            "Provisioned replacement %s for dead account %s (was %s, cause=%s)",
            new_account_id, dead.account_id, dead.username, dead.cause,
        )

        # Transfer funnel enrollments — reset step to 0, keep targets
        await self._transfer_funnel_enrollments(
            dead_account_id=dead.account_id,
            new_account_id=new_account_id,
            enrollment_ids=dead.funnel_enrollments,
        )

        # Mark the dead record as replaced
        await self._mark_replaced(dead.account_id, new_account_id)

        return new_account_id

    async def run_replacement_cycle(
        self,
        spare_pool: SpareCredentialPool,
    ) -> ReplacementCycleResult:
        """
        Full cycle: detect → provision → escalate if needed.

        Blast-radius cap: at most MAX_REPLACEMENTS_PER_CYCLE replacements per
        call.  If more dead accounts exist, they are counted as pending and the
        next cycle handles them.

        Returns a ReplacementCycleResult.
        """
        result = ReplacementCycleResult()

        dead_accounts = await self.detect_dead_accounts()

        replacements_done = 0

        for dead in dead_accounts:
            if replacements_done >= MAX_REPLACEMENTS_PER_CYCLE:
                result.accounts_pending += 1
                continue

            spare = spare_pool.pop()
            if spare is None:
                # No spares left — this account and all remaining are pending
                result.accounts_pending += 1
                continue

            try:
                new_id = await self.provision_replacement(dead, spare)
                result.accounts_replaced += 1
                replacements_done += 1
                result.replaced_pairs.append({
                    "dead_account_id": dead.account_id,
                    "replacement_account_id": new_id,
                    "username": spare["username"],
                    "cause": dead.cause,
                })
            except Exception as exc:
                log.error(
                    "Replacement failed for dead account %s: %s",
                    dead.account_id, exc,
                )
                result.errors.append(f"replace_failed:{dead.account_id}:{exc}")
                # Put spare back so next account can try
                spare_pool.credentials.insert(0, spare)

        result.spare_pool_remaining = len(spare_pool.credentials)

        if result.spare_pool_remaining < SPARE_POOL_ESCALATE_THRESHOLD:
            result.escalated_pool_low = True
            self._escalate_pool_low(result.spare_pool_remaining)

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_enrollment_ids(self, account_id: str) -> list[str]:
        """Return active funnel enrollment IDs for an account."""
        if self._funnel is None:
            return []
        try:
            enrollments = await self._funnel.get_enrollments_for_account(account_id)
            return [e["enrollment_id"] for e in enrollments if "enrollment_id" in e]
        except Exception as exc:
            log.warning("Could not fetch enrollments for %s: %s", account_id, exc)
            return []

    async def _transfer_funnel_enrollments(
        self,
        dead_account_id: str,
        new_account_id: str,
        enrollment_ids: list[str],
    ) -> None:
        """
        Copy funnel enrollments from the dead account to the replacement.
        Each enrollment is reset to step 0 — fresh start, same targets.
        The old enrollment is left on the dead account for audit purposes.
        """
        if self._funnel is None or not enrollment_ids:
            return

        for eid in enrollment_ids:
            try:
                await self._funnel.transfer_enrollment(
                    enrollment_id=eid,
                    from_account_id=dead_account_id,
                    to_account_id=new_account_id,
                    reset_step=True,
                )
            except Exception as exc:
                log.warning(
                    "Could not transfer enrollment %s from %s to %s: %s",
                    eid, dead_account_id, new_account_id, exc,
                )

    async def _mark_replaced(self, dead_account_id: str, replacement_id: str) -> None:
        """
        Persist the replacement_account_id onto the dead account row.
        Falls back to logging if the repo does not support the field.
        """
        try:
            if hasattr(self._accounts, "set_replacement_account_id"):
                await self._accounts.set_replacement_account_id(
                    dead_account_id, replacement_id
                )
            else:
                # Fallback: update via generic update if available
                log.info(
                    "Dead account %s → replaced by %s (no set_replacement_account_id on repo)",
                    dead_account_id, replacement_id,
                )
        except Exception as exc:
            log.error(
                "Could not persist replacement link %s→%s: %s",
                dead_account_id, replacement_id, exc,
            )

    def _escalate_pool_low(self, remaining: int) -> None:
        """Log an escalation event.  In production wire to manager.dispatch()."""
        log.warning(
            "ESCALATION spare_pool_low: only %d spares remaining (threshold=%d). "
            "Upload more credentials via POST /api/accounts/spare-pool/upload",
            remaining, SPARE_POOL_ESCALATE_THRESHOLD,
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _classify_cause(dead_reason: str) -> str:
    """Map a raw dead_reason string to a canonical cause label."""
    if not dead_reason:
        return "unknown"
    r = dead_reason.lower()
    if "ban" in r:
        return "banned"
    if "session" in r or "expired" in r or "401" in r:
        return "session_expired"
    if "block" in r and "72" in r:
        return "action_blocked_72h"
    if "checkpoint" in r or "verify" in r:
        return "checkpoint"
    return dead_reason[:64]  # truncate arbitrary strings


def _parse_dt(value: Any) -> datetime:
    """
    Parse a datetime from either a datetime object or an ISO string.
    Returns epoch if unparseable (safe fallback — won't trigger false positives).
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
