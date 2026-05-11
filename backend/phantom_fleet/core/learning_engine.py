"""
Learning Engine — feedback loop for all farming actions.

Records outcomes of every action (post, comment, follow, reply), runs
periodic AI analysis across the outcome history, and produces reusable
insights that get injected into future AI prompts.

Over time this makes every generated caption, comment, and reply improve
without any manual tuning — the fleet learns what actually works.

Architecture:
    record_outcome()       — called after every agent action (async, non-blocking)
    get_learning_context() — called BEFORE AI generation to inject proven patterns
    analyze()              — run periodically (daily/weekly) to generate new insights
    get_top_insights()     — raw insight list for dashboard/monitoring

Outcome scoring (0–1):
    1.0  — exceptional (viral, many comments, direct conversion)
    0.8  — good (high likes, shares, positive signal)
    0.6  — above average
    0.5  — neutral (no signal yet — default at time of action)
    0.3  — below average
    0.1  — bad (low engagement, flagged, reported)
    0.0  — ban / account death attributable to this action

Score is set to 0.5 at action time and updated later when engagement
data is collected (or when an account dies shortly after the action).

DB tables used: learning_outcomes, learning_insights (see migration 002)
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

log = logging.getLogger("phantom_fleet.learning_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_CATEGORIES = [
    "threads_post",
    "threads_reply",
    "threads_follow",
    "instagram_post",
    "instagram_comment",
    "reddit_post",
    "reddit_comment",
    "follow_strategy",
    "content_performance",
    "warmup_pattern",
    "account_survival",
]

_ANALYSIS_WINDOW_DAYS = 30
_MIN_CONFIDENCE_FOR_INJECTION = 0.30
_MAX_INSIGHTS_PER_INJECTION = 8
_INSIGHT_DEPRECATION_DAYS = 60
_MIN_APPLIES_FOR_DEPRECATION = 10
_DEPRECATION_SUCCESS_THRESHOLD = 0.30


# ---------------------------------------------------------------------------
# Outcome recording
# ---------------------------------------------------------------------------


async def record_outcome(
    conn,
    action_type: str,
    outcome_score: float = 0.5,
    account_id: Optional[str] = None,
    target: Optional[str] = None,
    input_data: Optional[dict] = None,
    outcome_data: Optional[dict] = None,
    insights_applied: Optional[list[str]] = None,
) -> int:
    """
    Record the outcome of one agent action. Non-fatal — never raises.

    Args:
        conn:              asyncpg connection.
        action_type:       e.g. "threads_post", "follow", "reddit_comment"
        outcome_score:     0–1 float. Default 0.5 (neutral — update later).
        account_id:        Account that performed the action.
        target:            What was targeted (hashtag, user_id, subreddit).
        input_data:        Dict of what was sent (caption, comment, etc.).
        outcome_data:      Dict of what came back (likes, reposts, etc.).
        insights_applied:  IDs of insights injected into the prompt.

    Returns:
        The new outcome row ID (BIGSERIAL).
    """
    try:
        score = max(0.0, min(1.0, float(outcome_score)))
        row_id = await conn.fetchval(
            """
            INSERT INTO learning_outcomes
                (action_type, account_id, target,
                 input_data, outcome_data, outcome_score, insights_applied)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            action_type,
            account_id,
            target,
            json.dumps(input_data)  if input_data  else None,
            json.dumps(outcome_data) if outcome_data else None,
            score,
            json.dumps(insights_applied) if insights_applied else None,
        )

        # Update insight stats if any were applied
        if insights_applied:
            for insight_id in insights_applied:
                await _update_insight_stats(conn, insight_id, score)

        return row_id or 0
    except Exception as exc:
        log.warning("record_outcome failed (non-fatal): %s", exc)
        return 0


async def update_outcome_score(
    conn,
    outcome_id: int,
    new_score: float,
    outcome_data: Optional[dict] = None,
) -> None:
    """
    Update a previously-recorded outcome with actual engagement data.

    Call this when you collect post metrics (likes, replies, etc.) or
    when an account dies shortly after an action.
    """
    try:
        score = max(0.0, min(1.0, float(new_score)))
        await conn.execute(
            """
            UPDATE learning_outcomes
               SET outcome_score = $1,
                   outcome_data  = COALESCE($2::jsonb, outcome_data)
             WHERE id = $3
            """,
            score,
            json.dumps(outcome_data) if outcome_data else None,
            outcome_id,
        )
    except Exception as exc:
        log.warning("update_outcome_score failed (non-fatal): %s", exc)


