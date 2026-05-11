-- Phantom Fleet migration 003
-- Adds: groups, scraped_targets, warmup_plans,
--       scheduler_pro tables, pods, A/B tests, strategies

BEGIN;

-- ---------------------------------------------------------------------------
-- Groups (campaign / model organisation)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS groups (
    id                  TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name                TEXT NOT NULL,
    slug                TEXT,
    hq_model_id         TEXT,
    color               TEXT NOT NULL DEFAULT '#7c3aed',
    description         TEXT,
    mother_account      TEXT,
    link_in_bio         TEXT,
    bio_template        TEXT,
    sister_account_id   TEXT,
    target_accounts     JSONB NOT NULL DEFAULT '[]'::jsonb,
    target_hashtags     JSONB NOT NULL DEFAULT '[]'::jsonb,
    target_keywords     JSONB NOT NULL DEFAULT '[]'::jsonb,
    settings            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_groups_hq ON groups (hq_model_id) WHERE hq_model_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_groups_name ON groups (name);

-- Add group_id to accounts
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS group_id TEXT REFERENCES groups(id);
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS follow_count    INTEGER NOT NULL DEFAULT 0;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS follower_count  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS proxy_id        TEXT;
CREATE INDEX IF NOT EXISTS idx_accounts_group ON accounts (group_id);

-- ---------------------------------------------------------------------------
-- Scraped targets (follow-target pool from trend scraping)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scraped_targets (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id         TEXT NOT NULL,
    username        TEXT NOT NULL,
    follower_count  INTEGER NOT NULL DEFAULT 0,
    source          TEXT NOT NULL DEFAULT 'liker',   -- liker / commenter
    source_post_id  TEXT,
    source_topic    TEXT,
    group_id        TEXT REFERENCES groups(id),
    status          TEXT NOT NULL DEFAULT 'pending', -- pending/followed/converted/unfollowed/filtered
    followback      BOOLEAN,
    followed_by     TEXT,          -- account_id that followed this target
    followed_at     TIMESTAMPTZ,
    checked_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, group_id)
);
CREATE INDEX IF NOT EXISTS idx_st_status    ON scraped_targets (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_st_group     ON scraped_targets (group_id, status);
CREATE INDEX IF NOT EXISTS idx_st_followed  ON scraped_targets (followed_by, followed_at DESC);

-- ---------------------------------------------------------------------------
-- Warmup plans (day-based action limits)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warmup_plans (
    id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    account_id  TEXT NOT NULL REFERENCES accounts(id),
    start_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    last_run    TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, is_active)
);
CREATE INDEX IF NOT EXISTS idx_wp_account  ON warmup_plans (account_id);
CREATE INDEX IF NOT EXISTS idx_wp_active   ON warmup_plans (is_active) WHERE is_active = true;

