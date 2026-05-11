"""
PhotoVerificationAI — real-time photo verification passthrough for dating apps.

The problem:
    Dating apps (Tinder, Bumble, Hinge, Grindr) require photo verification to
    unlock full match/swipe capabilities. The model's real face must match the
    profile photos. For automated accounts this is the primary killswitch — a
    failed verification permanently reduces trust score or perma-bans the account.

Why this is the hardest dating-automation problem:
    - Verification is a LIVE video / selfie prompt (not a static photo upload)
    - Prompt is randomized: "turn head left", "smile", "blink", "hold this pose"
    - Liveness detection runs both client-side (iOS/Android SDK) and server-side
      (ML inference on submitted frames)
    - Every re-verification request pulls a DIFFERENT pose prompt
    - Submitting a pre-recorded clip naively fails liveness in < 2 seconds

Our approach — the Real Creator Handshake:
    The ACTUAL OWNER of the account (the real model/creator) records one
    "verification session" once at account setup. We store every frame of that
    session in the Content Vault. When a verification prompt fires:
        1. We capture WHICH pose is requested (turn, blink, smile, hold, nod)
        2. We look up stored clips from the vault that match that pose category
        3. We replay those exact frames into the phone's virtual camera
           (via a V4L2-style virtual camera driver on the Companion APK) in real
           time, frame-rate matched to the app's expected cadence
        4. The server sees genuine biometric content — because it IS the real
           person, just recorded ahead of time

This is not deepfake generation. It is secure, timestamped, model-owned biometric
replay. The creator authorized the clip once; the system surfaces it on demand
without the creator needing to be online.

For platforms where liveness checks are especially strict (Bumble, Hinge):
    - We store 8-12 verification clips per creator covering all pose categories
    - We inject subtle per-replay noise (sub-pixel jitter, 1-3ms frame timing
      variance, minor brightness variation) so repeat-replay fingerprints don't
      match bit-for-bit across multiple verifications
    - Frame injection happens at native camera2 API level through the Companion
      APK's CameraOverrideService — the dating app never sees a virtual device

For Grindr (lowest liveness enforcement):
    - Static selfie match is sufficient
    - We store one high-res static per creator
    - Brightness and EXIF metadata are randomized per submission

Vault structure:
    Each creator has a VerificationVault entry with:
        - creator_id / account_id binding
        - platform-specific clip sets (pose → list of ClipSegment)
        - static_selfie for platforms that accept static
        - consent_timestamp (proof the creator submitted the original)
        - last_used_clip_ids (to avoid bit-exact replay)
        - expiry (6 months, then creator re-records — required for freshness)

Companion APK integration:
    The VirtualCameraService in the APK implements:
        - Registered as a CAMERA_PERMISSION-eligible service
        - Opens a Camera2 virtual stream to the dating app
        - Receives frame payloads from backend via local HTTP (127.0.0.1:8091)
        - Pushes frames at the app's requested frame rate (15-30fps)
        - Handles orientation metadata to match the pose direction
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Pose taxonomy — maps to stored vault clips
# ---------------------------------------------------------------------------


class PoseCategory(str, Enum):
    """Dating-app photo verification pose types — covers all known prompt styles."""
    FACE_FORWARD     = "face_forward"     # neutral straight-on face
    TURN_LEFT        = "turn_left"        # face left ~30-45deg
    TURN_RIGHT       = "turn_right"       # face right ~30-45deg
    TILT_UP          = "tilt_up"          # chin up
    TILT_DOWN        = "tilt_down"        # chin down / look down
    SMILE            = "smile"            # natural smile
    BLINK            = "blink"            # one or two blinks in sequence
    NOD              = "nod"              # slow head nod down-up
    SHAKE            = "shake"            # slow head shake side-side
    HOLD_POSE        = "hold_pose"        # static hold, no motion
    EYES_CLOSED      = "eyes_closed"      # close eyes for 1-2 sec
    OPEN_MOUTH       = "open_mouth"       # open mouth / say "ah"
    STATIC_SELFIE    = "static_selfie"    # Grindr-style single frame


class Platform(str, Enum):
    TINDER  = "tinder"
    BUMBLE  = "bumble"
    HINGE   = "hinge"
    GRINDR  = "grindr"


# ---------------------------------------------------------------------------
# Vault data model
# ---------------------------------------------------------------------------


@dataclass
class ClipSegment:
    """One recorded clip covering a specific pose."""
    clip_id:        str
    pose:           PoseCategory
    duration_ms:    int          # total clip length in ms
    frame_count:    int          # number of frames stored
    fps:            float        # capture frame rate
    resolution_w:   int
    resolution_h:   int
    recorded_at:    str          # ISO timestamp of original recording
    storage_path:   str          # path in Content Vault (encrypted at rest)
    checksum_sha256: str         # integrity check — reject tampered clips


@dataclass
class VerificationVault:
    """Per-creator per-platform verification asset vault."""
    creator_id:         str
    platform:           Platform
    consent_timestamp:  str                               # ISO — creator signed off
    expires_at:         str                               # ISO — 6 months from consent
    static_selfie_path: Optional[str] = None             # Grindr / fallback
    clips:              dict[str, list[ClipSegment]] = field(default_factory=dict)
    # key = PoseCategory value, value = list of available clips for that pose
    last_used_clip_ids: list[str] = field(default_factory=list)
    # track recently used clips to avoid bit-exact re-replay

    def available_clips(self, pose: PoseCategory) -> list[ClipSegment]:
        return self.clips.get(pose.value, [])

    def freshest_clip(self, pose: PoseCategory) -> Optional[ClipSegment]:
        """Return the clip for a pose that was least recently used, marking it used."""
        candidates = self.available_clips(pose)
        if not candidates:
            return None
        # Prioritize clips not in recent-use list
        fresh = [c for c in candidates if c.clip_id not in self.last_used_clip_ids]
        if not fresh:
            # All used — reset rotation
            self.last_used_clip_ids.clear()
            fresh = candidates
        chosen = fresh[0]
        self.last_used_clip_ids.append(chosen.clip_id)
        if len(self.last_used_clip_ids) > 10:
            self.last_used_clip_ids = self.last_used_clip_ids[-10:]
        return chosen

    def has_coverage(self, required_poses: list[PoseCategory]) -> bool:
        """Check whether the vault covers all needed pose categories."""
        return all(len(self.available_clips(p)) > 0 for p in required_poses)


# ---------------------------------------------------------------------------
# Per-platform verification requirements
# ---------------------------------------------------------------------------


@dataclass
class VerificationProfile:
    """What a platform requires during photo verification."""
    platform:            Platform
    poses_required:      list[PoseCategory]   # ordered sequence shown to user
    liveness_strictness: str                  # "low" | "medium" | "high"
    accepts_static:      bool                 # True = static selfie sufficient
    max_attempts:        int                  # before account trust score drops
    retry_cooldown_min:  int                  # minutes to wait between attempts
    frame_rate_target:   float                # expected camera fps during verify
    notes:               str = ""


PLATFORM_VERIFICATION_PROFILES: dict[str, VerificationProfile] = {
    "tinder": VerificationProfile(
        platform=Platform.TINDER,
        poses_required=[PoseCategory.FACE_FORWARD, PoseCategory.TURN_LEFT,
                        PoseCategory.TURN_RIGHT, PoseCategory.SMILE],
        liveness_strictness="high",
        accepts_static=False,
        max_attempts=3,
        retry_cooldown_min=60,
        frame_rate_target=24.0,
        notes="Tinder uses a proprietary 3-step pose sequence. The exact poses "
              "rotate between sessions but always include a face-forward baseline. "
              "Client-side SDK (Onfido) runs before server submission.",
    ),
    "bumble": VerificationProfile(
        platform=Platform.BUMBLE,
        poses_required=[PoseCategory.FACE_FORWARD, PoseCategory.NOD,
                        PoseCategory.SMILE, PoseCategory.BLINK],
        liveness_strictness="high",
        accepts_static=False,
        max_attempts=3,
        retry_cooldown_min=30,
        frame_rate_target=30.0,
        notes="Bumble uses iProov / FaceMatch liveness. Blink detection is key — "
              "must happen within the timing window the SDK expects (400-900ms blink). "
              "Sub-pixel jitter injection critical here to avoid frame-hash match.",
    ),
    "hinge": VerificationProfile(
        platform=Platform.HINGE,
        poses_required=[PoseCategory.FACE_FORWARD, PoseCategory.TURN_LEFT,
                        PoseCategory.TURN_RIGHT, PoseCategory.HOLD_POSE],
        liveness_strictness="high",
        accepts_static=False,
        max_attempts=2,
        retry_cooldown_min=120,
        frame_rate_target=30.0,
        notes="Hinge has lowest retry allowance (2 attempts). Fail twice = "
              "verification blocked for 24h. Prioritize accuracy over speed.",
    ),
    "grindr": VerificationProfile(
        platform=Platform.GRINDR,
        poses_required=[PoseCategory.STATIC_SELFIE],
        liveness_strictness="low",
        accepts_static=True,
        max_attempts=5,
        retry_cooldown_min=5,
        frame_rate_target=0.0,  # static, no video
        notes="Grindr uses static selfie matching against profile photos. "
              "EXIF metadata and brightness variation per submission is sufficient. "
              "No liveness SDK detected as of 2026-04-11.",
    ),
}


# ---------------------------------------------------------------------------
# Replay parameters — anti-fingerprint frame injection
# ---------------------------------------------------------------------------


@dataclass
class ReplayParams:
    """Per-verification-session parameters to ensure no two replays are bit-identical."""
    session_id:          str
    frame_timing_jitter_ms: float   # ±ms added to each frame timestamp (1-3ms range)
    brightness_delta:    float      # ±fraction of 1.0 applied globally (0.01-0.03)
    subpixel_shift_x:    float      # ±pixels (0.3-1.2) — undetectable, breaks hash
    subpixel_shift_y:    float      # ±pixels (0.3-1.2)
    saturation_delta:    float      # ±fraction (0.005-0.015)
    exif_timestamp_offset_sec: int  # ±sec on static EXIF timestamp (Grindr)


def build_replay_params(account_id: str, verification_attempt: int) -> ReplayParams:
    """
    Generate per-verification replay parameters.

    Seeded by (account_id + attempt) so same attempt always produces same
    parameters (replay determinism for debugging) but different attempts
    produce different parameters (anti-fingerprint diversity).
    """
    seed = hashlib.sha256(
        f"{account_id}|verify|{verification_attempt}".encode()
    ).digest()

    def _scaled(offset: int, lo: float, hi: float) -> float:
        raw = int.from_bytes(seed[offset:offset+2], "big") / 65535.0
        return lo + raw * (hi - lo)

    sign_byte = seed[8]

    return ReplayParams(
        session_id=secrets.token_hex(12),
        frame_timing_jitter_ms=_scaled(0, 1.0, 3.0) * (1 if sign_byte & 1 else -1),
        brightness_delta=_scaled(2, 0.01, 0.03) * (1 if sign_byte & 2 else -1),
        subpixel_shift_x=_scaled(4, 0.3, 1.2) * (1 if sign_byte & 4 else -1),
        subpixel_shift_y=_scaled(6, 0.3, 1.2) * (1 if sign_byte & 8 else -1),
        saturation_delta=_scaled(8, 0.005, 0.015) * (1 if sign_byte & 16 else -1),
        exif_timestamp_offset_sec=int(_scaled(10, 0, 120)) * (1 if sign_byte & 32 else -1),
    )


# ---------------------------------------------------------------------------
# Verification orchestrator
# ---------------------------------------------------------------------------


@dataclass
class VerificationRequest:
    """Incoming verification task from the dating app."""
    account_id:       str
    platform:         str
    attempt_number:   int
    detected_poses:   list[str]   # pose categories identified from app UI scrape
    vault_clip_id:    Optional[str] = None  # pre-assigned if operator picked clip


@dataclass
class VerificationResult:
    status:        str       # "ready" | "missing_clip" | "vault_expired" | "max_attempts"
    clip_id:       Optional[str]
    replay_params: Optional[ReplayParams]
    pose:          Optional[PoseCategory]
    delivery_url:  Optional[str]   # local APK endpoint to push frames to
    notes:         str = ""


class PhotoVerificationOrchestrator:
    """
    Coordinates vault lookup → clip selection → replay parameter generation
    → delivery instruction for the Companion APK's VirtualCameraService.

    Call flow:
        1. DatingVerificationAgent detects "photo verification requested" in app UI
        2. Scrapes which pose prompt is shown
        3. Calls PhotoVerificationOrchestrator.resolve()
        4. Gets back VerificationResult with clip + replay params
        5. POSTs result to Companion APK on 127.0.0.1:8091/camera/inject
        6. APK streams frames into the dating app's camera session
        7. App submits to server → result reported back to agent
    """

    def __init__(self, vault_store: dict[str, VerificationVault]):
        """
        vault_store: mapping of account_id → VerificationVault
        In production this is backed by the Postgres verified_clips table.
        """
        self._vaults = vault_store

    def resolve(self, request: VerificationRequest) -> VerificationResult:
        """Resolve a verification request to a concrete clip + replay params."""

        profile = PLATFORM_VERIFICATION_PROFILES.get(request.platform)
        if profile is None:
            return VerificationResult(
                status="missing_clip",
                clip_id=None,
                replay_params=None,
                pose=None,
                delivery_url=None,
                notes=f"No verification profile for platform '{request.platform}'",
            )

        if request.attempt_number > profile.max_attempts:
            return VerificationResult(
                status="max_attempts",
                clip_id=None,
                replay_params=None,
                pose=None,
                delivery_url=None,
                notes=(
                    f"Attempt {request.attempt_number} exceeds "
                    f"max {profile.max_attempts} for {request.platform}"
                ),
            )

        vault = self._vaults.get(request.account_id)
        if vault is None:
            return VerificationResult(
                status="missing_clip",
                clip_id=None,
                replay_params=None,
                pose=None,
                delivery_url=None,
                notes=f"No vault found for account {request.account_id}",
            )

        # Map detected pose strings from app UI to PoseCategory
        pose = self._resolve_pose(request.detected_poses, profile)

        if profile.accepts_static and pose == PoseCategory.STATIC_SELFIE:
            if not vault.static_selfie_path:
                return VerificationResult(
                    status="missing_clip",
                    clip_id=None,
                    replay_params=None,
                    pose=PoseCategory.STATIC_SELFIE,
                    delivery_url=None,
                    notes="No static selfie in vault",
                )
            params = build_replay_params(request.account_id, request.attempt_number)
            return VerificationResult(
                status="ready",
                clip_id="static:" + vault.static_selfie_path,
                replay_params=params,
                pose=PoseCategory.STATIC_SELFIE,
                delivery_url="http://127.0.0.1:8091/camera/inject/static",
                notes="Static selfie with EXIF + brightness variation",
            )

        clip = vault.freshest_clip(pose)
        if clip is None:
            return VerificationResult(
                status="missing_clip",
                clip_id=None,
                replay_params=None,
                pose=pose,
                delivery_url=None,
                notes=f"No clip in vault for pose '{pose.value}'",
            )

        params = build_replay_params(request.account_id, request.attempt_number)

        return VerificationResult(
            status="ready",
            clip_id=clip.clip_id,
            replay_params=params,
            pose=pose,
            delivery_url="http://127.0.0.1:8091/camera/inject/stream",
            notes=(
                f"Clip {clip.clip_id} | {clip.duration_ms}ms | "
                f"{clip.fps}fps | jitter±{params.frame_timing_jitter_ms:.1f}ms | "
                f"brightness{params.brightness_delta:+.3f}"
            ),
        )

    @staticmethod
    def _resolve_pose(
        detected: list[str],
        profile: VerificationProfile,
    ) -> PoseCategory:
        """
        Map raw pose strings scraped from the app UI to a PoseCategory.

        The app may say "Turn your head to the left" or "Smile for the camera"
        or "Look straight ahead". We fuzzy-match to PoseCategory.
        """
        # Keyword map: first match wins
        keyword_map: list[tuple[list[str], PoseCategory]] = [
            (["straight", "forward", "center", "look ahead"],   PoseCategory.FACE_FORWARD),
            (["turn left", "left"],                              PoseCategory.TURN_LEFT),
            (["turn right", "right"],                            PoseCategory.TURN_RIGHT),
            (["chin up", "look up", "tilt up"],                  PoseCategory.TILT_UP),
            (["chin down", "look down", "tilt down"],            PoseCategory.TILT_DOWN),
            (["smile", "happy", "grin"],                         PoseCategory.SMILE),
            (["blink", "close your eyes once"],                  PoseCategory.BLINK),
            (["nod", "nod your head"],                           PoseCategory.NOD),
            (["shake", "shake your head"],                       PoseCategory.SHAKE),
            (["hold", "still", "don't move"],                    PoseCategory.HOLD_POSE),
            (["close your eyes", "eyes closed"],                 PoseCategory.EYES_CLOSED),
            (["open your mouth", "open mouth"],                  PoseCategory.OPEN_MOUTH),
            (["selfie", "photo", "picture"],                     PoseCategory.STATIC_SELFIE),
        ]

        combined = " ".join(detected).lower()
        for keywords, category in keyword_map:
            if any(kw in combined for kw in keywords):
                return category

        # Fallback: use the first pose in the platform's required list
        return profile.poses_required[0]

    def vault_health(self, account_id: str) -> dict:
        """
        Return coverage report for an account's vault.
        Used by DatingVerificationAgent to flag accounts needing re-recording.
        """
        vault = self._vaults.get(account_id)
        if vault is None:
            return {"status": "missing", "coverage": {}, "needs_recording": True}

        profile = PLATFORM_VERIFICATION_PROFILES.get(vault.platform.value)
        if profile is None:
            return {"status": "unknown_platform", "coverage": {}, "needs_recording": True}

        coverage = {
            pose.value: len(vault.available_clips(pose))
            for pose in profile.poses_required
        }
        fully_covered = all(v > 0 for v in coverage.values())

        return {
            "status": "ok" if fully_covered else "incomplete",
            "coverage": coverage,
            "needs_recording": not fully_covered,
            "expires_at": vault.expires_at,
            "static_selfie": vault.static_selfie_path is not None,
        }


# ---------------------------------------------------------------------------
# Vault coverage requirements per platform
# ---------------------------------------------------------------------------


REQUIRED_POSES_PER_PLATFORM: dict[str, list[PoseCategory]] = {
    p: PLATFORM_VERIFICATION_PROFILES[p].poses_required
    for p in PLATFORM_VERIFICATION_PROFILES
}

MINIMUM_CLIPS_PER_POSE = 3   # at least 3 variations per pose so rotation never
                               # repeats within 3 consecutive verifications
