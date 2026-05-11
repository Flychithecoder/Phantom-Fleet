"""
Pydantic request/response schemas for Phantom Fleet API.

Centralised here so route modules stay thin and schemas can be reused
across routes without circular imports.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Funnel sequences
# ---------------------------------------------------------------------------


class SequenceStepIn(BaseModel):
    day_offset: int = Field(..., ge=0, description="Days after enrollment to execute this step")
    action: str = Field(..., description="story_view | like_post | profile_visit | dm")
    dm_template_pool: Optional[list[str]] = Field(
        None,
        description="Required when action='dm'. Minimum 15 templates.",
    )
    condition: Optional[str] = Field(
        None,
        description="if_followed_back | if_story_viewed_back | null",
    )
    max_tokens: int = Field(100, ge=10, le=500)


class SequenceCreateIn(BaseModel):
    sequence_id: str = Field(..., min_length=1, description="Unique slug for this sequence")
    name: str = Field(..., min_length=1)
    steps: list[SequenceStepIn] = Field(..., min_length=1)
    chat_tier: int = Field(3, ge=1, le=5, description="ChatTier int value (3=FLIRTY_SFW)")


class SequenceStepOut(BaseModel):
    day_offset: int
    action: str
    condition: Optional[str]
    template_pool_size: int
    max_tokens: int


class SequenceOut(BaseModel):
    sequence_id: str
    name: str
    chat_tier: int
    step_count: int
    steps: list[SequenceStepOut]


# ---------------------------------------------------------------------------
# Funnel enrollments
# ---------------------------------------------------------------------------


class EnrollmentOut(BaseModel):
    enrollment_id: str
    account_id: str
    target_user_id: str
    sequence_id: str
    enrolled_at_iso: str
    current_step_index: int
    last_action_at_iso: Optional[str]
    completed: bool
    converted: bool


class BulkEnrollIn(BaseModel):
    account_id: str
    target_user_ids: list[str] = Field(..., min_length=1)
    sequence_id: Optional[str] = Field(
        None,
        description="Sequence to enroll into. Defaults to DEFAULT_OFM_SEQUENCE.",
    )


class BulkEnrollOut(BaseModel):
    enrolled_count: int
    enrollment_ids: list[str]
    duplicate_skips: int
    errors: list[str]


# ---------------------------------------------------------------------------
# Funnel stats
# ---------------------------------------------------------------------------


class FunnelStatsOut(BaseModel):
    total_enrolled: int
    total_completed: int
    total_converted: int
    conversion_rate: float
    step_completion_rate: float
    by_sequence: dict[str, dict]