async def _update_insight_stats(conn, insight_id: str, score: float) -> None:
    """Increment times_applied and conditionally times_successful."""
    try:
        await conn.execute(
            """
            UPDATE learning_insights
               SET times_applied    = times_applied + 1,
                   times_successful = CASE WHEN $1 > 0.6
                                           THEN times_successful + 1
                                           ELSE times_successful END,
                   success_rate     = CAST(
                       CASE WHEN $1 > 0.6 THEN times_successful + 1
                            ELSE times_successful END
                       AS REAL
                   ) / NULLIF(times_applied + 1, 0),
                   updated_at = now()
             WHERE id = $2
            """,
            score, insight_id,
        )
    except Exception:
        pass  # non-critical


# ---------------------------------------------------------------------------
# Insight injection (called before AI generation)
# ---------------------------------------------------------------------------


async def get_learning_context(
    conn,
    context: str,
    categories: Optional[list[str]] = None,
) -> dict:
    """
    Return prompt-injection text + insight IDs relevant to `context`.

    Args:
        conn:       asyncpg connection.
        context:    Human-readable description of what's being generated.
                    e.g. "threads post for OF creator promoting telegram funnel"
        categories: Optional explicit list of categories to query.
                    If None, inferred from context string.

    Returns:
        {
            "prompt_text": str,   # formatted block to append to system prompt
            "insight_ids": [str], # IDs of insights included (log these)
        }
    """
    try:
        if categories is None:
            categories = _infer_categories(context)

        if not categories:
            categories = ["threads_post", "content_performance"]

        placeholders = ", ".join(f"${i+1}" for i in range(len(categories)))
        insights = await conn.fetch(
            f"""
            SELECT id, category, insight, confidence, times_applied, success_rate
              FROM learning_insights
             WHERE status = 'active'
               AND category IN ({placeholders})
               AND confidence >= {_MIN_CONFIDENCE_FOR_INJECTION}
             ORDER BY (confidence * CASE WHEN times_applied > 0
                                         THEN success_rate
                                         ELSE confidence END) DESC
             LIMIT {_MAX_INSIGHTS_PER_INJECTION}
            """,
            *categories,
        )

        if not insights:
            return {"prompt_text": "", "insight_ids": []}

        total_outcomes = await conn.fetchval("SELECT COUNT(*) FROM learning_outcomes") or 0

        lines = [
            f"{i+1}. [{row['category']}] {row['insight']} "
            f"(confidence: {row['confidence']*100:.0f}%"
            + (f", success: {row['success_rate']*100:.0f}%" if row['times_applied'] > 0 else "")
            + ")"
            for i, row in enumerate(insights)
        ]

        prompt_text = (
            f"\n--- LEARNED PATTERNS (from {total_outcomes} past actions) ---\n"
            "Apply these proven insights to improve your output:\n"
            + "\n".join(lines)
            + "\n--- END LEARNED PATTERNS ---\n"
        )

        return {
            "prompt_text": prompt_text,
            "insight_ids": [row["id"] for row in insights],
        }

    except Exception as exc:
        log.warning("get_learning_context failed (non-fatal): %s", exc)
        return {"prompt_text": "", "insight_ids": []}


def _infer_categories(context: str) -> list[str]:
    """Map a context string to relevant insight categories."""
    ctx = context.lower()
    cats: list[str] = []
    if "threads" in ctx and "post" in ctx:
        cats.append("threads_post")
    if "threads" in ctx and "reply" in ctx:
        cats.append("threads_reply")
    if "threads" in ctx and "follow" in ctx:
        cats.append("threads_follow")
    if "instagram" in ctx or "ig" in ctx:
        if "post" in ctx:
            cats.append("instagram_post")
        if "comment" in ctx:
            cats.append("instagram_comment")
    if "reddit" in ctx:
        if "post" in ctx:
            cats.append("reddit_post")
        if "comment" in ctx:
            cats.append("reddit_comment")
    if "follow" in ctx:
        cats.append("follow_strategy")
    if "content" in ctx or "caption" in ctx:
        cats.append("content_performance")
    if "warmup" in ctx or "phase" in ctx:
        cats.append("warmup_pattern")
    return list(dict.fromkeys(cats))  # dedup, preserve order


