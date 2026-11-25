//! Port of `ops/dispatch/wire_test.py --stub`.
//!
//! Runs the SAME 8 assertions against a stub APK:
//!   1. dispatcher ran 1 row
//!   2. row got outcome='ok'
//!   3. stub got exactly 1 POST
//!   4. APK path hit (/instagram/engage/follow)
//!   5. body has clonePackage
//!   6. body has APK-shape 'username' (not 'targetUsername')
//!   7. username value is the picked target
//!   8. second row produced a decision

use pf_core::{store, worker};
use serde_json::{json, Value};
use sqlx::sqlite::SqlitePool;
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

#[derive(Debug, Clone)]
struct LogEntry {
    method: String,
    path: String,
    body: Value,
}

#[derive(Default)]
struct StubState {
    log: Vec<LogEntry>,
    fail_once: Vec<String>,
}

type SharedState = Arc<Mutex<StubState>>;

async fn stub_server(state: SharedState) -> (SocketAddr, tokio::task::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let handle = tokio::spawn(async move {
        loop {
            let (socket, _) = match listener.accept().await {
                Ok(s) => s,
                Err(_) => continue,
            };
            let s = state.clone();
            tokio::spawn(async move {
                handle_conn(socket, s).await;
            });
        }
    });
    (addr, handle)
}

async fn handle_conn(mut socket: tokio::net::TcpStream, state: SharedState) {
    let mut buf = Vec::with_capacity(4096);
    let mut tmp = [0u8; 4096];
    // Read until we have headers + any body.
    let mut headers_end = None;
    for _ in 0..16 {
        let n = match socket.read(&mut tmp).await {
            Ok(0) => break,
            Ok(n) => n,
            Err(_) => return,
        };
        buf.extend_from_slice(&tmp[..n]);
        if let Some(idx) = find_double_crlf(&buf) {
            headers_end = Some(idx);
            break;
        }
    }
    let Some(headers_end) = headers_end else { return };
    let head = &buf[..headers_end];
    let head_text = String::from_utf8_lossy(head).to_string();
    let mut lines = head_text.split("\r\n");
    let request_line = lines.next().unwrap_or("");
    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or("").to_string();
    let path = parts.next().unwrap_or("").to_string();

    let mut content_length: usize = 0;
    for line in lines {
        if let Some((k, v)) = line.split_once(':') {
            if k.trim().eq_ignore_ascii_case("content-length") {
                content_length = v.trim().parse().unwrap_or(0);
            }
        }
    }

    // Read remaining body bytes.
    let body_start = headers_end + 4;
    let mut body_bytes = buf[body_start..].to_vec();
    while body_bytes.len() < content_length {
        let n = match socket.read(&mut tmp).await {
            Ok(0) => break,
            Ok(n) => n,
            Err(_) => return,
        };
        body_bytes.extend_from_slice(&tmp[..n]);
    }
    body_bytes.truncate(content_length);
    let body_json: Value = if body_bytes.is_empty() {
        json!({})
    } else {
        serde_json::from_slice(&body_bytes).unwrap_or_else(|_| json!({"_raw": String::from_utf8_lossy(&body_bytes).to_string()}))
    };

    let (status, resp_body) = {
        let mut st = state.lock().unwrap();
        st.log.push(LogEntry {
            method: method.clone(),
            path: path.clone(),
            body: body_json.clone(),
        });

        if method == "GET" && path.starts_with("/instagram/engage/check_session") {
            (200u16, json!({"loggedIn": true, "needsReauth": false}))
        } else if method == "POST" {
            let (ok, err) = validate_apk_shape(&path, &body_json);
            if !ok {
                (400u16, json!({"error": err}))
            } else if let Some(pos) = st.fail_once.iter().position(|p| p == &path) {
                st.fail_once.remove(pos);
                (500u16, json!({"error": "stubbed transient"}))
            } else {
                (200u16, json!({"success": true}))
            }
        } else {
            (404u16, json!({"error": "unknown"}))
        }
    };

    let body_text = serde_json::to_vec(&resp_body).unwrap();
    let response = format!(
        "HTTP/1.1 {} OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        status,
        body_text.len()
    );
    let _ = socket.write_all(response.as_bytes()).await;
    let _ = socket.write_all(&body_text).await;
    let _ = socket.shutdown().await;
}

