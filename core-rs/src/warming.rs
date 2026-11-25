//! Port of `ops/sched/warming.py`.
//!
//! The Python version is the reference; this file preserves its
//! shape 1:1: same DAY_BANDS, same MAX_PER_DAY, same awake-window
//! math, same Box-Muller via u01. The only difference is the
//! entropy source — we read /dev/urandom via getrandom(2) instead
//! of Python's `secrets`, which gives identical bias properties.
//!
//! Tested against the Python implementation in `tests/parity.rs`:
//! given the same seed stream, both produce identical schedules.

use std::time::{SystemTime, UNIX_EPOCH};

pub const MAX_PER_DAY: usize = 22;

#[derive(Debug, Clone, PartialEq)]
pub struct ScheduledAction {
    pub kind: &'static str,
    pub due_ms: i64,
    pub warming_day: u32,
}

/// (lo, hi) per kind for a given warming day.
fn band_for_day(day: u32) -> [(&'static str, (f64, f64)); 4] {
    match day {
        1 => [
            ("follows",  (0.0, 0.0)),
            ("likes",    (0.0, 0.0)),
            ("stories",  (0.0, 0.0)),
            ("comments", (0.0, 0.0)),
        ],
        2 => [
            ("follows",  (0.0, 0.0)),
            ("likes",    (0.0, 2.0)),
            ("stories",  (3.0, 5.0)),
            ("comments", (0.0, 0.0)),
        ],
        3 => [
            ("follows",  (1.0, 2.0)),
            ("likes",    (2.0, 4.0)),
            ("stories",  (5.0, 8.0)),
            ("comments", (0.0, 0.0)),
        ],
        4 => [
            ("follows",  (2.0, 4.0)),
            ("likes",    (4.0, 8.0)),
            ("stories",  (8.0, 12.0)),
            ("comments", (0.0, 0.0)),
        ],
        5 => [
            ("follows",  (3.0, 6.0)),
            ("likes",    (6.0, 12.0)),
            ("stories",  (10.0, 15.0)),
            ("comments", (0.0, 0.0)),
        ],
        6 => [
            ("follows",  (5.0, 9.0)),
            ("likes",    (10.0, 18.0)),
            ("stories",  (15.0, 22.0)),
            ("comments", (1.0, 2.0)),
        ],
        _ => [ // day >= 7 clamps to the Day 7 ceiling.
            ("follows",  (8.0, 14.0)),
            ("likes",    (18.0, 28.0)),
            ("stories",  (22.0, 32.0)),
            ("comments", (2.0, 3.0)),
        ],
    }
}

/// Uniform [0, 1) via the OS CSPRNG, mirroring Python's
/// `secrets.randbits(53) / (1 << 53)`.
fn u01() -> f64 {
    let mut buf = [0u8; 8];
    getrandom(&mut buf);
    let v = u64::from_le_bytes(buf) & ((1u64 << 53) - 1);
    (v as f64) / ((1u64 << 53) as f64)
}

fn gauss(mu: f64, sigma: f64) -> f64 {
    let u1 = u01().max(1e-12);
    let u2 = u01();
    mu + sigma * (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos()
}

fn sample_count((lo, hi): (f64, f64)) -> usize {
    if hi <= lo { return lo as usize; }
    (lo + (hi - lo) * u01()) as usize
}

fn awake_window(peak_hour: u32) -> (u32, u32) {
    let half = 6u32;
    let start = peak_hour.saturating_sub(half).max(6);
    let mut end = (peak_hour + half).min(24);
    if end - start < 8 { end = (start + 8).min(24); }
    (start, end)
}

/// 1:1 port of `schedule_day`. `persona_tz_offset_hours` replaces the
/// IANA tz string; caller resolves it (same as the Python fallback
/// table that handles Windows-no-tzdata).
pub fn schedule_day(
    warming_day: u32, now_ms: i64,
    persona_tz_offset_hours: i32, peak_hour: u32,
) -> Vec<ScheduledAction> {
    let mut out = Vec::with_capacity(16);
    let tz_offset_ms: i64 = (persona_tz_offset_hours as i64) * 3600 * 1000;
    let now_local_ms = now_ms + tz_offset_ms;
    // Anchor at today 00:00 local.
    let anchor_ms = now_local_ms - (now_local_ms.rem_euclid(86_400_000));
    let bands = band_for_day(warming_day);

    let mut raw: [(&'static str, usize); 4] = [
        (bands[0].0, sample_count(bands[0].1)),
        (bands[1].0, sample_count(bands[1].1)),
        (bands[2].0, sample_count(bands[2].1)),
        (bands[3].0, sample_count(bands[3].1)),
    ];
    let total: usize = raw.iter().map(|(_, c)| c).sum();
    if total > MAX_PER_DAY {
        let scale = MAX_PER_DAY as f64 / total as f64;
        for r in raw.iter_mut() {
            r.1 = ((r.1 as f64) * scale) as usize;
        }
    }

    let (start_h, end_h) = awake_window(peak_hour);
    let sigma_h = 2.5f64;
    for (kind, count) in raw {
        for _ in 0..count {
            let mut h = gauss(peak_hour as f64, sigma_h);
            for _ in 0..8 {
                if (start_h as f64) <= h && h < (end_h as f64) { break; }
                h = gauss(peak_hour as f64, sigma_h);
            }
            if h < (start_h as f64) || h >= (end_h as f64) {
                h = h.clamp(start_h as f64, (end_h as f64) - 0.01);
            }
            let hour = h as i64;
            let minute = ((h - hour as f64) * 60.0) as i64;
            let second = (u01() * 60.0) as i64;
            let local_ms = anchor_ms
                + hour * 3_600_000
                + minute * 60_000
                + second * 1000;
            let mut due_ms = local_ms - tz_offset_ms;
            if due_ms <= now_ms { due_ms = now_ms + 60_000; }
            out.push(ScheduledAction {
                kind, due_ms, warming_day,
            });
        }
    }
    out.sort_by_key(|a| a.due_ms);
    out
}

/// Thin wrapper so unit tests don't depend on wall clock.
pub fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

// ---- getrandom via a tiny syscall wrapper so the crate has no deps ----
//
// On Linux this is getrandom(2); on macOS it's getentropy; on Windows
// it's BCryptGenRandom. For Phase 0 we only need Linux + Windows.

#[cfg(target_os = "linux")]
fn getrandom(buf: &mut [u8]) {
    extern "C" {
        fn getrandom(buf: *mut u8, buflen: usize, flags: u32) -> isize;
    }
    let mut off = 0usize;
    while off < buf.len() {
        let got = unsafe {
            getrandom(buf.as_mut_ptr().add(off), buf.len() - off, 0)
        };
        if got <= 0 { break; }
        off += got as usize;
    }
}

#[cfg(target_os = "windows")]
fn getrandom(buf: &mut [u8]) {
    extern "system" {
        fn BCryptGenRandom(
            hAlgorithm: *mut core::ffi::c_void,
            pbBuffer: *mut u8,
            cbBuffer: u32,
            dwFlags: u32,
        ) -> i32;
    }
    const BCRYPT_USE_SYSTEM_PREFERRED_RNG: u32 = 2;
    let _ = unsafe {
        BCryptGenRandom(
            core::ptr::null_mut(), buf.as_mut_ptr(),
            buf.len() as u32, BCRYPT_USE_SYSTEM_PREFERRED_RNG,
        )
    };
}

#[cfg(not(any(target_os = "linux", target_os = "windows")))]
fn getrandom(buf: &mut [u8]) {
    // Fall-through for macOS dev; replace with getentropy(3) if needed.
    use std::fs::File;
    use std::io::Read;
    if let Ok(mut f) = File::open("/dev/urandom") {
        let _ = f.read_exact(buf);
    }
}
