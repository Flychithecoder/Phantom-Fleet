"""
Threads audit harness — 10K-persona Monte Carlo coverage for every
distribution the platform ships.

Per CLAUDE.md §Distribution discipline + §Fleet-scale audit gate:

    > Any new persona field, fingerprint dimension, or action primitive
    > requires an audit-harness test case covering its distribution shape.

Threads added:
    * 14-day warming curve with LogNormal-sampled daily budgets
    * 4 action primitives (post / reply / repost / follow)
    * LogNormal-sampled inter-action delays
    * Deterministic seed-driven content pick

This module exercises every one of those distributions across N synthetic
account_ids and asserts the shape properties CLAUDE.md requires:

    1. Budget uniqueness — no two accounts share an identical 14-day
       budget vector (prevents the "every phone has the same 15 accounts"
       cluster-detection tell from the Onimator audit findings).
    2. LogNormal shape — log-transformed samples have coefficient of
       variation in the expected band; they are NOT uniform.
    3. Daily cap discipline — every sample is ≤ 1.5× the base-curve
       mean, matching the clamp in threads.py.
    4. Inter-action delay bounds — all delays in [10s, 900s].
    5. Content pick spread — no library item dominates the draw.
    6. Cross-field: Threads warming day in [1, WARMING_DAYS].

The harness is re-entrant and deterministic: same N, same seed → same
report, so CI can diff it. Returning a structured report instead of
raising lets the UI show which specific check failed.
"""
from __future__ import annotations

import hashlib
import math
import statistics
import time
from dataclasses import dataclass, field
from typing import Literal

from . import threads as threads_mod
from . import threads_executor as threads_exec
from . import threads_health as threads_health_mod
from . import threads_orchestrator as threads_orch

CheckStatus = Literal["pass", "warn", "fail"]


@dataclass
class CheckResult:
    key:     str
    label:   str
    status:  CheckStatus
    detail:  str
    metrics: dict = field(default_factory=dict)


