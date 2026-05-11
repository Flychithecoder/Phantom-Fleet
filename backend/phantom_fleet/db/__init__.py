"""
Database layer — Postgres schema + async connection pool.

Quick-start:
    from phantom_fleet.db import get_conn, run_migrations
    from phantom_fleet.db import PhoneRepository, AccountRepository

    await run_migrations()

    async with get_conn() as conn:
        repo = PhoneRepository(conn)
        phones = await repo.get_ready_phones()
"""

from phantom_fleet.db.connection import (
    get_pool,
    get_conn,
    close_pool,
    run_migrations,
    ping_db,
)

from phantom_fleet.db.repositories import (
    PhoneRepository,
    AccountRepository,
    ActionLogRepository,
    DailyPlanRepository,
    AgentRunRepository,
    AlertRepository,
)

__all__ = [
    # Connection
    "get_pool",
    "get_conn",
    "close_pool",
    "run_migrations",
    "ping_db",
    # Repositories
    "PhoneRepository",
    "AccountRepository",
    "ActionLogRepository",
    "DailyPlanRepository",
    "AgentRunRepository",
    "AlertRepository",
]
