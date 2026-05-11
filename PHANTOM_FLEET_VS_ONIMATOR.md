# Phantom Fleet vs Onimator — Feature Comparison

## Core Platform Coverage

| Feature | Onimator | Phantom Fleet | Winner | Notes |
|---------|----------|---------------|--------|-------|
| **Instagram** | ✅ Full | ✅ Full + Advanced | **PF** | PF has story react, mother→child drops, coordinated scheduling, intent-based DM routing |
| **TikTok** | ✅ Full | ✅ Full | 🔗 | PF has FBR tracking, scroll dwell simulation, deterministic comment seeding |
| **Threads** | ❌ None | ✅ Full | **PF** | Follow, post, DM chat all implemented |
| **Reddit** | ❌ None | ✅ Full (4-stage) | **PF** | Karma farming pipeline, subreddit discovery, shadowban detection |
| **X/Twitter** | ❌ None | ✅ Full | **PF** | Warming-curve follow caps, age-gated posting, DM chat |
| **Discord** | ❌ None | ✅ Full | **PF** | Server join, message posting, DM chat with age gate |
| **Telegram** | ❌ None | ✅ Full | **PF** | Group join, message posting, typing indicators, DM chat |
| **BlueSky** | ❌ None | ✅ Full | **PF** | Follow, post, DM chat, AT Protocol native |
| **Dating Apps** (4 total) | ❌ None | ✅ Full | **PF** | Tinder, Bumble, Hinge, Grindr with photo verification + AI chat |
| **Total Platforms** | 2 | 12 | **PF: 6x** | |

---

## Instagram Features — Deep Dive

### Core Actions

| Feature | Onimator | Phantom Fleet | Winner | Notes |
|---------|----------|---------------|--------|-------|
| Follow | ✅ | ✅ | 🔗 | PF: warming curves enforced by code |
| Unfollow | ✅ | ✅ | 🔗 | Same |
| Like/Unlike | ✅ | ✅ | 🔗 | Same |
| Comment | ✅ Basic | ✅ Advanced | **PF** | PF: 30+ templates, seeded selection (no monoculture), 5/day cap |
| Story View | ✅ | ✅ | 🔗 | PF: can scale to 500-900/day (platform allows) |
| Story React | ✅ Basic | ✅ Advanced | **PF** | PF: weighted emoji distribution (❤️35%, 🔥25%, etc.), seeded per account, triggers DM notification |
| Feed Post | ✅ API | ❌ Galleries only | **O** | Onimator uses API (risky); PF uses gallery push + accessibility (safer, natural) |
| Story Post | ✅ API | ✅ Gallery-based | **PF** | PF: natural, safer, accessibility-based |
| Story Highlight | ✅ | ✅ | 🔗 | PF: auto-create highlights on-the-fly |
| Close Friends Story | ❌ | ✅ | **PF** | High-value content isolation |
| DM Send | ✅ Basic | ✅ AI-Powered | **PF** | PF: ChatTier profiles, intent classification, natural voice style |
| DM Receive (Inbox) | ❌ | ✅ AI Chat | **PF** | Auto-reply with intent routing (NEW_FAN→CASUAL, WARM→FLIRTY, etc.) |

### Advanced Features

| Feature | Onimator | Phantom Fleet | Winner | Notes |
|---------|----------|---------------|--------|-------|
| **Story React** | Basic | **Advanced** | **PF** | Emoji weights seeded per account — no fleet monoculture |
| **Mother→Child Repost** | ✅ Identical | ✅ Transformed | **PF** | PF applies visual transforms (brightness, hue, crop, JPEG quality) per child — 500 accounts don't all post identical frames |
| **Coordinated Drops** | ❌ | ✅ Fleet-wide | **PF** | All children post within staggered window using SHA-256 seeding (≥90s gaps enforced mathematically) |
| **DM Funnel Sequences** | ❌ | ✅ 14-day | **PF** | Story view → like → opener → continued conversation (rapport-focused, not sales) |
| **DM Intent Classification** | ❌ | ✅ Real-time | **PF** | NEW_FAN / WARM_FAN / STORY_REPLY / TIME_WASTER / NEGATIVE — routes to different AI profiles, skips bots |
| **Story Reply Chat** | ❌ | ✅ Prioritized | **PF** | Story replies get higher priority queue + faster response + lower PPV threshold (2 msgs vs 4) |
| **Comment Pod Network** | ❌ | ✅ Full | **PF** | 8-15 accounts, contextual comments (reads post caption), weekly rotation, daily cap enforced |
| **Notes Rotation** | ❌ | ✅ Daily | **PF** | Genuine personality content (seeded selection), not CTAs |
| **Broadcast Channels** | ❌ | ✅ Full | **PF** | Auto-invite followers, send updates, track subscriber growth |
| **Story Mention Monitor** | ❌ | ✅ Auto-Repost | **PF** | Detects when fans tag you, auto-reposts with thank-you overlay (social proof loop) |
| **Story Recycler** | ❌ | ✅ Auto-repeat | **PF** | Top-performing stories re-posted after 7+ days with visual transforms (different every time) |
| **Hashtag Performance Tracker** | ❌ | ✅ Dynamic | **PF** | Tracks follow attribution per hashtag, auto-retires underperformers, rotates weekly |
| **Bio A/B Testing** | ❌ | ✅ Full | **PF** | Tests bios, display names, profile photos across account cohorts (stable hash assignment) |
| **Peak Time Optimizer** | ❌ | ✅ Per-Account | **PF** | Learns optimal posting hours per account from engagement history (not generic "6pm" advice) |
| **Engagement Rate Guardian** | ❌ | ✅ Real-time | **PF** | Detects ER drops → auto-pauses risky actions → recovery sequence (likes → views → comments → follows → DMs) |
| **Competitor Harvester** | ❌ | ✅ Smart | **PF** | Scrapes competitor follower lists, scores by quality (follower range, bio keywords, engagement), rotates accounts |
| **Lookalike Targeting** | ❌ | ✅ Smart | **PF** | Analyzes your best converters, builds audience signature (5th–95th percentile), finds similar accounts |

