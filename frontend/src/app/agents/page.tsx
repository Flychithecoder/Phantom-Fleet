"use client";

import { useCallback, useEffect, useState } from "react";
import { AgentTree, type ChiefAgent } from "@/components/agent-tree";
import { Panel } from "@/components/panel";
import { AgentFeed } from "@/components/agent-feed";
import { Bot, DollarSign, Activity, Layers, Rocket, ExternalLink, RefreshCw, Shield, Workflow, Users, Zap } from "lucide-react";

// Full agent hierarchy — Chief → 11 platform managers → specialists each
const CHIEF: ChiefAgent = {
  name: "Phantom Chief",
  status: "running",
  lastRun: "now",
  costToday: 5.69,
  managers: [
    {
      name: "instagram_mgr",
      platform: "instagram",
      status: "running",
      lastRun: "12s ago",
      costToday: 1.82,
      maxIterations: 5,
      maxUsd: 2.0,
      chatTier: "FLIRTY_SFW",
      supervisedAgents: [
        { name: "ig_warmup", role: "Daily warming curve enforcement", status: "running", lastRun: "12s ago", costToday: 0, loopCap: 5, toolsAllowed: ["adb_tap", "adb_swipe", "log_action"] },
        { name: "ig_follow", role: "Target follow / unfollow", status: "running", lastRun: "34s ago", costToday: 0, loopCap: 5, toolsAllowed: ["adb_tap", "log_action"] },
        { name: "ig_content", role: "Caption gen + post scheduling", status: "idle", lastRun: "2h ago", costToday: 1.82, loopCap: 3, toolsAllowed: ["openrouter_chat", "media_upload", "log_action"] },
        { name: "ig_dm", role: "Fan DM + OF funnel reply", status: "running", lastRun: "1m ago", costToday: 0, loopCap: 5, toolsAllowed: ["adb_tap", "openrouter_chat", "log_action"] },
      ],
    },
    {
      name: "threads_mgr",
      platform: "threads",
      status: "running",
      lastRun: "8s ago",
      costToday: 0.94,
      maxIterations: 5,
      maxUsd: 1.5,
      chatTier: "CASUAL_SFW",
      supervisedAgents: [
        { name: "threads_post", role: "Thread post + reply", status: "running", lastRun: "8s ago", costToday: 0.94, loopCap: 5, toolsAllowed: ["adb_tap", "openrouter_chat", "log_action"] },
        { name: "threads_engage", role: "Like + rethread engagement", status: "idle", lastRun: "22m ago", costToday: 0, loopCap: 5, toolsAllowed: ["adb_tap", "log_action"] },
      ],
    },
    {
      name: "reddit_mgr",
      platform: "reddit",
      status: "running",
      lastRun: "1m ago",
      costToday: 0.62,
      maxIterations: 5,
      maxUsd: 1.0,
      chatTier: "MIXED",
      supervisedAgents: [
        { name: "reddit_warmup", role: "Karma building + subreddit targeting", status: "running", lastRun: "1m ago", costToday: 0.42, loopCap: 5, toolsAllowed: ["adb_tap", "openrouter_chat", "log_action"] },
        { name: "reddit_post", role: "Targeted sub posting", status: "idle", lastRun: "4h ago", costToday: 0.20, loopCap: 3, toolsAllowed: ["adb_tap", "openrouter_chat", "media_upload", "log_action"] },
      ],
    },
    {
      name: "x_mgr",
      platform: "x",
      status: "running",
      lastRun: "45s ago",
      costToday: 0.38,
      maxIterations: 5,
      maxUsd: 1.0,
      chatTier: "FLIRTY_SFW",
      supervisedAgents: [
        { name: "x_tweet", role: "Tweet + reply cadence", status: "running", lastRun: "45s ago", costToday: 0.38, loopCap: 5, toolsAllowed: ["adb_tap", "openrouter_chat", "log_action"] },
        { name: "x_follow", role: "Targeted follow / unfollow", status: "idle", lastRun: "30m ago", costToday: 0, loopCap: 5, toolsAllowed: ["adb_tap", "log_action"] },
      ],
    },
    {
      name: "tiktok_mgr",
      platform: "tiktok",
      status: "running",
      lastRun: "2m ago",
      costToday: 0.24,
      maxIterations: 5,
      maxUsd: 1.0,
      chatTier: "CASUAL_SFW",
      supervisedAgents: [
        { name: "tt_scroll", role: "FYP scroll + like engagement", status: "running", lastRun: "2m ago", costToday: 0, loopCap: 5, toolsAllowed: ["adb_swipe", "adb_tap", "log_action"] },
        { name: "tt_post", role: "Video post + caption gen", status: "idle", lastRun: "6h ago", costToday: 0.24, loopCap: 3, toolsAllowed: ["adb_tap", "openrouter_chat", "media_upload", "log_action"] },
      ],
    },
    {
      name: "telegram_mgr",
      platform: "telegram",
      status: "idle",
      lastRun: "3h ago",
      costToday: 0.00,
      maxIterations: 5,
      maxUsd: 0.5,
      chatTier: "PROFESSIONAL",
      supervisedAgents: [
        { name: "tg_outreach", role: "Group outreach + DM", status: "idle", lastRun: "3h ago", costToday: 0, loopCap: 5, toolsAllowed: ["adb_tap", "openrouter_chat", "log_action"] },
      ],
    },
    {
      name: "discord_mgr",
      platform: "discord",
      status: "idle",
      lastRun: "5h ago",
      costToday: 0.00,
      maxIterations: 5,
      maxUsd: 0.5,
      chatTier: "CASUAL_SFW",
      supervisedAgents: [
        { name: "discord_post", role: "Server post + engagement", status: "idle", lastRun: "5h ago", costToday: 0, loopCap: 5, toolsAllowed: ["adb_tap", "openrouter_chat", "log_action"] },
      ],
    },
    {
      name: "dating_mgr",
      platform: "dating",
      status: "idle",
      lastRun: "2h ago",
      costToday: 0.00,
      maxIterations: 5,
      maxUsd: 0.5,
      chatTier: "FLIRTY_SFW",
      supervisedAgents: [
        { name: "dating_swipe", role: "Match + opener message", status: "idle", lastRun: "2h ago", costToday: 0, loopCap: 5, toolsAllowed: ["adb_tap", "adb_swipe", "openrouter_chat", "log_action"] },
      ],
    },
    {
      name: "bluesky_mgr",
      platform: "bluesky",
      status: "idle",
      lastRun: "4h ago",
      costToday: 0.00,
      maxIterations: 5,
      maxUsd: 0.5,
      chatTier: "CASUAL_SFW",
      supervisedAgents: [
        { name: "bsky_post", role: "Post + reply cadence", status: "idle", lastRun: "4h ago", costToday: 0, loopCap: 5, toolsAllowed: ["adb_tap", "openrouter_chat", "log_action"] },
      ],
    },
    {
      name: "infrastructure_mgr",
      platform: "infrastructure",
      status: "running",
      lastRun: "3s ago",
      costToday: 0.42,
      maxIterations: 10,
      maxUsd: 1.0,
      chatTier: null,
      supervisedAgents: [
        { name: "proxy_orchestrator", role: "4G proxy rotation + block recovery", status: "running", lastRun: "3s ago", costToday: 0, loopCap: 10, toolsAllowed: ["proxy_rotate", "proxy_verify", "log_action"] },
        { name: "fingerprint_monitor", role: "20-dim cluster histogram scan", status: "running", lastRun: "10m ago", costToday: 0, loopCap: 5, toolsAllowed: ["read_fleet_stats", "log_action"] },
        { name: "recovery", role: "Phone crash / logout auto-heal", status: "running", lastRun: "6m ago", costToday: 0, loopCap: 5, toolsAllowed: ["adb_reboot", "adb_reauth", "log_action"] },
        { name: "audit_harness", role: "10K-persona Monte Carlo gate", status: "running", lastRun: "10m ago", costToday: 0.42, loopCap: 3, toolsAllowed: ["openrouter_chat", "read_fleet_stats", "log_action"] },
      ],
    },
    {
      name: "funnel_mgr",
      platform: "funnel",
      status: "running",
      lastRun: "4m ago",
      costToday: 0.27,
      maxIterations: 5,
      maxUsd: 0.5,
      chatTier: "PROFESSIONAL",
      supervisedAgents: [
        { name: "funnel_conversion", role: "Fan → OF sub attribution", status: "running", lastRun: "4m ago", costToday: 0, loopCap: 5, toolsAllowed: ["read_crm", "log_action"] },
        { name: "source_discovery", role: "Auto-discover female US sources", status: "running", lastRun: "18m ago", costToday: 0.27, loopCap: 5, toolsAllowed: ["openrouter_chat", "read_fleet_stats", "log_action"] },
        { name: "fresh_target", role: "Fresh unique targets per account", status: "idle", lastRun: "1h ago", costToday: 0, loopCap: 3, toolsAllowed: ["read_target_db", "log_action"] },
      ],
    },
  ],
};