fn find_double_crlf(buf: &[u8]) -> Option<usize> {
    for i in 0..buf.len().saturating_sub(3) {
        if &buf[i..i + 4] == b"\r\n\r\n" {
            return Some(i);
        }
    }
    None
}

fn validate_apk_shape(path: &str, body: &Value) -> (bool, String) {
    let obj = match body.as_object() {
        Some(o) => o,
        None => return (false, "body not object".into()),
    };
    if obj.get("clonePackage").and_then(|v| v.as_str()).unwrap_or("").is_empty() {
        return (false, "missing clonePackage".into());
    }
    if path.ends_with("/engage/follow") || path.ends_with("/engage/unfollow") {
        if obj.get("username").and_then(|v| v.as_str()).unwrap_or("").is_empty() {
            return (false, "missing username".into());
        }
        return (true, "".into());
    }
    if path.ends_with("/engage/like") {
        if obj.get("mediaId").and_then(|v| v.as_str()).unwrap_or("").is_empty() {
            return (false, "missing mediaId".into());
        }
        return (true, "".into());
    }
    if path.ends_with("/engage/comment") {
        if obj.get("mediaId").and_then(|v| v.as_str()).unwrap_or("").is_empty() {
            return (false, "missing mediaId".into());
        }
        if obj.get("commentText").and_then(|v| v.as_str()).unwrap_or("").is_empty() {
            return (false, "missing commentText".into());
        }
        return (true, "".into());
    }
    if path.ends_with("/engage/view_stories") {
        if obj.get("username").and_then(|v| v.as_str()).unwrap_or("").is_empty() {
            return (false, "missing username".into());
        }
        return (true, "".into());
    }
    if path.ends_with("/engage/scroll_reels") {
        return (true, "".into());
    }
    (false, format!("unknown path: {}", path))
}

