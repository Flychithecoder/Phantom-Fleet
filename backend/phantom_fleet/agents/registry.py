"""
Agent registry — the canonical list of every Phantom Fleet agent.

Import from here to get a single source of truth for agent classes and their
configs. Used by the FastAPI agent endpoint and the scheduler.
"""
from __future__ import annotations

from .account_setup_agent import AccountSetupAgent
from .audit_harness_agent import AuditHarnessAgent
from .content_agent import ContentAgent
from .content_scout_agent import ContentScoutAgent
from .dm_agent import DMAgent
from .fingerprint_monitor_agent import FingerprintMonitorAgent
from .fresh_target_agent import FreshTargetAgent
from .funnel_conversion_agent import FunnelConversionAgent
from .growth_strategy_agent import GrowthStrategyAgent
from .persona_factory_agent import PersonaFactoryAgent
from .proxy_orchestrator_agent import ProxyOrchestratorAgent
from .recovery_agent import RecoveryAgent
from .replacement_agent import ReplacementAgent
from .source_discovery_agent import SourceDiscoveryAgent
from .warming_agent import WarmingAgent


AGENT_CLASSES = {
    "account_setup": AccountSetupAgent,
    "audit_harness": AuditHarnessAgent,
    "content": ContentAgent,
    "content_scout": ContentScoutAgent,
    "dm": DMAgent,
    "fingerprint_monitor": FingerprintMonitorAgent,
    "fresh_target": FreshTargetAgent,
    "funnel_conversion": FunnelConversionAgent,
    "growth_strategy": GrowthStrategyAgent,
    "persona_factory": PersonaFactoryAgent,
    "proxy_orchestrator": ProxyOrchestratorAgent,
    "recovery": RecoveryAgent,
    "replacement": ReplacementAgent,
    "source_discovery": SourceDiscoveryAgent,
    "warming": WarmingAgent,
}


__all__ = [
    "AGENT_CLASSES",
    "AccountSetupAgent", "AuditHarnessAgent", "ContentAgent",
    "ContentScoutAgent", "DMAgent", "FingerprintMonitorAgent",
    "FreshTargetAgent", "FunnelConversionAgent", "GrowthStrategyAgent",
    "PersonaFactoryAgent", "ProxyOrchestratorAgent", "RecoveryAgent",
    "ReplacementAgent", "SourceDiscoveryAgent", "WarmingAgent",
]
