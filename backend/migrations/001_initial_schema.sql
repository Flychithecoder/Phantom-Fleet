-- Phantom Fleet — initial Postgres schema
-- Apply via: psql -d phantomfleet -f 001_initial_schema.sql
--
-- All tables use UUIDv4 text PKs for easy migration and cross-system references.

BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- Farms (physical locations with N phones)
-- ---------------------------------------------------------------------------
CREATE TABLE farms (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    location_city   TEXT,
    location_state  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes           TEXT
);

-- ---------------------------------------------------------------------------
-- Phones (physical devices)
-- ---------------------------------------------------------------------------
CREATE TABLE phones (
    id                  TEXT PRIMARY KEY,
    farm_id             TEXT NOT NULL REFERENCES farms(id),
    serial              TEXT NOT NULL UNIQUE,
    model               TEXT,
    android_version     TEXT,
    locale              TEXT DEFAULT 'en-US',
    timezone            TEXT DEFAULT 'America/New_York',
    state               TEXT NOT NULL DEFAULT 'idle', -- active/idle/warming/cooldown/recovery/offline
    assigned_persona_id TEXT,
    wifi_ip             TEXT,
    last_seen_at        TIMESTAMPTZ,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_phones_farm ON phones (farm_id);
CREATE INDEX idx_phones_persona ON phones (assigned_persona_id);
CREATE INDEX idx_phones_state ON phones (state);

-- ---------------------------------------------------------------------------
-- Personas (cross-platform human characters — the core primitive)
-- ---------------------------------------------------------------------------
CREATE TABLE personas (
    id                  TEXT PRIMARY KEY,
    display_name        TEXT NOT NULL,
    gender              TEXT NOT NULL DEFAULT 'f',
    age                 INTEGER NOT NULL,
    city                TEXT NOT NULL,
    state               TEXT NOT NULL,
    country             TEXT NOT NULL DEFAULT 'US',
    locale              TEXT NOT NULL DEFAULT 'en-US',
    timezone            TEXT NOT NULL DEFAULT 'America/New_York',
    device_model        TEXT NOT NULL,
    android_version     TEXT NOT NULL,
    aggressiveness      REAL NOT NULL,
    peak_hour_local     INTEGER NOT NULL,
    active_window_start INTEGER NOT NULL,
    active_window_end   INTEGER NOT NULL,
    bio_template        TEXT DEFAULT '',
    caption_voice       TEXT DEFAULT 'casual_young_adult_texting',
    interest_topics     TEXT[] NOT NULL DEFAULT '{}',
    target_funnel       TEXT NOT NULL DEFAULT 'onlyfans',
    biometrics          JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Accounts (platform accounts under personas — N per persona)
-- ---------------------------------------------------------------------------
CREATE TABLE accounts (
    id                  TEXT PRIMARY KEY,
    persona_id          TEXT NOT NULL REFERENCES personas(id),
    platform            TEXT NOT NULL DEFAULT 'instagram', -- instagram/threads/reddit/tiktok/etc
    phone_id            TEXT REFERENCES phones(id),
    clone_package       TEXT, -- com.instagram.andrvws style cloned package name
    username            TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'imported', -- imported/warming/active/paused/dead
    curve_type          TEXT NOT NULL DEFAULT 'fresh_warmup', -- re_wake/fresh_warmup/steady
    day_in_curve        INTEGER NOT NULL DEFAULT 0,
    weekly_multiplier   REAL NOT NULL DEFAULT 1.0,
    home_state          TEXT,
    home_city           TEXT,
    credentials_ref     JSONB, -- never store raw passwords; references encrypted store
    aggressiveness      REAL NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    imported_at         TIMESTAMPTZ,
    last_action_at      TIMESTAMPTZ,
    dead_reason         TEXT,
    UNIQUE (platform, username)
);
CREATE INDEX idx_accounts_persona ON accounts (persona_id);
CREATE INDEX idx_accounts_phone ON accounts (phone_id);
CREATE INDEX idx_accounts_status ON accounts (status);

-- ---------------------------------------------------------------------------
-- Daily plans (one row per account per day with LogNormal-sampled targets)
-- ---------------------------------------------------------------------------
CREATE TABLE daily_plans (
    id                    TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    account_id            TEXT NOT NULL REFERENCES accounts(id),
    plan_date             DATE NOT NULL,
    day_in_curve          INTEGER NOT NULL,
    curve_label           TEXT,
    intensity_level       TEXT NOT NULL,
    intensity_multiplier  REAL NOT NULL,
    weekly_multiplier     REAL NOT NULL,
    persona_aggressiveness REAL NOT NULL,
    follows_target        INTEGER NOT NULL,
    likes_target          INTEGER NOT NULL,
    story_views_target    INTEGER NOT NULL,
    comments_target       INTEGER NOT NULL,
    dms_target            INTEGER NOT NULL,
    actions_executed      INTEGER NOT NULL DEFAULT 0,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, plan_date)
);
CREATE INDEX idx_daily_plans_date ON daily_plans (plan_date);

-- ---------------------------------------------------------------------------
-- Target history (90-day dedup window — no target reused fleet-wide within 90 days)
-- ---------------------------------------------------------------------------
CREATE TABLE target_history (
    id              BIGSERIAL PRIMARY KEY,
    username        TEXT NOT NULL,
    persona_id      TEXT NOT NULL,
    account_id      TEXT NOT NULL,
    action_type     TEXT NOT NULL, -- follow/like/dm/story_view/profile_visit
    targeted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    result          TEXT
);
CREATE INDEX idx_target_history_username ON target_history (username, targeted_at DESC);
CREATE INDEX idx_target_history_account ON target_history (account_id, targeted_at DESC);

-- ---------------------------------------------------------------------------
-- Approved source pool (female US high-engagement creators)
-- Maintained by SourceDiscoveryAgent, consumed by FreshTargetAgent
-- ---------------------------------------------------------------------------
CREATE TABLE source_pool (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    persona_id      TEXT NOT NULL REFERENCES personas(id),
    username        TEXT NOT NULL,
    score           REAL NOT NULL,
    tier            TEXT NOT NULL, -- rejected/approved/premium
    is_female       BOOLEAN NOT NULL,
    is_us           BOOLEAN NOT NULL,
    metrics         JSONB NOT NULL DEFAULT '{}'::jsonb,
    reasons         TEXT[] NOT NULL DEFAULT '{}',
    discovered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scored_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scraped_at TIMESTAMPTZ,
    retired_at      TIMESTAMPTZ,
    UNIQUE (persona_id, username)
);
CREATE INDEX idx_source_pool_persona_tier ON source_pool (persona_id, tier, score DESC);
CREATE INDEX idx_source_pool_active ON source_pool (tier, retired_at) WHERE retired_at IS NULL;

-- ---------------------------------------------------------------------------
-- Daily target slices (one row per (account, day) with the list of targets)
-- ---------------------------------------------------------------------------
CREATE TABLE daily_target_slices (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    slice_date      DATE NOT NULL,
    targets         TEXT[] NOT NULL, -- usernames to engage with today
    consumed_count  INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, slice_date)
);

