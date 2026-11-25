//! Dispatcher worker — port of `ops/dispatch/worker.py`.
//!
//! Reads `action_queue`, calls the companion APK's engagement endpoints
//! over HTTP, records outcomes into `action_results`. Atomic claim
//! prevents double dispatch under parallel workers.
//!
//! Deterministic at the dispatcher level; outcomes come from real phone
//! state so they aren't bit-reproducible, but every decision this
//! module makes (which row to claim, which endpoint to hit, how to
//! classify the response) is a pure function.

use anyhow::Result;
use serde::Serialize;
use serde_json::{json, Value};
use sqlx::sqlite::SqlitePool;
use std::collections::HashMap;
use std::time::{Duration, Instant};

use crate::{endpoints, outcome, store, transport};

pub const DEFAULT_CLONE_PACKAGE: &str = "com.instagram.android";
pub const PER_DEVICE_COOLDOWN_MS: i64 = 150;

#[derive(Debug, Clone, Serialize)]
pub struct Totals {
    pub claimed: usize,
    pub dispatched: usize,
    pub skipped_cooldown: usize,
    pub ok: usize,
    pub err: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct ActionResult {
    pub action_id: i64,
    pub account_id: i64,
    pub device_serial: String,
    pub kind: String,
    pub outcome: String,
    pub signal: Value,
    pub latency_ms: i64,
    pub dispatched: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct Report {
    pub now_ms: i64,
    pub apply: bool,
    pub totals: Totals,
    pub results: Vec<ActionResult>,
}

fn resolve_clone(row: &transport::ClaimedRow) -> String {
    row.clone_package
        .clone()
        .unwrap_or_else(|| DEFAULT_CLONE_PACKAGE.to_string())
}

pub async fn dispatch_one(
    pool: &SqlitePool,
    client: &reqwest::Client,
    row: &transport::ClaimedRow,
    apply: bool,
) -> ActionResult {
    let params: Value = row
        .params_json
        .as_deref()
        .and_then(|s| serde_json::from_str(s).ok())
        .unwrap_or_else(|| json!({}));
    let clone = resolve_clone(row);
    let endpoint = match endpoints::spec_for_kind(&row.kind) {
        Some(e) => e,
        None => {
            return ActionResult {
                action_id: row.id,
                account_id: row.account_id,
                device_serial: row.device_serial.clone(),
                kind: row.kind.clone(),
                outcome: "unknown".into(),
                signal: json!({"reason": "no_endpoint", "kind": row.kind}),
                latency_ms: 0,
                dispatched: false,
            };
        }
    };

    let (payload, missing) = endpoints::build_payload(&endpoint, &clone, &params);
    let payload = match payload {
        Some(p) => p,
        None => {
            return ActionResult {
                action_id: row.id,
                account_id: row.account_id,
                device_serial: row.device_serial.clone(),
                kind: row.kind.clone(),
                outcome: "missing_target".into(),
                signal: json!({"missing": missing}),
                latency_ms: 0,
                dispatched: false,
            };
        }
    };

    let ip_port = match transport::resolve_device(pool, &row.device_serial).await {
        Ok(Some(ip_port)) => ip_port,
        _ => {
            return ActionResult {
                action_id: row.id,
                account_id: row.account_id,
                device_serial: row.device_serial.clone(),
                kind: row.kind.clone(),
                outcome: "network_error".into(),
                signal: json!({
                    "reason": "no_endpoint_for_serial",
                    "serial": row.device_serial,
                }),
                latency_ms: 0,
                dispatched: false,
            };
        }
    };
    let (ip, port) = ip_port;
    let url = format!("http://{}:{}{}", ip, port, endpoint.path);

    if !apply {
        return ActionResult {
            action_id: row.id,
            account_id: row.account_id,
            device_serial: row.device_serial.clone(),
            kind: row.kind.clone(),
            outcome: "ok".into(),
            signal: json!({
                "would_dispatch": true,
                "url": url,
                "payload": payload,
            }),
            latency_ms: 0,
            dispatched: false,
        };
    }

    let body = if endpoint.method == "GET" {
        None
    } else {
        Some(endpoints::dumps(&payload))
    };
    let t0 = Instant::now();
    let resp = transport::do_request(
        client,
        endpoint.method,
        &url,
        body,
        Duration::from_secs(30),
    )
    .await;
    let latency_ms = t0.elapsed().as_millis() as i64;
    let cls = outcome::classify(resp.status, &resp.body, resp.transport_error.as_deref());
    let mut sig = cls.signal;
    if let Some(obj) = sig.as_object_mut() {
        obj.insert("status".into(), json!(resp.status));
        obj.insert("endpoint".into(), json!(endpoint.path));
    }
    ActionResult {
        action_id: row.id,
        account_id: row.account_id,
        device_serial: row.device_serial.clone(),
        kind: row.kind.clone(),
        outcome: cls.outcome,
        signal: sig,
        latency_ms,
        dispatched: true,
    }
}

pub async fn run(
    pool: &SqlitePool,
    client: &reqwest::Client,
    apply: bool,
    max_actions: i64,
    only_serial: Option<&str>,
    now_ms_override: Option<i64>,
) -> Result<Report> {
    let now_ms = now_ms_override.unwrap_or_else(store::now_ms);
    let claimed = transport::claim(pool, max_actions, now_ms).await?;
    let mut totals = Totals {
        claimed: claimed.len(),
        dispatched: 0,
        skipped_cooldown: 0,
        ok: 0,
        err: 0,
    };
    let mut last_dispatch: HashMap<String, i64> = HashMap::new();
    let mut results: Vec<ActionResult> = Vec::with_capacity(claimed.len());

    for row in claimed {
        if let Some(s) = only_serial {
            if row.device_serial != s {
                transport::release_claim(pool, row.id).await.ok();
                continue;
            }
        }
        let last = *last_dispatch.get(&row.device_serial).unwrap_or(&0);
        if now_ms - last < PER_DEVICE_COOLDOWN_MS {
            transport::release_claim(pool, row.id).await.ok();
            totals.skipped_cooldown += 1;
            continue;
        }

        let result = dispatch_one(pool, client, &row, apply).await;
        last_dispatch.insert(row.device_serial.clone(), store::now_ms());

        if apply && result.dispatched {
            store::record_result(
                pool,
                result.action_id,
                result.account_id,
                &result.outcome,
                result.latency_ms,
                &result.signal,
                store::now_ms(),
            )
            .await?;
            totals.dispatched += 1;
            if result.outcome == "ok" {
                totals.ok += 1;
            } else {
                totals.err += 1;
            }
        } else if apply
            && (result.outcome == "missing_target" || result.outcome == "unknown")
        {
            // Permanent failures that never reached HTTP: terminate so
            // they don't re-enter the queue.
            store::record_result(
                pool,
                result.action_id,
                result.account_id,
                &result.outcome,
                0,
                &result.signal,
                store::now_ms(),
            )
            .await?;
            totals.err += 1;
        } else {
            transport::release_claim(pool, row.id).await.ok();
        }
        results.push(result);
    }

    Ok(Report {
        now_ms,
        apply,
        totals,
        results,
    })
}