-- ---------------------------------------------------------------------------
-- Scheduler Pro
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pro_schedules (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name            TEXT NOT NULL,
    group_id        TEXT REFERENCES groups(id),
    post_type       TEXT NOT NULL DEFAULT 'text',      -- text / image / carousel
    posts_per_day   INTEGER NOT NULL DEFAULT 3,
    posting_start   TEXT NOT NULL DEFAULT '09:00',
    posting_end     TEXT NOT NULL DEFAULT '22:00',
    caption_mode    TEXT NOT NULL DEFAULT 'ai',        -- ai / template / manual
    caption_template TEXT,
    vault_model     TEXT,
    status          TEXT NOT NULL DEFAULT 'active',    -- active / paused
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ps_group ON pro_schedules (group_id);

CREATE TABLE IF NOT EXISTS pro_schedule_accounts (
    id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    schedule_id TEXT NOT NULL REFERENCES pro_schedules(id) ON DELETE CASCADE,
    account_id  TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'active',
    UNIQUE (schedule_id, account_id)
);

CREATE TABLE IF NOT EXISTS pro_schedule_queue (
    id           TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    schedule_id  TEXT NOT NULL REFERENCES pro_schedules(id) ON DELETE CASCADE,
    account_id   TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    scheduled_at TIMESTAMPTZ NOT NULL,
    post_type    TEXT NOT NULL DEFAULT 'text',
    caption      TEXT,
    media_url    TEXT,
    vault_file_id TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',   -- pending / posted / failed
    posted_at    TIMESTAMPTZ,
    media_id     TEXT,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_psq_schedule  ON pro_schedule_queue (schedule_id);
CREATE INDEX IF NOT EXISTS idx_psq_account   ON pro_schedule_queue (account_id);
CREATE INDEX IF NOT EXISTS idx_psq_time      ON pro_schedule_queue (scheduled_at);
CREATE INDEX IF NOT EXISTS idx_psq_status    ON pro_schedule_queue (status);

-- ---------------------------------------------------------------------------
-- Engagement Pods
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pods (
    id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    group_id    TEXT REFERENCES groups(id),
    name        TEXT NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT true,
    like_enabled     BOOLEAN NOT NULL DEFAULT true,
    comment_enabled  BOOLEAN NOT NULL DEFAULT false,
    comment_pool     JSONB NOT NULL DEFAULT '[]'::jsonb,
    delay_min_sec    INTEGER NOT NULL DEFAULT 30,
    delay_max_sec    INTEGER NOT NULL DEFAULT 300,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pod_queue (
    id                  BIGSERIAL PRIMARY KEY,
    pod_id              TEXT NOT NULL REFERENCES pods(id),
    poster_account_id   TEXT NOT NULL,
    media_id            TEXT NOT NULL,
    engager_account_id  TEXT NOT NULL,
    action              TEXT NOT NULL DEFAULT 'like',    -- like / comment
    comment_text        TEXT,
    status              TEXT NOT NULL DEFAULT 'pending', -- pending / done / failed
    scheduled_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    done_at             TIMESTAMPTZ,
    error               TEXT
);
CREATE INDEX IF NOT EXISTS idx_pq_status   ON pod_queue (status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_pq_pod      ON pod_queue (pod_id);

-- ---------------------------------------------------------------------------
-- A/B Tests
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ab_tests (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name            TEXT NOT NULL,
    test_type       TEXT NOT NULL DEFAULT 'strategy', -- strategy/opener_style/cta_timing/custom
    status          TEXT NOT NULL DEFAULT 'draft',    -- draft / running / paused / ended
    traffic_split   INTEGER NOT NULL DEFAULT 50,      -- % going to variant A (rest to B)
    variant_a       JSONB NOT NULL DEFAULT '{}'::jsonb,
    variant_b       JSONB NOT NULL DEFAULT '{}'::jsonb,
    events_a        JSONB NOT NULL DEFAULT '{}'::jsonb,
    events_b        JSONB NOT NULL DEFAULT '{}'::jsonb,
    winner          TEXT,                              -- 'a' / 'b' / null
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Account configs (per-account AI agent settings)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account_configs (
    account_id          TEXT PRIMARY KEY REFERENCES accounts(id),
    ai_agent_enabled    BOOLEAN NOT NULL DEFAULT false,
    ai_agent_goal       TEXT,
    schedule_start      TEXT DEFAULT '09:00',
    schedule_end        TEXT DEFAULT '23:00',
    dm_enabled          BOOLEAN NOT NULL DEFAULT false,
    dm_template         TEXT,
    dm_trigger          TEXT DEFAULT 'after_follow',
    comment_enabled     BOOLEAN NOT NULL DEFAULT false,
    comment_templates   JSONB NOT NULL DEFAULT '[]'::jsonb,
    comment_ai_enabled  BOOLEAN NOT NULL DEFAULT false,
    comment_ai_prompt   TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Activity log (Threads panel style — replaces/extends action_log)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS activity_log (
    id          BIGSERIAL PRIMARY KEY,
    account_id  TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT,
    status      TEXT NOT NULL DEFAULT 'success',   -- success / failed
    message     TEXT,
    va_id       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_al_account  ON activity_log (account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_al_action   ON activity_log (action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_al_status   ON activity_log (status);

-- ---------------------------------------------------------------------------
-- Trending posts cache (for warmup likes + agent context)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trending_posts (
    id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    media_id    TEXT NOT NULL UNIQUE,
    username    TEXT,
    user_id     TEXT,
    text        TEXT,
    topic       TEXT,
    likes       INTEGER NOT NULL DEFAULT 0,
    reposts     INTEGER NOT NULL DEFAULT 0,
    replies     INTEGER NOT NULL DEFAULT 0,
    platform    TEXT NOT NULL DEFAULT 'threads',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tp_topic    ON trending_posts (topic);
CREATE INDEX IF NOT EXISTS idx_tp_likes    ON trending_posts (likes DESC);

-- ---------------------------------------------------------------------------
-- Settings KV store
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
