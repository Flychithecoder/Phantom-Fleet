# `comment_generator` — AI comment candidate drafting

**Role:** Produce candidate Instagram-style comments for a given niche.
Candidates land in `comment_pool.status='needs_approval'`. The owner
approves or rejects them via the `/approvals` UI (frontend) or
Staffroom MCP tools before any clone posts them.

**Runs as:** Owner-triggered HTTP call (`POST /api/comments/generate`),
or Staffroom bot via `staffroom_generate_comments`. This is the one
intentional AI write-path in Phantom Fleet. Every other action in the
system is a deterministic state machine.

---

## System prompt (bot definition)

```
You are comment_generator, the one AI write-path in Phantom Fleet.
You draft candidate Instagram-style comments for a farm niche. You
return a batch of candidate texts. You never post, never approve,
never flip comment_pool rows to active. Your output goes through a
safety filter (links, @-mentions, phone numbers, emails, blocklist)
and an admission gate before the owner ever sees it.

You MUST:
  1. Stay under the per-run cost cap enforced by the
     cost_quality_router recommendation; the router's chosen team
     (claude | glm) is logged in the receipt.
  2. Produce exactly up to `n` candidates per call; return fewer if
     you cannot meet the quality bar for the niche.
  3. Keep each candidate ≤ 500 characters.
  4. Avoid links, @-mentions, phone numbers, email addresses, and the
     project blocklist. Even though the safety filter will drop them,
     wasting the caller's budget on candidates it will drop is
     antisocial.
  5. Write in the register appropriate to the niche; follow
     `style_hints` when provided.

You MUST NOT:
  - Call staffroom_approve_comment. Approval is owner-only.
  - Return anything that would identify the farm, the clone, or the
    Phantom Fleet operator.
  - Chain into the picker, the dispatcher, or the executor.
  - Post directly to any platform. Your scopes are text generation
    only.
```

## Input contract

```
POST /api/comments/generate
{
  "niche": "fashion",
  "n": 20,
  "style_hints": ["warm", "specific", "under 12 words"]
}
```

- `niche`: 1–40 chars, used as `comment_pool.niche` for admission rows.
- `n`: 1–200. The run produces at most this many candidates.
- `style_hints` (optional): up to 20 short strings passed to the
  model. Not persisted on the row — only in the audit log.

## Output contract (the receipt)

```
{
  "run_id": "cg_1764012345_a1b2c3d4",
  "niche": "fashion",
  "style_hints": ["warm", "specific"],
  "requested": 20,
  "raw_candidates": 20,
  "length_dropped": 1,
  "within_batch_duplicates": 2,
  "safety_dropped": [
    {"text": "...@spam...", "reason": "contains_mention"}
  ],
  "submitted_to_admission": 16,
  "admission": {
    "inserted": 15,
    "duplicates": 1,
    "rejected_count": 0
  },
  "route_recommendation": {
    "recommended_team": "claude",
    "role": "content_writer"
  },
  "source": "ai.comment_generator:cg_1764012345_a1b2c3d4",
  "duration_ms": 1823
}
```

## Pipeline (deterministic within a single run)

1. `cost_quality_router.recommend_team(workflow="comment_generation",
   role="content_writer")` — pick the model team and record the
   factors in the receipt.
2. Call the injected `generator_fn(niche, n, style_hints)` for `n`
   raw candidate strings.
3. Strip whitespace; drop empty.
4. Drop anything > 500 characters (counted in `length_dropped`).
5. Exact-text dedupe within the batch (counted in
   `within_batch_duplicates`). This is a cheap pre-filter; the
   admission gate enforces the real dedupe against the stored pool.
6. `comment_safety.filter_safe(...)` — drop candidates containing a
   URL, an `@mention`, a phone number, an email, or a blocklist
   term. The blocklist lives at
   `backend/.data/comment_blocklist.txt`.
7. `targets_admission.ingest_comments(rows, source=...)` — lands
   survivors as `needs_approval`. The admission gate itself also
   enforces length and dedupe.

The run writes one record to
`backend/.data/comment_generator-audit.ndjson` with the full receipt.

## Failure modes (never raises)

- The generator function returns fewer than `n` → the receipt shows
  it; the run still succeeds.
- Every candidate fails safety → `submitted_to_admission=0`,
  `admission.inserted=0`. The owner sees an empty batch and can
  retry.
- The admission gate rejects every row (long text, empty, DB error on
  insert) → `admission.rejected_count > 0`; the receipt is still
  returned.
- `recommend_team` raises → propagates as a 500 (bad input to the
  router); the HTTP layer surfaces it.

## Cost budget

Per-run cost is tracked by the router, not enforced inside this
module. The enforced cap is the admission gate:
- `n ≤ 200` per call
- length ≤ 500 chars per candidate
- the admission gate deduplicates against the entire stored
  `comment_pool`, so repeat runs cannot flood the queue with the
  same text.

The audit log entry (`backend/.data/comment_generator-audit.ndjson`)
is the owner's primary receipt. Every run writes one line.

## Approval requirement — non-bypassable

**The comment_generator module has no ability to call
`approve_comment`.** It can only produce `needs_approval` rows. This
is enforced three ways:

1. The module does not import `approve_comment`.
2. `targets_admission.ingest_comments` hard-codes
   `status='needs_approval'`.
3. The picker (deterministic) reads only `status='active'`. A
   candidate that never reaches `active` can never be posted.

The owner is the only path from `needs_approval` → `active`, via
`/approvals` (frontend) or the Staffroom MCP tools
`staffroom_approve_comment` / `staffroom_reject_comment`. This is the
CLAUDE.md agent rule: the admission gate is non-bypassable.

## Cross-reference

- Admission gate code: `backend/phantom_fleet/core/targets_admission.py`
- Safety filter: `backend/phantom_fleet/core/comment_safety.py`
- HTTP surface: `backend/phantom_fleet/api/routes/comments.py`
- Staffroom MCP tool: `_staffroom/server/staffroom-mcp.js`
  (`staffroom_generate_comments`)
- Runner allowlist: `runner/src/mcp.mjs`
- Owner UI: `frontend/src/app/approvals/page.tsx`
- Audit log: `backend/.data/comment_generator-audit.ndjson`
- Sibling pattern: `docs/staffroom/agents/ig_target_scout.md`
