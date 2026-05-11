"""
Phantom Fleet agent mesh.

Every manual operation Onimator users still do by hand becomes a dedicated
autonomous agent. The mesh is designed to run the fleet with zero human
intervention once provisioned.

Agents (14 total):
    1. AccountSetupAgent      — onboard new accounts from Onimator migration
    2. WarmingAgent           — run the daily re-wake + warming curves
    3. FreshTargetAgent       — produce fresh unique targets per account per day
    4. SourceDiscoveryAgent   — auto-discover female US high-engagement sources
    5. ContentAgent           — pull from Content Vault, generate captions, schedule
    6. DMAgent                — fan conversations, OF funnel conversion
    7. RecoveryAgent          — phone crash / logout / reauth auto-heal
    8. ReplacementAgent       — dead-account detection + replacement provisioning
    9. ProxyOrchestratorAgent — IPRoyal rotation + block-signal rotation
   10. FingerprintMonitorAgent — live cluster detection + cohort pause
   11. PersonaFactoryAgent    — generate new personas on demand
   12. GrowthStrategyAgent    — weekly KPI review + retargeting decisions
   13. FunnelConversionAgent  — fan → OF sub tracking per persona
   14. AuditHarnessAgent      — 10K-persona Monte Carlo cluster check (CI gate)

Every agent obeys the global CLAUDE.md agent-audit rules:
- Tool allowlist (agent can only call tools listed in its ALLOWED_TOOLS)
- Loop cap (agents run N steps max, then yield or stop)
- Cost cap (per-run + per-session + per-user LLM spend caps)
- Confirmation gates on destructive actions (never auto-execute deletes)
- Event-sourced audit log (every action logged before execution)
- Per-agent cost attribution (every LLM call tagged)
- Idempotency (repeated runs don't double-fire actions)
"""
from .base import Agent, AgentConfig, AgentRun
