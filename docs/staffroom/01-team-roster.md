# Phantom Fleet / OrionFarm — specialist roster

**Headcount: 45** — 1 COO + 6 platform managers + 14 core non-platform specialists + 24 Treg-driven platform-team specialists.
Dating, Discord, and Telegram dropped by owner 2026-11-24.

Every role maps to a concrete Phantom Fleet subsystem — a
`backend/phantom_fleet/agents/managers/*.py` module, a
`agents/specialists/*.py`, a `platforms/*` module, a Treg catalog scope
from `treg.to/catalog/{instagram,tiktok,threads,reddit,bluesky}`, or a
recurring operational workflow.

Model pin is informational: the runner's auto-router decides routing
from message shape; `effective_model` in `runner/logs/runner-audit.ndjson`
is the authoritative record.

Every role runs read-only during the pilot and surfaces decisions
through Staffroom. Destructive paths (flash, factory-reset, fleet-wide
APK push, `iguserdatabase.db` mutation) stay gated by **code**, per
CLAUDE.md.

Platform-team specialists (violet in the UI) sit **under** their
platform manager (pink) and hand off results via Staffroom's
`staffroom_propose_work` pattern. The manager is the dispatcher +
reviewer; the specialists do the Treg-driven discovery and intel.

---

## Executive (1)

### `coo_strategist` (opus)
Decompose owner missions, review evidence, write the final decision.
Backing: `agents/managers/chief.py`.

---

## Platform managers (6) — all sonnet

| Slug | Manages |
|---|---|
| `instagram_manager` | 8 IG specialists + `platforms/instagram_*` triad |
| `threads_manager` | 3 Threads specialists + `platforms/threads_*` triad |
| `reddit_manager` | 4 Reddit specialists + `agents/specialists/reddit_*` + Gmail pool |
| `x_manager` | X ops (orchestrator/health gap flagged, no platform team yet) |
| `tiktok_manager` | 7 TikTok specialists + `core/tiktok_controller.py` + FBR tracker |
| `bluesky_manager` | 2 Bluesky specialists + 11 native specialists + A/B test |

---

## Instagram platform team (+8 under `instagram_manager`)

Treg scope: `*.instagram.*` (118 capabilities catalogued).

| Slug | Role | Primary Treg tools |
|---|---|---|
| `ig_target_scout` | Target discovery | `treg.instagram.hashtag.posts`, `treg.instagram.search.users`, `tikhub.instagram-v3-get-similar-users`, `tikhub.instagram-v2-fetch-user-followers`, `tikhub.instagram-v1-fetch-related-profiles` |
| `ig_viral_hunter` | Viral Reel + explore discovery | `scrapecreators.v1-instagram-reels-trending`, `tikhub.instagram-v3-get-recommended-reels`, `treg.instagram.search.reels`, `tikhub.instagram-v1-fetch-explore-sections`, AnyAPI Hashtag Top Posts + Analytics |
| `ig_commenter_harvester` | Warm-lead harvest | `treg.instagram.post.comments`, `tikhub.instagram-v3-get-post-likes`, AnyAPI Post Likers |
| `ig_profile_intel` | Target dossier | `treg.instagram.user.profile`, `.user.posts`, `.user.reels`, `tikhub.instagram-v3-get-user-about`, `-former-usernames`, `-stories`, AnyAPI Stories (full/basic) |
| `ig_comment_bait` | Bait placement | consumer only → feeds `ig_comment_pod_agent.py` |
| `ig_follow_unfollow` | Follow/unfollow pacing | consumer only → feeds `ig_follow_story_orchestrator_agent.py`, `ig_unfollow_agent.py` |
| `ig_contact_extractor` | Contact enrichment | AnyAPI Instagram Profile Contact Info (highest-cost IG tool, cap 50/day) |
| `ig_transcript_analyst` | Viral content theme mining | ScrapeCreators IG video/reel transcript, AnyAPI Reel + Media Transcript |

---

## TikTok platform team (+7 under `tiktok_manager`)

Treg scope: `*.tiktok.*` (123 capabilities catalogued).