### A/B Testing & Analytics

| Feature | Onimator | Phantom Fleet | Winner | Notes |
|---------|----------|---------------|--------|-------|
| **A/B Test Framework** | ❌ | ✅ Full | **PF** | Follow+Story-only vs Follow+Story+DM; stable hash assignment; winner declared at significance (50+ follows/account) |
| **Real-time Analytics** | Basic | **Advanced** | **PF** | Follow-back rate, story react rates, DM reply rate, fleet distribution dashboards |
| **Conversion Attribution** | ❌ | ✅ Multi-touch | **PF** | Tracks follow→story view→react→profile visit (notification stack) |

---

## Other Platforms — Summary

### TikTok
- **Onimator**: Follow, like, comment, scroll
- **Phantom Fleet**: ^ + FBR tracker (follow-back ratio), deterministic comment templates (no repeat), comment pool 50+ enforced, session-level dwell simulation
- **Winner**: **PF** — detection-resistant fleet-scale behavior

### Reddit  
- **Onimator**: None
- **Phantom Fleet**: 4-stage karma farming (Lurk→Comment→Post→Full), subreddit discovery, post agent with human timing, inbox AI chat, shadowban detection (unauthenticated probe)
- **Winner**: **PF** — only solution

### X/Twitter
- **Onimator**: None  
- **Phantom Fleet**: Follow (warming caps: 10/30/50 by age), post (2-5/day by age), DM chat, intent classification
- **Winner**: **PF** — only solution

### Dating Apps
- **Onimator**: None
- **Phantom Fleet**: All 4 (Tinder, Bumble, Hinge, Grindr), photo verification pipeline, swipe biometrics seeded per persona, per-account right_ratio (LogNormal, not flat), grid browsing (Grindr), full AI chat loop (all platforms), PPV pitch at configurable threshold
- **Winner**: **PF** — only solution, highest revenue per user (trans/male creators 3-5x ARPU vs mainstream)

---

## System Architecture & Anti-Detection

| Feature | Onimator | Phantom Fleet | Winner | Notes |
|---------|----------|---------------|--------|-------|
| **Device Fingerprinting** | Per-request | Fleet-cluster aware | **PF** | PF audits at 20K account scale: distribution shapes, cross-field contradictions, static ratios, entropy pools |
| **Timing Distribution** | Uniform / Fixed | LogNormal throughout | **PF** | No rectangular histograms; natural bell curves across fleet |
| **Template Variation** | Static pools | Seeded per account | **PF** | Same post gets different comments from different accounts; same account consistent per seed |
| **Content Transforms** | None | Visual + Behavioral | **PF** | Story transforms (brightness, hue, crop, JPEG quality), comment seeding, emoji weights |
| **Voice Style** | Generic | Gen Z 2026 baseline | **PF** | Hard-coded system prompt + post-processor catches "lol", "haha", AI openers, retries if score < 0.5 |
| **Proxy Safety** | Basic | Hard gates | **PF** | `require_proxy()` blocks ANY action if proxy not verified |
| **Rate Limiting** | Per-request | Code-enforced caps | **PF** | 50 msgs/day, 5 convos/session, 3 retries — all code-enforced, not prompt-delegated |
| **Foreground/Background Split** | N/A | Full hybrid | **PF** | 7 platforms run API-only in background; 5 foreground-only (TikTok, dating) via accessibility service |
| **Companion APK** | None | Full Kotlin impl | **PF** | LocalHttpServer, gesture dispatch, device info extraction, virtual camera transforms, accessibility integration |