-- ---------------------------------------------------------------------------
-- Action log (event-sourced — every agent action written BEFORE execution)
-- ---------------------------------------------------------------------------
CREATE TABLE action_log (
    id              BIGSERIAL PRIMARY KEY,
    account_id      TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    action_type     TEXT NOT NULL,
    target_username TEXT,
    phone_serial    TEXT,
    proxy_ip        TEXT,
    queued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    executed_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'queued', -- queued/executing/success/failed
    error           TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_action_log_account_date ON action_log (account_id, queued_at DESC);
CREATE INDEX idx_action_log_agent ON action_log (agent_name, queued_at DESC);

-- ---------------------------------------------------------------------------
-- Alerts raised by FingerprintMonitorAgent
-- ---------------------------------------------------------------------------
CREATE TABLE alerts (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    severity        TEXT NOT NULL, -- low/medium/high/critical
    dimension       TEXT NOT NULL,
    description     TEXT NOT NULL,
    affected_count  INTEGER NOT NULL DEFAULT 0,
    action          TEXT NOT NULL, -- monitor/pause_cohort/pause_all
    raised_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- ---------------------------------------------------------------------------
-- Funnel conversions (fan → OF/Fanvue/ScaleHer)
-- ---------------------------------------------------------------------------
CREATE TABLE conversions (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    platform        TEXT NOT NULL, -- onlyfans/fanvue/scaleher
    sub_id          TEXT,
    attributed_account_id TEXT,
    attributed_persona_id TEXT,
    amount_usd      REAL,
    converted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_conversions_persona ON conversions (attributed_persona_id, converted_at DESC);
CREATE INDEX idx_conversions_account ON conversions (attributed_account_id, converted_at DESC);

-- ---------------------------------------------------------------------------
-- Agent runs (audit log per execution)
-- ---------------------------------------------------------------------------
CREATE TABLE agent_runs (
    run_id          TEXT PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    status          TEXT NOT NULL,
    iterations      INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0,
    inputs          JSONB NOT NULL DEFAULT '{}'::jsonb,
    outputs         JSONB NOT NULL DEFAULT '{}'::jsonb,
    error           TEXT
);
CREATE INDEX idx_agent_runs_agent ON agent_runs (agent_name, started_at DESC);

COMMIT;
