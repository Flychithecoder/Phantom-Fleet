import { AgentTree, type ChiefAgent } from "@/components/agent-tree";
import { Panel } from "@/components/panel";
import { AgentFeed } from "@/components/agent-feed";
import { Bot, DollarSign, Activity, Layers } from "lucide-react";

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
    </div>
  );
}
