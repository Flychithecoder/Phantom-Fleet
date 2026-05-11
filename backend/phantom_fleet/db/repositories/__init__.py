"""
Phantom Fleet database repositories.

Each repository owns one table (or a tightly related set) and exposes
an async interface that takes an asyncpg connection or pool as its first
constructor argument.  All methods return plain dicts, never ORM objects.
All queries are parameterised — no string interpolation.

Available repositories:
    PhoneRepository     — phones table
    AccountRepository   — accounts table
    ActionLogRepository — action_log table
    DailyPlanRepository — daily_plans table
    AgentRunRepository  — agent_runs table
    AlertRepository     — alerts table
"""

from .phones import PhoneRepository
from .accounts import AccountRepository
from .action_log import ActionLogRepository
from .daily_plans import DailyPlanRepository
from .agent_runs import AgentRunRepository
from .alerts import AlertRepository

__all__ = [
    "PhoneRepository",
    "AccountRepository",
    "ActionLogRepository",
    "DailyPlanRepository",
    "AgentRunRepository",
    "AlertRepository",
]