export default function AgentsPage() {
  const totalCost = CHIEF.costToday;
  const runningManagers = CHIEF.managers.filter((m) => m.status === "running").length;
  const totalSpecialists = CHIEF.managers.reduce((acc, m) => acc + m.supervisedAgents.length, 0);
  const runningSpecialists = CHIEF.managers.reduce(
    (acc, m) => acc + m.supervisedAgents.filter((s) => s.status === "running").length,
    0
  );

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Agent mesh
          </div>
          <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
            <Bot className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
            Autonomous <span className="phantom-accent-text">Agents</span>
          </h1>
          <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
            Hierarchical agent mesh. Chief orchestrates 11 platform managers, each with specialist
            sub-agents. Tool allowlists, loop caps, and cost caps enforced by code — not prompt.
          </p>
        </div>
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="phantom-panel p-5 flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-phantom-accent/10 flex items-center justify-center shrink-0">
            <Layers className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
          </div>
          <div>
            <div className="text-2xl font-display font-bold tabular-nums">{CHIEF.managers.length}</div>
            <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em]">Platform managers</div>
          </div>
        </div>
        <div className="phantom-panel p-5 flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-phantom-alive/10 flex items-center justify-center shrink-0">
            <Activity className="w-4 h-4 text-phantom-alive" strokeWidth={1.75} />
          </div>
          <div>
            <div className="text-2xl font-display font-bold tabular-nums text-phantom-alive">{runningManagers}</div>
            <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em]">Managers running</div>
          </div>
        </div>
        <div className="phantom-panel p-5 flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-phantom-magenta/10 flex items-center justify-center shrink-0">
            <Bot className="w-4 h-4 text-phantom-magenta" strokeWidth={1.75} />
          </div>
          <div>
            <div className="text-2xl font-display font-bold tabular-nums">{runningSpecialists}<span className="text-phantom-ghost text-lg">/{totalSpecialists}</span></div>
            <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em]">Specialists active</div>
          </div>
        </div>
        <div className="phantom-panel p-5 flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-phantom-amber/10 flex items-center justify-center shrink-0">
            <DollarSign className="w-4 h-4 text-phantom-amber" strokeWidth={1.75} />
          </div>
          <div>
            <div className="text-2xl font-display font-bold tabular-nums font-mono">${totalCost.toFixed(2)}</div>
            <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em]">LLM cost today</div>
          </div>
        </div>
      </div>

      {/* Tree + live feed */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <Panel label="agent hierarchy" title="Chief → Platform managers → Specialists">
            <div className="text-xs text-phantom-ghost mb-4">
              Click a platform manager to expand its config and specialist agents.
            </div>
            <AgentTree chief={CHIEF} />
          </Panel>
        </div>
        <AgentFeed />
      </div>

      <StaffroomPanel />

      <StaffroomRosterPanel />
    </div>
  );
}