async fn seed_fleet(pool: &SqlitePool, port: u16) -> i64 {
    let now_ms = store::now_ms();
    sqlx::query("INSERT INTO personas (name, mode, settings_json, imported_at_ms) VALUES ('wire_p', 'warm', '{}', ?)")
        .bind(now_ms).execute(pool).await.unwrap();
    sqlx::query("INSERT INTO devices (serial, source, imported_at_ms) VALUES ('WIRE_SER', 'wire', ?)")
        .bind(now_ms).execute(pool).await.unwrap();
    sqlx::query("INSERT INTO device_farm (serial, farm_id) VALUES ('WIRE_SER', 'wireF')")
        .execute(pool).await.unwrap();
    sqlx::query("INSERT INTO accounts (id, username, persona, device_serial, status, imported_at_ms) VALUES (1, 'wire_acct', 'wire_p', 'WIRE_SER', 'alive', ?)")
        .bind(now_ms).execute(pool).await.unwrap();
    sqlx::query("INSERT INTO device_endpoints (serial, wifi_ip, port, last_seen_ms) VALUES ('WIRE_SER', '127.0.0.1', ?, ?)")
        .bind(port as i64).bind(now_ms).execute(pool).await.unwrap();
    sqlx::query("INSERT INTO clone_assignments (account_id, clone_package, assigned_ms) VALUES (1, 'com.scalerpro.phantomfleet.ig1', ?)")
        .bind(now_ms).execute(pool).await.unwrap();
    let params = json!({"targetUsername": "wire_target_account"}).to_string();
    let row = sqlx::query_scalar::<_, i64>(
        "INSERT INTO action_queue (account_id, kind, due_ms, params_json, state, created_ms) VALUES (1, 'follows', ?, ?, 'due', ?) RETURNING id",
    )
    .bind(now_ms - 1000)
    .bind(params)
    .bind(now_ms - 1000)
    .fetch_one(pool)
    .await
    .unwrap();
    row
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn wire_test_stub() {
    let state: SharedState = Arc::new(Mutex::new(StubState::default()));
    let (addr, _srv) = stub_server(state.clone()).await;

    let tmp = tempfile::tempdir().unwrap();
    let db_path = tmp.path().join("store.sqlite");
    let pool = store::connect(&db_path).await.unwrap();
    store::apply_migrations(&pool).await.unwrap();
    let qid = seed_fleet(&pool, addr.port()).await;
    println!("stub listening on {}; seeded queue row id={}", addr, qid);

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .unwrap();

    // Pass 1.
    let report = worker::run(&pool, &client, true, 5, None, None).await.unwrap();
    let results = &report.results;

    let mut passed = 0usize;
    let mut failed = 0usize;
    let mut check = |name: &str, cond: bool, info: &str| {
        let tag = if cond { "PASS" } else { "FAIL" };
        if cond {
            passed += 1;
        } else {
            failed += 1;
        }
        println!("  [{}] {:60} {}", tag, name, info);
    };

    check(
        "dispatcher ran 1 row",
        results.len() == 1,
        &format!("{:?}", report.totals),
    );
    let outcome0 = results.first().map(|r| r.outcome.as_str()).unwrap_or("");
    check(
        "row got outcome='ok'",
        outcome0 == "ok",
        &format!("{:?}", results.first().map(|r| &r.outcome)),
    );

    let posts: Vec<LogEntry> = {
        let st = state.lock().unwrap();
        st.log.iter().filter(|e| e.method == "POST").cloned().collect()
    };
    check("stub got exactly 1 POST", posts.len() == 1, &format!("{}", posts.len()));
    if let Some(p) = posts.first() {
        check(
            "APK path hit",
            p.path == "/instagram/engage/follow",
            &p.path,
        );
        let body = &p.body;
        check(
            "body has clonePackage",
            body.get("clonePackage").is_some(),
            &body.to_string(),
        );
        let has_apk_key = body.get("username").is_some();
        let has_picker_key = body.get("targetUsername").is_some();
        check(
            "body has APK-shape 'username' (not 'targetUsername')",
            has_apk_key && !has_picker_key,
            &body.to_string(),
        );
        check(
            "username value is the picked target",
            body.get("username").and_then(|v| v.as_str()) == Some("wire_target_account"),
            &body.to_string(),
        );
    }

    // Pass 2: stub a transient 500, add a second row.
    {
        let mut st = state.lock().unwrap();
        st.fail_once.push("/instagram/engage/follow".into());
    }
    let now_ms = store::now_ms();
    let params = json!({"targetUsername": "wire_target_account"}).to_string();
    sqlx::query("INSERT INTO action_queue (account_id, kind, due_ms, params_json, state, created_ms) VALUES (1, 'follows', ?, ?, 'due', ?)")
        .bind(now_ms - 1000)
        .bind(params)
        .bind(now_ms - 1000)
        .execute(&pool).await.unwrap();

    // Wait past the per-device cooldown so the second row actually
    // dispatches instead of being released for cooldown.
    tokio::time::sleep(Duration::from_millis(250)).await;
    let rep2 = worker::run(&pool, &client, true, 5, None, None).await.unwrap();
    let res2 = &rep2.results;
    let all_have_outcomes = !res2.is_empty() && res2.iter().all(|r| !r.outcome.is_empty());
    check(
        "second row produced a decision",
        all_have_outcomes,
        &format!("{:?}", res2.iter().map(|r| &r.outcome).collect::<Vec<_>>()),
    );

    println!("\n--- {} PASS / {} FAIL ---", passed, failed);
    assert_eq!(failed, 0, "wire_test_stub had {} failing assertions", failed);
}
