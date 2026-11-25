"""Per-role model backend router.

Decides which vendor (anthropic | zai) and which model id to use for a
given fleet role. Reads env at import; caller may override per-call.

This module is scaffolding — the actual z.ai client call path is not
wired yet. The resolver returns a typed spec that callers interpret:
the runner reads `cli_bin` + env to spawn the right CLI subprocess;
the Python backend reads `base_url` + `api_key_env` to open an
OpenAI-compatible HTTP client.

Model aliases are env-driven so swapping model ids (as z.ai ships
new GLM revisions) needs no code change — just update .env.

Budget caps are advisory here; the hard gate lives in the Treg transport
and Staffroom engine. The router only refuses to resolve a role when the
env config for that role is incomplete.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

Vendor = Literal["anthropic", "zai"]
Role = Literal["coo", "worker", "fast"]


@dataclass(frozen=True)
class ModelSpec:
    vendor: Vendor
    model: str
    base_url: str | None
    api_key_env: str | None
    cli_bin: str | None
    cli_auth_mode: Literal["api_key", "plan"] | None
    max_tokens: int
    daily_cap_usd: float


_ROLE_ENV = {
    "coo": "PF_ROUTER_ROLE_COO",
    "worker": "PF_ROUTER_ROLE_WORKER",
    "fast": "PF_ROUTER_ROLE_FAST",
}

_ANTHROPIC_DEFAULTS = {
    "coo": "claude-opus-4-7",
    "worker": "claude-sonnet-4-6",
    "fast": "claude-haiku-5-5",
}

_ZAI_ENV_FOR_ROLE = {
    "coo": "PF_ZAI_MODEL_PLAN",
    "worker": "PF_ZAI_MODEL_WORK",
    "fast": "PF_ZAI_MODEL_FAST",
}


class RouterError(RuntimeError):
    pass


class SensitivityError(RouterError):
    """Raised when a sensitive role is routed to a non-US-jurisdictional vendor."""


# Roles whose briefs may contain owner PII, fleet credentials, device DB
# contents, or Treg routing data. These MUST NOT leave US jurisdiction, so
# resolve() refuses to route them to z.ai regardless of env configuration.
# Overridable via PF_ROUTER_ALLOW_ZAI_SENSITIVE=1 for explicit owner opt-in.
_SENSITIVE_ROLES: set[str] = {"coo"}


def _zai_spec(role: Role) -> ModelSpec:
    model = os.environ.get(_ZAI_ENV_FOR_ROLE[role], "").strip()
    if not model:
        raise RouterError(
            f"Role '{role}' routed to z.ai but {_ZAI_ENV_FOR_ROLE[role]} is unset."
        )
    api_key = os.environ.get("PF_ZAI_API_KEY", "").strip()
    if not api_key:
        raise RouterError("PF_ZAI_API_KEY is unset; cannot route to z.ai.")
    return ModelSpec(
        vendor="zai",
        model=model,
        base_url=os.environ.get(
            "PF_ZAI_BASE_URL", "https://api.z.ai/api/paas/v4/"
        ).rstrip("/") + "/",
        api_key_env="PF_ZAI_API_KEY",
        cli_bin=os.environ.get("PF_ZAI_CLI_BIN") or None,
        cli_auth_mode=(os.environ.get("PF_ZAI_CLI_AUTH_MODE", "api_key") or "api_key"),  # type: ignore[arg-type]
        max_tokens=int(os.environ.get("PF_ZAI_MAX_TOKENS_PER_CALL", "16000")),
        daily_cap_usd=float(os.environ.get("PF_ZAI_DAILY_CAP_USD", "10.0")),
    )


def _anthropic_spec(role: Role) -> ModelSpec:
    return ModelSpec(
        vendor="anthropic",
        model=_ANTHROPIC_DEFAULTS[role],
        base_url=None,
        api_key_env="ANTHROPIC_API_KEY",
        cli_bin=os.environ.get("PF_CLAUDE_BIN", "claude"),
        cli_auth_mode="plan",
        max_tokens=int(os.environ.get("PF_CLAUDE_MAX_TOKENS", "16000")),
        daily_cap_usd=float(os.environ.get("PHANTOM_DAILY_LLM_CAP_USD", "25.0")),
    )


def resolve(role: Role, override: Vendor | None = None) -> ModelSpec:
    """Return the model spec for a role.

    `override` forces a vendor (used by tests and manual retry paths).
    Otherwise reads PF_ROUTER_ROLE_<ROLE>. "auto" currently falls through
    to anthropic; a future revision will read Causal Fleet Memory outcome
    scores and pick the higher-quality / cheaper vendor per role.
    """
    if role not in _ROLE_ENV:
        raise RouterError(f"Unknown role: {role}")
    choice = (override or os.environ.get(_ROLE_ENV[role], "anthropic")).strip().lower()
    if choice == "zai":
        if role in _SENSITIVE_ROLES and os.environ.get(
            "PF_ROUTER_ALLOW_ZAI_SENSITIVE", ""
        ).strip() not in ("1", "true", "yes"):
            raise SensitivityError(
                f"Role '{role}' carries sensitive context; z.ai routing refused. "
                "Set PF_ROUTER_ALLOW_ZAI_SENSITIVE=1 only after owner review of "
                "data-residency implications (z.ai servers are PRC-hosted)."
            )
        return _zai_spec(role)
    if choice in ("anthropic", "auto", ""):
        return _anthropic_spec(role)
    raise RouterError(f"Unknown vendor '{choice}' for role '{role}'.")


def describe() -> dict:
    """Snapshot for /api/router/health — never returns secret values."""
    out: dict = {"roles": {}}
    for role in ("coo", "worker", "fast"):
        try:
            spec = resolve(role)  # type: ignore[arg-type]
            out["roles"][role] = {
                "vendor": spec.vendor,
                "model": spec.model,
                "base_url": spec.base_url,
                "cli_bin": spec.cli_bin,
                "cli_auth_mode": spec.cli_auth_mode,
                "max_tokens": spec.max_tokens,
                "daily_cap_usd": spec.daily_cap_usd,
                "api_key_present": bool(
                    os.environ.get(spec.api_key_env or "", "")
                ),
            }
        except RouterError as err:
            out["roles"][role] = {"error": str(err)}
    return out
