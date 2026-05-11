"""
AccountSetupAgent — onboards new accounts into Phantom Fleet.

Used for:
    1. Migrating the existing 219 Tatiana/Melodie accounts from Onimator
       into Phantom Fleet's persona schema
    2. Provisioning replacement accounts when ReplacementAgent fires
    3. Importing newly-purchased aged accounts from BHW/BTZ/Onimator markets

For each account:
    - Parse credentials (username, password, email, 2FA)
    - Assign persona
    - Sample per-account personality (aggressiveness + biometrics lock-in)
    - Pick home region (US state/city) matching persona geography
    - Assign phone slot
    - Write to DB
    - If dormant (6+ months inactive), flag for re-wake curve
    - If fresh, flag for Day 0 warmup curve
"""
from __future__ import annotations

import secrets

from .base import Agent, AgentConfig, AgentRun
from ..core.distributions import _secure_rng as secure_rng


class AccountSetupAgent(Agent):
    config = AgentConfig(
        name="account_setup",
        max_iterations=50,
        max_usd_per_run=0.00,
        confirmation_required_for=("wipe_account_data",),
        allowed_tools=(
            "db.load_persona",
            "db.save_account",
            "db.load_available_phone_slot",
            "db.assign_account_to_phone",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        imports = ctx["imports"]  # list of dicts: {username, password, email, ...}
        persona_id = ctx["persona_id"]
        dormant = ctx.get("dormant", False)

        persona = await self.tool("db.load_persona", persona_id)
        rng = secure_rng()

        for entry in imports:
            account = {
                "id": secrets.token_hex(8),
                "persona_id": persona_id,
                "username": entry["username"],
                "status": "imported",
                "day_in_curve": 0 if not dormant else 0,
                "curve_type": "re_wake" if dormant else "fresh_warmup",
                "aggressiveness": rng.uniform(0.85, 1.15),
                "weekly_multiplier": 1.0,
                "home_state": persona.state,
                "home_city": persona.city,
                "locale": persona.locale,
                "timezone": persona.timezone,
                "credentials": {
                    "username": entry["username"],
                    "password_ref": entry.get("password_ref"),
                    "email": entry.get("email"),
                    "email_password_ref": entry.get("email_password_ref"),
                    "twofa_secret_ref": entry.get("twofa_secret_ref"),
                },
            }
            slot = await self.tool("db.load_available_phone_slot", persona_id)
            if slot is None:
                run.audit_events.append({"no_slot_for": entry["username"]})
                continue
            account["phone_serial"] = slot["phone_serial"]
            await self.tool("db.save_account", account)
            await self.tool("db.assign_account_to_phone", account["id"], slot["phone_serial"])
            run.audit_events.append({"imported": entry["username"], "phone": slot["phone_serial"]})

        return True
