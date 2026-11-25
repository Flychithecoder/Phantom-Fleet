"""Mission composer — moonshot #7.

Single-call pipeline that stitches the earlier moonshots into one
owner-approval card. Given a workflow + raw brief + role, returns:

    {
      go: bool,
      stop_reason: str | None,   # when go=false
      safety: {verdict, findings, ...},     # from safety_critic (#6)
      team_recommendation: {...},           # from cost_quality_router (#4)
      redaction: {applied, hits, report},   # brief_redactor
      final_brief: str,                     # the brief as it would be dispatched
      ghost_preview: {...},                 # from ghost_preview (#2)
      duration_ms: int,
    }

Pipeline:
  1. safety_critic.critique(brief)
     if verdict == block  -> stop here, go=false
  2. cost_quality_router.recommend_team(workflow, role)
  3. if team == "glm"     -> brief_redactor.redact(brief), set final_brief
     else                 -> final_brief = brief
  4. ghost_preview.preview_mission(hypothetical mid, final_brief)
  5. go = (safety.verdict != block) and (ghost_preview has no decisive
                                         conflict / pending-collision)

Every step is wrapped so one failure does not blank the card. A failed
non-critical step records {error} and the pipeline continues.
"""

from __future__ import annotations

import time
from typing import Any, Optional


def _safe(fn, *args, **kwargs) -> dict[str, Any]:
    try:
        return {"ok": True, "value": fn(*args, **kwargs)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def compose_mission(
    *,
    workflow: str,
    brief: str,
    role: Optional[str] = None,
    mission_id: str = "composer-hypothetical",
) -> dict[str, Any]:
    """Run the full mission-composer pipeline. See module docstring."""
    t0 = time.monotonic()

    if not workflow or not isinstance(workflow, str):
        raise ValueError("workflow required")
    if len(workflow) > 80:
        raise ValueError("workflow must be <=80 chars")
    if not brief or not isinstance(brief, str):
        raise ValueError("brief required")
    if len(brief) > 32_000:
        raise ValueError("brief must be <=32000 chars")

    # --- 1. safety critic ---
    from .safety_critic import critique
    safety_wrap = _safe(critique, brief)
    safety = safety_wrap["value"] if safety_wrap["ok"] else {
        "verdict": "ok",  # fail-open on critic bug so we don't block the owner
        "findings": [],
        "finding_count": 0,
        "block_count": 0,
        "warn_count": 0,
        "info_count": 0,
        "error": safety_wrap.get("error"),
    }

    if safety.get("verdict") == "block":
        return {
            "go": False,
            "stop_reason": "safety_critic verdict=block",
            "safety": safety,
            "team_recommendation": None,
            "redaction": None,
            "final_brief": None,
            "ghost_preview": None,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }

    # --- 2. route recommendation ---
    from .cost_quality_router import recommend_team
    route_wrap = _safe(recommend_team, workflow, role)
    team_recommendation = route_wrap["value"] if route_wrap["ok"] else {
        "recommended_team": "claude",
        "error": route_wrap.get("error"),
    }
    recommended_team = team_recommendation.get("recommended_team", "claude")

    # --- 3. redaction when routing to GLM ---
    redaction: dict[str, Any] = {"applied": False, "hits": 0, "report": None}
    final_brief = brief
    if recommended_team == "glm":
        try:
            from .brief_redactor import redact, redaction_report
            final_brief = redact(brief)
            report = redaction_report(brief)
            redaction = {
                "applied": True,
                "hits": report.get("total_hits", 0),
                "report": report,
            }
        except Exception as e:
            redaction = {"applied": False, "hits": 0, "error": str(e)[:300]}

    # --- 4. ghost preview on final_brief ---
    from .ghost_preview import preview_mission
    gp_wrap = _safe(preview_mission, mission_id, final_brief)
    ghost_preview = gp_wrap["value"] if gp_wrap["ok"] else {
        "error": gp_wrap.get("error"),
    }

    # --- 5. go decision ---
    stop_reasons: list[str] = []
    # ghost_preview conflicts: a non-empty "conflicts" list from scan is
    # a soft signal; pending_collisions is firmer.
    if isinstance(ghost_preview, dict):
        pc = ghost_preview.get("pending_collisions") or []
        if pc:
            stop_reasons.append(f"ghost_preview flagged {len(pc)} pending collision(s)")
    go = len(stop_reasons) == 0

    return {
        "go": go,
        "stop_reason": "; ".join(stop_reasons) if stop_reasons else None,
        "safety": safety,
        "team_recommendation": team_recommendation,
        "redaction": redaction,
        "final_brief": final_brief,
        "ghost_preview": ghost_preview,
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }
