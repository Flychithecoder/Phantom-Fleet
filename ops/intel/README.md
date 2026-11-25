# ops/intel/ — the deterministic-architecture dividend

Seven capabilities that are mathematically impossible under an
LLM-driven control plane and uniquely possible under ours. Every
module here is a pure function; AI is used for research and oversight
only.

## Modules

| # | Module | What it unlocks |
|---|---|---|
| 1 | `replay.py` | Perfect replay of any tick + shadow-mode A/B testing |
| 2 | `clone.py` | MLE-fit per-persona distributions from 43K rows of Onimator data |
| 3 | `detector.py` | 14-rule detection simulator + P(survival|N days) scoring |
| 4 | `swarm.py` | Trending-view, Barabási-Albert community graphs, cohort synchrony |
| 5 | `chain.py` | Hash-chained decision audit + weekly signed commitments |
| 6 | (sibling: `core-rs/`) | Rust transpilation; `warming.rs` shipped |
| 7 | `marketplace.py` | Rule-PR grader (static + determinism + survival gradient) |

## How they compose

```
PR lands rule candidate -> marketplace.grade_rule_pr
                              |
                              v
                   static_check (no random, no net, no AI)
                              |
                              v
                   determinism_check (same inputs -> same output 200x)
                              |
                              v
                   detector.grade(with) vs detector.grade(without)
                              |
                              v
                   accepted iff survival_delta >= 0

Every tick in ops/sched -> replay.log_tick + chain.append
                              |                   |
                              v                   v
                  shadow comparisons        verify_chain by anyone
                              |                   |
                              v                   v
                   divergence rows       zk-STARK compatible when
                                         chain.make_commitment is
                                         swapped for a prover
```

## Smoke test

`scratchpad/intel_smoke.py` exercises all 7 end-to-end on a fresh DB:
25/25 PASS on last run.

## The gradient

The point of #3 is that every future change to the control plane gets
a number. Add a rule -> survival goes up or down by X. That number
becomes the CI check, the hiring metric, the compliance claim, and
the KPI for the SaaS pricing tier. No competitor built on LLMs can
climb this gradient; they can't even measure where they stand on it.

## What's stubbed

- `chain.make_commitment` uses HMAC-SHA256; Phase 1 swaps in zk-STARK
  without changing the chain shape.
- `core-rs/` has only `warming.rs` ported; remaining state machines
  land in Phase 1.
- The detector's `_WEIGHTS` are tuned against synthetic cohorts;
  real-data calibration happens as the Onimator log + production
  observations land.
