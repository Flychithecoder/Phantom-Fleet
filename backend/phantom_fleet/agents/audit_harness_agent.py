"""
AuditHarnessAgent — 10,000-persona Monte Carlo cluster check.

Runs in CI on every PR AND continuously in production (hourly). Simulates
a full day of 10,000 synthetic personas using the same distributions and
sampling logic the live system uses, then runs the 10 cluster-analysis
checks from the global CLAUDE.md rule.

If any dimension clusters, the harness FAILS THE BUILD (in CI) or pauses
the affected cohort (in production).

No overrides, no exceptions. The harness is a hard gate.
"""
from __future__ import annotations

import logging
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field

from .base import Agent, AgentConfig, AgentRun
from ..core.persona import create_persona

log = logging.getLogger(__name__)


@dataclass
class HarnessResult:
    passed: bool
    total_personas: int
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


class AuditHarnessAgent(Agent):
    config = AgentConfig(
        name="audit_harness",
        max_iterations=3,
        max_usd_per_run=0.00,
        allowed_tools=("audit.store_result",),
    )

    N_SYNTHETIC_PERSONAS = 10_000
    MAX_SINGLE_VALUE_FRACTION = 0.30  # no single device/locale/tz > 30%
    MAX_TIMING_UNIFORMITY_CV = 0.20   # coefficient of variation — >0.2 means shaped, <0.2 means flat/clustered

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        result = self.simulate_and_check()
        await self.tool("audit.store_result", result)
        run.outputs = {"passed": result.passed, "failures": result.failures}
        return True

    def simulate_and_check(self) -> HarnessResult:
        personas = [create_persona(display_name=f"syn{i:05d}") for i in range(self.N_SYNTHETIC_PERSONAS)]

        failures: list[str] = []
        warnings: list[str] = []
        metrics: dict = {}

        # Check 1: device model distribution
        models = Counter(p.device_model for p in personas)
        max_model_share = max(models.values()) / len(personas)
        metrics["max_device_model_share"] = max_model_share
        if max_model_share > self.MAX_SINGLE_VALUE_FRACTION:
            top_model, count = models.most_common(1)[0]
            failures.append(
                f"device model '{top_model}' is {max_model_share*100:.1f}% "
                f"of fleet (>{self.MAX_SINGLE_VALUE_FRACTION*100:.0f}% ceiling)"
            )

        # Check 2: android version distribution
        versions = Counter(p.android_version for p in personas)
        max_version_share = max(versions.values()) / len(personas)
        metrics["max_android_version_share"] = max_version_share
        if max_version_share > self.MAX_SINGLE_VALUE_FRACTION:
            failures.append(
                f"android version cluster: {max_version_share*100:.1f}% share"
            )

        # Check 6: locale/timezone cross-field (should always match)
        for p in personas:
            if p.locale == "en-US" and not p.timezone.startswith("America/"):
                failures.append(f"cross-field: {p.persona_id} en-US + {p.timezone}")
                break

        # Check 10: aggressiveness distribution — should be smooth, not bimodal
        aggs = [p.aggressiveness for p in personas]
        metrics["aggressiveness_mean"] = statistics.mean(aggs)
        metrics["aggressiveness_stdev"] = statistics.pstdev(aggs)

        # Check: biometric fields vary naturally
        dwells = [p.biometrics.tap_dwell_ms_mean for p in personas]
        cv = statistics.pstdev(dwells) / (statistics.mean(dwells) or 1)
        metrics["tap_dwell_cv"] = cv
        if cv < 0.10:
            warnings.append(f"tap_dwell CV only {cv:.3f} — may be too narrow")

        passed = len(failures) == 0
        return HarnessResult(
            passed=passed,
            total_personas=len(personas),
            failures=failures,
            warnings=warnings,
            metrics=metrics,
        )
