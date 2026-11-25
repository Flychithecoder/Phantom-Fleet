# Target + comment admission contract

Phantom Fleet's deterministic target picker only reads rows in
`target_pool.status='active'` and `comment_pool.status='active'`. Every
candidate lands in `needs_approval` first; the owner approves via
Staffroom. This is the Fleet half of that contract; the Staffroom MCP
shim wraps these HTTP calls and nothing else.

## Where the rows come from

The Treg-driven platform-team agents listed in
`docs/staffroom/01-team-roster.md` produce candidates:

| Agent | Treg scope used | Delivers to |
|---|---|---|
| `ig_target_scout` | `treg.instagram.hashtag.posts`, `treg.instagram.search.users` | `POST /api/targets/ingest` (kind=account) |
| `ig_viral_hunter` | `treg.instagram.hashtag.posts` (sort=reels) | `POST /api/targets/ingest` (kind=media) |
| `ig_commenter_harvester` | `treg.instagram.post.comments` | `POST /api/targets/ingest` (kind=account) |
| `ig_profile_intel` | `treg.instagram.user.profile` | annotate existing rows (future) |

Treg credentials stay server-side in
`_staffroom/server/treg-transport.js`. Each live Treg call still goes
through `/api/treg-research/:id/approve` with its max_micro cost gate
and receipt check. Ingest to Fleet is cheap (local HTTP) and happens
AFTER the Treg call has settled.

## Base URL

`http://${FLEET_HOST}:3016` — Phantom Fleet FastAPI app on port 3016.

Auth: Staffroom server uses the shared bearer already configured for
every other Fleet bridge call. Not a public surface.

## Endpoints

### 1. Ingest targets (upstream agent → Fleet)

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

### 2. List pending targets (Staffroom browse)

```
GET /api/targets/pending?farm_id=farm_us_east_01&limit=100
```

Returns `{rows: [...]}`. Omit `farm_id` to see all pending across every
farm (including global `farm_id=NULL` rows).

### 3. Approve / reject target (owner decision)

```
POST /api/targets/{target_id}/approve
{"approver": "owner@phantomfleet"}

POST /api/targets/{target_id}/reject
{"approver": "owner@phantomfleet", "reason": "off-niche for this farm"}
```

Both return `{"ok": true, "id": N, "status": "active"|"rejected", "ts_ms": ...}`.
Approving an already-decided row returns `{ok: false}` with a 404.

### 4. Comment pool (parallel surface)

```
POST /api/targets/comments/ingest
{"source": "treg.comment_writer",
 "rows": [{"text": "love this!", "niche": "fitness"}]}

GET  /api/targets/comments/pending?limit=100
POST /api/targets/comments/{id}/approve  {"approver": "..."}
POST /api/targets/comments/{id}/reject   {"approver": "...", "reason": "..."}
```

### 5. Signals for owner_brief

`GET /api/targets/pending_counts` → `{"pending_target_approvals": N,
"pending_comment_approvals": M}`. The owner brief already pulls these
via the `targets_admission.pending_counts()` core call; the HTTP is for
Staffroom's own card rendering.

## MCP tool shims (Staffroom side)

The runner allowlist already carries these names:

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

Shim implementation goes in `_staffroom/server/mcp-tools/targets.js`
mirroring the existing `_staffroom/server/mcp-tools/tool_exchange.js`
pattern — thin fetch calls, no business logic.

## Guarantees

- Picker reads only `status='active'`. Rejected and pending rows are
  invisible to the dispatcher.
- Rows are farm-scoped by `farm_id`. A global row (`farm_id=NULL`) is
  pickable by every farm; use for evergreen targets.
- Deterministic admission: idempotent approvals, no double-approval.
- Owner remains the sole gate from `needs_approval` → `active`.
