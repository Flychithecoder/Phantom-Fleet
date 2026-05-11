"""
Audit harness — 10,000-persona Monte Carlo cluster detection.

Runs in CI on every PR and hourly in production. Fails the build or pauses
the affected cohort when any fingerprint dimension clusters.
"""
from __future__ import annotations

from ..agents.audit_harness_agent import AuditHarnessAgent, HarnessResult

__all__ = ["AuditHarnessAgent", "HarnessResult"]