| Slug | Role | Primary Treg tools |
|---|---|---|
| `tiktok_target_scout` | Target discovery | `treg.tiktok.search.users`, ScrapeCreators popular-creators (filter followers + country), `anyapi.tiktok.trending_hashtags`, `tikhub.tiktok.hashtag.videos`, similar-user-recommendations |
| `tiktok_viral_hunter` | FYP + music charts | `scrapecreators.v1-tiktok-get-trending-feed`, music chart list (Top 50 / Viral 50), `treg.tiktok.search.videos`, trending-searchwords, home-feed |
| `tiktok_authenticity_gate` | Fake-view detection | `tikhub.tiktok-analytics-detect-fake-views`, video-metrics, comment-keywords |
| `tiktok_comment_bait` | Bait placement | `treg.tiktok.video.comments`, `.video.detail` → feeds `tiktok_comment_agent.py` |
| `tiktok_follow_unfollow` | Follow/unfollow pacing | consumer only → feeds `tiktok_follow_agent.py`, FBR tracker |
| `tiktok_creator_health_intel` | **Shadowban + violation watch** (replaces in-house) | TikHub creator account health + violation + info + insights + video analytics + audience demographics |
| `tiktok_contact_extractor` | Contact enrichment | AnyAPI TikTok Profile Contact Info |

**Key win:** TikHub's `creator account health status` + `creator account violation records` give us real shadowban + strike intel via Treg. This replaces what we'd have to infer from device-side behaviour.

---

## Threads platform team (+3 under `threads_manager`)

Treg scope: `*.threads.*` (19 capabilities — complete catalog).

| Slug | Role | Primary Treg tools |
|---|---|---|
| `threads_target_scout` | Target discovery | `treg.threads.search.posts`, `tikhub.threads-web-search-profiles`, `scrapecreators.v1-threads-search-users` + profile enrich |
| `threads_viral_hunter` | Viral post discovery | `tikhub.threads-web-search-top`, `scrapecreators.v1-threads-post` (velocity), post-detail-v2 |
| `threads_commenter_harvester` | Warm-lead harvest | `tikhub.threads-web-fetch-post-comments`, user-replies |

Follow/unfollow + bait placement stay on existing Python agents
(`threads_follow_agent.py`, `threads_engagement_agent.py`) driven by
these three.

---

## Reddit platform team (+4 under `reddit_manager`)

Treg scope: `*.reddit.*` (31 of 52 capabilities catalogued; shadowban
stays on in-house `shadowban_check_agent.py` — no Treg endpoint).

| Slug | Role | Primary Treg tools |
|---|---|---|
| `reddit_sub_scout` | Subreddit discovery | `tikhub.reddit-app-fetch-search-typeahead`, subreddit-info, `scrapecreators.v1-reddit-subreddit-details` |
| `reddit_post_harvester` | Bait-candidate posts | `treg.reddit.subreddit.posts`, scrapecreators subreddit posts, `treg.reddit.post.detail`, post-details-batch |
| `reddit_karma_gate` | Target karma verify | `tikhub.reddit-app-fetch-user-profile`, user-posts, `crawl4ai.reddit.user.posts` |
| `reddit_thread_intel` | Thread timing + depth | `crawl4ai.reddit.post.comments`, comment-replies |

Karma floor from CLAUDE.md is enforced here — nothing reaches
`reddit_inbox_chat_agent.py` until `reddit_karma_gate` passes.

---

## Bluesky platform team (+2 under `bluesky_manager`)

Treg scope: `scrapecreators.*-bluesky-*` (only 3 capabilities — Treg is
thin for Bluesky; discovery stays on in-house `bluesky_scrape_agent.py`).

| Slug | Role | Primary Treg tools |
|---|---|---|
| `bluesky_profile_intel` | Target enrichment | `scrapecreators.v1-bluesky-profile`, `-user-posts` |
| `bluesky_post_engagement_monitor` | Viral velocity watch | `scrapecreators.v1-bluesky-post` |

---

## Core non-platform specialists (14) — all sonnet

### Funnel + content

- **`funnel_manager`** — fan → OF / Fanvue funnel (`agents/funnel_conversion_agent.py`, `core/dm_funnel.py`, `platforms/instagram_funnel.py`)
- **`content_vault_operator`** — content supply chain (`core/content_vault.py`, `content_scout_agent.py`, `content_agent.py`)

### Fleet operations