# ---------------------------------------------------------------------------
# AI analysis — run daily/weekly
# ---------------------------------------------------------------------------


async def analyze(conn) -> dict:
    """
    Run a full 30-day analysis cycle:
    1. Pull all outcomes from the last 30 days
    2. Aggregate by action_type and target
    3. Send summary to Claude for pattern extraction
    4. Store new insights, update existing ones, deprecate stale ones

    Returns a summary dict with counts.
    """
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        log.warning("analyze(): OPENROUTER_API_KEY not set — skipping AI analysis")
        return {"error": "no_openrouter_key"}

    cutoff = datetime.now(timezone.utc) - timedelta(days=_ANALYSIS_WINDOW_DAYS)

    # Pull outcomes
    outcomes = await conn.fetch(
        """
        SELECT action_type, account_id, target, input_data, outcome_data, outcome_score, created_at
          FROM learning_outcomes
         WHERE created_at >= $1
         ORDER BY created_at DESC
         LIMIT 2000
        """,
        cutoff,
    )

    if not outcomes:
        return {"message": "no_outcomes", "insights_created": 0, "insights_updated": 0}

    # Aggregate
    by_type: dict = {}
    for row in outcomes:
        atype = row["action_type"]
        if atype not in by_type:
            by_type[atype] = []
        by_type[atype].append({
            "target":       row["target"],
            "input_data":   _safe_json(row["input_data"]),
            "outcome_data": _safe_json(row["outcome_data"]),
            "score":        row["outcome_score"],
        })

    summaries: dict = {}
    for atype, items in by_type.items():
        scores = [i["score"] for i in items if i["score"] is not None]
        avg_score = sum(scores) / len(scores) if scores else 0

        by_target: dict = {}
        for item in items:
            t = item["target"] or "unknown"
            if t not in by_target:
                by_target[t] = {"count": 0, "total_score": 0.0, "samples": []}
            by_target[t]["count"] += 1
            by_target[t]["total_score"] += item["score"] or 0
            if len(by_target[t]["samples"]) < 3:
                by_target[t]["samples"].append(item["input_data"])

        target_rankings = sorted(
            [
                {
                    "name":      t,
                    "count":     d["count"],
                    "avg_score": round(d["total_score"] / d["count"], 3) if d["count"] else 0,
                    "samples":   d["samples"],
                }
                for t, d in by_target.items()
            ],
            key=lambda x: x["avg_score"],
            reverse=True,
        )[:15]

        summaries[atype] = {
            "total":         len(items),
            "avg_score":     round(avg_score, 3),
            "score_dist":    {
                "excellent": sum(1 for s in scores if s >= 0.8),
                "good":      sum(1 for s in scores if 0.6 <= s < 0.8),
                "average":   sum(1 for s in scores if 0.4 <= s < 0.6),
                "poor":      sum(1 for s in scores if s < 0.4),
            },
            "top_targets":   target_rankings[:5],
        }

    # Account survival
    account_rows = await conn.fetch(
        """
        SELECT a.status, a.warmup_phase,
               COUNT(lo.id)    AS total_actions,
               AVG(lo.outcome_score) AS avg_score
          FROM accounts a
          LEFT JOIN learning_outcomes lo ON lo.account_id = a.id
         WHERE a.status IN ('active', 'paused', 'dead')
         GROUP BY a.status, a.warmup_phase
        """
    )
    survival = {
        "by_status_phase": [dict(r) for r in account_rows],
    }

    # Call Claude for insight extraction
    prompt = (
        "You are analyzing social media automation performance data for an OnlyFans creator promotion fleet. "
        "Extract specific, actionable patterns from the outcomes below. For each pattern provide: "
        "insight (specific + measurable), evidence (what data), confidence (0–1). "
        "Focus on: which content hooks drive engagement, which follow strategies work, "
        "which warmup patterns produce longest-lived accounts, which caption styles convert.\n\n"
        f"OUTCOMES BY ACTION TYPE:\n{json.dumps(summaries, indent=2)}\n\n"
        f"ACCOUNT SURVIVAL:\n{json.dumps(survival, indent=2)}\n\n"
        "Return ONLY a JSON array of insight objects with fields: "
        "category (one of " + str(VALID_CATEGORIES) + "), insight, evidence, confidence. "
        "No markdown fences, no extra text."
    )

    try:
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       "anthropic/claude-haiku-4-5-20251001",
                    "temperature": 0.4,
                    "max_tokens":  2000,
                    "messages": [
                        {"role": "system", "content": "You are a data analyst for social media automation. Return valid JSON only."},
                        {"role": "user",   "content": prompt},
                    ],
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()

        # Strip markdown fences if present
        clean = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
        insights = json.loads(clean)
        if not isinstance(insights, list):
            insights = [insights]

    except Exception as exc:
        log.error("analyze(): AI call failed: %s", exc)
        return {"error": str(exc), "outcomes_analyzed": len(outcomes)}

    # Persist insights
    now = datetime.now(timezone.utc)
    created = updated = 0

    for ins in insights:
        if not ins.get("category") or not ins.get("insight"):
            continue
        if ins["category"] not in VALID_CATEGORIES:
            continue

        confidence = max(0.0, min(1.0, float(ins.get("confidence", 0.5))))

        # Check for similar existing insight (same category)
        existing_rows = await conn.fetch(
            "SELECT id, insight, confidence FROM learning_insights WHERE category = $1 AND status = 'active'",
            ins["category"],
        )
        matched_id = None
        for ex in existing_rows:
            if _text_similarity(ex["insight"], ins["insight"]) > 0.6:
                matched_id = ex["id"]
                old_conf   = ex["confidence"]
                break

        if matched_id:
            new_conf = min(1.0, (old_conf + confidence) / 2 + 0.05)
            await conn.execute(
                """
                UPDATE learning_insights
                   SET confidence = $1, evidence = $2,
                       source_analysis_date = $3, updated_at = now()
                 WHERE id = $4
                """,
                new_conf, ins.get("evidence"), now, matched_id,
            )
            updated += 1
        else:
            await conn.execute(
                """
                INSERT INTO learning_insights (category, insight, evidence, confidence, source_analysis_date)
                VALUES ($1, $2, $3, $4, $5)
                """,
                ins["category"], ins["insight"], ins.get("evidence"), confidence, now,
            )
            created += 1

    # Deprecate stale low-performing insights
    await conn.execute(
        """
        UPDATE learning_insights
           SET status = 'deprecated'
         WHERE status = 'active'
           AND updated_at < now() - interval '{days} days'
           AND times_applied >= {min_applies}
           AND success_rate < {threshold}
        """.replace("{days}", str(_INSIGHT_DEPRECATION_DAYS))
           .replace("{min_applies}", str(_MIN_APPLIES_FOR_DEPRECATION))
           .replace("{threshold}", str(_DEPRECATION_SUCCESS_THRESHOLD))
    )

    log.info(
        "Learning analysis complete: %d outcomes → %d created, %d updated insights",
        len(outcomes), created, updated,
    )
    return {
        "outcomes_analyzed":  len(outcomes),
        "insights_created":   created,
        "insights_updated":   updated,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_json(val) -> Optional[dict]:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return {"raw": str(val)[:200]}


def _text_similarity(a: str, b: str) -> float:
    """Jaccard similarity on word bigrams — used to detect duplicate insights."""
    def bigrams(text: str) -> set:
        words = re.sub(r"[^a-z0-9\s]", "", text.lower()).split()
        bg: set[str] = set()
        for i in range(len(words) - 1):
            bg.add(f"{words[i]} {words[i+1]}")
        bg.update(w for w in words if len(w) > 4)
        return bg

    ba, bb = bigrams(a), bigrams(b)
    if not ba and not bb:
        return 1.0
    if not ba or not bb:
        return 0.0
    intersection = len(ba & bb)
    return intersection / (len(ba) + len(bb) - intersection)
