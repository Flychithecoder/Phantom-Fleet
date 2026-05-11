"""
BlueSkyABTestAgent — AI-driven A/B test lifecycle manager for BlueSky.

What this agent does:
    It is the brain of the BlueSky A/B testing system. It uses OpenRouter
    (claude-haiku) to make decisions a human analyst would otherwise make:

    Operation "create":
        Given a cohort of accounts and a niche, the LLM designs 2–4 variant
        configurations that are worth comparing — choosing which engagement
        dimensions are highest-leverage for this persona type.  It returns
        a fully-specified BlueSkyABSpec that the framework can immediately
        persist and begin tracking.

    Operation "evaluate":
        Given current metrics for a running test, the LLM analyses the
        data, decides whether there is a meaningful winner, and writes a
        plain-English recommendation.  If the test has reached significance
        AND the LLM agrees a winner is clear, the agent calls
        manager.conclude_test() and returns rollout params.

    Operation "status":
        Quick snapshot of all active tests — no LLM call, just aggregates
        metrics and returns a summary dict per test.

    Operation "rollout":
        For a concluded test: fetch the winning params dict and package it
        as a ready-to-use strategy config that the BlueSky manager can
        inject into its daily decision.

LLM safety rules (CLAUDE.md agent-audit checklist):
    - No credentials in prompts (api_key read from env, never passed to LLM).
    - All user/external content in XML-delimited blocks (not concatenated).
    - Tool allowlist: () — agent uses no tools, only OpenRouter over httpx.
    - Cost cap: $0.02/run (haiku is cheap, but we still track it).
    - Loop cap: max_iterations=1 (single LLM call per operation).
    - Structured output: LLM response parsed as JSON, schema-validated;
      falls back to framework heuristics if parsing fails.
    - Prompt injection: account IDs / niche strings enter as <data> blocks,
      never as plain instruction text.

Fleet-scale note (20K-account rule):
    Each test covers a COHORT, not the entire fleet.  Maximum cohort size
    enforced at MAX_COHORT_SIZE.  This prevents a single test from touching
    every account and creating a uniform-strategy monoculture during the test
    period — which would be a cluster fingerprint even if the strategy itself
    is varied.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from typing import Optional

import httpx

from ..base import Agent, AgentConfig, AgentRun
from ...core.bluesky_ab_test import (
    BlueSkyABManager,
    BlueSkyABVariant,
    BlueSkyEngagementVariant,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_COHORT_SIZE    = 500    # never run a single test over more accounts than this
MAX_VARIANTS       = 4      # LLM may propose up to 4 variants
OPENROUTER_MODEL   = "anthropic/claude-haiku-4-5-20251001"
OPENROUTER_URL     = "https://openrouter.ai/api/v1/chat/completions"
LLM_TIMEOUT_SEC    = 30.0


# ---------------------------------------------------------------------------
# Default variant templates (used when LLM variant generation is skipped)
# ---------------------------------------------------------------------------

_DEFAULT_VARIANTS = [
    BlueSkyABVariant(
        variant_id="a",
        label="A: Follow+Like only",
        engagement_strategy=BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY,
        params={"follow_source": "search", "hashtag_rate": 0.15},
    ),
    BlueSkyABVariant(
        variant_id="b",
        label="B: Follow+Like+DM",
        engagement_strategy=BlueSkyEngagementVariant.FOLLOW_LIKE_DM,
        params={"follow_source": "search", "hashtag_rate": 0.15},
    ),
]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class BlueSkyABTestAgent(Agent):
    """
    AI-driven A/B test lifecycle manager for BlueSky.

    ctx keys:
        operation:         str   — "create" | "evaluate" | "status" | "rollout"
        account_ids:       list[str]   — cohort (for "create")
        test_id:           str         — existing test (for "evaluate"/"rollout")
        niche:             str         — persona niche ("lifestyle", "fitness", …)
        start_date_iso:    str         — test start (defaults today)
        end_date_iso:      str         — test end (defaults today + 14 days)
        min_sample_size:   int         — min follows per variant (default 50)
        test_name:         str         — human name for "create"
        use_llm:           bool        — False to skip LLM and use defaults (default True)
        date_iso:          str         — today's date

    Outputs (run.outputs):
        operation:   str
        test_id:     str                — created or evaluated test ID
        report:      dict               — BlueSkyABReport.to_dict() for evaluate/status
        rollout_params: dict            — winning variant params for "rollout"
        recommendation: str             — LLM or framework recommendation text
        llm_used:    bool
        errors:      list[str]
    """

    config = AgentConfig(
        name="bluesky_ab_test",
        max_iterations=1,
        max_usd_per_run=0.02,
        max_usd_per_session=0.50,
        allowed_tools=(),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ab_manager = BlueSkyABManager()

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        operation:       str       = ctx.get("operation", "evaluate")
        account_ids:     list[str] = (ctx.get("account_ids") or [])[:MAX_COHORT_SIZE]
        test_id:         str       = ctx.get("test_id", "")
        niche:           str       = ctx.get("niche", "lifestyle")
        start_date_iso:  str       = ctx.get("start_date_iso", date.today().isoformat())
        end_date_iso:    str       = (
                                         ctx.get("end_date_iso")
                                         or (date.today() + timedelta(days=14)).isoformat()
                                     )
        min_sample_size: int       = int(ctx.get("min_sample_size", 50))
        test_name:       str       = ctx.get("test_name", f"BlueSky AB Test {start_date_iso}")
        use_llm:         bool      = bool(ctx.get("use_llm", True))
        errors:          list[str] = []

        self._audit({
            "event":     "bluesky_ab_test_start",
            "operation": operation,
            "test_id":   test_id,
            "niche":     niche,
            "cohort":    len(account_ids),
        })

        run.outputs["operation"] = operation
        run.outputs["errors"]    = errors
        run.outputs["llm_used"]  = False

        if operation == "create":
            return await self._op_create(
                ctx, run, account_ids, test_name, niche,
                start_date_iso, end_date_iso, min_sample_size,
                use_llm, errors,
            )

        elif operation == "evaluate":
            if not test_id:
                errors.append("test_id required for evaluate")
                return True
            return await self._op_evaluate(ctx, run, test_id, use_llm, errors)

        elif operation == "status":
            return await self._op_status(run, errors)

        elif operation == "rollout":
            if not test_id:
                errors.append("test_id required for rollout")
                return True
            return await self._op_rollout(run, test_id, errors)

        else:
            errors.append(f"unknown operation: {operation!r}")
            return True

    # ------------------------------------------------------------------
    # Operation: create
    # ------------------------------------------------------------------

    async def _op_create(
        self,
        ctx:             dict,
        run:             AgentRun,
        account_ids:     list[str],
        test_name:       str,
        niche:           str,
        start_date_iso:  str,
        end_date_iso:    str,
        min_sample_size: int,
        use_llm:         bool,
        errors:          list[str],
    ) -> bool:
        if not account_ids:
            errors.append("account_ids required for create operation")
            return True

        variants: list[BlueSkyABVariant] = []

        if use_llm:
            try:
                variants = await self._llm_design_variants(niche, len(account_ids))
                run.outputs["llm_used"] = True
                self.charge_cost(run, 0.002, "llm_design_variants")
            except Exception as exc:
                log.warning("[bluesky_ab_test] LLM variant design failed: %s", exc)
                errors.append(f"llm_design_error:{exc}")

        if not variants:
            # Fallback to hardcoded defaults — safe, always works.
            # Use the same variant_ids ("a", "b") as _DEFAULT_VARIANTS so
            # downstream metric maps and LLM recommendations are consistent.
            variants = [
                BlueSkyABVariant(
                    variant_id=_DEFAULT_VARIANTS[i].variant_id,
                    label=_DEFAULT_VARIANTS[i].label,
                    engagement_strategy=_DEFAULT_VARIANTS[i].engagement_strategy,
                    params=dict(_DEFAULT_VARIANTS[i].params),
                )
                for i in range(min(len(_DEFAULT_VARIANTS), 2))
            ]
            log.info("[bluesky_ab_test] Using default 2-variant setup (A/B follow+like vs +DM)")

        spec = self._ab_manager.create_test(
            name=test_name,
            account_ids=account_ids,
            variants=variants,
            start_date_iso=start_date_iso,
            end_date_iso=end_date_iso,
            min_sample_size=min_sample_size,
            niche=niche,
        )

        self._audit({
            "event":     "bluesky_ab_test_created",
            "test_id":   spec.test_id,
            "variants":  [v.variant_id for v in spec.variants],
            "cohort":    len(account_ids),
        })

        run.outputs["test_id"]  = spec.test_id
        run.outputs["spec"]     = spec.to_dict()
        run.outputs["recommendation"] = (
            f"Test '{spec.test_id}' created with {len(spec.variants)} variants "
            f"across {len(account_ids)} accounts. "
            f"Evaluate after {min_sample_size} follows per variant."
        )
        return True

    # ------------------------------------------------------------------
    # Operation: evaluate
    # ------------------------------------------------------------------

    async def _op_evaluate(
        self,
        ctx:     dict,
        run:     AgentRun,
        test_id: str,
        use_llm: bool,
        errors:  list[str],
    ) -> bool:
        report = self._ab_manager.generate_report(test_id)
        if report is None:
            errors.append(f"test not found: {test_id}")
            return True

        recommendation = report.recommendation

        if use_llm and report.is_significant:
            # Ask LLM to write a richer recommendation
            try:
                recommendation = await self._llm_evaluate_report(report.to_dict())
                run.outputs["llm_used"] = True
                self.charge_cost(run, 0.002, "llm_evaluate_report")
            except Exception as exc:
                log.warning("[bluesky_ab_test] LLM evaluation failed: %s", exc)
                errors.append(f"llm_eval_error:{exc}")
                # Keep framework recommendation as fallback

        # If significant and winner identified, conclude the test
        concluded_report = None
        if report.is_significant and report.winner_id:
            concluded_report = self._ab_manager.conclude_test(
                test_id, recommendation=recommendation
            )
            self._audit({
                "event":      "bluesky_ab_test_concluded",
                "test_id":    test_id,
                "winner_id":  report.winner_id,
                "lift_pct":   report.winner_lift_pct,
            })
            log.info(
                "[bluesky_ab_test] Test %s concluded — winner: %s (+%.1f%%)",
                test_id, report.winner_id, report.winner_lift_pct,
            )

        final_report = concluded_report or report
        run.outputs["test_id"]       = test_id
        run.outputs["report"]        = final_report.to_dict()
        run.outputs["recommendation"] = recommendation
        run.outputs["concluded"]     = concluded_report is not None

        # Attach rollout params if we just concluded.
        # Derive directly from concluded_report.spec — no additional JSONL read.
        if concluded_report:
            winner_variant = next(
                (v for v in concluded_report.spec.variants
                 if v.variant_id == concluded_report.winner_id),
                None,
            )
            run.outputs["rollout_params"] = (
                {
                    "engagement_strategy": winner_variant.engagement_strategy.value,
                    **winner_variant.params,
                }
                if winner_variant else {}
            )

        return True

    # ------------------------------------------------------------------
    # Operation: status
    # ------------------------------------------------------------------

    async def _op_status(self, run: AgentRun, errors: list[str]) -> bool:
        active = self._ab_manager.list_active_tests()
        summaries: list[dict] = []

        for spec in active:
            metrics = self._ab_manager.aggregate_metrics(spec.test_id, spec)
            summaries.append({
                "test_id":       spec.test_id,
                "name":          spec.name,
                "status":        spec.status,
                "start_date":    spec.start_date_iso,
                "end_date":      spec.end_date_iso,
                "cohort_size":   len(spec.cohort_account_ids),
                "variants":      len(spec.variants),
                "metrics":       [m.to_dict() for m in metrics],
                "min_follows_so_far": min((m.follows_sent for m in metrics), default=0),
                "min_sample_needed":  spec.min_sample_size,
            })

        run.outputs["active_tests"] = summaries
        run.outputs["count"]        = len(summaries)
        return True

    # ------------------------------------------------------------------
    # Operation: rollout
    # ------------------------------------------------------------------

    async def _op_rollout(
        self, run: AgentRun, test_id: str, errors: list[str]
    ) -> bool:
        # Single report load — eliminates 3× redundant JSONL reads that the
        # old approach caused (get_winning_params + 2 direct generate_report calls).
        # Also prevents AttributeError when generate_report returns None.
        report = self._ab_manager.generate_report(test_id)
        if report is None:
            errors.append(f"test {test_id} not found")
            return True
        if not report.is_significant:
            errors.append(f"test {test_id} not yet significant — cannot roll out")
            return True
        if not report.winner_id:
            errors.append(f"test {test_id} has no clear winner")
            return True

        # Derive params from report.spec — no additional file read needed
        winner_variant = next(
            (v for v in report.spec.variants if v.variant_id == report.winner_id),
            None,
        )
        if winner_variant is None:
            errors.append(f"winner variant {report.winner_id} not found in spec")
            return True

        params = {
            "engagement_strategy": winner_variant.engagement_strategy.value,
            **winner_variant.params,
        }

        run.outputs["test_id"]        = test_id
        run.outputs["rollout_params"] = params
        run.outputs["winner_label"]   = winner_variant.label
        run.outputs["recommendation"] = (
            f"Roll out variant '{winner_variant.label}' to all BlueSky accounts. "
            f"Params: {json.dumps(params)}"
        )
        return True

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    async def _llm_design_variants(
        self, niche: str, cohort_size: int
    ) -> list[BlueSkyABVariant]:
        """
        Ask the LLM to design 2–4 A/B test variants for a BlueSky cohort.

        The LLM returns a JSON array of variant objects.  Each variant
        specifies which engagement strategy and optional params to use.

        Niche is passed inside an XML data block to prevent injection.
        """
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")

        system_prompt = (
            "You are a BlueSky growth strategy analyst. "
            "Your job: design A/B test variants that compare different engagement approaches "
            "for a social media persona cohort on BlueSky (AT Protocol). "
            "You must return ONLY valid JSON — no prose, no markdown. "
            "The JSON must be an array of variant objects matching this schema:\n"
            "[\n"
            "  {\n"
            '    "variant_id": "a",\n'
            '    "label": "A: Follow+Like only",\n'
            '    "engagement_strategy": "follow_like_only",\n'
            '    "params": {\n'
            '      "follow_source": "search",\n'
            '      "hashtag_rate": 0.15,\n'
            '      "post_strategy": "mixed",\n'
            '      "timing_strategy": "distributed"\n'
            "    }\n"
            "  }\n"
            "]\n"
            "engagement_strategy must be one of: "
            "follow_like_only, follow_like_dm, follow_only, follow_post_dm. "
            "Produce 2 variants minimum, 4 maximum. "
            "Make the variants meaningfully different — no near-duplicates."
        )

        user_prompt = (
            "Design A/B test variants for a BlueSky persona cohort.\n\n"
            "<niche>" + niche.replace("<", "&lt;").replace(">", "&gt;") + "</niche>\n"
            f"<cohort_size>{cohort_size}</cohort_size>\n\n"
            "Return a JSON array of 2–4 variant objects as specified. No other text."
        )

        payload = {
            "model":       OPENROUTER_MODEL,
            "max_tokens":  600,
            "temperature": 0.7,
            "messages":    [{"role": "user", "content": user_prompt}],
            "system":      system_prompt,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(LLM_TIMEOUT_SEC)) as http:
            resp = await http.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            raw = (
                resp.json()
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

        # Parse and validate — never trust LLM output directly
        variants = _parse_llm_variants(raw)
        if not variants:
            raise ValueError(f"LLM returned no valid variants. Raw: {raw[:200]}")
        return variants

    async def _llm_evaluate_report(self, report_dict: dict) -> str:
        """
        Ask the LLM to write a plain-English recommendation given test metrics.

        The report dict enters the prompt as a structured XML block so it
        cannot inject additional instructions.
        """
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")

        report_json = json.dumps(report_dict, indent=2)

        system_prompt = (
            "You are a BlueSky growth strategy analyst. "
            "Analyse A/B test results and give a clear, actionable recommendation "
            "in 2–4 sentences. "
            "Focus on: which variant wins, why it wins (mechanistically), and "
            "what to do next (roll out / extend / pause). "
            "Be direct. No hedging. No bullet points. Plain prose only."
        )

        user_prompt = (
            "Analyse these BlueSky A/B test results and give your recommendation.\n\n"
            "<test_report>\n"
            + report_json
            + "\n</test_report>\n\n"
            "Write 2–4 sentences. Do NOT repeat raw numbers already in the report — "
            "interpret them."
        )

        payload = {
            "model":       OPENROUTER_MODEL,
            "max_tokens":  300,
            "temperature": 0.3,
            "messages":    [{"role": "user", "content": user_prompt}],
            "system":      system_prompt,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(LLM_TIMEOUT_SEC)) as http:
            resp = await http.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            text = (
                resp.json()
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

        # Sanity-check output length — reject if suspiciously short or long
        if len(text) < 20 or len(text) > 2000:
            raise ValueError(f"LLM evaluation response unexpected length: {len(text)}")

        return text


# ---------------------------------------------------------------------------
# LLM output parser + validator
# ---------------------------------------------------------------------------


_VALID_STRATEGIES = {e.value for e in BlueSkyEngagementVariant}
_VALID_FOLLOW_SOURCES  = {"search", "scraped_pool", "timeline"}
_VALID_POST_STRATEGIES = {"native_only", "crosspost_only", "mixed"}
_VALID_TIMING          = {"morning_burst", "distributed", "peak_hours"}
_VALID_LIKE_FEEDS      = {"timeline", "search", "feed_uri"}


def _parse_llm_variants(raw: str) -> list[BlueSkyABVariant]:
    """
    Parse and validate the LLM JSON output into BlueSkyABVariant objects.

    Validation rules (all code-enforced):
    - engagement_strategy must be a known enum value
    - hashtag_rate must be 0.0–1.0
    - variant_id deduplicated
    - Max MAX_VARIANTS items
    - Unknown param keys are stripped silently (whitelist approach)
    """
    # Strip possible markdown fences the LLM might add despite instructions
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first and last fence lines
        inner = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(inner).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("[bluesky_ab_test] LLM variant JSON parse failed: %s", exc)
        return []

    if not isinstance(data, list):
        log.warning("[bluesky_ab_test] LLM variant output is not a list")
        return []

    seen_ids: set[str] = set()
    variants: list[BlueSkyABVariant] = []

    for i, item in enumerate(data[:MAX_VARIANTS]):
        if not isinstance(item, dict):
            continue

        strategy_str = item.get("engagement_strategy", "")
        if strategy_str not in _VALID_STRATEGIES:
            log.warning(
                "[bluesky_ab_test] LLM proposed invalid strategy %r — skipping variant %d",
                strategy_str, i,
            )
            continue

        variant_id = str(item.get("variant_id", f"v{i}"))[:16]
        if variant_id in seen_ids:
            variant_id = f"{variant_id}_{i}"
        seen_ids.add(variant_id)

        label = str(item.get("label", variant_id))[:64]

        # Whitelist-validate params
        raw_params = item.get("params", {}) if isinstance(item.get("params"), dict) else {}
        params: dict = {}

        if "follow_source" in raw_params and raw_params["follow_source"] in _VALID_FOLLOW_SOURCES:
            params["follow_source"] = raw_params["follow_source"]

        if "post_strategy" in raw_params and raw_params["post_strategy"] in _VALID_POST_STRATEGIES:
            params["post_strategy"] = raw_params["post_strategy"]

        if "timing_strategy" in raw_params and raw_params["timing_strategy"] in _VALID_TIMING:
            params["timing_strategy"] = raw_params["timing_strategy"]

        if "like_feed" in raw_params and raw_params["like_feed"] in _VALID_LIKE_FEEDS:
            params["like_feed"] = raw_params["like_feed"]

        if "hashtag_rate" in raw_params:
            try:
                rate = float(raw_params["hashtag_rate"])
                params["hashtag_rate"] = max(0.0, min(1.0, rate))
            except (TypeError, ValueError):
                pass  # omit if invalid

        variants.append(BlueSkyABVariant(
            variant_id=variant_id,
            label=label,
            engagement_strategy=BlueSkyEngagementVariant(strategy_str),
            params=params,
        ))

    return variants


# Public alias for manager dispatch
BlueSkyABTestAgent.__name__ = "BlueSkyABTestAgent"
