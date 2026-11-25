"""Persona cohort HTTP surface — moonshot #10."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.persona_cohort import generate_cohort, generate_persona
from ...core.persona_cohort_validators import validate_persona, validate_cohort

router = APIRouter(prefix="/api/persona", tags=["persona-cohort"])


class _GenerateIn(BaseModel):
    n: int = Field(default=1, ge=1, le=10_000)


class _ValidateIn(BaseModel):
    personas: list[dict[str, Any]] = Field(..., min_length=1, max_length=10_000)


@router.post("/generate")
async def generate(body: _GenerateIn) -> dict:
    import asyncio
    try:
        return await asyncio.to_thread(generate_cohort, body.n)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/one")
async def one() -> dict:
    return generate_persona().as_dict()


@router.post("/validate")
async def validate(body: _ValidateIn) -> dict:
    return validate_cohort(body.personas)
