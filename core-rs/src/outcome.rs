//! HTTP response (status, body) -> outcome string the recovery state
//! machine understands. Port of `ops/dispatch/_outcome.py`.
//!
//! Outcome strings MUST match `ops/sched/recovery.py`'s rules exactly:
//!   ok, login_required, checkpoint, account_disabled, ig_rate_limited,
//!   network_error, accessibility_unbound, missing_target, unknown.

use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::{json, Value};

static CHECKPOINT: Lazy<Vec<Regex>> = Lazy::new(|| {
    vec![
        Regex::new(r"(?i)(We noticed unusual activity|Help us confirm|suspicious login)").unwrap(),
        Regex::new(r"(?i)checkpoint required").unwrap(),
    ]
});
static DISABLED: Lazy<Vec<Regex>> = Lazy::new(|| {
    vec![Regex::new(r"(?i)(Your account has been disabled|account has been disabled)").unwrap()]
});
static LOGIN: Lazy<Vec<Regex>> = Lazy::new(|| {
    vec![Regex::new(r"(?i)(login_required|session expired|please log in again)").unwrap()]
});
static RATE: Lazy<Vec<Regex>> = Lazy::new(|| {
    vec![Regex::new(r"(?i)(please wait a few minutes|rate limit|try again later)").unwrap()]
});

#[derive(Debug, Clone)]
pub struct Classified {
    pub outcome: String,
    pub signal: Value,
}

pub fn classify(status: u16, body_bytes: &[u8], transport_error: Option<&str>) -> Classified {
    if let Some(err) = transport_error {
        return Classified {
            outcome: "network_error".into(),
            signal: json!({"transport": err}),
        };
    }

    if status == 0 {
        return Classified {
            outcome: "network_error".into(),
            signal: json!({"status": status}),
        };
    }

    if status == 429 {
        return Classified {
            outcome: "ig_rate_limited".into(),
            signal: json!({"status": status}),
        };
    }
    if status == 502 || status == 503 || status == 504 {
        return Classified {
            outcome: "network_error".into(),
            signal: json!({"status": status}),
        };
    }

    let body_text = String::from_utf8_lossy(body_bytes).to_string();
    let body_json: Option<Value> = serde_json::from_slice(body_bytes).ok();

    if let Some(obj) = body_json.as_ref().and_then(|v| v.as_object()) {
        if let Some(err) = obj.get("error").and_then(|v| v.as_str()) {
            match err {
                "accessibility_unbound" => {
                    return Classified {
                        outcome: "accessibility_unbound".into(),
                        signal: json!({"error": err}),
                    }
                }
                "session_expired" | "login_required" => {
                    return Classified {
                        outcome: "login_required".into(),
                        signal: json!({"error": err}),
                    }
                }
                "checkpoint" => {
                    return Classified {
                        outcome: "checkpoint".into(),
                        signal: json!({"error": err}),
                    }
                }
                _ => {}
            }
        }
        if let Some(verdict) = obj.get("verdict").and_then(|v| v.as_str()) {
            match verdict {
                "dead" => {
                    return Classified {
                        outcome: "account_disabled".into(),
                        signal: json!({"verdict": verdict}),
                    }
                }
                "needs_reset" => {
                    return Classified {
                        outcome: "login_required".into(),
                        signal: json!({"verdict": verdict}),
                    }
                }
                "alive" => {
                    return Classified {
                        outcome: "ok".into(),
                        signal: json!({"verdict": verdict}),
                    }
                }
                _ => {}
            }
        }
    }

    for pat in CHECKPOINT.iter() {
        if let Some(m) = pat.find(&body_text) {
            return Classified {
                outcome: "checkpoint".into(),
                signal: json!({"match": m.as_str().chars().take(60).collect::<String>()}),
            };
        }
    }
    for pat in DISABLED.iter() {
        if let Some(m) = pat.find(&body_text) {
            return Classified {
                outcome: "account_disabled".into(),
                signal: json!({"match": m.as_str().chars().take(60).collect::<String>()}),
            };
        }
    }
    for pat in LOGIN.iter() {
        if let Some(m) = pat.find(&body_text) {
            return Classified {
                outcome: "login_required".into(),
                signal: json!({"match": m.as_str().chars().take(60).collect::<String>()}),
            };
        }
    }
    for pat in RATE.iter() {
        if let Some(m) = pat.find(&body_text) {
            return Classified {
                outcome: "ig_rate_limited".into(),
                signal: json!({"match": m.as_str().chars().take(60).collect::<String>()}),
            };
        }
    }

    if (200..300).contains(&status) {
        if let Some(obj) = body_json.as_ref().and_then(|v| v.as_object()) {
            if obj.get("ok") == Some(&Value::Bool(false)) {
                return Classified {
                    outcome: "unknown".into(),
                    signal: json!({"body_ok_false": true}),
                };
            }
        }
        return Classified {
            outcome: "ok".into(),
            signal: json!({"status": status}),
        };
    }
    if (400..500).contains(&status) {
        return Classified {
            outcome: "unknown".into(),
            signal: json!({"status": status, "client_error": true}),
        };
    }
    Classified {
        outcome: "unknown".into(),
        signal: json!({"status": status}),
    }
}
