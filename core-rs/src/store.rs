//! SQLite schema bring-up — subset of `ops/sched/_store.py` needed by
//! the dispatcher hot path. We only create tables the dispatcher reads
//! or writes, not the whole scheduler universe; the Python side owns
//! the authoritative migrations.

use anyhow::Result;
use sqlx::sqlite::{SqliteConnectOptions, SqlitePool, SqlitePoolOptions};
use std::path::Path;

const DISPATCHER_SCHEMA: &[&str] = &[
    "CREATE TABLE IF NOT EXISTS personas (
        name TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        settings_json TEXT,
        imported_at_ms INTEGER NOT NULL
    );",
    "CREATE TABLE IF NOT EXISTS devices (
        serial TEXT PRIMARY KEY,
        model TEXT, region TEXT,
        source TEXT NOT NULL,
        imported_at_ms INTEGER NOT NULL
    );",
    "CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        persona TEXT,
        device_serial TEXT,
        status TEXT NOT NULL DEFAULT 'unknown',
        imported_at_ms INTEGER NOT NULL
    );",
    "CREATE TABLE IF NOT EXISTS action_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        due_ms INTEGER NOT NULL,
        params_json TEXT,
        state TEXT NOT NULL DEFAULT 'due',
        attempts INTEGER NOT NULL DEFAULT 0,
        created_ms INTEGER NOT NULL,
        claimed_ms INTEGER
    );",
    "CREATE INDEX IF NOT EXISTS ix_action_queue_due ON action_queue(state, due_ms);",
    "CREATE TABLE IF NOT EXISTS action_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_id INTEGER NOT NULL,
        account_id INTEGER NOT NULL,
        outcome TEXT NOT NULL,
        latency_ms INTEGER,
        signal_json TEXT,
        ts_ms INTEGER NOT NULL
    );",
    "CREATE TABLE IF NOT EXISTS clone_assignments (
        account_id INTEGER PRIMARY KEY,
        clone_package TEXT NOT NULL,
        assigned_ms INTEGER NOT NULL
    );",
    "CREATE TABLE IF NOT EXISTS device_endpoints (
        serial TEXT PRIMARY KEY,
        wifi_ip TEXT,
        port INTEGER NOT NULL DEFAULT 8080,
        last_seen_ms INTEGER
    );",
    "CREATE TABLE IF NOT EXISTS device_farm (
        serial TEXT PRIMARY KEY,
        farm_id TEXT NOT NULL
    );",
];

pub async fn connect(db_path: &Path) -> Result<SqlitePool> {
    if let Some(parent) = db_path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent).ok();
        }
    }
    // Pass the path directly rather than build a sqlite:// URL — on
    // Windows the backslash separators break URL parsing.
    let opts = SqliteConnectOptions::new()
        .filename(db_path)
        .create_if_missing(true)
        .foreign_keys(true);
    let pool = SqlitePoolOptions::new()
        .max_connections(4)
        .connect_with(opts)
        .await?;
    Ok(pool)
}

pub async fn apply_migrations(pool: &SqlitePool) -> Result<()> {
    for stmt in DISPATCHER_SCHEMA {
        sqlx::query(stmt).execute(pool).await?;
    }
    Ok(())
}

pub async fn record_result(
    pool: &SqlitePool,
    action_id: i64,
    account_id: i64,
    outcome: &str,
    latency_ms: i64,
    signal: &serde_json::Value,
    now_ms: i64,
) -> Result<()> {
    let sig = serde_json::to_string(signal)?;
    sqlx::query(
        "INSERT INTO action_results (action_id, account_id, outcome, latency_ms, signal_json, ts_ms)
         VALUES (?, ?, ?, ?, ?, ?)",
    )
    .bind(action_id)
    .bind(account_id)
    .bind(outcome)
    .bind(latency_ms)
    .bind(sig)
    .bind(now_ms)
    .execute(pool)
    .await?;
    let new_state = if outcome == "ok" { "done" } else { "failed" };
    sqlx::query("UPDATE action_queue SET state = ?, attempts = attempts + 1 WHERE id = ?")
        .bind(new_state)
        .bind(action_id)
        .execute(pool)
        .await?;
    Ok(())
}

pub fn now_ms() -> i64 {
    // Wallclock stamping only (allowed by the hot-path rules). Never
    // used as an input to any decision.
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}
