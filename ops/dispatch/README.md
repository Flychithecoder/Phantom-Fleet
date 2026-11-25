# ops/dispatch/ — queue → APK dispatcher

Reads `action_queue`, calls the companion APK over HTTP, records the
outcome into `action_results`. Deterministic at the decision level;
the actual phone response isn't reproducible, but every row we claim,
every endpoint we choose, every outcome we classify is a pure
function of (queue state, response bytes).

## Files

```
ops/dispatch/
  _endpoints.py   scheduler kind -> APK endpoint spec + payload build
  _outcome.py     HTTP (status, body) -> outcome string
  _transport.py   atomic claim, device IP resolution, urllib HTTP
  worker.py       main loop + CLI
```

## Kind → endpoint mapping (verified in the APK audit)

| scheduler kind | HTTP | APK path | required params from `params_json` |
|---|---|---|---|
| `follows` | POST | `/instagram/engage/follow` | `targetUsername` |
| `likes` | POST | `/instagram/engage/like` | `mediaCode` |
| `stories` | POST | `/instagram/engage/view_stories` | `usernames` |
| `comments` | POST | `/instagram/engage/comment` | `mediaCode`, `text` |
| `unfollow` | POST | `/instagram/engage/unfollow` | `targetUsername` |
| `scroll_reels` | POST | `/instagram/engage/scroll_reels` | — |
| `check_session` | GET | `/instagram/engage/check_session` | — |

## Outcome catalogue (feeds recovery.py)

| outcome | recovery rule that acts on it |
|---|---|
| `ok` | R5 self-heal |
| `login_required` | R1 (3x in 24h → needs_reset) |
| `checkpoint` / `account_disabled` | R2 (→ dead) |
| `network_error` | R3 (5x in 2h → proxy rotate signal) |
| `ig_rate_limited` | R3 (3x in 2h → proxy rotate signal) |
| `accessibility_unbound` | operator alert (not scheduler-actionable) |
| `missing_target` | terminal; permanent failure |
| `unknown` | terminal; permanent failure |

## Safety

- **Atomic claim.** `_transport.claim()` transitions `due → claimed`
  in one UPDATE; two concurrent workers never dispatch the same row.
- **Per-device cooldown.** 150ms minimum between actions on the same
  phone. Prevents sub-100ms-synchrony detection and overloaded UI.
- **Terminal failures land results.** `missing_target` and no-endpoint
  rows get a result row so they don't re-enter the queue forever.
- **Transport failures release the claim.** A phone that times out
  gets its row back to `due` for the next loop.
- **Every live pass is audited.** `instrument("dispatch", apply=True)`
  writes tick_log + audit_chain just like the sched layer.

## Cron

```
# Fire every minute; 25 rows per pass is well under any phone's cap.
*/1 * * * *  python -m ops.dispatch.worker --apply --max 25
```

## Smoke test

`scratchpad/dispatch_smoke.py` stands up a localhost HTTP server that
replays the real APK's response shapes (ok, accessibility_unbound,
checkpoint, 429), seeds 7 queue rows (5 real + 2 garbage), and asserts:

- every row drains in at most 7 loops under cooldown
- each outcome lands in `action_results` with the correct classification
- every live pass writes a chain row
- `chain.verify_chain()` is clean
- the first dispatcher tick's decisions can be replayed verbatim

14/14 PASS. Run it: `python scratchpad/dispatch_smoke.py`.

## What's NOT here

- **Target picker.** `params_json` carries `targetUsername` / `mediaCode`
  today; the warming-curve scheduler emits those as empty, so real
  dispatch needs a Content Vault → target-pool step upstream. For now
  rows without a target land `missing_target` cleanly.
- **Parallel workers.** One process, serial per-device. Scale by
  running more processes; the atomic `claim()` is the lock.
- **HMAC auth header.** Phase 1 hardening.
