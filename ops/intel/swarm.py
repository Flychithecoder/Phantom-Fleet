"""#4 Swarm primitive — choreographed cross-account physics.

Three capabilities no LLM-driven farm can do:

  * **trending_view(story_url, k, window_s)**
      k accounts jittered within `window_s` seconds (persona-local)
      simultaneously view a story, triggering IG "popular with your
      network" cues. Each account's firing time is drawn from a
      Normal around the window center + the account's own peak-hour
      offset, so it's simultaneous *in persona time* and spread in
      wall time.

  * **community_graph(n, k_follow_median)**
      Generate a Barabási-Albert preferential-attachment follow graph
      so a fresh cohort doesn't look like n strangers who all
      discovered you on Day 1. Returns edges to enqueue over N days.

  * **synchrony_offsets(cohort, kind, when)**
      Given a cohort and a wall-clock target, return each account's
      (due_ms, tap_offset_ms) pair such that they LOOK identical in
      persona-local time but are jittered in wall time with per-account
      entropy so no two taps share the same ms offset. This defeats
      the "same-ms across cohort" detection vector directly.

Deterministic. No LLM calls. Entropy via secrets.randbits(53).
"""
from __future__ import annotations

import math
import secrets
from dataclasses import dataclass


def _u01() -> float:
    return secrets.randbits(53) / (1 << 53)


def _gauss(mu: float, sigma: float) -> float:
    u1 = max(_u01(), 1e-12)
    u2 = _u01()
    return mu + sigma * math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


@dataclass
class ViewSlot:
    account: str
    due_ms: int
    jitter_ms: int           # pre-tap dwell to break ms-exact clustering


def trending_view(
    story_subject: str, accounts: list[dict], window_s: int = 90,
    center_ms: int | None = None,
) -> list[ViewSlot]:
    """Each account's firing time drawn from Normal(center, window/4),
    clipped to [center - window/2, center + window/2].

    center_ms defaults to "now + 10 min" so the orchestrator has buffer
    to enqueue before the window opens.
    """
    import time as _t
    center = center_ms if center_ms is not None else int(_t.time() * 1000) + 600_000
    half = window_s * 500  # half-window in ms
    slots: list[ViewSlot] = []
    for a in accounts:
        for _ in range(16):
            off = _gauss(0, window_s * 250)  # sigma = quarter window in ms
            if -half <= off <= half:
                break
        due = center + int(off)
        # Per-account jitter baked into the tap offset itself so cohort
        # tap times never share an ms in wall-clock.
        jitter = int(_u01() * 97) + int(secrets.randbits(16)) % 83
        slots.append(ViewSlot(
            account=str(a.get("account") or a.get("username")),
            due_ms=due, jitter_ms=jitter,
        ))
    return slots


# -------- Barabási-Albert preferential attachment graph --------

def community_graph(
    n_accounts: int, m: int = 3, seed_accounts: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Returns a list of (follower, followee) edges. BA guarantees the
    degree distribution follows a power law — the exact shape real
    Instagram communities do, and the shape a uniform-follow cohort
    fatally lacks.

    `m` = how many existing accounts each new one follows. Set 3 for a
    warming cohort; 8+ for an aged pool.
    """
    if n_accounts < max(2, m):
        return []
    labels = seed_accounts or [f"acct_{i:04d}" for i in range(n_accounts)]
    labels = labels[:n_accounts]
    # Degree counter over labels.
    degree: dict[str, int] = {lbl: 0 for lbl in labels}
    edges: list[tuple[str, str]] = []
    # Start with a connected m-clique (so preferential attachment has
    # mass to pick from).
    for i in range(m):
        for j in range(i + 1, m):
            edges.append((labels[i], labels[j]))
            degree[labels[i]] += 1
            degree[labels[j]] += 1
    # Add remaining nodes.
    for k in range(m, n_accounts):
        # Draw m distinct targets weighted by current degree.
        total = sum(degree.values())
        picked: set[str] = set()
        attempts = 0
        while len(picked) < m and attempts < 50 * m:
            attempts += 1
            r = _u01() * total
            acc = 0.0
            for lbl, d in degree.items():
                acc += d
                if acc >= r and lbl not in picked and lbl != labels[k]:
                    picked.add(lbl)
                    break
        for tgt in picked:
            edges.append((labels[k], tgt))
            degree[labels[k]] += 1
            degree[tgt] += 1
    return edges


# -------- Synchrony offsets (break the "same-ms" detector) --------

@dataclass
class SyncSlot:
    account: str
    due_ms: int
    tap_offset_ms: int


def synchrony_offsets(
    accounts: list[dict], kind: str, persona_local_ms: int,
    max_wall_jitter_s: int = 180,
) -> list[SyncSlot]:
    """`persona_local_ms` is the timestamp we want each account to
    fire at *in its own local reference*. Each account is shifted into
    wall time by the offset implied by its `tz_offset_hours`, then
    jittered up to `max_wall_jitter_s` so wall-clock clusters never
    form.
    """
    out: list[SyncSlot] = []
    seen_tap_offsets: set[int] = set()
    for a in accounts:
        tz_off = int(a.get("tz_offset_hours", -5)) * 3600_000
        wall_target = persona_local_ms - tz_off
        jitter = int(_gauss(0, max_wall_jitter_s * 500))
        due = wall_target + jitter
        # Guarantee unique tap-offset ms across the cohort.
        for _ in range(32):
            tap = secrets.randbits(8)  # 0..255 ms
            if tap not in seen_tap_offsets:
                seen_tap_offsets.add(tap)
                break
        else:
            tap = secrets.randbits(10) % 256
        out.append(SyncSlot(
            account=str(a.get("account") or a.get("username")),
            due_ms=due, tap_offset_ms=tap,
        ))
    return out


def summary(edges: list[tuple[str, str]] | list[ViewSlot] | list[SyncSlot]) -> dict:
    if not edges:
        return {"n": 0}
    if isinstance(edges[0], tuple):
        deg_out: dict[str, int] = {}
        deg_in: dict[str, int] = {}
        for u, v in edges:
            deg_out[u] = deg_out.get(u, 0) + 1
            deg_in[v] = deg_in.get(v, 0) + 1
        in_vals = sorted(deg_in.values(), reverse=True)
        return {
            "edges": len(edges),
            "nodes": len(set(list(deg_in) + list(deg_out))),
            "top_in_degree": in_vals[:5],
            "min_in_degree": min(in_vals) if in_vals else 0,
            "max_in_degree": max(in_vals) if in_vals else 0,
        }
    if isinstance(edges[0], ViewSlot):
        times = [e.due_ms for e in edges]
        return {
            "n": len(edges),
            "span_ms": max(times) - min(times),
            "unique_jitter": len({e.jitter_ms for e in edges}),
        }
    # SyncSlot
    taps = [e.tap_offset_ms for e in edges]
    return {
        "n": len(edges),
        "unique_tap_offsets": len(set(taps)),
        "tap_offset_min": min(taps), "tap_offset_max": max(taps),
    }