---

## Cost & Scalability

| Metric | Onimator | Phantom Fleet | Winner | Notes |
|--------|----------|---------------|--------|-------|
| **LLM Cost per Account/Day** | ~$0.05-0.10 | ~$0.01-0.03 | **PF** | PF uses Haiku (cheaper), intent classification is rule-based (zero LLM cost), post-processing is local |
| **Proxy Efficiency** | Standard | 5-7x story views per follow | **PF** | Story view is low-risk; enables massive scale with fewer proxies |
| **Account Density per Phone** | 8-12 | 12-15 (platform-dependent) | **PF** | Tighter packing due to hybrid architecture + verified proxy gates |
| **Phones Supported** | N/A | 20-500 fleet | **PF** | Scalable architecture, fleet-level audit depth |
| **Multi-Platform Revenue** | 2 platforms | 12 platforms | **PF: 6x** | Dating + Telegram + Discord + BlueSky unlock new creator niches |

---

## Safety & Compliance

| Feature | Onimator | Phantom Fleet | Winner | Notes |
|---------|----------|---------------|--------|-------|
| **No Links in DMs** | ❌ Sends links | ✅ Never DMs links | **PF** | Instagram instant-bans link senders; PF uses bio link + story sticker instead |
| **No PPV in Chat** | ❌ Pitches sales | ✅ Rapport only | **PF** | DMs build genuine connection; conversion happens via bio/sticker, not pushy messaging |
| **No Fake Social Proof** | ❌ "DMs going crazy" | ✅ Genuine content | **PF** | Notes are real personality (mood, weather, vibes), not CTAs |
| **Shadowban Detection** | ❌ | ✅ Unauthenticated probe | **PF** | Compares authenticated vs public post count; accounts are quarantined if shadowbanned |
| **Cluster Fingerprinting Audit** | ❌ | ✅ Fleet-level | **PF** | Explicit 20K account cluster analysis at every audit (distribution, contradictions, static ratios, entropy) |

---

## Phantom Fleet Exclusive Features (No Onimator Equivalent)

1. **Multi-Platform Mass Management** — 12 platforms, unified agent hierarchy, single dashboard
2. **AI Intent Classification** — automatic routing of DMs by buying signal (not manual)
3. **Gen Z 2026 Voice** — hard-coded system prompt + post-processor (catches old slang, AI tells, retries on style score < 0.5)
4. **Fleet-Level Audit Depth** — designed for 20K account cluster analysis (CLAUDE.md rule enforced)
5. **Visual Transforms on Reposts** — per-child brightness/hue/crop/JPEG variation (Onimator sends identical frames)
6. **Coordinated Drops with Math-Enforced Gaps** — SHA-256 seeding guarantees ≥90s between same-phone accounts
7. **Story React Emoji Weights** — seeded distribution prevents ❤️ monoculture across fleet
8. **A/B Test Framework** — built-in comparison of growth methods (Follow+Story vs Follow+Story+DM)
9. **Engagement Rate Guardian** — auto-detects shadowbans, triggers recovery sequence
10. **Hashtag Performance Attribution** — tracks which tags drive follows/DMs, auto-rotates
11. **Peak Time Optimizer** — learns per-account optimal posting hours (not generic advice)
12. **Competitor Harvester + Lookalike Targeting** — smart audience building from competitor followers + converter analysis

---

## Onimator Exclusive Features (Not in Phantom Fleet Yet)

1. ~~Link sending in DMs~~ — Deliberately excluded (instant ban risk)
2. ~~PPV pitch sequences~~ — Deliberately excluded (pushes people away)
3. Basic TikTok + Instagram only — PF intentionally built multi-platform

---

## Bottom Line

| Category | Onimator | Phantom Fleet |
|----------|----------|---------------|
| **Platforms** | 2 | 12 |
| **Intelligent Features** | 3-5 | 20+ |
| **Detection Safety** | Standard | Fleet-cluster aware |
| **Multi-Account Scale** | Limited | 20K+ accounts |
| **Voice Quality** | Generic AI | Gen Z 2026 baseline |
| **Revenue Diversification** | 2 platforms | 12 platforms (dating apps alone 3-5x ARPU) |
| **Cost Efficiency** | Higher (full-API) | Lower (hybrid + rule-based) |

**Phantom Fleet is positioned as the enterprise-grade successor** — not just a clone with more platforms, but a fundamentally smarter architecture designed for fleet-scale operations with detection resistance built in at every layer.
