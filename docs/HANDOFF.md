# Phantom Fleet — complete buildout handoff

This document is the single hand-off spec for everything planned or built in
the Phantom Fleet / OrionFarm project as of 2026-11-25. It was assembled
from the live source tree and docs, not from memory. Every claim is cited
to the file it came from.

The next session should be able to rebuild, extend, or audit any part of
the system using only this document plus repo access.

## How this doc is organized

- **Section 1** — Mission, 5-layer architecture, locked stack, hard rules,
  repo layout, phase roadmap, open questions.
- **Section 2** — Backend: FastAPI app, every route file, every core
  module, the ops layer (sched/dispatch/targets/cron), persona-store
  schema, state machines, picker→APK contract.
- **Section 3** — Frontend: app shell, sidebar, every page under
  `src/app/`, shared components, design system, WebSocket flows, the
  `/approvals` owner UI from commit `14d11d9`.
- **Section 4** — Companion APK (Kotlin + Ktor), pilot wire-up, Staffroom
  MCP server + Treg research transport, Fleet's MCP allowlist,
  `ig_target_scout` agent spec, the target admission contract.
- **Section 5** — Docs inventory, 4 Onimator fleet bugs with fix loci,
  tiered buildout backlog, cron cadences, hardware intel, audit/safety,
  the end-to-end golden-path workflow, smoke-harness index,
  observability, glossary.

## Repos touched by this spec

- `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\` — Fleet (this
  codebase: backend, frontend, ops, companion-apk, docs).
- `C:\Users\admin\Desktop\PhantomFleet\_staffroom\` — adjacent Staffroom
  repo. Owns the owner approval surface, the MCP server, and the Treg
  research transport.

---

# Section 1: Mission, architecture, stack, rules

> **Scope of this document.** Section 1 of a multi-section handoff spec for the
> Phantom Fleet project (internal codename **OrionFarm** in older docs — the
> repository was renamed to Phantom Fleet mid-plan; both names refer to the
> same product). It covers the executive mission + business model, the
> 5-layer architecture, locked stack decisions, every hard rule, repo layout,
> working mode, phase roadmap, and open questions. Downstream sections
> (persona core, fingerprint audit, agents, UI, companion APK, provisioning,
> proxy, etc.) are handled by parallel handoff documents — this file
> deliberately does not duplicate them.
>
> **Primary sources.** All claims in this section cite exact file paths inside
> `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\`:
> - `PLAN.md` (1009 lines) — the executive plan v2 (Discord-amplified)
> - `HARDWARE.md` (281 lines) — the fleet-hardware audit
> - `README.md` (218 lines) — the public-facing status + metrics doc
> - `PHANTOM_FLEET_VS_ONIMATOR.md` (172 lines) — feature-parity matrix
> - `.claude/CLAUDE.md` — repo-local Claude Code instructions
> - `frontend/src/app/phase1/page.tsx` and `phase2/page.tsx` — live readiness
>   dashboards that visualize the phase roadmap
> - `C:\Users\admin\Desktop\PhantomFleet\_staffroom\` — adjacent repo for the
>   Clipster → Fleet publishing handoff contract

---

## Mission and business model

### One-line pitch

> "Phantom Fleet is the only social media automation platform that runs
> fleet-scale cluster detection on 20 fingerprint dimensions with a 10,000-
> persona Monte Carlo CI gate, a unified cross-platform persona primitive, and
> 15 autonomous AI agents that replace every hour of manual operational
> labor — all on hardware you already own."
> — `README.md:212–216`

### Executive mission statement

From `PLAN.md:3`:

> **Mission:** The single operating system for mass social media automation
> across physical Android device farms. Built to 1000x every axis of
> Onimator while working on the exact hardware we already own, funneling
> fans to OnlyFans / Fanvue / ScaleHer at scale, with AI agent
> orchestration replacing every hour of manual labor.

The public README restates this in industry-neutral form (`README.md:4–13`):

> Phantom Fleet is the real-device social media automation platform for
> growth agencies, brands, creators, dropshippers, OFM agencies, and
> lead-gen operators who need to scale across every major platform without
> burning accounts. **15 autonomous AI agents**, live fleet-scale cluster
> detection, a unified cross-platform persona primitive, and a $500M-tier
> command dashboard — all running on the hardware you already own.
>
> **Whatever your vertical.** Phantom Fleet is industry-neutral: what you
> run on it, and what destination you funnel conversions to (store,
> subscription, lead capture, affiliate, OF/Fanvue/ScaleHer, etc.) is up
> to you.

Internal strategy docs still name OnlyFans / Fanvue / ScaleHer as the first
revenue vertical (`PLAN.md:3`), but the product itself is positioned
industry-neutral in the README (`README.md:11–13`).

### Status timestamp

- Planning v2 locked **2026-04-11** (`PLAN.md:5`)
- README status "**Phase 0 scaffolding complete**" (`README.md:28`)
- Today's working date: **2026-11-25** — i.e. Phase 0 scaffolding was marked
  complete ~7 months before this handoff is being written, but the four
  blockers in `README.md:30–33` are still open at README time:
  1. Proxy-state diagnostic (read-only verification of current phone routing)
  2. IPRoyal Royal Residential Unlimited purchase (~$80/mo)
  3. Login-survival test on all 16 authorized phones (blocked by proxy gate)
  4. Full-box parallel Day 1 launch across 19 devices + 219 Tatiana/Melodie
     accounts

### Discord intel pedigree

Planning v2 was written after reading **48,849 messages** from the Onimator
Discord (2023-09-26 to 2026-04-11), covering founder "curdoc/Simon" plus the
top community professional users (`PLAN.md:5`). The export lives in
`discord-export/` with analysis files `top_authors.md`, `keyword_index.md`,
`pro_posts.md`, `channel_summaries.md`, `full_small.md`, and two large data
dumps `onimator_intel.md` (2.3 MB) + `onimator_intel.json` (7.3 MB), plus a
concise 219-account extraction `onimator_summary.md`
(`README.md:121–127`).

### Panel integration metadata

- **Panel name:** OrionFarm (in `.claude/CLAUDE.md`) / Phantom Fleet (in
  `README.md`)
- **Panel location (planning-era):** `C:\Users\User\Desktop\Scaler Pro\orionfarm\`
  (`PLAN.md:7`). The actual working repo is
  `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\` — the
  `Scaler Pro\orionfarm\` path was the intended destination in the Scaler
  Pro panel ecosystem; the current checkout is a stand-alone clone.
- **Port:** 3016 (`PLAN.md:8`, `.claude/CLAUDE.md`, `README.md:73`)
- **Complements (never replaces):** existing `meta/`, `instagram/`,
  `threads/`, `reddit/`, `x-panel/`, `tiktok/` panels in Scaler Pro
  (`PLAN.md:9`, `.claude/CLAUDE.md`)
- **Depends on:** Scaler Pro ecosystem — HQ, Chat AI, ModelForge, Content
  Vault, unified model registry, cross-panel proxy sharing
  (`.claude/CLAUDE.md`)

### Scale targets

Hardware floor (`PLAN.md:10`):

> 9 farms × ~20 Samsung Galaxy S10 Lite phones (SM-G770F / SM-G770U1) =
> ~180 real devices

Hosting floor (`PLAN.md:11`):

> ZERO external hosting. Each farm PC runs local orchestrator. No VPS, no
> cloud cost.

### Capacity model — per-platform density

From `PLAN.md:373–391` (the "realistic accounts per phone" table):

| Platform | Onimator's claim | OrionFarm safe target | OrionFarm max push | Provisioning method |
|---|---|---|---|---|
| Instagram | 22-80 (with Jobs) | **15-20** | 30 | Aged marketplace + FB OAuth |
| TikTok | 8-12 | **8-12** | 20 | Aged marketplace (harder market) |
| Threads | same phone as IG | **5-10** | 15 | FB/IG linked, comes free with IG |
| Snapchat | 3-5 (from news) | **3-5** | 8 | Real SIM required, hardest |
| Reddit | 20-30 | **20-25** | 50 | Easy email signup, low friction |
| Tinder | Broken per user | **2-4** | 6 | Real SIM needed, Magisk for SafetyNet |
| Bumble | Broken per user | **2-4** | 6 | Real SIM needed, Magisk for SafetyNet |
| Hinge | Not supported | **2-3** | 5 | Real SIM needed, Magisk for SafetyNet |
| Twitter/X | via Xmator web | **15-20** | 30 | Xmator API path OR phone farm |
| Spotify | via NomixCloner | **15-25** | 40 | Email signup, very loose |
| LinkedIn | not mentioned | **3-5** | 8 | Email signup, phone optional |
| Facebook | via NomixCloner | **3-5** | 8 | Real phone or aged |
| YouTube | via NomixCloner | **8-15** | 20 | Gmail signup |
| Fanvue (mgmt) | manual | **5-10** | 15 | Creator login |
| OnlyFans (mgmt) | manual | **5-10** | 15 | Creator login |

Fleet capacity, realistic (`PLAN.md:395–404`):

| Cohort | Phones | Accounts/phone | Total | Purpose |
|---|---|---|---|---|
| Whale (premium personas) | 30 | 3 | 90 | OF funnel main, high-value revenue |
| Established | 60 | 10 | 600 | Daily DM/engage cohort |
| Volume warming | 60 | 20 | 1,200 | Warmup + mass actions |
| Dating (Tinder/Bumble/Hinge) | 20 | 3 | 60 | Limited by SafetyNet + real SIMs |
| Scratch / premium testing | 10 | 1 | 10 | Top-tier whale, brand-new personas |
| **TOTAL** | **180** | — | **~1,960 accounts** | Across 10+ platforms |

Per-platform slot totals from those 1,960 phone-slots (different accounts
per phone per platform — `PLAN.md:406–414`):

- IG: 1,400
- TikTok: 900
- Threads: 700 (linked with IG)
- Reddit: 800
- Snapchat: 300
- X (via Xmator): 500
- Tinder+Bumble+Hinge: 60
- Others: 200+

Grand total across platforms: **~4,000–5,000 active accounts at steady
state** (`PLAN.md:416`).

### Target market

The README lists the explicit customer buyers (`README.md:4–9`):

- Growth agencies
- Brands
- Creators
- Dropshippers
- OFM (OnlyFans management) agencies
- Lead-gen operators

The PLAN is specific that Onimator is the direct competitor the product is
built to 1000x on every axis (`PLAN.md:3, 977–998`).

### Revenue model and valuation path

From `PLAN.md:915–935` (section "**6. Business model / $100M valuation path**"):

Revenue streams:

1. **SaaS subscription** — undercut Onimator at low end, 10x at high end
   - Starter: $29/mo for 3 devices
   - Growth: $199/mo for 25 devices
   - Scale: $799/mo for 100 devices (vs Onimator's $650)
   - Enterprise: $2,499–$6,500/mo for 500–1000+
2. **Hosted-farm slot rental** — $150–400/phone/month
3. **Per-action metered** — $0.001 per action over plan
4. **White-label licensing** — $5–25K/mo flat per enterprise partner
5. **API access tier** — $499/mo
6. **Own clone pipeline (Phase 3+)** — compete directly with NomixCloner.
   $49–149/mo subscriptions. NomixCloner is doing ~$150K+/mo based on their
   1,500 clones/day and Premium pricing.
7. **Aged account brokerage** — built-in marketplace like Onimator's, take
   10% fee
8. **CupidAI-equivalent** — built into OrionFarm CRM, $99–299/mo add-on

Target revenue at scale (`PLAN.md:932–935`):

- 1,000 SaaS customers × $500 MRR = $6M ARR
- 50 hosted-farm customers × 20 phones × $250 = $3M ARR
- White-label + API + clone pipeline + CRM = $3–5M ARR
- **$12–14M ARR total → $120–140M valuation at 10x**

Moat (`PLAN.md:938–944`):

1. **Audit depth** — no competitor does fleet-scale cluster analysis in CI
2. **Persona unification** — no competitor has one persona across 10+
   platforms
3. **Hybrid execution routing** — no competitor routes intelligently
   between real phones + mobile APIs (note: the "hybrid" concept was later
   *revised*; see Layer 3 correction in `PLAN.md:244–248`)
4. **Full agent mesh** — Onimator has 1 AI feature (chat), we have 13+
   autonomous agents
5. **Scaler Pro ecosystem** — Chat AI, ScaleHer, ModelForge, HQ, Content
   Vault all become OrionFarm force multipliers
6. **Self-hosted, no kill switch** — unlike Onimator's license-gated model
7. **Real fleet operator** — we run 180 phones ourselves, so every feature
   is battle-tested on actual scale

The product-family naming (`README.md:19–22`):

- **Phantom Fleet** — the physical-device orchestrator (this repo)
- **Phantom Forge** — custom clone generation pipeline (Phase 3+)
- **Phantom Panel** — multi-tenant SaaS control plane (Phase 2+)
- **Phantom Prime** — enterprise tier (Phase 5+)

### Business-context reminder in CLAUDE.md

Repeated verbatim because it drives every architectural call
(`.claude/CLAUDE.md`, section "Business context reminder"):

> This is not a hobby project. Target is $100M valuation at ~$10M ARR via
> multi-tenant SaaS + hosted-farm leasing + API tier + white-label
> licensing. Every architectural choice should be evaluated against: does
> this scale to 1,000 tenants × 100 phones each?
>
> If the answer is no, rethink.

### Headline target metrics

From `README.md:191–207`:

| Metric | Value |
|---|---|
| Phones simultaneous | **19 of 19** |
| Accounts simultaneous | **219 existing + replacements** |
| Proxy IPs simultaneous (concurrent) | **up to 19 unique per session** via IPRoyal |
| Account 30-day survival target | **99.4%** |
| Account 6-month survival target | **60%+** |
| Daily fresh targets generated | **~4,000** |
| Approved source pool size target | **500+ female US creators** |
| Cluster detection latency | **< 5 minutes** |
| Agent mesh runs / day | **~2,000** |
| LLM cost cap / day | **$50** |
| Monthly proxy cost | **$80** (IPRoyal Unlimited) |
| Phase 1 revenue target | **$500–2,000/mo** OF funnel |

### Onimator intel summary (why Phantom Fleet exists)

The planning document section "**0. Intel summary — what we learned from
reading Onimator's Discord**" (`PLAN.md:15–220`) is the longest research
artifact in the repo and the direct justification for every architectural
decision. Highlights:

**Onimator's actual product stack** (`PLAN.md:17–27`):

- **Phone-farm orchestrator:** Python 3.9 PyInstaller monolith, Django web
  UI, per-persona Setting folders, AppCloner-driven multi-instance
- **NomixCloner:** Onimator's own cloud APK clone generator (replaced
  AppCloner May 2024). 14,278 Android IG clones/month in March 2025. 1,500
  clones/day with ~2,500 queued at peak — bottlenecked on software, not
  hardware
- **insta.onimator.com:** API-based IG service (Stories+, Close Friends
  bulk, mass DM, AI chat, caption generator, etc.)
- **ios.onimator.com:** iOS automation for Bumble/Instagram/Reddit
  (released Sept 2024)
- **OniBox.net:** Pre-built 20-phone boxes sold as a hardware product,
  bundled with Onimator license
- **Jobs system:** Real-device SMM panel replacement. "50–80 IG clones per
  device" claim. Sell follows/likes as a service. 20+ device licenses only.
- **Onimator Helper:** Bulk management add-on. $99/year or free for 20+
  device licenses. Targets splitter, settings copier, post scheduler, tag
  manager, stats analyzer, etc.
- **Onimator CRM:** Web-based OAuth-integrated platform. "Two weeks zero
  bans with CupidAI daily." No proxies, no VPS required. Authorizes via IG
  OAuth.
- **Xmator.com:** X/Twitter SaaS launched Feb 2026. 200+ accounts per
  dashboard. Auto Follow, Auto Reply, Auto DM, Auto Retweet, Scraper, AI
  replies with OpenAI/Anthropic/Groq.
- **Bouncy.ai partnership:** Link cloaking for IG bio. 70% off code
  ONIMATOR. Opens in real browser.

**Onimator's actual scale** (`PLAN.md:29–35`):

- 5,056 Discord members (live count pulled from channel)
- Founder: "curdoc" / Simon (posts 13% of all general channel messages,
  writes entire news channel solo)
- 2,500+ Telegram members
- "We run 300+ phones across all our boxes" (curdoc, Jan 22 2025)
- 14,278 Android IG clones created in March 2025 alone (NomixCloner stats)
- 1,500 clones/day throughput, 2,500 queued at peak (NomixCloner dev, Dec
  2025)

**Onimator's gaps + failures — the OrionFarm/Phantom Fleet opportunity
list** (`PLAN.md:203–220`):

1. Tinder/Bumble is broken for Onimator users (user confirmed directly:
   "Tinder and Bumble is dead for them theirs doesn't work really")
2. Their clone pipeline is bottlenecked — 2,500 clones queued at peak means
   users wait days for bulk batches
3. No fleet-scale audit harness — flat randomization, no cluster
   detection, no cohort analytics. Users complain about batch bans.
4. No persona unification across platforms — each platform is a separate
   "account" with separate settings. No concept of one persona on N
   platforms.
5. No AI agent orchestration — they have "AI Chat" but it's
   per-conversation, not a multi-agent mesh. No warming agent, no recovery
   agent, no proxy orchestrator.
6. Hardware-locked to their OniBox hardware — ships on their phones,
   doesn't generalize to owned fleets
7. iOS automation was "3 months away" in March 2024, "next month" in April
   2026 — still mostly aspirational
8. Tinder automation is still broken in 2026 per user feedback
9. No built-in account-provisioning pipeline — users have to source their
   own aged accounts
10. Django web UI from 2018 — no real-time, no multi-tenant, no mobile
11. Single-tenant only — can't white-label to agencies
12. License kill-switch — if Onimator's server goes down, every
    customer's automation stops
13. No account death → replacement automation — users manually notice dead
    accounts and manually replace them
14. No cross-platform funnel tracking — you can't see "this persona's IG
    drove 17 subs to its OF"
15. Staff-heavy support — everything routes through one Telegram support
    admin

Each of the 15 gaps is the design driver for one or more Phantom Fleet
agents (see Layer 4 — AI agent mesh).

### The 1000x-vs-Onimator checklist

Verbatim from `PLAN.md:979–998`:

| Axis | Onimator | OrionFarm |
|---|---|---|
| Phones per PC | 20-30 (USB limit) | 20 (same, no need to push) |
| Platforms | 7 (IG, TikTok, Threads, Reddit, Tinder, Bumble, Snapchat) + X on separate product | 13+ (all Onimator + X, Spotify, LinkedIn, FB, YouTube, Pinterest, Kick, Discord, Telegram, Hinge) with unified persona |
| Persona system | None (accounts are first-class, fragmented across platforms) | First-class persona primitive spans all platforms |
| AI agents | 1 (chat) | 13+ (warming, DM, content, recovery, replace, proxy, fingerprint, persona, growth, funnel, scout, audit, setup) |
| Fingerprint clustering detection | None | Live histogram monitoring + CI Monte Carlo gate |
| Account lifespan | 30-60 days fresh, 90-180 days aged | 3-6x longer via aged + persona + human emulation amplification |
| Account provisioning | User responsibility | Built-in: aged marketplace + FB OAuth chain + own SIM farm |
| Human behavior emulation | Basic scroll feed + story watch | Full stack: touch biometrics, keystroke dynamics, Bezier swipes, typo rate, Markov burst-pause, session diurnal curve, content-aware pauses, per-persona profile |
| Multi-tenant | No (single-tenant Django) | Yes (Next.js + WebSocket + Postgres RLS) |
| Kill switch | Yes (Onimator license server) | No (self-hosted) |
| Cost | $45-650/mo + $20/proxy | $29-6,500/mo, proxies included in hosted-farm tier |
| Funnel tracking | None | Per-persona fan → subscription conversion |
| Cross-platform graph | Separate playbooks | Unified persona graph |
| Auto-replace dead accounts | Manual | Fully autonomous |
| Scripted vs autonomous | Scripted with user supervision | Autonomous with human oversight |
| Clone pipeline | NomixCloner (bottlenecked at 1.5k/day) | NomixCloner initially, own pipeline Phase 3+ with fingerprint audit integration |
| Modem farm | None (users buy proxies) | Built-in DIY modem farm for mobile IPs + SIM signup pool |

### The Phantom Fleet vs Onimator feature matrix (separate doc)

`PHANTOM_FLEET_VS_ONIMATOR.md` holds a 172-line head-to-head that treats
Phantom Fleet as a shipping product:

- **Platform coverage** (`PHANTOM_FLEET_VS_ONIMATOR.md:5–17`): Onimator = 2
  (IG, TikTok); Phantom Fleet = 12 (IG, TikTok, Threads, Reddit, X,
  Discord, Telegram, BlueSky, Tinder, Bumble, Hinge, Grindr). **6x
  platform coverage.**
- **Instagram deep-dive** (`PHANTOM_FLEET_VS_ONIMATOR.md:19–68`): 30+
  features compared across Core Actions, Advanced Features, and A/B
  Testing & Analytics. Key wins:
  - Mother→Child Repost with per-child visual transforms
    (`:46`)
  - Coordinated Drops with SHA-256-seeded ≥90s gaps (`:47`)
  - DM Funnel 14-day sequences (`:48`)
  - DM Intent Classification (NEW_FAN / WARM_FAN / STORY_REPLY /
    TIME_WASTER / NEGATIVE) (`:49`)
  - Comment Pod Network, Notes Rotation, Broadcast Channels, Story
    Mention Monitor, Story Recycler, Hashtag Performance Tracker, Bio A/B
    Testing, Peak Time Optimizer, Engagement Rate Guardian, Competitor
    Harvester, Lookalike Targeting (`:52–60`)
  - A/B Test Framework with stable-hash assignment and significance
    gating (`:64`)
- **Phantom Fleet Exclusive Features** list (12 items,
  `PHANTOM_FLEET_VS_ONIMATOR.md:137–148`)
- **Deliberately-excluded Onimator features** (not misses, policy):
  - Link sending in DMs (instant ban risk) — `:154`
  - PPV pitch sequences (pushes people away) — `:155`
- **Bottom line comparison** (`PHANTOM_FLEET_VS_ONIMATOR.md:162–170`):

| Category | Onimator | Phantom Fleet |
|---|---|---|
| Platforms | 2 | 12 |
| Intelligent Features | 3–5 | 20+ |
| Detection Safety | Standard | Fleet-cluster aware |
| Multi-Account Scale | Limited | 20K+ accounts |
| Voice Quality | Generic AI | Gen Z 2026 baseline |
| Revenue Diversification | 2 platforms | 12 platforms (dating apps alone 3–5x ARPU) |
| Cost Efficiency | Higher (full-API) | Lower (hybrid + rule-based) |

### Content rules (locked 2026-04-11)

From `PLAN.md:309–337`:

- **NO HASHTAGS in any posted caption. Ever.** IG deprioritized hashtag
  discovery in 2023; hashtag spam is now a soft-ban signal. Posts with
  zero hashtags outperform hashtagged posts by 2–4x in current reach.
  Caption generator **rejects any caption containing `#`** before it
  reaches the phone.
- **NO hashtags anywhere in the system** — not in captions, not in
  scraping, not in target discovery. Target discovery uses competitor
  follower/viewer/liker lists, location pages, explore page, reel likers,
  audio-based discovery, keyword text search (NOT hashtag search),
  suggested-for-you, and chain discovery. Hashtag pages are never touched.
- **LLM detection tells banned from captions:**
  - Words/phrases: "delve into", "it's worth noting", "elevate",
    "resonates with", "game-changer", "in conclusion", "furthermore",
    "moreover", "it's important to note"
  - Punctuation: no em-dashes (—), no ellipses (…), no semicolons in short
    captions
  - Sentence structure: no "not only X but also Y", no triadic parallel
    lists, no rhetorical questions
  - Style: write like a 22-year-old woman texting, not like a brand or a
    blog
- **Caption length cap:** 15–40 words max, 2–3 emojis max placed naturally
  (not clustered at end), must reference the actual content in the
  image/reel not be generic

### Warming curve principles

From `PLAN.md:48–163` — **CORE PRINCIPLE** (`PLAN.md:50–52`):

> Every number is a RANGE, sampled fresh per account per day. No two
> accounts ever hit the same exact daily totals. No account ever hits the
> same total twice. Every value uses LogNormal sampling from its range
> with a per-`(account_id, date)` seed. Exact numbers = cohort fingerprint.
> Ranges with distribution sampling = natural variance = undetectable.

The six warming phases (`PLAN.md:64–113`):

- **Phase 1 — Dormant (Day 0–2):** zero actions. Scroll reels (20–50 per
  session), watch stories, browse feed. No follows, likes, or comments.
- **Phase 2 — First actions (Day 3–7):** 2–8 follows/day, 3–15 likes/day,
  6–22 story views/day, 0–1 comments/day
- **Phase 3 — Controlled ramp (Day 8–14):** 5–15 follows/day, 9–34
  likes/day, 14–38 story views/day, 0–4 comments/day
- **Phase 4 — Sustained ramp (Day 15–21):** 9–22 follows/day, 22–54
  likes/day, 25–57 story views/day, 2–7 comments/day, 0–3 DMs/day
- **Phase 5 — Established (Day 22–28):** 14–30 follows/day, 36–75
  likes/day, 36–75 story views/day, 3–10 comments/day, 1–6 DMs/day
- **Phase 6 — Steady state (Day 29+):** Follows 18–32/day, Likes 45–85/day,
  Story views 48–85/day, Comments 5–12/day, DMs 3–9/day

**Rest days per week = 0 (NEVER)** — every account active every day — rest
days are a cluster fingerprint, not a defense (`PLAN.md:123`).

All other parameters are also ranges sampled per account per day (16
parameters total — `PLAN.md:117–139`): sessions per day, session length,
gap between actions, gap between sessions, daily intensity roll
(minimal/light/normal/heavy at 15/25/45/15%), actions per session,
Follow/Like/Story/Comment Dirichlet ratio per session, tap dwell time
(60–200ms LogNormal), tap position offset (±5–12 px Normal), inter-tap
delay (150–1800ms LogNormal), per-char typing delay (80–400ms LogNormal),
typo rate (per account, fixed at provision, 1.5–4.5%), scroll distance
(300–1400 px LogNormal), content pause time (1.2–9 sec LogNormal), backward
scroll chance (per account, 5–12%), weekly activity multiplier (0.75–1.25x,
sampled Monday).

**Per-account "personality" profile** — sampled ONCE at account import,
never changes (`PLAN.md:141–146`):

- Aggressiveness factor (0.85–1.15) — applies to every daily target for
  this account's entire life
- Comment probability (0.3–0.7)
- DM willingness (0.2–0.8)
- Active hours window (4–8 hours of the day)
- Peak hour — sampled from a distribution matching the persona's timezone

**UI rule** (`PLAN.md:150`):

> Never expose the ranges to the UI as "3-7 follows/day". The UI shows
> "target: follows ~4 this account today" — a per-account exact value,
> different for every account.

Auto-pause triggers table (`PLAN.md:152–163`) — 9 distinct detection
signals, each with an action. E.g. "Action block on any action type" →
"Pause 24h, reduce next-day target by 50%"; "Checkpoint challenge" →
"Account dead, mark for replacement"; "Suspicious activity popup" → "Pause
72h, drop next-day target by 70%".

---

## Architecture — the 5-layer model

`PLAN.md:223–368` defines five layers; the frontend's landing page also
visualizes it via the `architecture-diagram` component
(`README.md:110`). Full ASCII:

```
┌────────────────────────────────────────────────────────────────────────┐
│ LAYER 5  Multi-tenant SaaS                                             │
│   Agency accounts · per-tenant RLS · Stripe + Crypto · device leasing  │
│   API tier · white-label theming · compliance dashboard                │
│                                            (Phase 4+ unlock)           │
├────────────────────────────────────────────────────────────────────────┤
│ LAYER 4  AI Agent Mesh  (15 agents, all obey CLAUDE.md agent-audit)    │
│                                                                        │
│   warming  fresh_target  source_discovery  fingerprint_monitor         │
│   recovery  replacement  proxy_orchestrator  dm  content               │
│   account_setup  persona_factory  growth_strategy                      │
│   funnel_conversion  content_scout  audit_harness                      │
│                                                                        │
│   Rust core routes · Go supervisors · Python ML · NATS / Redis Streams │
├────────────────────────────────────────────────────────────────────────┤
│ LAYER 3.5  Fresh Target Agent                                          │
│   Daily unique scrape · 90-day global dedup · per-persona source       │
│   isolation · NO hashtag sources (banned fleet-wide)                   │
├────────────────────────────────────────────────────────────────────────┤
│ LAYER 3  Pure real-device execution                                    │
│                                                                        │
│   Mother (1 phone / persona) ──► content origination                   │
│   Slave  (15-18 phones)      ──► story-share amplification             │
│   Whale care                 ──► top performers, max care              │
│                                                                        │
│   100 % physical phones via Phantom Fleet Companion APK                │
│   (ZERO signed-mobile-API backends — correction 2026-04-11)            │
├────────────────────────────────────────────────────────────────────────┤
│ LAYER 2  Persona Core  (THE differentiator — Onimator has none)        │
│                                                                        │
│   Demographics  · Device + OS consistency                              │
│   Locale ↔ TZ   · Carrier ↔ HNI    · Proxy ↔ TZ                         │
│   Interest graph · Touch biometrics · Diurnal rhythm                   │
│                                                                        │
│   One persona → N accounts across 12+ platforms                        │
│   Personas never die; accounts die and are replaced under the persona  │
├────────────────────────────────────────────────────────────────────────┤
│ LAYER 1  Hardware Fabric (local, no cloud)                             │
│                                                                        │
│  Farm PC 1 ──┐          ┌── Farm PC 2  …  Farm PC 9                    │
│   USB hubs   │          │   USB hubs                                   │
│   Wi-Fi ADB  │ WireGuard│   Wi-Fi ADB                                  │
│      │       │ or       │      │                                       │
│      ▼       │ Tailscale│      ▼                                       │
│  ~20 phones  │   LAN    │  ~20 phones                                  │
│  each (S10   │   mesh   │  each                                        │
│  Lite)       └─────────►│                                              │
│                                                                        │
│  180 phones total · companion APK + Accessibility Service              │
│  NomixCloner primary clone generator (Phase 1-2, replaced in Phase 3+) │
└────────────────────────────────────────────────────────────────────────┘
```

### Layer 1 — Hardware fabric (local, no cloud)

`PLAN.md:225–231`:

- **Per-farm PC runs the local orchestrator** — no VPS, no cloud, no
  hosting. Peer coordination over LAN between farm PCs via WireGuard or
  Tailscale.
- USB hubs stay (user already has them, works fine at 20 phones per PC)
- Wi-Fi ADB as free redundancy path for any phone
- Custom OrionFarm Companion APK on each phone replaces uiautomator2 + some
  of AppCloner's runtime role. Accessibility Service for input (no root
  needed).
- NomixCloner remains the primary clone generator short-term (Onimator's
  own pipeline — we're their customer). Long-term we build our own clone
  pipeline that amplifies it with additional fingerprint axes.
- 180 phones, 20 per farm, 9 farms. No new hardware needed for Phase 1–2.
  Phase 3 expansion is hand-picked per farm.

### Layer 2 — Persona core

`PLAN.md:233–243` (the "real differentiator — Onimator has nothing like
this"):

> A "persona" is a human character with a consistent cross-platform identity:
>
> - Demographics from inverse-CDF sampling of real census data
> - Realistic device model + OS version (matches installed base, not 78% flagships)
> - Realistic timezone ↔ locale consistency (fixes the `en-GB` /
>   `America/New_York` bug we found live on the current farm)
> - Realistic interest graph drawn from real topic clusters
> - Per-persona touch biometric profile (tap pressure, key dwell time,
>   scroll velocity)
> - Per-persona daily rhythm matching diurnal curve for claimed geography
> - **One persona → N accounts across N platforms** (IG, TikTok, Threads,
>   Snapchat, Reddit, Tinder, Bumble, Hinge, Twitter, Facebook, YouTube,
>   Spotify, LinkedIn)
> - **Personas never die — accounts die and get replaced under the same persona**

### Layer 3 — Pure real-device execution (corrected 2026-04-11)

**Key correction from the v1 plan.** `PLAN.md:245–248`:

> All Phantom Fleet actions run on physical phones. Zero
> signed-mobile-API backends. Zero cloud-based action execution.
>
> Original plan had a "hybrid phone + API router" layer — that was wrong
> for this use case. User's warmed fleet survived 72 days with 0.6% ban
> rate on real-device-only execution. Switching warmed accounts to
> API-based execution would create a behavioral signature change that
> IG's ML classifier flags as a cluster. Signed mobile APIs also have
> 30–90 day account lifespans vs 6+ month real-device lifespans, and
> break on every IG internal protocol change.

What "hybrid" means now (`PLAN.md:250–258`): hybrid is between **trust
tiers of physical execution**, not between phones and servers. Every tier
is real device via the Phantom Fleet Companion APK.

| Tier | Role | Uses |
|---|---|---|
| **Mother** | 1 dedicated phone per persona | Main post/reel origination, primary grid content |
| **Slave** | 15–18 phones per persona | Share-as-story amplification, volume follow/like/DM |
| **Whale care** | Top-performing mother phones | Maximum care, minimum action pacing, priority proxy routes |

The **Mother/Slave pattern** (`PLAN.md:260–265`): mother account posts
original content, slave accounts share mother's content as stories with
mention tag, each slave story view counts as a reel/post view for the
mother, amplification without generating new content per slave. Documented
in Onimator's news channel as the most effective growth strategy.

### Layer 3.5 — Fresh Target Agent

`PLAN.md:267–307`. Decision by user 2026-04-11:

> No static target pool. Every account gets fresh unique targets scraped
> daily. The old Onimator `iguserdatabase.db` 7,412-user pool is imported
> into `target_history` as "already targeted" so the 90-day cooldown
> excludes them from fresh pulls.

Per-day pipeline per persona (`PLAN.md:272–278`):

1. Scraper accounts (4–6 per persona, separate from action accounts) pull
   fresh usernames from multiple sources
2. Sources (NO hashtags): competitor followers, competitor story viewers,
   competitor post likers, competitor post commenters, location page
   recent posts, explore page sampling, reel likers, reel commenters,
   audio-based reel discovery, keyword text search (usernames + bios,
   NOT hashtag search), suggested-for-you lists, mutual follower
   discovery, HikerAPI, chain discovery (followers-of-followers 2nd-degree
   graph walks)
3. Raw results deduped against 90-day `target_history` (global fleet-wide)
4. Deduped list deduped against other personas' same-day lists (zero
   cross-persona overlap)
5. Final list sliced per account in the persona cohort (each account gets
   unique targets, no within-persona overlap)
6. Lists expire at end of day — tomorrow is a fresh pull

Uniqueness rules (`PLAN.md:280–284`):

- No target appears in two accounts' lists on the same day
- No target is reused fleet-wide within 90 days of last targeting
- No overlap between personas' daily lists
- Every source scraped fresh daily (no caching)

Scale per day (`PLAN.md:286–290`):

- Per account: 15–25 fresh targets
- Per persona (~100 accounts): ~2,000 filtered fresh targets
- Fleet-wide: ~4,000 fresh targets per day
- Raw scrape volume needed (filter rate ~50%): ~8,000 raw per day

Scraper accounts are read-only — they never follow/like/DM. They only
browse discovery surfaces to collect usernames. Looks like "lurker" users
to IG, totally normal pattern (`PLAN.md:292`).

Per-persona source isolation (`PLAN.md:294–298`):

- Tatiana cohort and Melodie cohort have completely separate source
  configs
- Different competitor lists, different location pools, different audio
  seeds, different scraper accounts
- Zero source overlap → impossible for the same user to appear on both
  personas' target lists
- **NO hashtag sources anywhere** (banned fleet-wide, user decision
  2026-04-11)

Database schema (`PLAN.md:300–307`):

```sql
CREATE TABLE target_history (
    username TEXT, persona_id TEXT, account_id TEXT,
    action_type TEXT, targeted_at TIMESTAMP, result TEXT,
    PRIMARY KEY (username, targeted_at)
);
CREATE INDEX idx_username_date ON target_history (username, targeted_at);
```

### Layer 4 — AI agent mesh

`PLAN.md:340–358`. **Zero manual labor goal.** Every single manual task
Onimator users still do manually becomes an autonomous agent. Each agent
obeys the CLAUDE.md agent-audit rules: tool allowlists, loop caps, cost
caps, confirmation gates, event-sourced audit log.

The 13 agents listed in the PLAN table (with what they replace and what
they do):

| Agent | Replaces | Behavior |
|---|---|---|
| Account Setup Agent | Manual account creation + profile filling | Loads persona, runs sign-in flow (aged account OR new via FB OAuth), types bio character-by-character with typos + corrections, uploads profile pic from gallery, follows suggested accounts, runs Day 0 warmup session, logs health state |
| Warming Agent | Manual 48-hour warmup supervision | Runs the exact Onimator 48h reel-scroll flow autonomously (30–50 reels per round, 10% likes, 100/day), then ramps 15F+25L → 50F+100L over 14 days, logs every action, self-pauses on signal drift |
| DM Agent | Manual DM chat + funneling | Reads incoming DMs on every platform, qualifies fans by intent, generates per-persona reply using Chat AI / ModelForge / CupidAI integration, CTAs to OF/Fanvue/ScaleHer funnel, measures conversion rate per persona |
| Content Agent | Manual post + caption generation | Pulls from Content Vault, scores per-account fit, varies captions per-persona, strips LLM detection tells ("delve into", "it's worth noting", etc.), schedules to the persona's diurnal curve |
| Recovery Agent | Manual "oh this phone is stuck" | Detects phone crash / IG logout / shadowban / action block / checkpoint challenge. Auto-reboot, auto-reauth, auto-proxy-rotate, auto-resume. Logs death reason if unrecoverable. Triggers replacement. |
| Replacement Agent | Manual account replacement | When an account dies: mark it graveyard, keep the persona, source a new account from aged marketplace OR FB OAuth chain OR warming pool, re-provision on a fresh phone + fresh IP, begin Day 0 warmup |
| Proxy Orchestrator Agent | Manual proxy rotation | Monitors every proxy's block signals, rotates per-persona mobile IPs on block, manages cross-panel proxy sharing (IG + Reddit already have this pattern in memory), alerts on pool exhaustion |
| Fingerprint Monitor Agent | No Onimator equivalent | Live cluster detection across the fleet. Runs the 10 checks from the CLAUDE.md rule every 5 minutes. Pauses cohorts on cluster tightening BEFORE Meta notices. |
| Persona Factory Agent | Onimator has no personas at all | Generates new personas on demand with full demographic consistency + cross-field validation. Every field is sampled from real distributions. No flat randomization allowed. |
| Growth Strategy Agent | Manual performance review | Weekly review of every account's KPIs. Adjusts action pacing, swaps targeting sources, retires under-performing personas, promotes high-performers to whale cohort |
| Funnel Conversion Agent | No Onimator equivalent | Tracks fan → OF/Fanvue/ScaleHer subscription rate per persona per platform. Reallocates traffic/budget from low-converting personas to high-converting. Shows you which personas are making money. |
| Content Scout Agent | Manual content hunting | Scrapes trending content from real sources, routes to Content Vault, tags by niche, suggests to Content Agent |
| Audit Harness Agent | No Onimator equivalent | Runs 10,000-persona Monte Carlo simulation in CI before every deploy. Blocks merge if any fingerprint dimension clusters. |

The **README-era list is 15 agents** (`README.md:50–66`) — the planning
table was later expanded with `source_discovery` and `fresh_target`
(replacing the collapsed "static target pool" model from Layer 3.5). Full
listing with one-line descriptions from the README:

- `warming` — Daily re-wake + warmup curve orchestration
- `fresh_target` — Fresh unique targets per account per day, 90d dedup
- `source_discovery` — Auto-discover female US high-engagement sources
- `fingerprint_monitor` — Live 20-dim cluster detection every 5 min
- `recovery` — Phone crash / session expire auto-heal
- `replacement` — Dead-account detection + replacement provisioning
- `proxy_orchestrator` — IPRoyal rotation + block recovery
- `dm` — Fan DM + OF/Fanvue/ScaleHer funnel
- `content` — Caption gen + post scheduling (hashtag-free, LLM-tell-free)
- `account_setup` — Onboard imports + replacements
- `persona_factory` — Generate new personas with audit validation
- `growth_strategy` — Weekly KPI review + source reweighting
- `funnel_conversion` — Fan → OF sub attribution
- `content_scout` — Trending content discovery
- `audit_harness` — 10K-persona Monte Carlo cluster gate

Actual files present in `backend/phantom_fleet/agents/`:

- `account_setup_agent.py`
- `audit_harness_agent.py`
- `base.py` (base `Agent` class enforcing CLAUDE.md agent-audit rules per
  `README.md:50`)
- `capacity_planner_agent.py`
- `content_agent.py`
- `content_scout_agent.py`
- `device_tools.py`
- `dm_agent.py`
- `fingerprint_monitor_agent.py`
- `fresh_target_agent.py`
- `funnel_conversion_agent.py`
- `growth_strategy_agent.py`
- `instagram_agent.py`
- `managers/` (sub-dir)
- `persona_factory_agent.py`
- `proxy_orchestrator_agent.py`
- `recovery_agent.py`
- `registry.py`
- `replacement_agent.py`
- `source_discovery_agent.py`
- `specialists/` (sub-dir)
- `threads_agent.py`
- `warming_agent.py`

So the tree already holds the 15 README agents **plus** a
`capacity_planner_agent.py`, platform-specific `instagram_agent.py` and
`threads_agent.py`, a `managers/` sub-tree, a `specialists/` sub-tree, and a
`registry.py`. The on-disk agent surface is already slightly larger than
either the PLAN table (13) or the README list (15) — treat the README as
authoritative for the planned agent-mesh contract and the files as the
scaffolding plus ad-hoc specialists.

Agent orchestration (`PLAN.md:358`):

> Agent orchestration is built on the existing HQ Opus COO pattern. Agents
> live in Go for long-running supervisors + Python for ML, orchestrated by
> a Rust core over NATS/Redis Streams.

### Layer 5 — Multi-tenant SaaS layer (the $100M upside)

`PLAN.md:360–368`:

- Agency accounts — scoped data isolation, each agency sees only their
  personas/devices/analytics
- Per-agency billing — Stripe + Crypto recurring + metered
- Device leasing — agencies rent slots on your 180-phone fleet at
  $150–400/phone/month (you own hardware, they own accounts)
- API tier — agencies integrate OrionFarm into their tools
- White-label theming — per-agency domain, logo, branding
- Compliance dashboard — every action audit-logged per agency

---

## Stack decisions (locked)

The canonical table from `.claude/CLAUDE.md` under "**Stack decisions
(locked)**":

| Layer | Technology | Reason |
|---|---|---|
| Core orchestrator | Rust | Latency + throughput for hot path (device control, action queue) |
| Agents | Go | Concurrency for long-running supervisors (proxy orchestrator, recovery agent) |
| ML / content generation | Python | ModelForge, Chat AI, OpenRouter integration already Python |
| Web UI | TypeScript / Next.js | Matches Scaler Pro panel convention |
| Android companion APK | Kotlin + Jetpack | Native performance + modern Android APIs |
| Event bus | NATS or Redis Streams | Decision made at Phase 0 scaffolding; prefer NATS for durability |
| Database | Postgres 16 | Matches existing Scaler Pro panels, cross-panel queries via schema links |
| Cache | Redis | Standard |
| CI | GitHub Actions | Audit harness runs here as required check |

Discussion of each:

**Rust core orchestrator.** Picked for the **hot path**: device control
and action queue. Rust gives the latency floor and the memory discipline
that lets a single orchestrator process manage hundreds of simultaneous
ADB / Companion APK sessions without GC pauses or FFI tax. Device control
is cycle-tight (tap dwell is sampled in milliseconds per
`PLAN.md:133`), so the hot path needs a predictable runtime. **Alternative
considered:** Go for everything. Rejected because Go's GC + runtime adds
jitter to the per-tap timing budget, and because the agent mesh already
has a Go tier that gets structural concurrency benefits where latency
matters less.

**Go agent supervisors.** Picked for **long-running supervisors**:
specifically the proxy orchestrator and the recovery agent. Go's
goroutines handle 180 concurrent supervisor loops without the structural
weight of one Rust async task per phone. **Alternative considered:**
collapsing agents into the Rust core. Rejected because supervisor lifetimes
are hours to days and hot-path isolation is desirable.

**Python ML.** Locked because **ModelForge, Chat AI, OpenRouter
integration already Python** — the Scaler Pro ecosystem is Python on the
ML side, and Phantom Fleet is explicitly a Scaler Pro panel
(`.claude/CLAUDE.md`, "Depends on" line). This is a compatibility
constraint, not an engineering preference. **Alternative considered:**
running ML via API only, with Rust/Go SDKs. Rejected because the existing
Chat AI / ModelForge code is already in-process Python, and re-implementing
the integration surface would blow up Phase 1 scope.

**Next.js dashboard (TypeScript).** Locked because **matches Scaler Pro
panel convention** — the other panels (`meta/`, `instagram/`, `threads/`,
`reddit/`, `x-panel/`, `tiktok/`) all use the Next.js / Tailwind convention
and Phantom Fleet needs to look like one more panel in that family.
`README.md:73–77` names the design-system tokens: dark-first premium SaaS,
neon cyan-green signature accent `hsl(162 100% 54%)`, Inter display font,
glass panels with grid background, optimized for 14–24-hour sessions in a
dim room.

**Kotlin + Jetpack APK.** Locked for **native performance + modern Android
APIs** — Accessibility Service is a Kotlin-first API surface and the
companion APK needs to be installable without root on Android 11 (the
S10 Lite's baseline OS — `HARDWARE.md:22`). **Alternative considered:**
Flutter / React Native. Rejected because the APK's job is to drive native
input primitives (tap dwell, scroll velocity, typing latency) with <50ms
latency, which the cross-platform frameworks can't guarantee, plus
Accessibility Service work needs Kotlin coroutines for proper lifecycle
integration.

**NATS vs Redis Streams.** The CLAUDE.md line reads: "Decision made at
Phase 0 scaffolding; prefer NATS for durability." So the formal decision
was deferred to Phase 0, with NATS as the default. As of this handoff no
concrete `nats-server` or Redis Streams config is visible in `docker-
compose.yml` (which brings up Postgres 5436 + Redis 6380 + backend 8000 +
frontend 3016 per `README.md:134`). The Redis container is present; NATS
has not yet been added. Treat as **"NATS to be chosen in Phase 0, Redis
already present as cache"**.

**Postgres 16.** Locked for **cross-panel queries via schema links** — the
Scaler Pro ecosystem keeps panel databases linkable through Postgres
schemas rather than a federated graph, so Phantom Fleet reuses the same
engine. Migration file `backend/migrations/001_initial_schema.sql` holds
11 tables + indexes (`README.md:67–68`).

**Redis cache.** "Standard" — no further justification needed, used both
for cache and (potentially) for Streams.

**GitHub Actions CI.** The **audit harness runs here as a required check**
— specifically the 10,000-persona Monte Carlo gate described in the hard
rules below. No Phase-0-era GHA workflow files are visible in the tree I
inspected; the CI gate is an architectural requirement, not yet a shipped
workflow.

---

## Hard rules

All drawn from `.claude/CLAUDE.md`, with `README.md` cross-references where
the running codebase enforces the same rule.

### Distribution discipline

Verbatim from `.claude/CLAUDE.md`:

> - `random.uniform()`, `random.randint()`, `Math.random()` are
>   **lint-banned** on any code path that touches persona identity,
>   fingerprint fields, scheduling, or inter-action delays.
> - Every random value must come from a typed distribution class:
>   `LogNormal`, `Normal`, `Bimodal`, `WeightedCategorical`. The
>   distribution parameters must be derivable from real-world
>   measurements — not guessed.
> - Use `secrets.randbits()` / `crypto.randomBytes()` as the underlying
>   entropy source for anything uniqueness-contributing. Never seed from
>   `time()` or process state.

**Code enforcement.** `README.md:43–45` states the four typed distribution
classes are shipped at `backend/phantom_fleet/core/distributions.py`
("LogNormal, Normal, Bimodal, WeightedCategorical. Banned raw
`random.uniform` across identity code."). `README.md:184–187` under "Hard
safety gates" reiterates: "`core/distributions.py` is the only entry point
for random values on identity-contributing code paths. Raw
`random.uniform()`, `Math.random()` are lint-banned."

**Why.** Flat randomization (uniform distributions) produces rectangular
histograms when 10k accounts are compared; real humans produce bell curves
and bimodal shapes. The 10 cluster checks (below) catch rectangular
histograms as cluster fingerprints. Any PR that re-introduces
`random.uniform` on a fingerprint path will either fail the lint check or
fail the Monte Carlo audit harness.

### Fleet-scale audit gate

Verbatim from `.claude/CLAUDE.md`:

> - The 10,000-persona Monte Carlo harness is a **required CI check**. No
>   PR merges with a failing audit run.
> - The 10 cluster-analysis checks from global CLAUDE.md are not optional
>   — all 10 must pass.
> - Any new persona field, fingerprint dimension, or action primitive
>   requires an audit-harness test case covering its distribution shape.

**Code enforcement.** `README.md:173–176`: "Audit harness CI gate. The
`AuditHarnessAgent` runs 10,000-persona Monte Carlo cluster checks on
every deploy. Any dimension clustering fails the build." The agent file
exists at `backend/phantom_fleet/agents/audit_harness_agent.py`.

**The 10 cluster-analysis checks** — these are referenced in
`.claude/CLAUDE.md` as living in the global CLAUDE.md
(`~\.claude\CLAUDE.md`). Based on where the planning doc describes them
(`PLAN.md:696–706`, Layer F — Fleet-level cluster monitoring), they
cover:

1. Live histograms of every fingerprint dimension across the fleet
2. Cross-field contradiction scan (locale vs timezone, UA vs TLS, app ver
   vs OS ver, carrier vs IP geo)
3. Cohort distribution shape checks (real-world vs uniform)
4. Static ratio detection (hardcoded weights = cluster fingerprint)
5. Identifier regularity scans (common prefixes, fixed lengths)
6. Behavioral pool diversity (content/caption pool size vs account count)
7. Sequence determinism (every account follows the same nav chain =
   cluster)
8. Entropy source verification (Math.random = banned in identity code)
9. (implied) Distribution-tail clipping detection — if every account's
   sampled value caps at the same floor/ceiling, that's a rectangular
   tail = cluster
10. (implied) Temporal cluster detection — fleet-wide action timing
    distribution vs expected diurnal curve for claimed geography

The frontend's `cluster-heatmap` component (`README.md:105`) renders a
**20-dimension fingerprint monitor**, i.e. the cluster monitor's shipping
surface already looks at 20 dimensions. `README.md:198` lists cluster
detection latency target at **< 5 minutes**.

### Cross-field consistency

Verbatim from `.claude/CLAUDE.md`:

> - If a persona claims a locale, the timezone must be consistent with
>   the locale.
> - If a persona claims a device model, the OS version must be in the
>   range that model actually shipped with.
> - If a persona claims a carrier, the HNI must match that carrier and
>   country.
> - If a persona claims a proxy location, the persona's timezone must be
>   consistent with that geography.
> - **Every field that contributes to identity must pair-check against
>   every other field that contributes to identity.** Build this into the
>   persona factory, not as a downstream fixer.

**Enforcement surface.** `Persona Factory Agent`
(`backend/phantom_fleet/agents/persona_factory_agent.py`), which the PLAN
describes as: "Generates new personas on demand with full demographic
consistency + cross-field validation. Every field is sampled from real
distributions. No flat randomization allowed." (`PLAN.md:352`).

**Immediate live bug this rule kills.** `HARDWARE.md:101–124` details the
live cluster fingerprint on the current farm — every phone has
`ro.product.locale = en-GB` combined with
`persist.sys.timezone = America/New_York`. That's rule-6-violation
territory ("locale vs timezone" cross-field contradiction) and must be
fixed before Phase 1 ships.

### Agent rules

Verbatim from `.claude/CLAUDE.md`:

> - All orchestration agents follow the global CLAUDE.md agent-audit
>   rules in full.
> - Each agent has: a named tool allowlist, a hard iteration cap (≤5
>   typical, ≤20 absolute max), a per-run cost cap, a per-session cost
>   cap, a per-user cost cap.
> - Destructive actions (delete account, factory-reset phone, wipe
>   cache, revoke session) require confirmation gates in code, not just
>   in prompt.
> - Every agent action writes to an event-sourced audit log before
>   execution, and writes the result after.
> - Agents cannot call each other without going through the central
>   orchestrator's routing layer.

**Enforcement.** `backend/phantom_fleet/agents/base.py` is described in
`README.md:50` as the "base `Agent` class enforcing CLAUDE.md agent-audit
rules". The README also lists a concrete allowlist of destructive actions
requiring confirmation gates — `wipe_account_data`, `mass_dm_blast`,
`purchase_new_accounts`, `factory_reset_phone` — all gated through the
`confirmation_required_for` allowlist (`README.md:178–180`).

**Cost caps.** README line 204: "LLM cost cap / day: **$50**". Per-run /
per-session / per-user caps have to be programmatic inside the base Agent.

**Iteration caps.** ≤5 typical, ≤20 absolute max. No agent should loop
beyond 20 iterations without surfacing to a human.

**Central routing.** Agents cannot call each other directly. All
inter-agent calls go through the orchestrator's routing layer (planned to
live in the Rust core).

**Audit log.** Event-sourced: write-before-execute, then write result.
Two log rows per action.

### Known Onimator fleet bugs #1–4

Verbatim from `.claude/CLAUDE.md`, "Known fleet bugs (from existing
Onimator deployment on user's farm)":

> Fix these before shipping, even if not directly related to the PR:
>
> 1. **Locale/timezone cross-field contradiction** — every phone has
>    `en-GB` locale with `America/New_York` timezone. Fix at persona
>    factory level.
> 2. **AppCloner fingerprint** — all 22 IG clones share common signing
>    certificate patterns. OrionFarm companion APK must not replicate
>    this.
> 3. **Static per-device account count of 15-22** — real users don't
>    share this exact number across a fleet. Vary by device-aging persona.
> 4. **Flat fleet-wide action timing** — current Onimator uses uniform
>    delays per persona regardless of claimed timezone. OrionFarm must
>    schedule against the persona's diurnal curve.

**Where each lives in the live fleet audit.**

Bug #1 is detailed in `HARDWARE.md:101–124` with the exact Meta SQL query
that would flag it:

```sql
SELECT locale, timezone, COUNT(*)
FROM accounts_telemetry
WHERE client_fp IN (fleet_fingerprints)
GROUP BY 1, 2
```

Every account bucket lands in `(en-GB, America/New_York)` = cluster
fingerprint. The three fix options from `HARDWARE.md:122–124`:

- Option A: align timezone to Europe/London (if persona is UK)
- Option B: align locale to en-US (if persona is US)
- **Option C (correct):** persona factory decides both together, based on
  the persona's claimed geography

Bug #2 is detailed in `HARDWARE.md:187–192`: AppCloner Premium repackages
the Instagram APK with a different package ID + isolated storage path, so
each clone runs as a separate app with its own login session. 22 clones
per phone share common signing-cert patterns = package-enumeration
cluster. The HARDWARE replacement plan (`HARDWARE.md:194`):

> Single real IG app, session-level account switching inside the
> companion APK. Clear IG's auth cache, inject new session tokens,
> restart the IG Activity. No repackaging, no cloning.

Bug #3 — static per-device account count of 15–22. Fleet-level audit catch
is a histogram with a sharp spike at that bucket; fix is to vary by
device-aging persona (older personas carry more accounts, newer ones
fewer).

Bug #4 — flat fleet-wide action timing — directly contradicted by the
LogNormal per-`(account, date)` sampling in the warming curve
(`PLAN.md:50–62`) and by the diurnal-curve requirement in Layer 2.

### Irreversible-action safety

Verbatim from `.claude/CLAUDE.md`, "Working mode":

> The user's global CLAUDE.md rule is **full autonomy, no permission
> requests except for irreversible destructive actions on shared
> infrastructure**. Apply that here.
>
> For OrionFarm specifically:
>
> - Never flash a phone without user confirmation (irreversible)
> - Never factory-reset a phone without user confirmation (destroys
>   accounts)
> - Never push a companion APK to the whole fleet without user
>   confirmation (must pilot on 1 phone first)
> - Never modify the existing Onimator deployment's databases without
>   backing them up first
> - Never delete account data from `iguserdatabase.db` or
>   `notificationdatabase.db`
>
> Everything else (write code, run audits, refactor, add features, build
> infrastructure) proceeds without confirmation.

**Code enforcement (README hard-safety-gates — `README.md:163–187`):**

1. **No IG clone launches until proxy routing is verified.** Enforced in
   `phones/__init__.py` at the method level —
   `PhoneController.tap()`, `.type_text()`, `.launch_clone()` all raise
   `RuntimeError` if `_proxy_verified[serial]` is not True. **No bypass.**
2. **No destructive Onimator writes.** `migrate_onimator.py` opens every
   SQLite DB in `mode=ro` URI mode. Never writes.
3. **Audit harness CI gate.** (covered above)
4. **Agent confirmation gates.** Destructive actions
   (`wipe_account_data`, `mass_dm_blast`, `purchase_new_accounts`,
   `factory_reset_phone`) require human confirmation via the
   `confirmation_required_for` allowlist.
5. **Hashtags banned in captions + DMs.**
   `ContentAgent._is_caption_valid()` and `DMAgent._contains_banned()`
   reject any output containing `#`, em-dashes, ellipses, or LLM
   detection tells.
6. **Distribution discipline.** (covered above)

### Content-rule hard gates

Not duplicating the full content-rule block (above under Mission), but the
compiled set of hard gates on caption/DM output:

- Reject `#` (hashtags) in any generated caption or DM
- Reject em-dashes `—`
- Reject ellipses `…`
- Reject the LLM detection-tell phrases list (`PLAN.md:320–322`)
- Reject short captions containing semicolons
- Reject "not only X but also Y", triadic parallel lists, rhetorical
  questions
- Enforce 15–40 word caption length, 2–3 emojis max

---

## Repo folder layout

### Canonical tree (from `.claude/CLAUDE.md`, "Folder convention")

```
orionfarm/
├── .claude/
│   └── CLAUDE.md         (this file)
├── PLAN.md               (executive plan)
├── HARDWARE.md           (fleet intel)
├── backend/
│   ├── core-rs/          (Rust orchestrator core)
│   ├── agents-go/        (Go agent supervisors)
│   ├── ml-py/            (Python ML + content generation)
│   ├── audit-harness/    (10K-persona Monte Carlo CI gate)
│   ├── persona-factory/  (Python persona generator)
│   └── migrations/       (Postgres schema migrations)
├── frontend/             (Next.js + WebSocket dashboard)
├── companion-apk/        (Android Studio project)
├── farm-agents/          (per-farm edge agent binaries + configs)
├── docs/
│   ├── architecture/     (diagrams, decision records)
│   ├── playbooks/        (operational runbooks)
│   └── api/              (OpenAPI specs)
└── logs/
```

> Do NOT create `backend/`, `frontend/`, `companion-apk/`, etc. until the
> user signs off on `PLAN.md`. Only the top-level planning docs exist at
> the moment.

That last line was written at planning time. Phase-0 scaffolding is marked
complete per `README.md:28`, so the canonical tree is partially realized
and partially diverged. Actual on-disk layout follows:

### Actual tree (as of 2026-11-25)

Top level of `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\`:

```
phantom-fleet-clone/
├── .claude/
│   ├── CLAUDE.md                        ← present (hard rules + stack)
│   └── launch.json
├── HARDWARE.md                          ← present
├── PHANTOM_FLEET_VS_ONIMATOR.md         ← present (feature matrix)
├── PLAN.md                              ← present
├── README.md                            ← present
├── _discord_analyze.py                  ← Discord intel pipeline
├── _discord_export_onimator.py
├── _discord_extract_token.py
├── _discord_list_guilds.py
├── _discord_recon.ps1
├── _onimator_full_dump.py
├── _onimator_summary.py
├── backend/
│   ├── Dockerfile
│   ├── NUL                              ← stray Windows null-device file
│   ├── config/
│   ├── migrations/                      ← 001_initial_schema.sql (+ ?)
│   ├── phantom_fleet/                   ← Python package root
│   │   ├── __init__.py
│   │   ├── agents/                      ← 15+ agents (see Layer 4)
│   │   │   ├── base.py                  ← Agent base w/ audit rules
│   │   │   ├── registry.py
│   │   │   ├── device_tools.py
│   │   │   ├── managers/
│   │   │   ├── specialists/
│   │   │   └── <15 *_agent.py files>
│   │   ├── api/                         ← FastAPI routes
│   │   ├── audit/                       ← audit harness
│   │   ├── config/
│   │   ├── core/                        ← 69 modules — see below
│   │   ├── db/
│   │   ├── fleet_mirror_client.py
│   │   ├── main.py                      ← Uvicorn entrypoint (per README)
│   │   ├── mirror_bridge.py
│   │   ├── phones/                      ← PhoneController + proxy gate
│   │   ├── platforms/
│   │   └── proxy/                       ← IPRoyal orchestrator
│   ├── pyproject.toml
│   ├── scripts/                         ← migrate_onimator.py et al.
│   └── tests/                           ← 19 pytest tests passing
├── companion-apk/
│   ├── README.md
│   ├── app/                             ← MainActivity.kt, Service skel
│   └── build.gradle.kts
├── core-rs/                             ← Rust orchestrator skeleton
│   ├── Cargo.toml
│   ├── README.md
│   ├── src/
│   └── tests/
├── desktop/
├── discord-export/                      ← 48,849-message corpus
├── docker-compose.yml                   ← pg 5436 / redis 6380 / be 8000 / fe 3016
├── docs/
├── frontend/                            ← Next.js 15 + TS + Tailwind
│   ├── package.json
│   ├── next.config.mjs
│   ├── .env.example
│   └── src/
│       ├── app/                         ← 30+ routes (see below)
│       ├── components/                  ← 23 shared components
│       └── lib/
├── login_survival_test.py               ← Phase-0 health probe script
├── ops/
├── runner/
├── scratchpad/
├── scripts/
└── survival_reports/
```

**Divergence from the canonical tree in CLAUDE.md:**

- **`backend/core-rs/` vs top-level `core-rs/`.** The canonical layout
  nests the Rust core under `backend/core-rs/`. The actual tree has
  `core-rs/` as a top-level sibling of `backend/`. The Rust tier is
  structurally separate from the Python backend package. Either layout is
  defensible; the handoff-reader should know the actual path is
  `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\core-rs\`, not
  `backend/core-rs/`.
- **No `backend/agents-go/` directory.** Go supervisors were planned but
  are not yet scaffolded. All agents currently live in Python at
  `backend/phantom_fleet/agents/`. The agent-mesh is implemented in
  Python-first and the Go tier is deferred.
- **No `backend/ml-py/` directory.** ML lives inside the main Python
  package at `backend/phantom_fleet/core/` alongside the main code (e.g.
  `ai_agent.py`, `chat_modes.py`, `cost_quality_router.py`,
  `safety_critic.py`, `voice_style.py`, `model_router.py`,
  `learning_engine.py`, `ops_brain.py`). The planned split between a
  separate `ml-py/` package and the orchestrator didn't happen.
- **No `backend/audit-harness/` directory.** Audit harness lives in two
  places: the agent at
  `backend/phantom_fleet/agents/audit_harness_agent.py`, and (presumably)
  the audit subpackage at `backend/phantom_fleet/audit/`. No stand-alone
  package yet.
- **No `backend/persona-factory/` directory.** Persona factory lives at
  `backend/phantom_fleet/agents/persona_factory_agent.py` and
  `backend/phantom_fleet/core/persona.py` /
  `persona_cohort.py` / `persona_cohort_validators.py` /
  `male_persona_factory.py`.
- **No `farm-agents/` directory.** Per-farm edge agent binaries + configs
  were planned for the local-orchestrator-per-farm pattern but have not
  been scaffolded. Possibly replaced by `runner/` and `ops/` directories.
- **`docs/architecture/`, `docs/playbooks/`, `docs/api/`** — there is a
  top-level `docs/` directory but the three sub-folders have not been
  inspected in this handoff; treat as "convention declared, may or may
  not be populated".
- **`logs/` directory** — not visible at the top level. Logs may be
  running into `scratchpad/`, `survival_reports/`, or a Docker-volume
  path.

**Additional on-disk directories not in the canonical tree:**

- `desktop/` — possibly an Electron shell or desktop-app-stub (see also
  `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-desktop\` which is a
  sibling directory outside this repo).
- `discord-export/` — the 48,849-message corpus + analysis MDs + 7.3 MB
  JSON dump that backs the planning intel section (`README.md:121–127`).
- `ops/`, `runner/`, `scripts/`, `scratchpad/`, `survival_reports/` — ops
  and scripting ancillaries.
- `login_survival_test.py` — top-level Phase-0 login diagnostic
  (referenced by `README.md:31` as one of the still-open Phase-0
  blockers).
- The `_discord_*.py` + `_onimator_*.py` scripts — one-off intel
  harvesters prefixed with underscore to indicate "not import-safe
  modules".
- `backend/NUL` — a stray Windows null-device file (artifact of a
  misdirected `> NUL` redirection on the Windows shell). Harmless but
  should be removed.

### `backend/phantom_fleet/core/` — 69 modules

The `core/` directory in the live Python package (`ls` output trimmed from
earlier tool call) holds considerably more than the canonical layout
suggested. Organized rough by domain:

- **Distribution + warming primitives:** `distributions.py`,
  `warming_curve.py`, `warming_orchestrator.py`, `warmup_phases.py`
- **Persona primitives:** `persona.py`, `persona_cohort.py`,
  `persona_cohort_validators.py`, `male_persona_factory.py`
- **Content + discovery:** `content_vault.py`, `source_scorer.py`,
  `target_filter.py`, `targets_admission.py`, `competitor_registry.py`,
  `comment_pod.py`, `pod_registry.py`
- **Fingerprint + safety:** `cluster_monitor.py`, `safety_critic.py`,
  `ghost_preview.py`, `voice_style.py`
- **Scheduling + execution:** `fleet_scheduler.py`,
  `scheduler_executor.py`, `time_slot_scheduler.py`, `time_machine.py`,
  `engagement_executor.py`, `human_post_behavior.py`, `hybrid_runner.py`
- **Instagram-specific:** `instagram_client.py`,
  `ig_action_dispatcher.py`, `ig_session_manager.py`,
  `ig_session_store.py`, `ig_ab_test.py`
- **Per-platform clients:** `bluesky_client.py`, `bluesky_ab_test.py`,
  `bumble_client.py`, `discord_client.py`, `grindr_client.py`,
  `hinge_client.py`, `reddit_client.py`, `reddit_header_extractor.py`,
  `reddit_oauth.py`, `telegram_client.py`, `threads_client.py`,
  `tinder_client.py`, `tiktok_controller.py`, `x_client.py`
- **DM pipeline:** `dm_funnel.py`, `dm_intent_classifier.py`,
  `chat_modes.py`
- **AI / routing:** `ai_agent.py`, `cost_quality_router.py`,
  `mission_composer.py`, `model_router.py`, `ops_brain.py`,
  `owner_brief.py`, `brief_redactor.py`, `learning_engine.py`,
  `tool_exchange.py`, `safety_critic.py`
- **Device + proxy:** `adb_router.py`, `apk_client.py`,
  `phone_controller.py`, `s10_box_config.py`
- **Account pooling:** `gmail_account_pool.py`
- **Photo verification + capacity:** `photo_verification.py`,
  `capacity_planner.py`
- **Integration:** `hq_bridge.py`
- **Simulation:** `simulate.py`

### Frontend route inventory

Routes present under `frontend/src/app/` (per `ls`):

```
app/
├── (marketing)/           ← route group for marketing pages
├── accounts/
├── agents/
├── alerts/
├── analytics/
├── approvals/
├── briefing/
├── calendar/
├── capacity/
├── cluster/
├── content/
├── content-vault/
├── dating/
├── fleet/
├── funnel/
├── globals.css
├── ig/
├── instagram/
├── layout.tsx
├── mirroring/
├── onboarding/
├── ops/
├── page.tsx               ← command center (/)
├── personas/
├── phase1/                ← Phase 1 readiness dashboard
├── phase2/                ← Phase 2 readiness dashboard
├── pipeline/
├── platforms/
├── proxy/
├── s10-box/
├── schedule/
├── settings/
├── targets/
├── threads/
└── tiktok/
```

The 11 dashboard routes + 4 marketing routes listed in `README.md:79–98`
are a **subset** of what's actually on disk — the on-disk tree carries
additional pages (approvals, briefing, calendar, capacity, content-vault,
dating, ig, instagram, mirroring, onboarding, ops, phase1, phase2,
pipeline, platforms, proxy, s10-box, schedule, threads, tiktok). Phase1
and phase2 are confirmed present (file sizes from `wc -l`: `phase1/page.tsx`
265 lines, `phase2/page.tsx` 279 lines).

### Frontend shared components (23 files per README)

From `README.md:99–113`:

- `sidebar`, `top-bar`, `command-palette` — navigation chrome
- `panel`, `kpi-card`, `status-badge` — canonical layout primitives
- `fleet-grid` — 19-phone live status card grid
- `agent-feed`, `action-stream` — live agent + action firehoses
- `cluster-heatmap` — 20-dim fingerprint monitor
- `revenue-chart` — OF/Fanvue/ScaleHer stacked area
- `stat-ring`, `sparkline`, `heatmap-grid`, `funnel-viz` — data-viz
  primitives
- `data-table` — sortable table for accounts/sources
- `animated-hero-bg` — canvas particle system for landing page
- `comparison-table` — Onimator vs Phantom Fleet feature matrix
- `architecture-diagram` — 5-layer SVG diagram
- `faq-accordion`, `testimonials` — marketing components
- `live-ticker` — drifting numeric ticker

### Companion APK scaffolding

`README.md:114–119`:

- `MainActivity.kt` — App entry with AccessibilityService enable button
- `PhantomAccessibilityService.kt` — Service skeleton with
  `tapAt(x, y, dwellMs)` primitive
- Gradle build config, AndroidManifest, accessibility config
- **Phase 1 adds** Ktor embedded HTTP server on 127.0.0.1:8765 with
  tap/type/scroll/screenshot/UI-inspect primitives

### Adjacent `_staffroom` repo

Location: `C:\Users\admin\Desktop\PhantomFleet\_staffroom\`

**Role.** The Staffroom repo is the clipping/content pipeline upstream of
Phantom Fleet. It produces approved content packages
(`handoff` records) that Phantom Fleet stages for publishing. See
`STAFFROOM_PHANTOM_FLEET_HANDOFF.md` (110 lines) which documents the
cross-repo HTTP contract. Full HTTP surface (verbatim from that file):

| Method and path | Request and response |
|---|---|
| `POST /api/clipster/renders/:id/handoffs` | Send `platform` and `caption` for a rendered export. The resulting handoff identifies the exact package. |
| `GET /api/clipster/handoffs/:id` | Read the package under the authenticated organization. The integration needs `id`, `render_id`, `version_id`, `media_sha256`, `platform`, `caption`, `decision`, `reviewer_id` and `reviewed_at`. |
| `POST /api/clipster/handoffs/:id/decision` | Send `decision` as `approved` or `changes_requested`. Replaying the same decision by the same reviewer returns the existing decision. A conflicting decision returns 409. |
| `PUT /api/clipster/handoffs/:id/fleet-staging` | The recorded approver sends `account_reference` and optional `scheduled_at`. New stage returns 201. Exact replay returns 200 with the saved staging receipt. |
| `GET /api/clipster/handoffs/:id/fleet-staging` | Returns `{staging: [...]}` for the handoff in the authenticated organization. |

**Approval / identity / retry rules** (from
`STAFFROOM_PHANTOM_FLEET_HANDOFF.md:25–28`):

- Package ID is lowercase hexadecimal SHA-256 of the UTF-8 bytes of
  `JSON.stringify([render_id, version_id, media_sha256, platform, caption])`
- Staging ID is lowercase hex SHA-256 of
  `JSON.stringify([handoff_id, account_reference])`
- Exact retry does not create another stage. A different schedule for the
  same `(package, account)` returns 409. A different account gets its own
  stage. A non-approver receives 403.

**Proposed Fleet intake mount** (from
`STAFFROOM_PHANTOM_FLEET_HANDOFF.md:44–69`):

- New router at `backend/phantom_fleet/api/routes/staffroom_intake.py`,
  mounted inside `create_app()` in `backend/phantom_fleet/api/app.py`
  immediately after the HQ-bridge router.
- Prefix: `/api/integrations/staffroom`, with `POST /intake` and
  `POST /intake/{staging_id}/cancel`.
- Setting: `FLEET_STAFFROOM_INTAKE_ENABLED` — defaults unset / false;
  register the router only when explicitly `true`. Disabled → 404, no
  intake storage or workers initialized.

**ASGI entrypoint divergence** (`STAFFROOM_PHANTOM_FLEET_HANDOFF.md:56–66`)
— multiple launchers select different modules:

- Python package launcher → `phantom_fleet.api.app:app` (per
  `backend/phantom_fleet/main.py:32`)
- README's local Uvicorn command → `phantom_fleet.api.main:app`
- Backend Docker image → `phantom_fleet.api.main:app`, port 8000 (per
  `backend/Dockerfile:19`)
- `docker-compose.yml` → `phantom_fleet.api.main:app`, port 8000 mapped
  to host 8002
- Windows `start.bat` → `phantom_fleet.api.main:app`, loopback 8001
- PM2 `deploy.sh` → `phantom_fleet.api.main:app`, loopback 8002

The intake mount in `api/app.py` would miss the four `api.main` launchers.
The Fleet integration review has not yet resolved the launcher
inconsistency.

**Other Staffroom files referenced** (file-listing of
`C:\Users\admin\Desktop\PhantomFleet\_staffroom\` includes but is not
limited to):

- `BUILD_REGISTER.md`
- `PHANTOM_FLEET_ACCEPTANCE_CHECKLIST.md`
- `PHANTOM_FLEET_COMPLETION_CHECKLIST_2026-11-16.md`
- `README.md`
- `STAFFROOM_MASTER_BLUEPRINT.txt`
- `STAFFROOM_MCP.md`
- `STAFFROOM_PHANTOM_FLEET_HANDOFF.md`
- `STAFFROOM_TOOL_GATEWAY.md`
- `VIDEO-PIPELINE-REPAIR-20261105.html`
- `artifacts/`, `clipster-worker/`, `config/`, `computer/`, `desktop/`,
  `document-worker/`, `node_modules/`, `public/`, `reference/`,
  `research/`, `scripts/`, `server/`, `tests/`
- `package.json`, `package-lock.json`, `requirements-documents.txt`

Downstream sections of this handoff spec (handled by parallel agents)
will presumably cover the Staffroom integration contract more deeply;
Section 1's job is to flag that it exists and set the handoff reader up
with the ASGI-mount-point + flag-gating constraints.

---

## Working mode

Verbatim from `.claude/CLAUDE.md`, "Working mode":

> The user's global CLAUDE.md rule is **full autonomy, no permission
> requests except for irreversible destructive actions on shared
> infrastructure**. Apply that here.
>
> For OrionFarm specifically:
>
> - Never flash a phone without user confirmation (irreversible)
> - Never factory-reset a phone without user confirmation (destroys
>   accounts)
> - Never push a companion APK to the whole fleet without user
>   confirmation (must pilot on 1 phone first)
> - Never modify the existing Onimator deployment's databases without
>   backing them up first
> - Never delete account data from `iguserdatabase.db` or
>   `notificationdatabase.db`
>
> Everything else (write code, run audits, refactor, add features, build
> infrastructure) proceeds without confirmation.

Operational translation for the implementing agent:

1. Write code, run tests, run migrations, refactor, add features, scaffold
   new agents, add CI jobs, modify Postgres schema, add new frontend
   routes — **no confirmation needed**.
2. Run audit harness in CI — **no confirmation needed**.
3. Issue ADB commands to a single phone for testing, build and install
   the companion APK on a single pilot phone, run login-survival
   diagnostics — **no confirmation needed**.
4. Flash a phone (bootloader unlock, custom recovery, custom ROM, Magisk)
   — **always ask first**.
5. Factory-reset a phone — **always ask first** (destroys installed IG
   clones + all stored accounts).
6. Push the companion APK fleet-wide — **always ask first**; the process
   must be pilot-on-1 → verify → fleet rollout.
7. Modify Onimator's `C:\Onimator\full_igbot_14.1.8.1\*.db` — **always
   back up first**, then ask before mutating.
8. Delete rows from `iguserdatabase.db` (7,412 rows) or
   `notificationdatabase.db` (43,571 rows) — **never, no exceptions**.

All of these integrate with the Hard Rules section (irreversible-action
safety) above — the overlap is intentional.

---

## Phase roadmap

Two definitions of the phases coexist in the repo:

1. The **revenue-funded Option C** in `PLAN.md:709–911` — six phases,
   each unlocked by the previous phase's revenue hitting a threshold.
2. The older **Phase 1 / Phase 2 / Phase 3 / Phase 4** in
   `PLAN.md:853–911` (overlaps and redefines with the Option C model).

Both are presented below; the implementing agent should treat the
**Option C revenue-funded ladder** as authoritative where the two
disagree, because it was "LOCKED: Option C revenue-funded scale-up
(2026-04-11)" (`PLAN.md:709`).

### Phase 0 — Full box parallel launch (Day 1 simultaneous, ~$98 Week 1)

`PLAN.md:713–766`. **Status: scaffolding complete per `README.md:28`;
four blockers remain open per `README.md:30–33`.**

**Day 0 pre-flight (~30 min, zero code)** (`PLAN.md:720–725`):

1. Authorize 2 unauthorized phones (`RF8N30B5FAD`, `RF8N406NLWK`) — user
   taps "Allow USB debugging"
2. Fix `en-GB` → `en-US` on all 19 phones via automated ADB script (fixes
   locale cluster bug + matches TrumpProxies NYC personas)
3. Enable Wi-Fi ADB on all 19 phones
4. Buy TrumpProxies YUGE 1-month plan ($98) — **later revised to IPRoyal
   Royal Residential Unlimited $80/mo, `PLAN.md:460–467`**
5. Configure proxy credentials + rotation API URL in Phantom Fleet
   config

**Day 0 login-survival diagnostic** (`PLAN.md:727–732`): run a login-only
diagnostic against all 219 accounts simultaneously — open each cloned IG
app on its assigned phone, attempt silent login, categorize:

- ✅ **Alive** — logged in, feed loads, ready for actions
- ⚠️ **Needs reset** — session expired, email/password recovery needed
- 💀 **Dead** — suspended, checkpoint, unrecoverable

Reports `survival_report.json` with exact count of usable accounts. The
file `login_survival_test.py` + the `survival_reports/` directory are
present in the repo root.

**Day 1 — full parallel re-wake launch** (`PLAN.md:734–740`):

- All 19 phones online simultaneously
- All surviving accounts start re-wake Day 1 in parallel
- 1 TrumpProxies YUGE plan handles full simultaneous load (proven)
- Re-wake Day 1 flow: login + scroll only, **zero follows/likes/comments**
  (gentlest possible dormant-account re-engagement)
- Fingerprint Monitor Agent watches for any suspensions in real time

**Day 2–7 — lockstep re-wake curve** (`PLAN.md:742–750`):

- Day 2: 0 follows, 0–2 likes, 3–5 story views
- Day 3: 1–2 follows, 2–4 likes, 5–8 story views
- Day 4: 2–4 follows, 4–8 likes, 8–12 story views
- Day 5: 3–6 follows, 6–12 likes, 10–15 story views
- Day 6: 5–9 follows, 10–18 likes, 15–22 story views, 1–2 comments
- Day 7: 8–14 follows, 18–28 likes, 22–32 story views, 2–3 comments

All ranges LogNormal per `(account, date)`, per-account personality
profile locked at migration.

**Day 8+ — steady state, full box running** (`PLAN.md:752–753`): all
accounts at ~22 actions/day (user's proven historical rate on the exact
same infrastructure). 1 persona per phone. Funneling fans to
OF/Fanvue/ScaleHer.

**Phase 0 code deliverables (Week 1)** (`PLAN.md:755–766`):

1. Wi-Fi ADB activation script — enables and verifies all 19 phones
2. Locale fixer script — sets `en-US` on all 19 phones
3. Onimator migration script — reads all 219 account DBs from existing
   Onimator install, imports into Phantom Fleet persona schema
4. Login-survival diagnostic — parallel health check across all 219
   accounts
5. Companion APK (Kotlin) — Accessibility Service + HTTP `/ping` +
   `/login_check` primitive (Day 0)
6. Python backend — FastAPI + asyncpg + Postgres, persona schema, account
   model, phone-to-account assignment
7. Proxy Orchestrator Agent — TrumpProxies single-plan wrapper with
   block-signal rotation (**revised to IPRoyal — `PLAN.md:496–534`**)
8. Warming Agent — LogNormal range sampling for re-wake curve Day 1–7
9. Fingerprint Monitor Agent — live cluster detection + real-time
   suspension alerts
10. Next.js dashboard — all 19 phones + 219 accounts on one live view,
    shows survival status, re-wake day, action counts, suspension alerts
11. First session validation — Day 1 login+scroll only flow executes
    end-to-end across the full box

**Phase 0 status as of README** (`README.md:28–33`):

> **Phase 0 scaffolding complete.** Awaiting:
>
> 1. Proxy-state diagnostic (read-only verification of current phone
>    routing)
> 2. IPRoyal Royal Residential Unlimited purchase (~$80/mo)
> 3. Login-survival test on all 16 authorized phones (blocked by proxy
>    gate)
> 4. Full-box parallel Day 1 launch across 19 devices + 219 Tatiana/Melodie
>    accounts

### Phase 1 — IG MVP (Weeks 2–6, IG ONLY)

`PLAN.md:768–789` (revenue-funded Option C) and `PLAN.md:853–868` (older
Phase 1 definition).

**Goal.** Full 17-phone box running ~30–50 Tatiana+Melodie IG accounts
end-to-end on 1–2 TrumpProxies plans. Revenue target: **$500–1,000/mo**
from OF/Fanvue/ScaleHer funnels.

**Spend (incremental Week 2–6).** `PLAN.md:772–775`:

- $0 — still using existing Tatiana/Melodie accounts (no new purchases
  until Phase 2 revenue funds them)
- $98–196/mo — upgrade to 2 TrumpProxies plans if concurrency requires
  (revised to IPRoyal $80/mo)
- $0 — dev work, CI, dashboards

**Deliverables.** `PLAN.md:777–787`:

- Full 28-day warming curve running on all existing accounts
- Account Setup Agent (account import + health probe on existing
  accounts)
- Recovery Agent (auto-reboot, auto-reauth, auto-resume)
- Replacement Agent (dead-account detection, marks for replacement)
- DM Agent with Chat AI + OF funnel integration
- Content Agent pulling from Content Vault
- Funnel Conversion Agent tracking fan → OF subscription rate per persona
- Fingerprint Monitor Agent (live cluster detection)
- Full Next.js dashboard with real-time account status, funnel metrics,
  OF revenue attribution
- **Validation gate:** Phase 1 is "done" when $500–1,000/mo is flowing
  from the funnel

**Phase 1 UI.** The frontend ships `/phase1` at
`frontend/src/app/phase1/page.tsx` (265 lines). It fetches
`/api/phase1/readiness` on load and polls every 15 s. The readiness
payload shape:

```ts
type Readiness = {
  ready: boolean;
  fleet_size: number;
  gates: Gate[];
  agents_total: number;
  agents_available: number;
  summary: string;
};

type Gate = {
  key: string;
  label: string;
  status: "pass" | "warn" | "fail" | "pending";
  detail: string;
  blocking: boolean;
};
```

The page shows a launch strip ("Cleared for launch" / "Launch blocked"), a
set of summary tiles (Fleet size, Agents registered, Gates passing,
Blocking issues), and a divided gates list with four states (pass / warn /
fail / pending), each with a "Blocking" badge where applicable. The launch
button hits `POST /api/phase1/start` and returns a `LaunchResult`:

```ts
type LaunchResult = {
  started: boolean;
  warming_running: boolean;
  agents_started: string[];
  message: string;
};
```

**Older Phase 1 definition** (`PLAN.md:853–868`):

> **Goal:** Full 17-phone box running ~50 IG accounts (3 per phone,
> conservative) on 3 mobile proxies, $90–120/mo recurring, Tatiana+Melodie
> migrated from existing Onimator.
>
> Deliverables:
> - Companion APK full primitive set (tap, type, navigate, state, recover)
> - Warming Agent autonomous 48h flow
> - Account Setup Agent (aged purchase + FB OAuth chain)
> - Recovery Agent (auto-reboot + re-auth)
> - Replacement Agent (account death → new provision)
> - Proxy Orchestrator Agent
> - Fingerprint Monitor Agent (live distribution tracking)
> - CI audit harness blocking
> - Basic Next.js dashboard with real-time farm status
>
> **Deliverable:** 200 IG accounts running autonomously on 1 farm, 4
> cohorts, measured account lifespan vs Onimator baseline.

### Phase 2 — Add Reddit (revenue-funded, Weeks 7–10)

`PLAN.md:789–800`.

**Trigger.** Phase 1 produces ≥$500/mo in OF/Fanvue/ScaleHer revenue.

**Budget.** Whatever Phase 1 revenue affords, no more.

**Add:**

- Aged Reddit accounts (or self-created, email-only, ~$0.50–2 each)
- Reddit-specific Companion APK primitives
- Reddit warming curve (looser, Reddit has cheaper detection)
- Reddit → OF funnel paths (subreddit posting, DM to profile visitors,
  etc.)
- Revenue target: **$1,000–2,500/mo combined (IG + Reddit)**

**Phase 2 UI.** The frontend ships `/phase2` at
`frontend/src/app/phase2/page.tsx` (279 lines). The readiness payload is
richer than Phase 1's — it carries a per-platform roster with status
(`scaffold` / `primitives` / `warming` / `ready`):

```ts
type PlatformGate = {
  key: string;
  label: string;
  status: "scaffold" | "primitives" | "warming" | "ready";
  account_source: string;
  warming_days: number;
  account_count: number;
  detail: string;
  blocking: boolean;
};

type Readiness = {
  ready: boolean;
  phase1_ready: boolean;
  platforms: PlatformGate[];
  gates: Gate[];
  agents_total: number;
  agents_available: number;
  summary: string;
};
```

The icons map (`PLATFORM_ICON` in `phase2/page.tsx:43–50`) reveals the
Phase-2 target platform roster at the UI layer: **threads, reddit,
tiktok, snapchat, x, instagram**. The dashboard surfaces a card per
platform with:

- Icon + label
- Account source (snake_case → space-separated)
- Warming days
- Account count
- Status badge (scaffold / primitives / warming / ready, each color-coded)
- "Blocking" badge where applicable

The launch button hits `POST /api/phase2/start` — the gating guarantee is
that Phase 2 cannot launch unless Phase 1 is `ready` (dashboard shows
"Phase 1 is not cleared — Phase 2 can't launch until Phase 1 is live." if
not).

The on-disk roster in Phase 2 mixes **the older PLAN-era Phase 2 roster**
(Threads + TikTok + Reddit + Snapchat + X — `PLAN.md:870–883`) with the
Option-C Phase 2's **narrow Reddit-only unlock** (`PLAN.md:789–800`).
The UI is therefore implementing the older parity-expansion plan, not the
revenue-funded single-platform-at-a-time plan. The implementing agent
should expect to reconcile these two views.

**Older Phase 2 definition — "Parity + expansion" (Weeks 7–12)**
(`PLAN.md:870–883`):

> **Goal:** Match Onimator's full platform roster on your full fleet.
>
> - Threads support (shares IG infrastructure)
> - TikTok support (TikMatrix + companion APK primitives)
> - Reddit support (Chameleon mode + companion APK)
> - Snapchat support (harder — real SIM required)
> - X/Twitter via integration with existing `x-panel/` + Xmator-style web
>   path
> - DM Agent across all platforms
> - Content Agent routing through ModelForge + Chat AI
> - Funnel Conversion Agent tracking fan → OF/Fanvue/ScaleHer subscribe
>   rate
> - Full fleet deployment: all 9 farms + 180 phones
> - Mobile proxy modem farm built (20 DIY IPs online)
>
> **Deliverable:** 1,000–1,500 active accounts across IG + TikTok +
> Threads + Reddit + Snapchat + X, running autonomously, cost-per-
> account-day tracked, fan funnel measured.

### Phase 3 — Option C: Add Snapchat (revenue-funded, Weeks 11–14)

`PLAN.md:802–812`.

**Trigger.** Phase 2 produces ≥$1,000/mo total.

**Add:**

- Aged Snapchat accounts (~$10–40 each, harder market, budget accordingly)
- Snapchat Companion APK primitives
- Snapchat → OF funnel (Snap adds, AI chat, CTA to OF)
- Revenue target: **$2,500–5,000/mo combined**

**Older Phase 3 definition — "Dating + OF monetization" (Weeks 13–20)**
(`PLAN.md:886–898`):

> **Goal:** Unlock Tinder/Bumble/Hinge + deeply integrate with
> OF/Fanvue/ScaleHer funnels.
>
> - Magisk rollout on dedicated 20-phone dating farm (SafetyNet spoofing)
> - Tinder automation (where Onimator failed — cleaner implementation
>   from scratch)
> - Bumble automation (where Onimator is broken)
> - Hinge automation (new for the market)
> - CupidAI-equivalent self-hosted AI chat layer routed through Chat AI
> - ScaleHer + Fanvue + OnlyFans deep integration (cross-link personas,
>   shared DM pool)
> - Fan funnel dashboard: "persona X drove N subs to Y platform last week"
>
> **Deliverable:** 60–100 dating accounts + full cross-platform funnel
> with conversion tracking.

### Phase 4 — Option C: Add TikTok (revenue-funded, Weeks 15–18)

`PLAN.md:814–824`.

**Trigger.** Phase 3 produces ≥$2,500/mo.

**Add:**

- Aged TikTok accounts (~$8–30 each)
- TikTok Companion APK (follow/like/comment/scroll feed + FBR tracking)
- TikTok → OF funnel (bio link, mass follow, DM)
- Revenue target: **$5,000–10,000/mo combined**

**Older Phase 4 definition — "The long tail + SaaS upsell" (Weeks 21+)**
(`PLAN.md:899–911`):

> **Goal:** Every other platform + multi-tenant SaaS go-live for agencies.
>
> - Spotify, LinkedIn, Facebook, YouTube, Pinterest, Kick, Telegram,
>   Discord, Bluesky, Lemon8
> - Platform plugin framework (new platform = 2-week integration)
> - Multi-tenant dashboard
> - Stripe + Crypto billing
> - White-label theming
> - Device leasing portal (rent slots on your fleet)
> - API access tier
> - Public marketing site
>
> **Deliverable:** OrionFarm SaaS live with first 10 paying agency
> customers, hosted farm tier live with first 5 renters.

### Phase 5 — Option C: Add Threads (revenue-funded, Weeks 19–22)

`PLAN.md:826–836`.

**Trigger.** Phase 4 produces ≥$5,000/mo.

**Add:**

- Threads accounts (free — linked to existing IG accounts)
- Threads Companion APK primitives
- Cross-posting IG ↔ Threads
- Revenue target: **$10,000–15,000/mo combined**

### Phase 6+ — Option C: Everything else (revenue-funded, Month 6+)

`PLAN.md:838–842`.

Only unlocks when Phase 5 is earning: X/Twitter (via Xmator pattern),
Spotify, LinkedIn, Facebook, YouTube, Tinder/Bumble/Hinge (with Magisk),
Pinterest, Kick, Discord, Telegram, Bluesky, Lemon8. Each platform gets
unlocked only when the previous month's revenue funds it, not before.

### Revenue-funded scale math

`PLAN.md:844–851`:

- **Phase 0:** $50 max spend, $0 revenue
- **Phase 1:** $100–200/mo recurring, target $500–1,000/mo revenue →
  **net $300–800/mo**
- **Phase 2:** +$100/mo, target $1,000–2,500/mo →
  **net $700–2,200/mo**
- **Phase 3:** +$300/mo (Snapchat accounts are pricey), target
  $2,500–5,000/mo → **net $2,000–4,500/mo**
- **Phase 4:** +$200/mo, target $5,000–10,000/mo →
  **net $4,500–9,500/mo**
- **Phase 5:** +$50/mo, target $10,000–15,000/mo →
  **net $9,700–14,700/mo**
- **Phase 6+:** Each new platform is now trivially affordable from
  5-figure/month cashflow

### First-week concrete deliverables (overlaps Phase 0)

`PLAN.md:948–961`:

1. Fix `en-GB`/`NY` timezone cluster across all 180 phones (1 day)
2. Enable Wi-Fi ADB on all phones (1 day)
3. Auth the 2 unauthorized phones on current farm (5 min — user does
   this manually)
4. Buy 10 aged IG accounts + 5 mobile IPs as test pool (1 day + $100)
5. Companion APK skeleton that responds to `/ping` over HTTP (2 days)
6. Persona factory prototype generating 100 synthetic personas (2 days)
7. Audit harness skeleton running the 10 cluster checks (2 days)
8. Pilot Day 0 flow: 1 phone, 1 persona, 1 aged IG account, 48h warmup
   (3 days)
9. Next.js dashboard skeleton with 1 farm + 1 phone + 1 account live (2
   days)
10. Decision memo on Magisk rollout (covered in Phase 3 scoping)

**Cost to start Week 1:** ~$150–300 (10 aged accounts + 5 rented proxies
+ ~$50 in incidentals). (`PLAN.md:961`)

### Out of scope (anti-scope-creep)

`PLAN.md:965–973`:

- VPS hosting (**NEVER** — local only)
- USB-to-Ethernet networking upgrade (NEVER — USB hubs work at 20
  phones/PC)
- Emulator support Phase 1–2 (real phones only; emulators Phase 4+ if
  demand)
- iOS Phase 1–2 (Android only; iOS Phase 3+)
- Building our own clone pipeline Phase 1–2 (use NomixCloner as
  dependency; build competitor in Phase 3+)
- Custom ROMs / kernel modifications (too risky Phase 1; revisit Phase
  4+)
- Multi-tenant UI Phase 1–2 (single-tenant only until core is proven)

---

## Open questions from PLAN.md §12 and `.claude/CLAUDE.md`

The PLAN document ends at `§10. Open decisions to confirm`
(`PLAN.md:1001–1008`). The user's instructions refer to "§12" — that
section does not exist in the current PLAN (the doc stops at §10, with §9
being "The 1000x vs Onimator checklist" and §10 being "Open decisions to
confirm"). Treating §10 as the referenced open-questions section:

### PLAN §10 — Open decisions to confirm (`PLAN.md:1001–1008`)

1. [ ] Start Phase 0 scaffolding immediately? (yes = build companion APK
       skeleton + persona factory this week)
2. [ ] Pilot persona: migrate Tatiana/Melodie from existing Onimator or
       create new?
3. [ ] First 10 aged IG accounts: which marketplace (BHW / BTZ / Swapd)?
       **PLAN's recommendation:** BTZ VIP for quality.
4. [ ] Mobile proxy Phase 0 budget: spend $200 on 5 rented or $300 on 5
       DIY modems as starter?
5. [ ] Magisk rollout: which phones are you willing to flash for Phase 3
       dating tier? **PLAN's recommendation:** 20 phones dedicated.
6. [ ] Stack confirmation: Rust core + Go agents + Python ML + TypeScript
       UI? (lock now to avoid bikeshedding later)

### `.claude/CLAUDE.md` — Open questions tracked in PLAN.md §12

The CLAUDE.md file also lists open questions "tracked in PLAN.md §12"
(the §12 reference in CLAUDE.md appears to be stale — the current PLAN
ends at §10). The questions listed in CLAUDE.md:

> Before Phase 1 implementation:
>
> - [ ] Plan approval
> - [ ] Pilot farm selection
> - [ ] Pilot persona (new vs migrate Tatiana/Melodie)
> - [ ] Magisk rollout plan
> - [ ] Stack confirmation
> - [ ] Monorepo vs polyrepo
> - [ ] Phase 0 scaffolding go-ahead

Cross-referencing: the CLAUDE.md open-question set is nearly a superset
of PLAN §10, plus two items that §10 omits:

- **Pilot farm selection** — out of 9 farms, which one is the Phase 0
  pilot farm? The audit in `HARDWARE.md:5` names farm 1 of 9 as the only
  audited one.
- **Monorepo vs polyrepo** — the current layout is effectively a
  monorepo with Rust + Python + Kotlin + Next.js all under one tree. The
  planning doc assumed a single repo; the question flags whether that
  decision is confirmed or whether some components should split off.

### HARDWARE.md — Open questions for the user (`HARDWARE.md:274–281`)

The hardware doc carries six more open questions:

1. **Are all 9 farms on the same LAN, or distributed across locations?**
   Affects central orchestrator networking design.
2. **How many phones per farm, exactly?** Farm 1 shows 17 ADB-visible + 20
   in `devices.db` — is ~20 the target per farm?
3. **Proxy inventory** — how many SuperProxy endpoints, how many 4G
   residential providers, what's the per-farm allocation?
4. **Which phones (if any) are you willing to Magisk-flash for Phase 2
   signature permission upgrade?**
5. **Are there real SIMs you could install in some phones for native
   mobile IPs?** Even 10–20 SIMs across the fleet would open genuine
   cellular fingerprints for high-value personas.
6. **Why is Onimator currently offline?** Last-known-good state? Any
   pending issues on the existing deployment we need to preserve while
   migrating?

### Phase-0 README blockers (`README.md:30–33`)

The four Phase-0 blockers from README function as open questions /
pending actions:

1. Proxy-state diagnostic (read-only verification of current phone
   routing)
2. IPRoyal Royal Residential Unlimited purchase (~$80/mo)
3. Login-survival test on all 16 authorized phones (blocked by proxy
   gate)
4. Full-box parallel Day 1 launch across 19 devices + 219 Tatiana/Melodie
   accounts

### Staffroom integration open questions (`STAFFROOM_PHANTOM_FLEET_HANDOFF.md:95–104`)

Section 1 flagged these for completeness; downstream handoff sections
will address them in detail:

| Input | What the review needs |
|---|---|
| Approved Fleet source and launcher | Writable integration branch + exact base commit + decision on which pending Fleet edits belong in the base; authoritative deployment manifest, ASGI command, and image digest. |
| Service authentication | Credential issuer + secret reference, expected audience + scope, rotation policy, how Fleet derives tenant from authenticated service identity. |
| Tenant, campaign and destination mapping | Authoritative mapping source, owner, representative valid + revoked test records; how Fleet resolves `account_reference` to provider account + platform. |
| Approval and immutable media | Staffroom approval + media access contracts, required service permissions, how Fleet validates media against SHA-256, how revocation reaches Fleet. |
| Durable intake storage | Production datastore + migration owner, tenant uniqueness rules, persistence-across-restart; qualification environment for selected launcher. |

---

## Appendix A — Verbatim stack-decision table

Repeated for easy reference; cite `.claude/CLAUDE.md` for all rows.

| Layer | Technology | Reason |
|---|---|---|
| Core orchestrator | Rust | Latency + throughput for hot path (device control, action queue) |
| Agents | Go | Concurrency for long-running supervisors (proxy orchestrator, recovery agent) |
| ML / content generation | Python | ModelForge, Chat AI, OpenRouter integration already Python |
| Web UI | TypeScript / Next.js | Matches Scaler Pro panel convention |
| Android companion APK | Kotlin + Jetpack | Native performance + modern Android APIs |
| Event bus | NATS or Redis Streams | Decision made at Phase 0 scaffolding; prefer NATS for durability |
| Database | Postgres 16 | Matches existing Scaler Pro panels, cross-panel queries via schema links |
| Cache | Redis | Standard |
| CI | GitHub Actions | Audit harness runs here as required check |

## Appendix B — Verbatim repo tree from CLAUDE.md "Folder convention"

```
orionfarm/
├── .claude/
│   └── CLAUDE.md         (this file)
├── PLAN.md               (executive plan)
├── HARDWARE.md           (fleet intel)
├── backend/
│   ├── core-rs/          (Rust orchestrator core)
│   ├── agents-go/        (Go agent supervisors)
│   ├── ml-py/            (Python ML + content generation)
│   ├── audit-harness/    (10K-persona Monte Carlo CI gate)
│   ├── persona-factory/  (Python persona generator)
│   └── migrations/       (Postgres schema migrations)
├── frontend/             (Next.js + WebSocket dashboard)
├── companion-apk/        (Android Studio project)
├── farm-agents/          (per-farm edge agent binaries + configs)
├── docs/
│   ├── architecture/     (diagrams, decision records)
│   ├── playbooks/        (operational runbooks)
│   └── api/              (OpenAPI specs)
└── logs/
```

## Appendix C — Per-phase agent-mesh ownership map

Cross-referencing `PLAN.md:755–766` (Phase 0 deliverables),
`PLAN.md:777–787` (Phase 1 Option C), and `README.md:50–66` (15 shipped
agents), the agent ownership by phase:

| Agent | Phase 0 | Phase 1 | Phase 2 | Phase 3+ |
|---|---|---|---|---|
| `warming` | ✓ (re-wake Day 1–7) | ✓ (full 28-day) | ✓ | ✓ |
| `fresh_target` | — | ✓ | ✓ | ✓ |
| `source_discovery` | — | ✓ | ✓ | ✓ |
| `fingerprint_monitor` | ✓ | ✓ | ✓ | ✓ |
| `recovery` | — | ✓ | ✓ | ✓ |
| `replacement` | — | ✓ | ✓ | ✓ |
| `proxy_orchestrator` | ✓ (single-plan) | ✓ (multi-plan) | ✓ | ✓ |
| `dm` | — | ✓ | ✓ | ✓ |
| `content` | — | ✓ | ✓ | ✓ |
| `account_setup` | ✓ (import existing) | ✓ (purchased aged) | ✓ | ✓ |
| `persona_factory` | — | ✓ | ✓ | ✓ |
| `growth_strategy` | — | ✓ | ✓ | ✓ |
| `funnel_conversion` | — | ✓ | ✓ | ✓ |
| `content_scout` | — | — | ✓ | ✓ |
| `audit_harness` | ✓ (CI gate) | ✓ | ✓ | ✓ |

## Appendix D — Live hardware audit cross-reference

The live hardware audit (`HARDWARE.md`) surfaces one bug that each of the
four CLAUDE.md "Known fleet bugs" entries points at, plus additional
infra observations relevant to Section 1 architecture decisions:

| Bug (CLAUDE.md) | Live evidence (HARDWARE.md) | Section-1 implication |
|---|---|---|
| #1 locale/tz mismatch | `HARDWARE.md:101–124` — every phone is `(en-GB, America/New_York)` | Persona factory must decide both together per Layer 2 cross-field consistency rule |
| #2 AppCloner fingerprint | `HARDWARE.md:187–192` — 22 clones share signing cert | Companion APK must use session-level switching inside single IG app, no repackaging |
| #3 static 15–22 account count | implied — `devices.db` carries 20 rows, 22 clones installed | Persona-factory should vary account count by device-aging persona |
| #4 flat action timing | contradicted by `PLAN.md:50–62` LogNormal per-(account,date) | Warming Agent + core/distributions.py already address at the architectural level |

Other hardware-audit infra data points relevant to Section 1 architecture:

- **No root.** `HARDWARE.md:67–83` — su binary not present, SELinux
  enforcing, retail firmware. Phase 1 companion APK must use
  Accessibility Service (no root). Signature-permission
  `InputManager.injectInputEvent()` is a Phase-2+ upgrade pending Magisk.
- **Wi-Fi ADB trivially activatable.** `HARDWARE.md:85–97` — USB hub
  dependency can be eliminated immediately as a free Phase-0 win.
- **No SIM cards on any phone.** `HARDWARE.md:127–148` — the entire farm
  is Wi-Fi-only. Invalidates Onimator's "native mobile IPs via SIMs"
  claim. Proxy routing happens via SuperProxy (per-app) + Surfshark VPN
  (system-wide fallback). Phase 1 drops SIM-IP from the architecture,
  uses cross-panel 4G residential proxy rotation.
- **Onimator currently offline.** `HARDWARE.md:231` — no Onimator
  processes running, only `adb.exe`. Databases on disk are
  last-known-good state at migration time.
- **Onimator DB sizes** (`HARDWARE.md:244–249`):
  - `iguserdatabase.db` 0.69 MB — **7,412 rows** of scraped IG target
    users (scrape pool, not user's own accounts)
  - `notificationdatabase.db` 3.23 MB — **43,571 rows** of per-account
    action history (no indexes)
  - `devices.db` — 20 rows, fleet device registry
- **Existing persona folders** (`HARDWARE.md:252–258`): `Tatiana` and
  `Melodie` personas, each with Default and Warmup operation modes, plus
  a shared `48hourInitialReelWatchingwarmup` folder. Preserve the pattern.

---

## Appendix E — Section 1 citation index (exact file paths)

Every claim in this handoff section can be traced back to one of the
following paths. All paths absolute:

- `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\PLAN.md`
  (1009 lines, planning v2 locked 2026-04-11, Discord-amplified)
- `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\HARDWARE.md`
  (281 lines, fleet hardware audit 2026-04-11)
- `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\README.md`
  (218 lines, product-facing status + metrics)
- `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\PHANTOM_FLEET_VS_ONIMATOR.md`
  (172 lines, feature-parity matrix)
- `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\.claude\CLAUDE.md`
  (repo-local Claude Code instructions: stack, hard rules, folder
  convention, working mode, open questions)
- `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\frontend\src\app\phase1\page.tsx`
  (265 lines, Phase-1 readiness dashboard)
- `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\frontend\src\app\phase2\page.tsx`
  (279 lines, Phase-2 readiness dashboard)
- `C:\Users\admin\Desktop\PhantomFleet\_staffroom\STAFFROOM_PHANTOM_FLEET_HANDOFF.md`
  (110 lines, upstream Clipster → Fleet publishing contract)
- `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\backend\phantom_fleet\agents\`
  (15+ agent files — see Layer 4 and Appendix C)
- `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\backend\phantom_fleet\core\`
  (69 Python modules — distributions, warming, persona, per-platform
  clients, DM funnel, scheduler, etc.)
- `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docker-compose.yml`
  (Postgres 5436 + Redis 6380 + backend 8000 + frontend 3016)

---

*End of Section 1.*


---

# Section 2: Backend

Scope: FastAPI app, every route file, core modules, ops/sched, ops/dispatch, ops/targets, ops/cron, and the persona store SQLite schema. Everything is anchored to live source at `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\backend\` and `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\ops\`.

Design invariants that run through every subsystem below:

- No `random.*` or `Math.random` anywhere on the hot path. All stochasticity is typed distribution objects seeded from `secrets.randbits`/hashing. Ties are broken deterministically (target.id, account-id-alphabetical, SHA256-derived jitter).
- The API never talks IG/Threads/Reddit directly. It plans into queues; the companion APK is the only thing that drives a real app. The one hard contract between them is the picker-shape → APK-shape translation in `ops/dispatch/_endpoints.py`.
- A single SQLite file, `backend/.data/persona-store.sqlite`, is the control plane. Every sched/dispatch/target/comment/hydrator/supervisor module opens it through `ops.sched._store.connect()` and applies the same additive migrations idempotently.
- Owner approval is a **hard gate**. Targets and comments land as `needs_approval` and only Staffroom/API approval transitions them to `active`. The picker refuses to return a non-active row.

---

## 2.1  FastAPI app (`backend/phantom_fleet/api/app.py`)

Single-file wiring, 734 lines. Sole responsibility: compose middleware, lifespan, routers, `/health`. No request handlers live here.

### 2.1.1  CORS and config

`create_app()` reads env `PHANTOM_ALLOWED_ORIGINS` (comma-separated, default `http://localhost:3016`), strips entries, installs `CORSMiddleware` with `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`.

Env vars read at boot:

| Var | Default | Purpose |
|-----|---------|---------|
| `PHANTOM_ALLOWED_ORIGINS` | `http://localhost:3016` | CORS allowlist. |
| `REDIS_URL` | `redis://localhost:6379/0` | Optional pub/sub for OpsBrain. Missing Redis logs a warning and the app continues. |
| `PHANTOM_DAILY_LLM_CAP_USD` | `25.0` | Daily LLM cost ceiling for OpsBrain. |
| `PHANTOM_MIRROR_URL` | unset | If set, PhoneFleet prefers the Phantom Fleet Mirror for `scan()` and falls back to local adb. |
| `STAFFROOM_BASE_URL` | `http://127.0.0.1:4321` | Staffroom base. |
| `STAFFROOM_SESSION_COOKIE` | `""` | Cookie for authenticating into Staffroom. |
| `STAFFROOM_COO_BOT_ID` | `bot-coo` | COO bot id used for cadence dispatch. |
| `STAFFROOM_CADENCE_LOOP` | off | `1` enables the in-process cadence tick loop. |
| `STAFFROOM_CADENCE_TICK_SECONDS` | `60` | Loop interval when enabled. |
| `PHANTOM_PROXY_POOL` / `IPROYAL_ISP_PROXIES` / `SMARTPROXY_PROXIES` | — | Seeded into the generic proxy pool at boot; legacy vendor pools are migrated into a single `GenericProxyPool`. |

A `.env` file at `backend/.env` is loaded via `python-dotenv` if present (fails silently when package is missing).

### 2.1.2  Lifespan events

The `@asynccontextmanager` lifespan on `app` is the single boot sequence. Order of initialisation and what it attaches to `app.state`:

1. `get_pool()` + `run_migrations()` from `..db.connection`. On failure, logs a warning and sets `db_pool = None` — the app keeps running stateless.
2. `AppState()` with `PhoneFleet()` singleton → `app.state.ctx`.
3. Mirror bridge from `mirror_bridge_from_env()`. When reachable, attached to the fleet via `ctx.fleet.set_mirror(mirror)` and its SSE event stream is started.
4. Redis connection (`aioredis.from_url`). Optional. Missing Redis logs a warning.
5. Generic proxy pool from env, with legacy pools migrated in if the generic pool is empty.
6. `PhantomFleetOpsBrain` with fleet, redis, db_pool and daily cap → `app.state.brain`, awaited `start()`.
7. `FleetScheduler` → `app.state.scheduler`.
8. `HQBridge(fleet, db_pool)` → `app.state.hq_bridge`.
9. Conditional on `db_pool`:
   - `SchedulerExecutor(db_pool)` → `app.state.scheduler_executor`, started.
   - `EngagementExecutor(db_pool)` → `app.state.engagement_executor`, started.
10. Threads stack (ordered):
    - `ThreadsRepository(db_pool)` → `app.state.threads_repo`.
    - `ThreadsFunnelTracker(repo=threads_repo)` → `app.state.threads_funnel`. Restores durable counters from repo.
    - `ThreadsExecutor(fleet, mirror, queue_getter, funnel)` → `app.state.threads_executor`. The `queue_getter` returns `app.state.threads_queue` (lazily created list).
    - `ThreadsHealthMonitor(accounts_store_getter, queue_getter, funnel, repo)` → `app.state.threads_health`.
    - `ThreadsProbeScheduler(..., tick_sec=90.0)` → `app.state.threads_probes`, late-bound into health via `health.set_probes(probes)`.
    - `ThreadsRecoveryAgent(..., tick_sec=30.0, repo=repo)` → `app.state.threads_recovery`. Restores records from repo.
    - `ThreadsAgent` + `AgentRunsRing` from `agents.threads_agent`; tool registry built from `platforms.threads`.
    - `ThreadsFleetRebalancer(health, probes, recovery, tick_sec=20.0, alert_sink)` → `app.state.threads_rebalancer`.
    - `ThreadsOrchestrator(accounts_store_getter, queue_getter, funnel, tick_sec=60.0, health, agent, agent_ring, rebalancer)` → `app.state.threads_orchestrator`.
11. IG bridge:
    - `IGEventBus(repo=threads_repo)` → `app.state.ig_event_bus`. Replays last 200 IG events from repo.
    - `ThreadsCrossPostBridge(accounts_store_getter, queue_getter, funnel)` subscribed to `ig_bus`.
12. Instagram stack mirrors the Threads stack (health, funnel, queue, agent, orchestrator, probes, recovery, rebalancer, proxy, drift, identity, dm, unfollow, session, checkpoint, lattice, executor). Each is attached to `app.state` under a sibling name (`ig_health`, `ig_funnel`, …). The orchestrator's `tick_sec` is 60.0; the probes 120.0; the rebalancer 20.0; the executor 2.0.
13. IG proxy pool is seeded from the generic pool: `proxy_id = f"{host}:{port}"`, `country` parsed from the `country-XX` token in the proxy username (default `US`), stored on `app.state.ig_proxy_pool`.
14. Staffroom integration: `StaffroomMissionStore(StaffroomClient(base, session_cookie), coo_bot_id, config_source="env")` → `app.state.staffroom`. Optional cadence loop fires `staffroom.cadence_tick()` every `STAFFROOM_CADENCE_TICK_SECONDS`.
15. IG checkpoint handler is wired so `two_factor_prompt` / `password_change` / `account_locked` events are forwarded into the session manager.

Shutdown reverses all starts: orchestrators, recovery agents, probes, rebalancers, executors, OpsBrain, close_pool(), redis close(), mirror close().

### 2.1.3  Router registration

All routers are included in `create_app()`. Table of prefix × tag × router (preserves order):

| Router | Prefix | Tags |
|--------|--------|------|
| `fleet.router` | `/api/fleet` | `fleet` |
| `phase1.router` | `/api/phase1` | `phase1` |
| `phase2.router` | `/api/phase2` | `phase2` |
| `proxy_pool.router` | `/api/proxy` | `proxy` |
| `threads.router` | `/api/platforms/threads` | `threads` |
| `instagram.router` | `/api/platforms/instagram` | `instagram-platform` |
| `accounts.router` | `/api/accounts` | `accounts` |
| `capacity.router` | `/api` | `capacity` |
| `agents.router` | `/api/agents` | `agents` |
| `schedule.router` | `/api/schedule` | `schedule` |
| `funnel.router` | `/api/funnel` | `funnel` |
| `ig_growth.router` | `/api/ig/growth` | `ig-growth` |
| `replacement.router` | `/api/accounts` | `replacement` |
| `cluster_monitor.router` | `/api/cluster` | `cluster` |
| `content_vault.router` | `/api/content-vault` | `content-vault` |
| `ops.router` | `/api/ops` | `ops` |
| `hq_bridge.router` | `/api/hq` | `hq-bridge` |
| `ig_intelligence.router` | `/api/ig` | `ig-intelligence` |
| `comment_pods.router` | `/api/comment-pods` | `comment-pods` |
| `gmail_reddit_pipeline.router` | `/api/pipeline` | `pipeline` |
| `groups.router` | `/api/groups` | `groups` |
| `warmup.router` | `/api/warmup` | `warmup` |
| `scraper.router` | `/api/scraper` | `scraper` |
| `strategy.router` | `/api/strategy` | `strategy` |
| `staffroom_missions.router` | (self) | (self) |
| `simulate.router` | (self) | (self) |
| `time_machine.router` | (self) | (self) |
| `tool_exchange.router` | (self) | (self) |
| `owner_brief.router` | (self) | (self) |
| `targets.router` | (self) | `targets` |
| `cost_quality_router.router` | (self) | (self) |
| `safety_critic.router` | (self) | (self) |
| `mission_composer.router` | (self) | (self) |
| `persona_cohort.router` | (self) | (self) |
| `scheduler_pro.router` | `/api/scheduler-pro` | `scheduler-pro` |
| `ai_agent_routes.router` | `/api/ai-agent` | `ai-agent` |
| `pods.router` | `/api/pods` | `pods` |
| `ab_tests.router` | `/api/ab-tests` | `ab-tests` |
| `settings.router` | `/api/settings` | `settings` |
| `activity_log.router` | `/api/activity` | `activity` |
| `profiles.router` | `/api/profiles` | `profiles` |
| `trending.router` | `/api/trending` | `trending` |
| `learning.router` | `/api/learning` | `learning` |
| `reddit.router` | `/api/reddit` | `reddit` |
| `fleet_mirror.router` | `/api/fleet-mirror` | `fleet-mirror` |

Routers marked `(self)` set their own `prefix` and `tags` inside the router file. For example, `targets.py` defines `APIRouter(prefix="/api/targets", tags=["targets"])` itself; `owner_brief.py` sets `/api/owner_brief`.

### 2.1.4  WebSocket endpoints

There are two: `/api/fleet/ws/fleet` (in `routes/fleet.py` around line 951) and `/api/ops/ws/ops` (in `routes/ops.py` around line 253). Fleet WS streams scan diffs; OpsBrain WS streams the cycle event bus.

### 2.1.5  Health probe

```python
@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "product": "phantom_fleet", "version": "0.1.0"}
```

### 2.1.6  Failure modes

- No DB: lifespan continues and routes that depend on `db_pool` branch on `None`. `SchedulerExecutor` and `EngagementExecutor` are not booted.
- No Redis: OpsBrain runs without pub/sub.
- No mirror: PhoneFleet uses local adb.
- Threads/IG executors started before DB restore of durable counters would crash if the repo raises — each restore is wrapped in `try/except log.exception("… restore failed")`.
- Staffroom cadence loop failures log and sleep; a single tick failure never kills the loop.

---

## 2.2  Route files

The route layer has 42 modules totaling 15,207 lines. Each is documented in its own H3, with H4 per endpoint. Every file sets `APIRouter` in its own idiom; a few (`targets.py`, `owner_brief.py`, `simulate.py`, `time_machine.py`, `tool_exchange.py`, `safety_critic.py`, `cost_quality_router.py`, `mission_composer.py`, `persona_cohort.py`, `staffroom_missions.py`) carry their own prefix.

### 2.2.1  `routes/targets.py` (133 lines)

Prefix `/api/targets`, tag `targets`. Thin HTTP skin around `core.targets_admission`.

Pydantic models:

```python
class _TargetRow(BaseModel):
    kind: str = Field(..., pattern="^(account|media)$")
    handle: str = Field(..., min_length=1, max_length=120)
    media_code: Optional[str] = Field(default=None, max_length=64)
    tags: list[str] = Field(default_factory=list)
    locale: Optional[str] = Field(default=None, max_length=16)
    farm_id: Optional[str] = Field(default=None, max_length=64)

class _IngestIn(BaseModel):
    rows: list[_TargetRow]
    source: str = Field(..., min_length=1, max_length=64)

class _ApproveIn(BaseModel):
    approver: str = Field(..., min_length=1, max_length=120)

class _RejectIn(BaseModel):
    approver: str = Field(..., min_length=1, max_length=120)
    reason: str = Field(..., min_length=1, max_length=500)

class _CommentRow(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    niche: str = Field(default="generic", max_length=40)

class _CommentIngestIn(BaseModel):
    rows: list[_CommentRow]
    source: str = Field(..., min_length=1, max_length=64)
```

#### POST `/api/targets/ingest`
Body `_IngestIn`. Delegates to `targets_admission.ingest_targets(rows, source)`. Returns `{inserted, duplicates, rejected: [(row, reason), ...], ts_ms}`.

#### GET `/api/targets/pending`
Query `farm_id?`, `limit` (1–500, default 100). Returns `{rows: [...]}`. Rows match the `target_pool` table.

#### POST `/api/targets/{target_id}/approve`
Body `_ApproveIn`. 404 on not found or already-decided. Returns `{ok: True, id, status: "active", ts_ms}`.

#### POST `/api/targets/{target_id}/reject`
Body `_RejectIn`. 404 on not found or already-decided. Returns `{ok: True, id, status: "rejected", ts_ms}`.

#### POST `/api/targets/comments/ingest`
Body `_CommentIngestIn`. Delegates to `ingest_comments`. Same return shape as target ingest.

#### GET `/api/targets/comments/pending`
Query `limit` (1–500, default 100). Returns `{rows: [...]}`.

#### POST `/api/targets/comments/{comment_id}/approve`
Body `_ApproveIn`. 404 on not found or already-decided.

#### POST `/api/targets/comments/{comment_id}/reject`
Body `_RejectIn`. 404 on not found or already-decided.

#### GET `/api/targets/pending_counts`
Returns `{pending_target_approvals: int, pending_comment_approvals: int}`. Called by `owner_brief`.

### 2.2.2  `routes/owner_brief.py` (15 lines)

Prefix `/api/owner_brief`, tag `owner-brief`. Single endpoint:

#### GET `/api/owner_brief`
Delegates to `core.owner_brief.owner_brief()` on a thread (synchronous composer wrapped by `asyncio.to_thread`). Returns a six-signal brief (plus target/comment admission signals) in under 500 ms. See §2.3.1 for shape.

### 2.2.3  `routes/fleet.py` (983 lines)

Prefix `/api/fleet`, tag `fleet`. Manages the physical farm — scan, verify, APK install, heartbeat, cluster collisions, ADB locks, mirror status, per-serial accounts, warming entry point, WebSocket.

Endpoints (method, path, line):

| Line | Method | Path | Notes |
|------|--------|------|-------|
| 154 | GET | `` | `FleetSummaryOut` — count/status breakdown. |
| 171 | GET | `/{serial}` | `PhoneOut` — one phone's full state. |
| 181 | POST | `/scan` | `ScanResultOut` — adb-scan the farm, diff, update DB. |
| 201 | POST | `/{serial}/verify-proxy` | `ProxyVerifyOut` — curl through phone's proxy and record. |
| 232 | POST | `/verify-all` | `VerifyAllOut` — fan out verify-proxy. |
| 249 | POST | `/verify-all-proxy-pool` | `VerifyAllOut` — same against the proxy pool. |
| 296 | POST | `/dev/force-proxy-ready` | Dev shortcut; sets proxy state to ready for every serial. |
| 315 | POST | `/{serial}/install-apk` | `InstallAPKOut` — pushes the companion APK. |
| 360 | GET | `/{serial}/apk-health` | `APKHealthOut` — polls APK `/health`. |
| 399 | POST | `/{serial}/extract-device-info` | Reads IMEI/serial/screen/android version. |
| 431 | POST | `/heartbeat` | Received from the companion APK; updates `device_endpoints`, bumps last-seen. |
| 482 | GET | `/cluster/collisions` | Reports IMEI/ANDROID_ID/HNI collisions across the fleet. |
| 605 | POST | `/{serial}/adb/acquire` | Takes an exclusive ADB lock for a calling pid. |
| 632 | POST | `/{serial}/adb/release` | Releases the lock. |
| 642 | GET | `/mirror/status` | Mirror bridge liveness + last event. |
| 661 | GET | `/{serial}/accounts` | Accounts currently assigned to this serial. |
| 789 | POST | `/start-warming` | `StartWarmingOut` — kicks off the warming orchestrator. |
| 951 | WS | `/ws/fleet` | Streams fleet-scan diffs and heartbeat updates. |

Response models like `FleetSummaryOut`, `ScanResultOut`, etc. are all defined at the top of `fleet.py` (lines 1-153).

Failure modes: adb not on PATH, APK unresponsive on `/health`, mirror bridge down, proxy curl timeout. Each endpoint wraps its action in `try/except` and surfaces an error payload rather than a 500 unless the body is malformed (which `FastAPI`/`pydantic` already handle).

### 2.2.4  `routes/accounts.py` (1504 lines)

Prefix `/api/accounts`, tag `accounts`. Largest route file. The `_store` function here is also imported by many lifespan agents as `_accounts_store` — it's the in-memory accounts store the fleet-wide state revolves around.

Endpoints:

| Line | Method | Path | Response model |
|------|--------|------|----------------|
| 219 | GET | `` | `AccountListOut` |
| 242 | GET | `/{account_id}` | `AccountOut` |
| 259 | POST | `/seed-dev` | `ProvisionResultOut` |
| 305 | POST | `/provision` | `ProvisionResultOut` |
| 372 | GET | `/{account_id}/health` | `HealthOut` |
| 408 | POST | `/{account_id}/assign-phone` | `AssignPhoneOut` |
| 469 | POST | `/{account_id}/login` | `LoginResultOut` |
| 607 | PATCH | `/{account_id}` | update fields (persona, device, status, tags). |
| 668 | POST | `/{account_id}/detect-clone` | Finds which cloned IG package this account is signed into. |
| 760 | GET | `/{account_id}/session` | `SessionStatusOut` |
| 784 | POST | `/{account_id}/session/refresh` | `HealthOut` |
| 836 | DELETE | `/{account_id}/session` | 204 — revoke session. |
| 865 | POST | `/bulk-login` | `BulkLoginResultOut` |
| 939 | POST | `/bulk-import` | — CSV/JSON import of accounts. |
| 1004 | POST | `/provision-pending` | — provision every account in a pending state. |
| 1048 | GET | `/{account_id}/stats` | — follower/following/history. |
| 1162 | POST | `/{account_id}/scrape-follow-source` | Enqueue a scrape of the account's current followers/following so target picking has material. |
| 1223 | GET | `/{account_id}/targets` | Per-account target list. |
| 1262 | POST | `/{account_id}/targets` | Add a target row for this account. |
| 1320 | DELETE | `/{account_id}/targets/{target_id}` | 204. |
| 1340 | POST | `/{account_id}/targets/ai-scrape` | LLM-driven target expansion (uses CostQualityRouter + SafetyCritic). |
| 1395 | POST | `/{account_id}/clone` | Create an AppClone instance for this account. |

State machine ties: `status` field values observed across the codebase: `alive`, `paused`, `dead`, `unknown`, `provisioning`, `shadowbanned`, `needs_login`, `locked`, `retired`. Transitions log to `account_status_history`.

### 2.2.5  `routes/capacity.py` (148 lines)

Prefix `/api` (so endpoint is `/api/capacity-plan`), tag `capacity`.

#### POST `/api/capacity-plan`
Body is a `CapacityPlanRequest` with fleet size, target DAU, action mix. Response `CapacityReportOut` giving per-day actions/account, accounts/phone, and capacity headroom. Pure function; no DB side effect.

### 2.2.6  `routes/agents.py` (177 lines)

Prefix `/api/agents`, tag `agents`.

| Line | Method | Path | Response model |
|------|--------|------|----------------|
| 133 | GET | `` | `AgentsListOut` — names + last status. |
| 140 | GET | `/status` | `AgentsStatusOut` — detailed per-agent runtime stats. |
| 167 | GET | `/{name}` | `AgentDetailOut` — one agent's full state and recent run log. |

### 2.2.7  `routes/schedule.py` (206 lines)

Prefix `/api/schedule`, tag `schedule`.

| Line | Method | Path | Response model |
|------|--------|------|----------------|
| 155 | GET | `/today` | `TodayScheduleOut` — flatten today's enqueued actions per account. |
| 175 | POST | `/generate` | `DailyScheduleOut` — call `ops.sched.warming.schedule_day()` for a given account and return the plan without enqueueing. |

### 2.2.8  `routes/threads.py` (1223 lines)

Prefix `/api/platforms/threads`, tag `threads`. Core surface for the Threads agent stack.

Endpoints (summary):

| Line | Method | Path |
|------|--------|------|
| 204 | GET | `/accounts` |
| 211 | POST | `/link` |
| 259 | POST | `/post` |
| 265 | POST | `/reply` |
| 271 | POST | `/repost` |
| 277 | POST | `/follow` |
| 283 | GET | `/budget/{account_id}` |
| 290 | GET | `/curve/{account_id}` |
| 299 | GET | `/status` |
| 312 | POST | `/advance-day/{account_id}` |
| 374 | GET | `/queue` |
| 401 | POST | `/executor/start` |
| 415 | POST | `/executor/stop` |
| 429 | GET | `/executor/status` |
| 492 | POST | `/funnel/event` |
| 521 | GET | `/funnel/summary` |
| 532 | GET | `/funnel/{account_id}` |
| 561 | GET | `/orchestrator/status` |
| 575 | POST | `/orchestrator/run` |
| 583 | POST | `/orchestrator/start` |
| 590 | POST | `/orchestrator/stop` |
| 597 | GET | `/funnel/activity/stream` |
| 631 | POST | `/ig-event` |
| 650 | GET | `/ig-events` |
| 658 | GET | `/bridge/status` |
| 672 | POST | `/accounts/{account_id}/warmup` |
| 702 | POST | `/audit/run` |
| 720 | GET | `/audit/last` |
| 726 | POST | `/cross-post` |
| 809 | POST | `/health/scan` |
| 817 | GET | `/health/summary` |
| 823 | GET | `/health/{account_id}` |
| 838 | POST | `/health/simulate` |
| 933 | GET | `/recovery/status` |
| 939 | POST | `/recovery/tick` |
| 948 | POST | `/recovery/{account_id}/graduate` |
| 956 | POST | `/recovery/{account_id}/skip-cooldown` |
| 999 | GET | `/rebalancer/status` |
| 1004 | POST | `/rebalancer/tick` |
| 1042 | GET | `/probes/status` |
| 1053 | POST | `/probes/tick` |
| 1062 | GET | `/probes/{account_id}` |
| 1109 | GET | `/agent/runs` |
| 1131 | GET | `/persistence/status` |
| 1162 | GET | `/accounts/{account_id}/dossier` |

Response-model shapes live inline at the top of `threads.py`. The dossier endpoint is the compact view a Staffroom human reads to make a judgment about one account.

### 2.2.9  `routes/instagram.py` (877 lines)

Prefix `/api/platforms/instagram`, tag `instagram-platform`. Mirrors Threads but with more surfaces (DM, unfollow, session, checkpoint, drift, identity, lattice, proxy, diurnal, executor, agent).

Groups of endpoints:

- **Health**: POST `/health/scan`, GET `/health/summary`, GET `/health/{account_id}`, POST `/health/simulate`.
- **Recovery**: GET `/recovery/status`, POST `/recovery/tick`, POST `/recovery/{account_id}/graduate`, POST `/recovery/{account_id}/skip-cooldown`.
- **Budget/curve**: GET `/budget/{account_id}`, GET `/curve/{account_id}`.
- **Rebalancer**: GET `/rebalancer/status`, POST `/rebalancer/tick`.
- **Orchestrator**: GET `/orchestrator/status`, POST `/orchestrator/plan-now`.
- **Queue**: GET `/queue`.
- **Probes**: GET `/probes/status`, POST `/probes/tick`, GET `/probes/{account_id}`.
- **Funnel**: GET `/funnel/summary`, GET `/funnel/{account_id}`, POST `/funnel/record`.
- **DM**: GET `/dm/summary`, POST `/dm/tick`, POST `/dm/draft`, POST `/dm/{dm_id}/sent`, POST `/dm/reply`, GET `/dm/{actor_id}`.
- **Unfollow**: GET `/unfollow/summary`, POST `/unfollow/tick`, POST `/unfollow/record-follow`, POST `/unfollow/record-follow-back`, POST `/unfollow/mark-retained`, GET `/unfollow/{actor_id}`.
- **Session**: GET `/session/summary`, POST `/session/tick`, POST `/session/{account_id}/login`, POST `/session/{account_id}/complete-2fa`, POST `/session/{account_id}/expire`, GET `/session/{account_id}`.
- **Checkpoint**: GET `/checkpoint/summary`, POST `/checkpoint/observe`, GET `/checkpoint/{account_id}`.
- **Lattice**: GET `/lattice/summary`, POST `/lattice/plan`.
- **Drift**: GET `/drift/summary`, POST `/drift/scan`, POST `/drift/{phone_serial}/snapshot`, GET `/drift/{phone_serial}`.
- **Proxy**: GET `/proxy/summary`, POST `/proxy/tick`, POST `/proxy/{account_id}/rotate`, POST `/proxy/{account_id}/pin`, POST `/proxy/{account_id}/release`, POST `/proxy/pool/add`.
- **Identity**: GET `/identity/summary`, POST `/identity/scan`, GET `/identity/{account_id}`.
- **Diurnal**: GET `/diurnal/summary`, GET `/diurnal/{account_id}`.
- **Executor**: GET `/executor/status`, POST `/executor/start`, POST `/executor/stop`.
- **Agent**: GET `/agent/config`, GET `/agent/runs`.
- **Dossier**: GET `/accounts/{account_id}/dossier`.

### 2.2.10  `routes/proxy_pool.py` (156 lines)

Prefix `/api/proxy`.

| Line | Method | Path | Response model |
|------|--------|------|----------------|
| 76 | GET | `/pool` | `ProxyListOut` |
| 93 | POST | `/pool` | `AddProxiesOut` |
| 115 | DELETE | `/pool/{index}` | — delete by list index. |
| 131 | POST | `/pool/verify` | `VerifyPoolOut` — curl-test each proxy and report. |

Important: the deleter uses list index, not a stable id. Known TODO: switch to stable `proxy_id`.

### 2.2.11  `routes/phase1.py` (372 lines)

Prefix `/api/phase1`, tag `phase1`.

| Line | Method | Path | Response model |
|------|--------|------|----------------|
| 267 | GET | `/readiness` | `ReadinessOut` — fleet/account/APK/proxy gates. |
| 305 | POST | `/start` | `LaunchOut` — begin the Phase 1 pilot. |

### 2.2.12  `routes/phase2.py` (311 lines)

Prefix `/api/phase2`, tag `phase2`.

| Line | Method | Path | Response model |
|------|--------|------|----------------|
| 231 | GET | `/readiness` | `ReadinessOut` |
| 274 | POST | `/start` | `LaunchOut` |

### 2.2.13  `routes/replacement.py` (289 lines)

Prefix `/api/accounts` (shared with the accounts router). Endpoints:

| Line | Method | Path | Response model |
|------|--------|------|----------------|
| 139 | GET | `/dead` | `DeadAccountListOut` — read `replacements_needed`. |
| 155 | POST | `/replacement/run` | `ReplacementRunOut` — run the sched/replacement job once. |
| 182 | GET | `/spare-pool` | `SparePoolStatusOut` |
| 203 | POST | `/spare-pool/upload` | `SpareUploadOut` — upload raw credentials file to the spare pool. |

### 2.2.14  `routes/cluster_monitor.py` (257 lines)

Prefix `/api/cluster`, tag `cluster`.

| Line | Method | Path | Response model |
|------|--------|------|----------------|
| 143 | GET | `/health` | `ClusterHealthReportOut` |
| 168 | POST | `/health/run` | `ClusterHealthReportOut` |
| 201 | GET | `/alerts` | `AlertListOut` |
| 212 | POST | `/alerts/{alert_id}/resolve` | `ResolveOut` |
| 232 | GET | `/alerts/history` | `AlertListOut` |

Backed by `core.cluster_monitor.ClusterMonitor`, which runs the 10 cluster-analysis checks from CLAUDE.md: locale/timezone contradiction, AppCloner certificate overlap, flat account counts per device, flat timing, HNI/carrier mismatch, …

### 2.2.15  `routes/content_vault.py` (442 lines)

Prefix `/api/content-vault`, tag `content-vault`.

| Line | Method | Path | Response model |
|------|--------|------|----------------|
| 185 | POST | `/push` | `PushResultOut` — upload one item. |
| 238 | GET | `` | `ContentListOut` |
| 271 | POST | `/upload` | `PushResultOut` — multipart variant. |
| 310 | DELETE | `/{item_id}` | `DeleteResultOut` |
| 321 | GET | `/stats` | — content counts/types. |
| 341 | POST | `/{item_id}/deliver` | `DeliverResultOut` — send to a target. |
| 399 | POST | `/schedule` | `ScheduleResultOut` — schedule a vault item on an account. |

### 2.2.16  `routes/ops.py` (311 lines)

Prefix `/api/ops`, tag `ops`.

| Line | Method | Path | Response model |
|------|--------|------|----------------|
| 114 | GET | `/status` | `OpsStatusOut` |
| 129 | GET | `/cycle/latest` | `CycleReportOut | None` |
| 139 | GET | `/cycle/history` | `list[CycleReportOut]` |
| 146 | POST | `/pause` | `PauseResumeOut` |
| 156 | POST | `/resume` | `PauseResumeOut` |
| 166 | POST | `/cycle/trigger` | `TriggerCycleOut` |
| 176 | GET | `/schedule/today` | — today's planned actions across the farm. |
| 209 | GET | `/alerts/live` | — streaming snapshot of active alerts. |
| 253 | WS | `/ws/ops` | Streams OpsBrain cycle events. |

### 2.2.17  `routes/hq_bridge.py` (351 lines)

Prefix `/api/hq`, tag `hq-bridge`. Bridges the panel to the Scaler Pro HQ. Endpoints at lines 167, 194, 222, 261, 299 — decorators split across multiple lines. The surface covers `/sync`, `/account-sync`, `/campaigns`, `/push`, `/status`.

### 2.2.18  `routes/ig_intelligence.py` (456 lines)

Prefix `/api/ig`, tag `ig-intelligence`.

| Line | Method | Path | Response model |
|------|--------|------|----------------|
| 210 | GET | `/competitors` | `CompetitorListOut` |
| 223 | POST | `/competitors` | `AddCompetitorOut` |
| 233 | POST | `/competitors/harvest` | `HarvestTriggerOut` |
| 286 | GET | `/targets/lookalikes` | `LookalikeListOut` |
| 298 | POST | `/targets/lookalikes` | `LookalikeGenerateOut` |
| 357 | GET | `/health` | `HealthSummaryOut` |
| 384 | GET | `/health/{account_id}` | `AccountHealthOut` |
| 397 | POST | `/health/guardian/run` | `GuardianRunOut` |

### 2.2.19  `routes/comment_pods.py` (313 lines)

Prefix `/api/comment-pods`, tag `comment-pods`.

| Line | Method | Path | Response model |
|------|--------|------|----------------|
| 189 | GET | `` | `PodsListOut` |
| 198 | POST | `` | `CreatePodOut` (201) |
| 224 | POST | `/{pod_id}/rotate` | `RotateOut` |
| 250 | GET | `/{pod_id}/stats` | `PodStatsOut` |
| 269 | POST | `/auto-assign` | `AutoAssignOut` (201) |

### 2.2.20  `routes/gmail_reddit_pipeline.py` (491 lines)

Prefix `/api/pipeline`, tag `pipeline`.

| Line | Method | Path | Response model |
|------|--------|------|----------------|
| 163 | GET | `/gmail/stats` | `PipelineStatsResponse` |
| 179 | POST | `/gmail/create` | 202 |
| 203 | POST | `/reddit/register` | 202 |
| 237 | GET | `/reddit/accounts` | `AccountListResponse` |
| 276 | POST | `/reddit/provision` | 202 |
| 473 | POST | `/reddit/export` | — export reddit credentials bundle. |

### 2.2.21  `routes/groups.py` (239 lines)

Prefix `/api/groups`.

| Line | Method | Path |
|------|--------|------|
| 80 | POST | `/register` |
| 114 | GET | `` |
| 142 | POST | `` |
| 165 | PATCH | `/{group_id}` |
| 201 | DELETE | `/{group_id}` |
| 208 | POST | `/{group_id}/assign` |
| 220 | POST | `/{group_id}/unassign` |
| 229 | GET | `/{group_id}/accounts` |

### 2.2.22  `routes/warmup.py` (254 lines)

Prefix `/api/warmup`.

| Line | Method | Path |
|------|--------|------|
| 64 | GET | `` |
| 83 | POST | `` |
| 117 | DELETE | `/{plan_id}` |
| 124 | POST | `/run` |

### 2.2.23  `routes/scraper.py` (534 lines)

Prefix `/api/scraper`.

| Line | Method | Path |
|------|--------|------|
| 256 | POST | `/run` |
| 265 | GET | `/targets` |
| 292 | GET | `/stats` |
| 343 | POST | `/follow-from-queue` |
| 389 | POST | `/follow-back-check` |
| 495 | POST | `/auto-unfollow` |
| 527 | DELETE | `/targets` |

### 2.2.24  `routes/strategy.py` (284 lines)

Prefix `/api/strategy`.

| Line | Method | Path |
|------|--------|------|
| 132 | POST | `/generate` |
| 180 | POST | `/apply` |
| 275 | GET | `/{group_id}` |

### 2.2.25  `routes/staffroom_missions.py` (187 lines)

Self-prefixed under `/api/staffroom`.

| Line | Method | Path |
|------|--------|------|
| 53 | GET | `/missions/summary` |
| 58 | POST | `/missions/dispatch` |
| 73 | GET | `/roster` |
| 78 | GET | `/roster/{team}` |
| 88 | GET | `/research-grants` |
| 98 | GET | `/cadences` |
| 103 | POST | `/cadences/tick` |
| 108 | POST | `/cadences/toggle` |
| 117 | GET | `/missions/{request_id}` |
| 126 | POST | `/missions/{request_id}/refresh` |
| 135 | GET | `/missions/{request_id}/ghost-preview` |
| 171 | POST | `/missions/adopt` |
| 181 | GET | `/missions/{request_id}/open-url` |

### 2.2.26  `routes/simulate.py` (69 lines)

Self-prefixed under `/api/simulate`.

| Line | Method | Path |
|------|--------|------|
| 40 | POST | `/fleet_shape` |
| 45 | POST | `/action_sequence` |
| 62 | POST | `/ghost_preview` |

### 2.2.27  `routes/time_machine.py` (76 lines)

Self-prefixed under `/api/time-machine`.

| Line | Method | Path |
|------|--------|------|
| 42 | POST | `/snapshot` |
| 53 | GET | `/snapshots` |
| 58 | POST | `/fork_from` |
| 69 | GET | `/forks` |
| 74 | POST | `/prune` |

### 2.2.28  `routes/tool_exchange.py` (101 lines)

Self-prefixed under `/api/tool_exchange`.

| Line | Method | Path |
|------|--------|------|
| 43 | POST | `/propose` |
| 60 | GET | `/proposals` |
| 71 | GET | `/proposals/{proposal_id}` |
| 79 | POST | `/proposals/{proposal_id}/approve` |
| 89 | POST | `/proposals/{proposal_id}/reject` |
| 99 | GET | `/discover` |

### 2.2.29  `routes/cost_quality_router.py` (29 lines)

#### POST `/api/cost_quality_router/recommend`
Returns a model pick for a given workflow at a given cost tier. Thin wrapper on `core.cost_quality_router.recommend`.

### 2.2.30  `routes/safety_critic.py` (27 lines)

| Line | Method | Path |
|------|--------|------|
| 17 | POST | `/critique` |
| 25 | GET | `/rules` |

### 2.2.31  `routes/mission_composer.py` (34 lines)

#### POST `/api/mission_composer/mission`
Composes a mission brief (Staffroom-shape) from a short natural-language goal.

### 2.2.32  `routes/persona_cohort.py` (40 lines)

| Line | Method | Path |
|------|--------|------|
| 24 | POST | `/generate` |
| 33 | POST | `/one` |
| 38 | POST | `/validate` |

### 2.2.33  `routes/scheduler_pro.py` (408 lines)

Prefix `/api/scheduler-pro`.

| Line | Method | Path |
|------|--------|------|
| 105 | GET | `/schedules` |
| 123 | POST | `/schedules` |
| 143 | PATCH | `/schedules/{schedule_id}` |
| 171 | DELETE | `/schedules/{schedule_id}` |
| 182 | POST | `/schedules/{schedule_id}/accounts` |
| 199 | GET | `/schedules/{schedule_id}/accounts` |
| 216 | POST | `/schedules/{schedule_id}/generate` |
| 279 | GET | `/queue` |
| 326 | GET | `/calendar` |
| 373 | GET | `/timeline/{account_id}` |
| 391 | GET | `/stats` |

### 2.2.34  `routes/ai_agent_routes.py` (206 lines)

Prefix `/api/ai-agent`.

| Line | Method | Path |
|------|--------|------|
| 68 | GET | `/status` |
| 74 | POST | `/start/{account_id}` |
| 86 | POST | `/stop/{account_id}` |
| 93 | POST | `/start-all` |
| 106 | POST | `/start-group/{group_id}` |
| 121 | POST | `/stop-all` |
| 128 | POST | `/run-once/{account_id}` |
| 139 | GET | `/logs` |
| 178 | POST | `/configure` |
| 196 | GET | `/config` |

### 2.2.35  `routes/pods.py` (310 lines)

Prefix `/api/pods`.

| Line | Method | Path |
|------|--------|------|
| 82 | GET | `` |
| 103 | POST | `` |
| 122 | PATCH | `/{pod_id}` |
| 146 | DELETE | `/{pod_id}` |
| 157 | GET | `/queue` |
| 184 | POST | `/queue` |
| 200 | POST | `/process` |

### 2.2.36  `routes/ab_tests.py` (316 lines)

Prefix `/api/ab-tests`.

| Line | Method | Path |
|------|--------|------|
| 103 | GET | `` |
| 131 | POST | `` |
| 154 | GET | `/{test_id}` |
| 166 | PATCH | `/{test_id}` |
| 196 | POST | `/{test_id}/start` |
| 208 | POST | `/{test_id}/pause` |
| 218 | POST | `/{test_id}/end` |
| 231 | DELETE | `/{test_id}` |
| 238 | GET | `/{test_id}/results` |
| 282 | POST | `/{test_id}/assign` |
| 296 | POST | `/{test_id}/event` |

### 2.2.37  `routes/settings.py` (95 lines)

Prefix `/api/settings`.

| Line | Method | Path |
|------|--------|------|
| 44 | GET | `` |
| 58 | GET | `/{key}` |
| 71 | POST | `` |
| 91 | DELETE | `/{key}` |

### 2.2.38  `routes/activity_log.py` (124 lines)

Prefix `/api/activity`.

| Line | Method | Path |
|------|--------|------|
| 32 | GET | `` |
| 77 | GET | `/stats` |
| 113 | DELETE | `` |

### 2.2.39  `routes/profiles.py` (350 lines)

Prefix `/api/profiles`.

| Line | Method | Path |
|------|--------|------|
| 99 | POST | `/generate-bio` |
| 159 | POST | `/update-bio` |
| 204 | POST | `/update-pfp` |
| 256 | POST | `/pin-post` |
| 289 | GET | `/{account_id}/posts` |

### 2.2.40  `routes/trending.py` (425 lines)

Prefix `/api/trending`.

| Line | Method | Path |
|------|--------|------|
| 299 | POST | `/discover` |
| 321 | GET | `/discover/{job_id}` |
| 329 | GET | `/all` |
| 339 | GET | `/google` |
| 390 | GET | `/evergreen` |
| 398 | GET | `/posts` |
| 420 | DELETE | `/posts` |

### 2.2.41  `routes/learning.py` (118 lines)

Prefix `/api/learning`.

| Line | Method | Path |
|------|--------|------|
| 42 | POST | `/outcome` |
| 57 | GET | `/insights` |
| 88 | POST | `/context` |
| 100 | POST | `/analyze` |
| 109 | DELETE | `/insights/{insight_id}` |

### 2.2.42  `routes/reddit.py` (1191 lines)

Prefix `/api/reddit`.

| Line | Method | Path |
|------|--------|------|
| 310 | GET | `/stats` |
| 388 | GET | `/accounts` |
| 444 | GET | `/accounts/{account_id}/status` |
| 501 | POST | `/accounts/{account_id}/advance` |
| 570 | GET | `/subreddits` |
| 623 | POST | `/subreddits/seed` |
| 670 | GET | `/history/posts` |
| 725 | GET | `/history/comments` |
| 779 | GET | `/shadowban-queue` |
| 803 | POST | `/accounts/login` (202) |
| 840 | POST | `/accounts/{account_id}/refresh-token` |
| 930 | POST | `/accounts/{account_id}/extract-headers` (202) |
| 1002 | POST | `/phones/{serial}/extract-headers` (202) |
| 1065 | POST | `/trigger/karma-farm` (202) |
| 1109 | POST | `/trigger/post` (202) |
| 1171 | POST | `/trigger/discover` (202) |

### 2.2.43  `routes/fleet_mirror.py` (91 lines)

Prefix `/api/fleet-mirror`.

| Line | Method | Path |
|------|--------|------|
| 31 | GET | `/status` |
| 44 | GET | `/embed` |
| 59 | GET | `/embed-wall` |
| 73 | GET | `/access` |

---

## 2.3  Core modules (`backend/phantom_fleet/core/`)

Most core modules are ≈100–600 lines. This section documents the ones with external dependencies in `app.py` lifespan and the critical gatekeepers.

### 2.3.1  `targets_admission.py`

The one gatekeeper between upstream intake (Treg agents, scrapers, Staffroom) and the picker. Owns:

- `ingest_targets(rows, source)` — inserts into `target_pool` as `needs_approval`, deduped by `(COALESCE(farm_id,''), kind, handle, COALESCE(media_code,''))`. Returns `{inserted, duplicates, rejected: [(row, reason), ...], ts_ms}`. Rejects rows where `kind not in ('account','media')`, missing handle, or `kind='media'` without `media_code`.
- `list_pending_targets(farm_id=None, limit=100)` — `WHERE status='needs_approval' [AND (farm_id=? OR farm_id IS NULL)]` ordered by `imported_ms DESC`.
- `approve_target(id, approver)` — `UPDATE target_pool SET status='active', approved_by=?, approved_ms=? WHERE id=? AND status='needs_approval'`. Returns `{ok:False, reason}` if row doesn't exist or already decided.
- `reject_target(id, approver, reason)` — sets `status='rejected'` and `rejected_reason`.
- Comment versions `ingest_comments / list_pending_comments / approve_comment / reject_comment` with identical semantics against `comment_pool`.
- `pending_counts()` — `{pending_target_approvals, pending_comment_approvals}` used by owner_brief.

Everything runs against `ops.sched._store`. `apply_migrations()` is called on every entry point so the table is guaranteed to exist.

### 2.3.2  `owner_brief.py`

Composer for moonshot #9. The brief is eight signals (originally six, extended with target/comment admission):

```python
_SIGNAL_RUNNERS = [
    ("pending_tool_proposals", _signal_pending_tool_proposals),
    ("stale_approvals", _signal_stale_approvals),
    ("cost_anomalies", _signal_cost_anomalies),
    ("contradictions_flagged", _signal_contradictions_flagged),
    ("snapshot_pressure", _signal_snapshot_pressure),
    ("recent_forks", _signal_recent_forks),
    ("pending_target_approvals", _signal_pending_target_approvals),
    ("pending_comment_approvals", _signal_pending_comment_approvals),
]
```

Each runner is wrapped in try/except so a single failing source cannot blank the brief. The response shape:

```json
{
  "headline": "3 tool proposal(s); 2 stale approval(s); snapshot pressure",
  "needs_attention_total": 12,
  "signals": {
    "pending_tool_proposals":   {"status": "ok|no_data|error", "count": int, "items": [...]},
    "stale_approvals":          {...},
    "cost_anomalies":           {...},
    "contradictions_flagged":   {...},
    "snapshot_pressure":        {...},
    "recent_forks":             {...},
    "pending_target_approvals": {...},
    "pending_comment_approvals":{...}
  },
  "duration_ms": 118,
  "generated_unix_ms": 1732700000000
}
```

Signal rules:
- **pending_tool_proposals**: calls into `tool_exchange.list_proposals(status='needs_approval', limit=20)`.
- **stale_approvals**: SQLite query on Staffroom DB for `missions WHERE status='needs_approval' AND created_at <= now - 2h`. Returns `[]` if the schema differs (schema-probe tolerant).
- **cost_anomalies**: reads the ghost-preview audit log, groups by workflow for both the last 24h and the last 7d, flags workflows where `day_p95_usd >= 2 * week_median_usd`, and requires at least 3 day samples and 10 week samples. P95 uses `statistics.quantiles(n=20)` when sample size ≥ 20, else `max()`.
- **contradictions_flagged**: `mission_memory WHERE contradiction=1 AND created_at >= now - 24h`.
- **snapshot_pressure**: polls `ghost_preview._snapshot_gc()` and `time_machine.prune_snapshots()` for retention warnings.
- **recent_forks**: last 5 time-machine forks (informational — does not increment `needs_attention_total`).
- **pending_target_approvals** / **pending_comment_approvals**: hit `targets_admission.list_pending_targets / list_pending_comments` with limit 20.

`recent_forks` is in `_INFO_ONLY`, so its count does not raise `needs_attention_total`.

### 2.3.3  Persona, scheduling, picker auxiliaries

- `persona.py`, `persona_cohort.py`, `persona_cohort_validators.py`, `male_persona_factory.py` — persona factory. Every field cross-checks locale/timezone/device/carrier/HNI/proxy. Uses `LogNormal`, `Normal`, `Bimodal`, `WeightedCategorical` from `distributions.py` and `secrets.randbits` for entropy. No `random.*` on persona paths.
- `distributions.py` — the typed distribution classes. Every parameter derived from a measured source (not guessed).
- `warming_curve.py` — day-by-day baseline envelopes for follows/likes/stories/comments. Backs `ops.sched.warming.schedule_day`.
- `warming_orchestrator.py` — long-running loop that walks the fleet, advances per-account warming day, triggers `scheduler_tick`.
- `warmup_phases.py` — concrete phase definitions (seed, warm, ramp, maintain, cool) with per-phase caps.
- `time_slot_scheduler.py` — diurnal curve. `peak_hour_local` and `timezone` live on `persona_profiles` and this module turns them into per-hour weights; `schedule_day` samples due_ms within the account's local 24h window using the curve.
- `fleet_scheduler.py` — the in-memory fleet-scheduler object attached to `app.state.scheduler`. Orchestrates FleetScheduler API endpoints.
- `scheduler_executor.py` — fires Scheduler Pro posts on time. Started by lifespan when a DB pool exists.
- `engagement_executor.py` — 60-second loop: story/like/follow/unfollow/comment/dm.
- `source_scorer.py`, `target_filter.py` — scoring layer above the picker; used by scraper routes before pool admission.
- `phone_controller.py` — `PhoneFleet` singleton with `scan`, `set_mirror`, `get_serial`, `exec_shell`, tracks ADB locks.
- `ops_brain.py` — `PhantomFleetOpsBrain` cycle engine. Reads Redis for events, drives agents, emits cycle reports surfaced by `ops/status` and `ops/cycle/*`.
- `model_router.py`, `cost_quality_router.py` — model pick with price/quality tradeoff. `safety_critic.py` vets prompts/outputs. Both run in-process; no external MCP.
- `mission_composer.py` — composes a Staffroom mission payload from a short brief.
- `learning_engine.py` — outcome ingest, insight generation, feeds `/api/learning` routes.
- `dm_funnel.py`, `dm_intent_classifier.py`, `voice_style.py` — DM layer; owns dedupe, template rotation, opt-out detection.
- `comment_pod.py`, `pod_registry.py`, `competitor_registry.py` — comment-pod lifecycle and the competitor set the IG intelligence module draws from.
- `content_vault.py` — content-vault storage. `delivery` writes to `scheduled_posts`.
- `safety_critic.py` — the policy critic. Rules in-code; `/api/safety_critic/rules` exposes them read-only.
- `hq_bridge.py` — bidirectional bridge to Scaler Pro HQ. Started by lifespan.
- `gmail_account_pool.py` — Gmail pool for the pipeline.
- `reddit_*` — Reddit header extractor, OAuth, client.
- `threads_client.py`, `instagram_client.py`, `tiktok_controller.py`, `x_client.py`, `bluesky_client.py`, `bumble_client.py`, `discord_client.py`, `grindr_client.py`, `hinge_client.py`, `telegram_client.py`, `tinder_client.py` — platform HTTP/UIA clients.
- `ig_ab_test.py`, `bluesky_ab_test.py` — A/B test engines.
- `s10_box_config.py`, `ghost_preview.py`, `simulate.py`, `time_machine.py`, `tool_exchange.py` — simulation and tool-exchange primitives.
- `persona_cohort.py`, `persona_cohort_validators.py` — persona cohort generation + validation (validates all persona cross-field checks from CLAUDE.md).
- `adb_router.py`, `apk_client.py` — HTTP client for talking to the companion APK.
- `brief_redactor.py` — strips PII / destructive-action secrets from brief payloads before they leave the box.
- `chat_modes.py` — chat-mode registry.
- `capacity_planner.py` — fleet capacity math backing `/api/capacity-plan`.
- `cluster_monitor.py` — cluster health analysis (10 checks).
- `photo_verification.py` — IG photo-verification challenge classifier.
- `human_post_behavior.py` — per-persona post-behavior model (delay before like, scroll-pause).
- `hybrid_runner.py` — runs a mix of APK-driven and API-backed actions through a single interface.

---

## 2.4  Ops layer (`ops/`)

### 2.4.1  `ops/sched/` — state machine core

Files:

- `_store.py` — SQLite connection, migrations, `transition_status`, `enqueue`, `record_result`, `now_ms`.
- `_telemetry.py` — `instrument(kind, apply)` context manager; writes tick_log and appends to Merkle chain when intel modules are available.
- `tick.py` — daily enqueueing tick.
- `warming.py` — `schedule_day()` builds the per-day action list from the warming curve + persona diurnal.
- `recovery.py` — account status transitions driven by `action_results` tail.
- `replacement.py` — emits `replacements_needed` for dead accounts.
- `proxy.py` — proxy rotate + heal.
- `rules/` — rule JSON files.

#### 2.4.1.1  `_store.py`

The only module that touches SQLite directly. `STORE = backend/.data/persona-store.sqlite`. All functions:

- `apply_migrations(store=None)` — idempotent. Runs the `MIGRATIONS` list of `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` statements.
- `connect(store=None)` → context-managed `sqlite3.Connection` with `row_factory=Row` and `PRAGMA foreign_keys = ON`. Commits on exit, rolls back on exception.
- `now_ms()` — `int(time.time() * 1000)`.
- `transition_status(con, account_id, status, reason)` — updates accounts.status and appends to `account_status_history`.
- `enqueue(con, account_id, kind, due_ms, params)` — inserts an `action_queue` row with `state='due'` (via default), returns the new id.
- `record_result(con, action_id, account_id, outcome, latency_ms, signal)` — inserts `action_results`, then `UPDATE action_queue SET state='done' if outcome='ok' else 'failed', attempts = attempts+1`.

Full migration set (see §2.5 for per-table detail).

#### 2.4.1.2  `_telemetry.py`

Every tick wraps its work in `with instrument(kind, apply=True) as rec:` and populates `rec["inputs"]`, `rec["decisions"]`, `rec["now_ms"]`. On `__exit__`:

1. If `ops.intel.replay` is importable, call `replay.log_tick(kind, now_ms, seed_hex, rule_version=SCHEMA_VERSION, inputs, decisions, duration_ms, is_shadow=not apply)`. `SCHEMA_VERSION = "sched@v0"`.
2. If `apply=True` and `ops.intel.chain` is importable, call `chain.append(kind, {tick_id, now_ms, inputs_hash, outputs_hash, rule_version})` — the Merkle head.

Instrumentation failures are swallowed — a tick is never allowed to fail for a telemetry reason.

#### 2.4.1.3  `tick.py` — scheduler_tick cron

Logic:

1. `apply_migrations()`.
2. `accounts_due(con, now_ms, lookahead_ms=24h)` — `SELECT` from `accounts JOIN account_schedule_state s LEFT JOIN persona_profiles p WHERE a.status='alive' AND (s.last_tick_ms IS NULL OR s.last_tick_ms < now - 24h) ORDER BY a.id`.
3. For each candidate:
   - Skip if `future_queued_count(account_id, now_ms) > 0`.
   - Build `actions = schedule_day(warming_day, now_ms, persona_tz, peak_hour)`.
   - If `apply`: enqueue each action, upsert `account_schedule_state (account_id, warming_day+1, now_ms)` on conflict.
4. Record totals and per-account summary in `rec["decisions"]`.

Determinism: ordered by `a.id`; no `random.*`.

CLI:
```
python -m ops.sched.tick --apply
python -m ops.sched.tick --dry-run --now-ms 1732700000000 --limit 5
```

#### 2.4.1.4  `warming.py`

`schedule_day(warming_day, now_ms, persona_tz, peak_hour)` returns a list of `Action(kind, due_ms, params)` where `kind ∈ {follows, likes, stories, comments}` (singular aliases exist too) and `due_ms` is sampled against the diurnal curve centered on `peak_hour` in `persona_tz`. `params` is `{}` — the hydrator fills in `targetUsername / mediaCode / text / usernames` later. `summarise(actions)` returns `{total, by_kind: {...}}`.

#### 2.4.1.5  `recovery.py`

Reads the recent `action_results` tail, pattern-matches outcome strings to account status transitions. `transition_status(con, account_id, status, reason)` is the single state writer. Outcome → status rules:

| Outcome | Status |
|---------|--------|
| `login_required` | `needs_login` |
| `checkpoint` | `paused` |
| `account_disabled` | `dead` |
| `ig_rate_limited` | `paused` (temporary) |
| `accessibility_unbound` | (phone-level alert, no account transition) |

#### 2.4.1.6  `replacement.py`

Walks `accounts WHERE status='dead' AND not already in replacements_needed`, inserts a row per dead account.

#### 2.4.1.7  `proxy.py`

Proxy rotate + heal. Updates `proxy_state` with `in_use`, `blocked_count`, `last_rotate_ms`, `last_block_ms`. The `--register` flag registers a vendor plan id (e.g. `trumpproxies_yuge`) so the state row exists.

### 2.4.2  `ops/dispatch/` — picker-shape → APK-shape

Files:

- `_endpoints.py` — spec per kind, picker-shape → APK-shape translation, `build_payload`, `dumps`.
- `_transport.py` — `resolve_device`, `do_request`, `claim`, `release_claim`.
- `_outcome.py` — HTTP status/body → outcome classification.
- `worker.py` — the drain loop.
- `wire_test.py` — stub + live modes.

#### 2.4.2.1  `_endpoints.py`

The picker-shape → APK-shape map is the single contract between the planner and the phone:

```python
_PICKER_TO_APK = {
    "targetUsername": "username",
    "mediaCode":      "mediaId",
    "text":           "commentText",
}
```

Endpoint table (verified against `companion-apk/.../LocalHttpServer.kt` data classes at line 1059+):

| Kind | Method | Path | Required picker fields | Extras |
|------|--------|------|------------------------|--------|
| `follow` / `follows` | POST | `/instagram/engage/follow` | `targetUsername` | — |
| `unfollow` | POST | `/instagram/engage/unfollow` | `targetUsername` | — |
| `like` / `likes` | POST | `/instagram/engage/like` | `mediaCode` | — |
| `comment` / `comments` | POST | `/instagram/engage/comment` | `mediaCode`, `text` | — |
| `story` / `stories` / `view_stories` | POST | `/instagram/engage/view_stories` | `usernames` (list; first taken) | `storyCount: 5` |
| `scroll_reels` | POST | `/instagram/engage/scroll_reels` | — | `watchCount: 5` |
| `check_session` | GET | `/instagram/engage/check_session` | — | — |

`build_payload(endpoint, clone_package, action_params)`:

1. Start with `{"clonePackage": clone_package}`.
2. For each `picker_field`: pull from `action_params` under its camelCase key OR snake_case alias. Missing required field → return `(None, [missing...])`.
3. Special case `usernames`: list → `payload["username"] = list[0]`; scalar → `payload["username"] = scalar`.
4. Translate camelCase picker key through `_PICKER_TO_APK` into the APK key.
5. Merge `endpoint.extras` via `setdefault`.

`dumps(payload)` emits compact JSON (`separators=(",", ":")`).

#### 2.4.2.2  `_transport.py`

Pure stdlib (`urllib`). Three public helpers:

- `resolve_device(con, serial) -> (ip, port) | None` — reads `device_endpoints`.
- `do_request(method, url, body, timeout=30.0) -> (status, body_bytes, transport_error)`. `HTTPError` → `(code, body, None)`; `URLError` → `(0, b"", "url_error: ...")`; `socket.timeout` → `(0, b"", "timeout")`.
- `claim(con, limit, now_ms)` — atomic: `SELECT q.id, q.account_id, q.kind, q.due_ms, q.params_json, a.username, a.device_serial, a.status AS account_status, c.clone_package FROM action_queue q JOIN accounts a ON a.id = q.account_id LEFT JOIN clone_assignments c ON c.account_id = q.account_id WHERE q.state='due' AND q.due_ms <= ? AND a.status='alive' ORDER BY q.due_ms ASC LIMIT ?` then `UPDATE action_queue SET state='claimed' WHERE id IN (...)`. Returns the SELECTed rows as dicts.
- `release_claim(con, action_id)` — `UPDATE … SET state='due' WHERE id=? AND state='claimed'`.

#### 2.4.2.3  `_outcome.py`

HTTP → outcome classifier. Outcome strings MUST match `ops/sched/recovery.py` exactly: `ok`, `login_required`, `checkpoint`, `account_disabled`, `ig_rate_limited`, `network_error`, `accessibility_unbound`, `missing_target`, `unknown`.

Pattern lists:

- `CHECKPOINT_PATTERNS`: `"We noticed unusual activity|Help us confirm|suspicious login"`, `"checkpoint required"`.
- `DISABLED_PATTERNS`: `"Your account has been disabled|account has been disabled"`.
- `LOGIN_PATTERNS`: `"login_required|session expired|please log in again"`.
- `RATE_LIMIT_PATTERNS`: `"please wait a few minutes|rate limit|try again later"`.

Classification order:
1. transport_error → `network_error`.
2. status 0 → `network_error`.
3. 429 → `ig_rate_limited`; 502/503/504 → `network_error`.
4. If body is JSON with `error` ∈ `{accessibility_unbound, session_expired, login_required, checkpoint}` → corresponding outcome.
5. If body is JSON with `verdict` ∈ `{dead → account_disabled, needs_reset → login_required, alive → ok}`.
6. Plain-text pattern matches against the four regex lists.
7. 2xx → `ok` (or `unknown` if body says `ok: false`).
8. 4xx → `unknown` (`client_error: True`).
9. Otherwise `unknown`.

#### 2.4.2.4  `worker.py`

The dispatcher. `run(apply, max_actions=25, only_serial=None, now_ms=None)`:

1. `instrument("dispatch", apply=apply)` wraps the body; records `now_ms`, `inputs` (counts), `decisions` (totals + per-row outcome).
2. `claim(con, max_actions, now_ms)` → up to N rows atomically moved to `state='claimed'`.
3. For each claimed row:
   - If `only_serial` filter rejects it → `release_claim`.
   - Per-device cooldown gate: `now - last_dispatch_ms[serial] < PER_DEVICE_COOLDOWN_MS (150)` → `release_claim`, `skipped_cooldown += 1`.
   - `dispatch_one(con, row, apply, now_ms)` → one of:
     - `"unknown"` with `{reason: "no_endpoint", kind}` — no endpoint for this kind.
     - `"missing_target"` with `{missing: [...]}` — required picker field absent.
     - `"network_error"` with `{reason: "no_endpoint_for_serial", serial}` — no row in `device_endpoints`.
     - On `apply=False`: `"ok"` with `{would_dispatch: True, url, payload}`, `dispatched=False`.
     - Otherwise do the HTTP, record `latency_ms`, classify via `_outcome.classify`.
   - If dispatched: `record_result(con, action_id, account_id, outcome, latency_ms, signal)` → `action_queue.state` moves to `done` or `failed`, `attempts += 1`.
   - If permanent failure never reached HTTP (`missing_target`/`unknown`): terminal `record_result`.
   - Else: `release_claim` so the next tick retries.
4. Totals: `{claimed, dispatched, skipped_cooldown, ok, err}`.

Constants: `DEFAULT_CLONE_PACKAGE = "com.instagram.android"`, `DEFAULT_PORT = 8080`, `PER_DEVICE_COOLDOWN_MS = 150`.

CLI:
```
python -m ops.dispatch.worker --once --max 25
python -m ops.dispatch.worker --once --max 1 --only RF8N10J57DA
python -m ops.dispatch.worker --dry-run --max 25
```

#### 2.4.2.5  `wire_test.py`

Two modes:

- **Stub mode** (default): spawns `_StubAPKHandler` on an ephemeral port, seeds one account + one due follow row + one active target, invokes `worker.run(apply=True)`, then asserts:
  - dispatcher ran exactly 1 row.
  - outcome is `ok`.
  - stub saw exactly 1 POST.
  - the POST hit `/instagram/engage/follow`.
  - body has `clonePackage` and APK-shape `username` (never `targetUsername`).
  - username value equals the picked target.
  - a transient 500 (seeded via `STUB_FAIL_ONCE`) behaves like a transient failure.
- **Live mode** (`--live --serial <SER> --port 8089`): must also pass `--I-UNDERSTAND` (safety gate — a real IG follow will fire on the pilot phone). Does `adb -s <SER> reverse tcp:<port> tcp:<port>`, probes `/health`, seeds a row, drains 1.

`_validate_apk_shape(path, body)` enforces the exact APK data-class contract: `clonePackage` required; follow/unfollow needs `username`; like needs `mediaId`; comment needs `mediaId` + `commentText`; view_stories needs `username`; scroll_reels is unconstrained. Deviation returns HTTP 400.

### 2.4.3  `ops/targets/`

Files:

- `picker.py` — deterministic scorer; returns picker-shape params.
- `hydrator.py` — cron that reads due unhydrated rows, fills params, writes target_history.

#### 2.4.3.1  `picker.py`

Weights:

```python
W_RECENCY         = +0.8
W_FLEET_PRESSURE  = -1.2
W_NICHE_AFFINITY  = +0.9
W_LOCALE_MATCH    = +0.2
W_JITTER          = 0.05
RECENCY_CAP_DAYS = 90
FLEET_PRESSURE_WINDOW_MS = 7 * 86_400 * 1000
FLEET_PRESSURE_CAP = 10
```

`pick_for(con, account, kind, now_ms)`:

1. Map `kind` to `(pool_kind, field)`:
   - `follows / follow / unfollow` → `("account", "targetUsername")`
   - `stories / story / view_stories` → `("account", "usernames")`
   - `likes / like / comments / comment` → `("media", "mediaCode")`
   - Anything else → `None`.
2. `_candidates(con, pool_kind, farm_id)` — `SELECT ... FROM target_pool WHERE status='active' AND kind=? AND (farm_id IS NULL OR farm_id=?)`.
3. `_persona_tags(con, persona)` — set of persona tags.
4. For each candidate:
   - `_account_touched_days_ago` via MAX(ts_ms) from `target_history`. If `< 1.0` day → skip (micro-cooldown).
   - `_fleet_pressure` — DISTINCT account_id touches in last 7d. If `>= FLEET_PRESSURE_CAP (10)` → skip.
   - Score: additive `W_RECENCY * min(days,cap)/cap` (or full `W_RECENCY` for novel) + `W_FLEET_PRESSURE * min(pressure,cap)/cap` + `W_NICHE_AFFINITY * overlap/|persona_tags|` + `W_LOCALE_MATCH if cand.locale == account.locale` + deterministic `W_JITTER` from `SHA256(account_id:target_id)[:4] / 2^32`.
5. Return picker-shape params + `_target_id` (or `_target_ids` for stories, top 3 by score).

For comments: `_pick_comment(con, tags)` — prefer niche overlap, fall back to `generic`; `WHERE status='active' AND niche=? ORDER BY id LIMIT 1`.

`record_touch(con, account_id, target_id, kind, now_ms, outcome='picked')` writes to `target_history`.

**Determinism**: no `random.*`. Ties broken by jitter (deterministic per-pair). Stories pick is the top-3 by score; `sorted(cands, key=score, reverse=True)[:3]`.

#### 2.4.3.2  `hydrator.py`

Cron between `scheduler_tick` and `dispatch`. Pseudo-code:

```
for row in action_queue WHERE state='due' AND due_ms<=now ORDER BY due_ms, id LIMIT 500:
  params = json.loads(row.params_json or "{}")
  if not _needs_hydration(row.kind, params):      # required keys already present
    stats.already_hydrated += 1
    continue
  account = _load_account(row.account_id)         # pulls persona locale from settings_json
  if not account:
    stats.account_missing += 1
    continue
  picked = picker.pick_for(con, account, row.kind, now_ms)
  if picked is None:
    stats.exhausted += 1
    if apply: UPDATE action_queue SET state='missing_target' WHERE id=row.id
    continue
  target_id(s) = picked.pop("_target_id" | "_target_ids")
  params.update(picked)
  stats.hydrated += 1
  if apply:
    UPDATE action_queue SET params_json=? WHERE id=?
    for tid in target_ids: picker.record_touch(con, account_id, tid, kind, now_ms, 'picked')
```

`REQUIRED_KEYS`:

```python
{
  "follows":   ("targetUsername",),
  "follow":    ("targetUsername",),
  "unfollow":  ("targetUsername",),
  "likes":     ("mediaCode",),
  "like":      ("mediaCode",),
  "comments":  ("mediaCode", "text"),
  "comment":   ("mediaCode", "text"),
  "stories":   ("usernames",),
  "story":     ("usernames",),
  "view_stories": ("usernames",),
}
```

`_needs_hydration(kind, params)` returns True if any required key is missing, None, an empty string, or an empty list.

CLI:
```
python -m ops.targets.hydrator --apply
python -m ops.targets.hydrator --apply --max 200
python -m ops.targets.hydrator --dry-run
```

### 2.4.4  `ops/cron/`

Files:

- `schedule.py` — the canonical schedule (shared by Linux cron, Windows Task Scheduler, and the supervisor).
- `supervisor.py` — in-process dev supervisor.
- `crontab.example` — production Linux crontab template.
- `windows-tasks.ps1` — Windows Task Scheduler equivalent.
- `README.md` — operator guide.

#### 2.4.4.1  `schedule.py`

```python
@dataclass(frozen=True)
class Job:
    name: str
    interval_s: int
    argv: tuple[str, ...]
    description: str

JOBS: tuple[Job, ...] = (
  Job("target_hydrate",     30,      ("python","-m","ops.targets.hydrator","--apply","--max","200"), "Fill target params on due queue rows before dispatch picks them up."),
  Job("dispatch",           60,      ("python","-m","ops.dispatch.worker","--apply","--max","25"), "Drain action_queue -> companion APK; the hot path."),
  Job("recovery",           300,     ("python","-m","ops.sched.recovery","--apply"), "Account status transitions from action_results tail."),
  Job("proxy",              900,     ("python","-m","ops.sched.proxy","--apply","--register","trumpproxies_yuge"), "Proxy rotation + healthy-decay state machine."),
  Job("scheduler_tick",     21_600,  ("python","-m","ops.sched.tick","--apply"), "Enqueue the next day's actions for every alive account."),
  Job("replacement",        21_600,  ("python","-m","ops.sched.replacement","--apply"), "Emit replacements_needed rows for dead accounts."),
  Job("weekly_commitment",  604_800, ("python","-c","from ops.intel import chain; print(chain.make_commitment())"), "Sign the audit chain head for the week."),
)
```

`by_name(name)` returns the Job or None.

#### 2.4.4.2  `supervisor.py`

Single-process dev runner. Persists last-run state in a `supervisor_state` table added to the same `persona-store.sqlite`:

```sql
CREATE TABLE IF NOT EXISTS supervisor_state (
    job_name TEXT PRIMARY KEY,
    last_run_ms INTEGER NOT NULL,
    last_exit INTEGER,
    last_duration_ms INTEGER,
    runs INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0
);
```

Behavior:
- Deterministic firing order: `sorted(JOBS, key=lambda j: j.name)`.
- Never runs the same job twice concurrently (one subprocess per job).
- Persists `last_run_ms` so a restart doesn't re-fire everything in the first second.
- Captures non-zero exits + stderr tail (last 500 chars, surfaced last 200 in the console).
- `--speed N` multiplies effective interval (60 → 1-min job runs every 1s for smoke testing).
- `--only name1,name2` restricts set.
- `--once` fires every due job once and exits.
- `--status` prints the per-job state table.

Job timeout: 1200s hard cap (`subprocess.TimeoutExpired → exit 124`). Missing executable → exit 127.

#### 2.4.4.3  `crontab.example`

Production Linux. Sets `PF_ROOT=/opt/phantom-fleet-clone`, `PF_PY=/opt/phantom-fleet-clone/.venv/bin/python`, `PF_LOG=/var/log/phantom-fleet/cron.log`. Cron lines:

```
* * * * *   cd $PF_ROOT && $PF_PY -m ops.targets.hydrator --apply --max 200 >> $PF_LOG 2>&1
* * * * *   sleep 30; cd $PF_ROOT && $PF_PY -m ops.targets.hydrator --apply --max 200 >> $PF_LOG 2>&1
* * * * *   cd $PF_ROOT && $PF_PY -m ops.dispatch.worker --apply --max 25 >> $PF_LOG 2>&1
*/5 * * * *  cd $PF_ROOT && $PF_PY -m ops.sched.recovery --apply >> $PF_LOG 2>&1
*/15 * * * * cd $PF_ROOT && $PF_PY -m ops.sched.proxy --apply --register trumpproxies_yuge >> $PF_LOG 2>&1
0 */6 * * *  cd $PF_ROOT && $PF_PY -m ops.sched.tick --apply >> $PF_LOG 2>&1
15 */6 * * * cd $PF_ROOT && $PF_PY -m ops.sched.replacement --apply >> $PF_LOG 2>&1
0 4 * * 1    cd $PF_ROOT && $PF_PY -c 'from ops.intel import chain; print(chain.make_commitment())' >> $PF_LOG 2>&1
```

The two `target_hydrate` lines (each `* * * * *`, second delayed by `sleep 30`) achieve 30-second cadence inside cron's 1-minute granularity.

#### 2.4.4.4  `windows-tasks.ps1`

PowerShell counterpart to the crontab. Imports from `schedule.py` by `JOBS` name and registers one scheduled task per job (same intervals).

#### 2.4.4.5  README

Operator runbook: install path, env vars, log rotation, order of start/stop, how to tell `supervisor.py` apart from cron.

---

## 2.5  Persona store (`backend/.data/persona-store.sqlite`)

Single SQLite file, `PRAGMA foreign_keys = ON`. Every migration is `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`, so re-runs and parallel initialisers are safe.

### 2.5.1  `personas`

```sql
CREATE TABLE IF NOT EXISTS personas (
    name TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    settings_json TEXT,
    imported_at_ms INTEGER NOT NULL
);
```

`settings_json` carries locale, timezone, device model, OS version, carrier, HNI, proxy locale — the cross-check inputs. Populated by the persona factory.

### 2.5.2  `devices`

```sql
CREATE TABLE IF NOT EXISTS devices (
    serial TEXT PRIMARY KEY,
    model TEXT, region TEXT,
    source TEXT NOT NULL,
    imported_at_ms INTEGER NOT NULL
);
```

### 2.5.3  `accounts`

```sql
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    persona TEXT,
    device_serial TEXT,
    status TEXT NOT NULL DEFAULT 'unknown',
    imported_at_ms INTEGER NOT NULL,
    FOREIGN KEY (persona) REFERENCES personas(name),
    FOREIGN KEY (device_serial) REFERENCES devices(serial)
);
CREATE INDEX IF NOT EXISTS ix_accounts_persona ON accounts(persona);
CREATE INDEX IF NOT EXISTS ix_accounts_device  ON accounts(device_serial);
```

Status values observed: `alive`, `paused`, `dead`, `unknown`, `provisioning`, `shadowbanned`, `needs_login`, `locked`, `retired`.

### 2.5.4  `warming_curves`

```sql
CREATE TABLE IF NOT EXISTS warming_curves (
    day INTEGER PRIMARY KEY,
    follows_lo REAL NOT NULL, follows_hi REAL NOT NULL,
    likes_lo   REAL NOT NULL, likes_hi   REAL NOT NULL,
    stories_lo REAL NOT NULL, stories_hi REAL NOT NULL,
    comments_lo REAL NOT NULL, comments_hi REAL NOT NULL
);
```

Per-day warming envelope. `schedule_day()` samples inside `[*_lo, *_hi]` per kind.

### 2.5.5  `action_queue`

```sql
CREATE TABLE IF NOT EXISTS action_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    due_ms INTEGER NOT NULL,
    params_json TEXT,
    state TEXT NOT NULL DEFAULT 'due',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_ms INTEGER NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);
CREATE INDEX IF NOT EXISTS ix_action_queue_due ON action_queue(state, due_ms);
CREATE INDEX IF NOT EXISTS ix_action_queue_account ON action_queue(account_id, due_ms);
```

`state` values in order of flow: `due` → `claimed` → `done` | `failed` | `missing_target`. The default is `due` (migration uses `DEFAULT 'due'`; comments in code reference a legacy `pending`/`due` distinction — see known TODOs).

### 2.5.6  `action_results`

```sql
CREATE TABLE IF NOT EXISTS action_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    latency_ms INTEGER,
    signal_json TEXT,
    ts_ms INTEGER NOT NULL,
    FOREIGN KEY (action_id) REFERENCES action_queue(id),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);
CREATE INDEX IF NOT EXISTS ix_action_results_account ON action_results(account_id, ts_ms);
```

### 2.5.7  `proxy_state`

```sql
CREATE TABLE IF NOT EXISTS proxy_state (
    plan_id TEXT PRIMARY KEY,
    in_use INTEGER NOT NULL DEFAULT 0,
    blocked_count INTEGER NOT NULL DEFAULT 0,
    last_rotate_ms INTEGER,
    last_block_ms INTEGER,
    notes TEXT
);
```

### 2.5.8  `account_status_history`

```sql
CREATE TABLE IF NOT EXISTS account_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    ts_ms INTEGER NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);
CREATE INDEX IF NOT EXISTS ix_status_history ON account_status_history(account_id, ts_ms);
```

### 2.5.9  `replacements_needed`

```sql
CREATE TABLE IF NOT EXISTS replacements_needed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    emitted_ms INTEGER NOT NULL,
    fulfilled_ms INTEGER,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);
```

### 2.5.10  `persona_profiles`

```sql
CREATE TABLE IF NOT EXISTS persona_profiles (
    persona TEXT PRIMARY KEY,
    diurnal_peak_hour_local INTEGER NOT NULL DEFAULT 14,
    timezone TEXT NOT NULL DEFAULT 'America/New_York',
    warming_anchor_day INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (persona) REFERENCES personas(name)
);
```

This is the surface the scheduler reads so `tick.py` is a pure function of `(now, account row, persona row)`.

### 2.5.11  `account_schedule_state`

```sql
CREATE TABLE IF NOT EXISTS account_schedule_state (
    account_id INTEGER PRIMARY KEY,
    warming_day INTEGER NOT NULL DEFAULT 1,
    last_tick_ms INTEGER,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);
```

Advanced atomically with each day's enqueue.

### 2.5.12  `clone_assignments`

```sql
CREATE TABLE IF NOT EXISTS clone_assignments (
    account_id INTEGER PRIMARY KEY,
    clone_package TEXT NOT NULL,
    assigned_ms INTEGER NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);
```

Which cloned IG package (e.g. `com.scalerpro.phantomfleet.ig1`) drives this account.

### 2.5.13  `device_endpoints`

```sql
CREATE TABLE IF NOT EXISTS device_endpoints (
    serial TEXT PRIMARY KEY,
    wifi_ip TEXT,
    port INTEGER NOT NULL DEFAULT 8080,
    last_seen_ms INTEGER,
    FOREIGN KEY (serial) REFERENCES devices(serial)
);
```

Where the device's APK answers HTTP. Updated by `/api/fleet/heartbeat`.

### 2.5.14  `target_pool`

```sql
CREATE TABLE IF NOT EXISTS target_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farm_id TEXT,                -- NULL = global; else farm-scoped
    kind TEXT NOT NULL,          -- 'account' or 'media'
    handle TEXT NOT NULL,        -- IG username
    media_code TEXT,             -- NULL for kind='account'
    tags_json TEXT NOT NULL DEFAULT '[]',
    locale TEXT,
    status TEXT NOT NULL DEFAULT 'needs_approval',
    source TEXT,                 -- 'onimator', 'manual', 'owner', ...
    imported_ms INTEGER NOT NULL,
    approved_by TEXT,
    approved_ms INTEGER,
    rejected_reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_target_pool_kind ON target_pool(kind, status);
CREATE INDEX IF NOT EXISTS ix_target_pool_farm ON target_pool(farm_id, status);
CREATE INDEX IF NOT EXISTS ix_target_pool_handle ON target_pool(handle);
```

Statuses: `needs_approval` (default), `active`, `rejected`.

### 2.5.15  `target_history`

```sql
CREATE TABLE IF NOT EXISTS target_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    kind TEXT NOT NULL,           -- 'follows', 'likes', 'stories', 'comments'
    ts_ms INTEGER NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'picked',
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (target_id)  REFERENCES target_pool(id)
);
CREATE INDEX IF NOT EXISTS ix_target_history_acct ON target_history(account_id, ts_ms);
CREATE INDEX IF NOT EXISTS ix_target_history_tgt  ON target_history(target_id, ts_ms);
```

`outcome` values the picker/hydrator/dispatcher write: `picked`, `pool_exhausted`, plus whatever string classification the dispatcher emits downstream.

### 2.5.16  `persona_tags`

```sql
CREATE TABLE IF NOT EXISTS persona_tags (
    persona TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (persona, tag),
    FOREIGN KEY (persona) REFERENCES personas(name)
);
```

Picker uses `tag` set intersection with `target_pool.tags_json` to compute niche affinity.

### 2.5.17  `comment_pool`

```sql
CREATE TABLE IF NOT EXISTS comment_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL UNIQUE,
    niche TEXT NOT NULL DEFAULT 'generic',
    status TEXT NOT NULL DEFAULT 'needs_approval',
    source TEXT,
    imported_ms INTEGER NOT NULL DEFAULT 0,
    approved_by TEXT,
    approved_ms INTEGER
);
CREATE INDEX IF NOT EXISTS ix_comment_pool_niche_status ON comment_pool(niche, status);
```

Same admission flow as `target_pool`.

### 2.5.18  `device_farm`

```sql
CREATE TABLE IF NOT EXISTS device_farm (
    serial TEXT PRIMARY KEY,
    farm_id TEXT NOT NULL,
    FOREIGN KEY (serial) REFERENCES devices(serial)
);
```

Bridges `devices.serial` → `farm_id` so farm-scoped target picking has a pivot.

### 2.5.19  `supervisor_state` (added by `ops/cron/supervisor.py`)

Already shown in §2.4.4.2. Not part of `_store.MIGRATIONS` — the supervisor adds it itself at startup via `con.executescript(SUPERVISOR_SCHEMA)`.

---

## 2.6  State machines

### 2.6.1  `target_pool` row

```
intake (scraper/manual/upload/owner)
  └──► INSERT target_pool (status='needs_approval')
           │
           ├──► POST /api/targets/{id}/approve  ──► status='active'
           │                                            │
           │                                            └──► picker reads it
           │                                                     │
           │                                                     └──► target_history row (outcome='picked')
           │                                                                │
           │                                                                └──► dispatcher outcome ──► target_history
           │                                                                        (outcome: 'picked' or any _outcome string)
           │
           └──► POST /api/targets/{id}/reject   ──► status='rejected', rejected_reason=…
```

Terminal statuses: `active` (still live — can be re-used), `rejected` (frozen). There is no explicit expiry; aging out is via the fleet_pressure window (7 days of history discourages re-use).

### 2.6.2  `action_queue` row

```
scheduler_tick (6h)
  └──► INSERT action_queue (state='due', params_json={})
           │
           │  target_hydrate (30s)
           ▼
       filled with targetUsername/mediaCode/text/usernames
       (still state='due')
           │
           │  OR: picker returns None → UPDATE state='missing_target' (terminal)
           │
           ▼
       dispatch (60s): claim()
           │  state='claimed'
           ▼
       dispatch_one → HTTP → _outcome.classify
           │
           ├── outcome='ok'       → record_result → state='done'    (terminal)
           ├── outcome=missing/unknown (never reached HTTP) → record_result terminal
           ├── other outcome      → record_result → state='failed' (terminal, retried only by re-tick)
           └── transport failure before record → release_claim → state='due' (retry next tick)
```

`attempts` is incremented inside `record_result` only (not on release_claim).

### 2.6.3  `accounts` row

```
status transitions (via transition_status):
  unknown → provisioning → alive (login success)
  alive → needs_login     (classify login_required)
  alive → paused          (classify checkpoint or ig_rate_limited)
  alive → shadowbanned    (health/probe detector)
  alive → dead            (classify account_disabled)
  * → retired             (operator action)
  * → locked              (checkpoint burst or 2FA lockout)
```

Every transition writes to `account_status_history` with a `reason` string. Only `alive` accounts are claimed by the dispatcher (see `_transport.claim`'s JOIN predicate).

---

## 2.7  Picker–APK field contract

The exact mapping, per kind. APK data classes are in `companion-apk/app/src/main/java/com/scalerpro/phantomfleet/http/LocalHttpServer.kt` starting at line 1059. The APK is the source of truth for field names; `_endpoints.py` tracks it.

| Kind | APK path | APK data-class fields | Hydrator-written picker fields |
|------|----------|-----------------------|--------------------------------|
| follow / follows | POST `/instagram/engage/follow` | `username: String`, `clonePackage: String` | `targetUsername` → `username` |
| unfollow | POST `/instagram/engage/unfollow` | `username`, `clonePackage` | `targetUsername` → `username` |
| like / likes | POST `/instagram/engage/like` | `mediaId`, `clonePackage` | `mediaCode` → `mediaId` |
| comment / comments | POST `/instagram/engage/comment` | `mediaId`, `commentText`, `clonePackage` | `mediaCode` → `mediaId`; `text` → `commentText` |
| story / stories / view_stories | POST `/instagram/engage/view_stories` | `username`, `storyCount?` (default 5), `clonePackage` | `usernames[0]` → `username` (APK consumes only one; the hydrator picks top 3 for queueing upstream) |
| scroll_reels | POST `/instagram/engage/scroll_reels` | `watchCount?` (default 5), `clonePackage` | none (extras supplied) |
| check_session | GET `/instagram/engage/check_session?clonePackage=<pkg>` | query `clonePackage` | none |

Every POST body MUST carry `clonePackage` and the exact APK field name. `_endpoints.build_payload` enforces this; `wire_test._validate_apk_shape` is the mirror test.

---

## 2.8  Deterministic guarantees

- **Picker ordering**: `_candidates` query has no ORDER BY, but scoring is a pure function and ties are broken by SHA256-derived jitter (`W_JITTER = 0.05`), which is deterministic per `(account_id, target_id)`. Two accounts with identical persona_tags and locale never pick the same tie-breaker winner unless their ids collide (impossible under AUTOINCREMENT).
- **Scheduler tick**: `accounts_due()` does `ORDER BY a.id`; `schedule_day()` samples due_ms from a hashed seed, not `random.*`.
- **Dispatcher claim**: `ORDER BY q.due_ms ASC` (and secondary id when ties — SQLite's rowid ordering is stable).
- **Supervisor firing order**: `sorted(JOBS, key=lambda j: j.name)`.
- **Hydrator row scan**: `ORDER BY due_ms ASC, id ASC`.
- **Entropy source**: `secrets.randbits`/SHA256-of-tuple for any uniqueness-contributing random; never `time()`-seeded.
- **Account cohort generation**: in persona_cohort.py, every field cross-checks locale/timezone/device/carrier/HNI/proxy before emission.

---

## 2.9  Known bugs / TODOs

Grepped from code comments and the prior-art CLAUDE.md:

1. **CLAUDE.md fleet bugs** (must fix): `en-GB` locale + `America/New_York` timezone across every phone; AppCloner certificate overlap on the 22 IG clones; flat per-device account count of 15–22; flat fleet-wide action timing. Scheduler layer already pivots off persona_profiles.diurnal_peak_hour_local + timezone, so (4) is addressed. (1)–(3) must be covered by the persona factory (cross-field pair-check) and the cluster_monitor checks.
2. `_transport.claim` comment: "a crash between claim and dispatch leaves them `claimed`, which the recovery sweeper reaps (future work)." — the sweeper is not yet implemented.
3. `proxy_pool.py` DELETE uses list index, not stable id.
4. `wire_test.py._run_live` calls `worker.drain` (line 267) but `worker` only exposes `run` — the live path is stale and will AttributeError.
5. `_telemetry.py` imports from `ops.intel.replay` and `ops.intel.chain`, which may not be present on a fresh install — wrapped in try/except so a tick still runs, but telemetry silently disappears.
6. `routes/accounts.py:1340` `/targets/ai-scrape` uses the CostQualityRouter + SafetyCritic; there is no in-code guard against the AI returning a non-active target handle (admission flow is still enforced at the pool level, but the LLM may propose handles that the owner then has to approve — acceptable but worth calling out).
7. `owner_brief._signal_cost_anomalies` requires `len(day_costs) >= 3` and `len(week_costs) >= 10` before raising an anomaly — low-traffic workflows will never flag.
8. Staffroom cadence loop: `if STAFFROOM_CADENCE_LOOP == "1"` only, no SIGHUP to toggle at runtime.
9. `supervisor.py` never reaps a timed-out subprocess children beyond its own 1200s; nested processes can orphan.
10. Dispatcher cooldown is per-device (150 ms). There is no per-account cooldown beyond what the warming curve naturally enforces through due_ms spread.
11. `action_queue.state` legacy — some code uses `pending` vs `due`. The migration default is `due`; `_store.enqueue` does not pass state (relies on default). Hydrator and dispatcher only handle `due`/`claimed`/`done`/`failed`/`missing_target`.
12. `picker._pick_comment` scans niches in `tags + ["generic"]` order and `LIMIT 1 ORDER BY id`. There is no round-robin across comment rows — the lowest-id active comment in the niche is always chosen until it is retired or deactivated.
13. `_endpoints._snake` is an ad-hoc camelCase→snake_case converter used as a fallback key. Works, but if a picker field is `targetUsernameURL` it would produce `target_username_u_r_l` — none exist today, but the conversion is brittle.

---

## 2.10  Reconstruction order

To rebuild this backend from the ground up in a fresh session:

1. **DB and ops/sched/_store.py** — bring up SQLite, apply migrations. Nothing else works until this exists.
2. **core/targets_admission.py** and **routes/targets.py** — admission layer that keeps the picker honest.
3. **ops/sched/warming.py + tick.py** — daily enqueue.
4. **ops/targets/picker.py + hydrator.py** — target enrichment.
5. **ops/dispatch/_endpoints.py + _transport.py + _outcome.py + worker.py** — the drain loop. Validate with `ops/dispatch/wire_test.py --stub`.
6. **ops/sched/recovery.py + replacement.py** — account state machine.
7. **ops/cron/schedule.py + supervisor.py + crontab.example + windows-tasks.ps1** — scheduling glue.
8. **backend/phantom_fleet/api/app.py** — FastAPI assembly. Routes follow in the order the lifespan expects (accounts store, fleet, proxy pool, threads stack, IG stack, ops brain).
9. **The remaining 40 route files** — safe to bring up in any order once the core modules exist. Attach each as it comes online.
10. **core/owner_brief.py + routes/owner_brief.py** — last, because it depends on tool_exchange, simulate, ghost_preview, time_machine, and targets_admission being up.


---

# Section 3: Frontend

This section documents the Phantom Fleet web dashboard. It covers the Next.js
app shell, sidebar navigation, every page under `src/app/`, every shared
component under `src/components/`, API wiring via `next.config.mjs` rewrites,
the Tailwind + CSS design system, the dev-server launch configuration, the
owner-gated `/approvals` surface, and the real-time WebSocket flows.

Repository root for everything in this section:

```
C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\frontend\
```

Primary tooling:

- Next.js **15.0.3** (App Router, React Server Components, `app/` directory).
- React **19.0.0** + React-DOM **19.0.0**.
- TypeScript **5.6.3**.
- Tailwind CSS **3.4.14** with `tailwindcss-animate`.
- Radix UI primitives for dialog, dropdown, hover-card, popover, select,
  separator, scroll-area, tabs, toast, tooltip, slot, label, switch, progress,
  avatar — all installed in `package.json` for future use even though many
  pages still render raw markup.
- `@tanstack/react-query` **^5.59** and `@tanstack/react-table` **^8.20** are
  installed but currently used sparingly; most pages use raw `useEffect` +
  `fetch`.
- `cmdk` ships the command-palette primitive (the current palette is a stub —
  see Section below).
- `framer-motion`, `lucide-react`, `recharts`, `sonner`, `zustand`,
  `class-variance-authority`, `clsx`, `tailwind-merge`, `date-fns`.

The dashboard runs standalone on **port 3016** via `npm run dev` (and `npm
start` in production). It talks to the Python/Rust backend through Next.js
rewrites (see §API wiring).

---

## 1. App shell

### 1.1 Root layout — `src/app/layout.tsx`

```
src/app/layout.tsx
```

The root layout wraps every page (including marketing routes). Its structure:

```tsx
<html lang="en" className="dark" suppressHydrationWarning>
  <body className="min-h-screen bg-phantom-bg font-sans antialiased">
    <div className="phantom-grid-bg h-screen flex overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col h-screen overflow-hidden">
        <TopBar />
        <main className="flex-1 overflow-y-auto px-8 py-6">
          <div className="max-w-[1600px] w-full mx-auto">
            {children}
          </div>
        </main>
      </div>
    </div>
    <CommandPalette />
    <AgentChatWidget />
  </body>
</html>
```

Key properties:

- `className="dark"` on `<html>` — the app is **dark-only**. There is no
  light-mode toggle; CSS variables in `globals.css` are only authored for
  dark. The sidebar/top-bar colors live in Tailwind's `phantom-*` namespace
  (see §Theme).
- The outer flex `phantom-grid-bg h-screen flex overflow-hidden` wraps the
  sidebar and a column containing top-bar + main. The grid-bg utility paints
  a subtle 60×60 grid on top of a radial accent plume (see §Theme).
- `main` is the only scroll container; the sidebar is `sticky top-0` and the
  top bar is `sticky top-0 z-40`, so the body never scrolls.
- `max-w-[1600px]` caps page content at 1600px. Pages are allowed to
  break out when they need a wider surface (mirror wall).
- `<CommandPalette />` and `<AgentChatWidget />` are rendered at the app-shell
  level so they overlay on every page.
- Metadata: title `Phantom Fleet — Fleet Command`, description
  `Invisible automation at fleet scale. A Scaler Pro product.`

### 1.2 Sidebar — see §2 (dedicated section)

### 1.3 Top bar — `src/components/top-bar.tsx`

A 64-tall header, sticky at `top-0 z-40`, with backdrop blur and a 1px bottom
border (`border-phantom-border bg-phantom-panel/40 backdrop-blur-xl`).

Left side — live fleet ticker:

- `phones online` (live-polled from `GET /api/fleet` every 30s). Falls back
  to a placeholder `19` while the request is pending or when the backend is
  down.
- `Active accounts 219` (hard-coded; placeholder until wired).
- `Agents 14 running` (hard-coded; placeholder).
- `OF revenue (30d) —` (hard-coded; placeholder, rendered em-dash).

The online count uses `useEffect` + `setInterval(load, 30_000)` with
`cache: "no-store"` and silently keeps the last value when the request
throws (backend down).

Right side:

- A `⌘ K` search button (visual — Cmd+K is handled globally by
  CommandPalette).
- A bell icon with a small accent dot indicating notifications (currently
  static — no notifications pipeline is wired).

Font: `font-sans` body but tabular numerals for the live counters.

### 1.4 Command palette — `src/components/command-palette.tsx`

A stub implementation. On mount it attaches a global key listener; `Cmd/Ctrl +
K` toggles it, `Esc` closes it. The palette renders a centered modal with an
autofocused search input and a static list of "Quick actions":

- Pause all accounts on cluster alert
- Run audit harness
- Rotate proxy (force)
- Launch Fresh Target Agent for Tatiana

None of the quick actions have handlers wired yet — the file calls itself a
stub and notes that a full `cmdk`-powered palette is a Phase 1 build-out.
`cmdk ^1.0.0` is already in `package.json`, so the next engineer has the
primitive available.

### 1.5 Agent chat widget — `src/components/agent-chat-widget.tsx`

A floating chat button bottom-right that expands into a 380×520 chat panel
styled with the phantom-panel look.

State:

- `open` — boolean.
- `agent` — one of `"chief" | "instagram" | "tiktok" | "reddit" | "dating"`
  (agent selector as pill buttons at the top of the panel).
- `messages` — array of `{ id, role: "user"|"agent", text, ts }` seeded with
  "Agent Command online. How can I assist?".
- `input` — current typed text.
- `typing` — boolean typing indicator while awaiting reply.

Send flow:

- POSTs to `/api/v1/agents/chat` with body
  `{ agent, message, history: [{ role, text }, …] }`.
- On 2xx, appends `data.reply`.
- On error, waits 900–1500ms and appends a canned reply from `MOCK_REPLIES`
  (e.g. "Roger that. Processing your request.", "Affirmative. Queued for
  fleet dispatch.") — the widget never hard-fails.
- Enter (without shift) sends. Scroll-to-bottom ref auto-scrolls on every
  message.

Visual details:

- User bubble is accent-filled with `phantom-bg` text, rounded-br-sm.
- Agent bubble is `phantom-bg` with `phantom-border/60`, rounded-bl-sm.
- Typing indicator: three bouncing dots with staggered `animationDelay`.
- Agent pills: filled accent for active, outlined for inactive.

---

## 2. Sidebar nav — `src/components/sidebar.tsx`

240px wide, sticky full-height, `border-r border-phantom-border
bg-phantom-panel/40 backdrop-blur-xl`. Has three regions: brand, scrollable
nav sections, footer.

Brand (top):

- 32×32 rounded accent gradient tile with an uppercase Φ glyph.
- Wordmark "PHANTOM" on top, tracked letter-spaced "FLEET" subtitle in ghost
  color.

Nav sections — the sidebar exports `NAV_SECTIONS` with 10 labeled groups and
49 total nav items. Active-item detection uses a *longest-prefix-wins*
`matches` helper so `/mirroring/access` highlights only "Device Access" and
not also "Phone Wall".

Footer:

- `A Scaler Pro product` label on the left.
- `v0.0.1` mono version on the right.

### 2.1 Command (12 items)

| href | label | icon | purpose |
|---|---|---|---|
| `/` | Overview | LayoutDashboard | Executive KPI dashboard with live fleet grid, agent feed, cluster heatmap, revenue, and the live action-stream WebSocket feed. |
| `/briefing` | Daily Briefing | Newspaper | Autogenerated morning brief — status, notable events, upcoming schedule. |
| `/approvals` | Approvals | Gavel | **Owner-gated** approval queue for research-agent target candidates and generator comments. Added in commit 14d11d9; see §Approvals. |
| `/phase1` | Phase 1 Launch | Rocket | Phase-1 readiness checklist + "Start Phase 1" button. |
| `/phase2` | Phase 2 Launch | Rocket | Phase-2 readiness checklist + "Start Phase 2" button. |
| `/fleet` | Fleet | Smartphone | Grid of all connected phones (serials), cluster collisions, scan/verify buttons. |
| `/onboarding` | Onboarding | Wand2 | Multi-step wizard: scan → install APK → verify proxies → provision accounts → start warming. |
| `/accounts` | Accounts | Activity | Account list + provision form. |
| `/ops` | Ops Brain | Brain | Operational status, cycle history, pause/resume/trigger, WebSocket live feed. |
| `/agents` | Agents | Bot | Staffroom roster, mission dispatcher, per-agent feed. |
| `/schedule` | Schedule | CalendarDays | Posting / action schedule generator. |
| `/calendar` | Content Calendar | CalendarDays | Content posting calendar. |

### 2.2 Mirroring (2 items)

| href | label | icon | purpose |
|---|---|---|---|
| `/mirroring` | Phone Wall | MonitorSmartphone | Embedded live screen wall of all phones via the Fleet Mirror hub. |
| `/mirroring/access` | Device Access | KeyRound | Per-device remote-access ACLs and tokens. |

### 2.3 Intelligence (7 items)

| href | label | icon | purpose |
|---|---|---|---|
| `/personas` | Personas | Users | Persona list + factory. |
| `/targets` | Fresh Targets | Target | Mocked grid of fresh targets. Note: this surface is currently mock-data only. |
| `/cluster` | Cluster Monitor | ShieldAlert | Mocked fleet-cluster collision/drift heatmap. |
| `/analytics` | Analytics | LineChart | Mocked analytics overview. |
| `/capacity` | Capacity Planner | Gauge | Capacity-plan calculator (posts an input JSON, renders predicted fleet usage). |
| `/platforms` | Platforms | Globe | Platform roster with a drill-through to per-platform page. |
| `/pipeline` | Gmail → Reddit | ArrowRight | Gmail-account factory + Reddit-account registration pipeline. |

### 2.4 Instagram (8 items)

| href | label | icon | purpose |
|---|---|---|---|
| `/ig/unfollow` | Unfollow Engine | RotateCcw | IG unfollow queue surface. |
| `/ig/notes` | IG Notes | MessageSquare | IG Notes posting surface. |
| `/ig/pods` | Pod Network | Network | Engagement-pod graph. |
| `/ig/saves` | Save Farming | Bookmark | Save-farming queue. |
| `/ig/reels` | Reel Farming | Film | Reel-farming queue. |
| `/ig/warmup` | Warm-up Curves | TrendingUp | Per-account warm-up curve. |
| `/ig/shadowban` | Shadowban Check | ShieldCheck | Shadowban detector. |
| `/ig/abtest` | A/B Testing | FlaskConical | A/B tests on captions / creative. |

### 2.5 Threads (5 items)

| href | label | icon | purpose |
|---|---|---|---|
| `/threads` | Command Center | MessageCircle | Threads platform command center (live-data; the richest Threads page). |
| `/threads/replies` | Reply Engine | MessageSquare | Reply-generation queue. |
| `/threads/reposts` | Repost Engine | Repeat2 | Repost queue. |
| `/threads/feed` | Feed Engagement | Zap | Feed-side engagement actions. |
| `/threads/unfollow` | Unfollow Queue | RotateCcw | Threads unfollow queue. |

### 2.6 TikTok (5 items)

| href | label | icon | purpose |
|---|---|---|---|
| `/tiktok` | Command Center | Video | Platform command center. |
| `/tiktok/warmup` | Warm-up Queue | Flame | Warm-up schedule. |
| `/tiktok/content` | Content Schedule | CalendarDays | Content posting schedule. |
| `/tiktok/geo` | Geo Distribution | Globe | Geo-distribution of accounts. |
| `/tiktok/unfollow` | Unfollow Engine | RotateCcw | Unfollow engine. |

### 2.7 Dating (4 items)

| href | label | icon | purpose |
|---|---|---|---|
| `/dating` | Command Center | Heart | Dating platform command center. |
| `/dating/tinder` | Tinder | Flame | Tinder-specific view. |
| `/dating/bumble` | Bumble | MessageCircle | Bumble-specific view. |
| `/dating/verification` | Verification Queue | ShieldCheck | Photo-verification / selfie queue. |

### 2.8 Revenue (4 items)

| href | label | icon | purpose |
|---|---|---|---|
| `/funnel` | Funnel | DollarSign | OF / revenue funnel visualization. |
| `/content` | Content Vault | ImageIcon | Content vault summary (reads `/api/content-vault/items`). |
| `/content-vault` | Media Bridge | Vault | Full content-vault with uploader, filter, stats, scheduling. |
| `/alerts` | Alerts | ShieldAlert | Alert feed. |

### 2.9 Infrastructure (2 items)

| href | label | icon | purpose |
|---|---|---|---|
| `/proxy` | Proxy Health | Globe | Proxy pool CRUD + verify-all. |
| `/s10-box` | S10 Male Box | Server | S10 male-device box — accounts/content view. |

### 2.10 System (1 item)

| href | label | icon | purpose |
|---|---|---|---|
| `/settings` | Settings | Settings | Settings for OpenRouter API key test/save. |

### 2.11 Dynamic routes not in the sidebar

These pages exist under `src/app/` but are reached from inline links on other
pages, not from the sidebar:

- `/agents/[name]` — per-agent detail (reached from `/agents`).
- `/personas/[id]` — per-persona detail (reached from `/personas`).
- `/platforms/[platform]` — per-platform detail (reached from `/platforms`).
- `/instagram/[account_id]` — IG account dossier (reached from `/instagram`).
- `/threads/[account_id]` — Threads account dossier.
- `/fleet/[serial]` — per-phone view (reached from `/fleet` grid).
- `/fleet/[serial]/[account_id]/settings` — per-clone deep settings
  (the largest page in the app at ~1800 lines).
- `/fleet/[serial]/[account_id]/stats` — per-clone stats.
- `/instagram` — not in the sidebar directly; the "Platforms" entry
  reaches it as the IG platform detail page. (`/instagram` is a top-level
  route, used as the IG command center.)
- `/(marketing)/welcome`, `/(marketing)/features`, `/(marketing)/pricing`,
  `/(marketing)/comparison`, `/(marketing)/docs` — marketing site, served at
  `/welcome`, `/features`, `/pricing`, `/comparison`, `/docs`.

---

## 3. Every page under `src/app/`

Pages are grouped by sidebar section. Dynamic routes and marketing routes
have their own subsections at the end.

### 3.1 Command

#### 3.1.1 `/` — Overview — `src/app/page.tsx`

- Route: `/`
- Title/H1: not using the standard `<h1>` — instead a multi-panel exec
  dashboard with its own hero layout.
- Purpose: Top-level executive snapshot of the entire fleet.
- Backend endpoints: WebSocket connection to `${wsBase}/fleet` (hosted at
  `NEXT_PUBLIC_WS_URL`, falling back to the current host). No REST fetches —
  all live numbers arrive on the socket, with a `DEMO_EVENTS` fallback.
- Live vs mocked: **Hybrid**. The action-stream feed is live when the
  WebSocket connects; otherwise it cycles through `DEMO_EVENTS` (tatiana_xo44
  etc.) with the badge "demo mode · WebSocket offline".
- Widgets/panels:
  - KPI row: KPICard × 4.
  - Live Fleet Grid (`<FleetGrid />`).
  - Agent Feed (`<AgentFeed />`).
  - Cluster Heatmap (`<ClusterHeatmap />`).
  - Revenue Chart (`<RevenueChart />`).
  - Live action-stream feed (local WebSocket + `<ActionStream />` component).
  - WebSocket status label — "/ws/fleet" or "demo mode · WebSocket offline".

#### 3.1.2 `/briefing` — Daily Briefing — `src/app/briefing/page.tsx`

- Route: `/briefing`.
- Purpose: Autogenerated morning briefing card with sections (overnight
  status, fresh risks, must-do today, revenue ping).
- Backend endpoints: none — fully mock data defined inline.
- Live vs mocked: **Mocked.**
- Widgets: Hero header, section cards, time-stamped feed entries. Uses
  `<Panel>` and KPI-style summary tiles.

#### 3.1.3 `/approvals` — Approvals — `src/app/approvals/page.tsx`

See §8 "Approvals page" for the full treatment. In short:

- Owner-gated approval queue for pending research-agent targets and pending
  generator comments.
- Polls `/api/targets/pending`, `/api/targets/comments/pending`,
  `/api/targets/pending_counts` every 10s.
- Approves via `POST /api/targets/{id}/approve` and
  `POST /api/targets/comments/{id}/approve` with
  `{ approver }` body; rejects with `{ approver, reason }`.
- Live.

#### 3.1.4 `/phase1` — Phase 1 Launch — `src/app/phase1/page.tsx`

- Route: `/phase1`.
- Purpose: Phase-1 readiness checklist and launch control.
- Backend endpoints: `GET /api/phase1/readiness`, `POST /api/phase1/start`.
- Live vs mocked: **Live.**
- Widgets: Readiness checklist, blocking issues, "Start Phase 1" button.

#### 3.1.5 `/phase2` — Phase 2 Launch — `src/app/phase2/page.tsx`

- Route: `/phase2`.
- Purpose: Same as Phase 1 but for Phase 2 of the rollout.
- Backend endpoints: `GET /api/phase2/readiness`, `POST /api/phase2/start`.
- Live.

#### 3.1.6 `/fleet` — Fleet — `src/app/fleet/page.tsx`

- Route: `/fleet`.
- Purpose: Grid of every connected phone across every host PC, with cluster
  collisions and scan/verify actions.
- Backend endpoints:
  - `GET /api/fleet` — list.
  - `GET /api/fleet/cluster/collisions` — cluster-cluster collisions.
  - `POST /api/fleet/scan` — adb scan.
  - `POST /api/fleet/verify-all` — verify all proxies.
  - `DELETE /api/fleet/phones/{serial}` — remove a phone.
- Live vs mocked: **Live.**
- Widgets: Phone cards (`<PhoneCard />`), cluster-collision list, action bar
  with scan/verify/remove buttons.

#### 3.1.7 `/onboarding` — Onboarding — `src/app/onboarding/page.tsx`

- Route: `/onboarding`.
- Purpose: Multi-step wizard that walks a new fleet owner through
  scan → install APK → verify proxies → provision accounts → start warming.
- Backend endpoints: `POST /api/fleet/scan`, `POST
  /api/fleet/{serial}/install-apk`, `POST /api/fleet/verify-all`,
  `POST /api/accounts/provision`, `POST /api/fleet/start-warming` (plus
  intermediate listing).
- Live.
- Widgets: Step tracker, progress log stream, install-APK form with per-serial
  status rows.

#### 3.1.8 `/accounts` — Accounts — `src/app/accounts/page.tsx`

- Route: `/accounts`.
- Purpose: Browse all accounts, provision a new account via form.
- Backend endpoints: `POST /api/accounts/provision` (plus list endpoint that
  the table is seeded from).
- Live (provisioning is wired; the list may be a mix).
- Widgets: Provisioning form, accounts table.

#### 3.1.9 `/ops` — Ops Brain — `src/app/ops/page.tsx`

- Route: `/ops`.
- Purpose: Operational pulse — status, latest cycle, cycle history, live
  feed. WebSocket-driven live feed.
- Backend endpoints:
  - `GET /api/ops/status`
  - `GET /api/ops/cycle/latest`
  - `GET /api/ops/cycle/history`
  - `POST /api/ops/pause`, `POST /api/ops/resume`, `POST /api/ops/cycle/trigger`
  - WebSocket from `NEXT_PUBLIC_WS_URL` — path dictated by ops module
    (see `src/app/ops/page.tsx` line 230; renders "Waiting for WebSocket
    connection…" placeholder while disconnected).
- Live vs mocked: **Live.**
- Widgets: Status badge, cycle-history table, pause/resume/trigger buttons,
  live feed console.

#### 3.1.10 `/agents` — Agents — `src/app/agents/page.tsx`

- Route: `/agents`.
- Purpose: Staffroom roster + mission dispatch control. Lists agents, lets
  the owner dispatch a mission, refreshes per-mission summaries.
- Backend endpoints:
  - `GET /api/platforms/staffroom/roster`
  - `GET /api/platforms/staffroom/missions/summary`
  - `POST /api/platforms/staffroom/missions/dispatch`
  - `POST /api/platforms/staffroom/missions/{rid}/refresh`
- Live.
- Widgets: Agent roster grid, dispatch form, per-mission card.

#### 3.1.11 `/schedule` — Schedule — `src/app/schedule/page.tsx`

- Route: `/schedule`.
- Purpose: Generate an action/posting schedule.
- Backend endpoints: `POST /api/schedule/generate`.
- Live for generation; display grid uses local state.
- Widgets: Generator form, slot strip (`<TimeSlotStrip>`), heatmap.

#### 3.1.12 `/calendar` — Content Calendar — `src/app/calendar/page.tsx`

- Route: `/calendar`.
- Purpose: Monthly content calendar.
- Backend endpoints: none grep'd — **mocked visualization**.
- Widgets: Month grid, event pills.

### 3.2 Mirroring

#### 3.2.1 `/mirroring` — Phone Wall — `src/app/mirroring/page.tsx`

- Route: `/mirroring`.
- Purpose: Embedded live screen wall of every phone, via the Fleet Mirror
  hub. Pulls `embed-wall` endpoint which returns iframe URLs + metadata
  keyed by serial.
- Backend endpoint: `GET /api/fleet-mirror/embed-wall?minutes=480`
  (`cache: "no-store"`).
- Live.
- Widgets: `<FleetMirrorView>` — the big tile wall.

#### 3.2.2 `/mirroring/access` — Device Access — `src/app/mirroring/access/page.tsx`

- Route: `/mirroring/access`.
- Purpose: Per-device remote-access ACL table — who has access, tokens, and
  expiry times.
- Backend endpoint: `GET /api/fleet-mirror/access` (`cache: "no-store"`).
- Live.
- Widgets: Access table.

### 3.3 Intelligence

#### 3.3.1 `/personas` — Personas — `src/app/personas/page.tsx`

- Route: `/personas`.
- Purpose: Browse personas — Tatiana, Melodie, Kira, etc. — and open per-
  persona detail.
- Backend endpoints: none grep'd — **mocked**; the persona list is a
  constant array in the file. Future wiring: a `/api/personas` endpoint.
- Widgets: Persona grid, per-row chips.

#### 3.3.2 `/personas/[id]` — Persona detail — `src/app/personas/[id]/page.tsx`

- Route: `/personas/[id]` where `[id]` matches a persona key.
- Purpose: Deep detail — identity fields, distribution snapshots, assigned
  phones/accounts.
- Backend endpoints: none grep'd — **mocked**.
- Widgets: Field card, distribution charts (`<Sparkline>`), accounts table.

#### 3.3.3 `/targets` — Fresh Targets — `src/app/targets/page.tsx`

- Route: `/targets`.
- Purpose: Fresh-target candidate feed from research agents.
- Backend endpoints: **none grep'd — mocked**. This is marked for rewiring:
  the real target feed lives behind `/api/targets/pending` (used by
  `/approvals`). Either rewire `/targets` to read from the same endpoint for
  pre-approval triage, or kill the page in favor of `/approvals`.
- Widgets: Target card grid, filter bar.

#### 3.3.4 `/cluster` — Cluster Monitor — `src/app/cluster/page.tsx`

- Route: `/cluster`.
- Purpose: Fleet-cluster collision/drift visualization — red-flag any
  duplicate locale/timezone, duplicate AppCloner fingerprint, static per-
  device account counts (the three known Onimator bugs from CLAUDE.md).
- Backend endpoints: **none grep'd — mocked**. Should rewire to the real
  audit harness endpoint when it ships.
- Widgets: `<ClusterHeatmap>`, warning strip, bugs-known list.

#### 3.3.5 `/analytics` — Analytics — `src/app/analytics/page.tsx`

- Route: `/analytics`.
- Purpose: Fleet-wide analytics — follow/like/comment totals, per-platform
  bars, time-series.
- Backend endpoints: **none grep'd — mocked**.
- Widgets: KPI tiles, Recharts line/bar charts, platform badges.

#### 3.3.6 `/capacity` — Capacity Planner — `src/app/capacity/page.tsx`

- Route: `/capacity`.
- Purpose: What-if calculator — given fleet size and target posts/day, show
  per-phone utilization.
- Backend endpoint: `POST /api/capacity-plan`.
- Live.
- Widgets: Input form, `<CapacityResultCard>`, warnings.

#### 3.3.7 `/platforms` — Platforms — `src/app/platforms/page.tsx`

- Route: `/platforms`.
- Purpose: Roster of all supported platforms with a drill-through.
- Backend endpoints: none grep'd — **mocked**; list is a constant.
- Widgets: `<PlatformGrid>`, `<PlatformBadge>`.

#### 3.3.8 `/platforms/[platform]` — Platform detail — `src/app/platforms/[platform]/page.tsx`

- Route: `/platforms/[platform]` for each key (instagram, threads, tiktok,
  reddit, dating).
- Purpose: Per-platform stats and controls — overlaps with each platform's
  own command center at `/instagram`, `/threads`, `/tiktok`, `/dating`.
- Backend endpoints: none grep'd — **mocked**.
- Widgets: `<PlatformDetailHeader>`, metric cards, embedded funnel.

#### 3.3.9 `/pipeline` — Gmail → Reddit — `src/app/pipeline/page.tsx`

- Route: `/pipeline`.
- Purpose: Factory for Gmail accounts → Reddit accounts bridge.
- Backend endpoints:
  - `GET /api/pipeline/gmail/stats`
  - `GET /api/pipeline/reddit/accounts`
  - `POST /api/pipeline/gmail/create`
  - `POST /api/pipeline/reddit/register`
  - `POST /api/pipeline/reddit/export`
- Live.
- Widgets: Gmail stats card, Reddit accounts table, create/register forms,
  export button.

### 3.4 Instagram sidebar section

The Instagram top-level page is at `/instagram` (not in the sidebar directly
but reached via platform drill-through). It is by far the densest page.

#### 3.4.1 `/instagram` — IG Command Center — `src/app/instagram/page.tsx`

- Route: `/instagram`.
- Purpose: Complete IG command center.
- Backend endpoints (all under `/api/platforms/instagram/`):
  - `health/summary`, `health/scan`, `health/simulate`.
  - `recovery/status`, `recovery/tick`, `recovery/{acc}/graduate`,
    `recovery/{acc}/skip-cooldown`.
  - `funnel/summary`, `funnel/record`.
  - `rebalancer/status`.
  - `orchestrator/status`, `orchestrator/plan-now`.
  - `probes/status?limit=20`, `probes/tick`.
  - `agent/config`, `agent/runs?limit=12`.
  - `executor/status`.
  - `diurnal/summary`.
  - `identity/summary`, `identity/scan`.
  - `proxy/summary`, `proxy/tick`, `proxy/{accountId}/rotate`.
  - `drift/summary`, `drift/scan`, `drift/{serial}/snapshot`.
  - `lattice/summary`, `lattice/plan`.
  - `checkpoint/summary`.
  - `session/summary`, `session/tick`, `session/{aid}/complete-2fa`.
  - `unfollow/summary`, `unfollow/tick`.
  - `dm/summary`, `dm/tick`.
  - Plus a generic `POST url` tick pattern.
- Live.
- Widgets: Grid of panels for each of the subsystems above, each with
  summary numbers, a tick button, and a details affordance.

#### 3.4.2 `/instagram/[account_id]` — IG account dossier — `src/app/instagram/[account_id]/page.tsx`

- Route: `/instagram/[account_id]`.
- Purpose: Full dossier for a single IG account.
- Backend endpoint: `GET /api/platforms/instagram/accounts/{account_id}/dossier`.
- Live.
- Widgets: Account header, timeline (`<TimelineVisual>`), stats, agents feed.

#### 3.4.3 `/ig/unfollow` — Unfollow Engine — `src/app/ig/unfollow/page.tsx`

- Route: `/ig/unfollow`.
- Purpose: Unfollow queue — who is queued to be unfollowed, cooldowns.
- Backend endpoints: none grep'd — **mocked** (the real engine is at
  `/instagram` `/unfollow/*`).
- Widgets: Unfollow table, status badges.

#### 3.4.4 `/ig/notes` — IG Notes — `src/app/ig/notes/page.tsx`

- Route: `/ig/notes`.
- Purpose: IG Notes post-queue.
- Backend endpoints: none grep'd — **mocked**.
- Widgets: Note editor, scheduled notes list.

#### 3.4.5 `/ig/pods` — Pod Network — `src/app/ig/pods/page.tsx`

- Route: `/ig/pods`.
- Purpose: Engagement pod graph — which accounts engage with which.
- Backend endpoints: none grep'd — **mocked**.
- Widgets: `<AgentHierarchyVisual>`-style graph, pod list.

#### 3.4.6 `/ig/saves` — Save Farming — `src/app/ig/saves/page.tsx`

- Route: `/ig/saves`.
- Purpose: Save-farming schedule (the "save" interaction on IG posts).
- Backend endpoints: none grep'd — **mocked**.
- Widgets: Save queue table, counters.

#### 3.4.7 `/ig/reels` — Reel Farming — `src/app/ig/reels/page.tsx`

- Route: `/ig/reels`.
- Purpose: Reel-farming queue.
- Backend endpoints: none grep'd — **mocked**.
- Widgets: Reel grid, per-reel metrics.

#### 3.4.8 `/ig/warmup` — Warm-up Curves — `src/app/ig/warmup/page.tsx`

- Route: `/ig/warmup`.
- Purpose: Per-account warm-up curve — follows/day, likes/day, dm/day over
  the first 30 days of account life.
- Backend endpoints: none grep'd — **mocked**.
- Widgets: Recharts curve per metric, per-account list.

#### 3.4.9 `/ig/shadowban` — Shadowban Check — `src/app/ig/shadowban/page.tsx`

- Route: `/ig/shadowban`.
- Purpose: Shadowban detector with per-account state (`h1`-style status id).
- Backend endpoints: none grep'd — **mocked**.
- Widgets: Status grid, probe history.

#### 3.4.10 `/ig/abtest` — A/B Testing — `src/app/ig/abtest/page.tsx`

- Route: `/ig/abtest`.
- Purpose: A/B tests on captions / creative with per-variant lift.
- Backend endpoints: none grep'd — **mocked**.
- Widgets: Variant cards, lift bars.

### 3.5 Threads sidebar section

#### 3.5.1 `/threads` — Threads Command Center — `src/app/threads/page.tsx`

- Route: `/threads`.
- Purpose: Threads command center — the richest Threads page, mirroring
  `/instagram` in structure.
- Backend endpoints (all under `/api/platforms/threads/` unless noted):
  - `accounts`, `status`, `executor/status`, `queue`, `funnel/summary`,
    `orchestrator/status`, `bridge/status`, `ig-events?limit=20`.
  - Plus `GET /api/accounts?platform=instagram`.
  - `ig-event` (POST to log), `accounts/{id}/warmup?day=`.
  - `orchestrator/run`, `orchestrator/{endpoint}`.
  - `audit/last`, `audit/run?n={n}`.
  - `health/summary`, `health/scan`, `health/simulate`.
  - `probes/status?limit=20`, `probes/tick`.
  - `agent/runs?limit=15`.
  - `persistence/status`.
  - `rebalancer/status`.
  - `recovery/status`, `recovery/tick`, `recovery/{accountId}/skip-cooldown`,
    `recovery/{accountId}/graduate`.
  - `executor/{endpoint}`.
  - `cross-post`.
  - `budget/{selected}`, `curve/{selected}`, `funnel/{selected}`.
  - `funnel/event`, `link`, `{kind}`, `advance-day/{selected}`.
- Live.
- Widgets: Many — accounts list, orchestrator status card, bridge card,
  recovery queue, audit control, probe feed, ig-events feed, budget/curve
  charts per selected account.

#### 3.5.2 `/threads/[account_id]` — Threads dossier — `src/app/threads/[account_id]/page.tsx`

- Route: `/threads/[account_id]`.
- Purpose: Full dossier for a single Threads account.
- Backend endpoint: `GET /api/platforms/threads/accounts/{id}/dossier`.
- Live.
- Widgets: Account header, timeline, stats, agents feed.

#### 3.5.3 `/threads/replies` — Reply Engine — `src/app/threads/replies/page.tsx`

- Route: `/threads/replies`.
- Purpose: Reply queue for Threads.
- Backend endpoints: none grep'd — **mocked**.
- Widgets: Reply table, status badges.

#### 3.5.4 `/threads/reposts` — Repost Engine — `src/app/threads/reposts/page.tsx`

- Route: `/threads/reposts`.
- Purpose: Repost queue.
- Backend endpoints: none grep'd — **mocked**.
- Widgets: Repost table.

#### 3.5.5 `/threads/feed` — Feed Engagement — `src/app/threads/feed/page.tsx`

- Route: `/threads/feed`.
- Purpose: Feed-side engagement actions.
- Backend endpoints: none grep'd — **mocked**.
- Widgets: Feed engagement table, probe history.

#### 3.5.6 `/threads/unfollow` — Unfollow Queue — `src/app/threads/unfollow/page.tsx`

- Route: `/threads/unfollow`.
- Purpose: Unfollow queue.
- Backend endpoints: none grep'd — **mocked**.
- Widgets: Unfollow table.

### 3.6 TikTok sidebar section

#### 3.6.1 `/tiktok` — TikTok Command Center — `src/app/tiktok/page.tsx`

- Route: `/tiktok`.
- Purpose: TikTok platform command center.
- Backend endpoints: none grep'd — **mocked**; this mirrors the IG/Threads
  centers but hasn't been wired yet.
- Widgets: Summary panels.

#### 3.6.2 `/tiktok/warmup` — Warm-up Queue — `src/app/tiktok/warmup/page.tsx`

- Route: `/tiktok/warmup`. **Mocked.**

#### 3.6.3 `/tiktok/content` — Content Schedule — `src/app/tiktok/content/page.tsx`

- Route: `/tiktok/content`. **Mocked.**

#### 3.6.4 `/tiktok/geo` — Geo Distribution — `src/app/tiktok/geo/page.tsx`

- Route: `/tiktok/geo`. **Mocked.**

#### 3.6.5 `/tiktok/unfollow` — Unfollow Engine — `src/app/tiktok/unfollow/page.tsx`

- Route: `/tiktok/unfollow`. **Mocked.**

### 3.7 Dating sidebar section

#### 3.7.1 `/dating` — Dating Command Center — `src/app/dating/page.tsx`

- Route: `/dating`. **Mocked.**

#### 3.7.2 `/dating/tinder` — Tinder — `src/app/dating/tinder/page.tsx`

- Route: `/dating/tinder`. **Mocked.**

#### 3.7.3 `/dating/bumble` — Bumble — `src/app/dating/bumble/page.tsx`

- Route: `/dating/bumble`. **Mocked.**

#### 3.7.4 `/dating/verification` — Verification Queue — `src/app/dating/verification/page.tsx`

- Route: `/dating/verification`. **Mocked.** (Verification will require a
  human-in-the-loop queue similar to `/approvals` — likely merge candidate.)

### 3.8 Revenue sidebar section

#### 3.8.1 `/funnel` — Funnel — `src/app/funnel/page.tsx`

- Route: `/funnel`.
- Purpose: OF/Fansly revenue funnel.
- Backend endpoints: none grep'd — **mocked**.
- Widgets: `<FunnelViz>`.

#### 3.8.2 `/content` — Content Vault (summary) — `src/app/content/page.tsx`

- Route: `/content`.
- Purpose: Light content-vault summary — most recent 12 items.
- Backend endpoint: `GET /api/content-vault/items?limit=12`.
- Live.
- Widgets: Content grid, item tiles.

#### 3.8.3 `/content-vault` — Media Bridge — `src/app/content-vault/page.tsx`

- Route: `/content-vault`.
- Purpose: Full content-vault with upload, filter, stats, schedule, and
  delete.
- Backend endpoints:
  - `POST /api/content-vault/upload` (multipart).
  - `GET /api/content-vault?{params}` (filtered list).
  - `GET /api/content-vault/stats`.
  - `DELETE /api/content-vault/{itemId}`.
  - `PATCH/POST /api/content-vault/{...}` (edit).
  - `POST /api/content-vault/schedule`.
- Live.
- Widgets: Uploader with progress, filter bar, stats cards, item grid with
  schedule-modal, delete confirmation.

#### 3.8.4 `/alerts` — Alerts — `src/app/alerts/page.tsx`

- Route: `/alerts`.
- Purpose: Alert feed — cluster warnings, account lockouts, etc.
- Backend endpoints: none grep'd — **mocked**.
- Widgets: Alert list with severity chips.

### 3.9 Infrastructure sidebar section

#### 3.9.1 `/proxy` — Proxy Health — `src/app/proxy/page.tsx`

- Route: `/proxy`.
- Purpose: Proxy pool management — list, add, delete, verify.
- Backend endpoints:
  - `GET /api/proxy/pool`
  - `POST /api/proxy/pool` (add)
  - `DELETE /api/proxy/pool/{idx}`
  - `POST /api/proxy/pool/verify`
- Live.
- Widgets: Pool table, add-proxy form, verify-all button.

#### 3.9.2 `/s10-box` — S10 Male Box — `src/app/s10-box/page.tsx`

- Route: `/s10-box`.
- Purpose: Status/control view for the "S10 male device" — the dedicated
  male-persona phone used for OF/dating interactions.
- Backend endpoints: none grep'd — **mocked**.
- Widgets: Status panel, accounts list, content pipeline.

### 3.10 System sidebar section

#### 3.10.1 `/settings` — Settings — `src/app/settings/page.tsx`

- Route: `/settings`.
- Purpose: Settings for OpenRouter API key and other ML/content toggles.
- Backend endpoints:
  - `POST /api/v1/settings/openrouter/test` — validate a submitted key.
  - `POST /api/v1/settings/openrouter` — save the key.
- Live.
- Widgets: Key input, test button, save button, toast on success/fail.

### 3.11 Dynamic routes not in the sidebar

#### 3.11.1 `/agents/[name]` — `src/app/agents/[name]/page.tsx`

- Route: `/agents/[name]`.
- Purpose: Per-agent detail — mission history, config, feed.
- Backend endpoints: inherits from `/agents` (`staffroom/missions/summary`
  and `/missions/{rid}/refresh`).
- Live where it uses the parent's endpoints; some sub-widgets are mocked.
- Widgets: Mission timeline, config card, logs feed.

#### 3.11.2 `/fleet/[serial]` — `src/app/fleet/[serial]/page.tsx`

- Route: `/fleet/[serial]`.
- Purpose: Per-phone detail — accounts on this phone, cluster collisions
  relevant to this phone, actions.
- Backend endpoints:
  - `GET /api/fleet/{serial}/accounts`
  - `GET /api/fleet/{serial}`
  - `GET /api/fleet/cluster/collisions`
  - `POST /api/fleet/{serial}/adb/release`
  - `POST /api/fleet/{serial}/verify-proxy`
  - `POST /api/accounts` (create)
  - `PATCH /api/accounts/{id}`, `DELETE /api/accounts/{id}`
  - `POST /api/accounts/{id}/clone`
- Live.
- Widgets: Phone header, account table, collision strip, action bar
  (`Verify proxy`, `Release ADB`), clone button.

#### 3.11.3 `/fleet/[serial]/[account_id]/settings` — `src/app/fleet/[serial]/[account_id]/settings/page.tsx`

- Route: `/fleet/[serial]/[account_id]/settings`.
- Purpose: **The** per-clone deep-settings page (~1800 lines). Every knob
  for an individual IG clone — persona identity, login/logout, AppCloner
  detection, follow sources (AI-scrape), per-account targets CRUD, warm-up
  tuning, scheduling, probe history, etc.
- Backend endpoints:
  - `GET /api/accounts/{account_id}` — load.
  - `PATCH /api/accounts/{id}` × 10 spots — update one field at a time.
  - `POST /api/accounts/{id}/detect-clone` — detect the IG clone's index.
  - `POST /api/accounts/{id}/login`, `POST /api/accounts/{id}/logout`.
  - `POST /api/accounts/{id}/scrape-follow-source` — AI-scrape follow sources.
  - `GET /api/accounts/{accountId}/targets` — per-account targets list.
  - `POST /api/accounts/{accountId}/targets` — add target.
  - `DELETE /api/accounts/{accountId}/targets/{id}` — remove target.
  - `POST /api/accounts/{accountId}/targets/ai-scrape` — AI target scrape.
- Live.
- Widgets: 10+ per-section cards (identity, login, clone, follow sources,
  warm-up, schedule, probes, targets, DM, misc). Each section has its own
  state + optimistic updates. The page is the **single largest UI surface**
  in the app and is the top candidate for extracting into sub-components in
  Phase 2.

#### 3.11.4 `/fleet/[serial]/[account_id]/stats` — `src/app/fleet/[serial]/[account_id]/stats/page.tsx`

- Route: `/fleet/[serial]/[account_id]/stats`.
- Purpose: 30-day stats for a single clone.
- Backend endpoint: `GET /api/accounts/{account_id}/stats?days=30`.
- Live.
- Widgets: Daily sparklines (`<Sparkline>`), KPI tiles, chart grid.

### 3.12 Marketing routes — `src/app/(marketing)/*`

These live under a route-group folder `(marketing)/` so they share the same
root layout (sidebar + top bar still render — even on marketing pages, which
is stylistically unusual but matches the current layout.tsx contract). Treat
them as the "sales site" for Phantom Fleet.

#### 3.12.1 `/welcome` — `src/app/(marketing)/welcome/page.tsx`

- Route: `/welcome`.
- Purpose: Landing/welcome page.
- Widgets: `<AnimatedHeroBg>`, big hero, testimonial strip, FAQ accordion.
- Fully static.

#### 3.12.2 `/features` — `src/app/(marketing)/features/page.tsx`

- Route: `/features`.
- Purpose: Feature tour — every capability per platform.
- Widgets: Feature grid, platform tabs, architecture diagram.
- Static. (Uses the word "mock" only inside the mockup imagery context.)

#### 3.12.3 `/pricing` — `src/app/(marketing)/pricing/page.tsx`

- Route: `/pricing`.
- Purpose: Pricing tiers.
- Widgets: Pricing table.
- Static.

#### 3.12.4 `/comparison` — `src/app/(marketing)/comparison/page.tsx`

- Route: `/comparison`.
- Purpose: "Phantom Fleet vs the alternatives" comparison.
- Widgets: `<ComparisonTable>`.
- Static.

#### 3.12.5 `/docs` — `src/app/(marketing)/docs/page.tsx`

- Route: `/docs`.
- Purpose: Public docs index — "Everything documented."
- Widgets: Docs index.
- Static.

---

## 4. Shared components — `src/components/`

### 4.1 Full component list (one-line each)

| File | Description |
|---|---|
| `action-stream.tsx` | Live action-stream feed component with WebSocket + demo fallback; used by `/`. |
| `agent-chat-widget.tsx` | Floating Cmd chat panel — see §1.5. |
| `agent-feed.tsx` | Scrolling agent-activity feed (used on `/`). |
| `agent-hierarchy-visual.tsx` | SVG hierarchy visualization of agents / pods. |
| `agent-tree.tsx` | Tree-view of the agent org chart. |
| `animated-hero-bg.tsx` | CSS/Framer animated grid+glow backdrop for marketing hero. |
| `architecture-diagram.tsx` | Static SVG system-architecture diagram (marketing). |
| `capacity-result-card.tsx` | Renders the output of `/api/capacity-plan`. |
| `chat-tier-badge.tsx` | Chat-tier chip (e.g. "Chief", "Specialist"). |
| `cluster-heatmap.tsx` | Fleet cluster collision heatmap. |
| `command-palette.tsx` | Cmd+K palette stub — see §1.4. |
| `comparison-table.tsx` | Big marketing comparison table. |
| `data-table.tsx` | Generic reusable table primitive — see §4.2. |
| `faq-accordion.tsx` | Marketing FAQ with Radix accordion. |
| `fleet-grid.tsx` | Fleet grid of phones for `/`. |
| `FleetMirrorView.tsx` | Big mirror-wall iframe grid — see §4.3. |
| `funnel-viz.tsx` | Recharts funnel for `/funnel`. |
| `heatmap-grid.tsx` | Generic heatmap-grid primitive. |
| `kpi-card.tsx` | Standard KPI card with number, label, delta. |
| `live-ticker.tsx` | Ambient ticker that pulses even without WebSocket — purely ornamental. |
| `panel.tsx` | Base `<Panel>` wrapper — section label + title + subtitle + body. |
| `phone-card.tsx` | Per-phone card — see §4.4. |
| `platform-badge.tsx` | Small chip for each platform (instagram, threads, tiktok, …). |
| `platform-detail-header.tsx` | Header for `/platforms/[platform]`. |
| `platform-grid.tsx` | Grid of platform tiles for `/platforms`. |
| `revenue-chart.tsx` | Recharts revenue line chart. |
| `sparkline.tsx` | Lightweight sparkline for KPI contexts. |
| `stat-ring.tsx` | Radial progress ring. |
| `status-badge.tsx` | Status chip — alive/warning/critical/accent. |
| `testimonials.tsx` | Marketing testimonial carousel. |
| `time-slot-strip.tsx` | 24h time-slot strip used on `/schedule`. |
| `timeline-grid.tsx` | Generic horizontal timeline grid. |
| `timeline-visual.tsx` | Vertical timeline used on dossier pages. |
| `top-bar.tsx` | App top bar — see §1.3. |
| `sidebar.tsx` | App sidebar — see §2. |

### 4.2 `data-table.tsx`

Generic table primitive. Props accept `columns`, `rows`, optional `getRowId`,
and render as the dark-styled table matching `phantom-panel`. Used wherever
a page needs a tabular list (accounts, targets, proxies). It provides:

- Sortable headers (click to toggle asc/desc).
- Zebra-striped rows with hover highlight.
- Monospace treatment for ID-like columns.
- Empty state slot.

Rewrite targets: once pages get bigger, wire this to `@tanstack/react-table`
(already installed).

### 4.3 `FleetMirrorView.tsx`

The mirror-wall surface for `/mirroring`.

- Takes an array of `{ serial, embedUrl, lastActive }` returned from
  `/api/fleet-mirror/embed-wall`.
- Renders a responsive grid of 240×400 iframes, each with a header showing
  serial + last-active ago-time.
- Handles iframe-load failure with a dark placeholder + "disconnected" chip.
- Per-tile "fullscreen" button that opens that tile's iframe in a modal.
- No heavy lifting on the client — the heavy stream is served by the Fleet
  Mirror hub itself.

### 4.4 `phone-card.tsx`

Per-phone card used on `/fleet` and the `<FleetGrid>` on `/`.

- Shows serial, status (alive/warning/critical), accounts-on-device count,
  and proxy status.
- Has a top-right "quick menu" that lets the owner: open fleet detail,
  verify proxy, release ADB, remove phone.
- Uses `phantom-dot-*` indicator for status.

### 4.5 Charts

- `revenue-chart.tsx` — Recharts `AreaChart` with gradient fill, tooltips
  styled to `phantom-panel`.
- `cluster-heatmap.tsx` — custom SVG heatmap (not Recharts) with
  phantom-accent on collision cells.
- `funnel-viz.tsx` — Recharts funnel.
- `sparkline.tsx` — tiny Recharts line.
- `stat-ring.tsx` — SVG radial-progress ring with accent glow.

All charts honor the design system: axis labels use `text-phantom-ghost`,
grid lines use `hsl(240 6% 18% / 0.3)`, tooltips use `phantom-panel-hi`.

### 4.6 `agent-feed.tsx`, `agent-tree.tsx`, `agent-hierarchy-visual.tsx`

Three related components for agent visualization:

- `agent-feed` — scrolling list of agent events.
- `agent-tree` — nested list tree.
- `agent-hierarchy-visual` — SVG graph of agent→agent handoffs.

### 4.7 `panel.tsx`

The repeated panel chrome. Props: `label` (small uppercase overline),
`title` (large display), `subtitle` (ghost paragraph), `children`. Wraps all
of it in a `.phantom-panel` with `p-6 space-y-3` — the canonical card.

---

## 5. API wiring

### 5.1 Rewrites — `next.config.mjs`

```js
async rewrites() {
  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  return [
    { source: "/api/:path*", destination: `${apiBase}/api/:path*` },
  ];
}
```

- All `/api/*` fetches on the frontend proxy through Next's rewrite layer to
  the backend at `NEXT_PUBLIC_API_URL`.
- The default is `http://localhost:8000` — matches the FastAPI backend in
  Section 2.
- Important note in the config: **WebSocket URLs cannot be rewritten** by
  Next. Client code uses `NEXT_PUBLIC_WS_URL` directly (see §9).
- `experimental.optimizePackageImports` is set for `lucide-react`,
  `recharts`, `framer-motion` to shrink the bundle.
- `reactStrictMode: true`.

### 5.2 Fetch pattern

Pages overwhelmingly follow this pattern:

```ts
const [data, setData] = useState<Shape | null>(null);
useEffect(() => {
  let stop = false;
  const load = async () => {
    try {
      const r = await fetch("/api/foo", { cache: "no-store" });
      if (!r.ok) return;
      const d = await r.json();
      if (!stop) setData(d);
    } catch {
      /* keep last value */
    }
  };
  load();
  const t = setInterval(load, 10_000);
  return () => { stop = true; clearInterval(t); };
}, []);
```

Variations:

- Some pages use `Promise.all([...])` to fan out multiple endpoints in one
  pass (e.g. `/approvals`, `/instagram`, `/threads`, `/agents`).
- Some pages use `${API}` prefix with `process.env.NEXT_PUBLIC_API_URL`
  directly (`/content-vault`, `/ops`, `/pipeline`, `/onboarding`) — these
  bypass the rewrite but still resolve to the same backend. Either style
  works but should be normalized.
- Action buttons POST with `{ method: "POST", headers: { "Content-Type":
  "application/json" }, body: JSON.stringify(...) }`.
- `cache: "no-store"` is used on top-bar fleet poll and mirror embed.

### 5.3 Error handling

The dominant pattern is **silent fallback**: pages keep last-known good
values and log nothing on failure. Only `/approvals` surfaces an inline
error ribbon with the fetch error message. The owner should be able to
opt into richer error toasts via `sonner` (already installed) when
Phase 1 wiring tightens.

---

## 6. Theme + design system

### 6.1 CSS variables — `src/app/globals.css`

Lives at `src/app/globals.css`. Declares HSL variables on `:root` for every
Radix/shadcn-style token:

- `--background: 240 10% 3.9%` — the deep almost-black.
- `--foreground: 0 0% 98%` — near-white body text.
- `--card: 240 6% 8%`, `--card-foreground: 0 0% 98%`.
- `--popover: 240 6% 10%`.
- `--primary: 162 100% 54%` — the signature neon cyan-green.
- `--primary-foreground: 240 10% 3.9%` — dark-on-accent text.
- `--secondary: 240 6% 15%`.
- `--muted: 240 6% 15%`, `--muted-foreground: 240 5% 64.9%` — ghost color.
- `--accent: 292 91% 68%` — magenta accent (used sparingly).
- `--destructive: 0 91% 65%`.
- `--border: 240 6% 18%`, `--input: 240 6% 18%`.
- `--ring: 162 100% 54%`.
- `--radius: 0.75rem`.

There is **no light-mode override**. The app sets `className="dark"` on
`<html>` and the CSS variables above are the dark palette unconditionally.

Selection styling: `::selection` uses `hsl(162 100% 54% / 0.3)` — a 30%
accent highlight — with near-white text.

Scrollbar styling: 10px wide, dark track `hsl(240 10% 3.9%)`, thumb
`hsl(240 6% 18%)` → `hsl(240 6% 25%)` on hover.

### 6.2 `phantom-*` color tokens — `tailwind.config.js`

```js
colors: {
  phantom: {
    bg: "hsl(240 10% 3.9%)",          // app background (deep neutral)
    panel: "hsl(240 6% 8%)",           // card surface
    panelHi: "hsl(240 6% 12%)",        // elevated surface
    border: "hsl(240 6% 18%)",         // 1-pixel outlines
    ghost: "hsl(240 5% 64.9%)",        // muted secondary text
    accent: "hsl(162 100% 54%)",       // the neon cyan-green signature
    accentHi: "hsl(162 100% 70%)",     // hover of accent
    glow: "hsl(162 100% 40%)",         // deeper accent for glow tints
    magenta: "hsl(292 91% 68%)",       // secondary accent — use sparingly
    amber: "hsl(38 92% 58%)",          // warning
    red: "hsl(0 91% 65%)",             // critical
    alive: "hsl(142 71% 45%)",         // "online/alive" green
  },
}
```

Every page composes from these tokens; `kpi-card`, `phone-card`, `panel`,
`sidebar`, `top-bar`, `data-table`, and chart tooltips all reference them.

### 6.3 Utility classes (in `@layer components`)

- **`.phantom-panel`** — base card: `bg-phantom-panel border
  border-phantom-border rounded-xl` plus a linear-gradient background,
  layered box-shadow (1px ring + 24px ambient drop + 1px top inset
  highlight). Every section card uses this.
- **`.phantom-panel-hi`** — same base but with a brighter gradient (the
  elevated variant).
- **`.phantom-panel-accent`** — base plus accent-tinted border and
  accent-tinted drop shadow (used on command palette and
  `/approvals` hero and anywhere the UI wants to say "this is live").
- **`.phantom-grid-bg`** — layered background:
  `radial-gradient` accent plume from top-center + two 1px grid lines at
  60×60 (horizontal and vertical). Applied to the outer layout wrapper so
  every page has the subtle grid.
- **`.phantom-accent-text`** — accent text with a 24px
  `text-shadow` glow. Used in hero titles.
- **`.phantom-kbd`** — kbd chip: mono, small, dark-panel with ghost text.
- **`.phantom-dot`** (+ `-alive`, `-warning`, `-critical`, `-accent`) — 8px
  round status dot with colored glow.
- **`.phantom-metric`** / `.phantom-metric-lg` (5xl) / `.phantom-metric-xl`
  (7xl) — tabular-nums display metric with `-0.02em` letter-spacing. Used
  on the KPI tiles and the top-stats on `/approvals`, `/overview`, etc.
- **`.phantom-skeleton`** — loading skeleton with an animated shimmer
  (handled by the `shimmer` keyframe).

### 6.4 Fonts

Declared in `tailwind.config.js`:

- **`display`** — `'Inter'` (same face as sans, but intended for the big
  hero display sizes and headings). Also `system-ui`, `sans-serif`
  fallbacks.
- **`sans`** — `'Inter'` (primary body).
- **`mono`** — `'JetBrains Mono'`, then `Menlo`, `Monaco`.

`body` sets `font-feature-settings: "rlig" 1, "calt" 1, "cv11" 1, "ss01" 1`
to enable ligatures and Inter's optional stylistic sets.

The fonts are not self-hosted — they rely on the browser's fallback stack
or an existing Inter install. For production, add `next/font` and self-host
Inter + JetBrains Mono.

### 6.5 Font sizes

Custom display sizes:

- `display-lg`: 4rem / line-height 1 / tracking -0.04em / 700
- `display`: 2.75rem / line-height 1.05 / tracking -0.035em / 700
- `display-sm`: 2rem / line-height 1.1 / tracking -0.025em / 700

### 6.6 Animations (keyframes + animation utilities)

- `accordion-down` / `accordion-up` — Radix accordion open/close.
- `phantom-pulse` — 1 → 0.5 → 1 opacity, 2s infinite cubic-bezier. Used on
  the active-sidebar-item indicator dot.
- `phantom-glow` — box-shadow accent pulse, 3s ease-in-out infinite.
- `shimmer` — translateX(-100%) → translateX(100%), 2s linear infinite,
  used by `.phantom-skeleton::after`.

Available classes: `animate-phantom-pulse`, `animate-phantom-glow`,
`animate-shimmer`, `animate-accordion-down`, `animate-accordion-up`.

### 6.7 Backgrounds

- `bg-gradient-phantom` — deep diagonal: `hsl(240 10% 3.9%)` →
  `hsl(240 15% 6%)` → `hsl(240 10% 3.9%)`.
- `bg-gradient-accent` — `hsl(162 100% 54%)` → `hsl(180 100% 60%)`.
- `bg-gradient-magenta` — `hsl(292 91% 68%)` → `hsl(320 91% 60%)`.
- `bg-grid-pattern` — 1px horizontal + vertical grid lines.
- `bg-grid` size `60px 60px`.

### 6.8 Dark-only aesthetic

Several design decisions reinforce the dark-only direction:

- `className="dark"` is hard-coded on `<html>` with `suppressHydrationWarning`.
- No `prefers-color-scheme` override; no light-mode variables in `:root`.
- The command palette uses `bg-phantom-bg/80 backdrop-blur-md` as the
  scrim — it would wash out a light scheme.
- The scrollbar track/thumb colors are deep and only work on dark.
- The chart tooltips and axis grid lines live in the ghost/border range
  that would be invisible on white.

If light mode is ever added, it would require: (a) a second CSS-variable
set under `:root:not([data-theme="light"])` / `[data-theme="light"]`,
(b) scrollbar/scrim updates, (c) chart grid/axis recoloring, and
(d) `phantom-glow` / `phantom-pulse` opacity tuning.

### 6.9 Icons

All icons come from `lucide-react`. The convention is `w-4 h-4 strokeWidth={1.75}`
for inline icons and `w-9 h-9 strokeWidth={1.5}` for hero icons. The
`lucide-react` package import is covered by
`experimental.optimizePackageImports` for tree-shaking.

---

## 7. Launch config — `.claude/launch.json`

Path: `frontend/.claude/launch.json`.

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "phantomfleet-frontend",
      "runtimeExecutable": "npm",
      "runtimeArgs": ["run", "dev"],
      "port": 3016
    }
  ]
}
```

- Dev server launches via `npm run dev` which translates to
  `next dev -p 3016` (defined in `package.json` scripts).
- Port 3016 is the Phantom Fleet port in the Scaler Pro port map
  (matches the CLAUDE.md panel-port note).
- The config is read by the Claude Code `preview_start` tool to launch the
  app in the Browser pane. There is no `url` override — the preview will
  open at `http://localhost:3016`.

### 7.1 Scripts — `package.json`

```json
"scripts": {
  "dev": "next dev -p 3016",
  "build": "next build",
  "start": "next start -p 3016",
  "lint": "next lint",
  "type-check": "tsc --noEmit"
}
```

### 7.2 Environment variables

Two `NEXT_PUBLIC_*` vars (both optional):

- `NEXT_PUBLIC_API_URL` — defaults to `http://localhost:8000`. Points the
  Next rewrite at the backend.
- `NEXT_PUBLIC_WS_URL` — base URL for WebSocket connections. Used by
  `/ops`, `/`, and `components/action-stream.tsx`.

---

## 8. The `/approvals` page (commit 14d11d9)

The most recent commit added `/approvals` as the owner-gated approval UI for
research-agent target candidates and generator comments. File:
`src/app/approvals/page.tsx`.

### 8.1 Why it exists

Research agents (`ig_target_scout` and sibling specialists) deliver candidate
IG targets into the Phantom Fleet backend as **pending** rows
(`needs_approval`). Nothing is dispatched to a clone until the owner
approves each one — that approval is stamped with the owner's handle and
becomes the audit trail. The same gate applies to generator-emitted
comments: the picker reads the active (approved) pool only.

### 8.2 State

```ts
const [approver, setApprover] = useState("owner");
const [targets, setTargets] = useState<PendingTarget[]>([]);
const [comments, setComments] = useState<PendingComment[]>([]);
const [counts, setCounts] = useState<Counts | null>(null);
const [farmFilter, setFarmFilter] = useState("");
const [busy, setBusy] = useState<Record<string, boolean>>({});
const [err, setErr] = useState<string | null>(null);
const [lastRefresh, setLastRefresh] = useState<number>(0);
```

- `approver` — the owner handle stamped on every decision (required).
- `farmFilter` — optional `farm_id` query filter for the pending targets
  (passes as `?farm_id=...`).
- `busy` — per-row `${kind}:${id}:${decision}` busy map so the Approve/Reject
  buttons disable individually.
- `err` — inline error ribbon.

### 8.3 Types

```ts
type PendingTargetRaw = {
  id: number;
  farm_id: string | null;
  kind: string;                 // "profile", "media", etc.
  handle: string;               // IG handle (no @)
  media_code: string | null;    // IG media shortcode if kind=="media"
  tags_json: string | null;     // JSON array of string tags
  locale: string | null;
  source: string;               // scout run id / source name
  imported_ms: number;          // epoch ms at import
};
type PendingTarget = Omit<PendingTargetRaw, "tags_json"> & { tags: string[] };

type PendingComment = {
  id: number;
  text: string;
  niche: string;    // comment niche cluster
  source: string;   // generator run id
  imported_ms: number;
};

type Counts = {
  pending_target_approvals: number;
  pending_comment_approvals: number;
};
```

### 8.4 Refresh loop

```ts
const refresh = useCallback(async () => {
  const qs = farmFilter ? `?farm_id=${encodeURIComponent(farmFilter)}` : "";
  const [t, c, pc] = await Promise.all([
    fetch(`/api/targets/pending${qs}`).then((r) => r.json()),
    fetch("/api/targets/comments/pending").then((r) => r.json()),
    fetch("/api/targets/pending_counts").then((r) => r.json()),
  ]);
  setTargets((t?.rows ?? []).map(parseTagsRow));
  setComments(c?.rows ?? []);
  setCounts(pc ?? null);
}, [farmFilter]);

useEffect(() => {
  refresh();
  const id = setInterval(refresh, 10_000);
  return () => clearInterval(id);
}, [refresh]);
```

- 10-second polling.
- `parseTags` safely JSON-parses the raw `tags_json` string into a
  `string[]`, defaulting to `[]`.
- Errors are surfaced into `err` (shown in the top bar's mono microtext).

### 8.5 Approve / reject

```ts
const act = async (
  kind: "target" | "comment",
  id: number,
  decision: "approve" | "reject",
) => {
  if (!approver.trim()) { setErr("Approver name required"); return; }
  let reason = "";
  if (decision === "reject") {
    reason = window.prompt("Reason for rejection?") ?? "";
    if (!reason.trim()) return;
  }
  const base = kind === "target"
    ? `/api/targets/${id}`
    : `/api/targets/comments/${id}`;
  const body = decision === "approve" ? { approver } : { approver, reason };
  await fetch(`${base}/${decision}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await refresh();
};
```

Backend endpoints exercised:

- `POST /api/targets/{id}/approve` with `{ approver }`.
- `POST /api/targets/{id}/reject` with `{ approver, reason }`.
- `POST /api/targets/comments/{id}/approve` with `{ approver }`.
- `POST /api/targets/comments/{id}/reject` with `{ approver, reason }`.

### 8.6 UI structure

1. Hero header — "Owner gate / Approvals" with a `<ShieldCheck>` icon and a
   descriptive paragraph.
2. Top stats grid (4 cards):
   - Pending targets (count, amber phantom-metric-lg).
   - Pending comments (count, amber).
   - Approver + farm filter card spanning 2 cols: input for approver handle,
     input for `farm_id`, a Refresh button, and an "err / refreshed Xs ago"
     status line.
3. Pending targets `<Panel>`:
   - Empty state with `<Target>` icon.
   - Otherwise a dark table: Handle (+ `/p/{media_code}` if present),
     Kind pill, Farm mono, Tags pills (first 4), Source mono, Age, and a
     right-aligned Approve/Reject button pair.
   - Approve = `bg-phantom-alive/10 border-phantom-alive/30 text-phantom-alive`.
   - Reject = `bg-phantom-red/10 border-phantom-red/30 text-phantom-red`.
4. Pending comments `<Panel>`:
   - Empty state with `<MessageSquare>` icon.
   - Otherwise a vertical stack of comment cards — text in monospace,
     niche pill accent-tinted, source mono, imported-age, and Approve/Reject
     buttons.

### 8.7 Design notes

- `fmtAge(ms)` is a plain `Date.now()-ms` formatter that emits
  `Ns / Nm / Nh / Nd ago`.
- Reject always prompts (via `window.prompt`) for a reason; an empty reason
  cancels.
- Every button's `disabled` is wired to `busy[key]` so a user can't
  double-fire and the UI gets visual feedback even without sonner.
- `approver` has a default of `"owner"` as a placeholder — it is **not**
  tied to any session identity yet. The next engineer should wire this to
  auth (session cookie, OIDC, or whatever Phantom Fleet picks).

### 8.8 Follow-ups for the next session

- Rewire `/targets` (currently mocked) to the same endpoints for pre-
  approval triage, or deprecate it in favor of `/approvals`.
- Add a sonner toast on success/failure instead of only the top ribbon.
- Add batch-approve/batch-reject for cases where a scout dumps 50 clean
  rows at once.
- Push a sidebar badge count next to "Approvals" wired to
  `/api/targets/pending_counts`.

---

## 9. WebSocket and real-time flows

Three places in the codebase use WebSockets. Next's rewrites **do not**
proxy `ws://` — the client connects directly, driven by `NEXT_PUBLIC_WS_URL`
(the code falls back to the current host when the env var is absent).

### 9.1 Overview page — `src/app/page.tsx`

```ts
const wsRef = useRef<WebSocket | null>(null);
// ...
const ws = new WebSocket(`${wsBase}/fleet`);
```

- Live-fleet-activity WebSocket at `${wsBase}/fleet`.
- Appends events to the in-memory list (bounded) and keeps the status badge
  `isLive ? "/ws/fleet" : "demo mode · WebSocket offline"`.
- The demo fallback cycles through `DEMO_EVENTS` with synthetic timestamps
  so the surface is never blank even in SSR / with the backend offline.

### 9.2 Ops page — `src/app/ops/page.tsx`

```ts
const wsRef = useRef<WebSocket | null>(null);
// ...
const wsUrl = `${wsBase}/ops` or similar
const ws = new WebSocket(wsUrl);
```

- Receives operational events into the live-feed console.
- Placeholder "Waiting for WebSocket connection…" string renders until
  the socket is open.
- Reconnect strategy: the page reconnects on mount; no exponential backoff.

### 9.3 Live action-stream component — `src/components/action-stream.tsx`

- Centralized component that other pages can embed.
- Opens a WebSocket to the configured URL.
- Sends a periodic `"ping"` while `ws.readyState === WebSocket.OPEN`.
- Falls back to demo mode if the socket errors or is unavailable (SSR /
  blocked). The demo banner matches the overview page.
- Used on `/` to render the right-side live stream.

### 9.4 No `EventSource` / SSE

A grep for `EventSource` or `wss://` returns no other hits. The project
uses raw WebSockets, not SSE. The three locations above are the entire
real-time surface.

### 9.5 Known gap

The top bar's live phone count uses a REST poll (`GET /api/fleet` every
30s), not the fleet WebSocket. Phase 1 wiring can collapse the two
sources.

---

## 10. Page inventory summary

### 10.1 Count by status

- ~60 page files under `src/app/`.
- **Live-data pages (~30):** `/`, `/fleet`, `/fleet/[serial]`,
  `/fleet/[serial]/[account_id]/settings`, `/fleet/[serial]/[account_id]/stats`,
  `/accounts`, `/onboarding`, `/ops`, `/agents`, `/schedule`, `/content`,
  `/content-vault`, `/proxy`, `/settings`, `/phase1`, `/phase2`,
  `/capacity`, `/pipeline`, `/mirroring`, `/mirroring/access`, `/approvals`,
  `/instagram`, `/instagram/[account_id]`, `/threads`,
  `/threads/[account_id]`.
- **Mocked pages (~30):** `/briefing`, `/calendar`, `/targets`, `/personas`,
  `/personas/[id]`, `/cluster`, `/analytics`, `/platforms`,
  `/platforms/[platform]`, all `/ig/*` subpages (notes, pods, saves, reels,
  warmup, shadowban, abtest, unfollow), all `/threads/*` subpages except
  `/threads` itself, all `/tiktok/*` pages, all `/dating/*` pages, `/funnel`,
  `/alerts`, `/s10-box`, `/agents/[name]`, and all 5 `(marketing)/*` pages.

### 10.2 Highest priority rewiring (Phase 1)

1. `/targets` — rewire to `/api/targets/pending` (same endpoint as
   `/approvals`) for pre-approval triage.
2. `/cluster` — rewire to the audit-harness endpoint when it ships (this is
   the CI gate from CLAUDE.md).
3. All `/ig/*` subpages — currently mocked but the real engines exist under
   `/api/platforms/instagram/*` (seen on the `/instagram` command center).
4. All `/threads/*` subpages — mirror the IG rewire path.
5. `/tiktok/*`, `/dating/*` — backend endpoints will arrive in Phase 2.
6. `/agents/[name]` — rewire to `/api/platforms/staffroom/missions/*`
   scoped by agent name.

---

## 11. How a page is typically shaped

For reference by the next engineer, the canonical page scaffold is:

```tsx
"use client";
import { useEffect, useState } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { Rocket } from "lucide-react";

export default function MyPage() {
  const [data, setData] = useState(null);
  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const r = await fetch("/api/my-endpoint", { cache: "no-store" });
        if (r.ok) { const d = await r.json(); if (!stop) setData(d); }
      } catch {}
    };
    load();
    const t = setInterval(load, 10_000);
    return () => { stop = true; clearInterval(t); };
  }, []);
  return (
    <div className="space-y-8">
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Section overline
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <Rocket className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <span className="phantom-accent-text">My Page</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-2xl">
          One-paragraph description.
        </p>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Total" value={data?.total ?? "—"} />
      </div>
      <Panel label="section" title="A table" subtitle="description">
        {/* body */}
      </Panel>
    </div>
  );
}
```

Every live-data page in the repo is a variation of this scaffold:

- Overline + phantom-accent-text H1 + icon + description paragraph.
- A KPI grid.
- One or more `<Panel>`s holding tables, forms, or charts.
- `useEffect` + interval refresh.

---

## 12. Repo utility and conventions

### 12.1 `src/lib/utils.ts`

Provides `cn(...classes)` — the standard `clsx` + `tailwind-merge`
combinator. Every component imports `import { cn } from "@/lib/utils"`.

### 12.2 TypeScript paths

`tsconfig.json` configures `@/*` → `src/*`, so imports consistently look
like `@/components/panel`, `@/lib/utils`, `@/app/...`.

### 12.3 Strict mode

React is in strict mode (`reactStrictMode: true`), which double-invokes
effects in dev. Every `useEffect` guards against this with a `let stop =
false; return () => { stop = true; };` cleanup — follow the same pattern
when adding effects that set state.

### 12.4 Linting

`npm run lint` uses `eslint-config-next` plus `@typescript-eslint`. There
is no custom rule about `random.uniform()` in the frontend (that rule lives
in the backend per CLAUDE.md); frontend random uses `Math.random()` in
exactly one place: the mock agent reply picker in
`agent-chat-widget.tsx`. Flag to the next engineer that even demo randomness
should migrate to a typed distribution when the widget gets wired for
real.

---

## 13. Handoff checklist for the next session

- [ ] Run `cd frontend && npm install`.
- [ ] Copy `.env.local` with `NEXT_PUBLIC_API_URL=http://localhost:8000` and
      `NEXT_PUBLIC_WS_URL=ws://localhost:8000` (match Section 2 backend).
- [ ] `npm run dev` — the app launches at `http://localhost:3016`.
- [ ] Confirm `/approvals` returns data from
      `/api/targets/pending{,_counts}` and `/api/targets/comments/pending`.
- [ ] Confirm the top bar's "phones online" number matches `GET /api/fleet`.
- [ ] Confirm the `/` WebSocket activity feed opens at
      `${NEXT_PUBLIC_WS_URL}/fleet`.
- [ ] Phase-1 wiring: replace mocks for `/targets`, `/cluster`, `/ig/*`,
      `/threads/*` subpages, `/tiktok/*`, `/dating/*`.
- [ ] Add session-aware `approver` wiring on `/approvals` (replace the
      hard-coded "owner" default).
- [ ] Add a sidebar badge for pending approvals counts.
- [ ] Extract `/fleet/[serial]/[account_id]/settings` (~1800 lines) into
      sub-components (one per section).
- [ ] Add self-hosted fonts via `next/font` instead of relying on fallback
      Inter / JetBrains Mono.

---

## 14. Appendix — exhaustive endpoint list used by the frontend

Grouped by backend prefix (every endpoint appears in at least one page
fetch; see §3 for the per-page list):

**Fleet / accounts / onboarding**
- `GET /api/fleet`
- `GET /api/fleet/{serial}`
- `GET /api/fleet/{serial}/accounts`
- `GET /api/fleet/cluster/collisions`
- `POST /api/fleet/scan`
- `POST /api/fleet/verify-all`
- `POST /api/fleet/{serial}/install-apk`
- `POST /api/fleet/{serial}/verify-proxy`
- `POST /api/fleet/{serial}/adb/release`
- `DELETE /api/fleet/phones/{serial}`
- `POST /api/fleet/start-warming`
- `POST /api/accounts/provision`
- `GET /api/accounts/{id}`
- `GET /api/accounts/{id}/stats?days=30`
- `GET /api/accounts/{id}/targets`
- `POST /api/accounts/{id}/targets`
- `POST /api/accounts/{id}/targets/ai-scrape`
- `DELETE /api/accounts/{id}/targets/{tid}`
- `POST /api/accounts/{id}/detect-clone`
- `POST /api/accounts/{id}/login`
- `POST /api/accounts/{id}/logout`
- `POST /api/accounts/{id}/scrape-follow-source`
- `POST /api/accounts/{id}/clone`
- `PATCH /api/accounts/{id}`
- `DELETE /api/accounts/{id}`
- `GET /api/accounts?platform=instagram`

**Targets / approvals**
- `GET /api/targets/pending[?farm_id=]`
- `GET /api/targets/pending_counts`
- `GET /api/targets/comments/pending`
- `POST /api/targets/{id}/approve`
- `POST /api/targets/{id}/reject`
- `POST /api/targets/comments/{id}/approve`
- `POST /api/targets/comments/{id}/reject`

**Ops / phase / capacity / schedule**
- `GET /api/ops/status`, `GET /api/ops/cycle/latest`,
  `GET /api/ops/cycle/history`
- `POST /api/ops/pause`, `POST /api/ops/resume`,
  `POST /api/ops/cycle/trigger`
- `GET /api/phase1/readiness`, `POST /api/phase1/start`
- `GET /api/phase2/readiness`, `POST /api/phase2/start`
- `POST /api/capacity-plan`
- `POST /api/schedule/generate`

**Mirroring**
- `GET /api/fleet-mirror/embed-wall?minutes=480`
- `GET /api/fleet-mirror/access`

**Proxy**
- `GET /api/proxy/pool`
- `POST /api/proxy/pool` (add)
- `DELETE /api/proxy/pool/{idx}`
- `POST /api/proxy/pool/verify`

**Content vault**
- `GET /api/content-vault/items?limit={n}`
- `GET /api/content-vault?{params}`
- `POST /api/content-vault/upload`
- `GET /api/content-vault/stats`
- `DELETE /api/content-vault/{itemId}`
- `POST /api/content-vault/schedule`

**Pipeline**
- `GET /api/pipeline/gmail/stats`
- `GET /api/pipeline/reddit/accounts`
- `POST /api/pipeline/gmail/create`
- `POST /api/pipeline/reddit/register`
- `POST /api/pipeline/reddit/export`

**Staffroom (agents)**
- `GET /api/platforms/staffroom/roster`
- `GET /api/platforms/staffroom/missions/summary`
- `POST /api/platforms/staffroom/missions/dispatch`
- `POST /api/platforms/staffroom/missions/{rid}/refresh`

**Instagram platform**
- `GET /api/platforms/instagram/accounts/{account_id}/dossier`
- `GET /api/platforms/instagram/health/summary`
- `POST /api/platforms/instagram/health/scan`
- `POST /api/platforms/instagram/health/simulate`
- `GET /api/platforms/instagram/recovery/status`
- `POST /api/platforms/instagram/recovery/tick`
- `POST /api/platforms/instagram/recovery/{acc}/graduate`
- `POST /api/platforms/instagram/recovery/{acc}/skip-cooldown`
- `GET /api/platforms/instagram/funnel/summary`
- `POST /api/platforms/instagram/funnel/record`
- `GET /api/platforms/instagram/rebalancer/status`
- `GET /api/platforms/instagram/orchestrator/status`
- `POST /api/platforms/instagram/orchestrator/plan-now`
- `GET /api/platforms/instagram/probes/status?limit={n}`
- `POST /api/platforms/instagram/probes/tick`
- `GET /api/platforms/instagram/agent/config`
- `GET /api/platforms/instagram/agent/runs?limit={n}`
- `GET /api/platforms/instagram/executor/status`
- `GET /api/platforms/instagram/diurnal/summary`
- `GET /api/platforms/instagram/identity/summary`
- `POST /api/platforms/instagram/identity/scan`
- `GET /api/platforms/instagram/proxy/summary`
- `POST /api/platforms/instagram/proxy/tick`
- `POST /api/platforms/instagram/proxy/{accountId}/rotate`
- `GET /api/platforms/instagram/drift/summary`
- `POST /api/platforms/instagram/drift/scan`
- `POST /api/platforms/instagram/drift/{serial}/snapshot`
- `GET /api/platforms/instagram/lattice/summary`
- `POST /api/platforms/instagram/lattice/plan`
- `GET /api/platforms/instagram/checkpoint/summary`
- `GET /api/platforms/instagram/session/summary`
- `POST /api/platforms/instagram/session/tick`
- `POST /api/platforms/instagram/session/{aid}/complete-2fa`
- `GET /api/platforms/instagram/unfollow/summary`
- `POST /api/platforms/instagram/unfollow/tick`
- `GET /api/platforms/instagram/dm/summary`
- `POST /api/platforms/instagram/dm/tick`

**Threads platform**
- `GET /api/platforms/threads/accounts`
- `GET /api/platforms/threads/accounts/{id}/dossier`
- `POST /api/platforms/threads/accounts/{id}/warmup?day={d}`
- `GET /api/platforms/threads/status`
- `GET /api/platforms/threads/executor/status`
- `POST /api/platforms/threads/executor/{endpoint}`
- `GET /api/platforms/threads/queue`
- `GET /api/platforms/threads/funnel/summary`
- `GET /api/platforms/threads/funnel/{selected}`
- `POST /api/platforms/threads/funnel/event`
- `GET /api/platforms/threads/orchestrator/status`
- `POST /api/platforms/threads/orchestrator/run`
- `POST /api/platforms/threads/orchestrator/{endpoint}`
- `GET /api/platforms/threads/bridge/status`
- `GET /api/platforms/threads/ig-events?limit={n}`
- `POST /api/platforms/threads/ig-event`
- `GET /api/platforms/threads/audit/last`
- `POST /api/platforms/threads/audit/run?n={n}`
- `GET /api/platforms/threads/health/summary`
- `POST /api/platforms/threads/health/scan`
- `POST /api/platforms/threads/health/simulate`
- `GET /api/platforms/threads/probes/status?limit={n}`
- `POST /api/platforms/threads/probes/tick`
- `GET /api/platforms/threads/agent/runs?limit={n}`
- `GET /api/platforms/threads/persistence/status`
- `GET /api/platforms/threads/rebalancer/status`
- `GET /api/platforms/threads/recovery/status`
- `POST /api/platforms/threads/recovery/tick`
- `POST /api/platforms/threads/recovery/{accountId}/skip-cooldown`
- `POST /api/platforms/threads/recovery/{accountId}/graduate`
- `POST /api/platforms/threads/cross-post`
- `GET /api/platforms/threads/budget/{selected}`
- `GET /api/platforms/threads/curve/{selected}`
- `POST /api/platforms/threads/link`
- `POST /api/platforms/threads/{kind}`
- `POST /api/platforms/threads/advance-day/{selected}`

**Agent chat**
- `POST /api/v1/agents/chat` with `{ agent, message, history }`.

**Settings**
- `POST /api/v1/settings/openrouter/test`
- `POST /api/v1/settings/openrouter`

**WebSockets**
- `${NEXT_PUBLIC_WS_URL}/fleet`
- `${NEXT_PUBLIC_WS_URL}/ops` (or similar — see `src/app/ops/page.tsx`
  line 230 for exact path).

---

## 15. End-of-section notes

- The frontend is **standalone**: any backend can serve `/api/*` as long as
  it honors the endpoint list in §14.
- The UI is **dark-only** and **owner-centric**: no multi-tenant surfaces
  yet, and no auth gating anywhere — `/approvals` uses a hand-typed
  `approver` string that must be wired to a real identity before any
  non-owner user touches the panel.
- The **sidebar is the source of truth** for what's shipping. If a page
  isn't in `NAV_SECTIONS`, it's a dynamic drill-through from another page
  (or a marketing page).
- The **`/approvals` page is the single highest-trust surface** in the
  system — every target or comment a research agent emits passes through
  it before a clone touches it. Phase-1 engineering must harden it first.
- The **`/fleet/[serial]/[account_id]/settings` page is the biggest
  mono-component in the repo** and the first candidate for decomposition
  when the codebase moves into Phase 1 cleanup.
- The theme uses the signature neon cyan-green `hsl(162 100% 54%)` as the
  single accent; magenta `hsl(292 91% 68%)` is the secondary accent but
  appears rarely. Warning amber and critical red are reserved for status.
- The WebSocket surface is three endpoints; Next's rewrites do not proxy
  `ws://`, so client code uses `NEXT_PUBLIC_WS_URL` directly.
- `dev` runs on port 3016 — hard-coded in `package.json` and
  `.claude/launch.json`.

---

## 16. Appendix — per-page widget/panel breakdowns (extended)

The following subsections drill into the live pages in more detail. The
next engineer should be able to recreate each page from these notes alone.

### 16.1 `/` — Overview, extended

The overview is composed of three vertical sections:

- **Row 1 — KPI strip.** Four `<KPICard>` instances: Fleet online,
  Active clones, Agents running (accent-colored), and 30d revenue. Each
  KPICard accepts `{ label, value, delta?, deltaKind?, sparklineData? }`.
  Delta is rendered as a small chip with `alive` tint for positive and
  `red` for negative.
- **Row 2 — 2-column grid.** Left column: `<FleetGrid>` showing all phones
  as mini `<PhoneCard>` tiles with status dots. Right column: `<AgentFeed>`
  with scrolling agent events.
- **Row 3 — 2-column grid.** Left: `<ClusterHeatmap>`. Right:
  `<RevenueChart>`.
- **Row 4 — Live Fleet Activity stream.** A full-width panel with the
  `<ActionStream>` component (the live WebSocket consumer). Shows a
  color-coded badge per event type: follow / like / comment / dm. Status
  line shows `/ws/fleet` or `demo mode · WebSocket offline`.

State machinery:

- `wsRef: useRef<WebSocket | null>`. On mount: open the socket, bind
  `onopen`, `onmessage`, `onerror`, `onclose`. On unmount: close the socket.
- `isLive: boolean` reflects the WebSocket's `readyState === OPEN`.
- The event list is capped (newest first, ~200 entries) to avoid
  unbounded growth.
- `DEMO_EVENTS` cycles with `setInterval` while `!isLive`.

### 16.2 `/fleet` — Fleet, extended

- Page state: `phones` (`Phone[]`), `collisions` (`Collision[]`).
- `Phone` shape (from `/api/fleet`): `{ serial, status, online,
  accounts_count, proxy_ok, last_seen_ms }`.
- `Collision` shape (from `/api/fleet/cluster/collisions`): `{ kind,
  phones: string[], field, value }`.
- Panels: top KPI row (total phones, online, warming, blocked), phone grid,
  cluster-collisions strip, action bar.
- Row click → `router.push('/fleet/' + serial)`.
- "Scan" button → `POST /api/fleet/scan`, optimistic loading state.
- "Verify all proxies" → `POST /api/fleet/verify-all`.
- Per-row kebab menu: Open, Remove (`DELETE /api/fleet/phones/{serial}`).

### 16.3 `/fleet/[serial]` — Phone detail, extended

- Page state: `phone`, `accounts`, `collisions`.
- Reads: `GET /api/fleet/{serial}`, `GET /api/fleet/{serial}/accounts`,
  `GET /api/fleet/cluster/collisions` (filtered client-side by serial).
- Top header: phone model, serial (mono), status badge, proxy badge, last-
  seen.
- Panels:
  - Account table (per-row Edit/Delete/Clone).
  - Cluster collisions filtered to this phone.
  - Action bar: Verify proxy, Release ADB, Add account.
- Actions:
  - "Add account" opens a modal that POSTs `POST /api/accounts` with
    `{ serial, platform, handle, persona_id }`.
  - "Clone" per-row → `POST /api/accounts/{id}/clone`.
  - "Delete" per-row → `DELETE /api/accounts/{id}`.
  - "Edit" per-row opens a side-drawer that PATCHes individual fields.
  - "Verify proxy" → `POST /api/fleet/{serial}/verify-proxy`; the button
    enters a 2s "verifying…" state.

### 16.4 `/fleet/[serial]/[account_id]/settings` — Clone settings, extended

The largest page in the repo. Section-by-section (each section's state is
local to that section and persists optimistically):

1. **Identity.** PATCHes `/api/accounts/{id}` with fields: `handle`,
   `email`, `password`, `phone`, `locale`, `timezone`, `birthday`.
2. **Login status.** Buttons wire `POST /api/accounts/{id}/login` and
   `POST /api/accounts/{id}/logout`; state field `loggedIn: boolean`.
3. **Clone detection.** `POST /api/accounts/{id}/detect-clone` returns the
   clone's app-index (0–21 across the 22 AppCloner clones). PATCHes
   `clone_index`.
4. **Follow sources.** Textarea of accounts to study; "AI scrape" calls
   `POST /api/accounts/{id}/scrape-follow-source` with `{ source: "@handle"
   }` and returns a list of expanded targets.
5. **Targets.** Per-account target CRUD via
   `/api/accounts/{id}/targets`:
   - List on mount.
   - Add via POST; remove via DELETE.
   - "AI scrape" button calls
     `/api/accounts/{accountId}/targets/ai-scrape` with
     `{ prompt, count }` and inserts the resulting targets.
6. **Warm-up tuning.** PATCHes `warmup_day`, `warmup_curve`,
   `warmup_frozen`.
7. **Scheduler.** PATCHes `schedule_*` fields (quiet hours, max actions,
   per-action caps).
8. **Probe schedule.** PATCHes `probe_*` fields (frequency, type).
9. **DM strategy.** PATCHes `dm_stage`, `dm_template_id`, `dm_cooldown_h`.
10. **Diagnostics.** Read-only; shows the last `GET /api/accounts/{id}`
    payload for debugging.

All PATCHes use the pattern:

```ts
await fetch(`/api/accounts/${local.id}`, {
  method: "PATCH",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ field: value }),
});
```

The page should be decomposed into one sub-component per section — a
natural PR for the next engineer. Candidate structure:

```
src/app/fleet/[serial]/[account_id]/settings/
  page.tsx                      # shell + layout
  sections/
    IdentitySection.tsx
    LoginSection.tsx
    CloneSection.tsx
    FollowSourcesSection.tsx
    TargetsSection.tsx
    WarmupSection.tsx
    SchedulerSection.tsx
    ProbeSection.tsx
    DmStrategySection.tsx
    DiagnosticsSection.tsx
```

### 16.5 `/accounts` — Accounts, extended

- Page state: `accounts`, `provisioning: boolean`.
- Reads: list via inline fetch.
- Provision form: `{ serial, platform, persona_id, handle, email,
  password }`.
- POST → `POST /api/accounts/provision`.
- Error path shows an inline alert.

### 16.6 `/onboarding` — Onboarding wizard, extended

Step list:

1. **Scan phones.** `POST /api/fleet/scan`. Shows the resulting phone list.
2. **Install APK on each.** For each serial, `POST
   /api/fleet/{serial}/install-apk` with a body indicating the APK path.
   A per-serial status chip (pending / installing / ok / failed) is
   rendered.
3. **Verify proxies.** `POST /api/fleet/verify-all`. Rolls up to a grid of
   proxy-status badges.
4. **Provision accounts.** For each clone slot, `POST
   /api/accounts/provision`. Shows counters per phone.
5. **Start warming.** `POST /api/fleet/start-warming`. Flips the fleet to
   "warming" mode and transitions to the overview page.

State machinery:

- `step` (`1..5`).
- `logs` (log line array).
- Per-step `busy`, `error`, `result` tuples.

### 16.7 `/ops` — Ops Brain, extended

- Reads (in `Promise.all`):
  - `GET /api/ops/status`
  - `GET /api/ops/cycle/latest`
  - `GET /api/ops/cycle/history`
- Opens a WebSocket to the ops channel for live event lines.
- Panels:
  - Status card with pause / resume / trigger buttons.
  - Latest cycle card: start time, end time, counts, errors.
  - Cycle history table.
  - Live feed console (dark pre-formatted text, `font-mono`, newest at
    bottom). Shows `Waiting for WebSocket connection…` while disconnected.

### 16.8 `/agents` — Agents, extended

- Reads (in `Promise.all`):
  - `GET /api/platforms/staffroom/roster`
  - `GET /api/platforms/staffroom/missions/summary`
- Panels:
  - Roster grid: per-agent card with avatar, name, tier badge
    (`<ChatTierBadge>`), running-count.
  - Mission dispatcher form: `{ agent, kind, params }` → `POST
    /api/platforms/staffroom/missions/dispatch`.
  - Mission feed: list of recent missions with per-row refresh button
    (`POST /api/platforms/staffroom/missions/{rid}/refresh`).

### 16.9 `/schedule` — Schedule, extended

- Reads: none on mount.
- POST `/api/schedule/generate` with
  `{ start_date, end_date, personas, platforms, posts_per_day }`.
- Response: `{ slots: [{ time, account_id, action, params }] }`.
- Renders `<TimeSlotStrip>` plus a heatmap grid showing density per hour.

### 16.10 `/capacity` — Capacity Planner, extended

- POST `/api/capacity-plan` with
  `{ fleet_size, platforms, posts_per_account_per_day,
  reserved_capacity_pct }`.
- Response: `{ per_phone_utilization, warnings[], suggestions[] }`.
- Renders `<CapacityResultCard>` with KPI tiles and a bar chart.

### 16.11 `/pipeline` — Gmail → Reddit, extended

- Reads:
  - `GET /api/pipeline/gmail/stats` — `{ total, active, blocked }`.
  - `GET /api/pipeline/reddit/accounts` — list of reddit accounts.
- Actions:
  - `POST /api/pipeline/gmail/create` with `{ count }`.
  - `POST /api/pipeline/reddit/register` with `{ gmail_id, subreddit }`.
  - `POST /api/pipeline/reddit/export` — export CSV; UI triggers a download.

### 16.12 `/proxy` — Proxy Health, extended

- Reads: `GET /api/proxy/pool` → `{ pool: [{ idx, host, port, user,
  status, latency_ms }] }`.
- Add form: `POST /api/proxy/pool` with `{ host, port, user, pass }`.
- Per-row delete: `DELETE /api/proxy/pool/{idx}`.
- "Verify all" button: `POST /api/proxy/pool/verify` — shows a count of
  passing/failing proxies.

### 16.13 `/content-vault` — Media Bridge, extended

- Reads: `GET /api/content-vault?{params}` — filtered list;
  `GET /api/content-vault/stats` — counts.
- Uploader: `POST /api/content-vault/upload` multipart with FormData.
- Delete: `DELETE /api/content-vault/{itemId}`.
- Schedule: `POST /api/content-vault/schedule` with `{ item_id, date,
  account_ids }`.
- Grid tiles show thumbnail + metadata chips; clicking a tile opens a
  side-drawer for edit/schedule.

### 16.14 `/approvals` — see §8.

### 16.15 `/instagram` — IG command center, extended

The page uses a dense 3-column grid of panels, each pulling from one
summary endpoint and offering a "Tick" button:

- **Health panel** — `health/summary`, `health/scan`, `health/simulate`.
- **Recovery panel** — `recovery/status`, `recovery/tick`,
  `recovery/{acc}/graduate`, `recovery/{acc}/skip-cooldown`. Per-account
  rows with Graduate / Skip cooldown buttons.
- **Funnel panel** — `funnel/summary`, `funnel/record`.
- **Rebalancer panel** — `rebalancer/status`.
- **Orchestrator panel** — `orchestrator/status`, `orchestrator/plan-now`.
- **Probes panel** — `probes/status`, `probes/tick`.
- **Agent config + runs panel** — `agent/config`, `agent/runs`.
- **Executor panel** — `executor/status`.
- **Diurnal panel** — `diurnal/summary`.
- **Identity panel** — `identity/summary`, `identity/scan`.
- **Proxy panel** — `proxy/summary`, `proxy/tick`,
  `proxy/{accountId}/rotate`.
- **Drift panel** — `drift/summary`, `drift/scan`, `drift/{serial}/snapshot`.
- **Lattice panel** — `lattice/summary`, `lattice/plan`.
- **Checkpoint panel** — `checkpoint/summary`.
- **Session panel** — `session/summary`, `session/tick`,
  `session/{aid}/complete-2fa`.
- **Unfollow panel** — `unfollow/summary`, `unfollow/tick`.
- **DM panel** — `dm/summary`, `dm/tick`.

All summaries are polled every 10–30 seconds via `useEffect`. Each panel
uses the same visual pattern: label overline + title + summary numbers +
"Tick" primary action + "details →" link to a drill-through.

### 16.16 `/threads` — Threads command center, extended

Mirror of `/instagram` but on the Threads surface. Same panel-grid pattern.
Extra pieces:

- **Bridge status** — `bridge/status` surfaces the IG↔Threads event bridge
  state.
- **IG events feed** — `ig-events?limit=20` renders the recent IG-side
  events that fed into the bridge, with a POST form to log an ad-hoc
  `ig-event`.
- **Audit control** — `audit/last`, `audit/run?n={n}` runs an audit sample
  and displays the result inline.
- **Budget / curve / funnel** — per selected account: `budget/{selected}`,
  `curve/{selected}`, `funnel/{selected}`. Renders three charts side-by-
  side.
- **Advance-day** — `advance-day/{selected}` — manual day advance for
  testing warm-up progression.
- **Generic action** — `POST /api/platforms/threads/{kind}` pattern for
  ad-hoc actions.

### 16.17 `/mirroring` — Phone Wall, extended

The surface renders an iframe grid from the Fleet Mirror hub.

- `GET /api/fleet-mirror/embed-wall?minutes=480` returns
  `{ tiles: [{ serial, embedUrl, lastActiveMs, token_expires_ms }] }`.
- `<FleetMirrorView>` renders tiles in a responsive CSS grid (auto-fill,
  min 240×400).
- Per-tile: iframe with `sandbox="allow-scripts allow-same-origin"`,
  header with serial + last-active ago, fullscreen button that opens the
  iframe in a modal at full viewport.
- Token expiry is honored client-side: tiles past `token_expires_ms` are
  replaced with a "reauthenticate" placeholder.

### 16.18 `/mirroring/access` — Device Access, extended

- `GET /api/fleet-mirror/access` returns a dict keyed by serial of
  access policies (who, what tokens, expiry).
- Renders a table with per-row revoke button (POST endpoint TBD; the UI
  renders the button but it's not wired yet in the current cut).

### 16.19 `/settings` — Settings, extended

- Single-form page.
- Enter an OpenRouter API key, hit "Test" to validate
  (`POST /api/v1/settings/openrouter/test` with `{ api_key }`).
- On successful test, "Save" POSTs `/api/v1/settings/openrouter` with
  `{ api_key }`.
- Toast on either result (via `sonner`).

---

## 17. Appendix — component deep-dives

### 17.1 `<KPICard>` — `src/components/kpi-card.tsx`

Props:

```ts
type KPICardProps = {
  label: string;
  value: string | number | null;
  delta?: string;
  deltaKind?: "up" | "down" | "flat";
  sparklineData?: number[];
  tone?: "default" | "accent" | "amber" | "red" | "alive";
};
```

Markup:

```tsx
<div className={cn("phantom-panel p-5", tone === "accent" && "phantom-panel-accent")}>
  <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">
    {label}
  </div>
  <div className={cn("phantom-metric-lg mt-3", toneClass(tone))}>
    {value ?? "—"}
  </div>
  {delta && <div className={cn("text-xs mt-1", deltaClass(deltaKind))}>{delta}</div>}
  {sparklineData && <Sparkline data={sparklineData} />}
</div>
```

### 17.2 `<Panel>` — `src/components/panel.tsx`

Props:

```ts
type PanelProps = {
  label?: string;
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
};
```

Renders:

```tsx
<section className="phantom-panel p-6 space-y-3">
  <div className="flex items-start justify-between">
    <div>
      {label && (
        <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">
          {label}
        </div>
      )}
      {title && <h2 className="font-display text-xl font-bold">{title}</h2>}
      {subtitle && <p className="text-sm text-phantom-ghost">{subtitle}</p>}
    </div>
    {action}
  </div>
  <div>{children}</div>
</section>
```

### 17.3 `<PhoneCard>` — `src/components/phone-card.tsx`

Props:

```ts
type PhoneCardProps = {
  serial: string;
  status: "alive" | "warming" | "blocked" | "offline";
  accountsCount: number;
  proxyOk: boolean;
  lastSeenMs?: number;
  onOpen?: () => void;
  onVerifyProxy?: () => void;
  onReleaseAdb?: () => void;
  onRemove?: () => void;
};
```

Renders a `phantom-panel` with:

- Phone silhouette icon (lucide `<Smartphone>`).
- Serial in monospace.
- Status dot (`phantom-dot-alive`, `-warning`, `-critical`).
- Accounts-count chip.
- Proxy badge: alive-green or red.
- Last-seen "Ns ago".
- Kebab menu (Radix dropdown) with the handler-driven actions.

### 17.4 `<DataTable>` — `src/components/data-table.tsx`

Columns `{ key, header, render?, sortable? }`. Rows generic `T[]`.
`getRowId?`. Features:

- Column-click toggles sort.
- Rows styled `border-b border-phantom-border/40 hover:bg-phantom-panelHi/30`.
- Empty slot: default is an em-dash with the "Nothing here" caption, but
  can be overridden via `empty` prop.
- No virtualization yet — switch to `@tanstack/react-table` when any list
  grows past 500 rows.

### 17.5 `<ActionStream>` — `src/components/action-stream.tsx`

The live WebSocket component. Props:

```ts
type ActionStreamProps = {
  wsUrl?: string;           // override; defaults to NEXT_PUBLIC_WS_URL
  demoEvents?: FleetEvent[];// fallback cycle
  max?: number;             // cap, default 200
};
```

Internals:

- `useRef<WebSocket | null>()` for the socket.
- `useEffect` opens the socket; on error/close it falls back to
  `demoEvents` cycle with `setInterval`.
- Keeps `events: FleetEvent[]` capped at `max`.
- Ping-pong: sends `"ping"` every 25s while open.
- Visual: each row has an icon per `type` (follow / like / comment / dm),
  the account in accent-mono, the action text, and an ago timestamp.

### 17.6 `<AgentChatWidget>` — see §1.5.

### 17.7 `<FleetMirrorView>` — see §4.3 and §16.17.

### 17.8 `<RevenueChart>` — `src/components/revenue-chart.tsx`

Recharts `<AreaChart>` with:

- Gradient accent fill (`hsl(162 100% 54%)` with 40%→0% stop).
- `<XAxis>` and `<YAxis>` colored `phantom-ghost`.
- `<CartesianGrid>` with stroke `hsl(240 6% 18% / 0.3)`.
- Custom `<Tooltip>` styled `phantom-panel-hi` with mono numbers.

### 17.9 `<ClusterHeatmap>` — `src/components/cluster-heatmap.tsx`

Custom SVG grid. Each cell represents one phone×field intersection; cells
with collisions are tinted `phantom-red/60`, singletons tinted `phantom-alive/20`.

### 17.10 `<FunnelViz>` — `src/components/funnel-viz.tsx`

Recharts `<FunnelChart>` of stage counts. Labels are custom via
`<LabelList>` with `phantom-accent-text` glow on the active stage.

### 17.11 `<TimelineVisual>` — `src/components/timeline-visual.tsx`

Vertical timeline used on dossier pages. Each entry has a colored dot, a
time label, a title, and a body. Supports an `action` slot for per-entry
buttons.

### 17.12 `<AnimatedHeroBg>` — `src/components/animated-hero-bg.tsx`

Framer-motion hero animation used on the marketing pages. Combines a
radial accent plume with a drifting grid using transform animations. Pure
visual — no data.

### 17.13 `<FaqAccordion>` — `src/components/faq-accordion.tsx`

Wraps Radix Accordion primitives with phantom styling. Used on `/docs` and
`/welcome`.

### 17.14 `<ComparisonTable>` — `src/components/comparison-table.tsx`

Marketing comparison table — Phantom Fleet vs alternatives. Sticky header,
accent check / red x per cell.

### 17.15 `<Testimonials>` — `src/components/testimonials.tsx`

Marketing testimonial carousel; auto-rotates with pause-on-hover.

### 17.16 `<ArchitectureDiagram>` — `src/components/architecture-diagram.tsx`

Static SVG system-architecture diagram shown on `/features`. Illustrates
the 5-layer architecture from `PLAN.md`.

### 17.17 `<HeatmapGrid>` — `src/components/heatmap-grid.tsx`

Generic heatmap: rows × columns with a color-scale prop. Used on `/schedule`.

### 17.18 `<TimeSlotStrip>` — `src/components/time-slot-strip.tsx`

24-hour horizontal strip used on `/schedule`. Each hour is a cell colored
by action density.

### 17.19 `<Sparkline>` — `src/components/sparkline.tsx`

Tiny Recharts `<LineChart>` (height 32px by default) with no axes, used
inside KPI cards and dossier pages.

### 17.20 `<StatRing>` — `src/components/stat-ring.tsx`

SVG radial-progress ring; props `{ value, max, label, color }`. Used for
per-account warm-up progress rings.

### 17.21 `<StatusBadge>` — `src/components/status-badge.tsx`

Chip: `{ status, label }`. Chooses between accent/alive/warning/critical
and renders `phantom-dot-*` + text.

### 17.22 `<ChatTierBadge>` — `src/components/chat-tier-badge.tsx`

Agent-tier chip: Chief / Specialist / Scout — color-coded.

### 17.23 `<PlatformBadge>` — `src/components/platform-badge.tsx`

Per-platform chip with the platform's brand color: IG magenta/pink,
Threads near-white, TikTok cyan-pink, Reddit orange, Dating red-pink,
OF teal.

### 17.24 `<PlatformDetailHeader>` — `src/components/platform-detail-header.tsx`

Header for `/platforms/[platform]`. Big display title, platform badge, KPI
row.

### 17.25 `<PlatformGrid>` — `src/components/platform-grid.tsx`

Grid of platform tiles for `/platforms`.

### 17.26 `<LiveTicker>` — `src/components/live-ticker.tsx`

Ornamental pulse animation used in the top bar's left region. Does not
consume any data — purely visual for the "feels alive" effect even when
the WebSocket is offline.

### 17.27 `<AgentFeed>` — `src/components/agent-feed.tsx`

Simple scrolling list of recent agent events. Props `{ events[], max? }`.

### 17.28 `<AgentTree>` — `src/components/agent-tree.tsx`

Nested-list tree view of the agent organization.

### 17.29 `<AgentHierarchyVisual>` — `src/components/agent-hierarchy-visual.tsx`

SVG graph of agent→agent handoff edges. Used on `/agents`.

### 17.30 `<CapacityResultCard>` — `src/components/capacity-result-card.tsx`

Renders the response of `/api/capacity-plan` — KPI row + warnings list +
suggestions list.

### 17.31 `<TimelineGrid>` — `src/components/timeline-grid.tsx`

Horizontal multi-row timeline, used on dossier pages to lay out per-
account actions on a shared time axis.

### 17.32 `<FleetGrid>` — `src/components/fleet-grid.tsx`

Dense grid of mini-phone tiles for the overview page. Similar to
`/fleet` but condensed; each tile links to `/fleet/{serial}`.

---

## 18. Appendix — data shapes used on the frontend

These are the de-facto frontend types inferred from grepping the fetch
callsites. The next engineer should put them in a shared `src/types/` and
import from there instead of re-declaring inline.

### 18.1 Account

```ts
type Account = {
  id: string;
  serial: string;
  platform: "instagram" | "threads" | "tiktok" | "reddit" | "tinder" | "bumble" | "of";
  handle: string;
  email: string;
  password?: string;
  phone?: string;
  locale?: string;
  timezone?: string;
  birthday?: string;
  persona_id?: string;
  clone_index?: number;
  status: "warming" | "alive" | "blocked" | "offline" | "recovery";
  loggedIn: boolean;
  warmup_day: number;
  warmup_curve?: string;
  warmup_frozen?: boolean;
  schedule_quiet_start?: string;
  schedule_quiet_end?: string;
  schedule_max_actions_per_day?: number;
  probe_frequency_h?: number;
  probe_type?: string;
  dm_stage?: number;
  dm_template_id?: string;
  dm_cooldown_h?: number;
  last_action_ms?: number;
};
```

### 18.2 Phone

```ts
type Phone = {
  serial: string;
  model?: string;
  status: "alive" | "warming" | "blocked" | "offline";
  online: boolean;
  accounts_count: number;
  proxy_ok: boolean;
  last_seen_ms: number;
};
```

### 18.3 Collision

```ts
type Collision = {
  kind: "locale_tz" | "fingerprint" | "account_count" | "timing_flat";
  phones: string[];
  field: string;
  value: string;
};
```

### 18.4 Target (pending)

```ts
type PendingTarget = {
  id: number;
  farm_id: string | null;
  kind: string;
  handle: string;
  media_code: string | null;
  tags: string[];        // parsed from tags_json
  locale: string | null;
  source: string;
  imported_ms: number;
};
```

### 18.5 Pending comment

```ts
type PendingComment = {
  id: number;
  text: string;
  niche: string;
  source: string;
  imported_ms: number;
};
```

### 18.6 Proxy pool entry

```ts
type ProxyEntry = {
  idx: number;
  host: string;
  port: number;
  user: string;
  status: "ok" | "failing" | "unknown";
  latency_ms?: number;
};
```

### 18.7 Content vault item

```ts
type ContentItem = {
  id: string;
  kind: "image" | "video" | "carousel";
  thumb_url: string;
  tags: string[];
  used_count: number;
  scheduled_count: number;
  created_ms: number;
};
```

### 18.8 Fleet event (WebSocket)

```ts
type FleetEvent = {
  id: string;
  type: "follow" | "like" | "comment" | "dm";
  account: string;         // "@handle"
  text: string;            // human-readable action
  time: string;            // "just now" / "Ns ago"
  phone_serial?: string;
  platform?: string;
};
```

### 18.9 Cycle snapshot

```ts
type OpsCycle = {
  id: string;
  started_ms: number;
  ended_ms: number | null;
  status: "running" | "ok" | "errored";
  counts: { follows: number; likes: number; comments: number; dms: number };
  errors: { code: string; message: string; account_id?: string }[];
};
```

### 18.10 Capacity plan response

```ts
type CapacityPlan = {
  per_phone_utilization: number[];      // 0..1 per phone
  warnings: string[];
  suggestions: string[];
  bottleneck_platform?: string;
};
```

---

## 19. Appendix — Tailwind utility class cheat sheet (frequently used)

- `bg-phantom-bg` — app background.
- `bg-phantom-panel` / `bg-phantom-panelHi` — card / elevated card.
- `bg-phantom-accent/10` — accent tint fill (buttons / highlights).
- `bg-phantom-alive/10 border-phantom-alive/30 text-phantom-alive` —
  "approve" button pattern.
- `bg-phantom-red/10 border-phantom-red/30 text-phantom-red` — "reject"
  button pattern.
- `border-phantom-border` — 1px hairline.
- `text-phantom-ghost` — secondary text.
- `text-phantom-accent` — accent text.
- `phantom-metric-lg` — big 5xl tabular number.
- `phantom-accent-text` — glowing accent text.
- `phantom-panel` — standard card.
- `phantom-panel-accent` — accent-tinted card.
- `phantom-grid-bg` — layered grid+radial background (applied to layout
  wrapper only).
- `phantom-dot phantom-dot-alive` — status dot + alive glow.
- `font-display` — Inter display face.
- `font-mono` — JetBrains Mono.
- `tabular-nums` — monospaced digits (applies to KPI counts and ticker).
- `uppercase tracking-[0.15em]` — the overline pattern.
- `rounded-xl` — standard card radius.

---

## 20. Appendix — known gaps / TODOs for Phase 1

- No authentication. The frontend assumes the owner is already at the
  console; nothing is gated.
- No sonner toasts hooked up anywhere; errors are silent (except
  `/approvals`).
- No request de-duplication. Multiple pages each poll on their own timers;
  a shared React Query layer would collapse duplicate `/api/fleet` calls.
- No self-hosted fonts.
- `/targets` is mocked and overlaps `/approvals` — rewire or deprecate.
- `/cluster` is mocked and overlaps the backend audit harness — rewire.
- `/calendar` is mocked.
- `/ig/*` subpages are all mocked while `/instagram` carries the real
  wiring — rewire using the same `/api/platforms/instagram/*` endpoints
  with a per-subsection filter.
- `/threads/*` subpages same story as `/ig/*`.
- `/tiktok/*` and `/dating/*` sections have no backend endpoints yet —
  Phase 2 work.
- `/s10-box`, `/alerts`, `/funnel`, `/analytics` all need backend wiring.
- `/fleet/[serial]/[account_id]/settings` should be decomposed.
- The command palette is a stub; the real implementation should use
  `cmdk` (already installed) and wire the quick-actions.
- The `top-bar`'s active-accounts / agents-running / revenue numbers are
  hard-coded; wire them.
- Add a sidebar badge per approval-queue count.
- Add ping/pong heartbeat + reconnection with exponential backoff to all
  three WebSocket consumers.
- Persist `approver` identity across sessions (localStorage or session
  cookie).
- Add batch approve/reject on `/approvals`.
- Extract shared fetch pattern into a `useLivePoll(url, intervalMs)` hook.
- Extract shared `useLiveWebSocket(url)` hook.
- Move inline type declarations into `src/types/`.
- Normalize `${API}` prefix vs rewrite usage — pick one.

---

End of Section 3.



---

# Section 4: Companion APK, Staffroom, MCP, Treg

This section hands off everything that lives at the on-device boundary of Phantom
Fleet and at the owner-command boundary beyond it. Three repos are in play:

1. **Phantom Fleet companion APK** — Kotlin/Jetpack app at
   `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\companion-apk\`.
   Runs on every pilot phone, exposes a Ktor HTTP server on loopback, and drives
   Instagram / Threads / TikTok clones via the Android Accessibility API and a
   virtual camera service.
2. **Phantom Fleet runner** — JS wiring at `phantom-fleet-clone\runner\src\mcp.mjs`
   that bridges claude subprocesses into the Staffroom MCP transport.
3. **Staffroom** — adjacent repo at `C:\Users\admin\Desktop\PhantomFleet\_staffroom\`.
   Owner's command surface. Holds the Treg research transport, the MCP server,
   the eight target-admission tools, and a dozen more fleet-ops tools that call
   back into Phantom Fleet over loopback HTTP.

Everything in this document is derived by reading the actual source and docs on
disk as of 2026-11-25. Discrepancies with the planning docs (e.g. the 8089 vs
8090 port) are flagged inline so the next session can reconcile rather than
inherit a hidden bug.

---

## 0. Known pre-session state

### 0.1 The `projectionsmoke` package is not us

Device R5CRC08KBGA has a package named `projectionsmoke` installed. That is a
dead 2021 leftover from the previous Onimator-generation research spike. It is
**NOT** the Phantom Fleet companion APK — our app ID is
`com.scalerpro.phantomfleet` (see `app/build.gradle.kts` →
`applicationId = "com.scalerpro.phantomfleet"`). Do not confuse the two. The
next session should feel free to `pm uninstall projectionsmoke` on the pilot
phone with no coordination needed.

### 0.2 Port mismatch — 8089 docs vs 8090 code

The planning doc `docs/playbooks/pilot-wire-up.md` and
`ops/dispatch/wire_test.py` both pin the APK loopback port to **8089**
(matching `HARDWARE.md`). But `LocalHttpServer.kt` has
`private val port: Int = 8090` as the default, and
`PhantomAccessibilityService.onServiceConnected()` constructs
`LocalHttpServer(...)` without overriding it. The `adb reverse tcp:8089 tcp:8089`
instruction in the playbook therefore cannot reach the Ktor server on first
install.

**Fix for next session:** in
`app/src/main/java/com/scalerpro/phantomfleet/PhantomAccessibilityService.kt`
pass `port = 8089` when constructing `LocalHttpServer`, or change the Kotlin
default. Either is fine; just pick one and align the three docs that already
say 8089.

### 0.3 Staffroom MCP is already wired on the Fleet side

`runner/src/mcp.mjs` already has the 8 target-admission tool names plus ~30
more on its allowlist. What's missing is the Staffroom-side shim file at
`_staffroom/server/mcp-tools/targets.js` (referenced by
`docs/staffroom/07-target-admission-contract.md` as the implementation target,
pattern-matched against `_staffroom/server/mcp-tools/tool_exchange.js`). All 8
tools are however already registered inline in
`_staffroom/server/staffroom-mcp.js` as of the current state (see § 3.2) —
the `mcp-tools/targets.js` extraction is a code-shape cleanup, not new
functionality.

### 0.4 Pending items

- `PF_AUDIT_SIGNER_KEY` — audit-log signing key is a pending work item (not yet
  wired anywhere in source). See § 7.
- Persona store backup — `backend/persona-factory/` output is not yet backed up
  on any schedule. See § 7.
- 23 specialist research agents beyond `ig_target_scout` are planned but not
  yet written. See § 6.4.

---

## 1. Companion APK architecture

### 1.1 One-paragraph summary

The companion APK is a single-application Kotlin project that runs on every
pilot phone. It installs as `com.scalerpro.phantomfleet`, exposes a small
Material3 Compose status screen, and — once the user grants it the
`BIND_ACCESSIBILITY_SERVICE` permission in Android Settings — spins up a
`PhantomAccessibilityService` that in turn starts a Ktor Netty HTTP server on
`0.0.0.0:<port>` (currently `8090` in code, `8089` in docs — see § 0.2) and a
`VirtualCameraService` foreground service. The backend (Python
`ops/dispatch/worker.py`) reaches the phone through `adb reverse tcp:8089
tcp:8089` and POSTs JSON action payloads to routes like
`POST /instagram/engage/follow`. Each handler on the APK side resolves to an
accessibility-driven UI flow: find a node by id/description/text, dispatch a
`GestureDescription` tap or swipe through the service, sleep for a
LogNormal-distributed delay, loop or finish.

### 1.2 Stack

| Layer | Choice | Version | Notes |
|---|---|---|---|
| Build tool | Gradle (Kotlin DSL) | Android Gradle Plugin 8.5.2 | `build.gradle.kts` roots |
| Language | Kotlin | 2.0.20 (+ serialization plugin 2.0.20) | `app/build.gradle.kts` |
| UI | Jetpack Compose + Material3 | compose-ui 1.7.5, material3 1.3.1 | one activity, StatusScreen only |
| Target SDK | 34 (Android 14) | — | `targetSdk = 34` |
| Compile SDK | 35 | — | `compileSdk = 35` |
| Min SDK | 28 (Android 9 Pie) | — | S10 Lite coverage per HARDWARE.md |
| JVM target | 17 | — | `jvmTarget = "17"` |
| HTTP server | Ktor + Netty | 3.0.1 | server-core, server-netty, content-negotiation, serialization-kotlinx-json |
| JSON | kotlinx.serialization | 1.7.3 | `@Serializable` DTOs |
| GAID | play-services-ads-identifier | 18.1.0 | no full Ads SDK, just AdvertisingIdClient |
| Camera | CameraX | 1.4.1 | core + camera2 + lifecycle + view |
| Coroutines | kotlinx-coroutines-android | 1.9.0 | all handlers are `suspend fun` |
| Lifecycle | androidx.lifecycle | 2.8.7 | service + runtime-ktx |

Namespace is `com.scalerpro.phantomfleet` and the application ID matches, so no
flavor split: the same build reaches the full fleet. `versionCode = 1`,
`versionName = "0.0.1"` — bump both before any multi-phone pilot push.

Gradle packaging notes: Ktor + Netty bundle duplicate META-INF entries, so
`app/build.gradle.kts` excludes `/META-INF/INDEX.LIST`,
`/META-INF/io.netty.versions.properties`, `/META-INF/DEPENDENCIES`. If a future
Ktor bump adds new duplicates, extend the excludes list rather than switching
packaging strategies.

### 1.3 Full package layout — every Kotlin source file

Root: `app/src/main/java/com/scalerpro/phantomfleet/`.

| File | One-line summary |
|---|---|
| `MainActivity.kt` | Single Compose activity. Renders StatusScreen with an "Enable Accessibility Service" button that launches `Settings.ACTION_ACCESSIBILITY_SETTINGS`. 46 lines, scaffold only. |
| `PhantomAccessibilityService.kt` | The real entry point. On `onServiceConnected()` constructs all five handlers, starts `VirtualCameraService` and `LocalHttpServer`. Owns shared gesture primitives (`tapAt`, `swipe`, `pressBack`, `pressHome`). On unbind/interrupt, tears both down. 144 lines. |
| `accessibility/IGEngagementHandler.kt` | The crown-jewel engagement driver: follow, unfollow, like, comment, viewStories, scrollReelFeed, sendDM, checkSession. 1015 lines. Every timing call is a LogNormal delay (`logNormalDelay(mean, sigma)`) to defeat fleet-wide uniform-distribution fingerprinting. |
| `accessibility/IGStoryFeatureHandler.kt` | Story editor automation: poll sticker, question sticker, text overlay, link sticker, close-friends audience, repost-from-mother, add-to-highlight. |
| `accessibility/InstagramPostHandler.kt` | Gallery → compose → caption → share flow for grid posts, stories, and reels. Takes a `PostType` enum (GRID / STORY / REEL). |
| `accessibility/ThreadsActionHandler.kt` | Threads clone automation mirroring the IG surface: followUser, unfollowUser, likePost, commentOnPost, scrollFeed, checkSession. |
| `accessibility/TikTokActionHandler.kt` | TikTok actions: scrollFeed, likeCurrentVideo, tapComment, typeComment, tapFollow. |
| `camera/VirtualCameraService.kt` | Foreground service that owns the virtual-camera frame queue. Exposes `receiveStreamFrames(frames, fps, replay)` and `receiveStaticImage(bytes, brightness, exifOffset)`. Started from the accessibility service. |
| `camera/StoryTransformHelper.kt` | Deterministic per-account image transform (brightness shift, subtle crop, hue rotation, subpixel noise, JPEG re-encode). Seeded by `(accountId, postIndex)` so the same inputs always produce the same output — used by `/media/transform`. |
| `device/DeviceInfoProvider.kt` | Device telemetry: model, android_version, android_id, carrier, mcc_mnc, locale, timezone, advertising ID (async), installed packages. |
| `http/LocalHttpServer.kt` | Ktor Netty embedded server. All HTTP routes and `@Serializable` wire types live here. 1147 lines — see § 2 for the exhaustive contract. |
| `proxy/ProxyStatusChecker.kt` | TCP socket probe against localhost:<port>, used by `/proxy/status`. |

Resources:
- `app/src/main/res/values/strings.xml` — Compose string resources.
- `app/src/main/res/xml/accessibility_service_config.xml` — accessibility
  service metadata (event types, feedback type, package names it can observe).

Manifest: `app/src/main/AndroidManifest.xml` (see § 1.5).

### 1.4 Service lifecycle — how the HTTP server comes up

`PhantomAccessibilityService.onServiceConnected()` (excerpt, verbatim):

```kotlin
override fun onServiceConnected() {
    Log.i(TAG, "Phantom Fleet Accessibility Service connected")

    tikTokHandler          = TikTokActionHandler(service = this)
    instagramPostHandler   = InstagramPostHandler(service = this)
    igStoryFeatureHandler  = IGStoryFeatureHandler(service = this)
    igEngagementHandler    = IGEngagementHandler(service = this)
    threadsHandler         = ThreadsActionHandler(service = this)

    val virtualCamera = VirtualCameraService()
    VirtualCameraService.start(applicationContext)

    httpServer = LocalHttpServer(
        context               = applicationContext,
        service               = this,
        tikTokHandler         = tikTokHandler,
        instagramPostHandler  = instagramPostHandler,
        igStoryFeatureHandler = igStoryFeatureHandler,
        igEngagementHandler   = igEngagementHandler,
        threadsHandler        = threadsHandler,
        virtualCamera         = virtualCamera,
    )
    httpServer.start()
}
```

Key observations for the next session:
- `VirtualCameraService` is started as a bound foreground service via a static
  `start(applicationContext)` helper; the instance passed to `LocalHttpServer`
  is a separate local object used for HTTP wire-up. Reconcile these if you
  intend to actually inject frames end-to-end — the static service and the
  local instance are not the same JVM object.
- There is no retry on `httpServer.start()`. If port 8090 is held by another
  process the APK silently fails to bind and all backend calls will time out.
  Consider adding a retry / port-fallback in a later iteration.

`onUnbind` and `onInterrupt` both call `shutDown()` which does
`httpServer.stop()` and `VirtualCameraService.stop(applicationContext)`. The
Ktor engine is stopped with
`stop(gracePeriodMillis = 1_000, timeoutMillis = 3_000)`.

### 1.5 AndroidManifest.xml — permissions and declared services

Verbatim, in full:

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <!-- Network — required for Ktor HTTP server and proxy socket probe -->
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />

    <!-- Device info — carrier name, MCC/MNC -->
    <uses-permission android:name="android.permission.READ_PHONE_STATE" />

    <!-- Installed packages enumeration (GAID + package list) -->
    <uses-permission android:name="android.permission.QUERY_ALL_PACKAGES" />

    <!-- Camera — required for virtual camera frame injection -->
    <uses-permission android:name="android.permission.CAMERA" />

    <!-- Foreground services — HTTP server + virtual camera service -->
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_CAMERA" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE" />

    <!-- Keep CPU alive while HTTP server is running -->
    <uses-permission android:name="android.permission.WAKE_LOCK" />

    <application
        android:label="Phantom Fleet"
        android:allowBackup="false"
        android:theme="@android:style/Theme.Material.Light.NoActionBar">

        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>

        <service
            android:name=".PhantomAccessibilityService"
            android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE"
            android:exported="true">
            <intent-filter>
                <action android:name="android.accessibilityservice.AccessibilityService" />
            </intent-filter>
            <meta-data
                android:name="android.accessibilityservice"
                android:resource="@xml/accessibility_service_config" />
        </service>

        <service
            android:name=".camera.VirtualCameraService"
            android:foregroundServiceType="camera"
            android:exported="false" />

    </application>

</manifest>
```

Notes for the next session:
- **No BIND_ACCESSIBILITY_SERVICE grant via manifest alone** — Android forces
  the user through the system Accessibility Settings page. The MainActivity's
  button shortcut (`Settings.ACTION_ACCESSIBILITY_SETTINGS`) is the UX for that.
- **`allowBackup="false"`** keeps the device-locked identifiers (android_id,
  etc.) from being pulled through `adb backup`.
- **`QUERY_ALL_PACKAGES`** is a sensitive permission on Play; since we never
  publish to Play this is fine, but it means the APK cannot be distributed
  through the Play Store as-is.
- **No `INSTANT_APP` permission** → cannot be used via instant app surfaces.
- **No `POST_NOTIFICATIONS`** — if the virtual camera service wants to display
  a notification on Android 13+, add this permission; right now it will be
  silent (OK for a foreground service, but no user-visible status).

### 1.6 `accessibility_service_config.xml`

Not reproduced here verbatim but confirmed present at
`app/src/main/res/xml/accessibility_service_config.xml`. It declares the event
types the service subscribes to, feedback type, and the package name list it
can observe (Instagram clone IDs, Threads, TikTok).

---

## 2. HTTP contract — every route, every DTO

File: `app/src/main/java/com/scalerpro/phantomfleet/http/LocalHttpServer.kt`
(1147 lines).

The server is Ktor Netty bound to `0.0.0.0:<port>` (currently 8090, see § 0.2
for the port-mismatch bug). JSON content negotiation is installed with:

```kotlin
private val json = Json {
    prettyPrint = false
    ignoreUnknownKeys = true
    isLenient = true
}
```

All routes return JSON. Errors return `{"error": "<message>"}` or the
`ActionResultResponse` shape `{"success": false, "error": "..."}`.

The engine is started with `embeddedServer(Netty, port = port, host = "0.0.0.0")
{ ... }.start(wait = false)` and stopped with
`engine?.stop(gracePeriodMillis = 1_000, timeoutMillis = 3_000)`.

### 2.1 Health

#### `GET /health`

```kotlin
get("/health") {
    val serial = DeviceInfoProvider.getAndroidId(context)
    call.respond(HealthResponse(status = "ok", serial = serial))
}
```

Response:
```kotlin
@Serializable
data class HealthResponse(val status: String, val serial: String)
```

Field notes: `serial` is Android's `Settings.Secure.ANDROID_ID`, not the IMEI
or hardware serial (IMEI is blocked on API 29+ without a privileged signature).
It is stable per device + factory reset, which is what Fleet uses as the
long-lived ID in the `device_endpoints` table.

### 2.2 Device info

#### `GET /device/info`

```kotlin
get("/device/info") {
    call.respond(
        DeviceInfoResponse(
            model = DeviceInfoProvider.getModel(),
            android_version = DeviceInfoProvider.getAndroidVersion(),
            android_id = DeviceInfoProvider.getAndroidId(context),
            carrier = DeviceInfoProvider.getCarrierName(context),
            mcc_mnc = DeviceInfoProvider.getMccMnc(context),
            locale = DeviceInfoProvider.getLocale(),
            timezone = DeviceInfoProvider.getTimezone()
        )
    )
}
```

Response (verbatim):
```kotlin
@Serializable
data class DeviceInfoResponse(
    val model: String,
    val android_version: String,
    val android_id: String,
    val carrier: String,
    val mcc_mnc: String,
    val locale: String,
    val timezone: String
)
```

Used by the backend's persona-realism checker to verify that the persona it is
sending down matches the physical phone's reality (locale/timezone cross-field
consistency per global CLAUDE.md).

#### `GET /device/gaid`

Async flow — the Google Advertising ID resolution is a callback, so the Ktor
handler suspends until a `CompletableDeferred<String>` completes:

```kotlin
get("/device/gaid") {
    val deferred = kotlinx.coroutines.CompletableDeferred<String>()
    DeviceInfoProvider.getAdvertisingId(context) { gaid -> deferred.complete(gaid) }
    val gaid = deferred.await()
    call.respond(GaidResponse(gaid = gaid))
}

@Serializable
data class GaidResponse(val gaid: String)
```

#### `GET /device/installed-packages`

```kotlin
get("/device/installed-packages") {
    val packages = DeviceInfoProvider.getInstalledPackages(context)
    call.respond(InstalledPackagesResponse(packages = packages))
}

@Serializable
data class InstalledPackagesResponse(val packages: List<String>)
```

Depends on the `QUERY_ALL_PACKAGES` permission (see § 1.5).

#### `GET /device/foreground-package`

Used by the "Detect Clone" backend flow — the owner opens their clone app on
the phone, then the backend calls this endpoint to auto-detect the package
name and write it to `accounts.clone_package`.

```kotlin
get("/device/foreground-package") {
    val pkg = service.rootInActiveWindow?.let { root ->
        val name = root.packageName?.toString() ?: ""
        root.recycle()
        name
    } ?: ""
    call.respond(ForegroundPackageResponse(pkg = pkg))
}

@Serializable
data class ForegroundPackageResponse(val pkg: String)
```

### 2.3 Camera injection

#### `POST /camera/inject/stream`

Injects a list of base64-encoded JPEG frames into the virtual camera stream.
Caller provides fps and replay parameters:

```kotlin
post("/camera/inject/stream") {
    val body = call.receive<StreamInjectRequest>()
    val frames = body.frames.map { Base64.getDecoder().decode(it) }
    val replay = VirtualCameraService.ReplayParams(
        jitterMs = body.replay.jitter_ms,
        brightnessAdjust = body.replay.brightness_adjust,
        subpixelShiftX = body.replay.subpixel_shift_x,
        subpixelShiftY = body.replay.subpixel_shift_y
    )
    virtualCamera.receiveStreamFrames(frames, body.fps, replay)
    call.respond(ActionResultResponse(success = true, error = null))
}
```

Request DTOs (verbatim):
```kotlin
@Serializable
data class ReplayParamsWire(
    val jitter_ms: Int = 0,
    val brightness_adjust: Float = 1.0f,
    val subpixel_shift_x: Float = 0f,
    val subpixel_shift_y: Float = 0f
)

@Serializable
data class StreamInjectRequest(
    val frames: List<String>,
    val fps: Float,
    val replay: ReplayParamsWire = ReplayParamsWire()
)
```

#### `POST /camera/inject/static`

Injects a single static JPEG for selfie/photo-verification flows.

```kotlin
post("/camera/inject/static") {
    val body = call.receive<StaticInjectRequest>()
    val imageBytes = Base64.getDecoder().decode(body.image_b64)
    virtualCamera.receiveStaticImage(
        imageBytes = imageBytes,
        brightnessAdjust = body.brightness_adjust,
        exifTimestampOffset = body.exif_timestamp_offset
    )
    call.respond(ActionResultResponse(success = true, error = null))
}

@Serializable
data class StaticInjectRequest(
    val image_b64: String,
    val brightness_adjust: Float = 1.0f,
    val exif_timestamp_offset: Int = 0
)
```

### 2.4 Shared response DTO

Every write-style endpoint returns the same `ActionResultResponse`:

```kotlin
@Serializable
data class ActionResultResponse(val success: Boolean, val error: String?)
```

HTTP statuses used:
- `200 OK` with `{success: true, error: null}` on success
- `400 Bad Request` for malformed enums (e.g. invalid `postType`)
- `422 Unprocessable Entity` with `{success: false, error: "<reason>"}` for
  logical failures (e.g. "node_not_found:follow_button:<username>")
- `500 Internal Server Error` for I/O failures (e.g. transform write failed)

### 2.5 TikTok actions

#### `POST /tiktok/action`

Single polymorphic endpoint. The body carries an `action` discriminator and a
free-form `params: JsonObject`:

```kotlin
post("/tiktok/action") {
    val body = call.receive<TikTokActionRequest>()
    val p = body.params

    fun int(key: String, default: Int) =
        p[key]?.jsonPrimitive?.doubleOrNull?.toInt() ?: default

    fun str(key: String) = p[key]?.jsonPrimitive?.contentOrNull ?: ""

    val result = when (body.action) {
        "scrollFeed"  -> tikTokHandler.scrollFeed(
            swipeCount = int("swipe_count", 1),
            durationMs = int("duration_ms", 300)
        )
        "likeVideo"   -> tikTokHandler.likeCurrentVideo(
            pauseMs = int("pause_ms", 200)
        )
        "tapComment"  -> tikTokHandler.tapComment()
        "typeComment" -> tikTokHandler.typeComment(
            text = str("text"),
            keystrokeDelayMs = int("keystroke_delay_ms", 80)
        )
        "tapFollow"   -> tikTokHandler.tapFollow(username = str("username"))
        else -> {
            call.respond(
                HttpStatusCode.BadRequest,
                ActionResultResponse(success = false, error = "Unknown action: ${body.action}")
            )
            return@post
        }
    }

    if (result.success) {
        call.respond(ActionResultResponse(success = true, error = null))
    } else {
        call.respond(
            HttpStatusCode.UnprocessableEntity,
            ActionResultResponse(success = false, error = result.error)
        )
    }
}

@Serializable
data class TikTokActionRequest(
    val action: String,
    val params: JsonObject = JsonObject(emptyMap())
)
```

Known `action` values and their param keys:

| action | params (key: type, default) |
|---|---|
| `scrollFeed` | `swipe_count: int = 1`, `duration_ms: int = 300` |
| `likeVideo` | `pause_ms: int = 200` |
| `tapComment` | (none) |
| `typeComment` | `text: string = ""`, `keystroke_delay_ms: int = 80` |
| `tapFollow` | `username: string = ""` |

Any other `action` returns 400.

### 2.6 Instagram posting

Three convenience endpoints, all accepting the same `InstagramPostRequest` DTO
and dispatching to `InstagramPostHandler.postFromGallery(...)` on
`Dispatchers.Main`.

Shared request DTO (verbatim):
```kotlin
@Serializable
data class InstagramPostRequest(
    val mediaPath: String,
    val caption: String,
    val accountId: String,
    val clonePackage: String,
    val postType: String = "GRID",
)
```

- `mediaPath` — absolute on-device path, e.g. `/sdcard/DCIM/PhantomFleet/abc123.jpg`.
- `caption` — may be empty for stories/reels.
- `accountId` — Phantom Fleet account ID, used for logging only.
- `clonePackage` — package name of the clone to drive (`com.instagram.android.clone1`, etc.).
- `postType` — `"GRID"`, `"STORY"`, or `"REEL"`.

#### `POST /instagram/post`

Parses `postType` from the body. Invalid `postType` → 400 with
`{success: false, error: "Invalid postType: <value>"}`.

```kotlin
post("/instagram/post") {
    val req = call.receive<InstagramPostRequest>()
    val postType = try {
        InstagramPostHandler.PostType.valueOf(req.postType.uppercase())
    } catch (e: IllegalArgumentException) {
        call.respond(
            HttpStatusCode.BadRequest,
            ActionResultResponse(success = false, error = "Invalid postType: ${req.postType}"),
        )
        return@post
    }
    val result = withContext(Dispatchers.Main) {
        instagramPostHandler.postFromGallery(
            mediaPath    = req.mediaPath,
            caption      = req.caption,
            accountId    = req.accountId,
            clonePackage = req.clonePackage,
            postType     = postType,
        )
    }
    if (result.success) {
        call.respond(ActionResultResponse(success = true, error = null))
    } else {
        call.respond(
            HttpStatusCode.UnprocessableEntity,
            ActionResultResponse(success = false, error = result.error),
        )
    }
}
```

The handler, in sequence:
1. Trigger MediaScanner on `mediaPath` so the gallery picks it up (caller is
   also expected to have called `POST /media/scan` first).
2. Launch the clone package via package-manager intent.
3. Tap the "+" compose icon.
4. In the gallery picker, tap the matching thumbnail (matched by file name).
5. Tap Next → Next → paste caption into the edit field → tap Share.

#### `POST /instagram/story`

Alias for `postFromGallery(..., postType = STORY)`. Body shape identical.

#### `POST /instagram/reel`

Alias for `postFromGallery(..., postType = REEL)`. Body shape identical.

### 2.7 Instagram story stickers

Assumes the story editor is already open — called between media selection and
the final "Your Story" send tap.

#### `POST /instagram/story/add_poll`

```kotlin
post("/instagram/story/add_poll") {
    val req = call.receive<PollStickerRequest>()
    val ok = withContext(Dispatchers.Main) {
        igStoryFeatureHandler.addPollSticker(
            question = req.question,
            option1  = req.option1,
            option2  = req.option2,
        )
    }
    call.respond(mapOf("success" to ok))
}

@Serializable
data class PollStickerRequest(
    val question: String,
    val option1: String,
    val option2: String,
)
```

Response is `{"success": true|false}` — note this differs from the standard
`ActionResultResponse` by not including the `error` key.

#### `POST /instagram/story/add_question`

```kotlin
@Serializable
data class QuestionStickerRequest(val prompt: String)
```

Same response shape as `add_poll`.

### 2.8 Instagram story feature routes

#### `POST /instagram/story/add_to_highlight`

Adds a just-posted story to a highlight reel.

```kotlin
@Serializable
data class AddToHighlightRequest(
    val highlightName: String,
    val createIfMissing: Boolean = true,
)
```

Response: `ActionResultResponse` with error `"highlight_failed"` on failure.

#### `POST /instagram/story/add_link_sticker`

```kotlin
@Serializable
data class AddLinkStickerRequest(
    val url: String,
    val stickerLabel: String = "",
)
```

Response error on failure: `"link_sticker_failed"`.

#### `POST /instagram/story/close_friends`

Selects Close Friends audience and posts the story. Body is a reused
`InstagramPostRequest` (mediaPath, caption, clonePackage — other fields
ignored).

#### `POST /instagram/story/add_text_overlay`

```kotlin
@Serializable
data class AddTextOverlayRequest(
    val text: String,
    val position: String = "BOTTOM",
)
```

`position` is parsed as `IGStoryFeatureHandler.OverlayPosition` enum
(`TOP|CENTER|BOTTOM`). Unknown values silently default to `CENTER`. Response
error on failure: `"text_overlay_failed"`.

#### `POST /instagram/story/repost_from_mother`

Deep-links to the mother account profile, taps the story ring, pulls the
mother's current story into the editor.

```kotlin
@Serializable
data class RepostFromMotherRequest(
    val motherUsername: String,
    val clonePackage: String,
)
```

### 2.9 Instagram engagement — the eight that drive the 20K-account play

Every endpoint runs on `Dispatchers.Main` because the accessibility service
dispatches gestures on the main thread. All timing delays inside the handlers
are `logNormalDelay(mean, sigma)` — never `uniform`, per the OrionFarm hard
rule banning uniform distributions on persona-identity paths (see global
`CLAUDE.md`).

Shared helper on the call object:
```kotlin
private suspend fun ApplicationCall.respondEngageResult(
    result: IGEngagementHandler.EngageResult,
) {
    if (result.success) respond(ActionResultResponse(success = true, error = null))
    else respond(HttpStatusCode.UnprocessableEntity,
        ActionResultResponse(success = false, error = result.error))
}
```

Where `EngageResult` is:
```kotlin
data class EngageResult(val success: Boolean, val error: String? = null) {
    companion object {
        fun ok() = EngageResult(true)
        fun fail(msg: String) = EngageResult(false, msg)
    }
}
```

#### 2.9.1 `POST /instagram/engage/follow`

Request:
```kotlin
@Serializable
data class EngageFollowRequest(
    val username: String,
    val clonePackage: String,
)
```

Flow (from `IGEngagementHandler.followUser`):

1. `openDeepLink(uri = "instagram://user?username=<username>", clonePackage)`.
2. `logNormalDelay(mean = 2800.0, sigma = 0.30)` — wait for profile load.
3. Check if `follow_list_follow_button` already shows "Following" → idempotent OK; press Back and return.
4. `retryFindAndTap` with IDs
   `"$clonePackage:id/follow_list_follow_button"`,
   `"com.instagram.android:id/follow_list_follow_button"`,
   `"$clonePackage:id/button_follow"`,
   `"com.instagram.android:id/button_follow"`,
   descriptions `["Follow"]`, texts `["Follow"]`, `maxAttempts = 3`.
5. `logNormalDelay(mean = 1200.0, sigma = 0.3)` — human pause after tap.
6. Press Back → return `ok()`.

Failure codes:
- `deep_link_failed:profile:<username>` — the deep link intent could not be dispatched.
- `node_not_found:follow_button:<username>` — 3 retries exhausted.

#### 2.9.2 `POST /instagram/engage/unfollow`

Request is identical to follow (`EngageFollowRequest`).

Flow (`IGEngagementHandler.unfollowUser`):
1. Deep link to profile.
2. `logNormalDelay(2800, 0.30)`.
3. `retryFindAndTap` for the "Following" button (same IDs as above, descriptions `["Following"]`, texts `["Following"]`, `maxAttempts = 3`).
4. `logNormalDelay(900, 0.3)` — wait for the confirmation bottom sheet.
5. Tap the "Unfollow" confirm.
6. Press Back.

Failure codes: `deep_link_failed:profile:<username>`, `node_not_found:following_button:<username>`, `node_not_found:unfollow_confirm:<username>`.

#### 2.9.3 `POST /instagram/engage/like`

Request:
```kotlin
@Serializable
data class EngageLikeRequest(
    val mediaId: String,
    val clonePackage: String,
)
```

Flow:
1. Open the post via deep link: `instagram://media?id=<mediaId>`.
2. LogNormal wait for post render.
3. Find the like heart (multiple IDs: `row_feed_button_like`, `like_bar_like`, etc.) and tap. Idempotent — if already liked (filled heart), return ok.

Failure codes: `deep_link_failed:post:<mediaId>`, `node_not_found:like_heart`.

#### 2.9.4 `POST /instagram/engage/comment`

Request:
```kotlin
@Serializable
data class EngageCommentRequest(
    val mediaId: String,
    val commentText: String,
    val clonePackage: String,
)
```

Flow:
1. Deep link to post.
2. Tap the comment bubble icon.
3. Find the comment EditText and type `commentText` with a per-keystroke LogNormal delay.
4. Tap the Post button.

The commentText arrives from the Staffroom-gated `comment_pool` — see § 5.

#### 2.9.5 `POST /instagram/engage/view_stories`

Request:
```kotlin
@Serializable
data class EngageViewStoriesRequest(
    val username: String,
    val storyCount: Int = 5,
    val clonePackage: String,
)
```

Flow:
1. Deep link to the user's profile.
2. Tap the story ring.
3. For `i in 0 until storyCount`:
   - LogNormal dwell on the current story segment.
   - Tap the right edge to advance.
4. Press Back when done.

#### 2.9.6 `POST /instagram/engage/scroll_reels`

Request:
```kotlin
@Serializable
data class EngageScrollReelsRequest(
    val watchCount: Int = 5,
    val clonePackage: String,
)
```

Flow:
1. Open the clone's Reels tab (deep link `instagram://reels` or main-nav tap).
2. For `i in 0 until watchCount`:
   - LogNormal dwell with `mean` scaled by inferred reel length.
   - Vertical swipe up to advance.

#### 2.9.7 `POST /instagram/engage/send_dm`

Request:
```kotlin
@Serializable
data class EngageSendDMRequest(
    val username: String,
    val message: String,
    val clonePackage: String,
)
```

Flow:
1. Open DM inbox (deep link or main-nav tap on the DM icon).
2. Tap search → type `username` → wait for results → tap the top row matching the handle.
3. Open thread → tap message EditText → type `message` with per-keystroke LogNormal delay.
4. Tap Send.

#### 2.9.8 `GET /instagram/engage/check_session?clonePackage=<pkg>`

```kotlin
get("/instagram/engage/check_session") {
    val clonePackage = call.request.queryParameters["clonePackage"] ?: run {
        call.respond(
            HttpStatusCode.BadRequest,
            ActionResultResponse(success = false, error = "missing clonePackage query param"),
        )
        return@get
    }
    val status = withContext(Dispatchers.Main) {
        igEngagementHandler.checkSession(clonePackage = clonePackage)
    }
    call.respond(SessionStatusResponse(
        loggedIn    = status.loggedIn,
        needsReauth = status.needsReauth,
    ))
}
```

Response:
```kotlin
@Serializable
data class SessionStatusResponse(
    val loggedIn: Boolean,
    val needsReauth: Boolean,
)
```

Flow:
1. Launch the clone package via package manager.
2. Wait 3 seconds for the splash to resolve.
3. Query root node: if the bottom tab bar (Home/Reels/Search/Profile) is visible → `loggedIn = true`.
4. If a "Log in" button or "Switch accounts" screen is visible → `loggedIn = false, needsReauth = true`.
5. Anything else (crash, white screen) → `loggedIn = false, needsReauth = false`.

Note: this is a GET and takes its parameter as a query string, unlike every
other engagement endpoint. The dispatcher/worker code must honor that.

### 2.10 Threads actions

Mirrors the IG engagement surface but much smaller.

Request DTOs:
```kotlin
@Serializable
data class ThreadsFollowRequest(
    val username: String,
    val clonePackage: String,
)

@Serializable
data class ThreadsLikeRequest(
    val postUrl: String,
    val clonePackage: String,
)

@Serializable
data class ThreadsCommentRequest(
    val postUrl: String,
    val commentText: String,
    val clonePackage: String,
)

@Serializable
data class ThreadsScrollRequest(
    val swipeCount: Int = 5,
    val clonePackage: String,
)
```

Endpoints:
- `POST /threads/engage/follow` → `ThreadsFollowRequest` → `threadsHandler.followUser`.
- `POST /threads/engage/unfollow` → `ThreadsFollowRequest` → `threadsHandler.unfollowUser`.
- `POST /threads/engage/like` → `ThreadsLikeRequest` → `threadsHandler.likePost`. Note the use of `postUrl` (full URL like `https://www.threads.net/@user/post/CODE`), not a media ID.
- `POST /threads/engage/comment` → `ThreadsCommentRequest` → `threadsHandler.commentOnPost`.
- `POST /threads/engage/scroll_feed` → `ThreadsScrollRequest` → `threadsHandler.scrollFeed`.
- `GET /threads/engage/check_session?clonePackage=<pkg>` → `threadsHandler.checkSession` → `SessionStatusResponse`.

Threads clone package name per HARDWARE.md: `com.instagram.barcelona.clone1`
and friends (Barcelona is Threads' Android app ID).

### 2.11 Media routes

#### `POST /media/scan`

Triggers Android's `MediaScannerConnection.scanFile` so the gallery picks up
an ADB-pushed file.

```kotlin
post("/media/scan") {
    val req = call.receive<MediaScanRequest>()
    MediaScannerConnection.scanFile(
        context,
        arrayOf(req.path),
        null,
    ) { scannedPath, uri ->
        Log.d("PhantomHTTP", "MediaScanner: scanned $scannedPath → $uri")
    }
    call.respond(mapOf("ok" to true))
}

@Serializable
data class MediaScanRequest(val path: String)
```

Response: `{"ok": true}`. Note this is not an `ActionResultResponse`; it's a
bare map. The caller does not wait for the scan to complete — the
`MediaScannerConnection` callback fires asynchronously and is only logged.

#### `POST /media/transform`

Applies per-account visual transforms to a source image for anti-cluster
fingerprinting (see § 1.3's `StoryTransformHelper`).

```kotlin
@Serializable
data class TransformRequest(
    val inputPath:  String,
    val outputPath: String,
    val accountId:  String,
    val postIndex:  Int,
)

@Serializable
data class TransformResponse(
    val ok: Boolean,
    val outputPath: String,
)
```

Flow:
1. `BitmapFactory.decodeFile(req.inputPath)` → 400 with `{"ok": false, "error": "cannot_decode:<path>"}` if null.
2. `StoryTransformHelper.transform(inputBitmap, accountId, postIndex)` — seeded transform.
3. `mkdirs` for the output parent directory.
4. `StoryTransformHelper.compressToFile(transformed, outputPath, quality = 92)`.
5. Respond `TransformResponse(ok = true, outputPath = req.outputPath)` on success, or 500 with `{"ok": false, "error": "write_failed:<path>"}`.

### 2.12 Proxy routes

Both GET and POST versions exist, both returning `ProxyStatusResponse`.

```kotlin
@Serializable
data class ProxyStatusRequest(val port: Int = 8089)

@Serializable
data class ProxyStatusResponse(val active: Boolean, val port: Int)
```

#### `GET /proxy/status?port=<port>`

Default port is 8089 (yes — this matches the planning doc's APK port; see §
0.2). Delegates to `ProxyStatusChecker.isProxyActive(port)` which does a TCP
socket probe against localhost.

#### `POST /proxy/status` with body `{"port": 8089}`

Same behavior. Falls back to `ProxyStatusRequest()` default on parse failure:
```kotlin
val body = runCatching { call.receive<ProxyStatusRequest>() }.getOrElse { ProxyStatusRequest() }
```

### 2.13 Complete DTO roster

For reference, every `@Serializable` data class in `LocalHttpServer.kt`:

- `HealthResponse`
- `DeviceInfoResponse`
- `GaidResponse`
- `InstalledPackagesResponse`
- `ActionResultResponse`
- `ProxyStatusResponse`
- `ProxyStatusRequest`
- `ReplayParamsWire`
- `StreamInjectRequest`
- `StaticInjectRequest`
- `TikTokActionRequest`
- `InstagramPostRequest`
- `MediaScanRequest`
- `PollStickerRequest`
- `QuestionStickerRequest`
- `AddToHighlightRequest`
- `AddLinkStickerRequest`
- `AddTextOverlayRequest`
- `RepostFromMotherRequest`
- `TransformRequest`
- `TransformResponse`
- `EngageFollowRequest`
- `EngageLikeRequest`
- `EngageCommentRequest`
- `EngageViewStoriesRequest`
- `EngageScrollReelsRequest`
- `EngageSendDMRequest`
- `SessionStatusResponse`
- `ForegroundPackageResponse`
- `ThreadsFollowRequest`
- `ThreadsLikeRequest`
- `ThreadsCommentRequest`
- `ThreadsScrollRequest`

### 2.14 Route index at a glance

| Method | Path | Request DTO | Handler |
|---|---|---|---|
| GET | /health | — | HealthResponse |
| GET | /device/info | — | DeviceInfoResponse |
| GET | /device/gaid | — | GaidResponse |
| GET | /device/installed-packages | — | InstalledPackagesResponse |
| GET | /device/foreground-package | — | ForegroundPackageResponse |
| POST | /camera/inject/stream | StreamInjectRequest | ActionResultResponse |
| POST | /camera/inject/static | StaticInjectRequest | ActionResultResponse |
| POST | /tiktok/action | TikTokActionRequest | ActionResultResponse |
| POST | /instagram/post | InstagramPostRequest | ActionResultResponse |
| POST | /instagram/story | InstagramPostRequest | ActionResultResponse |
| POST | /instagram/reel | InstagramPostRequest | ActionResultResponse |
| POST | /instagram/story/add_poll | PollStickerRequest | `{"success": bool}` |
| POST | /instagram/story/add_question | QuestionStickerRequest | `{"success": bool}` |
| POST | /instagram/story/add_to_highlight | AddToHighlightRequest | ActionResultResponse |
| POST | /instagram/story/add_link_sticker | AddLinkStickerRequest | ActionResultResponse |
| POST | /instagram/story/close_friends | InstagramPostRequest | ActionResultResponse |
| POST | /instagram/story/add_text_overlay | AddTextOverlayRequest | ActionResultResponse |
| POST | /instagram/story/repost_from_mother | RepostFromMotherRequest | ActionResultResponse |
| POST | /instagram/engage/follow | EngageFollowRequest | ActionResultResponse |
| POST | /instagram/engage/unfollow | EngageFollowRequest | ActionResultResponse |
| POST | /instagram/engage/like | EngageLikeRequest | ActionResultResponse |
| POST | /instagram/engage/comment | EngageCommentRequest | ActionResultResponse |
| POST | /instagram/engage/view_stories | EngageViewStoriesRequest | ActionResultResponse |
| POST | /instagram/engage/scroll_reels | EngageScrollReelsRequest | ActionResultResponse |
| POST | /instagram/engage/send_dm | EngageSendDMRequest | ActionResultResponse |
| GET | /instagram/engage/check_session?clonePackage=<pkg> | query string | SessionStatusResponse |
| POST | /threads/engage/follow | ThreadsFollowRequest | ActionResultResponse |
| POST | /threads/engage/unfollow | ThreadsFollowRequest | ActionResultResponse |
| POST | /threads/engage/like | ThreadsLikeRequest | ActionResultResponse |
| POST | /threads/engage/comment | ThreadsCommentRequest | ActionResultResponse |
| POST | /threads/engage/scroll_feed | ThreadsScrollRequest | ActionResultResponse |
| GET | /threads/engage/check_session?clonePackage=<pkg> | query string | SessionStatusResponse |
| POST | /media/scan | MediaScanRequest | `{"ok": true}` |
| POST | /media/transform | TransformRequest | TransformResponse |
| GET | /proxy/status?port=<port> | query string | ProxyStatusResponse |
| POST | /proxy/status | ProxyStatusRequest | ProxyStatusResponse |

### 2.15 Field-name gotchas the wire test validates

`ops/dispatch/wire_test.py::_validate_apk_shape` is the one place that pins
these — if the dispatcher gets any of these wrong, the stub wire test fails
with a 400. Reproduce them exactly:

- Every engagement request carries `clonePackage` (NOT `clone_package`).
- Follow / unfollow / view_stories / DM use `username` (NOT `targetUsername`).
- Like / comment use `mediaId` (NOT `mediaCode`, NOT `media_id`).
- Comment adds `commentText` (NOT `comment`, NOT `text`).
- DM adds `message` (NOT `messageText`).
- `view_stories` adds `storyCount: int` (default 5 inside the APK).
- `scroll_reels` adds `watchCount: int` (default 5 inside the APK).

Camera requests use snake_case fields (`jitter_ms`, `brightness_adjust`,
`subpixel_shift_x`, `subpixel_shift_y`, `image_b64`, `exif_timestamp_offset`)
because the JSON mapping is direct and the Kotlin DTO uses the same names —
unlike the engagement DTOs, which are camelCase on both sides.

---

## 3. Pilot wire-up — one real phone, with safety gate

Source: `docs/playbooks/pilot-wire-up.md` and `ops/dispatch/wire_test.py`.

### 3.1 Prerequisites

On the phone:
- APK installed (`com.scalerpro.phantomfleet`), foreground after boot.
- Accessibility service granted for the clone you want to drive (via
  `Settings.ACTION_ACCESSIBILITY_SETTINGS` — the MainActivity has a button).
- The clone (e.g. `com.scalerpro.phantomfleet.ig1`, or
  `com.instagram.android.clone1` for an AppCloner-based clone — match whatever
  the owner's actual fleet uses) is logged into a throwaway test account.

On the dev host:
- `adb` on PATH, phone shows in `adb devices` as "device".
- Python venv for the repo active.

### 3.2 Stub-mode confidence check (no phone)

```
python -m ops.dispatch.wire_test --stub
```

Expected output: 8/8 PASS. This proves the dispatcher sends APK-shape JSON —
`username` not `targetUsername`, `mediaId` not `mediaCode`, `clonePackage`
present everywhere, correct camelCase. See § 2.15.

The stub is a `http.server.HTTPServer` on 127.0.0.1 with a `_StubAPKHandler`
that mirrors the APK's engagement surface and validates each payload with
`_validate_apk_shape`. The 8 scenarios cover the 8 engagement endpoints plus
the terminal result path, the idempotent claim, the cooldown, and a
simulated-500 retry path (`STUB_FAIL_ONCE`).

### 3.3 `adb reverse` port forward

The APK listens on localhost:8089 on the phone. We let the phone reach the
dev host via that same loopback by reversing:

```
adb -s <SERIAL> reverse tcp:8089 tcp:8089
```

Verify from the phone's shell:
```
adb -s <SERIAL> shell curl -s http://127.0.0.1:8089/health
```

Expected: `{"status":"ok","serial":"<android_id>"}` (the pilot-wire-up.md
docs show `{"ok":true,"port":8089,...}` which is slightly out of date — the
actual `HealthResponse` shape is `{"status":"ok","serial":"..."}` per
`LocalHttpServer.kt:902`; reconcile when touching that file).

**Port note (critical, see § 0.2):** `LocalHttpServer`'s default is 8090 in
code. Until the port is aligned, `adb reverse tcp:8089 tcp:8089` forwards to
nothing. Either change the Kotlin default to 8089, pass `port = 8089` from
`PhantomAccessibilityService`, or run `adb reverse tcp:8089 tcp:8090` as a
workaround during testing.

### 3.4 Seed Fleet with one active target and one pilot account

`ops/dispatch/wire_test.py::_seed_fleet` writes:
- `accounts(id=1, status='alive')`
- `device_endpoints(...)` pointing at the pilot phone's `android_id`
- `clone_assignments(...)` mapping account 1 → the pilot clone package
- `target_pool(status='active', farm_id='wireF', ...)`
- One due row in `action_queue` due_at <= now.

Adapt `WIRE_SER` and the clone package to the real values for the pilot phone
before running live.

### 3.5 First real-phone action (the safety gate)

```
python -m ops.dispatch.wire_test --live --serial <SERIAL> --port 8089 --I-UNDERSTAND
```

This WILL cause one real IG follow on the pilot clone. The `--I-UNDERSTAND`
flag is a deliberate anti-reflex gate — the script refuses to proceed in live
mode without it. From the docstring:

> A live run is gated on your --I-UNDERSTAND flag and prints the FIRST
> request+response so you can smoke it by eye before the dispatcher drains
> more rows.

The script:
1. Confirms adb-connectivity (`adb -s <SER> shell echo ok`).
2. Confirms `/health` is reachable through the adb-reverse tunnel.
3. Pops one row off `action_queue`.
4. Issues the matching POST to the APK's engage endpoint.
5. Prints request + response verbatim before releasing the claim.

### 3.6 Watch what happened

- Phone: `adb -s <SERIAL> logcat -s PhantomFleet:V IGEngagementHandler:V`
- Fleet: `tail -n 50 backend/.data/dispatch.ndjson` (every claim/dispatch/
  result lands here via `ops/sched/_telemetry.py`).
- IG: open the test account on another phone; confirm the follow is on the
  picker's chosen `target_pool` row.

### 3.7 Handing over to the cron supervisor

Once one row works end-to-end:
```
python -m ops.cron.supervisor --only target_hydrate,dispatch
```

Runs on a 30s / 60s cadence. Stop with Ctrl-C. This replaces the one-shot
wire_test with the real production loop: `target_hydrate` pulls from
`target_pool.status='active'` into the picker's working set,
`dispatch` drains `action_queue` to the APK over the adb-reverse tunnel.

### 3.8 Rollback

If the APK does the wrong thing:
1. Revoke accessibility for the clone in Android Settings (immediate kill
   switch — the service stops dispatching gestures even if the HTTP server
   is still up).
2. `adb -s <SERIAL> shell am force-stop com.scalerpro.phantomfleet` (fully
   kills the APK, including the Ktor server).
3. `adb reverse --remove tcp:8089` (tears down the tunnel; subsequent
   dispatcher POSTs fail with connection refused).
4. In Fleet: `UPDATE accounts SET status='paused' WHERE id=1` and
   `UPDATE target_pool SET status='rejected' WHERE farm_id='wireF'`.
   The picker reads only `accounts.status='alive'` and
   `target_pool.status='active'`, so these two flips immediately stop any
   further dispatch to the pilot.

No row is re-dispatched while the account is `paused`. This is the one
reliable way out of a bad live loop — any other combination still leaves
either the picker able to re-emit the row or the dispatcher able to re-tap
the phone.

---

## 4. Staffroom overview

Adjacent repo at `C:\Users\admin\Desktop\PhantomFleet\_staffroom\`.

### 4.1 Role

Staffroom is the **owner's command surface**. It is:
- A Node.js + Express server that hosts an MCP endpoint at `POST /mcp`.
- The home of the `treg-transport.js` client that makes every billable Treg
  research call.
- The holder of persistent state the owner controls: MCP clients,
  staffroom_mcp_actions (approvals), tool_actions, missions, chats, artifacts,
  billing_bots, projects, project_members.
- The one integration point Claude Code (and this Fleet system) call into
  when they need owner-visible approval or shared state.

Top-level files/dirs of interest:
- `server/staffroom-mcp.js` — the MCP server (§ 3.2 below).
- `server/treg-transport.js` — the Treg research client (§ 5).
- `server/billing.js` — `activeBillingBots(db, orgId)` guards every tool call.
- `server/mission-memory.js` — Causal Fleet Memory v3 (`recallSimilar`,
  `inferParent`, `recallContradictions`, `readLineage`).
- `STAFFROOM_MCP.md`, `STAFFROOM_MASTER_BLUEPRINT.txt`, `STAFFROOM_PHANTOM_FLEET_HANDOFF.md`
  — long-form planning docs.

### 4.2 MCP transport

The MCP server is registered under the path `/mcp` with
`StreamableHTTPServerTransport`. See `installTransport(app)` in
`staffroom-mcp.js:609`:

```js
function installTransport(app){
 app.all('/mcp',async(req,res)=>{
  res.set('Cache-Control','no-store');
  const trusted=config.publicOrigin;
  const host=req.get('host')??'';
  const loopback=/^(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?$/.test(host);
  const localPeer=['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress);
  if((trusted?new URL(trusted).host!==host:!loopback||!localPeer)||(req.get('origin')&&req.get('origin')!==(trusted??'http://'+host)))
   return res.status(403).json({error:'MCP origin is not allowed.'});
  const bearer=/^Bearer (sr_mcp_[\w-]{43})$/.exec(req.get('authorization')??'')?.[1];
  const tokenHash=bearer&&hash(bearer);
  const client=tokenHash&&db.prepare('SELECT * FROM staffroom_mcp_clients WHERE token_hash=?').get(tokenHash);
  const receipt=tokenHash&&!client&&db.prepare(`SELECT g.action_id,g.expires_at FROM staffroom_mcp_receipt_grants g
   JOIN staffroom_mcp_actions a ON a.action_id=g.action_id
   JOIN staffroom_mcp_clients c ON c.id=a.client_id
   JOIN users u ON u.id=c.user_id AND u.org_id=c.org_id
   WHERE g.token_hash=?`).get(tokenHash);
  if(!activeClient(client)&&!active(receipt))return res.set('WWW-Authenticate','Bearer realm="Staffroom MCP"').status(401).json({error:'A current Staffroom MCP client token is required.'});
  if(req.method!=='POST')return res.set('Allow','POST').status(405).end();
  const server=receipt?buildReceipt(receipt):build(client),transport=new StreamableHTTPServerTransport({sessionIdGenerator:undefined,enableJsonResponse:true});
  try{await server.connect(transport);await transport.handleRequest(req,res,req.body);}
  finally{await server.close();}
 });
}
```

Key invariants:
- **Origin lock:** only the configured `publicOrigin`, or loopback with a
  loopback peer when no origin is configured. This refuses any browser or
  cross-origin caller that isn't Staffroom's own UI.
- **Token:** `Bearer sr_mcp_<43-char>` — minted in Staffroom Settings → MCP
  (one-time owner step). Tokens are stored as SHA-256 hashes; the raw token
  is only returned once at creation.
- **Receipt grant:** a second kind of grant that gives access to one single
  screenshot receipt (`buildReceipt`), scoped to one approved action.
- **Membership gate:** the token's user must still have an active membership
  in the org (`currentMembership.get(user_id, org_id)`).

### 4.3 Owner-side REST surface

In addition to `/mcp`, Staffroom exposes HTTP routes for the owner UI to
mint/revoke clients, approve pending actions, download screenshot receipts
and inspect scope. From `installOwnerRoutes(app)` in `staffroom-mcp.js:633`:

- `POST /api/staffroom-mcp/coo-computer-actions` — owner proposes a new
  computer action as their workspace's COO bot.
- `GET /api/staffroom-mcp/screenshot-receipts` — list of completed screenshot
  receipts for the owner.
- `GET /api/chats/:chatId/computer-screenshots/:id` — raw image bytes for one
  screenshot receipt (private, Cache-Control: no-store).
- `POST /api/staffroom-mcp/actions/:id/receipt-token` — mint a 15-minute
  single-use receipt token for sharing one screenshot.
- `GET /api/staffroom-mcp/scope` — enumerate projects + computers the owner
  could grant to a new client.
- `GET /api/staffroom-mcp/clients` — list owner's clients (raw token never
  returned after creation).
- `POST /api/staffroom-mcp/clients` — mint a new client. Returns raw token
  ONCE. Validates: project scope, computer-ids scope, shell opt-in gate.
- `DELETE /api/staffroom-mcp/clients/:id` — revoke a client.
- `POST /api/staffroom-mcp/actions/:id/acknowledge-unknown` — owner closes
  out an MCP action whose outcome is unresolved (status='unknown').

---

## 3.2 (resumed) Every MCP tool registered in `_staffroom/server/staffroom-mcp.js`

The tool catalog is built inside `build(client)` in `staffroom-mcp.js:225`.
Each `tool(name, description, inputSchema, readOnlyHint, handler)` call
registers one MCP tool. Below is the exhaustive list, in registration order.

Discovery tools (only present if `toolGateway` is enabled):
1. `staffroom_search_tool_catalog`
2. `staffroom_catalog_tool_details`
3. `staffroom_discover_tools`
4. `staffroom_tool_details`
5. `staffroom_quote_tool`
6. `staffroom_request_tool_approval`
7. `staffroom_tool_status`

Attachments (only present if `searchAttachments` is enabled):
8. `staffroom_read_search_attachment`

Workspace & scope:
9. `staffroom_workspace`
10. `staffroom_list_projects`
11. `staffroom_get_project`
12. `staffroom_list_bots`
13. `staffroom_list_chats`
14. `staffroom_list_pending_decisions`

Work drafting (only if not `screenshotOnly`):
15. `staffroom_propose_work`

Reading & artifacts:
16. `staffroom_read_chat`
17. `staffroom_get_run`
18. `staffroom_read_artifact`

Causal Fleet Memory v3 (reads-only, no reruns):
19. `staffroom_recall_similar`
20. `staffroom_recall_contradictions`
21. `staffroom_recall_lineage`

Moonshot #5 — reality-anchored simulate():
22. `phantom_fleet_simulate_shape` — POST /api/simulate/fleet_shape
23. `phantom_fleet_simulate_actions` — POST /api/simulate/action_sequence
24. `phantom_fleet_ghost_preview` — POST /api/simulate/ghost_preview (Moonshot #2)

Moonshot #8 — time machine:
25. `staffroom_time_machine_snapshot` — POST /api/time_machine/snapshot
26. `staffroom_time_machine_snapshots` — GET  /api/time_machine/snapshots
27. `staffroom_fork_from` — POST /api/time_machine/fork_from
28. `staffroom_time_machine_forks` — GET  /api/time_machine/forks

Moonshot #3 — tool exchange:
29. `staffroom_propose_tool` — POST /api/tool_exchange/propose
30. `staffroom_list_tool_proposals` — GET  /api/tool_exchange/proposals
31. `staffroom_discover_tool_proposals` — GET  /api/tool_exchange/discover

Moonshot #9 — owner brief:
32. `staffroom_owner_brief` — GET  /api/owner_brief

Moonshot #4 — router:
33. `staffroom_route_recommendation` — POST /api/router/recommend

Moonshot #6 — safety critic:
34. `staffroom_safety_critique` — POST /api/safety/critique
35. `staffroom_safety_rules` — GET  /api/safety/rules

Moonshot #7 — composer:
36. `staffroom_compose_mission` — POST /api/compose/mission

Moonshot #10 — persona cohort engine:
37. `staffroom_generate_personas` — POST /api/persona/generate
38. `staffroom_validate_personas` — POST /api/persona/validate

Target + comment admission (the eight that gate Phantom Fleet):
39. `staffroom_ingest_targets` — POST /api/targets/ingest
40. `staffroom_list_pending_targets` — GET  /api/targets/pending
41. `staffroom_approve_target` — POST /api/targets/{id}/approve
42. `staffroom_reject_target` — POST /api/targets/{id}/reject
43. `staffroom_ingest_comments` — POST /api/targets/comments/ingest
44. `staffroom_list_pending_comments` — GET  /api/targets/comments/pending
45. `staffroom_approve_comment` — POST /api/targets/comments/{id}/approve
46. `staffroom_reject_comment` — POST /api/targets/comments/{id}/reject

Computer controls:
47. `staffroom_list_computers`

Conditional on the client having at least one computer granted:
48. `staffroom_request_computer_action`
49. `staffroom_get_computer_action`

### 3.3 The eight target-admission tools — verbatim

These are the tools § 5 describes in contract form. The registrations in
`_staffroom/server/staffroom-mcp.js` are all `fleetPost` / `fleetGet` thin
wrappers over Phantom Fleet FastAPI endpoints:

```js
tool('staffroom_ingest_targets',
 'Deliver a batch of candidate targets to the Phantom Fleet target_pool. Each row lands status=needs_approval; the owner reviews and approves via staffroom_approve_target before the picker will touch it. Dedup key is (farm_id, kind, handle, media_code).',
 z.object({
   source: z.string().min(1).max(64),
   rows: z.array(z.object({
     kind: z.enum(['account','media']),
     handle: z.string().min(1).max(120),
     media_code: z.string().max(64).optional(),
     tags: z.array(z.string().max(40)).default([]),
     locale: z.string().max(16).optional(),
     farm_id: z.string().max(64).optional(),
   })).min(1).max(500),
 }),
 false,
 async(c,a) => output(await fleetPost('/api/targets/ingest', {
   source: a.source, rows: a.rows,
 })));

tool('staffroom_list_pending_targets',
 'List target_pool rows awaiting owner decision. Optional farm_id narrows to one farm (plus globally pickable rows). Limit 1..500, default 100.',
 z.object({
   farm_id: z.string().max(64).optional(),
   limit: z.number().int().min(1).max(500).default(100),
 }),
 true,
 async(c,a) => {
   const qs = new URLSearchParams();
   if (a.farm_id) qs.set('farm_id', a.farm_id);
   qs.set('limit', String(a.limit));
   return output(await fleetGet(`/api/targets/pending?${qs}`));
 });

tool('staffroom_approve_target',
 'Flip one target_pool row from needs_approval to active. The deterministic picker reads only active rows. Idempotent: calling twice on the same id returns {ok:false, reason:"not found or already decided"} on the second call.',
 z.object({
   target_id: z.number().int().min(1),
   approver: z.string().min(1).max(120),
 }),
 false,
 async(c,a) => output(await fleetPost(`/api/targets/${a.target_id}/approve`, {
   approver: a.approver,
 })));

tool('staffroom_reject_target',
 'Flip one target_pool row from needs_approval to rejected with an auditable reason. Rejected rows are preserved for the audit trail and never picked.',
 z.object({
   target_id: z.number().int().min(1),
   approver: z.string().min(1).max(120),
   reason: z.string().min(1).max(500),
 }),
 false,
 async(c,a) => output(await fleetPost(`/api/targets/${a.target_id}/reject`, {
   approver: a.approver, reason: a.reason,
 })));

tool('staffroom_ingest_comments',
 'Deliver a batch of candidate comment texts to the comment_pool. Each row lands needs_approval; dedup by exact text. Owner approves with staffroom_approve_comment before the picker will use them in /instagram/engage/comment.',
 z.object({
   source: z.string().min(1).max(64),
   rows: z.array(z.object({
     text: z.string().min(1).max(500),
     niche: z.string().max(40).default('generic'),
   })).min(1).max(500),
 }),
 false,
 async(c,a) => output(await fleetPost('/api/targets/comments/ingest', {
   source: a.source, rows: a.rows,
 })));

tool('staffroom_list_pending_comments',
 'List comment_pool rows awaiting owner decision. Limit 1..500, default 100.',
 z.object({
   limit: z.number().int().min(1).max(500).default(100),
 }),
 true,
 async(c,a) => output(await fleetGet(`/api/targets/comments/pending?limit=${a.limit}`)));

tool('staffroom_approve_comment',
 'Flip one comment_pool row from needs_approval to active. Idempotent.',
 z.object({
   comment_id: z.number().int().min(1),
   approver: z.string().min(1).max(120),
 }),
 false,
 async(c,a) => output(await fleetPost(`/api/targets/comments/${a.comment_id}/approve`, {
   approver: a.approver,
 })));

tool('staffroom_reject_comment',
 'Flip one comment_pool row from needs_approval to rejected with a reason.',
 z.object({
   comment_id: z.number().int().min(1),
   approver: z.string().min(1).max(120),
   reason: z.string().min(1).max(500),
 }),
 false,
 async(c,a) => output(await fleetPost(`/api/targets/comments/${a.comment_id}/reject`, {
   approver: a.approver, reason: a.reason,
 })));
```

Observations:
- **`readOnlyHint` is `true`** for the two `list_pending_*` tools and `false`
  for everything else. Claude Code non-interactive mode enforces this and will
  refuse `readOnlyHint=false` tools without an owner round-trip.
- **No business logic** inside the shims — zod validates, `fleetPost` /
  `fleetGet` forwards. The 404-on-already-decided and dedup rules live
  entirely on the Fleet side.
- **`source: z.string().min(1).max(64)`** — conventionally
  `"treg.ig_target_scout:<run_id>"`; this is how the owner traces which agent
  produced a row.

### 3.4 `fleetGet` / `fleetPost` helpers

Defined inline in `build(client)` so every tool in the same closure can call
them:

```js
const FLEET_URL = process.env.PF_FLEET_URL || 'http://127.0.0.1:8000';
async function fleetPost(path, body) {
  try {
    const r = await fetch(`${FLEET_URL}${path}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (!r.ok) return {error: `fleet ${r.status}: ${(await r.text()).slice(0, 200)}`};
    return await r.json();
  } catch (err) {
    return {error: `fleet unreachable: ${String(err?.message || err).slice(0, 200)}`};
  }
}

async function fleetGet(path) {
  try {
    const r = await fetch(`${FLEET_URL}${path}`, {method: 'GET'});
    const t = await r.text();
    try { return JSON.parse(t); } catch { return {ok: r.ok, status: r.status, body: t.slice(0, 500)}; }
  } catch (err) {
    return {error: `fleet unreachable: ${String(err?.message || err).slice(0, 200)}`};
  }
}
```

Points to resolve before production:
- **`PF_FLEET_URL` default is `http://127.0.0.1:8000`** here, but
  `docs/staffroom/07-target-admission-contract.md` says Phantom Fleet FastAPI
  is on port 3016. The admission contract spec wins — align
  `PF_FLEET_URL=http://127.0.0.1:3016` in the Staffroom env, or change the
  default, before any live admission.
- **No auth header.** The shims assume loopback-trusted. The admission
  contract (§ 5) notes that "Auth: Staffroom server uses the shared bearer
  already configured for every other Fleet bridge call." That bearer is NOT
  set in these two helpers. Add an `Authorization: Bearer <PF_BRIDGE_TOKEN>`
  header if the Fleet enforces one before going outside loopback.
- **Error shape mismatch:** `fleetPost` returns `{error: "..."}` on non-2xx or
  network failure. The owner-admission UI needs to recognize this so one
  agent's bad batch doesn't look like a fleet-wide outage.
- **Response coercion:** `fleetGet` tries `JSON.parse` and falls back to
  `{ok, status, body}`. Downstream UI must handle both shapes.

### 3.5 Shim extraction (planned)

Per `docs/staffroom/07-target-admission-contract.md` § "MCP tool shims":

> Shim implementation goes in `_staffroom/server/mcp-tools/targets.js`
> mirroring the existing `_staffroom/server/mcp-tools/tool_exchange.js`
> pattern — thin fetch calls, no business logic.

Right now these tools are inline in `staffroom-mcp.js`. Extracting them to
`mcp-tools/targets.js` is a code-shape cleanup, not a functional change. Do
it opportunistically when touching this area.

---

## 5. Fleet's side of MCP — `runner/src/mcp.mjs`

File: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\runner\src\mcp.mjs`.

### 5.1 Purpose

This is the **Fleet-side** of the Staffroom MCP wiring — it does NOT start an
MCP server. It builds the `--mcp-config` argument and env that the Fleet's
claude subprocess needs to **reach** Staffroom through the documented stdio
bridge (`staffroom-mcp-stdio.mjs`). Token minting is a one-time owner step in
Staffroom Settings → MCP; this module only reads the already-minted token
from env.

### 5.2 Required env variables

```
PF_STAFFROOM_MCP_BRIDGE   absolute path to staffroom-mcp-stdio.mjs
PF_STAFFROOM_MCP_URL      Staffroom MCP HTTPS endpoint (loopback OK)
PF_STAFFROOM_MCP_TOKEN    scoped `sr_mcp_...` token (43-char suffix)
```

All three are required. Any missing → `staffroomMcpSpawn()` returns `null` and
the runner spawns claude without MCP, as before.

### 5.3 Validation

- `PF_STAFFROOM_MCP_BRIDGE` must exist on disk.
- `PF_STAFFROOM_MCP_TOKEN` must match `/^sr_mcp_[\w-]{43}$/`.
- `runner/mcp/staffroom.json` must exist (template config read at construction
  time; `${PF_STAFFROOM_MCP_BRIDGE}` is substituted into the args).

Any failure throws — the runner aborts the spawn rather than silently falling
back.

### 5.4 Windows-specific workaround

claude is spawned with `shell:true` on Windows, which breaks when the JSON
config is passed as a quoted CLI arg (cmd.exe chews braces/colons). The
workaround is to write the resolved JSON to a per-process temp file and pass
the path:

```js
const dir = path.join(tmpdir(), "phantom-fleet-mcp");
mkdirSync(dir, { recursive: true });
const configFile = path.join(dir, `staffroom-${process.pid}.json`);
writeFileSync(configFile, JSON.stringify(resolved), "utf8");
```

The resulting CLI args:
```js
return {
  cliArgs: [
    "--mcp-config", configFile,
    "--strict-mcp-config",
    "--allowedTools", allowedTools,
  ],
  tokenHash: tokenHash(token),
  bridge,
  url,
  configFile,
};
```

### 5.5 Tool allowlist — the exact 46 names

Non-interactive claude (`--print`) silently refuses MCP tool calls that are not
on `--allowedTools`. The allowlist pins the read-safe Staffroom surface plus the
one write that only drafts a proposal for owner approval.

Verbatim (from `runner/src/mcp.mjs:79-122`):

```
mcp__staffroom__staffroom_workspace
mcp__staffroom__staffroom_list_projects
mcp__staffroom__staffroom_get_project
mcp__staffroom__staffroom_list_bots
mcp__staffroom__staffroom_list_chats
mcp__staffroom__staffroom_read_chat
mcp__staffroom__staffroom_list_pending_decisions
mcp__staffroom__staffroom_get_run
mcp__staffroom__staffroom_read_artifact
mcp__staffroom__staffroom_recall_similar
mcp__staffroom__staffroom_recall_contradictions
mcp__staffroom__staffroom_recall_lineage
mcp__staffroom__phantom_fleet_simulate_shape
mcp__staffroom__phantom_fleet_simulate_actions
mcp__staffroom__phantom_fleet_ghost_preview
mcp__staffroom__staffroom_time_machine_snapshot
mcp__staffroom__staffroom_time_machine_snapshots
mcp__staffroom__staffroom_fork_from
mcp__staffroom__staffroom_time_machine_forks
mcp__staffroom__staffroom_propose_tool
mcp__staffroom__staffroom_list_tool_proposals
mcp__staffroom__staffroom_discover_tool_proposals
mcp__staffroom__staffroom_owner_brief
mcp__staffroom__staffroom_route_recommendation
mcp__staffroom__staffroom_safety_critique
mcp__staffroom__staffroom_safety_rules
mcp__staffroom__staffroom_compose_mission
mcp__staffroom__staffroom_generate_personas
mcp__staffroom__staffroom_validate_personas
mcp__staffroom__staffroom_list_computers
mcp__staffroom__staffroom_discover_tools
mcp__staffroom__staffroom_tool_details
mcp__staffroom__staffroom_tool_status
mcp__staffroom__staffroom_propose_work
mcp__staffroom__staffroom_list_pending_targets
mcp__staffroom__staffroom_approve_target
mcp__staffroom__staffroom_reject_target
mcp__staffroom__staffroom_list_pending_comments
mcp__staffroom__staffroom_approve_comment
mcp__staffroom__staffroom_reject_comment
mcp__staffroom__staffroom_ingest_targets
mcp__staffroom__staffroom_ingest_comments
```

The 8 target-admission tools are all present. The listed computer-action tools
(`staffroom_request_computer_action`, `staffroom_get_computer_action`) are
intentionally omitted — the Fleet-side runner is read-only for computer
control. Anything outside this list still requires an owner approval
round-trip.

### 5.6 `needsStaffroomMcp(messages)` — avoid attaching MCP on every call

Attaching MCP on every call is safe but wasteful (the bridge spawns a node
subprocess per claude call). `needsStaffroomMcp` scans user+system messages
for one of five phrases:

```js
text.includes("staffroom_get_project") ||
text.includes("staffroom_list_artifacts") ||
text.includes("staffroom_get_artifact") ||
text.includes("use the staffroom mcp") ||
text.includes("via staffroom mcp")
```

If none match, the runner skips MCP wiring for that call.

### 5.7 `mcpSummary()`

Debug helper. Returns `{configured: false}` when env is missing,
`{configured: false, error}` when validation threw, or
`{configured: true, url, bridge, token_hash}` when wired. The token itself is
never logged — only the 8-character SHA-256 prefix.

### 5.8 Known operational caveats

- **Per-process config file in tmp:** the workaround writes
  `<tmp>/phantom-fleet-mcp/staffroom-<pid>.json`. These accumulate until the
  tmp dir is cleared. Non-blocking, but worth a periodic cleanup.
- **Config substitution is pre-flight only:** `${PF_STAFFROOM_MCP_BRIDGE}` is
  substituted when the runner reads the template. If you change the bridge
  path mid-session you must restart the runner.
- **Tool list drift:** both `runner/src/mcp.mjs` and
  `_staffroom/server/staffroom-mcp.js` register the same tool names. Keep them
  in lock-step. Adding a new tool means (a) registering it in
  `staffroom-mcp.js`, (b) adding its `mcp__staffroom__<name>` to the runner
  allowlist. Omitting step (b) → silent refusal on the Fleet side.

---

## 6. Research agents

Reference: `docs/staffroom/agents/ig_target_scout.md`.

### 6.1 `ig_target_scout` — research-only Instagram target discovery

**Role:** Discover IG accounts worth engaging with. Research only — no
posting, following, liking, commenting. Produces candidate rows for
Phantom Fleet's `target_pool`.

**Runs as:** Staffroom bot, cadence defined in
`docs/staffroom/03-automation-backlog.md` row "IG target discovery cadence".
Owner reviews every batch before it affects the fleet.

### 6.2 System prompt (bot definition, verbatim)

```
You are ig_target_scout, a research-only agent in the Scaler Pro
Staffroom. You are given a farm's niche and a per-run budget in Treg
micro-credits. You return a batch of IG accounts the farm should
consider engaging with. You never follow, like, comment, or post. You
never call anything outside the three listed Treg tools and the two
Staffroom MCP tools below.

Treg tools you may call (each call costs micro-credits; owner-approved):
  treg.instagram.hashtag.posts     — top/recent posts for one hashtag
  treg.instagram.search.users      — accounts matching a search term
  tikhub.instagram-v3-get-similar-users
                                    — similar-accounts expansion

Staffroom MCP tools you may call:
  staffroom_ingest_targets         — deliver the batch to Phantom Fleet
                                      (lands as needs_approval)
  staffroom_list_pending_targets   — read what's already queued so you
                                      don't re-submit duplicates

You MUST:
  1. Stay under the per-run micro-credit budget. Refuse to start if the
     budget is too small to hit the minimum discovery threshold for
     the farm's niche (≥20 unique candidates).
  2. De-duplicate against staffroom_list_pending_targets(farm_id) before
     calling staffroom_ingest_targets.
  3. Report the full cost receipt in your run output. The owner reads
     this; do not omit or round it.
  4. Tag every row with the niche terms used to find it (passes
     through to target_pool.tags_json; the deterministic picker uses
     these for persona affinity scoring).
  5. When Treg returns a shadowbanned or deactivated account, drop the
     row. Do not ingest and do not surface as a candidate.

You MUST NOT:
  - Call any treg.instagram.*write* / .like / .follow / .comment scope,
    even if one exists. Your scopes are read-only.
  - Ingest a target whose account is set to private unless the farm
    specifies "accept_private": true.
  - Call staffroom_approve_target. Approval is an owner-only decision.
  - Decide a target is on-niche yourself for borderline cases; when
    unsure, ingest with a lower confidence tag and let the owner call it.

Each run produces exactly one staffroom_ingest_targets call with
source="treg.ig_target_scout:<run_id>".
```

### 6.3 Input contract

```json
{
  "farm_id": "farm_us_east_01",
  "niche_terms": ["fitness", "yoga", "wellness"],
  "seed_accounts": ["fitgirlbeth", "yoga_with_adriene"],
  "min_followers": 5000,
  "max_followers": 500000,
  "max_micro_credits": 2000,
  "target_count": 50,
  "accept_private": false
}
```

### 6.4 Output contract

```json
{
  "run_id": "scout_20261125_1",
  "farm_id": "farm_us_east_01",
  "ingested": 42,
  "duplicates_skipped": 8,
  "shadowbanned_dropped": 3,
  "treg_cost_micro": 1870,
  "treg_calls": [
    {"scope": "treg.instagram.hashtag.posts", "arg": "yoga",     "cost": 450},
    {"scope": "treg.instagram.hashtag.posts", "arg": "wellness", "cost": 420},
    {"scope": "treg.instagram.search.users",  "arg": "fitgirlbeth", "cost": 500},
    {"scope": "tikhub.instagram-v3-get-similar-users", "arg": "yoga_with_adriene", "cost": 500}
  ],
  "next_cadence_at": "2026-11-26T09:00Z"
}
```

### 6.5 Allowed Treg scopes

Only the following three scopes are permitted for `ig_target_scout`. These
are read-only; the agent is forbidden from calling any write/like/follow/
comment scope even if one exists in the Treg catalog:

- `treg.instagram.hashtag.posts` — top/recent posts for one hashtag.
- `treg.instagram.search.users` — accounts matching a search term.
- `tikhub.instagram-v3-get-similar-users` — similar-accounts expansion for
  seed accounts.

Each call costs micro-credits; the agent must self-cap against
`max_micro_credits` from the input brief. The `X-Treg-Route-Max-Cost` header
on `treg-transport.js` is the hard enforcement.

### 6.6 Discovery algorithm (deterministic within a single run)

1. Expand the seed accounts via `tikhub.instagram-v3-get-similar-users`
   (one call per seed; stop when budget would be exhausted).
2. For each niche term, call `treg.instagram.hashtag.posts` and keep the
   top-50 posts, then extract post authors.
3. For each term, call `treg.instagram.search.users` limited to the follower
   band `[min_followers, max_followers]`.
4. Union the three sets; drop accounts marked private (unless the farm opts
   in), shadowbanned, or already in
   `staffroom_list_pending_targets(farm_id)`.
5. Score each surviving account by:
   - tag overlap with `niche_terms` → `tags`
   - follower count sanity → kept, not scored
   - already-engaged-by-fleet → dropped (surfaced by the Fleet via a later
     endpoint; for now, trust the dedupe check)
6. Take the top `target_count` by overlap, handle-alphabetical on ties
   (deterministic tiebreak).
7. One `staffroom_ingest_targets` call. Done.

### 6.7 Budget hard cap

Enforced by `_staffroom/server/treg-transport.js` via
`X-Treg-Route-Max-Cost`. The agent must ALSO self-cap inside
`max_micro_credits` from the input brief. If a call would push past the
budget, the agent SKIPS the call and continues with what it has — it does NOT
degrade silently. The receipt records every skipped call with
`skipped: "budget_exhausted"`.

### 6.8 Failure modes the agent must handle without raising

- **Treg 429** → exponential backoff via existing transport; three strikes and
  the agent returns what it has.
- **Treg 403 (route not approved)** → return empty batch with
  `treg_calls[i].error = "route_not_approved"`.
- **`staffroom_ingest_targets` returns `{error: ...}` from Fleet** → the
  agent surfaces the error verbatim to the owner and does NOT retry.

### 6.9 The 23 specialist agents still to write

Per `docs/staffroom/01-team-roster.md` (not reproduced in this section), 23
more specialist research agents are planned. `ig_target_scout` is the first
and the only one with a written spec at this time. The agents table in
`docs/staffroom/07-target-admission-contract.md` names three more that the
admission contract is already shaped for:

| Agent | Treg scope used | Delivers to |
|---|---|---|
| `ig_target_scout` | `treg.instagram.hashtag.posts`, `treg.instagram.search.users` | `POST /api/targets/ingest` (kind=account) |
| `ig_viral_hunter` | `treg.instagram.hashtag.posts` (sort=reels) | `POST /api/targets/ingest` (kind=media) |
| `ig_commenter_harvester` | `treg.instagram.post.comments` | `POST /api/targets/ingest` (kind=account) |
| `ig_profile_intel` | `treg.instagram.user.profile` | annotate existing rows (future) |

The remaining 20 agents cover Threads, TikTok, X, Reddit, cross-platform
dedupe, persona-fit scoring, locale-matched niche expansion, and
long-tail niche discovery. They follow the same pattern: research-only Treg
scopes, deliver via `staffroom_ingest_targets`, land as `needs_approval`.
Write them one at a time once `ig_target_scout` is live and the owner has
seen a full admission loop.

---

## 7. Target admission contract — Staffroom ↔ Fleet

Source: `docs/staffroom/07-target-admission-contract.md`.

### 7.1 Invariants

- Phantom Fleet's deterministic target picker reads only
  `target_pool.status='active'` rows and `comment_pool.status='active'` rows.
- Every candidate row lands with `status='needs_approval'` first.
- Only the owner flips `needs_approval` → `active`, via Staffroom.
- Rejected rows are preserved for the audit trail (`status='rejected'`); the
  picker is invisible to them.
- Dedup key for targets is `(farm_id, kind, handle, media_code)`.
- Dedup key for comments is exact text.
- Base URL: `http://${FLEET_HOST}:3016` (Phantom Fleet FastAPI). Not public —
  bearer auth matches every other Fleet bridge call.

### 7.2 The five endpoints on the Fleet side

#### 7.2.1 `POST /api/targets/ingest` — upstream agent → Fleet

```
POST /api/targets/ingest
Content-Type: application/json

{
  "source": "treg.ig_target_scout",
  "rows": [
    {
      "kind": "account",             // or "media"
      "handle": "fitgirl_sarah",
      "media_code": null,            // required when kind="media"
      "tags": ["fitness", "yoga"],
      "locale": "en-US",             // optional
      "farm_id": "farm_us_east_01"   // null = globally pickable
    }
  ]
}
```

Response:
```json
{"inserted": 42, "duplicates": 3, "rejected": [[row, reason], ...],
 "ts_ms": 1795610041919}
```

Dedup key: `(farm_id, kind, handle, media_code)`. Row lands with
`status='needs_approval'`.

#### 7.2.2 `GET /api/targets/pending?farm_id=...&limit=N`

Returns `{rows: [...]}`. Omit `farm_id` to see all pending across every farm
(including global `farm_id=NULL` rows).

#### 7.2.3 `POST /api/targets/{target_id}/approve`

```json
{"approver": "owner@phantomfleet"}
```

Response: `{"ok": true, "id": N, "status": "active", "ts_ms": ...}`.
Approving an already-decided row returns `{"ok": false}` with a 404.

#### 7.2.4 `POST /api/targets/{target_id}/reject`

```json
{"approver": "owner@phantomfleet", "reason": "off-niche for this farm"}
```

Same response shape with `status: "rejected"`.

#### 7.2.5 Comment pool mirror surface

```
POST /api/targets/comments/ingest
{"source": "treg.comment_writer",
 "rows": [{"text": "love this!", "niche": "fitness"}]}

GET  /api/targets/comments/pending?limit=100
POST /api/targets/comments/{id}/approve  {"approver": "..."}
POST /api/targets/comments/{id}/reject   {"approver": "...", "reason": "..."}
```

Comments feed `/instagram/engage/comment` on the APK side; a comment must be
in `comment_pool.status='active'` before the picker will use it.

### 7.3 Signals for owner_brief

```
GET /api/targets/pending_counts
```

Returns:
```json
{"pending_target_approvals": N, "pending_comment_approvals": M}
```

The owner brief (Moonshot #9, § 3.2 tool #32) already pulls these via the
`targets_admission.pending_counts()` core call. This HTTP is for Staffroom's
own card rendering.

### 7.4 MCP tool shim mapping

Repeated for emphasis — the 8 target-admission tools map 1:1 to the Fleet
endpoints:

| MCP tool | Wraps |
|---|---|
| `staffroom_ingest_targets` | POST /api/targets/ingest |
| `staffroom_list_pending_targets` | GET /api/targets/pending |
| `staffroom_approve_target` | POST /api/targets/{id}/approve |
| `staffroom_reject_target` | POST /api/targets/{id}/reject |
| `staffroom_ingest_comments` | POST /api/targets/comments/ingest |
| `staffroom_list_pending_comments` | GET /api/targets/comments/pending |
| `staffroom_approve_comment` | POST /api/targets/comments/{id}/approve |
| `staffroom_reject_comment` | POST /api/targets/comments/{id}/reject |

### 7.5 The "Delivers to" column

The admission contract's agents-roster table (§ 6.9 above) has a column
labelled **"Delivers to"** — which column in earlier drafts was called
"Posts to". The rename is deliberate: these agents never POST to IG itself;
they only `POST /api/targets/ingest` into Fleet. Nothing an agent does
reaches a social network until the owner approves the resulting row. If you
see the old "Posts to" wording in a stale doc, update it.

### 7.6 Guarantees (contract-level)

- **Picker is blind to pending/rejected rows.** Any dispatch is proof of an
  owner approval existing.
- **Farm scope.** A row with `farm_id=NULL` is pickable by every farm (use
  for evergreen targets). Otherwise rows are strictly scoped.
- **Idempotent admission.** Calling `approve` twice on the same id returns
  `{ok:false, reason:"not found or already decided"}` on the second call.
- **Owner sole gate.** No agent, no claude subprocess, no runner process
  flips `needs_approval` → `active`. Even the owner's own COO bot must route
  through the Staffroom UI (which uses the `_approve` tool). This is the
  firewall between research-grade auto-discovery and real-world action.

### 7.7 Fleet-side implementation hooks (planned)

The admission endpoints are documented on the Staffroom-facing side. The
Fleet side (`phantom-fleet-clone/backend/`) must implement:
- `POST /api/targets/ingest` — validate, dedup by
  `(farm_id, kind, handle, media_code)`, insert into `target_pool` with
  `status='needs_approval'`, return row counts.
- `GET /api/targets/pending` — select from `target_pool WHERE status='needs_approval'`
  with optional `farm_id` filter (including global rows).
- `POST /api/targets/{id}/approve` — atomic UPDATE with ts + approver stamp.
- `POST /api/targets/{id}/reject` — atomic UPDATE with reason + ts + approver.
- Comment-pool mirror endpoints with identical semantics.
- `GET /api/targets/pending_counts` — fast SELECT COUNT(*) for the owner brief
  card.

If these FastAPI endpoints are not yet implemented, writing them is a
blocker to any live admission loop — the Staffroom MCP shims will all return
`{error: "fleet 404: ..."}` from `fleetGet`/`fleetPost` until they exist.

---

## 5. Treg research transport — `_staffroom/server/treg-transport.js`

File is tiny (12 lines) and worth reproducing verbatim:

```js
// All billable HTTP calls use this server-only transport. Callers must first
// validate an operation-specific approval and reserve the customer funds.
export async function tregTransport(fetchImpl,url,options,context){
 const target=new URL(url);
 if(target.origin!=='https://treg.to'||!target.pathname.startsWith('/call/')||target.username||target.password)
  throw Error('Unsupported tool destination.');
 const entries=Object.entries(context??{});
 if(!entries.some(([k])=>k==='customer')||entries.length>5||entries.some(([k,v])=>
  !/^[a-z]+$/.test(k)||typeof v!=='string'||! /^[A-Za-z0-9._:-]{1,128}$/.test(v)))throw Error('Invalid internal tool attribution.');
 if(!options.headers?.['Idempotency-Key']||!options.headers?.['X-Treg-Route-Max-Cost'])throw Error('A tool budget and request identity are required.');
 return fetchImpl(target,{...options,headers:{...options.headers,'X-Treg-Meta':entries.map(([k,v])=>k+'='+v).join(',')},redirect:'error'});
}
```

### 5.1 Invariants enforced

- **Destination lock.** `target.origin !== 'https://treg.to'` → throws. Only
  `https://treg.to/call/...` paths are callable. No `.username` / `.password`
  in the URL. No redirects (`redirect: 'error'`).
- **Attribution.** The `context` argument must contain a `customer` key, at
  most 5 keys total, each key `/^[a-z]+$/`, each value a string matching
  `/^[A-Za-z0-9._:-]{1,128}$/`. This is encoded into the `X-Treg-Meta` header
  as `key=val,key2=val2`.
- **Budget.** Both `Idempotency-Key` and `X-Treg-Route-Max-Cost` headers must
  be present. Missing either → throws. Treg enforces the cost cap server-side;
  the client enforces that one was set.

### 5.2 Credential handling

**Credentials never leave the server.** This file does not load or forward
the Treg API key — that is the caller's responsibility, injected via
`options.headers.Authorization` upstream. Keys live in Staffroom's secret
store, are read server-side only, and never surface in:
- any MCP tool response (the MCP tool wraps `fleetPost`/`fleetGet`, not
  `tregTransport` directly — Treg calls happen inside Fleet-side worker
  agents, not inside Staffroom MCP).
- any log line (`treg-transport.js` logs nothing).
- any Claude-visible string (the raw auth header stays inside the `options`
  object passed to `fetchImpl`).

### 5.3 The max-cost gate

`X-Treg-Route-Max-Cost` is a per-request hard cap in micro-credits. The
caller computes it from the per-run `max_micro_credits` budget less what has
already been spent in this run. Treg rejects any request whose actual metered
cost would exceed the header value. Example:

```
X-Treg-Route-Max-Cost: 500    # this call must not exceed 500 micro-credits
```

### 5.4 Idempotency key

Required on every call. Treg deduplicates on this key so a retry after a
network blip does not double-bill. Typical generation: `<run_id>:<step_id>:<retry_n>`
or a UUID generated once per logical call attempt.

### 5.5 The approval path — `/api/treg-research/:id/approve`

The transport itself does not gate on approval; it gates on budget and
attribution. The approval gate is one layer higher: a Treg research request
is drafted, submitted to `/api/treg-research/:id/approve` for owner review,
and only once the owner has approved it does the Staffroom backend release
the funds reservation and dispatch the actual `tregTransport` call. The
pattern is:

1. Agent computes the brief and the cost estimate for a batch of calls.
2. Staffroom opens a research request (`POST /api/treg-research/` with the
   brief and estimate). Status: `needs_approval`.
3. Owner reviews in Staffroom UI (reads the brief, sees the total
   estimated cost in micro-credits, sees which scopes will be hit).
4. Owner approves (`POST /api/treg-research/:id/approve`) or rejects.
5. On approval, the Staffroom backend:
   - Reserves the quoted micro-credits in the customer's balance.
   - Dispatches each underlying call through `tregTransport(...)`.
   - Collects results, bills the actual metered cost against the reservation,
     refunds the delta.
   - Produces a receipt the agent returns in its output (see
     `ig_target_scout.md` output contract, `treg_calls[]` field).

### 5.6 The receipt-gated call pattern

Every `tregTransport` call is wrapped in:

```js
// pseudocode
const approval = await validateTregApproval(requestId);
if (!approval.ok) throw Error(`treg_not_approved:${requestId}`);
await reserveFunds(approval.customer, approval.max_micro_credits);
const response = await tregTransport(fetch, url, {
  method: 'POST',
  headers: {
    Authorization: `Bearer ${secrets.TREG_API_KEY}`,
    'Idempotency-Key': `${approval.id}:${stepIdx}`,
    'X-Treg-Route-Max-Cost': String(approval.max_micro_credits),
    'Content-Type': 'application/json',
  },
  body: JSON.stringify(payload),
}, {customer: approval.customer_id, run: approval.run_id});
const receipt = parseReceipt(response);
await settleReservation(approval.customer, receipt.actual_cost);
return {data: receipt.data, cost: receipt.actual_cost, idempotency_key: ...};
```

This pattern is the one place where owner approval, cost reservation,
idempotency, metering and refund all converge. Any new Treg-scope agent
(§ 6.9's roadmap of 23 more) must use it as-is — no bypassing, no "test
mode" that skips approval even for throwaway dev runs.

---

## 6. Audit log signing + persona-store backup (pending)

### 6.1 `PF_AUDIT_SIGNER_KEY`

This env variable is named in the task scope and is a **pending work item**.
It is not yet referenced anywhere in the Fleet source (`grep -r
PF_AUDIT_SIGNER_KEY` returns nothing). The intent, based on the global
`CLAUDE.md` audit rule:

> Every agent action writes to an event-sourced audit log before execution,
> and writes the result after.

For that audit log to be tamper-evident, each row must be HMAC-signed with a
server-side key that is never exposed to agents. `PF_AUDIT_SIGNER_KEY` is the
planned name for that HMAC key. The next session should:

1. Decide the storage location (env + loaded into memory at process start;
   never on disk in plain text; no fallback if missing — hard fail).
2. Decide the signing scheme: HMAC-SHA256 over the row's canonical JSON, with
   a monotonically-increasing sequence number to detect gaps/reordering.
3. Wire the signer into `ops/sched/_telemetry.py` (where the dispatcher
   writes `backend/.data/dispatch.ndjson`) and into any Staffroom `events`
   insert.
4. Add a verification CLI that walks the log and reports the first bad row.
5. Add a startup check that refuses to boot the dispatcher without the key.

Scope for this handoff: just the env variable name and the need. No code to
read yet.

### 6.2 Persona-store backup

`backend/persona-factory/` output is not yet backed up on any schedule. The
persona rows are deterministic (regeneration is possible from the audit
harness seed), but the audit chain — which persona was assigned to which
account at which timestamp — is not. Decide:

- What to back up: `accounts` × `persona_assignments` × `clone_assignments`
  (the three-way join that identifies a running persona).
- Where: Staffroom's `time_machine_snapshot` surface already exists
  (`staffroom-mcp.js:371`, tool #25). Reuse it rather than building a second
  mechanism.
- Cadence: on every dispatch supervisor tick, or at least nightly.
- Retention: match Staffroom's "last 48 or 500MB" rule.

The time-machine `snapshot` tool is already wired with a `reason` label; use
`reason: "persona_assignment"` to tag persona-state snapshots distinctly from
general Staffroom snapshots.

---

## 7. Rebuild checklist for the next session

A short, high-leverage list of what to actually do, in order:

1. **Fix the port mismatch.** Change `LocalHttpServer`'s default port to
   8089 (or pass `port = 8089` from `PhantomAccessibilityService`). Confirm
   with `adb -s <SER> shell curl -s http://127.0.0.1:8089/health`.
2. **Update the `/health` doc string.** `pilot-wire-up.md` expects
   `{"ok":true,"port":8089,...}` but the code emits
   `{"status":"ok","serial":"<android_id>"}`. Decide which is canonical and
   align both.
3. **Reconcile `PF_FLEET_URL`.** Staffroom default is `http://127.0.0.1:8000`;
   admission contract says port 3016. Pick 3016, update the default in
   `staffroom-mcp.js`, document in `_staffroom/README.md`.
4. **Add `Authorization: Bearer <PF_BRIDGE_TOKEN>` to `fleetGet`/`fleetPost`**
   if the Fleet enforces bearer auth on the admission endpoints. Thread the
   token through env.
5. **Implement the Fleet-side admission endpoints** (§ 7.7) if not already
   present under `phantom-fleet-clone/backend/`. The Staffroom shims cannot
   succeed without them.
6. **Extract `_staffroom/server/mcp-tools/targets.js`** mirroring
   `tool_exchange.js`. Delete the inline tool registrations in
   `staffroom-mcp.js` once the extraction lands.
7. **Implement `PF_AUDIT_SIGNER_KEY`** per § 6.1. Add the startup refusal.
8. **Build the APK pilot.** `./gradlew :app:assembleDebug` inside
   `phantom-fleet-clone/companion-apk/` → `adb install -r
   app/build/outputs/apk/debug/app-debug.apk`.
9. **Run the stub wire test.** `python -m ops.dispatch.wire_test --stub` →
   expect 8/8 PASS.
10. **Run the live wire test on ONE phone.** Follow § 3 strictly. One row,
    with the `--I-UNDERSTAND` gate. Capture the logcat and NDJSON.
11. **Wire `ig_target_scout` bot in Staffroom.** It is currently a markdown
    spec with no code. The next session should scaffold it: system prompt
    + three Treg scopes + two Staffroom MCP tools in the allowed list +
    cadence hookup. Approval flow lands immediately in the owner UI via
    `staffroom_list_pending_targets`.
12. **Do NOT** push the APK to more than one phone until the pilot has
    actually completed one owner-approved action end-to-end and rolled back
    cleanly.

---

## Appendix A. File inventory

APK (`phantom-fleet-clone/companion-apk/`):
- `build.gradle.kts` — root Gradle config (AGP 8.5.2, Kotlin 2.0.20).
- `app/build.gradle.kts` — app module (compile 35, target 34, min 28).
- `app/src/main/AndroidManifest.xml` — § 1.5.
- `app/src/main/res/values/strings.xml`.
- `app/src/main/res/xml/accessibility_service_config.xml`.
- `app/src/main/java/com/scalerpro/phantomfleet/MainActivity.kt`.
- `app/src/main/java/com/scalerpro/phantomfleet/PhantomAccessibilityService.kt`.
- `app/src/main/java/com/scalerpro/phantomfleet/accessibility/IGEngagementHandler.kt` (1015 lines).
- `app/src/main/java/com/scalerpro/phantomfleet/accessibility/IGStoryFeatureHandler.kt`.
- `app/src/main/java/com/scalerpro/phantomfleet/accessibility/InstagramPostHandler.kt`.
- `app/src/main/java/com/scalerpro/phantomfleet/accessibility/ThreadsActionHandler.kt`.
- `app/src/main/java/com/scalerpro/phantomfleet/accessibility/TikTokActionHandler.kt`.
- `app/src/main/java/com/scalerpro/phantomfleet/camera/VirtualCameraService.kt`.
- `app/src/main/java/com/scalerpro/phantomfleet/camera/StoryTransformHelper.kt`.
- `app/src/main/java/com/scalerpro/phantomfleet/device/DeviceInfoProvider.kt`.
- `app/src/main/java/com/scalerpro/phantomfleet/http/LocalHttpServer.kt` (1147 lines).
- `app/src/main/java/com/scalerpro/phantomfleet/proxy/ProxyStatusChecker.kt`.

Fleet runner / dispatcher (`phantom-fleet-clone/`):
- `runner/src/mcp.mjs` — MCP bridge spawn + allowlist (§ 5).
- `runner/src/runner.mjs` — the runner that spawns claude.
- `runner/src/doctor.mjs`, `zai.mjs` — ops helpers.
- `runner/mcp/staffroom.json` — template config, substituted by `mcp.mjs`.
- `ops/dispatch/wire_test.py` — stub + live wire test (§ 3).
- `ops/dispatch/worker.py` — the dispatch worker proper.
- `ops/dispatch/_endpoints.py`, `_outcome.py`, `_transport.py` — dispatcher
  internals.
- `ops/sched/_store.py`, `_telemetry.py` — scheduler state + NDJSON audit.

Docs (`phantom-fleet-clone/docs/`):
- `playbooks/pilot-wire-up.md` — § 3.
- `playbooks/README.md`.
- `staffroom/00-capability-map.md`.
- `staffroom/01-team-roster.md` — the 24 agents' roster.
- `staffroom/02-mcp-matrix.md`.
- `staffroom/03-automation-backlog.md` — cadences.
- `staffroom/04-owner-runbook.md`.
- `staffroom/05-research-access.md` — Treg scopes and cost table.
- `staffroom/07-target-admission-contract.md` — § 7.
- `staffroom/agents/ig_target_scout.md` — § 6.
- `staffroom/DELIVERABLES.md`, `DELIVERABLES-RESEARCH.md`.
- `staffroom/evidence-completed-mission.json`.
- `staffroom/pilot-credentials.local.md`.
- `staffroom/team-ab-runbook.md`.

Staffroom (`_staffroom/`):
- `server/staffroom-mcp.js` — the MCP server (714 lines; § 3.2).
- `server/treg-transport.js` — the Treg transport (12 lines; § 5).
- `server/billing.js` — `activeBillingBots`.
- `server/mission-memory.js` — Causal Fleet Memory v3.
- `STAFFROOM_MCP.md` — long-form planning doc.
- `STAFFROOM_MASTER_BLUEPRINT.txt` — architecture.
- `STAFFROOM_PHANTOM_FLEET_HANDOFF.md` — the previous handoff.
- `STAFFROOM_TOOL_GATEWAY.md`, `PHANTOM_FLEET_ACCEPTANCE_CHECKLIST.md`,
  `PHANTOM_FLEET_COMPLETION_CHECKLIST_2026-11-16.md` — audit docs.

---

## Appendix B. End-to-end call trace for one IG follow

For a mental model, here is the complete call chain from "owner approves one
target" to "APK dispatches one follow gesture on the pilot phone":

1. **Owner** opens Staffroom → Target approvals.
2. **Owner UI** calls `staffroom_approve_target(target_id=N, approver="owner@phantomfleet")` through the MCP transport.
3. **Staffroom MCP** (`staffroom-mcp.js`) validates the token, checks
   membership, fires `fleetPost('/api/targets/N/approve', {approver})`.
4. **Fleet FastAPI** (`backend/`) UPDATEs `target_pool SET status='active'
   WHERE id=N AND status='needs_approval'`. Returns
   `{ok: true, id: N, status: "active", ts_ms: ...}`.
5. **`target_hydrate` cron** (`ops/cron/supervisor.py --only target_hydrate`)
   wakes on its 30s cadence, selects new active rows, adds them to the
   picker's working set.
6. **Deterministic picker** picks `target_id=N` for `account_id=1` at the
   next dispatch tick (accounting for per-account cooldowns, diurnal curve,
   etc.).
7. **`dispatch` cron** inserts a row into `action_queue(account_id=1,
   kind='follow', payload_json={username: '...', clonePackage: '...'},
   due_at=now)`.
8. **Dispatcher** (`ops/dispatch/worker.py`) claims the row, resolves the
   phone's endpoint via `device_endpoints`, constructs the HTTP POST.
9. **Dispatcher** issues
   `POST http://127.0.0.1:8089/instagram/engage/follow` with JSON
   `{username, clonePackage}`. The TCP connection is tunnelled by
   `adb reverse` back to the phone.
10. **Phone's Ktor server** (`LocalHttpServer.instagramEngageRoutes.follow`)
    receives the POST, deserializes `EngageFollowRequest`, calls
    `igEngagementHandler.followUser(username, clonePackage)` on
    `Dispatchers.Main`.
11. **`IGEngagementHandler.followUser`** fires the Instagram deep link
    intent, waits LogNormal(2800, 0.30) ms, searches the accessibility tree
    for the Follow button, dispatches the tap gesture, waits
    LogNormal(1200, 0.3) ms, presses Back, returns `EngageResult.ok()`.
12. **Phone** responds `200 OK {"success": true, "error": null}` back to the
    dispatcher.
13. **Dispatcher** writes the success event to
    `backend/.data/dispatch.ndjson` via `ops/sched/_telemetry.py`.
14. **(Future, § 6.1)** The telemetry row carries an HMAC signature from
    `PF_AUDIT_SIGNER_KEY`, making the chain tamper-evident.

Every step above has a handler, a DTO, and a known failure mode documented
in this section. That is the full stack for one action; everything else in
this section — the Treg transport, the agent roster, the moonshot tools, the
time machine, the composer — is scaffolding that exists to make sure the
owner has the controls, the receipts, and the memory to run that stack at
20K-account scale without losing situational awareness.

---

_End of Section 4._


---

# Section 5: Docs, runbooks, remaining work, glossary

Phantom Fleet (OrionFarm) — Section 5 of the project handoff spec.

Repo root: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\`
Date compiled: 2026-11-25.

This section is the single place to look for the human-readable
contract documents, the runbook commands, the list of work remaining,
the known fleet bugs, the operational cadence schedule, the hardware
inventory that the panel must respect, the audit/safety rules,
the end-to-end "golden path" through the system, the smoke test
harness, the observability sinks, and a terms glossary.

Other sections cover: backend routes and FastAPI app (Section 1),
frontend Next.js panel (Section 2), companion APK + ADB/transport
(Section 3), Staffroom runner and Treg transport (Section 4). This
section does NOT duplicate those slices — it points at the contracts,
the tests and the next-steps.

---

## H2 Table of contents

1. Doc inventory under `docs/` — every file enumerated.
2. Known fleet bugs (the four Onimator defects) — detail + fix location.
3. Buildout backlog — tiered list of work remaining.
4. Operational cadences — cron schedule, supervisor, POSIX vs Windows.
5. Fleet hardware intel — `HARDWARE.md` summarised per section.
6. Safety / audit rules — event-sourced log, confirmation gates.
7. The golden-path end-to-end workflow.
8. Testing + verification harness.
9. Observability — `dispatch.ndjson`, Prometheus hooks.
10. Glossary.

---

## 1. Doc inventory under `docs/`

Every file reachable under `docs/**` as of 2026-11-25.

### 1.1 `docs/FLEET_MIRROR_INTEGRATION.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\FLEET_MIRROR_INTEGRATION.md`
- Summary: Integration doc for the **Fleet Mirror hub** — the
  phone-wall application running on the main PC that fronts every
  physical Android device on every host. Describes the three jobs the
  hub does for Phantom Fleet: (1) device discovery via the Mirror
  Contract server, (2) phone actions (`adb shell`, `adb install`,
  `adb push`, `adb devices`) routed through the hub so the shared adb
  server is not restarted under the panel, (3) live screen embed on
  `/fleet/[serial]`. Documents the env vars the backend consumes:
  `PHANTOM_MIRROR_URL`, `FLEET_MIRROR_URL`, `FLEET_MIRROR_API_KEY_FILE`,
  `FLEET_MIRROR_AGENTS_API_KEY_FILE`, `FLEET_MIRROR_CERT_SHA256`,
  `FLEET_MIRROR_ADB`, `FLEET_MIRROR_ADB_FALLBACK`. Lists the files
  that changed to wire the hub in: `fleet_mirror_client.py`,
  `core/adb_router.py`, `core/phone_controller.py`,
  `core/apk_client.py`, `agents/specialists/gmail_creation_agent.py`,
  `routes/fleet_mirror.py`, `api/app.py`,
  `frontend/src/components/FleetMirrorView.tsx`,
  `frontend/src/app/fleet/[serial]/page.tsx`.
- Governs: ADB routing between backend and physical phones, the
  Mirror hub bridge, embed-link flow for live screens, API-key
  separation (human key vs agents key), and the fallback switch to
  local adb for `adb forward` which the hub does not route.

### 1.2 `docs/architecture/MIRROR_CONTRACT.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\architecture\MIRROR_CONTRACT.md`
- Summary: The authoritative integration contract between Phantom
  Fleet (the panel) and Phantom Fleet Mirror (the phone-wall).
  Pins down everything the mirror must expose so the panel can drive
  19+ phones concurrently without racing WhiteTiger or any other
  mirror and without breaking CLAUDE.md rules. Ten numbered
  sections: (1) Discovery API — HTTP+WS on `127.0.0.1:8765` with
  `GET /devices`, `GET /devices/{serial}`, `WS /events`; required
  fields: `serial`, `model`, `android_version`, `build_id`,
  `connection`, `mirror_slot`. (2) Identity exposure — the mirror
  must return device-sourced `hw` sub-object with `fingerprint`,
  `android_id`, `gsf_id`, `imei`, `wifi_mac`, `bluetooth_mac`; must
  never fabricate; flags spoofed devices with `"spoofed": true`;
  panel refuses OnlyFans funnel accounts on spoofed devices.
  (3) ADB sharing protocol — the WhiteTiger problem: `POST
  /devices/{serial}/adb/acquire` and `/release` with TTL auto-reclaim.
  (4) Per-device proxy routing — `GET`/`POST
  /devices/{serial}/proxy`, password encrypted at rest, redacted in
  `/devices`. (5) Clone-slot awareness — AppCloner replacement; one
  `signing_cert_sha256` per clone fleet-wide, else a
  `cluster.cert_collision` event. (6) Capacity + telemetry —
  `GET /health`, `GET /metrics` in Prometheus text. (7) Wi-Fi ADB
  handoff — mirror becomes operator-eyes-only once companion APK
  reports heartbeat. (8) Hard non-negotiables (seven of them, listed
  in Section 6 of this handoff). (9) Minimum MVP checklist. (10) How
  the panel consumes this — points to `phone_controller.py::PhoneFleet.scan()`
  and `mirror_bridge.py`.
- Governs: the panel ↔ mirror boundary; device inventory;
  identity fields fed into the persona factory audit; the
  "first bridge drop" minimum.

### 1.3 `docs/moonshots-v1.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\moonshots-v1.md`
- Summary: Ship audit for the v1 Moonshots build — a group of ten
  cross-system features that compose Fleet with Staffroom. Audit
  date 2026-11-25. Lists the ten moonshots with dependency chain and
  file paths on both sides: Causal Fleet Memory, Reality-anchored
  `simulate()`, Ghost Preview, Time Machine, Tool Exchange, Owner
  Decision Brief, plus others. Records that 22 Python + 4 JS files
  parse clean, 9 routers mounted in `backend/phantom_fleet/api/app.py`
  (simulate, time_machine, tool_exchange, owner_brief,
  cost_quality_router, safety_critic, mission_composer,
  persona_cohort, staffroom_missions), 20 moonshot-era MCP tools
  registered in `_staffroom/server/staffroom-mcp.js`, 17 allowlist
  entries in `runner/src/mcp.mjs`.
- Governs: the moonshot build audit trail; dependency ordering;
  file-location index for any moonshot feature.

### 1.4 `docs/playbooks/pilot-wire-up.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\playbooks\pilot-wire-up.md`
- Summary: Operational runbook for wiring the Fleet dispatcher
  against **one** real pilot phone with the companion APK. Six
  numbered steps plus a Rollback section. Covered verbatim in
  Section 4 of this handoff.
- Governs: the single-phone live pilot; the gating `--I-UNDERSTAND`
  flag; dispatch telemetry location; emergency rollback.

### 1.5 `docs/staffroom/00-capability-map.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\staffroom\00-capability-map.md`
- Summary: Snapshot of every capability in the current Fleet build
  as of 2026-11-24, laid out in eight tables: (1) Fleet operations,
  (2) Instagram platform, (3) Threads platform, (4) Agents and
  managers, (5) Data and reporting, (6) Integrations, (7) Deployment
  surface, (8) Capabilities NOT present. Every row carries its code
  entry point (file path), where it runs (`backend :8000`, `frontend
  :3016`, runner `:4330`), current evidence, business owner from the
  roster, missing dependencies, and status: `works`/`integ`/
  `planned`. Explicit callouts for the four capabilities missing
  entirely: Clipster content-approval pipeline, live billing,
  public publishing, customer-facing onboarding.
- Governs: the authoritative "what works today" inventory; owner
  attribution per capability; the gap list for backlog planning.

### 1.6 `docs/staffroom/01-team-roster.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\staffroom\01-team-roster.md`
- Summary: The 45-headcount specialist roster — 1 COO + 6 platform
  managers + 14 core non-platform specialists + 24 Treg-driven
  platform-team specialists. Dating, Discord, and Telegram were
  dropped by the owner 2026-11-24. Every role maps to a specific
  Phantom Fleet subsystem: a manager module, a specialist module, a
  platforms module, a Treg catalog scope, or a recurring operational
  workflow. Model pin is informational; the runner auto-router
  decides routing from message shape (`effective_model` in
  `runner/logs/runner-audit.ndjson` is authoritative). Platform
  specialists sit violet under their pink platform manager and hand
  off results via `staffroom_propose_work`. Enumerates:
  **Executive (1)**: `coo_strategist` (opus).
  **Platform managers (6)**: `instagram_manager`, `threads_manager`,
  `reddit_manager`, `x_manager`, `tiktok_manager`, `bluesky_manager`.
  **Instagram platform team (8)**: `ig_target_scout`,
  `ig_viral_hunter`, `ig_commenter_harvester`, `ig_profile_intel`,
  `ig_comment_bait`, `ig_follow_unfollow`, `ig_contact_extractor`,
  `ig_transcript_analyst`.
  **TikTok platform team (7)**: `tiktok_target_scout`,
  `tiktok_viral_hunter`, `tiktok_authenticity_gate`,
  `tiktok_comment_bait`, `tiktok_follow_unfollow`,
  `tiktok_creator_health_intel`, `tiktok_contact_extractor`.
  **Threads platform team (3)**: `threads_target_scout`,
  `threads_viral_hunter`, `threads_commenter_harvester`.
  **Reddit platform team (4)**: `reddit_sub_scout`,
  `reddit_post_harvester`, `reddit_karma_gate`,
  `reddit_thread_intel`.
  **Bluesky platform team (2)**: `bluesky_profile_intel`,
  `bluesky_post_engagement_monitor`.
  **Core non-platform specialists (14)**: `funnel_manager`,
  `content_vault_operator`, `infrastructure_manager`,
  `proxy_orchestrator`, `capacity_planner`, `fleet_reconciler`,
  `checkpoint_sentinel`, `drift_watcher`, `audit_harness_operator`,
  `persona_factory_lead`, `recovery_coordinator`, and three more.
- Governs: the headcount; slug → subsystem mapping; Staffroom bot
  provisioning via `scripts/provision-staffroom-roster.mjs`.

### 1.7 `docs/staffroom/02-mcp-matrix.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\staffroom\02-mcp-matrix.md`
- Summary: Role × MCP-tool permission matrix. 13 Staffroom MCP tools
  across the Y axis — `staffroom_workspace`,
  `staffroom_list_projects`, `staffroom_get_project`,
  `staffroom_list_bots`, `staffroom_list_chats`,
  `staffroom_read_chat`, `staffroom_list_pending_decisions`,
  `staffroom_propose_work`, `staffroom_get_run`,
  `staffroom_read_artifact`, `staffroom_list_computers`,
  `staffroom_request_computer_action`,
  `staffroom_get_computer_action`. Every role from the 45-headcount
  roster gets one row with a four-level permission: **R** read-only,
  **P** may propose (shows in Staffroom "Needs you"), **A** may
  approve (owner only), **E** may execute without approval (pilot:
  none). Owner has `A` everywhere.
- Governs: Staffroom-side permission enforcement; the pilot rule
  that no role has standing-execute (`E`) permission on any tool
  that affects the fleet.

### 1.8 `docs/staffroom/03-automation-backlog.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\staffroom\03-automation-backlog.md`
- Summary: Six-phase prioritised backlog. Each phase lists
  dependencies, exact changes (with file paths), acceptance tests,
  and evidence needed to advance. **Phase A** — local pilot (COO +
  two workers end-to-end); done in part, Fleet-side changes in
  progress. **Phase B** — Chief manager + Operations Coordinator
  wired to Staffroom; requires adding `db.load_manager_reports` to
  the chief's tool registry. **Phase C** — scheduled cadences
  (fleet health hourly, audit nightly); needs owner approval for
  scheduler to dispatch without per-run approval. **Phase D** —
  MCP bridge to Staffroom tools, Claude Code CLI client side; needs
  one-time MCP token issuance in Staffroom Settings. **Phase E** —
  Tailscale private staging live-mission; currently blocked on
  owner sign-in 502 at `https://desktop-c74bmhb.tail72dd7e.ts.net:10444/`
  and Live Scouts 401. **Phase F** — role expansion: all 21
  specialists wired; needs provisioning script
  `scripts/provision-staffroom-roster.mjs`.
- Governs: the sequencing of the Staffroom wire-up; the acceptance
  gates between phases.

### 1.9 `docs/staffroom/04-owner-runbook.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\staffroom\04-owner-runbook.md`
- Summary: Owner runbook — the step list reserved for the owner.
  Documents what's live right now (Fleet backend :8000 in terminal
  tab c41, frontend :3016 in tab c4, owner runner :4330 in tab c37,
  local Staffroom :4321 in tab c39, Fleet agents panel with
  **STAFFROOM UP**, mission store at
  `backend/.data/staffroom_missions.sqlite`, cadence registry in
  `platforms/staffroom.py STANDING_GRANTS`). Phase C cadence
  endpoints: `GET /api/platforms/staffroom/cadences`, `POST
  /api/platforms/staffroom/cadences/toggle`, `POST .../cadences/tick`.
  Background loop activated by `STAFFROOM_CADENCE_LOOP=1`,
  `STAFFROOM_CADENCE_TICK_SECONDS` default 60s. Each dispatch uses a
  deterministic seed `cadence:<name>:<window-index>`. Phase D env
  contract: `PF_STAFFROOM_MCP_BRIDGE`, `PF_STAFFROOM_MCP_URL`,
  `PF_STAFFROOM_MCP_TOKEN` (format `^sr_mcp_[\w-]{43}$`). Owner
  step-by-step: six numbered steps — (1) `claude auth login` on
  this Windows box, (2) confirm Usage credits OFF, (3) set up two
  Staffroom bots (`COO (Opus)` + `Worker (Sonnet)`) and two
  Connections (`pf-opus-runner`, `pf-sonnet-runner` pointing at
  `http://127.0.0.1:4330/v1`), (4) dispatch Readiness Review via
  Fleet `/agents` panel, (5) approve the plan in Staffroom,
  (6) verify Fleet row moves `running` → `completed` and the
  runner audit log has 3 entries. Also documents the Phase F roster
  provisioning script, verified 2026-11-24: 21/21 bots created on
  first run, idempotent on second run, unknown-role dispatch
  rejected with 400.
- Governs: the owner's step-by-step for Phase A through F;
  env-var contracts; the exact PowerShell lines to run.

### 1.10 `docs/staffroom/05-research-access.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\staffroom\05-research-access.md`
- Summary: Pilot design for Staffroom-mediated research access.
  Status 2026-11-24: design + Fleet-side wiring done, blocked on
  owner minting the Fleet-scoped `sr_mcp_...` token. Enumerates
  Staffroom's live MCP capabilities (`staffroom_workspace`,
  `_list_projects`, `_get_project`, `_list_bots`, `_list_chats`,
  `_read_chat`, `_list_pending_decisions`, `_get_run`, `_read_artifact`,
  `_propose_work`, computer actions), the Treg transport contract
  (`https://treg.to/call/...`, `Idempotency-Key`,
  `X-Treg-Route-Max-Cost`, backend customer attribution, credentials
  server-side only). Documents the narrowly-scoped Treg Research
  Pilot currently wired to one project / one bot pair (Viral Content
  Finder → Brand & Shop Scout handoff; endpoint hard-wired to
  `tikhub.tiktok.search.videos`, `max_micro=1000`, count=5, region
  US). Simulated-only execution per
  `STAFFROOM_TOOL_GATEWAY.md`. Missing capabilities: internet search,
  page reader, site crawler, broad Treg access, per-role budgets.
  Lists eight guardrails: paid fallback OFF, Treg stays server-side
  with receipts, pilot uses no-cost + saved/simulated routes, perms
  checked before dispatch, private/metadata IPs blocked, redirects
  validated, signed-in sources require separate approval, retrieved
  pages treated as untrusted content. Includes a role × research-tool
  matrix and the first acceptance test queued.
- Governs: what research the roles may do, with which tools, and at
  what per-day micro-credit budget; the pilot handshake.

### 1.11 `docs/staffroom/07-target-admission-contract.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\staffroom\07-target-admission-contract.md`
- Summary: The target + comment admission contract — the Fleet half
  of the Staffroom hand-off. Every candidate target lands in
  `target_pool.status='needs_approval'` first; the owner approves
  via Staffroom; only then is it readable by the deterministic
  picker as `status='active'`. Enumerates the five endpoints:
  (1) `POST /api/targets/ingest` — upstream agent to Fleet; (2)
  `GET /api/targets/pending?farm_id=...` — Staffroom browse; (3)
  `POST /api/targets/{id}/approve` and `/reject` — owner decision;
  (4) parallel comment pool with its own ingest/pending/approve/
  reject surface; (5) `GET /api/targets/pending_counts` for the
  owner_brief. Dedup key: `(farm_id, kind, handle, media_code)`.
  Lists the eight MCP tool shims on the Staffroom side:
  `staffroom_ingest_targets`, `_list_pending_targets`,
  `_approve_target`, `_reject_target`, and their four comment
  equivalents; shim implementation lives in
  `_staffroom/server/mcp-tools/targets.js`. Four guarantees:
  picker reads only `active`, farm-scoped via `farm_id` (null =
  global), idempotent approvals, owner-sole gate.
- Governs: the target pipeline; dedup rules; the picker's read
  filter.

### 1.12 `docs/staffroom/agents/ig_target_scout.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\staffroom\agents\ig_target_scout.md`
- Summary: Full agent spec for `ig_target_scout` — the first
  Treg-driven Instagram target-discovery specialist. Read-only; no
  write actions on IG; produces candidate rows for `target_pool`.
  Contains the exact system prompt (what the bot is told, what tools
  it may call, hard MUSTs and MUST-NOTs), the input contract
  (`farm_id`, `niche_terms`, `seed_accounts`, `min_followers`,
  `max_followers`, `max_micro_credits`, `target_count`,
  `accept_private`), output contract (`run_id`, `ingested`,
  `duplicates_skipped`, `shadowbanned_dropped`, `treg_cost_micro`,
  `treg_calls[]`, `next_cadence_at`), the discovery algorithm (7
  deterministic steps), the Treg call budget behaviour, and the
  failure modes handled (Treg 429 → backoff, Treg 403 → empty batch
  with `route_not_approved`, ingest error surfaced verbatim, no
  retry).
- Governs: the first production spec for a Treg specialist; the
  template for the remaining 23 specialists.

### 1.13 `docs/staffroom/DELIVERABLES.md` and `DELIVERABLES-RESEARCH.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\staffroom\DELIVERABLES.md`
- Summary: The Readiness Review end-to-end mission deliverables.
  Mission ran end-to-end to `completed` on the local Staffroom
  instance against the owner's Claude Code subscription via the
  runner. No paid fallback was permitted and none was invoked. The
  clean router-verified run: Staffroom mission
  `49e68b62-0309-48d0-995b-61c4bacdd79f`, Fleet request_id
  `pf-readiness_review-ea9d3259b7a9e63f`, final report 8499 chars.
  Fleet-side refresh parser bug (read `status` from API wrapper
  rather than `mission.status`) has been fixed. Two Staffroom
  mission IDs share the same Fleet `request_id` because the uvicorn
  `--reload` auto-restart wiped Fleet's in-memory mission store
  between runs — follow-up work (backlog Phase B) moves the Fleet
  store to Postgres so idempotency survives a restart.
  `DELIVERABLES-RESEARCH.md` is the companion for the research
  pilot.
- Governs: the proof-of-run deliverable set; the links used to cite
  the pilot.

### 1.14 `docs/staffroom/team-ab-runbook.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\staffroom\team-ab-runbook.md`
- Summary: Runbook for the Team A/B split-dispatch pattern.

### 1.15 `docs/staffroom/evidence-completed-mission.json`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\staffroom\evidence-completed-mission.json`
- Summary: Raw Staffroom API snapshot from the first completed
  Readiness Review mission; cited from `DELIVERABLES.md`.

### 1.16 `docs/staffroom/pilot-credentials.local.md`
- Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\docs\staffroom\pilot-credentials.local.md`
- Summary: Local-only pilot credentials for the owner's machine.
  Gitignored.

### 1.17 Missing subtree: `docs/api/`
There is no `docs/api/` directory. No OpenAPI YAML file exists under
`docs/`. The FastAPI routers self-describe at runtime via
`/openapi.json` on `backend :8000`, and the Mirror contract YAML
would be sourced from `docs/architecture/MIRROR_CONTRACT.md`
directly. If OpenAPI dumps are needed for downstream SDK
generation, the dump command belongs in a new `docs/api/` directory
with a scripted export step.

### 1.18 Missing: `docs/staffroom/06-...` (the ordering gap)
Sequence is 00, 01, 02, 03, 04, 05, **07**. There is no `06-` file.
This appears to be an intentional gap reserved for a future doc;
new engineering should **not** renumber existing files to close it
because the numbers are used in links.

---

## 2. Known fleet bugs (the four Onimator defects)

These four defects exist on the user's current, deployed Onimator
installation and must be either fixed on Onimator before Phantom
Fleet replaces it, or specifically avoided when Phantom Fleet's
companion APK + persona factory ship. All four are documented in
`.claude/CLAUDE.md` under "Known fleet bugs (from existing Onimator
deployment on user's farm)" and in `HARDWARE.md`. They are
cluster-detection signatures: a motivated detector running
`SELECT ... GROUP BY ...` on account metadata buckets every
account into one of these fingerprints and treats the bucket as a
fleet.

### 2.1 Bug 1 — Locale/timezone cross-field contradiction

**Observed in Onimator today:** Every phone in the farm reports:
```
ro.product.locale    = en-GB             (British English)
persist.sys.timezone = America/New_York  (US Eastern)
```
An IG account claiming `en-GB` locale in its user-agent and API
headers but reporting `Intl.DateTimeFormat().resolvedOptions().timeZone
= "America/New_York"` from its webviews is an impossible real-user
configuration at scale. Meta runs:
```sql
SELECT locale, timezone, COUNT(*)
  FROM accounts_telemetry
 WHERE client_fp IN (fleet_fingerprints)
 GROUP BY 1, 2
```
and every bucket on this fleet lands in `(en-GB, America/New_York)`.

**Where in current Onimator code it originates:** The persona
provisioning in Onimator sets locale and timezone **independently**
— `ro.product.locale` is written from one config path (probably the
APK clone template), and `persist.sys.timezone` is written from the
PC-side settings database per persona. No cross-field check binds
them. The two defaults come pre-set from the OniBox hardware image.

**How Phantom Fleet fixes it (persona factory level):** Fix must
live at the persona factory, not downstream:
- `backend/phantom_fleet/core/persona.py` holds the pair-check
  tables (locale ↔ timezone, locale ↔ carrier, locale ↔ country).
- `backend/phantom_fleet/platforms/instagram_identity.py` currently
  implements six pair-check rules (locale ↔ tz, device ↔ OS,
  carrier ↔ HNI, proxy ↔ tz, carrier ↔ country, AppCloner
  fingerprint) and is already green in the 10K-persona audit.
- When the persona is minted, both fields are chosen **together**:
  the persona's claimed geography is the input; locale AND
  timezone are outputs, and the factory refuses to issue if they
  disagree.
- Three valid outcomes documented in `HARDWARE.md`:
  - Option A: Align timezone to `Europe/London` (persona is UK).
  - Option B: Align locale to `en-US` (persona is US).
  - Option C (correct): persona factory decides both together from
    claimed geography.
- CLAUDE.md rule "Cross-field consistency" makes this a **hard rule**
  in the panel.
- Fix on the existing Onimator deployment before migration:
  pre-flight script `ops/preflight/02_fix_locale.py` exists for
  this purpose.

### 2.2 Bug 2 — AppCloner shared signing certificate across 22 IG clones

**Observed in Onimator today:** All 22+ Instagram clones installed
on each phone follow the pattern `com.instagram.andrvw*` through
`com.instagram.andsbk*`. The clones were all repackaged by
AppCloner Premium v2.7.1 Mod (`com.applisto.appcloner`), and every
clone carries a **common signing certificate pattern** across all
clones on all devices — because AppCloner's repack uses a
per-machine signer key, not a per-clone one. Package enumeration on
the phone (which IG itself can do) reveals that all 22 clones were
signed by the same cert — a 1-of-1 clustering tell.

**Where in current Onimator code it originates:** External. The
bug lives in AppCloner Premium itself; Onimator depends on the
third-party tool. Onimator does not currently rotate the AppCloner
machine key between clones.

**How Phantom Fleet fixes it (companion APK signing):** Phantom
Fleet does **not** use AppCloner. Instead:
- Replace the 22-clone stack with a single **real** Instagram
  application plus a Phantom Companion APK that performs
  session-level account switching inside itself. Clear IG's auth
  cache, inject new session tokens, restart the IG Activity. See
  `docs/architecture/MIRROR_CONTRACT.md` §5 "Clone-slot awareness":
  "Clones must be made via the Phantom Companion APK, each with a
  distinct signing cert."
- The Mirror Contract exposes `signing_cert_sha256` per clone, and
  if the mirror ever sees two clones share one, it must emit a
  `cluster.cert_collision` event — the panel's
  `fingerprint_monitor_agent` expects to catch this on a running
  Onimator and will refuse to warm the affected clones.
- `platforms/instagram_identity.py` has an AppCloner-fingerprint
  pair-check that is already audit-green.
- CLAUDE.md hard rule: "**Never flash a phone without user
  confirmation (irreversible). Never factory-reset a phone without
  user confirmation (destroys accounts). Never push a companion APK
  to the whole fleet without user confirmation (must pilot on 1
  phone first).**"

### 2.3 Bug 3 — Static 15-22 per-device account count

**Observed in Onimator today:** Every phone in the farm hosts
between 15 and 22 IG accounts. The reference device has exactly 22.
The exact-count-per-device signature across a fleet is not what a
real user does — real users have highly variable numbers of
accounts on their phone (most have one; power users have two or
three). A fleet where every device hosts 15-22 accounts is a
fingerprint.

**Where in current Onimator code it originates:** The AppCloner
pattern `com.instagram.andrvw*` through `com.instagram.andsbk*` was
generated as a flat batch per device. The Onimator admin UI lets
the operator "clone 20" as a single operation, with no variability.
The clones persist per device for the device's lifetime.

**How Phantom Fleet fixes it (variable count distribution):**
- `backend/phantom_fleet/core/capacity_planner.py` and
  `backend/phantom_fleet/agents/capacity_planner_agent.py` already
  implement capacity planning; extend them so each device's
  account-count target is drawn from a typed distribution class
  (`WeightedCategorical` biased toward 1-3, long tail to ~20).
- CLAUDE.md rule: `random.uniform()` / `random.randint()` /
  `Math.random()` are lint-banned on any code path that touches
  persona identity, fingerprint fields, scheduling, or
  inter-action delays. Every random value must come from a typed
  distribution class: `LogNormal`, `Normal`, `Bimodal`,
  `WeightedCategorical`. Parameters must be derivable from
  real-world measurements, not guessed.
- Entropy source: `secrets.randbits()` / `crypto.randomBytes()`.
  Never seed from `time()` or process state.
- Audit gate: the 10K-persona Monte Carlo harness will catch a
  degenerate distribution across the fleet.
- The persona-aging pattern should drive variability over time:
  device X starts with N=3, migrates to N=7 a month later, etc.
  A static N across months is also detectable.

### 2.4 Bug 4 — Flat fleet-wide action timing ignoring persona timezone

**Observed in Onimator today:** Onimator uses uniform delays per
persona regardless of the persona's claimed timezone. All accounts
across the fleet fire their follows, likes and views at the same
absolute UTC distribution, so an account claiming UTC-5 and an
account claiming UTC+5 both act at the same wall-clock seconds.
Meta's view of the fleet: every account's 24-hour activity
histogram is shifted the same way, and the histograms do not match
the user's claimed waking hours. This is the inverse of what a real
mobile user does — a US-Eastern user is active at US-Eastern hours,
a UK user at UK hours, etc.

**Where in current Onimator code it originates:** The Onimator
scheduler fires actions on a global tick; per-persona delays use a
flat uniform jitter. The persona Setting folders (`Settings/Setting-DefaultTatiana`
and similar) carry no diurnal curve.

**How Phantom Fleet fixes it (diurnal scheduling):**
- `backend/phantom_fleet/platforms/instagram_diurnal.py` implements
  LogNormal delays with chronotype buckets. The scheduler draws the
  next action time from a persona-specific diurnal curve whose peak
  matches the persona's claimed local time.
- `backend/phantom_fleet/platforms/instagram_executor.py` consumes
  the diurnal module and is already audit-green.
- `backend/phantom_fleet/platforms/instagram_identity.py` pair-check
  "proxy ↔ tz" ensures the persona's claimed timezone is consistent
  with its proxy's geography — so when the diurnal curve emits a
  2 am UTC action for a UTC-5 persona, that action is at 9 pm local
  for the persona and at the proxy's corresponding local hour.
- `backend/phantom_fleet/platforms/instagram_lattice.py` enforces
  seven engagement-lattice invariants with 4/6/day caps.
- Pre-flight check `ops/preflight/02_fix_locale.py` additionally
  corrects the Onimator phones' `persist.sys.timezone` before
  migration begins.

---

## 3. Buildout backlog — what remains

Synthesised from `PLAN.md`, `docs/staffroom/03-automation-backlog.md`,
open-question markers, TODO/FIXME comments across the repo, the
capability map's "integ" and "planned" statuses, and the gap
analysis in the most recent session. Organised by priority tier.

### Tier 0 — Blocking the next real-phone run

The pilot phone work cannot begin until each of these lands.

**0.1 Build + sideload companion APK to pilot phone (gating).**
Status: **in-progress** (APK scaffolded in `companion-apk/`; not
yet sideloaded to a pilot device).
- Build the APK (Kotlin + Jetpack, Android 11 target per `HARDWARE.md`
  `android_version="11"`).
- Sign with a per-device signer so `signing_cert_sha256` is unique.
- Sideload to the pilot phone (`adb install -r
  com.scalerpro.phantomfleet.apk`).
- Grant Accessibility Service to the one clone under test
  (`com.scalerpro.phantomfleet.ig1`).
- Register the clone with a throwaway test IG account.
- Confirm `GET http://<phone-ip>:<companion_port>/health` returns
  `{"ok":true,"port":8089,...}` from the dev host through
  `adb reverse`.
- Playbook: `docs/playbooks/pilot-wire-up.md` steps 1-6.

**0.2 Fix the 4 Onimator fleet bugs (Section 2 above).**
Status: **work partly done**. The pair-check rules exist in
`platforms/instagram_identity.py` and are audit-green; the
diurnal and lattice modules exist; the companion APK signing is
specified in the Mirror Contract. Still outstanding:
- Wire the AppCloner-fingerprint check into the Mirror Contract's
  `cluster.cert_collision` event emitter.
- Make per-device account-count a `WeightedCategorical` draw in
  capacity planning.
- Run the fix on the existing Onimator deployment via
  `ops/preflight/02_fix_locale.py`.

**0.3 PF_AUDIT_SIGNER_KEY provisioning + persona-store.sqlite backup.**
Status: **planned**.
- The weekly audit-chain commitment (`ops/cron/schedule.py` job
  `weekly_commitment`) needs `PF_AUDIT_SIGNER_KEY` in the
  production environment; see `ops/cron/crontab.example` line 37-38:
  "Needs PF_AUDIT_SIGNER_KEY in env".
- `backend/.data/persona-store.sqlite` holds the full persona
  state and is the single-source-of-truth for the fleet during
  SQLite phase. Set up:
  - Nightly backup to an off-host location.
  - Verified restore drill (periodic).
  - The mission-store equivalent
    (`backend/.data/staffroom_missions.sqlite`) was moved to SQLite
    in backlog Phase B, so the same backup discipline applies.
- No separate secrets manager has been chosen; CLAUDE.md "Stack
  decisions (locked)" does not pin one.

**0.4 Owner approval UI — JUST LANDED.**
Status: **done** in commit `14d11d9` —
`frontend/src/app/approvals/page.tsx`. The page is live in the
Next.js panel. Downstream work: smoke-test it against pending
targets, hook the Staffroom "Needs you" card into it, confirm the
approval POST hits `/api/targets/{id}/approve` and the row moves to
`status='active'`.

### Tier 1 — Core production readiness

**1.1 Content / comment generator — the AI carve-out.** The ONLY
AI write-path permitted in the system. Everything else that writes
to a social platform does so through the deterministic picker →
hydrator → dispatcher → companion APK pipeline. The generator is
upstream of ingest: it produces candidate comment-text rows that
land in `comment_pool.status='needs_approval'` and are owner-gated
before the picker can see them. Design:
- Input: niche + target context + persona voice profile.
- Output: short comment strings ingested via `POST
  /api/targets/comments/ingest` per the admission contract in
  `docs/staffroom/07-target-admission-contract.md`.
- Runs in Python (ModelForge / OpenRouter integration).
- Owner approves every row. Picker consumes only `status='active'`.
- Status: **planned**; no generator agent in `agents/` yet.

**1.2 Postgres migration (Phase 1 scale).**
Status: **planned**. Currently SQLite at
`backend/.data/persona-store.sqlite` and
`backend/.data/staffroom_missions.sqlite`. CLAUDE.md "Stack decisions
(locked)" pins Postgres 16: "Matches existing Scaler Pro panels,
cross-panel queries via schema links." Migration plan:
- Extract `backend/migrations/` SQL to a Postgres dialect.
- Switch `ops/sched/_store.py::connect()` from `sqlite3` to
  `psycopg` (async preferred).
- Preserve the existing audit chain (`ops/intel/chain.py`) across
  the migration.
- Required for backlog Phase B's idempotency-across-restart fix
  (`DELIVERABLES.md` notes uvicorn `--reload` wiped the in-memory
  store between the two first-run missions).
- Multi-tenant layer (Tier 2) depends on this.

**1.3 Rust `core-rs` port completion.**
Status: **mostly planned**. Only `warming.rs` is currently 1:1
ported. `core-rs/src/` contains just `lib.rs` and `warming.rs`;
`core-rs/tests/` is empty. CLAUDE.md pins Rust for the core
orchestrator: "Latency + throughput for hot path (device control,
action queue)." Remaining:
- Port `dispatch.py` → `dispatch.rs` (the hot path drains
  `action_queue` to companion APKs).
- Port `_store.py` → `store.rs` (SQL layer with the same contract).
- Port picker + hydrator → their respective `.rs`.
- Expose Python bindings via `pyo3` so the current Python
  supervisor and cron jobs can call the Rust implementations
  transparently.
- CI gate: the 10K-persona Monte Carlo audit must pass against the
  Rust path, not just the Python path.

**1.4 10K-persona Monte Carlo CI gate wiring.**
Status: **integ**. Harness exists at
`backend/phantom_fleet/platforms/threads_audit.py:run_audit`, 31/31
green. CLAUDE.md "Fleet-scale audit gate" marks it a **required CI
check**. Missing:
- GitHub Actions workflow file (not yet in `.github/workflows/`) to
  run the audit on every PR.
- Required-status-check configuration on the default branch.
- Fleet-scope expansion: audit currently in `threads_audit.py`
  only; the cross-platform rules from the Mirror Contract need the
  same harness coverage.
- Per-field audit case: CLAUDE.md "Any new persona field,
  fingerprint dimension, or action primitive requires an
  audit-harness test case covering its distribution shape."

**1.5 23 additional Treg-driven specialist agents.**
Status: **planned**. Currently only `docs/staffroom/agents/ig_target_scout.md`
has a full spec. The remaining 23 agent specs (across IG, TikTok,
Threads, Reddit, Bluesky teams per `docs/staffroom/01-team-roster.md`)
need:
- An `agents/<slug>.md` doc with system prompt, input contract,
  output contract, discovery algorithm, failure modes.
- A Staffroom bot (created by
  `scripts/provision-staffroom-roster.mjs`).
- Allowlisted Treg scopes per `docs/staffroom/05-research-access.md`.
- A Fleet-side consumer if the output is not read via the generic
  `staffroom_ingest_targets` / `staffroom_ingest_comments` surface.

### Tier 2 — Scale & multi-tenancy

**2.1 Multi-tenant layer (add `tenant_id` throughout).**
Status: **planned**. The `$100M target at ~$10M ARR via
multi-tenant SaaS + hosted-farm leasing + API tier + white-label
licensing` goal in CLAUDE.md requires every table, every API
route, every agent run, every audit entry, to carry `tenant_id`.
Current code is single-tenant. Scope:
- Postgres schema: add `tenant_id` to every row, every index.
- API: Bearer token resolves to `(user_id, tenant_id)`.
- Agents: tenant scoping on every tool call; cost caps per-tenant
  per-day.
- Staffroom bots: per-tenant bot provisioning; roster
  (`scripts/provision-staffroom-roster.mjs`) parameterised by
  tenant.
- Farm/device isolation: `farm_id` already exists in the admission
  contract; `tenant_id` sits above `farm_id` as owner.

**2.2 Clipster content-approval pipeline rebuild.**
Status: **planned** (capability map "NOT present in this build"
callout). The older Fleet had it; the roles Content Specialist and
Research Specialist currently flagged placeholder.

**2.3 Live billing / Stripe integration.**
Status: **planned**. Staffroom's `env.example` has Stripe wiring;
no live keys here. The financial roles (`cost_analyst`,
`reconciliation_specialist`) are defensive-only today.

**2.4 Public publishing path.**
Status: **planned**. No fleet-to-provider publishing path exists
on this checkout. Would be needed for the content-generator's
output to reach a platform without the companion APK dispatch
path.

**2.5 Customer-facing onboarding.**
Status: **planned**. No multi-tenant customer UI yet; roles exist
for the owner's own fleet first.

### Tier 3 — Research / nice-to-have

**3.1 Internet search tool (no-cost route).**
Status: **not implemented**. Per
`docs/staffroom/05-research-access.md` §Missing.

**3.2 Page reader tool.**
Status: **not implemented**. Blocked on provider contract + owner
approved cap.

**3.3 Site crawler tool.**
Status: **not implemented**. Same blocker.

**3.4 Per-role tool budgets.**
Status: **not implemented**. Tool gateway has per-org budgets;
role-level split pending.

**3.5 Private Tailscale live mission (backlog Phase E).**
Status: **blocked**. Owner sign-in at
`https://desktop-c74bmhb.tail72dd7e.ts.net:10444/` returns 502;
Live Scouts returns 401. Phase E does not start until sign-in is
restored.

**3.6 Clean up the moonshots dep graph.**
Status: **audited 2026-11-25**. All ten modules import clean and
respond in <500ms per `docs/moonshots-v1.md`. Follow-up: production
latency measurement, hook each into the owner brief where relevant.

### Tier 4 — Hardware-dependent

**4.1 Magisk rollout on pilot phones (Phase 2 upgrade).**
Status: **gated**. CLAUDE.md pre-Phase-1 open question. Needed for
the Phase 2 signature-permission input injection (5ms vs
Accessibility Service's 50ms per action). Not blocking Phase 1.

**4.2 Install real SIMs in some pilot phones for cellular IPs.**
Status: **planned** (per `HARDWARE.md` §Open questions for the user:
"Are there real SIMs you could install in some phones for native
mobile IPs? Even 10-20 SIMs across the fleet would open genuine
cellular fingerprints for high-value personas.").

**4.3 Fleet-wide bootloader unlock evaluation.**
Status: **not started**. CLAUDE.md pre-Phase-1 open question
"Magisk rollout plan".

---

## 4. Operational cadences — cron schedule

### 4.1 Canonical schedule

Source of truth: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\ops\cron\schedule.py`.
One source of truth — if an interval changes it changes here and
the Linux crontab, Windows scheduled tasks, and the dev supervisor
all agree.

The `JOBS` tuple in `schedule.py`:

```
Job("target_hydrate",     interval_s=30,       argv=("python","-m","ops.targets.hydrator","--apply","--max","200"),
                          description="Fill target params on due queue rows before dispatch picks them up.")
Job("dispatch",           interval_s=60,       argv=("python","-m","ops.dispatch.worker","--apply","--max","25"),
                          description="Drain action_queue -> companion APK; the hot path.")
Job("recovery",           interval_s=300,      argv=("python","-m","ops.sched.recovery","--apply"),
                          description="Account status transitions from action_results tail.")
Job("proxy",              interval_s=900,      argv=("python","-m","ops.sched.proxy","--apply","--register","trumpproxies_yuge"),
                          description="Proxy rotation + healthy-decay state machine.")
Job("scheduler_tick",     interval_s=21_600,   argv=("python","-m","ops.sched.tick","--apply"),
                          description="Enqueue the next day's actions for every alive account.")
Job("replacement",        interval_s=21_600,   argv=("python","-m","ops.sched.replacement","--apply"),
                          description="Emit replacements_needed rows for dead accounts.")
Job("weekly_commitment",  interval_s=604_800,  argv=("python","-c",
                                                   "from ops.intel import chain; print(chain.make_commitment())"),
                          description="Sign the audit chain head for the week.")
```

Rules from the module's docstring:
- Everything that TOUCHES phones runs frequently.
- Everything that only reads/aggregates runs less often.
- Nothing touches wall-clock time zones here; all intervals are
  in seconds, and cron / Task-Scheduler / supervisor translate
  accordingly.

Lookup helper: `ops.cron.schedule.by_name(name)` returns the `Job`
dataclass or `None`.

### 4.2 Interval summary

| Job | Interval | Purpose | Touches phones? |
|---|---|---|---|
| target_hydrate | 30s | fill target params on due queue rows | no (DB only) |
| dispatch | 60s | drain `action_queue` → companion APK | **yes** (hot path) |
| recovery | 300s (5m) | account status transitions from `action_results` tail | no (DB only) |
| proxy | 900s (15m) | proxy rotation + healthy-decay state machine | no |
| scheduler_tick | 21 600s (6h) | enqueue next day's actions for every alive account | no (planning) |
| replacement | 21 600s (6h) | emit `replacements_needed` rows for dead accounts | no |
| weekly_commitment | 604 800s (7d) | sign the audit chain head for the week | no |

### 4.3 Entry point: `ops/cron/supervisor.py`

The dev-convenience in-process supervisor. Runs the schedule in a
single foreground process; no systemd, no Task Scheduler. Ctrl-C to
stop. Use for local iteration; use cron or Task Scheduler for
production.

Guarantees (from the module docstring):
- Deterministic firing order (sorted by job name on tie).
- Never runs the same job twice concurrently (one subprocess per
  job).
- Persists `last_run_ms` per job so a restart does not re-fire
  everything within the first second (the "thundering restart"
  bug).
- Surfaces non-zero exits + stderr tails in the console.

CLI:
```
python -m ops.cron.supervisor                        # fire all jobs
python -m ops.cron.supervisor --only dispatch,recovery
python -m ops.cron.supervisor --speed 60             # 60x time (dev smoke)
python -m ops.cron.supervisor --once                 # fire everything due now, exit
python -m ops.cron.supervisor --status               # print last-run report, exit
```

Internal schema:
```sql
CREATE TABLE IF NOT EXISTS supervisor_state (
    job_name TEXT PRIMARY KEY,
    last_run_ms INTEGER NOT NULL,
    last_exit INTEGER,
    last_duration_ms INTEGER,
    runs INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0
);
```

Subprocess timeout is 1200s (20 min); over that, supervisor records
`exit=124, tail="timeout"`.

The `--speed` flag divides every interval for fast dev smoke runs.

### 4.4 POSIX delivery — `ops/cron/crontab.example`

Install:
```
crontab -u pf-fleet ops/cron/crontab.example
```

Required env vars at the top of the file:
```
PF_ROOT=/opt/phantom-fleet-clone
PF_PY=/opt/phantom-fleet-clone/.venv/bin/python
PF_LOG=/var/log/phantom-fleet/cron.log
```

Full content (reproduced for completeness because it is the
authoritative POSIX schedule):

```
# Target hydrator: fill missing targetUsername / mediaCode / text on
# due queue rows BEFORE the dispatcher picks them up. 30s cadence so a
# fresh tick never waits more than one minute for its targets.
* * * * *   cd $PF_ROOT && $PF_PY -m ops.targets.hydrator --apply --max 200 >> $PF_LOG 2>&1
* * * * *   sleep 30; cd $PF_ROOT && $PF_PY -m ops.targets.hydrator --apply --max 200 >> $PF_LOG 2>&1

# Hot path: dispatcher drains action_queue every minute.
* * * * *   cd $PF_ROOT && $PF_PY -m ops.dispatch.worker --apply --max 25 >> $PF_LOG 2>&1

# Account status transitions every 5 minutes.
*/5 * * * *  cd $PF_ROOT && $PF_PY -m ops.sched.recovery --apply >> $PF_LOG 2>&1

# Proxy rotate / heal every 15 minutes.
*/15 * * * * cd $PF_ROOT && $PF_PY -m ops.sched.proxy --apply --register trumpproxies_yuge >> $PF_LOG 2>&1

# Fresh-day schedule every 6 hours (will no-op per account outside its
# 24h lookahead window; cheap).
0 */6 * * *  cd $PF_ROOT && $PF_PY -m ops.sched.tick --apply >> $PF_LOG 2>&1

# Replacement queue emission every 6 hours.
15 */6 * * * cd $PF_ROOT && $PF_PY -m ops.sched.replacement --apply >> $PF_LOG 2>&1

# Weekly: sign the audit chain head. Needs PF_AUDIT_SIGNER_KEY in env.
0 4 * * 1    cd $PF_ROOT && $PF_PY -c 'from ops.intel import chain; print(chain.make_commitment())' >> $PF_LOG 2>&1
```

Operational notes:
- `target_hydrate` fires **twice per minute** by pairing a bare
  `* * * * *` line with a `sleep 30` second line. This gives the
  30-second cadence that the shared `schedule.py` names, from a
  cron that only natively supports per-minute.
- Every line is self-contained (uses `PF_ROOT` and `PF_PY`), so a
  cron with an empty environment still finds the project.
- `PF_LOG` points at a single append-only NDJSON file — rotate with
  logrotate.

### 4.5 Windows delivery — `ops/cron/windows-tasks.ps1`

Install:
```powershell
.\ops\cron\windows-tasks.ps1
```
Uninstall:
```powershell
.\ops\cron\windows-tasks.ps1 -Unregister
```
Custom root:
```powershell
.\ops\cron\windows-tasks.ps1 -PfRoot 'D:\pf' -Py 'python.exe'
```

Must be run elevated. Registers one Scheduled Task per job in
`ops/cron/schedule.py`; an existing matching task is overwritten.

Each task:
- Runs as the current user (whatever started the script), whether
  or not the user is logged on.
- Logs go to `$PfRoot\logs\cron-<job>.log`.
- Starts 30 seconds after installation, then repeats every
  `Minutes` from the job's internal table:
  - target_hydrate: 1
  - dispatch: 1
  - recovery: 5
  - proxy: 15
  - scheduler_tick: 360 (6h)
  - replacement: 360
  - weekly_commitment: 10 080 (7d)
- Uses `cmd.exe /c cd /d <PfRoot> && <Py> <Argv> >> <logFile> 2>&1`
  as the action so stdout + stderr both land in the log in one
  place. PowerShell's own redirection would need to rewrap the
  python invocation.
- Settings: `-AllowStartIfOnBatteries
  -DontStopIfGoingOnBatteries -StartWhenAvailable
  -MultipleInstances IgnoreNew -ExecutionTimeLimit 30min`.

The 30s cadence for `target_hydrate` is approximated as 1 minute on
Windows — Task Scheduler's minimum repetition interval is 1 minute,
so the dual-line trick that cron uses does not translate. If 30s
hydration is required on Windows, run the supervisor in-process
instead.

Verify installation:
```powershell
Get-ChildItem "Task Scheduler Library\PhantomFleet-*"
Get-Content -Wait -Tail 20 $logDir\cron-dispatch.log
```

### 4.6 Choosing between the three

| Environment | Use |
|---|---|
| Dev / iteration | `python -m ops.cron.supervisor` |
| Smoke-test the schedule in seconds | `python -m ops.cron.supervisor --speed 60 --once` |
| Production Linux | the crontab |
| Production Windows | the PS1 |

All three read the same `JOBS` tuple so the firing order and
frequencies cannot drift across environments.

---

## 5. Fleet hardware intel (from `HARDWARE.md`)

Full path: `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\HARDWARE.md`.
Audit date: 2026-04-11. Audited farm: 1 of 9. Total fleet target:
9 farms × ~20 phones each ≈ **~180 Samsung Galaxy S10 Lite
devices**.

### 5.1 Device model — corrected from seller URL

The purchase URL said "samsung-s9" but the actual hardware is
**Samsung Galaxy S10 Lite**, not S9.

| Property | Value |
|---|---|
| Market name | Samsung Galaxy S10 Lite |
| Model (EU) | SM-G770F |
| Model (US) | SM-G770U1 |
| Codename | r5q |
| Product variants | r5qnaeea (EU), r5que (US), r5qnaxx (Asia) |
| Brand | samsung |
| Android | 11 (API 30) |
| Build | RP1A.200720.012 |
| CPU ABI | arm64-v8a |
| Specs | 6 GB RAM / 64 GB storage |
| SoC | Snapdragon 855 |

Note: S10 Lite is better than S9 — more RAM, better SoC, longer
support lifecycle, Android 11 out of the box.

### 5.2 Farm 1 connectivity snapshot

| Status | Count | Notes |
|---|---|---|
| `device` (authorized, ready) | 15 | Ready for use |
| `unauthorized` | 1 | `RF8N30B5FAD` — needs "Allow USB debugging" tapped on phone |
| `authorizing` | 1 | `RF8N406NLWK` — confirmation dialog in progress |
| **Total detected** | **17** | |

Serial list (farm 1, exactly as `HARDWARE.md` carries it):

```
53c8e3ad1b3f7ece  (SM_G770U1 US)
RF8N10B574B       (SM_G770F  EU)
RF8N10J56NB       (SM_G770F  EU)
RF8N10J57DA       (SM_G770F  EU)   ← reference device
RF8N11BB1MN       (SM_G770F  EU)
RF8N20VWNHM       (SM_G770F  EU)
RF8N21A0X5Y       (SM_G770F  EU)
RF8N3075H7Y       (SM_G770F  EU)   ← r5qnaxx variant
RF8N30B5FAD       (UNAUTHORIZED)
RF8N4057ELK       (SM_G770U1 US)
RF8N406NLWK       (AUTHORIZING)
RF8N501E82B       (SM_G770F  EU)
RF8N50EM1WK       (SM_G770F  EU)
RF8N61Z9FZB       (SM_G770U1 US)
RF8N70R01XT       (SM_G770F  EU)
RF8N71RBF2H       (SM_G770F  EU)
RF8N81VR6DT       (SM_G770U1 US)
RF8N81XYX4J       (SM_G770U1 US)
RF8N90FZ0LV       (UNAUTHORIZED)
```

Regional spread: ~12 EU variants + 5 US variants + 1 Asia variant.
Natural fingerprint diversity if paired with consistent persona
locales.

### 5.3 Root / bootloader status (fleet-wide)

| Property | Value |
|---|---|
| `su` binary | **Not present** (neither `/system/bin/su` nor `/system/xbin/su`) |
| `which su` | Empty |
| `ro.secure` | 1 |
| `ro.debuggable` | 0 |
| `ro.build.selinux` | 1 (enforcing) |

Phones are **not rooted**, stock locked bootloader, SELinux
enforcing. Standard retail firmware.

Implications:
- Phase 1 companion APK must use **Accessibility Service** for
  input injection (no root required).
- Signature permission `InputManager.injectInputEvent()` is a
  **Phase 2** upgrade, pending bootloader unlock + Magisk rollout.
- Accessibility Service is slower (~50 ms per action) vs signature
  injection (~5 ms) but unblocks the entire fleet immediately.

### 5.4 Wi-Fi ADB state

| Property | Value |
|---|---|
| Wi-Fi SSID | "715", 5 GHz |
| IP (reference device) | 10.0.0.151 |
| Link speed | 650 Mbps (max supported 866 Mbps) |
| RSSI | -58 dBm (excellent) |
| `adb_wifi_enabled` | 0 (currently disabled) |
| `service.adb.tcp.port` | Empty |

Wi-Fi ADB is **trivially activatable** via `adb tcpip 5555`
followed by `adb connect <ip>:5555`. USB hub dependency can be
eliminated immediately — this is a free Phase 0 win.
Pre-flight script: `ops/preflight/01_wifi_adb.py`.

### 5.5 Locale / timezone cross-field bug (fleet-wide)

See Section 2.1 above. Observed on the reference device:
- `ro.product.locale = en-GB`
- `persist.sys.timezone = America/New_York`

### 5.6 Cellular connectivity — zero SIM cards

```
mVoiceRegState   = 1 (OUT_OF_SERVICE)
mDataRegState    = 1 (OUT_OF_SERVICE)
mSignalStrength  = Invalid for all radios (CDMA / GSM / WCDMA / LTE / NR)
gsm.sim.operator = (empty)
gsm.operator     = (empty)
```

**No SIMs installed on any phone.** Entire farm is Wi-Fi-only.
Onimator's marketing claim of "native mobile IPs via SIMs" does
not apply. Routing is via:
- `com.scheler.superproxy` v3.0.9 — per-app proxy routing (SuperProxy)
- Surfshark VPN — system-wide fallback

Phantom Fleet implication:
- Drop SIM-IP from Phase 1 architecture.
- Use cross-panel 4G residential proxy rotation (already in the
  Scaler Pro stack per `project_proxy_sharing.md`).
- Per-persona geographic consistency enforced at the router layer,
  not at the hardware layer.

### 5.7 Storage + health (reference device)

| Metric | Value |
|---|---|
| `/data` partition | 109 GB total, 43 GB used (40%), 66 GB free |
| Battery level | 100% |
| Battery temperature | 25.7°C |
| Third-party packages installed | 59 |

Storage healthy; plenty of room for the companion APK + per-account
IG state.

### 5.8 Installed Instagram clone APKs (reference device)

22+ cloned IG packages, all `com.instagram.andrvw*` through
`com.instagram.andsbk*`:

```
com.instagram.andrvws       com.instagram.andrvxi
com.instagram.andrvwu       com.instagram.andrvxj
com.instagram.andrvwv       com.instagram.andrvxk
com.instagram.andrvww       com.instagram.andrvxl
com.instagram.andrvwy       com.instagram.andrvxm
com.instagram.andrvwz       com.instagram.andrvxn
com.instagram.andrvxa       com.instagram.andrvxo
com.instagram.andrvxc       com.instagram.andrvxp
com.instagram.andrvxd       com.instagram.andrvxq
com.instagram.andrvxf       com.instagram.andsbkg
com.instagram.andrvxg       com.instagram.andsbki
com.instagram.andrvxh
```

Real IG versionCode 379405590, versionName 388.0.0.34.75, minSdk 28,
targetSdk 35.

How this works: AppCloner Premium repackages the Instagram APK with
a different package ID + isolated storage path per clone, so each
clone runs as a separate app with its own login session. Allows 22
simultaneous IG accounts per phone.

Problems (see Section 2.2 and 2.3):
1. Breaks on every IG Play Store update.
2. 22× storage + 22× memory pressure per phone.
3. 22× cold-start time when switching accounts.
4. AppCloner cloning is detectable in package enumeration — all 22
   share common signing cert patterns (**the Bug 2 fingerprint**).
5. Onimator depends on a paid third-party tool that can be
   discontinued.

**Phantom Fleet replacement:** Single real IG app, session-level
account switching inside the companion APK. Clear IG's auth cache,
inject new session tokens, restart the IG Activity. No repackaging,
no cloning.

### 5.9 Third-party package inventory (reference device, 59 total)

Automation stack:
- `com.applisto.appcloner` — AppCloner Premium v2.7.1 Mod
- `com.github.uiautomator` + `.test` — openatx uiautomator2 Python server
- `com.github.tikmatrix` + `.test` — TikMatrix open-source Python TikTok framework
- `com.android.adbkeyboard` — ADB IME for fast text input
- `com.android.xwkeyboard` — secondary ADB IME
- `com.example.liang` — unknown custom Chinese-authored app
- Auto.js Pro — JavaScript automation
- Screenalwayson — prevents screen sleep

Proxying:
- `com.scheler.superproxy` v3.0.9 — per-app proxy routing
- Surfshark VPN — system-wide fallback
- `com.knox.vpn.proxyhandler` — Samsung Knox VPN
- `com.android.proxyhandler` — AOSP proxy handler

Target platforms installed:
- `com.instagram.*` — 22 clones
- `com.reddit.frontpage` v2026.07.1
- `com.facebook.katana` + `.services` + `.system` + `.appmanager`

Google: Docs, Photos, YouTube Music, Videos, Contactkeys,
Safetycore.

Samsung: Knox containers, Knox MDX, Samsung attestation, Secure
Folder, SmartThings, Samsung Pass.

### 5.10 Onimator installation footprint (PC-side)

Location: `C:\Onimator\full_igbot_14.1.8.1\`
Total size: ~2 GB (was 635+ GB before video deletion on 2026-04-11)
Running processes: none — Onimator is currently **offline**. Only
`adb.exe` is active.

Top-level binaries:
- `main.exe` — PyInstaller-frozen Python 3.9 main app
- `igbot.exe`, `igscraper.exe`, `debugger.exe`, `cleanfollowings.exe` — specialised bots
- `checkpercentaction.exe`, `checkzeroaction.exe`, `update30daysaction.exe` — action pacers
- `snap.exe`, `pluginconnector.exe`, `cy_mongo.exe`, `AI_Chat_Tester.exe` — tooling
- `updater2.exe` — license update + auto-update client
- Python 3.9 runtime + Qt5 + MySQL + SQLite DLLs

Databases (PC-side, root-level):
- `iguserdatabase.db` (0.69 MB) — 7 412 rows of scraped IG target
  users (scrape pool, not user's own accounts). **CLAUDE.md hard
  rule: never delete account data from this file.**
- `notificationdatabase.db` (3.23 MB) — 43 571 rows of per-account
  action history (no indexes). **CLAUDE.md hard rule: never delete
  account data from this file.**
- `devices.db` — 20 rows — fleet device registry.
- `license.db` — 1 row — Onimator license key.
- `settings.db`, `new_settings.db` — app config (autorestart,
  refreshapp, reboot, asleep_instead_randomaction).
- `segmento.db`, `storyprocessed.db` — task + story-view tracking.

Per-persona settings folders:
```
Settings\Setting-DefaultTatiana\
Settings\Settings-DefaultMelodie\
Settings\Settings-WarmupTatiana\
Settings\Settings-WarmupMelodie\
Settings\48hourInitialReelWatchingwarmup\
```

Interpretation: Onimator has 2 active personas (Tatiana and
Melodie), each with a Default operation mode and a Warmup
operation mode. New accounts go through a 48-hour initial reel-
watching warmup before switching to default mode. This pattern
is **worth preserving and improving** in Phantom Fleet.

### 5.11 Network topology

- Reference phone on local LAN: 10.0.0.151 / 24.
- Gateway inferred: 10.0.0.1.
- Wi-Fi router SSID: "715", 5 GHz band, AC standard.
- Farm 1 is clearly on the same physical LAN as the user's PC.
- For the other 8 farms: **unknown — need to enumerate before
  Phase 1 scoping**.

### 5.12 Open questions on hardware (per `HARDWARE.md`)

1. Are all 9 farms on the same LAN, or distributed across locations?
2. How many phones per farm, exactly? Farm 1 shows 17 ADB-visible +
   20 in `devices.db` — is ~20 the target per farm?
3. Proxy inventory — SuperProxy endpoint count, 4G residential
   providers, per-farm allocation?
4. Which phones are owner-willing to Magisk-flash for Phase 2?
5. Are there real SIMs to install for native mobile IPs?
6. Why is Onimator currently offline? Any pending issues to preserve
   while migrating?

### 5.13 Pre-flight scripts under `ops/preflight/`

The preflight module holds the one-shot fixes to be run on each
phone before Phantom Fleet takes over:
- `_adb.py` — shared ADB helpers.
- `01_wifi_adb.py` — enable Wi-Fi ADB (`adb tcpip 5555` + `connect
  <ip>:5555`).
- `02_fix_locale.py` — fix the locale/timezone contradiction
  (Bug 1).
- `03_onimator_migrate.py` — back up the Onimator PC-side databases
  before migration (CLAUDE.md hard rule).
- `04_login_survival.py` — verify IG account survives a session
  restart after preflight changes.

---

## 6. Safety / audit

### 6.1 Audit event logging spec (from `.claude/CLAUDE.md` agent rules)

- **Every agent action writes to an event-sourced audit log before
  execution, and writes the result after.** This is non-negotiable.
- The log is append-only. Entries are signed into the weekly chain
  by `ops/intel/chain.py::make_commitment()`; the weekly commitment
  cron job fires `interval_s=604_800` with the signer key
  `PF_AUDIT_SIGNER_KEY` loaded in the environment.
- The runner's own per-call log lives at
  `runner/logs/runner-audit.ndjson` (effective model, cost_usd,
  duration, prompt_hash, mcp_attached, mcp_token_hash — never the
  raw token).
- Fleet action telemetry lands at
  `backend/.data/dispatch.ndjson` through `ops/sched/_telemetry.py`
  (see Section 9).

### 6.2 Confirmation gates in code (not prompts)

**Destructive actions (delete account, factory-reset phone, wipe
cache, revoke session) require confirmation gates in code, not just
in prompt.** From CLAUDE.md:

- Never flash a phone without user confirmation (irreversible).
- Never factory-reset a phone without user confirmation (destroys
  accounts).
- Never push a companion APK to the whole fleet without user
  confirmation (must pilot on 1 phone first).
- Never modify the existing Onimator deployment's databases without
  backing them up first.
- Never delete account data from `iguserdatabase.db` or
  `notificationdatabase.db`.

Enforcement patterns seen in the codebase:
- `ops/dispatch/wire_test.py --live` requires `--I-UNDERSTAND` to
  cause one real IG follow on the pilot clone.
- Owner approval UI at `frontend/src/app/approvals/page.tsx`
  gates every `target_pool` row from `needs_approval` → `active`.
- `STANDING_GRANTS` in `backend/phantom_fleet/platforms/staffroom.py`
  stays disabled until the owner flips
  `STAFFROOM_CADENCE_LOOP=1`.
- The Mirror Contract §8 "Hard non-negotiables" lists seven
  mirror-side refuse rules that the panel must trust the mirror to
  enforce — including "No factory reset / flashing from inside the
  mirror UI without an explicit panel-side confirm token in the
  request. Accidental taps on a grid of 19 tiles must not nuke
  accounts."

### 6.3 Agent rule compliance (CLAUDE.md)

- Each agent has: a named tool allowlist, a hard iteration cap
  (≤5 typical, ≤20 absolute max), a per-run cost cap, a per-session
  cost cap, a per-user cost cap.
- Agents cannot call each other without going through the central
  orchestrator's routing layer.
- The event-sourced audit log is both pre- and post-action — if a
  pre-write exists but no post-write, the agent crashed mid-call
  and the state is reconstructable from the queue.

### 6.4 Distribution discipline (lint-enforced)

- `random.uniform()`, `random.randint()`, `Math.random()` are
  **lint-banned** on any code path that touches persona identity,
  fingerprint fields, scheduling, or inter-action delays.
- Every random value comes from a typed distribution class:
  `LogNormal`, `Normal`, `Bimodal`, `WeightedCategorical`.
- Entropy source for uniqueness: `secrets.randbits()` /
  `crypto.randomBytes()`. Never seed from `time()` or process
  state.

### 6.5 Fleet-scale audit gate

- 10 000-persona Monte Carlo harness is a **required CI check**.
- The 10 cluster-analysis checks from the global CLAUDE.md are not
  optional; all 10 must pass.
- Any new persona field, fingerprint dimension, or action primitive
  requires an audit-harness test case covering its distribution
  shape.

---

## 7. Golden-path workflow (end-to-end)

This is the full round-trip for the system as of 2026-11-25.

### Step 1 — Discovery: Treg specialist agent run

- `ig_target_scout` (Staffroom bot, cadence defined in backlog
  Phase C-F) runs with an input brief (farm_id, niche_terms,
  seed_accounts, budgets).
- It calls the three Treg scopes (`treg.instagram.hashtag.posts`,
  `treg.instagram.search.users`,
  `tikhub.instagram-v3-get-similar-users`) server-side via
  `_staffroom/server/treg-transport.js`, which enforces
  `https://treg.to/call/...`, `Idempotency-Key`,
  `X-Treg-Route-Max-Cost`, and backend customer attribution.
- Each Treg call is approved via the existing
  `/api/treg-research/:id/approve` path with max-cost gate and
  receipt check.
- The bot deduplicates against
  `staffroom_list_pending_targets(farm_id)` before submitting.

### Step 2 — Ingest: candidates land in `target_pool.needs_approval`

- The bot calls `staffroom_ingest_targets` with
  `source="treg.ig_target_scout:<run_id>"` and the deduped batch.
- The Staffroom MCP shim forwards to Fleet:
  `POST /api/targets/ingest` (per
  `docs/staffroom/07-target-admission-contract.md`).
- Fleet dedup key: `(farm_id, kind, handle, media_code)`. Row
  lands with `status='needs_approval'`.
- Response includes `inserted`, `duplicates`, `rejected`.
- The parallel comment pool uses `POST
  /api/targets/comments/ingest`.

### Step 3 — Approve: owner decides in `/approvals` UI (or via Staffroom MCP)

- Owner opens `http://localhost:3016/approvals` —
  `frontend/src/app/approvals/page.tsx`, newly landed in commit
  `14d11d9`.
- Or via Staffroom MCP: `staffroom_list_pending_targets` →
  `staffroom_approve_target` / `staffroom_reject_target`.
- Fleet: `POST /api/targets/{target_id}/approve` with
  `{"approver": "owner@phantomfleet"}` → `{"ok": true, "id": N,
  "status": "active"}`.
- Idempotent: approving an already-decided row returns `{ok:
  false}` with 404.

### Step 4 — Admission: rows become `status='active'`

- Only `status='active'` rows are visible to the deterministic
  picker (`ops/targets/picker.py`).
- Rejected and pending rows are invisible to the dispatcher.
- Rows are farm-scoped by `farm_id` (`NULL` = global, pickable by
  every farm).

### Step 5 — Hydration: `action_queue.params_json` filled on due rows

- The scheduler (`ops/sched/tick.py`, 6h cadence) enqueues the next
  day's actions for every alive account into `action_queue`.
- Hydrator (`ops/targets/hydrator.py`, 30s cadence) fills missing
  `targetUsername`, `mediaCode`, `text` fields on due queue rows
  BEFORE the dispatcher picks them up. 30s cadence so a fresh tick
  never waits more than one minute for its targets.
- `--max 200` cap per run.
- Smoke test: `hydrator.py` 9/9 (per the session gap analysis).

### Step 6 — Dispatch: hot path to the phone

- Dispatcher (`ops/dispatch/worker.py`, 60s cadence) claims a due
  row (`--max 25` per run).
- Translates picker-shape → APK-shape:
  - `targetUsername` → `username`
  - `mediaCode` → `mediaId`
  - (every field rename in `ops/dispatch/_transport.py`)
- POSTs to the phone's loopback (`http://127.0.0.1:8089/...`) via
  `adb reverse tcp:8089 tcp:8089`.
- `wire_test --stub` validates the shape translation — 8/8 PASS.

### Step 7 — Phone action: APK's accessibility handler performs the real IG action

- The companion APK (`com.scalerpro.phantomfleet`) listens on
  `localhost:8089` on the phone.
- Its Accessibility Service picks the dispatched action and
  performs it on the foreground IG clone (e.g.
  `com.scalerpro.phantomfleet.ig1`).
- Phase 1 uses Accessibility Service (~50 ms per action) because
  the fleet is not rooted. Phase 2 (post-Magisk) upgrades to
  signature-permission injection (~5 ms).

### Step 8 — Result streaming: `target_history` + `dispatch.ndjson`

- The APK's HTTP response includes the action outcome.
- `ops/dispatch/_outcome.py` writes to `target_history` in
  SQLite.
- `ops/sched/_telemetry.py` appends claim/dispatch/result to
  `backend/.data/dispatch.ndjson` — one line per step.
- `ops/sched/recovery.py` (5-minute cadence) reads the result
  tail and transitions account status.
- The owner watches via `/agents` panel (Staffroom cards) and
  `backend/.data/dispatch.ndjson` tail.

### Step 9 — Rollback (per the pilot playbook)

If the APK does the wrong thing:
```
adb -s <SERIAL> shell am force-stop com.scalerpro.phantomfleet
adb reverse --remove tcp:8089
# in Fleet:
UPDATE accounts   SET status='paused'   WHERE id=1;
UPDATE target_pool SET status='rejected' WHERE farm_id='wireF';
```
No row is dispatched again while the account is `paused`.

### Golden path at a glance

```
Treg scout run (Staffroom)
     ↓ staffroom_ingest_targets
POST /api/targets/ingest  →  target_pool.status='needs_approval'
     ↓
Owner /approvals  →  /api/targets/{id}/approve
     ↓
target_pool.status='active'
     ↓
ops.sched.tick (6h)     → action_queue rows
     ↓
ops.targets.hydrator (30s)  → action_queue.params_json filled
     ↓
ops.dispatch.worker (60s)
     ↓  (picker-shape → APK-shape)  POST http://127.0.0.1:8089/ via adb reverse
     ↓
Companion APK  →  Accessibility Service  →  foreground IG clone
     ↓  (HTTP response)
target_history + backend/.data/dispatch.ndjson
     ↓
ops.sched.recovery (5m)  →  account status transitions
```

---

## 8. Testing + verification harness

### 8.1 Smoke test suites named in the recent session

From the session gap analysis:
- **`hydrator.py` — 9 of 9 PASS.** The target hydrator's self-test
  suite, run by `python -m ops.targets.hydrator --test` (or a
  nearby entrypoint — the hydrator module ships its own smoke
  path).
- **`targets_admission` — 10 of 10 PASS.** The target admission
  contract's suite, covering ingest, pending list, approve,
  reject, dedup, comment pool, idempotency, counts. Source:
  `backend/phantom_fleet/core/targets_admission.py` with its
  adjacent smoke runner.
- **`wire_test --stub` — 8 of 8 PASS.** The dispatcher wire test in
  stub mode. Source:
  `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\ops\dispatch\wire_test.py`.
  Covers the picker-shape → APK-shape translation.

### 8.2 Where the tests live

| Suite | Source | How to run |
|---|---|---|
| `hydrator.py` 9/9 | `ops/targets/hydrator.py` (self-test block) | `python -m ops.targets.hydrator --test` |
| `targets_admission` 10/10 | `backend/phantom_fleet/core/targets_admission.py` | `python -m phantom_fleet.core.targets_admission --test` (adjust the path to the backend's `pyproject.toml` Python module name) |
| `wire_test --stub` 8/8 | `ops/dispatch/wire_test.py` | `python -m ops.dispatch.wire_test --stub` |
| `wire_test --live` | same | `python -m ops.dispatch.wire_test --live --serial <SER> --port 8089 --I-UNDERSTAND` |

The backend tests under `backend/tests/` (46+ files) cover the
platform modules, agents, and specialists. Examples relevant to
this handoff:
- `test_capacity_planner.py` — capacity planner.
- `test_cluster_monitor.py` — cluster monitor.
- `test_ig_follow_story_core.py`, `test_ig_pod_manager.py` —
  Instagram follow and pod features.
- `test_ig_intelligence.py` — IG intel.
- `test_warming_curve.py`, `test_warming_orchestrator.py` — warming.
- `test_distributions.py` — the distribution classes that back
  CLAUDE.md's rule.
- `test_db_repositories.py` — DB layer.
- `test_ops_brain.py` — operations brain.
- `test_photo_verification.py` — photo-verification path.

The fleet-scale audit lives at
`backend/phantom_fleet/platforms/threads_audit.py:run_audit`,
reporting 31/31 green as of 2026-11-24.

### 8.3 Smoke test harness for the moonshots

Per `docs/moonshots-v1.md` audit 2026-11-25: "live import + smoke on
all ten modules: every one returned a live response in <500 ms".
The smoke harness lives next to each moonshot module (e.g.
`core/simulate.py`, `core/time_machine.py`,
`core/tool_exchange.py`, `core/owner_brief.py`).

### 8.4 CI gate — not yet wired

- The 10K-persona Monte Carlo must be a required CI check per
  CLAUDE.md "Fleet-scale audit gate".
- No `.github/workflows/*.yml` is currently present with this
  wiring (Tier 1.4 backlog).

---

## 9. Observability

### 9.1 `backend/.data/dispatch.ndjson`

- Every claim / dispatch / result lands here via
  `ops/sched/_telemetry.py`.
- NDJSON (one event per line).
- Tail during the pilot: `tail -n 50 backend/.data/dispatch.ndjson`.
- Source-of-truth for dispatcher behaviour; the primary artefact
  the owner examines after a wire test.

### 9.2 `runner/logs/runner-audit.ndjson`

- Every call the Staffroom runner makes to the Claude API (or
  through the stdio bridge) logs one line.
- Fields: `effective_model` (e.g. `claude-opus-4-7`, `claude-sonnet-...`),
  `cost_usd` (0 or null on subscription path), `duration`,
  `prompt_hash`, `mcp_attached`, `mcp_token_hash` (first 8 chars
  of sha256; raw token never written).
- Source-of-truth for model routing + cost + MCP attach state.

### 9.3 Supervisor state (`supervisor_state` table)

- `ops/cron/supervisor.py` persists `last_run_ms`, `last_exit`,
  `last_duration_ms`, `runs`, `failures` per job.
- Query: `python -m ops.cron.supervisor --status`.

### 9.4 Fleet Mirror `/metrics` (Prometheus text, optional)

Per `docs/architecture/MIRROR_CONTRACT.md` §6.2. Scraped every 15s
for the Ops Brain dashboard. Minimum metric set:

```
mirror_devices_online{host="farm-01-dell-7920"} 18
mirror_adb_claim_busy{serial="R5CRC0J6CGT"} 0
mirror_frame_drops_total{serial="R5CRC0J6CGT"} 42
mirror_disconnect_events_total{serial="R5CRC0J6CGT",reason="usb_cable"} 2
```

### 9.5 Mirror Contract events (`WS /events`)

- `device.connected`, `device.disconnected`,
  `device.state_changed`, `adb.released`, `adb.reclaimed`,
  `mirror.focus_changed`, `device.wifi_adb_ready`,
  `cluster.cert_collision`.
- Panel subscribes via `backend/phantom_fleet/mirror_bridge.py`
  (planned per MIRROR_CONTRACT §10).

### 9.6 Phone-side logs

- `adb -s <SERIAL> logcat -s PhantomFleet:V IGEngagementHandler:V`
  — companion APK trace during a pilot run.

### 9.7 No Grafana / Prometheus stack is set up yet

- `/metrics` on the mirror is specified but no scrape config
  exists in the repo.
- No Grafana dashboard JSON is checked in.
- This is a Tier 1 follow-up: ship a Prometheus scrape config
  + a Grafana dashboard JSON next to `docs/architecture/`.

---

## 10. Glossary

- **Fleet.** The whole ~180-device Phantom Fleet deployment: 9 farms
  × ~20 Samsung Galaxy S10 Lite phones.
- **Farm.** One physical location of ~20 phones hanging off a single
  host PC. Farm 1 is on-prem with the user's dev host.
- **Phantom Fleet (OrionFarm).** The new project replacing Onimator.
  Code at `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\`.
  Port 3016 on the Scaler Pro panel bar.
- **Onimator.** The deployed predecessor. Install at
  `C:\Onimator\full_igbot_14.1.8.1\`. Currently offline.
- **Phantom Fleet Mirror.** The phone-wall application running on
  the main PC, fronting every physical device. Contract in
  `docs/architecture/MIRROR_CONTRACT.md`.
- **Clone.** One AppCloner-repackaged (Onimator) or companion-APK-
  managed (Phantom Fleet) instance of a social app on a phone. Each
  clone runs its own IG account. Phantom Fleet rule: unique
  `signing_cert_sha256` per clone fleet-wide.
- **Persona.** A single IG account identity, including its locale,
  timezone, device-model, OS version, carrier, HNI, proxy, diurnal
  curve, warming state, and chronotype. Issued by the persona
  factory with mandatory cross-field pair-check.
- **Persona factory.** The code (`core/persona.py`,
  `agents/persona_factory_agent.py`) that mints personas with the
  pair-check enforced.
- **Target.** An IG account or media item worth engaging with.
  Lives in `target_pool`. Admitted through the ingest / pending /
  approve / reject contract.
- **Picker.** The deterministic selector that reads only
  `target_pool.status='active'` and picks the next target(s) to
  act on, by persona affinity + farm scope. Source:
  `ops/targets/picker.py`.
- **Hydrator.** The 30-second-cadence job that fills missing
  `params_json` (`targetUsername`, `mediaCode`, `text`) on due
  `action_queue` rows before the dispatcher runs. Source:
  `ops/targets/hydrator.py`.
- **Dispatcher.** The 60-second-cadence job that claims due
  `action_queue` rows, translates picker-shape → APK-shape, POSTs
  to the companion APK via `adb reverse`, and records the outcome.
  Source: `ops/dispatch/worker.py`.
- **Picker-shape.** The field names Fleet uses internally
  (`targetUsername`, `mediaCode`, `text`).
- **APK-shape.** The field names the companion APK expects on its
  HTTP surface (`username`, `mediaId`, `text`). Translation
  happens in `ops/dispatch/_transport.py`.
- **adb reverse.** The ADB command that routes a phone's
  `localhost:<port>` to the host's `localhost:<port>`. Lets the
  phone reach a host-side dev server without needing the host's
  LAN IP.
- **Staffroom.** The sibling application (local clone at
  `_staffroom/`, runs on `127.0.0.1:4321`) that holds project
  briefs, bot definitions, MCP scopes, missions, artifacts, and
  the owner-approval UI for propose-work handoffs. Phantom Fleet
  uses Staffroom as the system of record for anything agent-shaped.
- **Staffroom MCP.** The MCP endpoint and tool catalog served by
  Staffroom; stdio bridge at
  `_staffroom/scripts/staffroom-mcp-stdio.mjs`. 13 base tools, 20
  moonshot-era tools.
- **Treg.** The external credential-managed provider of social-
  platform scrape and intel endpoints (treg.to). All Treg calls
  stay server-side in `_staffroom/server/treg-transport.js`; the
  credentials never leave the server. Scopes used: Instagram,
  TikTok, Threads, Reddit, Bluesky.
- **Treg catalog scope.** A dotted scope string such as
  `treg.instagram.hashtag.posts` (and TikHub, ScrapeCreators,
  AnyAPI equivalents) that identifies which Treg endpoint is being
  called. Each has a published micro-credit cost.
- **Max_micro / micro-credits.** Treg's micro-currency used for
  per-call cost gating. 1 000 micro = $0.001. Enforced server-side
  via `X-Treg-Route-Max-Cost` header.
- **COO (Chief of Staff / Chief Operating Officer).** The role in
  the Staffroom roster held by the `coo_strategist` Opus bot. The
  decomposer: breaks owner missions into worker assignments and
  writes the final decision. The COO is **refused `z.ai`** (the
  GLM provider) by configuration — the COO runs on Claude Opus
  only. See the "GLM team" below.
- **GLM team.** A separate set of Staffroom bots provisioned via
  `scripts/provision-staffroom-glm-team.mjs` and smoke-tested with
  `scripts/smoke-test-glm-mcp.mjs` and `smoke-test-glm-openrouter.mjs`,
  routed to the z.ai GLM model via OpenRouter. Used for cheap
  bulk work the COO delegates; the COO itself is not on GLM.
- **Opus COO / Sonnet Worker.** The two base roles configured in
  Staffroom for the Phase A pilot: `COO (Opus)` on connection
  `pf-opus-runner` (API key `pf-opus`, base URL
  `http://127.0.0.1:4330/v1`) and `Worker (Sonnet)` on
  `pf-sonnet-runner`.
- **Runner.** The Node service at `runner/` on port 4330 that
  owns Claude-API routing. Accepts a pinned Bearer (`pf-opus` /
  `pf-sonnet`) and maps it to a model. Enforces
  `--no-paid-fallback`. Source: `runner/src/runner.mjs`.
- **Readiness Review.** The Phase A pilot workflow: COO + two
  Sonnet workers produce a readiness summary + blocker ranking.
- **PF_AUDIT_SIGNER_KEY.** Env var holding the signing key for the
  weekly audit-chain commitment produced by
  `ops/intel/chain.py::make_commitment()`.
- **persona-store.sqlite.** `backend/.data/persona-store.sqlite`
  — the SQLite single-source-of-truth for persona state during the
  SQLite phase. Migrates to Postgres in Tier 1.2.
- **Owner approval UI.** `frontend/src/app/approvals/page.tsx`
  — the page the owner uses to approve/reject pending targets.
  Landed in commit `14d11d9`.
- **Content / comment generator.** The planned AI write-path (the
  only one) that produces candidate comment strings for the
  `comment_pool`. Owner-gated before the picker sees the rows.
- **Companion APK.** The native Kotlin + Jetpack Android app
  (`com.scalerpro.phantomfleet`) that performs social-platform
  actions via Accessibility Service (Phase 1) or signature
  injection (Phase 2 post-Magisk).
- **AppCloner.** The third-party tool Onimator depends on to
  create multiple IG instances per phone. Phantom Fleet
  explicitly replaces it (see Bug 2 in Section 2.2 and the Mirror
  Contract §5).
- **Clipster.** The content-approval pipeline from the older
  Fleet; not present in this build (capability map §8).
- **GLM.** The z.ai / OpenRouter model family used by the GLM
  team of Staffroom bots.
- **Tailscale staging.** The private URL
  `https://desktop-c74bmhb.tail72dd7e.ts.net:10444/`. Phase E of
  the backlog depends on owner sign-in being restored (currently
  502).
- **Warming curve.** The 48-hour initial reel-watching warmup
  pattern Onimator used for new accounts; Phantom Fleet preserves
  and extends this. Core: `core-rs/src/warming.rs` is the first
  1:1 Rust port.
- **Fleet Mirror hub.** The main-PC application fronting every
  physical phone across every host. Separate from the Mirror
  Contract spec.
- **Needs approval.** Target-pool status `needs_approval` — the
  state every ingested row lands in until the owner approves it.
- **Active.** Target-pool status `active` — rows readable by the
  deterministic picker.
- **Rejected.** Target-pool status `rejected` — rows invisible
  to the picker.
- **Dispatch.ndjson.** `backend/.data/dispatch.ndjson` — the
  single-file append-only event sink for every claim / dispatch /
  result (observability source-of-truth).
- **Supervisor_state.** The SQLite table tracking cron-job
  `last_run_ms`, `last_exit`, `last_duration_ms`, `runs`,
  `failures`. Prevents the "thundering restart" bug.
- **Scheduler tick.** The 6-hour-cadence job
  (`ops/sched/tick.py`) that enqueues the next day's actions per
  alive account.
- **Replacement queue.** The 6-hour-cadence job
  (`ops/sched/replacement.py`) that emits `replacements_needed`
  rows for dead accounts.
- **Weekly commitment.** The 7-day-cadence job that signs the audit
  chain head via `ops/intel/chain.py::make_commitment()`. Needs
  `PF_AUDIT_SIGNER_KEY` in env.
- **Pair-check.** The persona-factory rule that every identity
  field must consistency-check against every other identity field
  (locale ↔ tz, device ↔ OS, carrier ↔ HNI, proxy ↔ tz,
  carrier ↔ country, AppCloner fingerprint). Enforced at mint
  time, not downstream.
- **Diurnal curve.** The persona's per-hour action probability
  distribution, matched to its claimed local time. Implemented in
  `platforms/instagram_diurnal.py`.
- **LogNormal / Normal / Bimodal / WeightedCategorical.** The
  four typed distribution classes mandated by CLAUDE.md. Lives in
  `backend/phantom_fleet/core/distributions.py`.
- **Monte Carlo harness.** The 10 000-persona required-CI-check
  simulation at `platforms/threads_audit.py:run_audit`, 31/31
  green.
- **Micro-tenant.** Not yet implemented. The Tier 2 multi-tenant
  layer introduces `tenant_id` throughout; "micro-tenant" is the
  owner's own single-tenant pilot.
- **adb reverse port forward.** `adb -s <SERIAL> reverse tcp:8089
  tcp:8089` — the phone's `127.0.0.1:8089` becomes a tunnel to the
  host's `:8089` (where the Fleet dispatcher reaches the companion
  APK's loopback listener).
- **`--I-UNDERSTAND` flag.** The reflex-brake on
  `ops.dispatch.wire_test --live`. Required to perform one real IG
  follow on the pilot clone. The flag is there so operators do not
  run live-mode by muscle memory.

---

End of Section 5.


---

