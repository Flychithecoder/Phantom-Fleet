"""
ProxyOrchestratorAgent — manages IPRoyal Royal Residential rotation.

Responsibilities:
    - Pin each account to a home region (NY, NJ, MA, etc.) matching persona
    - Serve session proxies with sticky holds (10-15 min per warming session)
    - Force-rotate on block signals from any account
    - Track per-account IP history — avoid reuse within 24h
    - Never let two accounts use the same IP simultaneously
    - Health-score IPs from the pool, avoid dirty ones
"""
from __future__ import annotations

from collections import deque
from .base import Agent, AgentConfig, AgentRun


class ProxyOrchestratorAgent(Agent):
    config = AgentConfig(
        name="proxy_orchestrator",
        max_iterations=25,
        max_usd_per_run=0.00,
        allowed_tools=(
            "db.load_account_region",
            "db.load_ip_history",
            "db.save_ip_assignment",
            "proxy.get_session_ip",
            "proxy.force_rotate",
            "proxy.check_ip_reputation",
        ),
    )

    SESSION_TTL_SECONDS = 900  # 15-minute sticky hold
    HISTORY_MAXLEN = 20
    COOLDOWN_HOURS = 24

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id = ctx["account_id"]
        action = ctx.get("action", "get_session")

        if action == "get_session":
            region = await self.tool("db.load_account_region", account_id)
            recent = await self.tool("db.load_ip_history", account_id, hours=self.COOLDOWN_HOURS)
            ip = await self.tool(
                "proxy.get_session_ip",
                country="US",
                state=region["state"],
                city=region["city"],
                session_ttl=self.SESSION_TTL_SECONDS,
                exclude=[r["ip"] for r in recent],
            )
            rep = await self.tool("proxy.check_ip_reputation", ip)
            if rep.get("fraud_score", 0) > 75 or rep.get("is_datacenter", False):
                await self.tool("proxy.force_rotate")
                ip = await self.tool(
                    "proxy.get_session_ip",
                    country="US",
                    state=region["state"],
                    city=region["city"],
                    session_ttl=self.SESSION_TTL_SECONDS,
                    exclude=[r["ip"] for r in recent] + [ip],
                )
            await self.tool("db.save_ip_assignment", account_id, ip)
            run.outputs = {"ip": ip}
            return True

        if action == "on_block_signal":
            await self.tool("proxy.force_rotate")
            return True

        return True
