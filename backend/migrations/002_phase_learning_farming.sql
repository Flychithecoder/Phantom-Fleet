-- Phantom Fleet migration 002
-- Adds: warmup phase columns on accounts, learning engine tables,
--       content farming tables, PPV scripts table
-- All timestamp columns use TIMESTAMPTZ. All PKs are text UUIDs.

BEGIN;

-- ---------------------------------------------------------------------------
-- Warmup phase tracking on accounts
-- ---------------------------------------------------------------------------
ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS warmup_phase       TEXT NOT NULL DEFAULT 'profile_warmup',
    ADD COLUMN IF NOT EXISTS phase_started_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS daily_follows       INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS daily_likes         INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS daily_posts         INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS daily_comments      INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS daily_reset_at      TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_accounts_phase ON accounts (warmup_phase);

-- ---------------------------------------------------------------------------
-- Learning engine — outcomes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS learning_outcomes (
    id              BIGSERIAL PRIMARY KEY,
    action_type     TEXT NOT NULL,   -- threads_post / follow / comment / reply / like
    account_id      TEXT,
    target          TEXT,            -- subreddit / hashtag / user_id / niche
    input_data      JSONB,           -- what we sent (caption, comment text, etc.)
    outcome_data    JSONB,           -- what happened (likes, reposts, ban, etc.)
    outcome_score   REAL NOT NULL DEFAULT 0.5,  -- 0–1 scale
    insights_applied JSONB,          -- array of insight IDs that were injected
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lo_action_type  ON learning_outcomes (action_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lo_account      ON learning_outcomes (account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lo_target       ON learning_outcomes (target);

-- ---------------------------------------------------------------------------
-- Learning engine — derived insights
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS learning_insights (
    id                   TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    category             TEXT NOT NULL,   -- threads_post / follow / comment / content_performance / warmup_pattern
    insight              TEXT NOT NULL,
    evidence             TEXT,
    confidence           REAL NOT NULL DEFAULT 0.5,
    times_applied        INTEGER NOT NULL DEFAULT 0,
    times_successful     INTEGER NOT NULL DEFAULT 0,
    success_rate         REAL NOT NULL DEFAULT 0.0,
    status               TEXT NOT NULL DEFAULT 'active',  -- active / deprecated
    source_analysis_date TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_li_category_status ON learning_insights (category, status, confidence DESC);

-- ---------------------------------------------------------------------------
-- Farming content (viral / AI-generated content to post)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS farming_content (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    source_platform TEXT NOT NULL DEFAULT 'ai_generated',   -- reddit / tiktok / instagram / ai_generated
    source_url      TEXT,
    source_id       TEXT,
    content_type    TEXT NOT NULL DEFAULT 'text',           -- text / image / video
    category        TEXT,                                    -- memes / lifestyle / teaser / trending / cta
    platform_target TEXT NOT NULL DEFAULT 'threads',         -- threads / instagram / reddit
    title           TEXT,                                    -- original title / prompt
    ai_caption      TEXT,                                    -- AI-generated caption (Threads-optimised)
    media_url       TEXT,                                    -- for image/video content
    engagement_score REAL NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'available',       -- available / queued / posted / archived
    expires_at      TIMESTAMPTZ,
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_platform, source_id)
);
CREATE INDEX IF NOT EXISTS idx_fc_status      ON farming_content (status, engagement_score DESC);
CREATE INDEX IF NOT EXISTS idx_fc_platform    ON farming_content (platform_target, status);
CREATE INDEX IF NOT EXISTS idx_fc_category    ON farming_content (category, status);

-- ---------------------------------------------------------------------------
-- Farming queue (content scheduled for specific accounts)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS farming_queue (
    id                  BIGSERIAL PRIMARY KEY,
    account_id          TEXT NOT NULL REFERENCES accounts(id),
    farming_content_id  TEXT REFERENCES farming_content(id),
    queue_type          TEXT NOT NULL DEFAULT 'post',        -- post / comment / reply
    platform            TEXT NOT NULL DEFAULT 'threads',
    caption             TEXT,                                -- final caption to use
    media_url           TEXT,
    target_id           TEXT,                                -- media_id / user_id to reply to
    status              TEXT NOT NULL DEFAULT 'pending',     -- pending / executing / completed / failed
    scheduled_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ,
    error               TEXT,
    result_data         JSONB
);
CREATE INDEX IF NOT EXISTS idx_fq_account_status ON farming_queue (account_id, status);
CREATE INDEX IF NOT EXISTS idx_fq_scheduled      ON farming_queue (status, scheduled_at);

-- ---------------------------------------------------------------------------
-- PPV scripts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ppv_scripts (
    id               TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    persona_id       TEXT REFERENCES personas(id),
    duration_target  TEXT NOT NULL DEFAULT '10min',
    price_point      TEXT NOT NULL DEFAULT '$30',
    hook_style       TEXT NOT NULL DEFAULT 'slow_burn',
    solo_archetype   TEXT NOT NULL DEFAULT 'raw_authentic',
    niche            TEXT,
    custom_notes     TEXT,
    script_json      JSONB NOT NULL DEFAULT '{}'::jsonb,    -- full structured script
    caption_suggestion TEXT,
    price_anchoring  TEXT,
    ppv_teaser_clip  TEXT,
    ai_model         TEXT,
    status           TEXT NOT NULL DEFAULT 'draft',         -- draft / approved / used
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ppv_persona  ON ppv_scripts (persona_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ppv_status   ON ppv_scripts (status);

COMMIT;
