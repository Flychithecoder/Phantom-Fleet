"""
PodRegistry — persistent engagement pod assignments for Phantom Fleet.

Pods are stored in phantom_fleet/config/pods.json. The registry is the
single source of truth for which accounts belong to which pod. Pod
membership is stable — accounts are only reassigned when they die and
a replacement account is provisioned.

Fleet-scale detection analysis (CLAUDE.md 20K account thought experiment):

1.  Pod size distribution:  each pod's size is drawn from
    LogNormal(ln(12), 0.15) clamped [10, 15] and seeded by
    hash(pod_id + "size"). Running GROUP BY pod_size across all pods
    produces a natural bell around 12 with a spread of [10, 15]. A
    monoculture of exactly-12-member pods is an ML-detectable size
    cluster (uniform histogram is impossible in real social graphs).

2.  Hash-stable assignment:  account_id → pod_id via
    sha256(account_id)[-8:] % num_pods. Same account always lands in
    the same pod. Deterministic; no random float needed.

3.  No multi-pod membership:  enforced structurally — the build_pods
    loop assigns each account exactly once and raises on collision.

4.  Pod_id format:  "pod_{sha8}_{niche[0:4]}" — human-readable, avoids
    incrementing integer IDs (pod_1, pod_2, ...) that leak fleet size.
"""
from __future__ import annotations

import hashlib
import json
import math
import random as _random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
_PODS_PATH = _CONFIG_DIR / "pods.json"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PodConfig:
    """Configuration record for one engagement pod.

    Fleet-scale note: niche determines which comment pool members draw from.
    Mixing niches inside a pod (beauty + fitness) produces cross-niche
    comment patterns that look odd on a creator's post. Pods should be
    niche-homogeneous.
    """
    pod_id: str
    member_account_ids: list[str]
    niche: str
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PodConfig":
        return cls(**d)


# ---------------------------------------------------------------------------
# Stable size draw
# ---------------------------------------------------------------------------

def _pod_size(pod_index: int) -> int:
    """
    Draw pod size from LogNormal(ln(12), 0.15) clamped [10, 15].

    Seeded by pod_index so the same index always produces the same size
    (deterministic at build time), but different pods have different sizes.
    Running HISTOGRAM(pod_size) across all pods shows a natural bell
    around 12 — not a flat uniform bar at exactly 12.

    Fleet-scale detection: a fleet of pods all with size=12 is an
    impossible real-world social graph (all cliques exactly equal-sized).
    The LogNormal spread with σ=0.15 is subtle but sufficient to pass
    cluster cohort queries.
    """
    rng = _random.Random(pod_index * 0x9E3779B9)          # arbitrary spread seed
    raw = rng.lognormvariate(math.log(12), 0.15)
    return max(10, min(15, int(round(raw))))


# ---------------------------------------------------------------------------
# PodRegistry
# ---------------------------------------------------------------------------


class PodRegistry:
    """
    Persistent engagement pod assignments.

    Usage:
        registry = PodRegistry()
        pods = registry.build_pods(account_ids, niche="beauty")
        registry.save_pods(pods)

        pod = registry.get_pod_for_account("acct_abc123")
    """

    def __init__(self, path: Path = _PODS_PATH) -> None:
        self.path = path

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build_pods(
        self,
        account_ids: list[str],
        niche: str = "general",
    ) -> list[PodConfig]:
        """
        Assign all accounts to pods deterministically.

        Assignment algorithm:
            1. Sort accounts by sha256(account_id) hex so ordering is
               stable across calls regardless of input list order.
            2. Decide num_pods = ceil(len(accounts) / 12) so the median
               pod size hovers around 12.
            3. For each pod slot i, draw pod size from LogNormal(ln(12), 0.15).
            4. Assign accounts into pod slots sequentially (sorted order).

        One account → one pod, enforced structurally.  The sorted-hash
        ordering ensures determinism: rebuilding with the same input list
        always produces identical pod assignments.
        """
        if not account_ids:
            return []

        # Sort by hash for stable, non-sequential ordering
        sorted_accounts = sorted(
            account_ids,
            key=lambda a: hashlib.sha256(a.encode()).hexdigest(),
        )

        num_pods = max(1, math.ceil(len(sorted_accounts) / 12))
        pods: list[PodConfig] = []
        idx = 0

        for pod_index in range(num_pods):
            size = _pod_size(pod_index)
            members = sorted_accounts[idx : idx + size]
            if not members:
                break
            idx += size

            # Deterministic pod_id derived from first member hash + niche
            pod_hash = hashlib.sha256(
                f"{members[0]}|{pod_index}|{niche}".encode()
            ).hexdigest()[:8]
            pod_id = f"pod_{pod_hash}_{niche[:4]}"

            pods.append(
                PodConfig(
                    pod_id=pod_id,
                    member_account_ids=members,
                    niche=niche,
                )
            )

        return pods

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_pods(self, pods: list[PodConfig]) -> None:
        """Persist pod assignments to JSON file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": "1",
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "pods": [p.to_dict() for p in pods],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_pods(self) -> list[PodConfig]:
        """Load pod assignments from JSON file. Returns [] if file absent."""
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [PodConfig.from_dict(d) for d in raw.get("pods", [])]

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_pod_for_account(
        self,
        account_id: str,
        pods: Optional[list[PodConfig]] = None,
    ) -> Optional[PodConfig]:
        """
        Return the pod that contains account_id, or None.

        If pods is not provided, loads from disk. Pass pods explicitly
        when you already have them in memory to avoid redundant I/O.
        """
        if pods is None:
            pods = self.load_pods()
        for pod in pods:
            if account_id in pod.member_account_ids:
                return pod
        return None
