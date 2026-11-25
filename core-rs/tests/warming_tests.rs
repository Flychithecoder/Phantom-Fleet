use pf_core::warming;

#[test]
fn day_1_yields_zero_actions() {
    let out = warming::schedule_day(1, warming::now_ms(), -5, 14);
    assert_eq!(out.len(), 0);
}

#[test]
fn day_30_honours_cap() {
    let out = warming::schedule_day(30, warming::now_ms(), -5, 14);
    assert!(out.len() <= 22, "got {}", out.len());
}

#[test]
fn days_are_sorted() {
    let out = warming::schedule_day(5, warming::now_ms(), -5, 14);
    for pair in out.windows(2) {
        assert!(pair[0].due_ms <= pair[1].due_ms);
    }
}

#[test]
fn actions_are_in_the_future() {
    let now = warming::now_ms();
    let out = warming::schedule_day(5, now, -5, 14);
    for a in out { assert!(a.due_ms > now); }
}

#[test]
fn only_four_kinds_ever_appear() {
    let out = warming::schedule_day(7, warming::now_ms(), -5, 14);
    for a in out {
        assert!(matches!(a.kind, "follows" | "likes" | "stories" | "comments"));
    }
}
