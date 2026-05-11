"""
RecoveryAgent — phone/session auto-heal.

Detects phone crashes, IG logouts, frozen clones, checkpoint challenges, or
session expiry and automatically re-auths, reboots, or escalates. Zero
manual intervention required.
"""
from __future__ import annotations

import logging
from .base import Agent, AgentConfig, AgentRun

log = logging.getLogger(__name__)


class RecoveryAgent(Agent):
    config = AgentConfig(
        name="recovery",
        max_iterations=10,
        max_usd_per_run=0.00,
        confirmation_required_for=("wipe_account_data",),
        allowed_tools=(
            "phone.ping",
            "phone.reboot",
            "phone.force_stop_clone",
            "phone.launch_clone",
            "phone.check_session",
            "phone.reauth",
            "db.mark_account_paused",
            "db.mark_account_dead",
            "db.raise_alert",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        phone_serial = ctx["phone_serial"]
        account_id = ctx["account_id"]
        symptom = ctx.get("symptom", "unknown")

        if symptom == "phone_unreachable":
            alive = await self.tool("phone.ping", phone_serial)
            if not alive:
                await self.tool("phone.reboot", phone_serial)
                return True

        if symptom == "clone_crashed":
            await self.tool("phone.force_stop_clone", phone_serial, account_id)
            await self.tool("phone.launch_clone", phone_serial, account_id)
            return True

        if symptom == "session_expired":
            ok = await self.tool("phone.reauth", phone_serial, account_id)
            if not ok:
                await self.tool("db.mark_account_paused", account_id)
            return True

        if symptom in ("checkpoint_challenge", "suspended", "login_block"):
            await self.tool("db.mark_account_dead", account_id, reason=symptom)
            await self.tool("db.raise_alert", {"type": symptom, "account": account_id})
            return True

        run.audit_events.append({"phone": phone_serial, "symptom": symptom})
        return True
