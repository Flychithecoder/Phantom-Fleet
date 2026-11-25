//! Scheduler kind -> APK endpoint spec. Port of
//! `ops/dispatch/_endpoints.py`.
//!
//! Verified against `companion-apk/.../http/LocalHttpServer.kt` data
//! classes (line 1059+). The APK HTTP surface, with EXACT field names:
//!
//!   POST /instagram/engage/follow        {username, clonePackage}
//!   POST /instagram/engage/unfollow      {username, clonePackage}
//!   POST /instagram/engage/like          {mediaId, clonePackage}
//!   POST /instagram/engage/comment       {mediaId, commentText, clonePackage}
//!   POST /instagram/engage/view_stories  {username, storyCount?, clonePackage}
//!   POST /instagram/engage/scroll_reels  {watchCount?, clonePackage}
//!   POST /instagram/engage/send_dm       {username, message, clonePackage}
//!   GET  /instagram/engage/check_session?clonePackage=<pkg>
//!
//! The hydrator (ops/targets/hydrator.py) writes params in PICKER shape
//! (targetUsername / mediaCode / text / usernames[]). We translate here
//! so the APK contract and the picker contract stay independent.

use serde_json::{Map, Value};

/// Picker-shape key -> APK-shape key, per endpoint.
fn picker_to_apk(key: &str) -> &str {
    match key {
        "targetUsername" => "username",
        "mediaCode" => "mediaId",
        "text" => "commentText",
        other => other,
    }
}

// Static `Value` constants aren't const-constructible pre-serde_json 2,
// so we return a fresh `EndpointSpec` built per lookup.
pub fn spec_for_kind(kind: &str) -> Option<EndpointSpec> {
    match kind {
        "follow" | "follows" => Some(EndpointSpec {
            method: "POST",
            path: "/instagram/engage/follow",
            picker_fields: vec!["targetUsername"],
            required: vec!["targetUsername"],
            extras: vec![],
        }),
        "unfollow" => Some(EndpointSpec {
            method: "POST",
            path: "/instagram/engage/unfollow",
            picker_fields: vec!["targetUsername"],
            required: vec!["targetUsername"],
            extras: vec![],
        }),
        "like" | "likes" => Some(EndpointSpec {
            method: "POST",
            path: "/instagram/engage/like",
            picker_fields: vec!["mediaCode"],
            required: vec!["mediaCode"],
            extras: vec![],
        }),
        "comment" | "comments" => Some(EndpointSpec {
            method: "POST",
            path: "/instagram/engage/comment",
            picker_fields: vec!["mediaCode", "text"],
            required: vec!["mediaCode", "text"],
            extras: vec![],
        }),
        "story" | "stories" | "view_stories" => Some(EndpointSpec {
            // APK takes ONE username per call; picker emits a list of
            // up to 3. Dispatcher uses the first.
            method: "POST",
            path: "/instagram/engage/view_stories",
            picker_fields: vec!["usernames"],
            required: vec!["usernames"],
            extras: vec![("storyCount", Value::from(5u64))],
        }),
        "scroll_reels" => Some(EndpointSpec {
            method: "POST",
            path: "/instagram/engage/scroll_reels",
            picker_fields: vec![],
            required: vec![],
            extras: vec![("watchCount", Value::from(5u64))],
        }),
        "check_session" => Some(EndpointSpec {
            method: "GET",
            path: "/instagram/engage/check_session",
            picker_fields: vec![],
            required: vec![],
            extras: vec![],
        }),
        _ => None,
    }
}

/// Runtime variant of `Endpoint` so we can embed JSON defaults.
#[derive(Debug, Clone)]
pub struct EndpointSpec {
    pub method: &'static str,
    pub path: &'static str,
    pub picker_fields: Vec<&'static str>,
    pub required: Vec<&'static str>,
    pub extras: Vec<(&'static str, Value)>,
}

/// Convert camelCase to snake_case for the alternate-key lookup.
fn snake(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 4);
    for (i, ch) in s.chars().enumerate() {
        if ch.is_ascii_uppercase() && i > 0 {
            out.push('_');
        }
        out.push(ch.to_ascii_lowercase());
    }
    out
}

/// Return (payload, missing). If `missing` is non-empty, the payload is
/// `None` and the dispatcher must mark the row `missing_target`.
pub fn build_payload(
    endpoint: &EndpointSpec,
    clone_package: &str,
    action_params: &Value,
) -> (Option<Map<String, Value>>, Vec<String>) {
    let mut payload: Map<String, Value> = Map::new();
    payload.insert("clonePackage".to_string(), Value::String(clone_package.to_string()));
    let mut missing: Vec<String> = Vec::new();

    let params = action_params.as_object();

    for field_name in &endpoint.picker_fields {
        let val: Option<Value> = params.and_then(|p| {
            p.get(*field_name)
                .cloned()
                .or_else(|| p.get(&snake(field_name)).cloned())
        });

        let val = match val {
            Some(v) if !v.is_null() => v,
            _ => {
                if endpoint.required.contains(field_name) {
                    missing.push(field_name.to_string());
                }
                continue;
            }
        };

        // view_stories special case: APK takes one `username`, picker
        // hands us an array under `usernames`.
        if *field_name == "usernames" {
            match val {
                Value::Array(arr) if !arr.is_empty() => {
                    payload.insert("username".to_string(), arr.into_iter().next().unwrap());
                }
                Value::String(s) => {
                    payload.insert("username".to_string(), Value::String(s));
                }
                _ => missing.push(field_name.to_string()),
            }
            continue;
        }

        let apk_key = picker_to_apk(field_name);
        payload.insert(apk_key.to_string(), val);
    }

    if !missing.is_empty() {
        return (None, missing);
    }

    for (k, v) in &endpoint.extras {
        payload.entry((*k).to_string()).or_insert_with(|| v.clone());
    }

    (Some(payload), vec![])
}

/// Compact JSON encode, matching Python's `json.dumps(..., separators=(",",":"))`.
pub fn dumps(payload: &Map<String, Value>) -> Vec<u8> {
    serde_json::to_vec(&Value::Object(payload.clone())).unwrap_or_default()
}
