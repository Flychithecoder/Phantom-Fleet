# `ig_target_scout` — Instagram target discovery

**Role:** Discover IG accounts worth engaging with. Research only; no
posting, following, liking, or any write action on IG itself. Produces
candidate rows for Phantom Fleet's `target_pool`.

**Runs as:** Staffroom bot, cadence defined in
`docs/staffroom/03-automation-backlog.md` row "IG target discovery
cadence". Owner reviews every batch before it affects the fleet.

---

## System prompt (bot definition)

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

## Input contract

```
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

## Output contract (what the agent emits on completion)

```
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

## Discovery algorithm (deterministic within a single run)

1. Expand the seed accounts via `tikhub.instagram-v3-get-similar-users`
   (one call per seed; stop when budget would be exhausted).
2. For each niche term, call `treg.instagram.hashtag.posts` and keep
   top-50 posts, then extract post authors.
3. For each term, call `treg.instagram.search.users` limited to the
   follower band `[min_followers, max_followers]`.
4. Union the three sets; drop accounts marked private (unless opt-in),
   shadowbanned, or already in `staffroom_list_pending_targets(farm_id)`.
5. Score each surviving account by:
   - tag overlap with `niche_terms` → `tags`
   - follower count sanity → kept, not scored
   - already-engaged-by-fleet → dropped (surfaced by the Fleet via a
     later endpoint; for now, trust the dedupe check)
6. Take the top `target_count` by overlap, in handle-alphabetical order
   on ties (deterministic).
7. One `staffroom_ingest_targets` call. Done.

## Treg call budget (per run)

Hard cap enforced by `_staffroom/server/treg-transport.js` via
`X-Treg-Route-Max-Cost`. The agent must also self-cap inside
`max_micro_credits` from the input brief. If a call would push past
the budget, the agent SKIPS the call and continues with what it has;
it does not degrade silently — the receipt records every skipped call
with `skipped: "budget_exhausted"`.

## Failure modes the agent handles (never raises)

- Treg 429 → exponential backoff via existing transport; three strikes
  and the agent returns what it has.
- Treg 403 (route not approved) → return empty batch with
  `treg_calls[i].error = "route_not_approved"`.
- `staffroom_ingest_targets` returns `{error: ...}` from Fleet → the
  agent surfaces the error verbatim to the owner and does NOT retry.

## Cross-reference

- Treg scopes and cost table: `docs/staffroom/05-research-access.md`
- Ingest/approve contract: `docs/staffroom/07-target-admission-contract.md`
- Owner approval UI (pending): tracked in the buildout list
- Automation cadence: `docs/staffroom/03-automation-backlog.md`
