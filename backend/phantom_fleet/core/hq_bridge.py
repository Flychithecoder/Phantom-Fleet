"""
HQBridge — Agency HQ Panel → Phantom Fleet account handoff bridge.

HQ is the business layer: creator profiles, CRM, revenue tracking.
Phantom Fleet is the operations layer: social media automation.

Flow when HQ provisions a new account:
    1. HQ calls POST /api/hq/accounts/handoff  (auth: X-HQ-API-Key header)
    2. HQBridge.receive_account_handoff() validates + provisions the account
    3. Assigns it to an available phone via the PhoneFleet
    4. Inserts it into the warming queue (WarmingOrchestrator picks it up)
    5. Returns: account_id, phone_serial, warming_start_date, estimated_ready_date

HQ can also query Phantom Fleet for account performance metrics that
feed into HQ's creator performance dashboard.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

log = logging.getLogger("phantom_fleet.hq_bridge")

# Estimated warming duration per platform (days until "active" status)
_WARM_DAYS: dict[str, int] = {
    "instagram": 30,
    "threads":   14,
    "tiktok":    21,
    "reddit":    45,
    "x":         21,
    "discord":   10,
    "telegram":  10,
    "dating":    14,
    "bluesky":   7,
}


# ---------------------------------------------------------------------------
# Input / output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class HQAccountHandoff:
    """Payload sent by HQ when it provisions a new account."""

    creator_id:      str            # HQ's creator UUID
    platform:        str            # "instagram" | "threads" | "tiktok" etc.
    username:        str
    password:        str
    two_fa_secret:   str | None
    chat_tier:       str            # from HQ creator profile
    persona_name:    str            # e.g. "Tatiana_NYC"
    content_tags:    list[str]      # ["lifestyle", "sfw"]
    target_niches:   list[str]      # audience niches to target
    hq_api_key:      str            # for callback auth (validated before reaching here)


@dataclass
class HandoffResult:
    """Result returned to HQ after provisioning."""

    ok:                    bool
    account_id:            str
    phone_serial:          str | None
    platform:              str
    warming_start_date:    str       # ISO date
    estimated_ready_date:  str       # ISO date  (start + warm_days)
    status:                str       # "warming" | "queued" | "error"
    message:               str       # human-readable
    error:                 str | None = None


@dataclass
class BulkHandoffResult:
    """Result for a bulk handoff request."""

    total:     int
    succeeded: int
    failed:    int
    results:   list[HandoffResult] = field(default_factory=list)


@dataclass
class PerformanceMetrics:
    """Performance data returned to HQ for its creator dashboard."""

    account_id:       str
    platform:         str
    creator_id:       str
    username:         str
    post_count_30d:   int
    follower_count:   int
    follow_count:     int
    er_pct:           float    # engagement rate %
    dm_reply_rate:    float    # fraction of DMs that got a reply
    funnel_clicks_7d: int      # link-in-bio / OF link clicks last 7 days
    warming_day:      int
    status:           str      # "warming" | "active" | "dead" | "paused"
    last_active_iso:  str


# ---------------------------------------------------------------------------
# Bridge class
# ---------------------------------------------------------------------------

class HQBridge:
    """
    Bridge between Agency HQ panel and Phantom Fleet.

    Injected with the PhoneFleet singleton and optionally a DB pool
    for persisting account records.
    """

    def __init__(
        self,
        fleet: Any,
        db_pool: Any | None = None,
    ) -> None:
        self.fleet   = fleet
        self.db_pool = db_pool

    # ------------------------------------------------------------------
    # Account handoff
    # ------------------------------------------------------------------

    async def receive_account_handoff(
        self,
        payload: HQAccountHandoff,
    ) -> HandoffResult:
        """
        Provision one account from HQ:
        1. Generate a stable account_id
        2. Find the best available phone for this platform
        3. Persist the account record to DB
        4. Enqueue the account into the warming queue
        5. Return HandoffResult to HQ
        """
        platform   = payload.platform.lower()
        account_id = _make_account_id(payload.creator_id, payload.username, platform)
        today_iso  = _today_iso()

        # 1. Find available phone
        phone_serial = await self._find_available_phone(platform)

        # 2. Build account record
        account_record: dict[str, Any] = {
            "account_id":    account_id,
            "creator_id":    payload.creator_id,
            "platform":      platform,
            "username":      payload.username,
            "password":      payload.password,   # stored encrypted in DB in production
            "two_fa_secret": payload.two_fa_secret,
            "chat_tier":     payload.chat_tier,
            "persona_name":  payload.persona_name,
            "content_tags":  payload.content_tags,
            "target_niches": payload.target_niches,
            "phone_serial":  phone_serial,
            "warmup_day":    0,
            "curve_type":    "fresh_warmup",
            "status":        "warming",
            "created_at":    _now_iso(),
            "source":        "hq_handoff",
        }

        # 3. Persist to DB
        await self._persist_account(account_record)

        # 4. Enqueue into warming queue
        warming_ok = await self._enqueue_for_warming(account_record)

        warm_days           = _WARM_DAYS.get(platform, 30)
        estimated_ready_iso = _iso_date_plus_days(today_iso, warm_days)

        status  = "warming" if warming_ok else "queued"
        message = (
            f"Account @{payload.username} provisioned on "
            f"{phone_serial or 'pending phone assignment'}. "
            f"Warming starts {today_iso}, estimated active {estimated_ready_iso}."
        )

        log.info(
            "HQ handoff: creator=%s @%s platform=%s account_id=%s phone=%s",
            payload.creator_id, payload.username, platform, account_id, phone_serial,
        )

        return HandoffResult(
            ok=True,
            account_id=account_id,
            phone_serial=phone_serial,
            platform=platform,
            warming_start_date=today_iso,
            estimated_ready_date=estimated_ready_iso,
            status=status,
            message=message,
        )

    async def bulk_handoff(
        self,
        payloads: list[HQAccountHandoff],
    ) -> BulkHandoffResult:
        """Handoff multiple accounts. Returns per-account results."""
        results: list[HandoffResult] = []
        succeeded = 0
        failed    = 0

        for payload in payloads:
            try:
                result = await self.receive_account_handoff(payload)
                results.append(result)
                if result.ok:
                    succeeded += 1
                else:
                    failed += 1
            except Exception as exc:
                log.error(
                    "bulk_handoff: failed for @%s: %s",
                    getattr(payload, "username", "?"), exc,
                )
                results.append(HandoffResult(
                    ok=False,
                    account_id="",
                    phone_serial=None,
                    platform=getattr(payload, "platform", "unknown"),
                    warming_start_date="",
                    estimated_ready_date="",
                    status="error",
                    message=f"Handoff failed: {exc!s:.200}",
                    error=str(exc)[:200],
                ))
                failed += 1

        return BulkHandoffResult(
            total=len(payloads),
            succeeded=succeeded,
            failed=failed,
            results=results,
        )

    # ------------------------------------------------------------------
    # Performance reporting
    # ------------------------------------------------------------------

    async def report_performance_to_hq(
        self,
        account_ids: list[str],
    ) -> dict[str, Any]:
        """
        Return performance metrics for a list of account IDs.
        HQ uses this to populate its creator performance dashboard.
        """
        metrics: list[dict] = []
        for account_id in account_ids:
            try:
                m = await self._load_account_metrics(account_id)
                metrics.append(m)
            except Exception as exc:
                log.warning("report_performance: failed for %s: %s", account_id, exc)
                metrics.append({
                    "account_id": account_id,
                    "error": str(exc)[:200],
                })

        return {
            "generated_at": _now_iso(),
            "account_count": len(account_ids),
            "metrics": metrics,
        }

    async def sync_creator_personas(self, creator_id: str) -> None:
        """
        Pull updated persona/content config from HQ for all accounts
        belonging to creator_id and propagate to the fleet.
        """
        try:
            accounts = await self._get_accounts_for_creator(creator_id)
            for acct in accounts:
                await self._update_account_persona(acct)
            log.info(
                "sync_creator_personas: synced %d accounts for creator %s",
                len(accounts), creator_id,
            )
        except Exception as exc:
            log.error("sync_creator_personas failed for %s: %s", creator_id, exc, exc_info=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _find_available_phone(self, platform: str) -> str | None:
        """Ask the fleet for the best available phone for this platform."""
        try:
            if hasattr(self.fleet, 'get_phones_for_platform'):
                phones = await _async_or_sync(self.fleet.get_phones_for_platform, platform)
                if phones:
                    return phones[0].get("serial") if isinstance(phones[0], dict) else str(phones[0])
        except Exception as exc:
            log.debug("_find_available_phone failed: %s", exc)
        # Fallback: first phone from scan
        try:
            phones = await _async_or_sync(self.fleet.scan)
            if phones:
                return phones[0].get("serial") if isinstance(phones[0], dict) else str(phones[0])
        except Exception:
            pass
        return None

    async def _persist_account(self, record: dict) -> None:
        """Write account record to DB if available."""
        if self.db_pool is None:
            log.debug("_persist_account: no db_pool, skipping persist")
            return
        try:
            import json
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO accounts (
                        account_id, creator_id, platform, username,
                        phone_serial, status, warmup_day, persona_name,
                        content_tags, target_niches, created_at, source
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    ON CONFLICT (account_id) DO NOTHING
                    """,
                    record["account_id"],
                    record["creator_id"],
                    record["platform"],
                    record["username"],
                    record["phone_serial"],
                    record["status"],
                    record["warmup_day"],
                    record["persona_name"],
                    json.dumps(record["content_tags"]),
                    json.dumps(record["target_niches"]),
                    datetime.fromisoformat(record["created_at"]),
                    record["source"],
                )
        except Exception as exc:
            log.warning("_persist_account DB write failed: %s", exc)

    async def _enqueue_for_warming(self, record: dict) -> bool:
        """Add account to the warming queue via the fleet."""
        try:
            result = await _async_or_sync(
                self.fleet.enqueue_for_warming, record
            )
            return bool(result) if result is not None else True
        except Exception as exc:
            log.warning("_enqueue_for_warming failed: %s", exc)
            return False

    async def _load_account_metrics(self, account_id: str) -> dict:
        """Load performance metrics from fleet/DB."""
        try:
            result = await _async_or_sync(
                self.fleet.get_account_metrics, account_id
            )
            if result and isinstance(result, dict):
                return result
        except Exception:
            pass
        # Stub if fleet doesn't implement get_account_metrics yet
        return {
            "account_id":       account_id,
            "post_count_30d":   0,
            "follower_count":   0,
            "follow_count":     0,
            "er_pct":           0.0,
            "dm_reply_rate":    0.0,
            "funnel_clicks_7d": 0,
            "warming_day":      0,
            "status":           "unknown",
            "last_active_iso":  _now_iso(),
        }

    async def _get_accounts_for_creator(self, creator_id: str) -> list[dict]:
        try:
            result = await _async_or_sync(
                self.fleet.get_accounts_for_creator, creator_id
            )
            return result if isinstance(result, list) else []
        except Exception:
            return []

    async def _update_account_persona(self, account: dict) -> None:
        try:
            await _async_or_sync(self.fleet.update_account_persona, account)
        except Exception as exc:
            log.debug("_update_account_persona failed: %s", exc)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _make_account_id(creator_id: str, username: str, platform: str) -> str:
    import hashlib
    raw = f"{creator_id}:{platform}:{username}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.now(tz=timezone.utc).date().isoformat()


def _iso_date_plus_days(date_iso: str, days: int) -> str:
    d = datetime.fromisoformat(date_iso).date()
    return (d + timedelta(days=days)).isoformat()


import asyncio


async def _async_or_sync(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Call fn — awaits if coroutine, returns directly otherwise."""
    try:
        result = fn(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result
    except Exception as exc:
        log.debug("_async_or_sync %s failed: %s", getattr(fn, "__name__", fn), exc)
        return None