- **`infrastructure_manager`** — ADB + Wi-Fi + Postgres + event bus (`agents/managers/infrastructure.py`, `core/phone_controller.py`, `adb_router.py`, `apk_client.py`, `s10_box_config.py`)
- **`proxy_orchestrator`** — 72h TTL + 1:5:20 ratio (`agents/proxy_orchestrator_agent.py`, `platforms/instagram_proxy.py`)
- **`capacity_planner`** — accounts-per-phone ceiling (`agents/capacity_planner_agent.py`, `core/capacity_planner.py`, `cluster_monitor.py`)
- **`fleet_reconciler`** — three-way devices.db ↔ ADB ↔ Fleet Mirror (`routes/fleet.py`, `fleet_mirror.py`, `fleet_mirror_client.py`)

### Reliability + integrity

- **`checkpoint_sentinel`** — IG/Threads checkpoint burst (`platforms/instagram_checkpoint.py`, `threads_recovery.py`)
- **`drift_watcher`** — `_TRIP_STREAK` across model/OS/locale/timezone/carrier/HNI/signing_cert (`platforms/instagram_drift.py`, `agents/fingerprint_monitor_agent.py`)
- **`audit_harness_operator`** — 10K Monte Carlo CI gate (`agents/audit_harness_agent.py`, `core/distributions.py`)
- **`persona_factory_lead`** — issuance + cross-field pair-check (`agents/persona_factory_agent.py`, `core/persona.py`, `male_persona_factory.py`)
- **`recovery_coordinator`** — replacement queue (`agents/recovery_agent.py`, `replacement_agent.py`, `platforms/instagram_recovery.py`, `threads_recovery.py`)

### Warming + owner-facing

- **`warming_coordinator`** — Day-0→Day-29+ curves (`core/warming_curve.py`, `warming_orchestrator.py`, `warmup_phases.py`, `human_post_behavior.py`)
- **`briefing_writer`** — 08:00 owner-local brief (`/briefing`, `routes/ops.py`, `activity_log.py`)
- **`cost_reconciler`** — three-ledger reconcile (`runner-audit.ndjson` ↔ Staffroom ↔ Fleet SQLite)

---

## Recurring workflow ownership

| Workflow | Owner | Backing |
|---|---|---|
| Fleet reconcile vs devices.db | `fleet_reconciler` | `routes/fleet.py` |
| Fleet health sweep | `infrastructure_manager` | `platforms/{ig,threads}_health.py` |
| Proxy TTL rotation | `proxy_orchestrator` | `agents/proxy_orchestrator_agent.py` |
| IG session refresh | `instagram_manager` | `core/ig_session_store.py` |
| IG checkpoint burst watch | `checkpoint_sentinel` | `platforms/instagram_checkpoint.py` |
| Device-drift scan | `drift_watcher` | `platforms/instagram_drift.py` |
| Warming-curve pacing | `warming_coordinator` | `core/warming_curve.py` |
| 10K-persona audit | `audit_harness_operator` | `agents/audit_harness_agent.py` |
| Persona issuance + pair-check | `persona_factory_lead` | `agents/persona_factory_agent.py` |
| Account replacement queue | `recovery_coordinator` | `agents/replacement_agent.py` |
| Funnel conversion review | `funnel_manager` | `routes/funnel.py` |
| Source-pool rescore | `warming_coordinator` | `core/source_scorer.py` |
| Companion-APK pilot gate | `infrastructure_manager` | `companion-apk/app/...` (gated) |
| Postgres + IG DB backup | `infrastructure_manager` | `backend/migrations/` + CLAUDE.md gate |
| Owner briefing | `briefing_writer` | `/briefing` + `routes/ops.py` |
| Cost ledger | `cost_reconciler` | `runner-audit.ndjson` |
| Access/grant review | `coo_strategist` | `routes/staffroom_missions.py` |
| **IG target discovery cadence** | `ig_target_scout` | Treg `*.instagram.*` |
| **IG viral bait feed** | `ig_viral_hunter` | Treg `*.instagram.*` |
| **TikTok creator-health daily sweep** | `tiktok_creator_health_intel` | Treg TikHub analytics |
| **TikTok FYP viral feed** | `tiktok_viral_hunter` | Treg `*.tiktok.*` |
| **Threads viral bait feed** | `threads_viral_hunter` | Treg `*.threads.*` |
| **Reddit karma-gate per-DM** | `reddit_karma_gate` | Treg `*.reddit.user.*` |
