"""Tests for the photo verification AI system."""
import pytest

from phantom_fleet.core.photo_verification import (
    PoseCategory,
    Platform,
    ClipSegment,
    VerificationVault,
    VerificationRequest,
    PhotoVerificationOrchestrator,
    build_replay_params,
    PLATFORM_VERIFICATION_PROFILES,
    REQUIRED_POSES_PER_PLATFORM,
    MINIMUM_CLIPS_PER_POSE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_clip(clip_id: str, pose: PoseCategory) -> ClipSegment:
    return ClipSegment(
        clip_id=clip_id,
        pose=pose,
        duration_ms=2500,
        frame_count=60,
        fps=24.0,
        resolution_w=1080,
        resolution_h=1920,
        recorded_at="2026-04-11T10:00:00Z",
        storage_path=f"/vault/{clip_id}.enc",
        checksum_sha256="a" * 64,
    )


def make_full_vault(account_id: str, platform: str) -> VerificationVault:
    """Create a vault with full coverage for a platform."""
    profile = PLATFORM_VERIFICATION_PROFILES[platform]
    clips: dict[str, list[ClipSegment]] = {}
    for i, pose in enumerate(profile.poses_required):
        clips[pose.value] = [
            make_clip(f"clip_{account_id}_{pose.value}_{j}", pose)
            for j in range(MINIMUM_CLIPS_PER_POSE)
        ]
    static_selfie = f"/vault/{account_id}/selfie.enc" if platform == "grindr" else None
    return VerificationVault(
        creator_id=f"creator_{account_id}",
        platform=Platform(platform),
        consent_timestamp="2026-04-11T09:00:00Z",
        expires_at="2026-10-11T09:00:00Z",
        static_selfie_path=static_selfie,
        clips=clips,
    )


# ---------------------------------------------------------------------------
# PoseCategory coverage
# ---------------------------------------------------------------------------


def test_all_required_poses_have_enum_entries():
    """Every pose in every platform profile must be a valid PoseCategory."""
    for platform, profile in PLATFORM_VERIFICATION_PROFILES.items():
        for pose in profile.poses_required:
            assert isinstance(pose, PoseCategory), (
                f"{platform} requires pose {pose!r} which is not a PoseCategory"
            )


def test_grindr_only_needs_static_selfie():
    profile = PLATFORM_VERIFICATION_PROFILES["grindr"]
    assert profile.poses_required == [PoseCategory.STATIC_SELFIE]
    assert profile.accepts_static is True
    assert profile.liveness_strictness == "low"


def test_strict_platforms_require_multiple_poses():
    for platform in ("tinder", "bumble", "hinge"):
        profile = PLATFORM_VERIFICATION_PROFILES[platform]
        assert len(profile.poses_required) >= 3, (
            f"{platform} should require >= 3 poses for strict liveness"
        )
        assert profile.liveness_strictness == "high"
        assert profile.accepts_static is False


# ---------------------------------------------------------------------------
# Vault mechanics
# ---------------------------------------------------------------------------


def test_vault_freshest_clip_rotates():
    vault = make_full_vault("acc_001", "tinder")
    pose = PoseCategory.FACE_FORWARD
    clips = vault.available_clips(pose)
    assert len(clips) == MINIMUM_CLIPS_PER_POSE

    seen_ids = set()
    for _ in range(MINIMUM_CLIPS_PER_POSE):
        clip = vault.freshest_clip(pose)
        assert clip is not None
        seen_ids.add(clip.clip_id)
    # Should have cycled through at least 2 different clips
    assert len(seen_ids) >= 2


def test_vault_has_coverage():
    vault = make_full_vault("acc_002", "bumble")
    profile = PLATFORM_VERIFICATION_PROFILES["bumble"]
    assert vault.has_coverage(profile.poses_required)


def test_vault_missing_pose_detected():
    vault = make_full_vault("acc_003", "tinder")
    # Remove one pose
    vault.clips.pop(PoseCategory.TURN_LEFT.value, None)
    profile = PLATFORM_VERIFICATION_PROFILES["tinder"]
    assert not vault.has_coverage(profile.poses_required)


# ---------------------------------------------------------------------------
# Replay params — anti-fingerprint
# ---------------------------------------------------------------------------


def test_replay_params_deterministic():
    p1 = build_replay_params("acc_004", 1)
    p2 = build_replay_params("acc_004", 1)
    assert p1.frame_timing_jitter_ms == p2.frame_timing_jitter_ms
    assert p1.brightness_delta == p2.brightness_delta


def test_replay_params_vary_by_attempt():
    p1 = build_replay_params("acc_005", 1)
    p2 = build_replay_params("acc_005", 2)
    # Different attempts must produce different params (anti-fingerprint)
    assert p1.frame_timing_jitter_ms != p2.frame_timing_jitter_ms


def test_replay_params_within_safe_ranges():
    for i in range(10):
        p = build_replay_params(f"acc_{i:03d}", i + 1)
        assert 1.0 <= abs(p.frame_timing_jitter_ms) <= 3.0
        assert 0.01 <= abs(p.brightness_delta) <= 0.03
        assert 0.3 <= abs(p.subpixel_shift_x) <= 1.2
        assert 0.3 <= abs(p.subpixel_shift_y) <= 1.2
        assert 0.005 <= abs(p.saturation_delta) <= 0.015


def test_replay_session_ids_are_unique():
    ids = {build_replay_params("acc_999", i).session_id for i in range(20)}
    assert len(ids) == 20, "session_id must be unique per verification session"


# ---------------------------------------------------------------------------
# Orchestrator — resolve
# ---------------------------------------------------------------------------


def _make_orchestrator(accounts: list[str], platform: str) -> PhotoVerificationOrchestrator:
    vaults = {acc: make_full_vault(acc, platform) for acc in accounts}
    return PhotoVerificationOrchestrator(vaults)


def test_resolve_tinder_success():
    orch = _make_orchestrator(["acc_t01"], "tinder")
    req = VerificationRequest(
        account_id="acc_t01",
        platform="tinder",
        attempt_number=1,
        detected_poses=["look straight ahead"],
    )
    result = orch.resolve(req)
    assert result.status == "ready"
    assert result.clip_id is not None
    assert result.replay_params is not None
    assert result.delivery_url == "http://127.0.0.1:8091/camera/inject/stream"


def test_resolve_grindr_static():
    orch = _make_orchestrator(["acc_g01"], "grindr")
    req = VerificationRequest(
        account_id="acc_g01",
        platform="grindr",
        attempt_number=1,
        detected_poses=["take a selfie"],
    )
    result = orch.resolve(req)
    assert result.status == "ready"
    assert result.pose == PoseCategory.STATIC_SELFIE
    assert result.delivery_url == "http://127.0.0.1:8091/camera/inject/static"
    assert result.clip_id.startswith("static:")


def test_resolve_missing_vault():
    orch = PhotoVerificationOrchestrator({})
    req = VerificationRequest(
        account_id="does_not_exist",
        platform="tinder",
        attempt_number=1,
        detected_poses=["smile"],
    )
    result = orch.resolve(req)
    assert result.status == "missing_clip"


def test_resolve_max_attempts_exceeded():
    orch = _make_orchestrator(["acc_m01"], "hinge")
    profile = PLATFORM_VERIFICATION_PROFILES["hinge"]
    req = VerificationRequest(
        account_id="acc_m01",
        platform="hinge",
        attempt_number=profile.max_attempts + 1,
        detected_poses=["look straight ahead"],
    )
    result = orch.resolve(req)
    assert result.status == "max_attempts"


def test_resolve_unknown_platform():
    orch = PhotoVerificationOrchestrator({"acc_x": None})
    req = VerificationRequest(
        account_id="acc_x",
        platform="snapchat",
        attempt_number=1,
        detected_poses=["smile"],
    )
    result = orch.resolve(req)
    assert result.status == "missing_clip"


def test_pose_detection_all_platforms():
    """Pose resolver must map known phrases for each platform's required poses."""
    known_phrases = {
        PoseCategory.FACE_FORWARD: "look straight ahead",
        PoseCategory.TURN_LEFT:    "turn left please",
        PoseCategory.TURN_RIGHT:   "turn right please",
        PoseCategory.SMILE:        "smile for the camera",
        PoseCategory.BLINK:        "blink once",
        PoseCategory.NOD:          "nod your head",
        PoseCategory.HOLD_POSE:    "hold still",
        PoseCategory.STATIC_SELFIE: "take a selfie",
    }
    for platform, profile in PLATFORM_VERIFICATION_PROFILES.items():
        orch = _make_orchestrator([f"acc_{platform}"], platform)
        for pose in profile.poses_required:
            phrase = known_phrases.get(pose)
            if phrase is None:
                continue
            req = VerificationRequest(
                account_id=f"acc_{platform}",
                platform=platform,
                attempt_number=1,
                detected_poses=[phrase],
            )
            result = orch.resolve(req)
            assert result.status == "ready", (
                f"{platform}/{pose.value}: expected ready, got {result.status}: {result.notes}"
            )


# ---------------------------------------------------------------------------
# Vault health check
# ---------------------------------------------------------------------------


def test_vault_health_ok():
    orch = _make_orchestrator(["acc_h01"], "bumble")
    health = orch.vault_health("acc_h01")
    assert health["status"] == "ok"
    assert health["needs_recording"] is False


def test_vault_health_missing():
    orch = PhotoVerificationOrchestrator({})
    health = orch.vault_health("nobody")
    assert health["status"] == "missing"
    assert health["needs_recording"] is True


def test_vault_health_incomplete():
    vault = make_full_vault("acc_h02", "tinder")
    vault.clips.pop(PoseCategory.SMILE.value, None)
    orch = PhotoVerificationOrchestrator({"acc_h02": vault})
    health = orch.vault_health("acc_h02")
    assert health["status"] == "incomplete"
    assert health["needs_recording"] is True
    assert health["coverage"][PoseCategory.SMILE.value] == 0
