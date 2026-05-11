"use client";

import { use } from "react";
import { Panel } from "@/components/panel";
import { Sparkline } from "@/components/sparkline";
import { Bot, Check, Zap, DollarSign, Clock, AlertCircle } from "lucide-react";

const AGENT_DESCRIPTIONS: Record<string, { role: string; tools: string[]; cadence: string; body: string }> = {
  warming: {
    role: "Daily re-wake + warmup curve orchestration",
    tools: ["db.load_accounts", "db.load_persona", "db.save_daily_plan", "db.mark_account_paused"],
    cadence: "Every morning per persona's claimed timezone",
    body: "Reads each account's current day-in-curve and samples fresh daily action targets from LogNormal ranges. Enforces the 7-day re-wake curve for dormant accounts and the 28-day fresh curve for new ones. Applies per-account personality multipliers and daily intensity rolls (no rest days, just varying intensity levels).",
  },
  fresh_target: {
    role: "Fresh unique targets per account per day",
    tools: ["db.load_approved_sources", "scraper.pull_followers", "scraper.pull_post_likers", "db.save_daily_target_slices"],
    cadence: "Every morning, one run per persona",
    body: "Pulls followers, story viewers, post likers, and post commenters from the top 20 approved sources. Applies the 90-day fleet-wide deduplication window. Filters for male US targets via the TargetFilter classifier. Slices the result into per-account daily budgets with zero cross-account overlap.",
  },
  source_discovery: {
    role: "Auto-discover female US high-engagement source accounts",
    tools: ["scraper.similar_accounts", "scraper.chain_walk", "scraper.profile_info", "db.save_candidate_source"],
    cadence: "Every 6 hours",
    body: "Continuously expands the approved source pool via IG's 'Similar Accounts' graph, follower-of-follower chains, and keyword searches. Every candidate runs through core.source_scorer for female/US classification and engagement quality. Top-scoring candidates (>65) enter the pool, premium-scoring (>85) are scraped more frequently.",
  },
  dm: {
    role: "Fan DM + OF funnel conversion",
    tools: ["phone.read_dm_inbox", "llm.generate_reply", "phone.type_message", "funnel.log_cta"],
    cadence: "Every 10 minutes per account with pending inbound",
    body: "Reads new DM threads, pulls conversation history, generates persona-voiced replies via LLM. Validates output against the banned-phrase list (no hashtags, no LLM tells, no em-dashes). Types replies with persona biometric timing (per-char LogNormal delays, 3% typo rate, natural burst/pause cadence). CTAs capped at 1 per conversation per 24h.",
  },
  fingerprint_monitor: {
    role: "Live fleet cluster detection",
    tools: ["db.load_all_accounts", "db.load_fingerprint_fields", "db.pause_cohort", "notifier.alert"],
    cadence: "Every 5 minutes",
    body: "Runs the 10-check cluster analysis from the global CLAUDE.md rule across the full fleet. Checks device model distribution, locale/TZ contradictions, timing uniformity, identifier regularity, and cross-field contradictions. Auto-pauses affected cohorts on cluster tightening. Sends alerts to the dashboard + Telegram.",
  },
};

export default function AgentDetailPage({ params }: { params: Promise<{ name: string }> }) {
  const { name } = use(params);
  const info = AGENT_DESCRIPTIONS[name] || {
    role: "Agent",
    tools: [],
    cadence: "—",
    body: "Phase 1 wires full agent detail from /api/v1/agents/:name",
  };

  return (
    <div className="space-y-8">
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Agent detail
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <Bot className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <span className="font-mono phantom-accent-text">{name}</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm">{info.role}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <Panel label="about this agent" title={info.role}>
            <p className="text-sm text-phantom-ghost leading-relaxed">{info.body}</p>
          </Panel>

          <Panel label="allowed tools" title="Tool allowlist (security gate)">
            <ul className="space-y-2">
              {info.tools.map((t) => (
                <li key={t} className="flex items-center gap-2 text-sm font-mono">
                  <Check className="w-3.5 h-3.5 text-phantom-alive" strokeWidth={2.5} />
                  <span>{t}</span>
                </li>
              ))}
              {info.tools.length === 0 && (
                <li className="text-sm text-phantom-ghost">No tool allowlist loaded yet.</li>
              )}
            </ul>
          </Panel>

          <Panel label="run history" title="Last 24 hours">
            <div className="h-32">
              <Sparkline data={[10, 14, 18, 22, 19, 25, 28, 30, 27, 32, 35, 38]} height={128} />
            </div>
          </Panel>
        </div>

        <div className="space-y-4">
          <div className="phantom-panel p-5">
            <Clock className="w-4 h-4 text-phantom-accent mb-2" strokeWidth={1.75} />
            <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">Cadence</div>
            <div className="text-sm mt-1">{info.cadence}</div>
          </div>
          <div className="phantom-panel p-5">
            <Zap className="w-4 h-4 text-phantom-accent mb-2" strokeWidth={1.75} />
            <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">Runs 24h</div>
            <div className="phantom-metric text-3xl mt-1">288</div>
          </div>
          <div className="phantom-panel p-5">
            <DollarSign className="w-4 h-4 text-phantom-accent mb-2" strokeWidth={1.75} />
            <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">Cost 24h</div>
            <div className="phantom-metric text-3xl mt-1 text-phantom-accent">$0.42</div>
          </div>
          <div className="phantom-panel p-5">
            <AlertCircle className="w-4 h-4 text-phantom-accent mb-2" strokeWidth={1.75} />
            <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">Status</div>
            <div className="text-phantom-alive text-sm mt-1 font-mono">HEALTHY · 0 errors</div>
          </div>
        </div>
      </div>
    </div>
  );
}
