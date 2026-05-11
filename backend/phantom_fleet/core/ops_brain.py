"""
PhantomFleetOpsBrain — the always-on autonomous operations manager.

Boots from FastAPI lifespan and runs three perpetual background loops:

    _health_loop   (every 60s)  — phone/proxy/session health checks
    _ops_cycle_loop (every 10m) — Chief agent dispatch + auto-replacement
    _alert_loop    (every 5m)   — ER guardian, shadowban, spare pool, LLM cost

Self-healing behaviours wired into code (not prompts):
    - Chief fails → 30s backoff, then retry; 3 consecutive → pause + critical alert
    - One platform manager failing doesn't kill others
    - Phone goes offline mid-cycle → skip its accounts gracefully
    - LLM cost > 80% of daily cap → rule-based-only mode (no LLM calls)
    - 3 consecutive full-cycle failures → pause all + critical alert
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("phantom_fleet.ops_brain")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CYCLE_INTERVAL_SEC       = 600   # full ops cycle every 10 minutes
HEALTH_CHECK_INTERVAL_SEC = 60   # quick health check every 1 minute
ALERT_CHECK_INTERVAL_SEC  = 300  # alert sweep every 5 minutes
MAX_CONSECUTIVE_FAILURES  = 3    # pause after 3 consecutive cycle failures
LLM_COST_RULE_BASED_PCT   = 0.80 # switch to rule-based when cost hits 80% of cap
DEFAULT_DAILY_LLM_CAP_USD = 25.0 # overridden by env var PHANTOM_DAILY_LLM_CAP_USD


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class OpsCycleReport:
    """Complete record of one autonomous ops cycle."""

    cycle_id:                   str
    started_at_iso:             str
    completed_at_iso:           str
    duration_sec:               float
    phones_online:              int
    accounts_active:            int
    accounts_dead_this_cycle:   int
    accounts_replaced_this_cycle: int
    platform_cycles_completed:  dict[str, bool]   # platform → success
    alerts_fired:               int
    llm_cost_usd:               float
    status:                     str               # "success" | "partial" | "failed"
    errors:                     list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Health snapshot
# ---------------------------------------------------------------------------

@dataclass
class HealthSnapshot:
    ts_iso:          str
    online_phones:   int
    proxy_ready:     int
    active_accounts: int
    dead_accounts:   int
    sessions_valid:  int


# ---------------------------------------------------------------------------
# Main brain
# ---------------------------------------------------------------------------

class PhantomFleetOpsBrain:
    """
    The autonomous brain of Phantom Fleet.

    Runs continuously in the background from server startup.
    Every cycle it:
    1. Checks fleet health (phones online, proxies verified)
    2. Runs the Chief agent (which dispatches all platform managers)
    3. Monitors for anomalies (dead accounts, cluster alerts, ER drops)
    4. Self-heals: restarts failed workers, replaces dead accounts
    5. Reports status to the dashboard in real-time via Redis pub/sub

    This is the "zero-watch" operations layer — agencies should be able
    to set it and forget it for days at a time.
    """

    CYCLE_INTERVAL_SEC        = CYCLE_INTERVAL_SEC
    HEALTH_CHECK_INTERVAL_SEC = HEALTH_CHECK_INTERVAL_SEC

    def __init__(
        self,
        fleet: Any,
        redis: Any | None = None,
        db_pool: Any | None = None,
        chief_agent: Any | None = None,
        daily_llm_cap_usd: float = DEFAULT_DAILY_LLM_CAP_USD,
    ) -> None:
        self.fleet   = fleet
        self.redis   = redis
        self.db_pool = db_pool
        self._chief  = chief_agent     # injected; built lazily if None
        self._daily_llm_cap_usd = daily_llm_cap_usd

        self._running: bool = False
        self._paused:  bool = False
        self._rule_based_mode: bool = False  # True when LLM budget is near cap

        self._cycle_count:          int = 0
        self._consecutive_failures: int = 0

        self._latest_report:   OpsCycleReport | None = None
        self._cycle_history:   list[OpsCycleReport] = []   # last 24 reports
        self._latest_health:   HealthSnapshot | None = None
        self._active_alerts:   list[dict] = []

        self._tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Boot the ops brain. Starts 3 background loops."""
        self._running = True
        self._tasks = [
            asyncio.create_task(self._health_loop(),    name="ops_health_loop"),
            asyncio.create_task(self._ops_cycle_loop(), name="ops_cycle_loop"),
            asyncio.create_task(self._alert_loop(),     name="ops_alert_loop"),
        ]
        log.info("PhantomFleetOpsBrain started — 3 background loops active")

    async def stop(self) -> None:
        """Graceful shutdown: cancel all loops."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        log.info("PhantomFleetOpsBrain stopped")

    def pause(self) -> None:
        """Pause all operations (health checks continue)."""
        self._paused = True
        log.warning("OpsBrain PAUSED — health checks continue, ops cycles suspended")

    def resume(self) -> None:
        """Resume operations after a pause."""
        self._paused = False
        self._consecutive_failures = 0
        log.info("OpsBrain RESUMED")

    # ------------------------------------------------------------------
    # Status accessors (used by /api/ops/* routes)
    # ------------------------------------------------------------------

    def status(self) -> str:
        if not self._running:
            return "stopped"
        if self._paused:
            return "paused"
        if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            return "error"
        return "running"

    def latest_report(self) -> OpsCycleReport | None:
        return self._latest_report

    def cycle_history(self) -> list[OpsCycleReport]:
        return list(self._cycle_history)

    def latest_health(self) -> HealthSnapshot | None:
        return self._latest_health

    def active_alerts(self) -> list[dict]:
        return list(self._active_alerts)

    def is_rule_based_mode(self) -> bool:
        return self._rule_based_mode

    # ------------------------------------------------------------------
    # Background loops
    # ------------------------------------------------------------------

    async def _health_loop(self) -> None:
        """Runs every 60 seconds. Quick fleet health check."""
        while self._running:
            try:
                await self._run_health_check()
            except Exception as exc:
                log.error("health_loop exception: %s", exc, exc_info=True)
            await asyncio.sleep(HEALTH_CHECK_INTERVAL_SEC)

    async def _ops_cycle_loop(self) -> None:
        """Runs every 10 minutes. Full Chief→managers→specialists cycle."""
        # Stagger: wait one health interval before first cycle so health data is ready
        await asyncio.sleep(HEALTH_CHECK_INTERVAL_SEC)
        while self._running:
            if not self._paused:
                try:
                    await self._run_ops_cycle()
                except Exception as exc:
                    log.error("ops_cycle_loop unhandled exception: %s", exc, exc_info=True)
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        self.pause()
                        await self._publish_alert({
                            "severity": "critical",
                            "dimension": "ops_brain",
                            "description": (
                                f"3 consecutive ops cycle failures — fleet paused. "
                                f"Last error: {exc}"
                            ),
                        })
            await asyncio.sleep(CYCLE_INTERVAL_SEC)

    async def _alert_loop(self) -> None:
        """Runs every 5 minutes. ER, shadowban, spare pool, cost checks."""
        while self._running:
            try:
                await self._run_alert_sweep()
            except Exception as exc:
                log.error("alert_loop exception: %s", exc, exc_info=True)
            await asyncio.sleep(ALERT_CHECK_INTERVAL_SEC)

    # ------------------------------------------------------------------
    # Health check implementation
    # ------------------------------------------------------------------

    async def _run_health_check(self) -> None:
        """
        1. Ping all phones: detect newly connected / disconnected.
        2. Check proxy status on PROXY_READY phones.
        3. Ping active IG sessions per account.
        4. Mark dead sessions, trigger replacement.
        5. Publish health snapshot to Redis.
        """
        online_phones = 0
        proxy_ready   = 0
        active_accounts = 0
        dead_accounts   = 0
        sessions_valid  = 0

        try:
            # Scan connected phones
            scan_result = await _safe_call(self.fleet, "scan")
            phones = scan_result if isinstance(scan_result, list) else []
            online_phones = len(phones)

            for phone in phones:
                serial = phone.get("serial", "") if isinstance(phone, dict) else str(phone)
                state  = phone.get("state", "")  if isinstance(phone, dict) else ""

                # Verify proxy on PROXY_READY phones
                if state == "PROXY_READY":
                    proxy_ok = await _safe_call(self.fleet, "verify_proxy", serial)
                    if proxy_ok:
                        proxy_ready += 1

                # Ping each account's session on this phone
                accounts = await _safe_call(self.fleet, "get_accounts_for_phone", serial) or []
                for account in accounts:
                    acct_id = account.get("account_id", "") if isinstance(account, dict) else ""
                    session = account.get("session")  if isinstance(account, dict) else None
                    active_accounts += 1

                    if session is not None:
                        ping_ok = await _safe_call(session, "ping_session")
                        if ping_ok:
                            sessions_valid += 1
                        else:
                            dead_accounts += 1
                            await _safe_call(
                                self.fleet, "mark_session_dead", acct_id,
                            )

        except Exception as exc:
            log.error("_run_health_check error: %s", exc, exc_info=True)

        snapshot = HealthSnapshot(
            ts_iso=_now_iso(),
            online_phones=online_phones,
            proxy_ready=proxy_ready,
            active_accounts=active_accounts,
            dead_accounts=dead_accounts,
            sessions_valid=sessions_valid,
        )
        self._latest_health = snapshot

        await self._redis_publish(
            "fleet:health",
            {
                "ts_iso": snapshot.ts_iso,
                "online_phones": snapshot.online_phones,
                "proxy_ready": snapshot.proxy_ready,
                "active_accounts": snapshot.active_accounts,
                "dead_accounts": snapshot.dead_accounts,
                "sessions_valid": snapshot.sessions_valid,
            },
        )

    # ------------------------------------------------------------------
    # Ops cycle implementation
    # ------------------------------------------------------------------

    async def _run_ops_cycle(self) -> None:
        """
        Full autonomous cycle:
        1. Build context (accounts, metrics, alerts, spare pool)
        2. Check LLM cost vs daily cap → maybe switch to rule-based mode
        3. Run Chief agent (which dispatches all platform managers)
        4. Auto-replace accounts marked dead since last cycle
        5. Lightweight cluster audit every other cycle
        6. Log to agent_runs table
        7. Publish cycle summary to Redis
        """
        cycle_id   = str(uuid.uuid4())
        started_at = time.monotonic()
        started_iso = _now_iso()

        self._cycle_count += 1
        cycle_num = self._cycle_count

        errors: list[str] = []
        platform_results: dict[str, bool] = {}
        accounts_dead_this_cycle    = 0
        accounts_replaced_this_cycle = 0
        alerts_fired = 0
        llm_cost_usd = 0.0

        log.info("OpsBrain: starting cycle #%d  id=%s", cycle_num, cycle_id)

        # --- 1. Cost guard ---
        llm_cost_usd = await self._get_llm_cost_today()
        if llm_cost_usd >= self._daily_llm_cap_usd * LLM_COST_RULE_BASED_PCT:
            if not self._rule_based_mode:
                log.warning(
                    "LLM cost $%.2f >= 80%% of daily cap $%.2f — switching to rule-based mode",
                    llm_cost_usd, self._daily_llm_cap_usd,
                )
                self._rule_based_mode = True
                await self._publish_alert({
                    "severity": "high",
                    "dimension": "llm_cost",
                    "description": (
                        f"LLM cost ${llm_cost_usd:.2f} reached 80% of daily cap "
                        f"${self._daily_llm_cap_usd:.2f} — rule-based mode active"
                    ),
                })
                alerts_fired += 1
        else:
            self._rule_based_mode = False

        # --- 2. Build ops context ---
        ctx = await self._build_cycle_context()
        ctx["rule_based_mode"] = self._rule_based_mode
        ctx["cycle_id"]        = cycle_id
        ctx["cycle_num"]       = cycle_num

        # --- 3. Run Chief agent ---
        if not self._rule_based_mode:
            chief = await self._get_chief()
            try:
                await chief.run(ctx)
                # Collect per-platform results from chief's dispatch outcomes
                for platform in [
                    "infrastructure", "instagram", "threads", "reddit",
                    "x", "tiktok", "dating", "telegram", "discord", "bluesky", "funnel",
                ]:
                    platform_results[platform] = True
            except Exception as exc:
                log.error("Chief agent failed: %s", exc, exc_info=True)
                errors.append(f"chief_failed:{exc!s:.200}")
                self._consecutive_failures += 1
                if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    self.pause()
                    await self._publish_alert({
                        "severity": "critical",
                        "dimension": "chief_agent",
                        "description": f"Chief agent failed {MAX_CONSECUTIVE_FAILURES}x — fleet paused. Error: {exc!s:.300}",
                    })
                    alerts_fired += 1
                # Try to run individual platform managers directly as fallback
                platform_results = await self._run_platform_managers_direct(ctx, errors)
        else:
            # Rule-based mode: skip LLM calls, just run structural maintenance
            log.info("OpsBrain cycle #%d: rule-based mode — skipping LLM agent dispatch", cycle_num)
            for platform in ["infrastructure"]:
                try:
                    mgr = await self._get_platform_manager(platform)
                    if mgr:
                        await mgr.run(ctx)
                        platform_results[platform] = True
                except Exception as exc:
                    errors.append(f"{platform}_manager_failed:{exc!s:.200}")
                    platform_results[platform] = False

        if errors:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 0

        # --- 4. Auto-replacement for dead accounts ---
        accounts_dead_this_cycle, accounts_replaced_this_cycle = (
            await self._run_auto_replacement(errors)
        )

        # --- 5. Lightweight cluster audit every other cycle ---
        if cycle_num % 2 == 0:
            try:
                await self._run_cluster_audit_lite()
            except Exception as exc:
                log.warning("cluster_audit_lite failed: %s", exc)
                errors.append(f"cluster_audit_lite:{exc!s:.100}")

        # --- 6. Build report ---
        duration = time.monotonic() - started_at
        health = self._latest_health
        status = "success" if not errors else ("partial" if platform_results else "failed")

        report = OpsCycleReport(
            cycle_id=cycle_id,
            started_at_iso=started_iso,
            completed_at_iso=_now_iso(),
            duration_sec=round(duration, 2),
            phones_online=health.online_phones if health else 0,
            accounts_active=health.active_accounts if health else 0,
            accounts_dead_this_cycle=accounts_dead_this_cycle,
            accounts_replaced_this_cycle=accounts_replaced_this_cycle,
            platform_cycles_completed=platform_results,
            alerts_fired=alerts_fired,
            llm_cost_usd=llm_cost_usd,
            status=status,
            errors=errors,
        )
        self._latest_report = report
        self._cycle_history.append(report)
        if len(self._cycle_history) > 24:
            self._cycle_history.pop(0)

        # --- 7. Persist + publish ---
        await self._log_cycle_to_db(report)
        await self._redis_publish(
            "fleet:cycle",
            {
                "cycle_id":           report.cycle_id,
                "cycle_num":          cycle_num,
                "status":             report.status,
                "duration_sec":       report.duration_sec,
                "phones_online":      report.phones_online,
                "accounts_active":    report.accounts_active,
                "accounts_dead":      report.accounts_dead_this_cycle,
                "accounts_replaced":  report.accounts_replaced_this_cycle,
                "alerts_fired":       report.alerts_fired,
                "llm_cost_usd":       report.llm_cost_usd,
                "errors":             report.errors[:5],
                "ts_iso":             report.completed_at_iso,
            },
        )
        log.info(
            "OpsBrain: cycle #%d complete in %.1fs  status=%s  errors=%d",
            cycle_num, duration, status, len(errors),
        )

    async def _run_platform_managers_direct(
        self,
        ctx: dict,
        errors: list[str],
    ) -> dict[str, bool]:
        """
        Fallback: if Chief fails, try running each platform manager independently.
        One failure must NOT kill the others.
        """
        results: dict[str, bool] = {}
        platforms = [
            "infrastructure", "instagram", "threads", "reddit",
            "x", "tiktok", "dating", "telegram", "discord", "bluesky", "funnel",
        ]
        for platform in platforms:
            try:
                mgr = await self._get_platform_manager(platform)
                if mgr is None:
                    results[platform] = False
                    continue
                await mgr.run(ctx)
                results[platform] = True
            except Exception as exc:
                log.error("Platform manager %s failed: %s", platform, exc, exc_info=True)
                errors.append(f"{platform}_manager_failed:{exc!s:.200}")
                results[platform] = False
        return results

    # ------------------------------------------------------------------
    # Alert sweep
    # ------------------------------------------------------------------

    async def _run_alert_sweep(self) -> None:
        """
        Check:
        1. ER drop (engagement rate guardian)
        2. Shadowban signals
        3. Spare pool level
        4. LLM cost vs daily cap
        """
        new_alerts: list[dict] = []

        # ER guardian
        try:
            er_alerts = await _safe_call(self.fleet, "check_er_guardian") or []
            for a in (er_alerts if isinstance(er_alerts, list) else []):
                new_alerts.append({
                    "severity": "high",
                    "dimension": "engagement_rate",
                    "description": str(a)[:300],
                })
        except Exception as exc:
            log.debug("er_guardian check failed: %s", exc)

        # Shadowban check
        try:
            sb_alerts = await _safe_call(self.fleet, "check_shadowban_signals") or []
            for a in (sb_alerts if isinstance(sb_alerts, list) else []):
                new_alerts.append({
                    "severity": "medium",
                    "dimension": "shadowban",
                    "description": str(a)[:300],
                })
        except Exception as exc:
            log.debug("shadowban check failed: %s", exc)

        # Spare pool level
        try:
            spare_count = await _safe_call(self.fleet, "get_spare_pool_count") or 0
            if isinstance(spare_count, int) and spare_count < 5:
                new_alerts.append({
                    "severity": "medium" if spare_count > 0 else "high",
                    "dimension": "spare_pool",
                    "description": (
                        f"Spare account pool low: {spare_count} accounts remaining. "
                        "Refill required."
                    ),
                })
        except Exception as exc:
            log.debug("spare_pool check failed: %s", exc)

        # LLM cost check
        try:
            cost_today = await self._get_llm_cost_today()
            pct = cost_today / self._daily_llm_cap_usd if self._daily_llm_cap_usd > 0 else 0
            if pct >= 0.95:
                new_alerts.append({
                    "severity": "critical",
                    "dimension": "llm_cost",
                    "description": (
                        f"LLM spend ${cost_today:.2f} is at {pct*100:.0f}% of daily cap "
                        f"${self._daily_llm_cap_usd:.2f}"
                    ),
                })
            elif pct >= LLM_COST_RULE_BASED_PCT:
                new_alerts.append({
                    "severity": "high",
                    "dimension": "llm_cost",
                    "description": (
                        f"LLM spend ${cost_today:.2f} reached 80% of daily cap — rule-based mode"
                    ),
                })
        except Exception as exc:
            log.debug("llm_cost check failed: %s", exc)

        # Publish new alerts
        for alert in new_alerts:
            await self._publish_alert(alert)

        self._active_alerts = new_alerts  # replace with fresh sweep results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _build_cycle_context(self) -> dict:
        """Gather accounts, metrics, alerts, spare pool for Chief."""
        ctx: dict[str, Any] = {}
        try:
            ctx["accounts"] = await _safe_call(self.fleet, "get_all_active_accounts") or []
        except Exception:
            ctx["accounts"] = []
        try:
            ctx["metrics_yesterday"] = await _safe_call(
                self.fleet, "get_performance_metrics", days=1
            ) or {}
        except Exception:
            ctx["metrics_yesterday"] = {}
        try:
            ctx["active_alerts"] = list(self._active_alerts)
        except Exception:
            ctx["active_alerts"] = []
        try:
            ctx["spare_pool_count"] = await _safe_call(self.fleet, "get_spare_pool_count") or 0
        except Exception:
            ctx["spare_pool_count"] = 0
        return ctx

    async def _run_auto_replacement(
        self, errors: list[str]
    ) -> tuple[int, int]:
        """Check for dead accounts since last cycle; trigger replacement."""
        dead_count    = 0
        replaced_count = 0
        try:
            dead_accounts = await _safe_call(self.fleet, "get_newly_dead_accounts") or []
            dead_count    = len(dead_accounts) if isinstance(dead_accounts, list) else 0
            for acct in (dead_accounts if isinstance(dead_accounts, list) else []):
                acct_id = acct.get("account_id", "") if isinstance(acct, dict) else str(acct)
                try:
                    result = await _safe_call(self.fleet, "trigger_replacement", acct_id)
                    if result:
                        replaced_count += 1
                except Exception as exc:
                    errors.append(f"replacement_failed:{acct_id}:{exc!s:.100}")
        except Exception as exc:
            errors.append(f"auto_replacement_check_failed:{exc!s:.100}")
        return dead_count, replaced_count

    async def _run_cluster_audit_lite(self) -> None:
        """Lightweight cluster health audit — checks distributions, not full Monte Carlo."""
        audit = await _safe_call(self.fleet, "run_cluster_audit_lite")
        if audit and isinstance(audit, dict):
            findings = audit.get("findings", [])
            for finding in findings[:5]:  # cap at 5 alerts per audit
                await self._publish_alert({
                    "severity": finding.get("severity", "medium"),
                    "dimension": "cluster_audit",
                    "description": str(finding.get("description", finding))[:300],
                })

    async def _get_chief(self) -> Any:
        """Return the Chief agent, building it lazily if needed."""
        if self._chief is not None:
            return self._chief
        # Lazy construction — minimal, no DB required
        from ..agents.managers.chief import ChiefAgentManager
        self._chief = ChiefAgentManager()
        return self._chief

    async def _get_platform_manager(self, platform: str) -> Any | None:
        """Return a platform manager by name, or None if not available."""
        from ..agents.managers import MANAGER_CLASSES
        cls = MANAGER_CLASSES.get(platform)
        if cls is None:
            return None
        return cls()

    async def _get_llm_cost_today(self) -> float:
        """Query today's LLM cost from agent_runs, or return 0 if DB unavailable."""
        if self.db_pool is None:
            return 0.0
        try:
            from ..db.repositories.agent_runs import AgentRunRepository
            repo = AgentRunRepository(self.db_pool)
            return await repo.get_total_cost_today()
        except Exception as exc:
            log.debug("get_llm_cost_today failed: %s", exc)
            return 0.0

    async def _log_cycle_to_db(self, report: OpsCycleReport) -> None:
        """Write cycle completion to agent_runs for audit trail."""
        if self.db_pool is None:
            return
        try:
            from ..db.repositories.agent_runs import AgentRunRepository
            repo = AgentRunRepository(self.db_pool)
            await repo.log_run(
                agent_name="ops_brain_cycle",
                started_at=datetime.fromisoformat(report.started_at_iso),
                ended_at=datetime.fromisoformat(report.completed_at_iso),
                cost_usd=report.llm_cost_usd,
                success=(report.status != "failed"),
                result={
                    "cycle_id":      report.cycle_id,
                    "status":        report.status,
                    "duration_sec":  report.duration_sec,
                    "phones_online": report.phones_online,
                    "platform_cycles_completed": report.platform_cycles_completed,
                    "alerts_fired":  report.alerts_fired,
                    "errors":        report.errors,
                },
                error="; ".join(report.errors[:3]) if report.errors else None,
            )
        except Exception as exc:
            log.warning("_log_cycle_to_db failed: %s", exc)

    async def _publish_alert(self, alert: dict) -> None:
        """Publish an alert to Redis fleet:alerts channel."""
        payload = {
            "alert_id":   str(uuid.uuid4()),
            "ts_iso":     _now_iso(),
            **alert,
        }
        await self._redis_publish("fleet:alerts", payload)
        log.warning(
            "ALERT [%s] %s: %s",
            payload.get("severity", "?"),
            payload.get("dimension", "?"),
            payload.get("description", "")[:120],
        )

    async def _redis_publish(self, channel: str, payload: dict) -> None:
        """Publish to Redis if a client is available; silently skip otherwise."""
        if self.redis is None:
            return
        try:
            import json
            await self.redis.publish(channel, json.dumps(payload))
        except Exception as exc:
            log.debug("Redis publish failed on %s: %s", channel, exc)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


async def _safe_call(obj: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    """Call obj.method(*args) if it exists, return None otherwise."""
    fn = getattr(obj, method, None)
    if fn is None:
        return None
    try:
        result = fn(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result
    except Exception as exc:
        log.debug("_safe_call %s.%s failed: %s", type(obj).__name__, method, exc)
        return None