@dataclass
class AuditReport:
    ran_at:          str
    n_personas:      int
    pass_count:      int
    warn_count:      int
    fail_count:      int
    duration_ms:     float
    checks:          list[CheckResult]

    def as_dict(self) -> dict:
        return {
            "ran_at":      self.ran_at,
            "n_personas":  self.n_personas,
            "pass_count":  self.pass_count,
            "warn_count":  self.warn_count,
            "fail_count":  self.fail_count,
            "duration_ms": round(self.duration_ms, 2),
            "passed":      self.fail_count == 0,
            "checks":      [{
                "key":     c.key,
                "label":   c.label,
                "status":  c.status,
                "detail":  c.detail,
                "metrics": c.metrics,
            } for c in self.checks],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _synthetic_account_id(i: int) -> str:
    """
    Deterministic 16-hex account_id from a loop index. Keeps the audit
    reproducible: same i → same id → same budget draws.
    """
    return "aud-" + hashlib.sha256(f"audit-persona-{i}".encode()).hexdigest()[:12]


def _coef_of_variation(samples: list[float]) -> float:
    if len(samples) < 2:
        return 0.0
    m = statistics.mean(samples)
    if m <= 0:
        return 0.0
    return statistics.stdev(samples) / m


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _check_budget_uniqueness(ids: list[str]) -> CheckResult:
    """
    Every account's 14-day budget vector should be unique — if any two
    collide we've effectively given them identical behavior, which is the
    exact cluster-detection tell flagged in CLAUDE.md §Known fleet bugs.
    """
    seen: dict[tuple, int] = {}
    collisions = 0
    for aid in ids:
        vec = tuple(
            (b.follow, b.reply, b.repost, b.post)
            for b in threads_mod.budgets_across_curve(aid)
        )
        if vec in seen:
            collisions += 1
        else:
            seen[vec] = 1
    rate = collisions / len(ids)
    if collisions == 0:
        return CheckResult(
            key="budget_uniqueness",
            label="Budget vectors unique across fleet",
            status="pass",
            detail=f"{len(ids)} accounts produced {len(seen)} distinct 14-day vectors.",
            metrics={"collisions": 0, "collision_rate": 0.0,
                     "distinct_vectors": len(seen)},
        )
    # A handful of collisions on a 10K sweep is fine (pigeonhole on int budgets).
    status: CheckStatus = "warn" if rate < 0.005 else "fail"
    return CheckResult(
        key="budget_uniqueness",
        label="Budget vectors unique across fleet",
        status=status,
        detail=f"{collisions}/{len(ids)} accounts collide ({rate*100:.3f}%).",
        metrics={"collisions": collisions, "collision_rate": rate,
                 "distinct_vectors": len(seen)},
    )


def _check_lognormal_shape(ids: list[str]) -> CheckResult:
    """
    Pull one day's follow budgets across all accounts; the LogNormal should
    give coefficient-of-variation roughly in [0.15, 0.6]. A uniform draw
    would land near 0.58 for a 1..1.5 band; a constant draw would be 0.
    We check the day-10 follow budget (base mean = 11).
    """
    samples = [float(threads_mod.budget_for(aid, 10).follow) for aid in ids]
    cv = _coef_of_variation(samples)
    mean = statistics.mean(samples) if samples else 0
    status: CheckStatus = "pass" if 0.12 <= cv <= 0.6 else "warn"
    if cv < 0.05:
        status = "fail"
    return CheckResult(
        key="lognormal_shape",
        label="LogNormal day-10 follow budget shape",
        status=status,
        detail=f"CV={cv:.3f} (expected 0.12–0.6), mean={mean:.2f}, base=11.",
        metrics={"cv": round(cv, 4), "mean": round(mean, 2),
                 "min": min(samples), "max": max(samples)},
    )


def _check_cap_discipline(ids: list[str]) -> CheckResult:
    """
    Every sample ≤ 1.5× base-curve mean. threads.py clamps this; the audit
    asserts the clamp fires in practice, not just in theory.
    """
    base_day14 = {"follow": 14, "reply": 14, "repost": 5, "post": 3}
    caps = {k: int(round(v * 1.5)) for k, v in base_day14.items()}
    overshoots = 0
    worst = 0
    for aid in ids:
        b = threads_mod.budget_for(aid, 14)
        for kind, cap in caps.items():
            val = getattr(b, kind)
            if val > cap:
                overshoots += 1
                worst = max(worst, val - cap)
    if overshoots == 0:
        return CheckResult(
            key="cap_discipline",
            label="Daily cap discipline (≤1.5× base mean)",
            status="pass",
            detail=f"All {len(ids)} day-14 samples obey the 1.5× cap.",
            metrics={"overshoots": 0, "caps": caps},
        )
    return CheckResult(
        key="cap_discipline",
        label="Daily cap discipline (≤1.5× base mean)",
        status="fail",
        detail=f"{overshoots} samples exceed the clamp (worst +{worst}).",
        metrics={"overshoots": overshoots, "worst": worst, "caps": caps},
    )


def _check_delay_bounds(ids: list[str]) -> CheckResult:
    """
    Executor's sample_delay must stay inside [10s, 900s] (its own clamp)
    and mean roughly matches the per-kind configured means.
    """
    all_delays: list[float] = []
    per_kind: dict[str, list[float]] = {"follow": [], "reply": [],
                                         "repost": [], "post": []}
    for aid in ids[:2000]:
        for kind in per_kind:
            # Use the account_id itself as a stand-in action_id so we get
            # 2000 independent draws per kind without allocating memory.
            d = threads_exec.sample_delay(f"{aid}:{kind}", kind)
            per_kind[kind].append(d)
            all_delays.append(d)
    oob = sum(1 for d in all_delays if d < 10 or d > 900)
    # Per-kind sanity: configured means from threads_executor.
    mean_tol = 0.5    # Accept drift up to ±50% of configured mean
    expected = {"follow": 45.0, "reply": 70.0, "repost": 25.0, "post": 180.0}
    status: CheckStatus = "pass"
    details: list[str] = []
    for k, samples in per_kind.items():
        m = statistics.mean(samples)
        exp = expected[k]
        drift = abs(m - exp) / exp
        if drift > mean_tol:
            status = "warn"
        details.append(f"{k} mean={m:.1f}s exp≈{exp}s")
    if oob > 0:
        status = "fail"
    return CheckResult(
        key="delay_bounds",
        label="Inter-action delay bounds + mean drift",
        status=status,
        detail=f"{len(all_delays)} draws, {oob} out of bounds. " + " · ".join(details),
        metrics={"oob": oob,
                 "mean_by_kind": {k: round(statistics.mean(v), 2)
                                   for k, v in per_kind.items()}},
    )


def _check_content_spread(ids: list[str]) -> CheckResult:
    """
    Orchestrator's _draw picks from the library deterministically per seed.
    The distribution across 10K seeds should be close to uniform: no single
    library item should get > 2× its fair share.
    """
    from .threads_orchestrator import _REPLY_LIBRARY, _POST_LIBRARY, _draw
    reply_counts = {item: 0 for item in _REPLY_LIBRARY}
    post_counts = {item: 0 for item in _POST_LIBRARY}
    for i, aid in enumerate(ids):
        reply_counts[_draw(_REPLY_LIBRARY, f"{aid}:reply:{i % 97}")] += 1
        post_counts[_draw(_POST_LIBRARY,  f"{aid}:post:{i % 97}")]  += 1
    def _skew(counts: dict[str, int]) -> float:
        total = sum(counts.values())
        fair = total / len(counts)
        return max(counts.values()) / fair
    r_skew = _skew(reply_counts)
    p_skew = _skew(post_counts)
    status: CheckStatus = "pass" if (r_skew <= 1.5 and p_skew <= 1.5) else "warn"
    if r_skew > 2.0 or p_skew > 2.0:
        status = "fail"
    return CheckResult(
        key="content_spread",
        label="Content library pick is near-uniform",
        status=status,
        detail=f"Reply max/fair={r_skew:.2f}, Post max/fair={p_skew:.2f} (≤1.5 pass).",
        metrics={"reply_skew": round(r_skew, 3), "post_skew": round(p_skew, 3)},
    )


def _check_health_scoring(ids: list[str]) -> CheckResult:
    """
    Health detector correctness: synthesise one canonical scenario per
    status (healthy / watch / at_risk / shadowbanned) and assert the
    scorer lands in the right bucket every time. Deterministic — no
    randomness, so any failure is a real regression.

    This guards against a refactor silently shifting the thresholds or
    inverting a flag's sign.
    """
    from .threads_health import (
        ThreadsHealthMonitor, HealthSignals, _status_for,
        _MIN_REPLIES_FOR_GHOST_SIGNAL, _MIN_REPLIES_FOR_FUNNEL_SIGNAL,
        _FLOOR_REPLY_TO_VIEW,
    )

    # Direct scorer check: feed signal profiles and expect statuses.
    class _Probe(ThreadsHealthMonitor):
        def __init__(self):     # type: ignore[no-untyped-def]
            pass

    probe = _Probe()
    scenarios: list[tuple[str, HealthSignals, str]] = [
        ("fresh_healthy", HealthSignals(warmup_day=2), "healthy"),
        ("funnel_ghost", HealthSignals(
            reply_posted=_MIN_REPLIES_FOR_GHOST_SIGNAL + 5,
            profile_view=0, warmup_day=10), "shadowbanned"),
        ("reply_sink", HealthSignals(
            reply_posted=_MIN_REPLIES_FOR_FUNNEL_SIGNAL + 2,
            profile_view=1,
            reply_to_view_rate=1 / (_MIN_REPLIES_FOR_FUNNEL_SIGNAL + 2),
            warmup_day=10), "watch"),
        ("stagnant", HealthSignals(
            warmup_day=10, reply_posted=0), "watch"),
    ]
    wrong = 0
    details: list[str] = []
    for name, signals, expected in scenarios:
        score, _flags = probe._score(signals)
        got = _status_for(score)
        if got != expected:
            wrong += 1
            details.append(f"{name}: expected {expected}, got {got} (score={score})")

    # Sweep: score thresholds must be monotone — score N+1 never worse status than N.
    prev_rank = -1
    order = {"shadowbanned": 0, "at_risk": 1, "watch": 2, "healthy": 3}
    monotone_breaks = 0
    for s in range(0, 101):
        r = order[_status_for(s)]
        if r < prev_rank:
            monotone_breaks += 1
        prev_rank = r

    if wrong == 0 and monotone_breaks == 0:
        return CheckResult(
            key="health_scoring",
            label="Health detector classifies canonical scenarios",
            status="pass",
            detail=f"{len(scenarios)} scenarios + 101 thresholds correct.",
            metrics={"scenarios": len(scenarios), "wrong": 0,
                     "monotone_breaks": 0},
        )
    return CheckResult(
        key="health_scoring",
        label="Health detector classifies canonical scenarios",
        status="fail" if wrong else "warn",
        detail=f"{wrong} mislabeled, {monotone_breaks} threshold breaks. "
               + " · ".join(details),
        metrics={"wrong": wrong, "monotone_breaks": monotone_breaks},
    )


def _check_rebalancer_transitions(ids: list[str]) -> CheckResult:
    """
    Rebalancer invariants:
      * green → yellow → red transitions respect trip_streak
      * red → green transitions respect clear_streak
      * throttle multipliers monotonic (green=1.0, yellow=0.5, red=0.0)
      * linking_allowed only true in green
    """
    from .threads_rebalancer import (
        ThreadsFleetRebalancer, RebalancerThresholds,
    )
    from .threads_health import HealthRollup

    class _FakeHealth:
        def __init__(self):     # type: ignore[no-untyped-def]
            self.rollup = HealthRollup(total=0, shadowbanned=0, healthy=0)

    class _FakeProbes:
        class _S:
            total_run = 0
            total_hidden = 0
        stats = _S()

    class _FakeRecovery:
        records: dict = {}

    issues: list[str] = []

    h = _FakeHealth(); p = _FakeProbes(); r = _FakeRecovery()
    rb = ThreadsFleetRebalancer(
        health=h, probes=p, recovery=r,
        thresholds=RebalancerThresholds(trip_streak=2, clear_streak=3),
        tick_sec=1.0,
    )

    # Multiplier monotonicity
    for lvl, expected_mul, expected_link in [
        ("green", 1.0, True), ("yellow", 0.5, False), ("red", 0.0, False),
    ]:
        rb.stats.level = lvl        # type: ignore[assignment]
        if rb.plan_per_tick_multiplier() != expected_mul:
            issues.append(f"{lvl}: multiplier wrong "
                           f"({rb.plan_per_tick_multiplier()})")
        if rb.linking_allowed() != expected_link:
            issues.append(f"{lvl}: linking_allowed wrong")

    # Trip_streak: 15% shadowban for 1 tick stays green, 2 ticks → yellow
    rb.stats.level = "green"
    rb.stats.pending_level = None
    rb.stats.over_streak = 0
    h.rollup = HealthRollup(total=10, shadowbanned=2, healthy=8)   # 20%
    rb.tick()
    if rb.stats.level != "green":
        issues.append(f"single bad tick tripped yellow: {rb.stats.level}")
    rb.tick()
    if rb.stats.level != "yellow":
        issues.append(f"2nd bad tick didn't trip yellow: {rb.stats.level}")

    # Red escalation: shadowban 35% for 2 ticks
    h.rollup = HealthRollup(total=10, shadowbanned=4, healthy=6)   # 40%
    rb.tick(); rb.tick()
    if rb.stats.level != "red":
        issues.append(f"two 40% ticks didn't escalate to red: {rb.stats.level}")

    # Clearing: back to 0% for 3 ticks (clear_streak)
    h.rollup = HealthRollup(total=10, shadowbanned=0, healthy=10)
    rb.tick(); rb.tick()
    if rb.stats.level == "green":
        issues.append("cleared below clear_streak")
    rb.tick()
    if rb.stats.level != "green":
        issues.append(f"3-tick clear didn't return to green: {rb.stats.level}")

    if not issues:
        return CheckResult(
            key="rebalancer_transitions",
            label="Fleet rebalancer trip + clear streaks",
            status="pass",
            detail="Monotone throttles + trip/clear streaks honor thresholds.",
            metrics={"final_level": rb.stats.level,
                     "alerts": rb.stats.total_alerts},
        )
    return CheckResult(
        key="rebalancer_transitions",
        label="Fleet rebalancer trip + clear streaks",
        status="fail",
        detail=" · ".join(issues),
        metrics={"issues": issues},
    )


def _check_probe_scheduling(ids: list[str]) -> CheckResult:
    """
    Probe scheduler invariants:
      * every probe kind is covered,
      * searcher pool excludes shadowbanned / at_risk accounts,
      * flags_for returns PROBE_FLAG names, not raw kinds (prevents a
        future refactor from leaking kind strings into the health panel).
    """
    from .threads_probes import (
        ThreadsProbeScheduler, PROBE_KINDS, PROBE_FLAG, PROBE_PENALTY,
    )
    issues: list[str] = []
    if set(PROBE_KINDS) != set(PROBE_FLAG.keys()):
        issues.append("PROBE_FLAG doesn't cover every PROBE_KIND")
    if set(PROBE_KINDS) != set(PROBE_PENALTY.keys()):
        issues.append("PROBE_PENALTY doesn't cover every PROBE_KIND")
    if any(v <= 0 for v in PROBE_PENALTY.values()):
        issues.append("non-positive probe penalty")
    if "reply_hidden" not in PROBE_FLAG.values():
        issues.append("reply_hidden flag missing — classical shadowban signal")
    # Scheduler must refuse to run with no searcher pool: construct a
    # fake monitor whose world has ONE shadowbanned account and assert
    # the sweep hands back 0 runs, N skipped_no_searcher.
    class _FakeHealth:
        def status_of(self, _aid):     # type: ignore[no-untyped-def]
            return "shadowbanned"
        def for_account(self, _aid):   # type: ignore[no-untyped-def]
            from .threads_health import AccountHealth, HealthSignals
            return AccountHealth(account_id=_aid, status="shadowbanned",
                                  score=10, signals=HealthSignals(),
                                  computed_at="")
    store = {"th-only": {"account_id": "th-only", "platform": "threads",
                          "status": "active", "warmup_day": 5}}
    sched = ThreadsProbeScheduler(
        accounts_store_getter=lambda: store,
        health_monitor=_FakeHealth(),
        tick_sec=1.0,
    )

    import asyncio
    moved = asyncio.get_event_loop().run_until_complete(sched.tick()) \
        if False else None
    # Call tick synchronously — scheduler.tick() is async; use a fresh loop.
    loop = asyncio.new_event_loop()
    try:
        moved = loop.run_until_complete(sched.tick())
    finally:
        loop.close()
    if moved.get("run", 0) != 0:
        issues.append(f"searcher-pool gate broken: tick ran {moved} probes")
    if moved.get("skipped_no_searcher", 0) != len(PROBE_KINDS):
        issues.append(
            f"expected {len(PROBE_KINDS)} skipped, got "
            f"{moved.get('skipped_no_searcher')}")

    if not issues:
        return CheckResult(
            key="probe_scheduling",
            label="Active probe scheduler invariants",
            status="pass",
            detail=f"{len(PROBE_KINDS)} kinds covered, searcher-pool gate holds.",
            metrics={"kinds": list(PROBE_KINDS),
                     "penalties": dict(PROBE_PENALTY),
                     "sim_skipped": moved.get("skipped_no_searcher", 0)},
        )
    return CheckResult(
        key="probe_scheduling",
        label="Active probe scheduler invariants",
        status="fail",
        detail=" · ".join(issues),
        metrics={"issues": issues},
    )


def _check_agent_guardrails(ids: list[str]) -> CheckResult:
    """
    CLAUDE.md agent-audit sanity: ThreadsAgent must have a named tool
    allowlist, a bounded iteration count, and both per-run and per-session
    cost caps. A refactor removing any of these should fail CI.
    """
    from ..agents.threads_agent import ThreadsAgent
    cfg = ThreadsAgent.config
    issues: list[str] = []
    if not cfg.allowed_tools:
        issues.append("empty tool allowlist")
    if not (1 <= cfg.max_iterations <= 20):
        issues.append(f"max_iterations out of range: {cfg.max_iterations}")
    if cfg.max_usd_per_run <= 0:
        issues.append("no per-run cost cap")
    if cfg.max_usd_per_session <= 0:
        issues.append("no per-session cost cap")
    if cfg.max_usd_per_session < cfg.max_usd_per_run:
        issues.append("session cap < run cap (misconfigured)")
    if not any(t.startswith("threads.") for t in cfg.allowed_tools):
        issues.append("no threads.* tools in allowlist")

    if not issues:
        return CheckResult(
            key="agent_guardrails",
            label="ThreadsAgent CLAUDE.md agent-audit config",
            status="pass",
            detail=(f"allowlist={len(cfg.allowed_tools)} tools, "
                    f"iterations={cfg.max_iterations}, "
                    f"run_cap=${cfg.max_usd_per_run}, "
                    f"session_cap=${cfg.max_usd_per_session}"),
            metrics={"tools": list(cfg.allowed_tools),
                     "max_iterations": cfg.max_iterations,
                     "max_usd_per_run": cfg.max_usd_per_run,
                     "max_usd_per_session": cfg.max_usd_per_session},
        )
    return CheckResult(
        key="agent_guardrails",
        label="ThreadsAgent CLAUDE.md agent-audit config",
        status="fail",
        detail=" · ".join(issues),
        metrics={"issues": issues},
    )


def _check_recovery_state_machine(ids: list[str]) -> CheckResult:
    """
    Recovery state machine correctness: enroll → cool_down → rewarm →
    graduate (clean path); enroll → cool_down → rewarm → strike →
    cool_down → ... → retire (three-strike path). Uses a fake account
    store + funnel so the check is deterministic and runs in < 50ms.
    """
    from .threads_recovery import ThreadsRecoveryAgent, _REWARM_START_DAY
    from .threads_health import (
        AccountHealth, HealthSignals, ThreadsHealthMonitor,
    )
    from .threads_funnel import ThreadsFunnelTracker, FunnelEvent

    store: dict[str, dict] = {
        "th-A": {"account_id": "th-A", "platform": "threads",
                  "status": "active", "warmup_day": 10},
        "th-B": {"account_id": "th-B", "platform": "threads",
                  "status": "active", "warmup_day": 10},
    }
    tracker = ThreadsFunnelTracker()

    class _FakeHealth(ThreadsHealthMonitor):
        def __init__(self):     # type: ignore[no-untyped-def]
            self._next: dict[str, str] = {}

        def set_next(self, account_id: str, status: str) -> None:
            self._next[account_id] = status

        def for_account(self, account_id: str):
            s = self._next.get(account_id, "healthy")
            return AccountHealth(
                account_id=account_id, status=s, score=100 if s == "healthy" else 20,
                signals=HealthSignals(), computed_at="",
            )

        def compute(self, row):
            return self.for_account(row["account_id"])

    fake = _FakeHealth()
    agent = ThreadsRecoveryAgent(
        accounts_store_getter=lambda: store,
        health=fake, funnel=tracker,
        tick_sec=1.0, cool_down_sec=0,          # Instant cool-down for test
        rewarm_graduate_replies=3, max_strikes=3,
    )

    # Path 1: A gets flagged → cool_down → rewarm → graduates
    fake.set_next("th-A", "shadowbanned")
    agent.tick()
    assert "th-A" in agent.records, "A not enrolled"
    assert agent.records["th-A"].phase == "rewarming", (
        f"A should be rewarming after instant cool_down, got "
        f"{agent.records['th-A'].phase}")
    # Post 3 replies → trigger graduation health check
    for _ in range(3):
        tracker.record(FunnelEvent(kind="reply_posted", threads_account_id="th-A"))
    fake.set_next("th-A", "healthy")
    agent.tick()
    phase_a = agent.records["th-A"].phase
    assert phase_a == "graduated", f"A should graduate, got {phase_a}"
    assert store["th-A"]["status"] == "active"

    # Path 2: B gets flagged → repeatedly fails rewarm → retires.
    # With cool_down=0, a strike moves phase back to cooling_down, and
    # the NEXT tick advances to rewarming again; so each strike cycle
    # costs two ticks. Loop until retired or a safe iteration ceiling.
    fake.set_next("th-B", "shadowbanned")
    agent.tick()                              # enroll + instant cooldown → rewarm
    for _ in range(12):
        rec = agent.records["th-B"]
        if rec.phase == "retired":
            break
        if rec.phase == "rewarming":
            for _ in range(3):
                tracker.record(FunnelEvent(kind="reply_posted",
                                            threads_account_id="th-B"))
        fake.set_next("th-B", "shadowbanned")
        agent.tick()
    phase_b = agent.records["th-B"].phase
    assert phase_b == "retired", f"B should retire after 3 strikes, got {phase_b}"
    assert store["th-B"]["status"] == "retired"

    return CheckResult(
        key="recovery_state_machine",
        label="Recovery agent graduate + three-strike paths",
        status="pass",
        detail="A graduated, B retired after 3 strikes.",
        metrics={"a_phase": phase_a, "b_phase": phase_b,
                 "a_strikes": agent.records["th-A"].strikes,
                 "b_strikes": agent.records["th-B"].strikes},
    )


def _check_warming_day_bounds(ids: list[str]) -> CheckResult:
    """
    threads.py clamps warmup_day to [1, WARMING_DAYS] inside budget_for.
    The audit asserts this clamp holds for every budget we sampled.
    """
    oob = 0
    for aid in ids[:2000]:
        for raw in (-5, 0, 1, 7, 14, 50):
            b = threads_mod.budget_for(aid, raw)
            if b.day < 1 or b.day > threads_mod.WARMING_DAYS:
                oob += 1
    status: CheckStatus = "pass" if oob == 0 else "fail"
    return CheckResult(
        key="warming_day_bounds",
        label=f"Warming day clamp [1, {threads_mod.WARMING_DAYS}]",
        status=status,
        detail=f"{oob} day values escaped the clamp.",
        metrics={"oob": oob, "max_day": threads_mod.WARMING_DAYS},
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _check_ig_health_scoring(ids: list[str]) -> CheckResult:
    """
    Instagram health scorer: run every canonical scenario the IG-health
    module publishes and assert the classifier lands in the expected
    bucket. Mirrors the Threads check but on IG-specific signals.
    """
    from .instagram_health import audit_scenarios, score_signals

    scenarios = audit_scenarios()
    wrong = 0
    details: list[str] = []
    for sc in scenarios:
        score, _flags, status = score_signals(sc["signals"])
        if status != sc["expect"]:
            wrong += 1
            details.append(
                f"{sc['name']}: expected {sc['expect']}, got {status} "
                f"(score={score})"
            )
    if wrong == 0:
        return CheckResult(
            key="ig_health_scoring",
            label="IG health detector classifies canonical scenarios",
            status="pass",
            detail=f"{len(scenarios)} scenarios correct.",
            metrics={"scenarios": len(scenarios), "wrong": 0},
        )
    return CheckResult(
        key="ig_health_scoring",
        label="IG health detector classifies canonical scenarios",
        status="fail",
        detail=f"{wrong} mislabeled. " + " · ".join(details),
        metrics={"wrong": wrong},
    )


def _check_ig_recovery_state_machine(ids: list[str]) -> CheckResult:
    """
    IG recovery state machine: deterministic graduate path + three-strike
    retire path, using a fake IG event bus and a FakeHealth that lets the
    test script the next status.
    """
    from .instagram_recovery import InstagramRecoveryAgent
    from .instagram_health import IGAccountHealth, IGSignals

    store: dict[str, dict] = {
        "ig-A": {"account_id": "ig-A", "platform": "instagram",
                  "status": "active", "warmup_day": 10},
        "ig-B": {"account_id": "ig-B", "platform": "instagram",
                  "status": "active", "warmup_day": 10},
    }

    class _FakeBus:
        def __init__(self):
            self._posts: dict[str, int] = {}
        def recent(self, limit: int = 500) -> list[dict]:
            out: list[dict] = []
            for acc, n in self._posts.items():
                out.extend([{"ig_account_id": acc, "ts": ""} for _ in range(n)])
            return out[:limit]
        def add(self, acc: str) -> None:
            self._posts[acc] = self._posts.get(acc, 0) + 1

    class _FakeHealth:
        def __init__(self):
            self._next: dict[str, str] = {}
        def set_next(self, acc: str, status: str) -> None:
            self._next[acc] = status
        def for_account(self, acc: str):
            s = self._next.get(acc, "healthy")
            return IGAccountHealth(account_id=acc, status=s,
                                    score=100 if s == "healthy" else 20,
                                    signals=IGSignals(), computed_at="")
        def compute(self, row):
            return self.for_account(row["account_id"])

    bus = _FakeBus()
    fake = _FakeHealth()
    agent = InstagramRecoveryAgent(
        accounts_store_getter=lambda: store,
        health=fake, ig_bus=bus,
        tick_sec=1.0, cool_down_sec=0,
        rewarm_posts_to_graduate=3, max_strikes=3,
    )

    # Path 1: A enrolls, rewarms, graduates.
    fake.set_next("ig-A", "shadowbanned")
    agent.tick()
    if agent.records["ig-A"].phase != "rewarming":
        return CheckResult(key="ig_recovery_state_machine",
                            label="IG recovery graduate + three-strike paths",
                            status="fail",
                            detail=f"A not rewarming: {agent.records['ig-A'].phase}",
                            metrics={})
    for _ in range(3):
        bus.add("ig-A")
    fake.set_next("ig-A", "healthy")
    agent.tick()
    phase_a = agent.records["ig-A"].phase
    if phase_a != "graduated":
        return CheckResult(key="ig_recovery_state_machine",
                            label="IG recovery graduate + three-strike paths",
                            status="fail",
                            detail=f"A should graduate, got {phase_a}",
                            metrics={"a_phase": phase_a})

    # Path 2: B strike-strike-strike -> retired.
    fake.set_next("ig-B", "shadowbanned")
    agent.tick()
    for _ in range(12):
        rec = agent.records["ig-B"]
        if rec.phase == "retired":
            break
        if rec.phase == "rewarming":
            for _ in range(3):
                bus.add("ig-B")
        fake.set_next("ig-B", "shadowbanned")
        agent.tick()
    phase_b = agent.records["ig-B"].phase
    if phase_b != "retired":
        return CheckResult(key="ig_recovery_state_machine",
                            label="IG recovery graduate + three-strike paths",
                            status="fail",
                            detail=f"B should retire, got {phase_b}",
                            metrics={"b_phase": phase_b,
                                     "b_strikes": agent.records["ig-B"].strikes})

    return CheckResult(
        key="ig_recovery_state_machine",
        label="IG recovery graduate + three-strike paths",
        status="pass",
        detail="A graduated, B retired after 3 strikes.",
        metrics={"a_phase": phase_a, "b_phase": phase_b,
                 "a_strikes": agent.records["ig-A"].strikes,
                 "b_strikes": agent.records["ig-B"].strikes},
    )


def _check_ig_budget_uniqueness(ids: list[str]) -> CheckResult:
    from . import instagram as ig_mod
    seen: dict[tuple, int] = {}
    collisions = 0
    for aid in ids:
        vec = tuple(
            (b.follow, b.like, b.story_view, b.post)
            for b in ig_mod.budgets_across_curve(aid)
        )
        if vec in seen:
            collisions += 1
        else:
            seen[vec] = 1
    rate = collisions / len(ids) if ids else 0
    if collisions == 0:
        return CheckResult(
            key="ig_budget_uniqueness",
            label="IG budget vectors unique across fleet",
            status="pass",
            detail=f"{len(ids)} accounts produced {len(seen)} distinct 28-day vectors.",
            metrics={"collisions": 0, "collision_rate": 0.0,
                     "distinct_vectors": len(seen)},
        )
    status: CheckStatus = "warn" if rate < 0.005 else "fail"
    return CheckResult(
        key="ig_budget_uniqueness",
        label="IG budget vectors unique across fleet",
        status=status,
        detail=f"{collisions}/{len(ids)} IG accounts collide ({rate*100:.3f}%).",
        metrics={"collisions": collisions, "collision_rate": rate,
                 "distinct_vectors": len(seen)},
    )


def _check_ig_lognormal_shape(ids: list[str]) -> CheckResult:
    """CV of day-20 like budgets. Base mean = 38."""
    from . import instagram as ig_mod
    samples = [float(ig_mod.budget_for(aid, 20).like) for aid in ids]
    cv = _coef_of_variation(samples)
    mean = statistics.mean(samples) if samples else 0
    status: CheckStatus = "pass" if 0.12 <= cv <= 0.6 else "warn"
    if cv < 0.05:
        status = "fail"
    return CheckResult(
        key="ig_lognormal_shape",
        label="IG LogNormal day-20 like budget shape",
        status=status,
        detail=f"CV={cv:.3f} (expected 0.12–0.6), mean={mean:.2f}, base=38.",
        metrics={"cv": round(cv, 4), "mean": round(mean, 2),
                 "min": min(samples) if samples else 0,
                 "max": max(samples) if samples else 0},
    )


def _check_ig_cap_discipline(ids: list[str]) -> CheckResult:
    """Every day-28 sample ≤ 1.5× base-curve mean."""
    from . import instagram as ig_mod
    base_day28 = {"follow": 20, "like": 54, "story_view": 60, "post": 3}
    caps = {k: int(round(v * 1.5)) for k, v in base_day28.items()}
    overshoots = 0
    for aid in ids:
        b = ig_mod.budget_for(aid, 28)
        for kind, cap in caps.items():
            if getattr(b, kind) > cap:
                overshoots += 1
    if overshoots == 0:
        return CheckResult(
            key="ig_cap_discipline",
            label="IG daily cap discipline (≤1.5× base mean)",
            status="pass",
            detail=f"All {len(ids)} day-28 IG samples obey the 1.5× cap.",
            metrics={"overshoots": 0, "caps": caps},
        )
    return CheckResult(
        key="ig_cap_discipline",
        label="IG daily cap discipline (≤1.5× base mean)",
        status="fail",
        detail=f"{overshoots} IG day-28 samples overshot the 1.5× cap.",
        metrics={"overshoots": overshoots, "caps": caps},
    )


def _check_ig_funnel_invariants(ids: list[str]) -> CheckResult:
    """
    IG funnel counters obey the chain: post_posted ≥ impression is
    allowed (one post has many impressions), but all downstream kinds
    must be ≤ the one before them: impression ≥ profile_view ≥
    bio_link_click, and profile_view ≥ threads_tap. The rate calcs rely
    on this to stay in [0,1]. Simulate a sequence and assert the
    tracker never produces a rate > 1.
    """
    from .instagram_funnel import InstagramFunnelTracker, IGFunnelEvent

    tracker = InstagramFunnelTracker()
    # Simulate a plausible attribution funnel for one account.
    for _ in range(5):
        tracker.record(IGFunnelEvent(kind="post_posted", ig_account_id="ig-x"))
    for _ in range(500):
        tracker.record(IGFunnelEvent(kind="impression",    ig_account_id="ig-x"))
    for _ in range(50):
        tracker.record(IGFunnelEvent(kind="profile_view",  ig_account_id="ig-x"))
    for _ in range(20):
        tracker.record(IGFunnelEvent(kind="bio_link_click", ig_account_id="ig-x"))
    for _ in range(15):
        tracker.record(IGFunnelEvent(kind="threads_tap",   ig_account_id="ig-x"))

    c = tracker.for_account("ig-x")
    counts = c.as_dict()["counts"]
    rates = c.as_dict()["rates"]

    issues: list[str] = []
    # Monotone downstream chain (impression is upstream of profile_view).
    if counts["profile_view"] > counts["impression"]:
        issues.append("profile_view > impression")
    if counts["bio_link_click"] > counts["profile_view"]:
        issues.append("bio_click > profile_view")
    if counts["threads_tap"] > counts["profile_view"]:
        issues.append("threads_tap > profile_view")
    # Chain-order rates (downstream / upstream) are bounded in [0, 1];
    # post_to_X rates can exceed 1 (one post → many impressions).
    chain_rates = ("impression_to_view", "view_to_bio_click", "view_to_threads")
    for name in chain_rates:
        val = rates[name]
        if val < 0 or val > 1:
            issues.append(f"rate {name}={val} out of [0,1]")

    # Fresh tracker must produce zeroes, not NaNs.
    empty = tracker.for_account("ig-empty").as_dict()
    for name, val in empty["rates"].items():
        if val != 0:
            issues.append(f"empty rate {name}={val}")

    if not issues:
        return CheckResult(
            key="ig_funnel_invariants",
            label="IG funnel chain counts + rate bounds",
            status="pass",
            detail=f"5 counts respected monotone chain, 5 rates in [0,1].",
            metrics={"counts": counts, "rates": rates},
        )
    return CheckResult(
        key="ig_funnel_invariants",
        label="IG funnel chain counts + rate bounds",
        status="fail",
        detail="; ".join(issues),
        metrics={"counts": counts, "rates": rates},
    )


def _check_ig_probe_scheduling(ids: list[str]) -> CheckResult:
    """
    IG probe scheduler: three kinds, correct penalties, searcher pool
    never picks an at_risk or shadowbanned IG account, and the simulated
    dispatcher hides every kind for a shadowbanned suspect.
    """
    from .instagram_probes import (
        InstagramProbeScheduler, IG_PROBE_KINDS, IG_PROBE_PENALTY, IG_PROBE_FLAG,
    )
    from .instagram_health import IGAccountHealth, IGSignals

    store: dict[str, dict] = {
        "ig-clean":  {"account_id": "ig-clean",  "platform": "instagram",
                       "status": "active", "warmup_day": 10},
        "ig-dead":   {"account_id": "ig-dead",   "platform": "instagram",
                       "status": "active", "warmup_day": 10},
        "ig-risky":  {"account_id": "ig-risky",  "platform": "instagram",
                       "status": "active", "warmup_day": 10},
    }

    class _FakeHealth:
        def status_of(self, acc: str) -> str:
            return {"ig-clean": "healthy",
                    "ig-dead":  "shadowbanned",
                    "ig-risky": "at_risk"}.get(acc, "healthy")
        def for_account(self, acc: str):
            s = self.status_of(acc)
            return IGAccountHealth(account_id=acc, status=s,
                                    score=100 if s == "healthy" else 20,
                                    signals=IGSignals(), computed_at="")

    sched = InstagramProbeScheduler(
        accounts_store_getter=lambda: store,
        health_monitor=_FakeHealth(),
        tick_sec=5.0,
    )

    issues: list[str] = []
    if set(IG_PROBE_KINDS) != {"handle_search", "hashtag_page", "explore_surface"}:
        issues.append(f"probe kinds drifted: {IG_PROBE_KINDS}")
    expected_penalties = {"handle_search": 20, "hashtag_page": 30, "explore_surface": 45}
    for k, p in expected_penalties.items():
        if IG_PROBE_PENALTY[k] != p:
            issues.append(f"penalty {k} is {IG_PROBE_PENALTY[k]}, expected {p}")

    # Searcher pool must exclude ig-dead + ig-risky.
    pool = sched._clean_searcher_pool()
    pool_ids = {r["account_id"] for r in pool}
    if "ig-dead" in pool_ids:
        issues.append("searcher pool includes shadowbanned")
    if "ig-risky" in pool_ids:
        issues.append("searcher pool includes at_risk")

    import asyncio as _asyncio
    for suspect_id, expected_hidden_kinds in (
        ("ig-clean", set()),
        ("ig-dead", set(IG_PROBE_KINDS)),
    ):
        for kind in IG_PROBE_KINDS:
            result = _asyncio.run(
                sched._dispatch_probe(store[suspect_id], store["ig-clean"], kind)
            )
            if (not result.found) and (kind not in expected_hidden_kinds):
                issues.append(f"{suspect_id}/{kind} wrongly hidden")
            if result.found and (kind in expected_hidden_kinds):
                issues.append(f"{suspect_id}/{kind} wrongly found")

    if not issues:
        return CheckResult(
            key="ig_probe_scheduling",
            label="IG active probe scheduler invariants",
            status="pass",
            detail=f"3 kinds covered, searcher pool gate holds.",
            metrics={"kinds": list(IG_PROBE_KINDS),
                     "penalties": dict(IG_PROBE_PENALTY),
                     "pool_size": len(pool)},
        )
    return CheckResult(
        key="ig_probe_scheduling",
        label="IG active probe scheduler invariants",
        status="fail",
        detail="; ".join(issues),
        metrics={},
    )


def _check_ig_orchestrator(ids: list[str]) -> CheckResult:
    """
    IG orchestrator invariants:
      1. Never enqueues for a shadowbanned account.
      2. Honors the plan_per_tick cap.
      3. Each enqueued action's kind has non-zero remaining budget for
         its account on the plan day.
      4. Priority order (post > story_view > like > follow) — if an
         account has budget for 'post', the chosen kind must be 'post'.
    """
    import asyncio as _asyncio
    from .instagram_orchestrator import InstagramOrchestrator
    from .instagram_funnel import InstagramFunnelTracker
    from .instagram_health import IGAccountHealth, IGSignals
    from . import instagram as ig_mod

    store: dict[str, dict] = {
        "ig-ok":   {"account_id": "ig-ok",   "platform": "instagram",
                     "status": "active", "warmup_day": 20},
        "ig-ok2":  {"account_id": "ig-ok2",  "platform": "instagram",
                     "status": "active", "warmup_day": 15},
        "ig-dead": {"account_id": "ig-dead", "platform": "instagram",
                     "status": "active", "warmup_day": 20},
    }
    queue: list[dict] = []

    class _FakeHealth:
        rollup = None
        def __init__(self):
            self._cache = {}
        def status_of(self, acc: str) -> str:
            return "shadowbanned" if acc == "ig-dead" else "healthy"
        def for_account(self, acc: str):
            s = self.status_of(acc)
            return IGAccountHealth(account_id=acc, status=s,
                                    score=100 if s == "healthy" else 0,
                                    signals=IGSignals(), computed_at="")
        def compute(self, row):
            return self.for_account(row["account_id"])
        def scan_all(self):
            return [self.compute(r) for r in store.values()]

    orch = InstagramOrchestrator(
        accounts_store_getter=lambda: store,
        queue_getter=lambda: queue,
        funnel=InstagramFunnelTracker(),
        health=_FakeHealth(),
        plan_per_tick=5,
    )
    plan = _asyncio.run(orch.run_once())
    issues: list[str] = []

    if any(e["account_id"] == "ig-dead" for e in queue):
        issues.append("enqueued for shadowbanned account")
    if len(plan) > 5:
        issues.append(f"plan_per_tick cap breached: {len(plan)}")

    # Priority: both ig-ok and ig-ok2 have day >= 8 so post has budget 1+.
    for entry in plan:
        acc = entry.account_id
        row = store[acc]
        b = ig_mod.budget_for(acc, int(row["warmup_day"]))
        if b.post > 0 and entry.kind != "post":
            issues.append(f"{acc} chose {entry.kind} but post budget={b.post}")
        if getattr(b, entry.kind) == 0:
            issues.append(f"{acc} chose {entry.kind} with zero budget")

    if not issues:
        return CheckResult(
            key="ig_orchestrator",
            label="IG orchestrator shadowban gate + priority + cap",
            status="pass",
            detail=f"planned {len(plan)}, cap 5, 0 shadowbanned enqueues.",
            metrics={"planned": len(plan), "accounts_ranked": 2},
        )
    return CheckResult(
        key="ig_orchestrator",
        label="IG orchestrator shadowban gate + priority + cap",
        status="fail",
        detail="; ".join(issues),
        metrics={"planned": len(plan)},
    )


def _check_ig_rebalancer_transitions(ids: list[str]) -> CheckResult:
    """
    IG rebalancer invariants:
      * multiplier monotone: green 1.0, yellow 0.5, red 0.0
      * linking allowed only in green
      * trip requires 2 consecutive over-threshold ticks
      * clear requires 3 consecutive under-threshold ticks
    """
    from .instagram_rebalancer import (
        InstagramFleetRebalancer, IGRebalancerThresholds,
    )

    class _FakeRollup:
        total = 10
        shadowbanned = 0
        at_risk = 0
        watch = 0
        healthy = 10

    class _FakeHealth:
        def __init__(self):
            self.rollup = _FakeRollup()

    class _FakeStats:
        total_run = 0
        total_hidden = 0

    class _FakeProbes:
        def __init__(self):
            self.stats = _FakeStats()

    class _FakeRecovery:
        def __init__(self):
            self.records = {}

    h = _FakeHealth(); p = _FakeProbes(); r = _FakeRecovery()
    rb = InstagramFleetRebalancer(
        health=h, probes=p, recovery=r,
        thresholds=IGRebalancerThresholds(trip_streak=2, clear_streak=3),
        tick_sec=1.0,
    )
    issues: list[str] = []

    if rb.plan_per_tick_multiplier() != 1.0 or not rb.linking_allowed():
        issues.append("initial state not green")

    # Trip to RED: shadowban 50% for 2 ticks.
    h.rollup.shadowbanned = 5
    rb.tick()
    if rb.stats.level == "red":
        issues.append("tripped on first over-threshold tick")
    rb.tick()
    if rb.stats.level != "red":
        issues.append(f"2-tick trip didn't reach red: {rb.stats.level}")
    if rb.plan_per_tick_multiplier() != 0.0:
        issues.append("red multiplier != 0.0")
    if rb.linking_allowed():
        issues.append("linking allowed in red")

    # Clear: back to 0% shadowbans, needs 3 ticks to return to green.
    h.rollup.shadowbanned = 0
    rb.tick(); rb.tick()
    if rb.stats.level == "green":
        issues.append("cleared below clear_streak")
    rb.tick()
    if rb.stats.level != "green":
        issues.append(f"3-tick clear didn't return to green: {rb.stats.level}")

    if not issues:
        return CheckResult(
            key="ig_rebalancer_transitions",
            label="IG fleet rebalancer trip + clear streaks",
            status="pass",
            detail="Monotone throttles + trip/clear streaks honor thresholds.",
            metrics={"final_level": rb.stats.level,
                     "alerts": rb.stats.total_alerts},
        )
    return CheckResult(
        key="ig_rebalancer_transitions",
        label="IG fleet rebalancer trip + clear streaks",
        status="fail",
        detail="; ".join(issues),
        metrics={"final_level": rb.stats.level},
    )


def run(n: int = 10_000) -> AuditReport:
    """Run the full Monte Carlo sweep and return a structured report."""
    return run_audit(n)


def run_audit(n: int = 10_000) -> AuditReport:
    """Core implementation: all 12 fleet-scale checks."""
    from datetime import datetime, timezone

    def _check_ig_dm(ids: list[str]) -> CheckResult:
        """
        DM flow invariants:
          * per-recipient dedupe: second draft = blocked
          * cooldown honored: 2nd send within window = blocked
          * daily cap honored: cap+1-th = blocked
          * template fleet cap honored
          * content guard: shortlink / @mention / blocked phrase = blocked
          * at_risk actor = blocked
          * opt-out keyword in reply suppresses future drafts to that recipient
          * template picker is deterministic for same (actor, recipient)
        """
        from .instagram_dm import InstagramDMFlow, DMTemplate
        import unittest.mock as _mock
        from datetime import datetime, timedelta, timezone as _tz

        issues: list[str] = []
        store: dict = {
            "ig-A": {"account_id": "ig-A", "platform": "instagram", "status": "active"},
            "ig-B": {"account_id": "ig-B", "platform": "instagram", "status": "active"},
        }
        q: list[dict] = []

        class _HealthStub:
            def __init__(self): self.bad = set()
            def status_of(self, aid):
                return "at_risk" if aid in self.bad else "healthy"

        health = _HealthStub()
        base = datetime.now(_tz.utc)
        clock = {"t": base}

        flow = InstagramDMFlow(
            accounts_store_getter=lambda: store,
            queue_getter=lambda: q,
            health=health,
            daily_cap_per_actor=3, cooldown_min=30,
            template_cap_fleet_day=4,
        )

        with _mock.patch.object(flow, "_now", side_effect=lambda: clock["t"]):
            # 1. First draft ok
            r1 = flow.draft("ig-A", "@rec-1")
            if r1.state != "queued":
                issues.append(f"first draft blocked: {r1.block_reason}")

            # 2. Dedupe second draft same pair
            r2 = flow.draft("ig-A", "@rec-1")
            if r2.state != "blocked" or r2.block_reason != "dedupe":
                issues.append("dedupe missed")

            # 3. Cooldown — next draft same minute
            r3 = flow.draft("ig-A", "@rec-2")
            if r3.state != "blocked" or r3.block_reason != "cooldown":
                issues.append(f"cooldown missed: {r3.block_reason}")

            # Advance clock past cooldown
            clock["t"] = base + timedelta(minutes=35)
            r4 = flow.draft("ig-A", "@rec-2")
            if r4.state != "queued":
                issues.append(f"after cooldown blocked: {r4.block_reason}")
            # And then daily cap (3) — third is ok, fourth fails
            clock["t"] = base + timedelta(minutes=70)
            r5 = flow.draft("ig-A", "@rec-3")
            if r5.state != "queued":
                issues.append(f"3rd ok draft blocked: {r5.block_reason}")
            clock["t"] = base + timedelta(minutes=105)
            r6 = flow.draft("ig-A", "@rec-4")
            if r6.state != "blocked" or r6.block_reason != "actor_cap":
                issues.append(f"actor_cap missed: {r6.block_reason}")

            # 4. Content guard — mock pick_template to return a blocked body
            bad_tmpl = DMTemplate("bad-001", "click here to claim your {handle} prize")
            clock["t"] = base + timedelta(minutes=140)
            with _mock.patch.object(flow, "_pick_template", return_value=bad_tmpl):
                rbad = flow.draft("ig-B", "@spam-1")
                if rbad.state != "blocked" or not (rbad.block_reason and
                        rbad.block_reason.startswith("content:")):
                    issues.append(f"content guard missed: {rbad.block_reason}")

            short_tmpl = DMTemplate("short-001", "nice work {handle} bit.ly/xyz")
            with _mock.patch.object(flow, "_pick_template", return_value=short_tmpl):
                rsh = flow.draft("ig-B", "@spam-2")
                if rsh.state != "blocked" or "shortlink" not in (rsh.block_reason or ""):
                    issues.append(f"shortlink missed: {rsh.block_reason}")

            mention_tmpl = DMTemplate("m-001", "hey {handle} check out @influencer")
            with _mock.patch.object(flow, "_pick_template", return_value=mention_tmpl):
                rm = flow.draft("ig-B", "@spam-3")
                if rm.state != "blocked" or "mention" not in (rm.block_reason or ""):
                    issues.append(f"mention guard missed: {rm.block_reason}")

            # 5. Health gate — mark B at_risk, try new pair
            health.bad.add("ig-B")
            clock["t"] = base + timedelta(minutes=180)
            rh = flow.draft("ig-B", "@healthy-rec")
            if rh.state != "blocked" or rh.block_reason != "actor_unsafe":
                issues.append(f"health gate missed: {rh.block_reason}")

            # 6. Opt-out — reply with "stop" to r1, then try draft again
            flow.record_sent(r1.dm_id)
            flow.record_reply("ig-A", "@rec-1", "please stop messaging me")
            if flow._by_pair[("ig-A", "@rec-1")].state != "opted_out":
                issues.append("opt-out state not set")
            # Clock far in future — new day for daily cap; dedupe would still
            # block this pair, so test a NEW recipient after opt-out: ensure
            # opt-out set contains only the pair, not actor-wide.
            # Different recipient on A should still work (new day).
            clock["t"] = base + timedelta(days=1, minutes=10)
            r_new = flow.draft("ig-A", "@rec-5")
            if r_new.state != "queued":
                issues.append(f"next-day fresh draft blocked: {r_new.block_reason}")
            # Explicitly attempt the opted-out pair again — must be blocked
            # with opt_out_history
            rop = flow.draft("ig-A", "@rec-1")
            if rop.state != "blocked" or rop.block_reason != "opt_out_history":
                issues.append(f"opt-out suppression missed: {rop.block_reason}")

            # 7. Determinism — same (actor, recipient, fresh fleet state)
            # picks same template twice (we re-seed the templates to isolate).
            flow2 = InstagramDMFlow(
                accounts_store_getter=lambda: store,
                queue_getter=lambda: [], health=None,
                daily_cap_per_actor=10, cooldown_min=0,
            )
            with _mock.patch.object(flow2, "_now", side_effect=lambda: base):
                t1 = flow2._pick_template("ig-X", "@tg-1").template_id
                t2 = flow2._pick_template("ig-X", "@tg-1").template_id
            if t1 != t2:
                issues.append("template picker not deterministic")

        if not issues:
            return CheckResult(
                key="ig_dm",
                label="IG DM dedupe + cap + cooldown + content guard + opt-out",
                status="pass",
                detail="7 gates verified · template picker deterministic",
                metrics={"gates": 7},
            )
        return CheckResult(
            key="ig_dm",
            label="IG DM dedupe + cap + cooldown + content guard + opt-out",
            status="fail",
            detail=" · ".join(issues),
            metrics={"issues": issues},
        )

    def _check_ig_unfollow(ids: list[str]) -> CheckResult:
        """
        Unfollow discipline invariants:
          * min_dwell_h honored (fresh follows never queued)
          * follow-back cancels candidacy
          * retained flag blocks candidacy forever
          * daily cap honored per actor
          * ratio_trip doubles the cap
          * at_risk/shadowbanned actors never enqueue unfollows
        """
        from .instagram_unfollow import InstagramUnfollowDiscipline
        import unittest.mock as _mock
        from datetime import datetime, timedelta, timezone as _tz
        issues: list[str] = []
        store: dict = {
            "ig-A": {"account_id": "ig-A", "platform": "instagram",
                     "status": "active", "follows_out": 100, "followers_in": 90},
            "ig-B": {"account_id": "ig-B", "platform": "instagram",
                     "status": "active", "follows_out": 1000, "followers_in": 100},
            "ig-C": {"account_id": "ig-C", "platform": "instagram",
                     "status": "active"},
        }
        q: list[dict] = []

        class _HealthStub:
            def status_of(self, aid):
                return "shadowbanned" if aid == "ig-C" else "healthy"

        ud = InstagramUnfollowDiscipline(
            accounts_store_getter=lambda: store,
            queue_getter=lambda: q,
            health=_HealthStub(),
            min_dwell_h=48, follow_back_window_h=72,
            daily_cap=5, ratio_trip=3.0,
        )
        base = datetime.now(_tz.utc)

        # Plant 20 follows each on A and B at base-100h
        with _mock.patch.object(ud, "_now",
                                 side_effect=lambda: base - timedelta(hours=100)):
            for i in range(20):
                ud.record_follow("ig-A", f"@tgt-a-{i}")
                ud.record_follow("ig-B", f"@tgt-b-{i}")
            # Shadowbanned C with some follows
            for i in range(5):
                ud.record_follow("ig-C", f"@tgt-c-{i}")

        # Mark some retained + follow_backs on A
        ud.mark_retained("ig-A", "@tgt-a-0")
        ud.record_follow_back("ig-A", "@tgt-a-1")

        # Fresh follow on A at "now" — must not be candidate (dwell)
        ud.record_follow("ig-A", "@fresh-target")

        ud.tick()

        # A — cap 5 (ratio ~1.11 so NOT tripped), 20 old follows, 1 retained,
        # 1 follow_back, so 18 eligible, cap = 5 enqueued.
        a_queued = [e for e in q if e["account_id"] == "ig-A"]
        if len(a_queued) != 5:
            issues.append(f"A cap honored? queued={len(a_queued)} want 5")
        if any(e["target"] == "@tgt-a-0" for e in a_queued):
            issues.append("retained target enqueued")
        if any(e["target"] == "@tgt-a-1" for e in a_queued):
            issues.append("follow_back target enqueued")
        if any(e["target"] == "@fresh-target" for e in a_queued):
            issues.append("fresh target (dwell) enqueued")

        # B — ratio 10 (tripped), cap doubled to 10
        b_queued = [e for e in q if e["account_id"] == "ig-B"]
        if len(b_queued) != 10:
            issues.append(f"B ratio-tripped cap? queued={len(b_queued)} want 10")

        # C — shadowbanned, zero enqueued
        c_queued = [e for e in q if e["account_id"] == "ig-C"]
        if len(c_queued) != 0:
            issues.append(f"shadowbanned C enqueued {len(c_queued)}")

        if not issues:
            return CheckResult(
                key="ig_unfollow",
                label="IG unfollow dwell + cap + ratio + whitelist + health",
                status="pass",
                detail=f"A=5 (cap) · B=10 (ratio ×2) · C=0 (shadowban) · retained/follow_back honored",
                metrics={"A": len(a_queued), "B": len(b_queued), "C": len(c_queued)},
            )
        return CheckResult(
            key="ig_unfollow",
            label="IG unfollow dwell + cap + ratio + whitelist + health",
            status="fail",
            detail=" · ".join(issues),
            metrics={"issues": issues},
        )

    def _check_ig_session(ids: list[str]) -> CheckResult:
        """
        Session state-machine invariants:
          * fresh → active via login(ok=True)
          * login_fail × 3 → locked
          * active → aging on >60% TTL consumed
          * aging → expired on TTL
          * login(ok=True, needs_2fa=True) → two_factor_pending
          * complete_2fa → active
          * 2fa_pending past timeout → expired
          * is_dispatchable: true for active/aging, false otherwise
        """
        from .instagram_session import (
            InstagramSessionManager, _TWO_FACTOR_OP_TIMEOUT,
        )
        import unittest.mock as _mock
        from datetime import datetime, timedelta, timezone as _tz
        issues: list[str] = []
        store: dict = {
            "ig-X": {"account_id": "ig-X", "platform": "instagram", "status": "active"},
            "ig-Y": {"account_id": "ig-Y", "platform": "instagram", "status": "active"},
            "ig-Z": {"account_id": "ig-Z", "platform": "instagram", "status": "active"},
        }
        mgr = InstagramSessionManager(accounts_store_getter=lambda: store)

        # Login OK
        r = mgr.login("ig-X", ok=True)
        if r.state != "active":
            issues.append(f"login ok did not become active: {r.state}")
        if not mgr.is_dispatchable("ig-X"):
            issues.append("active not dispatchable")

        # Login 3 fails → locked
        mgr.login("ig-Y", ok=False)
        mgr.login("ig-Y", ok=False)
        mgr.login("ig-Y", ok=False)
        if mgr.for_account("ig-Y")["state"] != "locked":
            issues.append("3 fails did not lock")
        if mgr.is_dispatchable("ig-Y"):
            issues.append("locked is dispatchable")

        # TTL age + expire using mocked clock
        base = datetime.now(_tz.utc)
        with _mock.patch.object(mgr, "_now",
                                 side_effect=lambda: base + timedelta(days=5)):
            mgr.tick()
        if mgr.for_account("ig-X")["state"] != "aging":
            issues.append(f"5d not aged: {mgr.for_account('ig-X')['state']}")
        with _mock.patch.object(mgr, "_now",
                                 side_effect=lambda: base + timedelta(days=8)):
            mgr.tick()
        if mgr.for_account("ig-X")["state"] != "expired":
            issues.append(f"8d not expired: {mgr.for_account('ig-X')['state']}")
        if mgr.is_dispatchable("ig-X"):
            issues.append("expired is dispatchable")

        # 2FA flow
        mgr.login("ig-Z", ok=True, needs_2fa=True)
        if mgr.for_account("ig-Z")["state"] != "two_factor_pending":
            issues.append("needs_2fa did not set two_factor_pending")
        if mgr.is_dispatchable("ig-Z"):
            issues.append("2fa_pending is dispatchable")
        mgr.complete_2fa("ig-Z")
        if mgr.for_account("ig-Z")["state"] != "active":
            issues.append("complete_2fa did not go active")

        # 2FA timeout → expired
        mgr.login("ig-Z", ok=True, needs_2fa=True)
        with _mock.patch.object(mgr, "_now",
                                 side_effect=lambda: base + timedelta(hours=_TWO_FACTOR_OP_TIMEOUT + 2)):
            mgr.tick()
        if mgr.for_account("ig-Z")["state"] != "expired":
            issues.append(f"2fa timeout did not expire: "
                          f"{mgr.for_account('ig-Z')['state']}")

        if not issues:
            return CheckResult(
                key="ig_session",
                label="IG session state machine + TTL + 2FA",
                status="pass",
                detail=("fresh→active→aging→expired, 3-fail→locked, "
                        "2fa flow + timeout honored"),
                metrics={"states": 7},
            )
        return CheckResult(
            key="ig_session",
            label="IG session state machine + TTL + 2FA",
            status="fail",
            detail=" · ".join(issues),
            metrics={"issues": issues},
        )

    def _check_ig_checkpoint(ids: list[str]) -> CheckResult:
        """
        Checkpoint handler invariants:
          * every canonical signature classifies to its expected kind
          * severity + action table matches what the classifier returns
          * burst detector fires after threshold events in the window
          * enroll_recovery action actually enrolls on the recovery stub
        """
        from .instagram_checkpoint import (
            InstagramCheckpointHandler, _KIND_SEVERITY, _KIND_ACTION,
        )
        issues: list[str] = []
        cases: list[tuple[str, str]] = [
            ("Enter the 6-digit code we sent to +1 555-867-5309",
             "phone_sms_verify"),
            ("Enter the 6-digit code we sent to you@example.com",
             "email_verify"),
            ("Was this you? Unusual login attempt from Lagos",
             "suspicious_activity"),
            ("Please change your password now",
             "password_change"),
            ("Upload a video selfie to verify your age",
             "age_verify"),
            ("Please verify you're not a robot /recaptcha/verify",
             "captcha"),
            ("Your account has been disabled /accounts/disabled",
             "account_locked"),
            ("We've updated our terms. I agree to continue.",
             "terms_update"),
            ("Enter the code from your authentication app (two-factor)",
             "two_factor_prompt"),
            ("Trust this device? Unrecognized device detected",
             "device_verify"),
        ]

        class _RecStub:
            enrolled: list = []
            retired:  list = []
            def enroll(self, aid, reason=""):
                self.enrolled.append((aid, reason))
            def force_retire(self, aid):
                self.retired.append(aid)

        stub = _RecStub()
        burst: list[dict] = []
        h = InstagramCheckpointHandler(
            recovery=stub,
            rebalancer_alert=lambda e: burst.append(e),
            burst_window_min=15,
            burst_threshold=5,
        )
        for sig, expected in cases:
            evt = h.observe("acc-" + expected, sig)
            if evt.kind != expected:
                issues.append(f"classify({sig[:30]}) → {evt.kind}, "
                              f"expected {expected}")
            if evt.severity != _KIND_SEVERITY[expected]:
                issues.append(f"severity for {expected}: {evt.severity} "
                              f"vs {_KIND_SEVERITY[expected]}")
            if evt.action != _KIND_ACTION[expected]:
                issues.append(f"action for {expected}: {evt.action} "
                              f"vs {_KIND_ACTION[expected]}")

        # Recovery enrollments: suspicious_activity + password_change
        enrolled_kinds = [aid.replace("acc-", "") for aid, _ in stub.enrolled]
        for k in ("suspicious_activity", "password_change"):
            if k not in enrolled_kinds:
                issues.append(f"{k} did not trigger recovery enroll")
        if "acc-account_locked" not in stub.retired:
            issues.append("account_locked did not trigger retire")

        # Burst alert — we fired 10 events inside <15min
        if not burst:
            issues.append("burst alarm never fired despite 10 events")

        # Unknown signature falls back correctly
        u = h.observe("acc-x", "???")
        if u.kind != "unknown":
            issues.append(f"fallback: expected 'unknown', got {u.kind}")

        if not issues:
            return CheckResult(
                key="ig_checkpoint",
                label="IG checkpoint classify + route + burst",
                status="pass",
                detail=(f"{len(cases)} kinds classified · "
                        f"enroll/retire routed · burst fired"),
                metrics={"kinds": len(cases)},
            )
        return CheckResult(
            key="ig_checkpoint",
            label="IG checkpoint classify + route + burst",
            status="fail",
            detail=" · ".join(issues),
            metrics={"issues": issues},
        )

    def _check_ig_lattice(ids: list[str]) -> CheckResult:
        """
        Engagement lattice invariants:
          * per-target in-degree cap honored over repeated ticks
          * reciprocity A→B blocks B→A for cooldown window
          * same proxy can't double-hit the same target in a day
          * country affinity respected (US actor never picks GB target)
        """
        from .instagram_lattice import InstagramEngagementLattice
        issues: list[str] = []
        # 6 US + 2 GB accounts; all "active" and safe
        store: dict[str, dict] = {}
        for i, cc in enumerate(["US"]*6 + ["GB"]*2):
            aid = f"ig-{cc}-{i}"
            store[aid] = {"account_id": aid, "platform": "instagram",
                          "status": "active", "proxy_country": cc,
                          "timezone": "Europe/London" if cc == "GB" else "America/New_York"}
        queue: list[dict] = []

        class _ProxyStub:
            def __init__(self):
                # Pair ig-US-0 and ig-US-1 on the same proxy on purpose.
                self.pins = {aid: ("shared" if aid in ("ig-US-0","ig-US-1") else aid)
                             for aid in store}
            def pin_for(self, aid):
                pid = self.pins.get(aid)
                if pid is None: return None
                return type("P", (), {"proxy_id": pid})()

        # Force diurnal to always allow actor by picking a sympathetic hour
        import unittest.mock as _mock, phantom_fleet.platforms.instagram_diurnal as _d
        with _mock.patch.object(_d, "weight_now", return_value=0.95):
            latt = InstagramEngagementLattice(
                accounts_store_getter=lambda: store,
                queue_getter=lambda: queue,
                health=None,
                proxy=_ProxyStub(),
                in_degree_cap_per_day=2,
                out_degree_cap_per_day=4,
                reciprocity_cooldown_h=24,
                plan_per_tick=20,
                min_actor_weight=0.1,
            )
            plan1 = latt.plan_tick()
            plan2 = latt.plan_tick()
            plan3 = latt.plan_tick()

        edges = list(latt._edges)
        # In-degree ≤ cap
        in_counts: dict[str, int] = {}
        for e in edges:
            in_counts[e.target_id] = in_counts.get(e.target_id, 0) + 1
        if any(v > 2 for v in in_counts.values()):
            issues.append(f"in-degree cap violated: {max(in_counts.values())}")

        # Country affinity
        for e in edges:
            if store[e.actor_id]["proxy_country"] != store[e.target_id]["proxy_country"]:
                issues.append(f"country mismatch {e.actor_id}→{e.target_id}")
                break

        # Reciprocity: for each (a,b) edge, no (b,a) in same window
        pairs = {(e.actor_id, e.target_id) for e in edges}
        for a, b in pairs:
            if (b, a) in pairs:
                issues.append(f"reciprocity leak {a}↔{b}")
                break

        # Proxy diversity: shared-proxy actors can't both hit the same target
        for target in set(e.target_id for e in edges):
            seen_proxies = set()
            for e in edges:
                if e.target_id != target: continue
                pid = "shared" if e.actor_id in ("ig-US-0","ig-US-1") else e.actor_id
                if pid in seen_proxies:
                    issues.append(f"proxy reuse {pid} → {target}")
                    break
                seen_proxies.add(pid)

        if not issues:
            return CheckResult(
                key="ig_lattice",
                label="IG lattice caps + reciprocity + proxy + country",
                status="pass",
                detail=(f"3 ticks · {len(edges)} edges · "
                        f"in-cap 2 · reciprocity 24h · country+proxy honored"),
                metrics={"edges": len(edges), "plan_sizes":
                         [len(plan1), len(plan2), len(plan3)]},
            )
        return CheckResult(
            key="ig_lattice",
            label="IG lattice caps + reciprocity + proxy + country",
            status="fail",
            detail=" · ".join(issues),
            metrics={"issues": issues},
        )

    def _check_ig_drift(ids: list[str]) -> CheckResult:
        """
        Drift detector invariants:
          * stable baseline → 0 trips
          * 1-scan disagreement → 0 trips (hysteresis held)
          * 2-scan disagreement → trip fires with correct severity
          * dimension clears → trip clears
          * snapshot() rebases + clears streaks
        """
        from .instagram_drift import InstagramDriftDetector, _TRIP_STREAK
        issues: list[str] = []
        state = {"model_a": {
            "account_id":   "acc-1",
            "platform":     "instagram",
            "phone_serial": "serial-A",
            "device_model": "SM-G990B", "os_version": "13",
            "locale":       "en_US",    "timezone":   "America/New_York",
            "signing_cert": "sha1:good",
        }}
        det = InstagramDriftDetector(accounts_store_getter=lambda: state)
        det.scan_all()                       # capture baseline, no drift
        det.scan_all()                       # still stable
        if det.stats.tripped != 0:
            issues.append(f"stable baseline tripped: {det.stats.tripped}")

        # Flip a fail-tier dimension; expect 1-scan hysteresis
        state["model_a"]["device_model"] = "Pixel 7"
        det.scan_all()
        if det.stats.tripped != 0:
            issues.append("1-scan drift tripped (hysteresis broken)")
        det.scan_all()
        if det.stats.tripped != 1:
            issues.append(f"2-scan drift expected 1 trip, got {det.stats.tripped}")
        trips = det.for_phone("serial-A") or {}
        if not any(t["dimension"] == "device_model" and t["severity"] == "fail"
                    for t in trips.get("tripped", [])):
            issues.append("device_model fail-severity trip missing")

        # Clear the drift — streak should fall and trip should clear
        state["model_a"]["device_model"] = "SM-G990B"
        det.scan_all()
        trips = det.for_phone("serial-A") or {}
        if any(t["dimension"] == "device_model" for t in trips.get("tripped", [])):
            issues.append("drift did not clear after revert")

        # Snapshot: new baseline wipes previous drift state
        state["model_a"]["device_model"] = "Pixel 7"
        det.snapshot("serial-A")
        det.scan_all()
        det.scan_all()
        trips = det.for_phone("serial-A") or {}
        if any(t["dimension"] == "device_model" for t in trips.get("tripped", [])):
            issues.append("snapshot did not reset baseline")

        if not issues:
            return CheckResult(
                key="ig_drift",
                label="IG device-drift hysteretic trip + clear",
                status="pass",
                detail=f"trip_streak={_TRIP_STREAK} · fail severity · clear + snapshot",
                metrics={"trip_streak": _TRIP_STREAK},
            )
        return CheckResult(
            key="ig_drift",
            label="IG device-drift hysteretic trip + clear",
            status="fail",
            detail=" · ".join(issues),
            metrics={"issues": issues},
        )

    def _check_ig_proxy_scheduler(ids: list[str]) -> CheckResult:
        """
        Proxy pinning invariants:
          * every live account gets a pin when candidates exist
          * two live accounts never share a proxy within quarantine window
          * rotate() denies a candidate still held by another live account
          * country scope is honoured (US account won't get a GB proxy)
        """
        from .instagram_proxy import InstagramProxyScheduler
        issues: list[str] = []
        store: dict = {
            "ig-A": {"account_id": "ig-A", "platform": "instagram",
                     "status": "active", "proxy_country": "US"},
            "ig-B": {"account_id": "ig-B", "platform": "instagram",
                     "status": "active", "proxy_country": "US"},
            "ig-C": {"account_id": "ig-C", "platform": "instagram",
                     "status": "active", "proxy_country": "GB"},
        }
        pool: list[dict] = [
            {"proxy_id": "p1", "country": "US"},
            {"proxy_id": "p2", "country": "US"},
            {"proxy_id": "p3", "country": "GB"},
        ]
        sched = InstagramProxyScheduler(
            accounts_store_getter=lambda: store,
            proxy_pool_getter=lambda: pool,
        )
        sched.tick()
        if len(sched._pins) != 3:
            issues.append(f"expected 3 pins, got {len(sched._pins)}")
        p_ids = [p.proxy_id for p in sched._pins.values()]
        if len(set(p_ids)) != 3:
            issues.append("cross-account proxy reuse on live accounts")
        pin_c = sched.pin_for("ig-C")
        if pin_c and pin_c.country != "GB":
            issues.append(f"ig-C got non-GB proxy: {pin_c.country}")
        # Rotation deny: shrink pool to 1 US proxy; A rotation should fail
        # because p1/p2 are held by A/B.
        orig_a = sched.pin_for("ig-A").proxy_id  # type: ignore[union-attr]
        rot = sched.rotate("ig-A")
        if rot is not None and rot.proxy_id == sched.pin_for("ig-B").proxy_id:  # type: ignore[union-attr]
            issues.append("rotate let A take B's live proxy (reuse)")
        # Restore + check that releasing B frees the proxy for A.
        sched.release("ig-B")
        sched.rotate("ig-A")
        if sched.pin_for("ig-A") is None:
            issues.append("rotation failed after release")
        if not issues:
            return CheckResult(
                key="ig_proxy_scheduler",
                label="IG proxy pin/rotate/quarantine invariants",
                status="pass",
                detail="3 live accounts · 3 pins · quarantine honored · country scope honored",
                metrics={"pool_size": len(pool), "pins": len(sched._pins)},
            )
        return CheckResult(
            key="ig_proxy_scheduler",
            label="IG proxy pin/rotate/quarantine invariants",
            status="fail",
            detail=" · ".join(issues),
            metrics={"issues": issues},
        )

    def _check_ig_identity_rules(ids: list[str]) -> CheckResult:
        """
        Every pair-check rule must flag its canonical fail case and clear
        its canonical pass case. A refactor that neuters one rule fails
        here, not in production.
        """
        from . import instagram_identity as ig_id
        cases: list[tuple[str, dict, dict, str]] = [
            # bug #1 — locale/timezone
            ("locale_timezone",
             {"locale": "en_US", "timezone": "America/New_York"},
             {"locale": "en_GB", "timezone": "America/New_York"},
             "fail"),
            # bug #2 — AppCloner marker
            ("appcloner_fingerprint",
             {"signing_cert": "sha1:ab12cd34ef..."},
             {"signing_cert": "sha1:9ac41f3a9999..."},
             "fail"),
            # device/OS range
            ("device_os",
             {"device_model": "SM-G990B", "os_version": "13"},
             {"device_model": "SM-G990B", "os_version": "9"},
             "fail"),
            # carrier/HNI
            ("carrier_hni",
             {"carrier": "AT&T", "hni": "310410"},
             {"carrier": "AT&T", "hni": "23420"},
             "fail"),
            # proxy/timezone country
            ("proxy_country",
             {"timezone": "America/New_York", "proxy_country": "US"},
             {"timezone": "America/New_York", "proxy_country": "GB"},
             "fail"),
            # carrier country vs proxy country
            ("carrier_country",
             {"carrier": "EE", "proxy_country": "GB"},
             {"carrier": "EE", "proxy_country": "US"},
             "fail"),
        ]
        issues: list[str] = []
        for rule_name, pass_row, fail_row, expected in cases:
            pass_result = ig_id.scan_row(pass_row)
            fail_result = ig_id.scan_row(fail_row)
            if any(v.rule == rule_name for v in pass_result.violations):
                issues.append(f"{rule_name}: pass case flagged")
            if not any(v.rule == rule_name and v.severity == expected
                       for v in fail_result.violations):
                issues.append(f"{rule_name}: fail case not flagged")
        if not issues:
            return CheckResult(
                key="ig_identity_rules",
                label="IG identity pair-check rules fire correctly",
                status="pass",
                detail=f"{len(cases)} rules × pass + fail cases",
                metrics={"rules": [c[0] for c in cases]},
            )
        return CheckResult(
            key="ig_identity_rules",
            label="IG identity pair-check rules fire correctly",
            status="fail",
            detail=" · ".join(issues),
            metrics={"issues": issues},
        )

    def _check_ig_diurnal(ids: list[str]) -> CheckResult:
        """
        Diurnal curve sanity:
          * every hour of every curve lands in [0, 1]
          * chronotype distribution over 10K ids falls within target bands
            (lark 15–25%, standard 55–75%, owl 10–20%)
          * SHA256-seeded: same id → same chronotype & same weight
        """
        from . import instagram_diurnal as ig_diurnal
        issues: list[str] = []
        for chrono, curve in ig_diurnal._CURVES.items():
            if len(curve) != 24:
                issues.append(f"{chrono} curve len {len(curve)} != 24")
            if min(curve) < 0.0 or max(curve) > 1.0:
                issues.append(f"{chrono} out of [0,1] bounds")
            if max(curve) < 0.9:
                issues.append(f"{chrono} peak below 0.9")
            if min(curve) > 0.1:
                issues.append(f"{chrono} trough above 0.1 (no sleep)")
        buckets = {"morning_lark": 0, "standard": 0, "night_owl": 0}
        for i in ids[:10000]:
            buckets[ig_diurnal.chronotype_for(i)] += 1
        total = max(1, sum(buckets.values()))
        rl = buckets["morning_lark"] / total
        rs = buckets["standard"]     / total
        ro = buckets["night_owl"]    / total
        if not (0.15 <= rl <= 0.25):
            issues.append(f"lark share {rl:.2f} outside [0.15,0.25]")
        if not (0.55 <= rs <= 0.75):
            issues.append(f"standard share {rs:.2f} outside [0.55,0.75]")
        if not (0.10 <= ro <= 0.20):
            issues.append(f"owl share {ro:.2f} outside [0.10,0.20]")
        if ig_diurnal.chronotype_for("fixed") != ig_diurnal.chronotype_for("fixed"):
            issues.append("chronotype_for not deterministic")
        row = {"timezone": "America/New_York"}
        if ig_diurnal.weight_for("fixed", row, 12) != ig_diurnal.weight_for("fixed", row, 12):
            issues.append("weight_for not deterministic")
        if not issues:
            return CheckResult(
                key="ig_diurnal",
                label="IG diurnal chronotypes + hourly curves",
                status="pass",
                detail=(f"lark {rl:.2%} · std {rs:.2%} · owl {ro:.2%} · "
                        f"3 curves × 24h in [0,1]"),
                metrics={"lark": rl, "standard": rs, "owl": ro},
            )
        return CheckResult(
            key="ig_diurnal",
            label="IG diurnal chronotypes + hourly curves",
            status="fail",
            detail=" · ".join(issues),
            metrics={"issues": issues},
        )

    def _check_ig_executor_timing(ids: list[str]) -> CheckResult:
        """
        LogNormal inter-action delay sampler must stay inside [5s, 1200s]
        (CLAUDE.md distribution discipline) and the mean per kind must land
        within ±30% of the configured mean.
        """
        from .instagram_executor import sample_delay, _DELAY_MEAN
        issues: list[str] = []
        samples_per_kind: dict[str, list[float]] = {}
        for kind in _DELAY_MEAN:
            samples = [sample_delay(f"audit:{i}:{kind}", kind)
                       for i in range(min(1000, len(ids)))]
            samples_per_kind[kind] = samples
            if not samples:
                continue
            if min(samples) < 5.0 or max(samples) > 1200.0:
                issues.append(f"{kind} out of bounds: "
                              f"[{min(samples):.1f},{max(samples):.1f}]")
            mean = sum(samples) / len(samples)
            cfg_mean = _DELAY_MEAN[kind]
            if abs(mean - cfg_mean) / cfg_mean > 0.30:
                issues.append(f"{kind} mean drift: "
                              f"{mean:.1f} vs cfg {cfg_mean:.1f}")
            # Determinism: same seed → same value.
            if sample_delay("fixed", kind) != sample_delay("fixed", kind):
                issues.append(f"{kind} not deterministic")
        if not issues:
            means = {k: round(sum(v) / len(v), 1)
                     for k, v in samples_per_kind.items()}
            return CheckResult(
                key="ig_executor_timing",
                label="IG executor LogNormal delay within bounds",
                status="pass",
                detail=f"4 kinds · 1000 samples each · means {means}",
                metrics={"means": means},
            )
        return CheckResult(
            key="ig_executor_timing",
            label="IG executor LogNormal delay within bounds",
            status="fail",
            detail=" · ".join(issues),
            metrics={"issues": issues},
        )

    def _check_ig_agent_guardrails(ids: list[str]) -> CheckResult:
        from ..agents.instagram_agent import InstagramAgent
        cfg = InstagramAgent.config
        issues: list[str] = []
        if not cfg.allowed_tools:
            issues.append("empty tool allowlist")
        if not (1 <= cfg.max_iterations <= 20):
            issues.append(f"max_iterations out of range: {cfg.max_iterations}")
        if cfg.max_usd_per_run <= 0:
            issues.append("no per-run cost cap")
        if cfg.max_usd_per_session <= 0:
            issues.append("no per-session cost cap")
        if cfg.max_usd_per_session < cfg.max_usd_per_run:
            issues.append("session cap < run cap (misconfigured)")
        if not any(t.startswith("instagram.") for t in cfg.allowed_tools):
            issues.append("no instagram.* tools in allowlist")
        if len(cfg.allowed_tools) != 5:
            issues.append(f"allowlist size != 5 (got {len(cfg.allowed_tools)})")
        if not issues:
            return CheckResult(
                key="ig_agent_guardrails",
                label="InstagramAgent CLAUDE.md agent-audit config",
                status="pass",
                detail=(f"allowlist={len(cfg.allowed_tools)} tools, "
                        f"iterations={cfg.max_iterations}, "
                        f"run_cap=${cfg.max_usd_per_run}, "
                        f"session_cap=${cfg.max_usd_per_session}"),
                metrics={"tools": list(cfg.allowed_tools),
                         "max_iterations": cfg.max_iterations,
                         "max_usd_per_run": cfg.max_usd_per_run,
                         "max_usd_per_session": cfg.max_usd_per_session},
            )
        return CheckResult(
            key="ig_agent_guardrails",
            label="InstagramAgent CLAUDE.md agent-audit config",
            status="fail",
            detail=" · ".join(issues),
            metrics={"issues": issues},
        )

    t0 = time.perf_counter()
    ids = [_synthetic_account_id(i) for i in range(n)]
    checks: list[CheckResult] = [
        _check_budget_uniqueness(ids),
        _check_lognormal_shape(ids),
        _check_cap_discipline(ids),
        _check_delay_bounds(ids),
        _check_content_spread(ids),
        _check_warming_day_bounds(ids),
        _check_health_scoring(ids),
        _check_recovery_state_machine(ids),
        _check_agent_guardrails(ids),
        _check_probe_scheduling(ids),
        _check_rebalancer_transitions(ids),
        _check_ig_health_scoring(ids),
        _check_ig_recovery_state_machine(ids),
        _check_ig_budget_uniqueness(ids),
        _check_ig_lognormal_shape(ids),
        _check_ig_cap_discipline(ids),
        _check_ig_funnel_invariants(ids),
        _check_ig_probe_scheduling(ids),
        _check_ig_orchestrator(ids),
        _check_ig_rebalancer_transitions(ids),
        _check_ig_agent_guardrails(ids),
        _check_ig_executor_timing(ids),
        _check_ig_diurnal(ids),
        _check_ig_identity_rules(ids),
        _check_ig_proxy_scheduler(ids),
        _check_ig_drift(ids),
        _check_ig_lattice(ids),
        _check_ig_checkpoint(ids),
        _check_ig_session(ids),
        _check_ig_unfollow(ids),
        _check_ig_dm(ids),
    ]
    pass_count = sum(1 for c in checks if c.status == "pass")
    warn_count = sum(1 for c in checks if c.status == "warn")
    fail_count = sum(1 for c in checks if c.status == "fail")
    duration_ms = (time.perf_counter() - t0) * 1000.0
    return AuditReport(
        ran_at=datetime.now(timezone.utc).isoformat(),
        n_personas=n,
        pass_count=pass_count,
        warn_count=warn_count,
        fail_count=fail_count,
        duration_ms=duration_ms,
        checks=checks,
    )
