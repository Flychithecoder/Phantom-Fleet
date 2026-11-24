-- Phantom Fleet — Threads platform persistence
-- Funnel events, health snapshots, recovery records, IG cross-post bus.
--
-- Up to this migration, Threads kept its state in-memory on app.state. A
-- restart wiped funnel attribution, every health history point, every
-- recovery timeline, and every IG post the bridge had seen. That was fine
-- while the module was experimental; now that the orchestrator + recovery
-- agent read these counters to decide what to dispatch, losing them on a
-- deploy is a ship blocker.
--
-- All tables use TEXT PKs matching the in-memory dicts, so the app code
-- can replay them straight back in. JSONB columns hold things the schema
-- would churn on (signals dict, recovery notes list) — searchable but
-- not query-shaped.

BEGIN;

-- ---------------------------------------------------------------------------
-- threads_funnel_events — append-only attribution ring
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS threads_funnel_events (
    event_id            BIGSERIAL PRIMARY KEY,
    kind                TEXT NOT NULL,          -- reply_posted|post_posted|profile_view|bio_link_click|subscribe
    threads_account_id  TEXT NOT NULL,
    ig_account_id       TEXT,
    action_id           TEXT,
    target              TEXT NOT NULL DEFAULT '',
    meta                JSONB NOT NULL DEFAULT '{}'::jsonb,
    ts                  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_threads_funnel_by_account
    ON threads_funnel_events (threads_account_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_threads_funnel_by_kind
    ON threads_funnel_events (kind, ts DESC);


-- ---------------------------------------------------------------------------
-- threads_health_snapshots — one row per health computation
--
-- Every scan writes a snapshot so the drill page can draw a score sparkline
-- and the orchestrator (future) can react to score DELTA, not just
-- current state.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS threads_health_snapshots (
    snapshot_id         BIGSERIAL PRIMARY KEY,
    account_id          TEXT NOT NULL,
    status              TEXT NOT NULL,          -- healthy|watch|at_risk|shadowbanned
    score               INTEGER NOT NULL,
    flags               JSONB NOT NULL DEFAULT '[]'::jsonb,
    signals             JSONB NOT NULL DEFAULT '{}'::jsonb,
    computed_at         TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_threads_health_by_account
    ON threads_health_snapshots (account_id, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_threads_health_by_status
    ON threads_health_snapshots (status, computed_at DESC);


-- ---------------------------------------------------------------------------
-- threads_recovery_records — one row per enrolled account
--
-- Rows live for the lifetime of the account (graduated + retired stay so
-- the audit trail survives). The recovery agent replays them at startup
-- into its in-memory dict.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS threads_recovery_records (
    account_id                  TEXT PRIMARY KEY,
    phase                       TEXT NOT NULL,  -- cooling_down|rewarming|graduated|retired
    strikes                     INTEGER NOT NULL DEFAULT 0,
    entered_at                  TIMESTAMPTZ NOT NULL,
    cool_down_until             TIMESTAMPTZ,
    original_warmup_day         INTEGER NOT NULL DEFAULT 1,
    rewarm_baseline_replies     INTEGER NOT NULL DEFAULT 0,
    rewarm_actions_observed     INTEGER NOT NULL DEFAULT 0,
    graduated_at                TIMESTAMPTZ,
    retired_at                  TIMESTAMPTZ,
    notes                       JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_threads_recovery_by_phase
    ON threads_recovery_records (phase);


-- ---------------------------------------------------------------------------
-- threads_ig_events — cross-post bus ring, durable
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS threads_ig_events (
    event_id            BIGSERIAL PRIMARY KEY,
    ig_account_id       TEXT NOT NULL,
    post_id             TEXT NOT NULL,
    caption             TEXT NOT NULL DEFAULT '',
    source              TEXT NOT NULL DEFAULT 'manual',
    ts                  TIMESTAMPTZ NOT NULL,
    UNIQUE (ig_account_id, post_id)
);
CREATE INDEX IF NOT EXISTS idx_threads_ig_by_account
    ON threads_ig_events (ig_account_id, ts DESC);


COMMIT;
