"""
Hierarchical agent mesh — platform agent managers.

The top-level selling point of Phantom Fleet: you don't manage automations,
you don't manage agents, you don't even manage platforms. Agent Managers
run your fleet across every platform autonomously while you sleep.

Hierarchy (12 managers total, 10 platforms + 2 supervisory):

    ChiefAgentManager                   # fleet conductor
    ├── InfrastructureAgentManager      # cross-platform safety layer
    ├── FunnelAgentManager              # cross-platform content/conversion
    ├── InstagramAgentManager
    ├── ThreadsAgentManager
    ├── RedditAgentManager
    ├── XAgentManager
    ├── TikTokAgentManager
    ├── DatingAgentManager              # Tinder / Bumble / Hinge / Grindr
    ├── TelegramAgentManager
    ├── DiscordAgentManager
    └── BlueSkyAgentManager

LinkedIn is reserved for the general (non-OFM) brand build only.
LinkedInAgentManager exists in linkedin.py but is excluded from the OFM platform set.

Every manager supervises its own set of specialist agents. The Chief does
not dispatch to specialists directly — only to managers. Platform managers
dispatch only to their own specialists (enforced by the supervises allowlist).
"""
from .base import ManagerAgent
from .chief import ChiefAgentManager
from .infrastructure import InfrastructureAgentManager
from .funnel import FunnelAgentManager
from .instagram import InstagramAgentManager
from .threads import ThreadsAgentManager
from .reddit import RedditAgentManager
from .x import XAgentManager
from .tiktok import TikTokAgentManager
from .dating import DatingAgentManager
from .telegram import TelegramAgentManager
from .linkedin import LinkedInAgentManager
from .discord import DiscordAgentManager
from .bluesky import BlueSkyAgentManager


MANAGER_CLASSES = {
    "chief": ChiefAgentManager,
    "infrastructure": InfrastructureAgentManager,
    "funnel": FunnelAgentManager,
    "instagram": InstagramAgentManager,
    "threads": ThreadsAgentManager,
    "reddit": RedditAgentManager,
    "x": XAgentManager,
    "tiktok": TikTokAgentManager,
    "dating": DatingAgentManager,
    "telegram": TelegramAgentManager,
    "discord": DiscordAgentManager,
    "bluesky": BlueSkyAgentManager,
    # LinkedIn excluded from OFM build — general brand only
}


# Platform metadata — used by marketing pages + dashboard to render the
# platform catalog without hardcoding it in TypeScript.
PLATFORM_META = {
    "instagram":  {"label": "Instagram",  "order": 1, "phase": "Phase 1", "tier": "locked",      "icon": "Instagram"},
    "threads":    {"label": "Threads",    "order": 2, "phase": "Phase 2", "tier": "planned",     "icon": "Hash"},
    "reddit":     {"label": "Reddit",     "order": 3, "phase": "Phase 2", "tier": "planned",     "icon": "MessageCircle"},
    "x":          {"label": "X / Twitter","order": 4, "phase": "Phase 3", "tier": "planned",     "icon": "Twitter"},
    "tiktok":     {"label": "TikTok",     "order": 5, "phase": "Phase 3", "tier": "planned",     "icon": "Music"},
    "telegram":   {"label": "Telegram",   "order": 6, "phase": "Phase 4", "tier": "planned",     "icon": "Send"},
    "discord":    {"label": "Discord",    "order": 7, "phase": "Phase 4", "tier": "planned",     "icon": "MessageSquare"},
    "dating":     {"label": "Tinder · Bumble · Hinge · Grindr", "order": 8, "phase": "Phase 5", "tier": "gated",    "icon": "Heart"},
    "bluesky":    {"label": "BlueSky",    "order": 9, "phase": "Phase 5", "tier": "first_mover", "icon": "Cloud"},
    # LinkedIn lives in the general (non-OFM) brand only — not in PLATFORM_META here
}


__all__ = [
    "MANAGER_CLASSES",
    "PLATFORM_META",
    "ManagerAgent",
    "ChiefAgentManager",
    "InfrastructureAgentManager",
    "FunnelAgentManager",
    "InstagramAgentManager",
    "ThreadsAgentManager",
    "RedditAgentManager",
    "XAgentManager",
    "TikTokAgentManager",
    "DatingAgentManager",
    "TelegramAgentManager",
    "LinkedInAgentManager",
    "DiscordAgentManager",
    "BlueSkyAgentManager",
]
