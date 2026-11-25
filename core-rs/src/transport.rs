//! HTTP transport + device resolution + atomic queue claim.
//! Port of `ops/dispatch/_transport.py`.
//!
//! Three capabilities:
//!  1. `resolve_device` -> (ip, port) from device_endpoints.
//!  2. `do_request`     -> (status, body_bytes, transport_error).
//!  3. `claim`          -> up to `limit` action_queue rows atomically
//!     transitioned from 'due' -> 'claimed'. Prevents double dispatch
//!     when multiple workers run.

use anyhow::Result;
use serde::{Deserialize, Serialize};
use sqlx::sqlite::SqlitePool;
use sqlx::Row;
use std::time::Duration;

/// Default stale threshold: 5 minutes. A dispatch rarely exceeds the
/// per-request timeout (30 s) + overhead; anything claimed for 5
/// minutes is almost certainly orphaned by a worker crash between
/// claim and dispatch.
pub const STALE_CLAIM_MS: i64 = 5 * 60 * 1000;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClaimedRow {
    pub id: i64,
    pub account_id: i64,
    pub kind: String,
    pub due_ms: i64,
    pub params_json: Option<String>,
    pub username: String,
    pub device_serial: String,
    pub account_status: String,
    pub clone_package: Option<String>,
}

pub async fn resolve_device(pool: &SqlitePool, serial: &str) -> Result<Option<(String, i32)>> {
    let row = sqlx::query("SELECT wifi_ip, port FROM device_endpoints WHERE serial = ?")
        .bind(serial)
        .fetch_optional(pool)
        .await?;
    match row {
        Some(r) => {
            let ip: Option<String> = r.try_get("wifi_ip").ok();
            let port: i32 = r.try_get::<i32, _>("port").unwrap_or(8080);
            match ip {
                Some(ip) if !ip.is_empty() => Ok(Some((ip, port))),
                _ => Ok(None),
            }
        }
        None => Ok(None),
    }
}

#[derive(Debug, Clone)]
pub struct Response {
    pub status: u16,
    pub body: Vec<u8>,
    pub transport_error: Option<String>,
}

pub async fn do_request(
    client: &reqwest::Client,
    method: &str,
    url: &str,
    body: Option<Vec<u8>>,
    timeout: Duration,
) -> Response {
    let m = match method {
        "GET" => reqwest::Method::GET,
        "POST" => reqwest::Method::POST,
        "PUT" => reqwest::Method::PUT,
        "DELETE" => reqwest::Method::DELETE,
        _ => {
            return Response {
                status: 0,
                body: vec![],
                transport_error: Some(format!("bad_method: {}", method)),
            }
        }
    };
    let mut req = client.request(m, url).timeout(timeout);
    req = req.header("Accept", "application/json");
    if let Some(b) = body {
        req = req.header("Content-Type", "application/json").body(b);
    }
    match req.send().await {
        Ok(resp) => {
            let status = resp.status().as_u16();
            match resp.bytes().await {
                Ok(bytes) => Response {
                    status,
                    body: bytes.to_vec(),
                    transport_error: None,
                },
                Err(e) => Response {
                    status,
                    body: vec![],
                    transport_error: Some(format!("body_read: {}", e)),
                },
            }
        }
        Err(e) => {
            if e.is_timeout() {
                Response { status: 0, body: vec![], transport_error: Some("timeout".into()) }
            } else {
                Response {
                    status: 0,
                    body: vec![],
                    transport_error: Some(format!("url_error: {}", e)),
                }
            }
        }
    }
}

/// Atomically claim up to `limit` due rows. Oldest due_ms first so no
/// account is starved. Transitions them to state='claimed' under a
/// single transaction, stamping claimed_ms.
pub async fn claim(pool: &SqlitePool, limit: i64, now_ms: i64) -> Result<Vec<ClaimedRow>> {
    let mut tx = pool.begin().await?;
    let rows = sqlx::query(
        "SELECT q.id, q.account_id, q.kind, q.due_ms, q.params_json,
                a.username, a.device_serial, a.status AS account_status,
                c.clone_package
         FROM action_queue q
         JOIN accounts a ON a.id = q.account_id
         LEFT JOIN clone_assignments c ON c.account_id = q.account_id
         WHERE q.state = 'due' AND q.due_ms <= ?
           AND a.status = 'alive'
         ORDER BY q.due_ms ASC
         LIMIT ?",
    )
    .bind(now_ms)
    .bind(limit)
    .fetch_all(&mut *tx)
    .await?;

    let claimed: Vec<ClaimedRow> = rows
        .iter()
        .map(|r| ClaimedRow {
            id: r.try_get::<i64, _>("id").unwrap_or(0),
            account_id: r.try_get::<i64, _>("account_id").unwrap_or(0),
            kind: r.try_get::<String, _>("kind").unwrap_or_default(),
            due_ms: r.try_get::<i64, _>("due_ms").unwrap_or(0),
            params_json: r.try_get::<Option<String>, _>("params_json").unwrap_or(None),
            username: r.try_get::<String, _>("username").unwrap_or_default(),
            device_serial: r.try_get::<String, _>("device_serial").unwrap_or_default(),
            account_status: r.try_get::<String, _>("account_status").unwrap_or_default(),
            clone_package: r.try_get::<Option<String>, _>("clone_package").unwrap_or(None),
        })
        .collect();

    if !claimed.is_empty() {
        let placeholders = vec!["?"; claimed.len()].join(",");
        let sql = format!(
            "UPDATE action_queue SET state = 'claimed', claimed_ms = ? WHERE id IN ({})",
            placeholders
        );
        let mut q = sqlx::query(&sql).bind(now_ms);
        for r in &claimed {
            q = q.bind(r.id);
        }
        q.execute(&mut *tx).await?;
    }
    tx.commit().await?;
    Ok(claimed)
}

/// Hand a 'claimed' row back to the 'due' pool after a hard failure
/// before any result was recorded.
pub async fn release_claim(pool: &SqlitePool, action_id: i64) -> Result<()> {
    sqlx::query(
        "UPDATE action_queue SET state = 'due', claimed_ms = NULL
         WHERE id = ? AND state = 'claimed'",
    )
    .bind(action_id)
    .execute(pool)
    .await?;
    Ok(())
}

#[derive(Debug, Clone, Serialize)]
pub struct SweepReport {
    pub reset: usize,
    pub ids: Vec<i64>,
}

pub async fn sweep_stale_claims(
    pool: &SqlitePool,
    now_ms: i64,
    stale_ms: i64,
) -> Result<SweepReport> {
    let threshold = now_ms - stale_ms;
    let rows = sqlx::query(
        "SELECT id FROM action_queue
         WHERE state = 'claimed'
           AND (
               (claimed_ms IS NOT NULL AND claimed_ms < ?)
            OR (claimed_ms IS NULL     AND due_ms     < ?)
           )",
    )
    .bind(threshold)
    .bind(threshold)
    .fetch_all(pool)
    .await?;
    let ids: Vec<i64> = rows.iter().filter_map(|r| r.try_get("id").ok()).collect();
    if !ids.is_empty() {
        let placeholders = vec!["?"; ids.len()].join(",");
        let sql = format!(
            "UPDATE action_queue SET state = 'due', claimed_ms = NULL, attempts = attempts + 1
             WHERE id IN ({})",
            placeholders
        );
        let mut q = sqlx::query(&sql);
        for id in &ids {
            q = q.bind(*id);
        }
        q.execute(pool).await?;
    }
    Ok(SweepReport { reset: ids.len(), ids })
}