function StaffroomRosterPanel() {
  const [roster, setRoster] = useState<any>(null);
  const [missions, setMissions] = useState<any[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [rRoster, rSummary] = await Promise.all([
        fetch("/api/platforms/staffroom/roster").then((r) => r.json()),
        fetch("/api/platforms/staffroom/missions/summary").then((r) => r.json()),
      ]);
      setRoster(rRoster);
      setMissions(rSummary?.recent || []);
      setErr(null);
    } catch (e: any) {
      setErr(String(e?.message || e));
    }
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);

  const dispatchRole = useCallback(async (slug: string) => {
    setBusy(slug);
    try {
      await fetch("/api/platforms/staffroom/missions/dispatch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workflow: "readiness_review",
          seed: `role:${slug}:${new Date().toISOString().slice(0, 10)}`,
          role: slug,
        }),
      });
      await load();
    } finally { setBusy(null); }
  }, [load]);

  const roles = roster?.roles || {};
  const slugs = Object.keys(roles);

  // Fallback: when the provisioner hasn't run, show a single empty-state
  // panel instead of a grid of nothing.
  if (slugs.length === 0) {
    return (
      <div className="phantom-panel p-5 mt-6">
        <div className="flex items-center gap-2 mb-3">
          <Users className="w-4 h-4 text-cyan-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            Staffroom · roster (21 specialists)
          </span>
        </div>
        <div className="text-[11px] text-phantom-ghost font-mono">
          No roster found. Run <code>node scripts/provision-staffroom-roster.mjs</code> against the local Staffroom instance to create the 21 bots. The roster file is written to <code>backend/.data/staffroom_roster.json</code>.
        </div>
        {err && <div className="text-[11px] font-mono text-red-400 mt-2">UI error: {err}</div>}
      </div>
    );
  }

  // Count missions per bot so each role card can show its most recent mission.
  const missionsByBot = new Map<string, any[]>();
  for (const m of missions) {
    const list = missionsByBot.get(m.staffroom_mission_id || "") || [];
    list.push(m);
  }

  return (
    <div className="phantom-panel p-5 mt-6">
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <Users className="w-4 h-4 text-cyan-400" />
        <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
          Staffroom · roster · {slugs.length} specialists
        </span>
        <span className="text-[10px] text-phantom-ghost font-mono truncate max-w-[280px]">
          {roster?.base_url}
        </span>
        <span className="text-[10px] text-phantom-ghost font-mono flex items-center gap-1">
          <Shield className="w-3 h-3" /> read-only · owner approves each mission
        </span>
        <button onClick={load} className="phantom-btn flex items-center gap-1 text-[10px] ml-auto">
          <RefreshCw className="w-3 h-3" /> refresh
        </button>
      </div>

      {err && <div className="text-[11px] font-mono text-red-400 mb-2">UI error: {err}</div>}

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {slugs.map((slug) => {
          const entry = roles[slug];
          const isOpus = entry.model_pin === "claude-opus-4-7";
          const last = entry.last_mission;
          const lastColor =
            last?.status === "completed" ? "text-green-400" :
            last?.status === "running" || last?.status === "queued" ? "text-sky-400" :
            last?.status === "needs_approval" ? "text-phantom-amber" :
            last?.status === "failed" ? "text-red-400" : "text-phantom-ghost";
          return (
            <div key={slug} className="phantom-panel p-3 border-phantom-charcoal/70 flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <Bot className={`w-4 h-4 ${isOpus ? "text-fuchsia-400" : "text-cyan-400"}`} />
                <span className="text-[12px] font-mono text-phantom-mist truncate" title={entry.name}>
                  {entry.name}
                </span>
              </div>
              <div className="text-[10px] font-mono text-phantom-ghost truncate" title={entry.role}>
                {entry.role}
              </div>
              <div className="flex items-center gap-2 text-[10px] font-mono">
                <span className={`px-1.5 py-0.5 border rounded ${
                  isOpus
                    ? "bg-fuchsia-500/10 border-fuchsia-500/40 text-fuchsia-300"
                    : "bg-cyan-500/10 border-cyan-500/40 text-cyan-300"
                }`}>
                  {isOpus ? "opus" : "sonnet"}
                </span>
                <span className="text-phantom-ghost truncate" title={entry.bot_id}>
                  {entry.bot_id.slice(0, 8)}…
                </span>
              </div>
              <div className="text-[10px] font-mono text-phantom-ghost flex items-center gap-1">
                <Zap className="w-3 h-3" />
                <span className="truncate" title={entry.request_id}>{slug}</span>
              </div>
              {last ? (
                <div className="text-[10px] font-mono flex items-center gap-1">
                  <span className="text-phantom-ghost">last:</span>
                  <span className={lastColor}>{last.status}</span>
                  {last.staffroom_mission_id && roster?.base_url && (
                    <a
                      href={`${roster.base_url}/missions/${last.staffroom_mission_id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-cyan-400 inline-flex items-center gap-0.5 ml-auto"
                      title={last.staffroom_mission_id}
                    >
                      <ExternalLink className="w-3 h-3" /> open
                    </a>
                  )}
                </div>
              ) : (
                <div className="text-[10px] font-mono text-phantom-ghost">last: —</div>
              )}
              <button
                onClick={() => dispatchRole(slug)}
                disabled={!!busy}
                className="phantom-btn flex items-center justify-center gap-1 text-[10px] mt-auto"
                title={`Dispatch a readiness_review against ${entry.name}`}
              >
                <Rocket className="w-3 h-3" />
                {busy === slug ? "Dispatching…" : "Dispatch to this role"}
              </button>
            </div>
          );
        })}
      </div>
      <div className="text-[10px] text-phantom-ghost font-mono mt-3">
        Dispatches go to Staffroom as <code>needs_approval</code>. Approve each in Staffroom; the runner routes COO/review calls to opus and workers to sonnet from message shape. No paid fallback.
      </div>
    </div>
  );
}

function StaffroomPanel() {
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/platforms/staffroom/missions/summary");
      const j = await r.json();
      setData(j);
      setErr(null);
    } catch (e: any) {
      setErr(String(e?.message || e));
    }
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, [load]);

  const dispatch = useCallback(async () => {
    setBusy(true);
    try {
      await fetch("/api/platforms/staffroom/missions/dispatch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow: "readiness_review" }),
      });
      await load();
    } finally { setBusy(false); }
  }, [load]);

  const refresh = useCallback(async (rid: string) => {
    await fetch(`/api/platforms/staffroom/missions/${rid}/refresh`, { method: "POST" });
    await load();
  }, [load]);

  const health = data?.staffroom_health;
  const healthOk = !!health?.ok;
  const stats = data?.stats || {};
  const recent = data?.recent || [];

  return (
    <div className="phantom-panel p-5 mt-6">
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <Workflow className="w-4 h-4 text-cyan-400" />
        <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
          Staffroom · system of record · missions · assignments · artifacts
        </span>
        <span className={`px-2 py-0.5 border text-[10px] font-mono rounded ${healthOk ? "bg-green-500/10 border-green-500/50 text-green-400" : "bg-red-500/10 border-red-500/50 text-red-400"}`}>
          {healthOk ? "STAFFROOM UP" : "STAFFROOM DOWN"}
        </span>
        <span className="text-[10px] text-phantom-ghost font-mono truncate max-w-[280px]">
          {data?.base_url}
        </span>
        <span className="text-[10px] text-phantom-ghost font-mono flex items-center gap-1">
          <Shield className="w-3 h-3" /> COO=claude-opus-4-7 · workers=claude-sonnet-4-6
        </span>
        <button onClick={load} className="phantom-btn flex items-center gap-2 text-xs" title="Refresh summary">
          <RefreshCw className="w-3 h-3" />
        </button>
        <button onClick={dispatch} disabled={busy} className="phantom-btn flex items-center gap-2 text-xs ml-auto">
          <Rocket className="w-3 h-3" /> {busy ? "Dispatching…" : "Launch Readiness Review"}
        </button>
      </div>

      <div className="grid grid-cols-5 gap-3 mb-4">
        {[
          { label: "total",         value: stats.total ?? 0,                                    color: "text-phantom-mist" },
          { label: "needs appr.",   value: stats.by_status?.needs_approval ?? 0,                color: "text-phantom-amber" },
          { label: "running",       value: (stats.by_status?.running ?? 0) + (stats.by_status?.queued ?? 0), color: "text-sky-400" },
          { label: "completed",     value: stats.by_status?.completed ?? 0,                     color: "text-green-400" },
          { label: "failed",        value: (stats.by_status?.failed ?? 0) + (stats.by_status?.pending_dispatch ?? 0), color: "text-red-400" },
        ].map(({ label, value, color }) => (
          <div key={label} className="phantom-panel p-3 border-phantom-charcoal/70">
            <div className={`text-[10px] uppercase tracking-wider font-mono ${color}`}>{label}</div>
            <div className={`text-2xl font-bold mt-1 ${color}`}>{value}</div>
          </div>
        ))}
      </div>

      {err && <div className="text-[11px] font-mono text-red-400 mb-2">UI error: {err}</div>}

      {recent.length === 0 ? (
        <div className="text-[11px] text-phantom-ghost font-mono">
          No missions yet. Dispatching the Readiness Review will post a mission to Staffroom; the COO plan, two worker artifacts, and final report will appear here as they land, with an Open-in-Staffroom link on each row.
        </div>
      ) : (
        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-wider text-phantom-ghost font-mono mb-1">recent missions</div>
          {recent.map((r: any) => (
            <div key={r.request_id} className="flex items-center gap-3 text-[11px] font-mono py-1.5 border-b border-phantom-charcoal/40">
              <span className="text-phantom-mist w-48 truncate" title={r.request_id}>{r.request_id}</span>
              <span className="text-phantom-ghost w-32 truncate" title={r.workflow}>{r.workflow}</span>
              <span className={`w-28 ${
                r.status === "completed" ? "text-green-400" :
                r.status === "running" || r.status === "queued" ? "text-sky-400" :
                r.status === "needs_approval" ? "text-phantom-amber" :
                r.status === "failed" ? "text-red-400" : "text-phantom-ghost"
              }`}>{r.status}</span>
              <span className="text-phantom-ghost w-32 truncate" title={r.staffroom_mission_id || ""}>{r.staffroom_mission_id || "—"}</span>
              <button onClick={() => refresh(r.request_id)} className="phantom-btn flex items-center gap-1 text-[10px]">
                <RefreshCw className="w-3 h-3" /> poll
              </button>
              {r.staffroom_mission_id && data?.base_url && (
                <a
                  href={`${data.base_url}/missions/${r.staffroom_mission_id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="phantom-btn flex items-center gap-1 text-[10px] text-cyan-400"
                >
                  <ExternalLink className="w-3 h-3" /> Open in Staffroom
                </a>
              )}
              {r.error && <span className="text-red-400 flex-1 truncate" title={r.error}>{r.error}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
