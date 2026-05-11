"""
BlueSkyScrapeAgent — AT Protocol target discovery for the BlueSky follow pool.

What it does:
    1. Searches BlueSky for posts matching each topic keyword via
       app.bsky.feed.searchPosts.
    2. For each post returned, extracts the author's DID.
    3. Optionally resolves the author's follower count via app.bsky.actor.getProfile
       and applies minimum follower / maximum follower filters.
    4. Deduplicates against the existing_did_pool passed by the manager.
    5. Returns a list of new target DIDs suitable for BlueSkyFollowAgent.

Why AT Protocol search is valuable:
    - The AT Protocol firehose is public — no reverse engineering, no
      detection risk. Scraping is legal and expected by the protocol.
    - Search returns authors actively posting about relevant topics = warm targets.
    - Follower-count filtering lets the fleet avoid mega-celebrities
      (who won't follow back) and ghost accounts (who never will).

Fleet-scale hardening (CLAUDE.md 20K-account rule):
    - Topic list is shuffled per (account_id, date_iso) so different accounts
      use different topic orderings and the API call timing differs.
    - Inter-query sleep: LogNormal(mean=ln(4), σ=0.3) — not fixed.
    - Dedup against existing_did_pool happens before profile resolution so
      we avoid expensive profile API calls for already-known targets.
    - max_dids is code-enforced (caller cannot bypass the cap).

Blast-radius caps:
    MAX_DIDS_PER_RUN = 500  (code-enforced)
    MAX_PROFILE_LOOKUPS = 200  (limits extra API calls per run)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from ..base import Agent, AgentConfig, AgentRun
from ...core.distributions import LogNormal, seed_for
from ...core.bluesky_client import (
    BlueSkyClient,
    BlueSkySession,
    BlueSkySessionExpired,
    BlueSkyRateLimited,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

_INTER_QUERY_DIST   = LogNormal(low=2.0, high=15.0, sigma=0.30)
_INTER_PROFILE_DIST = LogNormal(low=0.5, high=5.0,  sigma=0.25)

# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------

MAX_DIDS_PER_RUN    = 500
MAX_PROFILE_LOOKUPS = 200

# ---------------------------------------------------------------------------
# Default topic pools — overridden by ctx["topics"] at runtime
# ---------------------------------------------------------------------------

DEFAULT_SFW_TOPICS: list[str] = [
    "creator", "content", "lifestyle", "photography", "art",
    "music", "travel", "fitness", "fashion", "food",
    "beauty", "motivation", "tech", "design", "culture",
    "wellness", "gaming", "film", "books", "comedy",
]

DEFAULT_NSFW_TOPICS: list[str] = [
    "onlyfans", "fanvue", "exclusive content", "creator content",
    "adult content", "nsfw", "18plus", "spicy content",
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ScrapedTarget:
    did:              str
    handle:           str
    follower_count:   int
    topic:            str    # which search query surfaced this account


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class BlueSkyScrapeAgent(Agent):
    """
    AT Protocol target discovery agent.

    ctx keys:
        account_id:        str
        session:           BlueSkySession
        topics:            list[str]    — search query terms
        max_dids:          int          — max new DIDs to collect (≤ 500)
        min_followers:     int          — skip profiles below this (default: 0)
        max_followers:     int          — skip profiles above this (default: 100_000)
        resolve_profiles:  bool         — whether to look up follower counts
        existing_did_pool: list[str]    — DIDs already in the pool (dedup)
        date_iso:          str
        proxy_url:         str

    Outputs (run.outputs):
        new_dids:     list[str]         — discovered DIDs not in existing pool
        targets:      list[dict]        — full ScrapedTarget records
        errors:       list[str]
    """

    config = AgentConfig(
        name="bluesky_scrape",
        max_iterations=1,
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id:        str            = ctx["account_id"]
        session:           BlueSkySession = ctx["session"]
        topics:            list[str]      = ctx.get("topics") or DEFAULT_SFW_TOPICS
        max_dids:          int            = min(int(ctx.get("max_dids", 100)), MAX_DIDS_PER_RUN)
        min_followers:     int            = int(ctx.get("min_followers", 0))
        max_followers:     int            = int(ctx.get("max_followers", 100_000))
        resolve_profiles:  bool           = bool(ctx.get("resolve_profiles", False))
        existing_pool:     set[str]       = set(ctx.get("existing_did_pool") or [])
        date_iso:          str            = ctx.get("date_iso", date.today().isoformat())
        proxy_url:         str            = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        new_dids:     list[str]           = []
        new_dids_set: set[str]            = set()  # O(1) dedup — list alone is O(n²)
        targets:      list[ScrapedTarget] = []
        errors:       list[str]           = []
        profile_lookups = 0

        # ---- Per-account topic shuffle ----
        seed_val = int(hashlib.sha256(
            f"{account_id}|{date_iso}|topic_shuffle".encode()
        ).hexdigest()[:8], 16)
        rng = random.Random(seed_val)
        shuffled_topics = list(topics)
        rng.shuffle(shuffled_topics)

        self._audit({
            "event":       "bluesky_scrape_start",
            "account_id":  account_id,
            "topics":      shuffled_topics,
            "max_dids":    max_dids,
        })

        async with BlueSkyClient(session, proxy_url=proxy_url) as client:
            for topic in shuffled_topics:
                if len(new_dids) >= max_dids:
                    break

                try:
                    resp = await client.search_posts(query=topic, limit=25)
                except BlueSkySessionExpired:
                    log.warning("[bluesky_scrape/%s] Session expired", account_id)
                    errors.append("session_expired")
                    break
                except BlueSkyRateLimited as exc:
                    log.warning(
                        "[bluesky_scrape/%s] Rate limited — backing off %ds",
                        account_id, exc.retry_after_sec,
                    )
                    errors.append(f"rate_limited:{exc.retry_after_sec}s")
                    await asyncio.sleep(min(exc.retry_after_sec, 60))
                    continue
                except Exception as exc:
                    log.warning("[bluesky_scrape/%s] Search failed for %r: %s", account_id, topic, exc)
                    errors.append(f"search_error:{topic}:{exc}")
                    continue

                for post in resp.get("posts", []):
                    if len(new_dids) >= max_dids:
                        break

                    author = post.get("author", {})
                    did    = author.get("did", "")
                    handle = author.get("handle", "")

                    if not did or did in existing_pool or did in new_dids_set:
                        continue

                    # ---- Profile resolution (optional) ----
                    follower_count = 0
                    if resolve_profiles and profile_lookups < MAX_PROFILE_LOOKUPS:
                        try:
                            profile = await client.get_profile(did)
                            follower_count = profile.get("followersCount", 0)
                            profile_lookups += 1

                            # Apply follower filter
                            if follower_count < min_followers or follower_count > max_followers:
                                continue

                        except Exception as exc:
                            log.debug("[bluesky_scrape/%s] Profile lookup failed for %s: %s", account_id, did, exc)
                            # Don't reject — include without filter
                        finally:
                            sleep_s = _INTER_PROFILE_DIST.sample(
                                account_id=account_id,
                                date_iso=date_iso,
                                field=f"profile_sleep_{did}",
                            )
                            await asyncio.sleep(sleep_s)

                    new_dids.append(did)
                    new_dids_set.add(did)
                    targets.append(ScrapedTarget(
                        did=did,
                        handle=handle,
                        follower_count=follower_count,
                        topic=topic,
                    ))

                # ---- Inter-query sleep ----
                sleep_s = _INTER_QUERY_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"inter_query_{topic}",
                )
                await asyncio.sleep(sleep_s)

        self._audit({
            "event":           "bluesky_scrape_end",
            "account_id":      account_id,
            "new_dids_found":  len(new_dids),
            "profile_lookups": profile_lookups,
            "errors":          len(errors),
        })

        run.outputs["new_dids"] = new_dids
        run.outputs["targets"]  = [
            {"did": t.did, "handle": t.handle, "follower_count": t.follower_count, "topic": t.topic}
            for t in targets
        ]
        run.outputs["errors"] = errors
        return True
