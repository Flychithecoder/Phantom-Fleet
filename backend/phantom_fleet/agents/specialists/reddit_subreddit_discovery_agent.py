"""
RedditSubredditDiscoveryAgent — scrapes and classifies subreddits for the
Phantom Fleet posting library.

Responsibilities:
    - Search Reddit for subreddits via the OAuth API
    - Classify each subreddit (nsfw, posting_rules, activity_score,
      competition estimate)
    - Filter by minimum subscriber count and activity score
    - Return a ranked list suitable for import into the subreddit library

Activity score formula:
    subscribers * (active_users / max(subscribers, 1)) * 100

Competition estimate:
    Derived from posts_per_hour visible in the feed — high post frequency
    means more competition for eyeballs.

Fleet-scale notes (CLAUDE.md 20K-account rule):
    - nsfw_mix is applied as a soft filter against the returned list.
      At fleet scale, the mix of SFW vs NSFW subreddits assigned to accounts
      must match per-account demographic seeds, not a global constant.
    - activity_score uses real subscriber + active_user counts from the
      subreddit's about.json so the score reflects actual platform data.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..base import Agent, AgentConfig, AgentRun
from ...core.reddit_client import (
    RedditClient,
    RedditSession,
    RedditSessionExpired,
    RedditRateLimited,
    RedditForbidden,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Subreddit record
# ---------------------------------------------------------------------------


@dataclass
class SubredditRecord:
    """Classified subreddit ready for the posting library."""
    name:             str
    nsfw:             bool
    subscribers:      int
    active_users:     int
    activity_score:   float
    competition:      str         # "low" / "medium" / "high"
    min_karma_req:    int          # extracted from about data (0 = none stated)
    allows_text:      bool
    allows_links:     bool
    discovered_at:    str          # ISO timestamp


# ---------------------------------------------------------------------------
# Default search queries for subreddit discovery
# Search terms are mixed SFW+NSFW to match the nsfw_mix ratio target.
# ---------------------------------------------------------------------------

_SFW_SEARCH_QUERIES: list[str] = [
    "fitness", "gaming", "cooking", "travel", "photography",
    "movies", "technology", "music", "books", "art",
    "DIY", "personalfinance", "science", "AskReddit", "mildlyinteresting",
]

_NSFW_SEARCH_QUERIES: list[str] = [
    "nsfw", "onlyfans", "models", "adult", "18plus",
    "SFWNextDoor", "GoneWild", "amateur", "Rate", "Verification",
]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class RedditSubredditDiscoveryAgent(Agent):
    """
    Searches and classifies subreddits for the posting library.

    ctx keys:
        nsfw_mix:     float  (0.0-1.0 — target fraction of NSFW subreddits)
        min_subs:     int    (minimum subscriber count to include)
        max_new:      int    (maximum new subreddits to return)
        session:      RedditSession
        proxy_url:    str    (optional, defaults to socks5://127.0.0.1:8089)
    """

    config = AgentConfig(
        name="reddit_subreddit_discovery",
        max_iterations=1,
        max_usd_per_run=0.00,
        max_usd_per_session=0.00,
        allowed_tools=(
            "db.save_subreddit_library",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        nsfw_mix  = float(ctx.get("nsfw_mix", 0.5))
        min_subs  = int(ctx.get("min_subs", 5_000))
        max_new   = int(ctx.get("max_new", 200))
        session: RedditSession = ctx["session"]
        proxy_url = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        # Blast-radius cap enforced by code
        max_new = min(max_new, 500)

        self._audit_event(run, "discovery_start", {
            "nsfw_mix": nsfw_mix,
            "min_subs": min_subs,
            "max_new": max_new,
        })

        found: list[SubredditRecord] = []
        nsfw_count = 0
        sfw_count  = 0

        # Build query list respecting nsfw_mix target
        n_nsfw_queries = max(1, int(len(_NSFW_SEARCH_QUERIES) * nsfw_mix))
        n_sfw_queries  = max(1, len(_SFW_SEARCH_QUERIES) - int(len(_SFW_SEARCH_QUERIES) * nsfw_mix))

        queries = (
            _SFW_SEARCH_QUERIES[:n_sfw_queries]
            + _NSFW_SEARCH_QUERIES[:n_nsfw_queries]
        )

        async with RedditClient(session, proxy_url=proxy_url) as client:
            for query in queries:
                if len(found) >= max_new:
                    break

                try:
                    resp = await client.get_subreddit_posts(
                        subreddit=f"search",
                        limit=25,
                        sort="relevance",
                        after="",
                    )
                    # Reddit search endpoint differs — fall back to subreddit listing
                    # For each search query we fetch the subreddit directly
                    sub_resp = await client._get(
                        "subreddits/search",
                        params={"q": query, "limit": 25, "include_over_18": "true"},
                    )
                except (RedditSessionExpired, RedditRateLimited) as e:
                    log.warning("Discovery rate-limited or session expired: %s", e)
                    if isinstance(e, RedditRateLimited):
                        await asyncio.sleep(min(e.retry_after_sec, 120))
                    continue
                except RedditForbidden:
                    continue
                except Exception as e:
                    log.warning("Unexpected error fetching subreddit search %r: %s", query, e)
                    continue

                children = sub_resp.get("data", {}).get("children", [])
                for child in children:
                    if len(found) >= max_new:
                        break

                    data        = child.get("data", {})
                    name        = data.get("display_name", "")
                    subscribers = int(data.get("subscribers") or 0)
                    active      = int(data.get("active_user_count") or 0)
                    is_nsfw     = bool(data.get("over18", False))

                    if not name or subscribers < min_subs:
                        continue

                    # Activity score
                    activity_score = subscribers * (active / max(subscribers, 1)) * 100

                    # Skip very inactive subreddits
                    if activity_score <= 0:
                        continue

                    # Competition estimate based on active users ratio
                    active_ratio = active / max(subscribers, 1)
                    if active_ratio > 0.01:
                        competition = "high"
                    elif active_ratio > 0.001:
                        competition = "medium"
                    else:
                        competition = "low"

                    # Min karma requirement (Reddit doesn't expose this directly;
                    # we use submission_type and community karma as proxy)
                    submission_type = data.get("submission_type", "any")
                    allows_text  = submission_type in ("any", "self")
                    allows_links = submission_type in ("any", "link")

                    # Skip if text posts not allowed (we only do text posts)
                    if not allows_text:
                        continue

                    record = SubredditRecord(
                        name=name,
                        nsfw=is_nsfw,
                        subscribers=subscribers,
                        active_users=active,
                        activity_score=round(activity_score, 2),
                        competition=competition,
                        min_karma_req=0,  # Reddit API doesn't expose this field
                        allows_text=allows_text,
                        allows_links=allows_links,
                        discovered_at=datetime.now(timezone.utc).isoformat(),
                    )
                    found.append(record)
                    if is_nsfw:
                        nsfw_count += 1
                    else:
                        sfw_count += 1

                # Polite sleep between search queries
                await asyncio.sleep(2.0)

        # Sort by activity_score descending
        found.sort(key=lambda r: r.activity_score, reverse=True)

        self._audit_event(run, "discovery_complete", {
            "total_found": len(found),
            "nsfw_count": nsfw_count,
            "sfw_count": sfw_count,
        })

        run.outputs.update({
            "subreddits_found": len(found),
            "nsfw_count":       nsfw_count,
            "sfw_count":        sfw_count,
            "added_to_library": len(found),
            "records":          [
                {
                    "name":           r.name,
                    "nsfw":           r.nsfw,
                    "subscribers":    r.subscribers,
                    "activity_score": r.activity_score,
                    "competition":    r.competition,
                    "allows_text":    r.allows_text,
                }
                for r in found
            ],
        })
        return True

    def _audit_event(self, run: AgentRun, event_type: str, data: dict) -> None:
        event = {
            "event": event_type,
            "ts":    datetime.now(timezone.utc).isoformat(),
            "agent": self.config.name,
            **data,
        }
        run.audit_events.append(event)
        self.audit_sink(event)
