"use client";

import { use } from "react";
import { notFound } from "next/navigation";
import { Panel } from "@/components/panel";
import { PlatformDetailHeader } from "@/components/platform-detail-header";
import { ChatTierBadge } from "@/components/chat-tier-badge";
import { StatusBadge } from "@/components/status-badge";
import { TimeSlotStrip } from "@/components/time-slot-strip";
import { Sparkline } from "@/components/sparkline";
import { DataTable, type Column } from "@/components/data-table";
import type { Platform } from "@/components/platform-badge";
import type { ChatTier } from "@/components/chat-tier-badge";
import { cn } from "@/lib/utils";

// ─── Platform configs ─────────────────────────────────────────────────────────

type PlatformDetailConfig = {
  platform: Platform;
  phase: 1 | 2 | 3 | 4 | 5;
  executionMode: "Background API" | "Foreground UI" | "Hybrid";
  chatTier: ChatTier;
  accountsActive: number;
  accountsMax: number;
  description: string;
  activeHours: number[];
  agentSpecialists: string[];
  chatTierInfo: {
    allowedContent: string[];
    bannedPhrasesCount: number;
    escalationRule: string;
  };
  settings: Record<string, string | number | boolean>;
  metrics: {
    actionsToday: number;
    successRate: number;
    avgFollowBackRate: number;
    avgDmOpenRate: number;
    trend: number[];
  };
};

const PLATFORM_CONFIGS: Partial<Record<Platform, PlatformDetailConfig>> = {
  instagram: {
    platform: "instagram",
    phase: 1,
    executionMode: "Background API",
    chatTier: "FLIRTY_SFW",
    accountsActive: 97,
    accountsMax: 114,
    description: "Primary revenue funnel. Tatiana persona across 9 phones. LogNormal-sampled action curve, cluster-audited fingerprints.",
    activeHours: [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22],
    agentSpecialists: ["FollowEngine", "StoryViewer", "ProfileScraper", "DMResponder", "ContentScheduler"],
    chatTierInfo: {
      allowedContent: ["Flirty compliments", "Lifestyle content", "Soft teasing", "SFW previews"],
      bannedPhrasesCount: 47,
      escalationRule: "Escalate to Tier 4 MIXED after 3 DM exchanges with high-intent signals",
    },
    settings: {
      follow_limit_per_day: 180,
      story_view_rate_per_hour: 45,
      unfollow_after_days: 3,
      dm_delay_min_seconds: 120,
      dm_delay_max_seconds: 480,
      profile_visit_before_follow: true,
      use_proxy_rotation: true,
    },
    metrics: {
      actionsToday: 4280,
      successRate: 0.978,
      avgFollowBackRate: 0.261,
      avgDmOpenRate: 0.143,
      trend: [3800, 4100, 4050, 4280, 4320, 4100, 4280],
    },
  },
  threads: {
    platform: "threads",
    phase: 1,
    executionMode: "Background API",
    chatTier: "FLIRTY_SFW",
    accountsActive: 97,
    accountsMax: 114,
    description: "Mirrored from Instagram accounts. Cross-platform amplification for Tatiana persona.",
    activeHours: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21],
    agentSpecialists: ["ThreadsFollower", "ContentMirror", "ProfileScraper"],
    chatTierInfo: {
      allowedContent: ["Lifestyle posts", "Flirty banter", "Soft promotion"],
      bannedPhrasesCount: 31,
      escalationRule: "Bridge to Instagram DMs for conversion",
    },
    settings: {
      follow_limit_per_day: 150,
      post_reply_rate: 0.3,
      mirror_instagram_posts: true,
      use_proxy_rotation: true,
    },
    metrics: {
      actionsToday: 3120,
      successRate: 0.985,
      avgFollowBackRate: 0.312,
      avgDmOpenRate: 0.09,
      trend: [2800, 3000, 3100, 3120, 3200, 3080, 3120],
    },
  },
  reddit: {
    platform: "reddit",
    phase: 1,
    executionMode: "Background API",
    chatTier: "NSFW",
    accountsActive: 25,
    accountsMax: 50,
    description: "NSFW subreddit targeting. Melodie persona. Direct-to-link conversion via DMs and post comments.",
    activeHours: [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
    agentSpecialists: ["SubredditScout", "PostCommentor", "DMOutreach", "ContentPoster"],
    chatTierInfo: {
      allowedContent: ["Explicit DMs", "NSFW previews", "Direct link drops", "Custom content offers"],
      bannedPhrasesCount: 18,
      escalationRule: "Direct to OF/Fanvue link on any positive reply signal",
    },
    settings: {
      subreddits_targeted: 12,
      posts_per_account_per_day: 2,
      comments_per_account_per_day: 8,
      dm_limit_per_day: 15,
      account_age_min_days: 30,
      karma_min: 100,
    },
    metrics: {
      actionsToday: 650,
      successRate: 0.944,
      avgFollowBackRate: 0.18,
      avgDmOpenRate: 0.22,
      trend: [580, 620, 600, 650, 680, 640, 650],
    },
  },
};

// ─── Account rows ────────────────────────────────────────────────────────────

type AccountRow = {
  id: string;
  username: string;
  phone: string;
  status: "active" | "warming" | "paused" | "dead";
  dayInCurve: number;
  actions24h: number;
  followers: number;
  trend: number[];
};

function generateAccountRows(platform: Platform, count: number): AccountRow[] {
  const prefixes: Record<string, string[]> = {
    instagram: ["tatiannalifee", "tatianamusee", "tatianazenn", "hackerhoneytatii", "tatiana.vibes", "tatianawave", "tattiana.official"],
    threads: ["tatiannalifee", "tatianamusee", "tatianazenn", "hackerhoneytatii", "tatiana.vibes", "tatianawave", "tattiana.official"],
    reddit: ["u_melodieee", "u_melodiedream", "u_sweetmelodieee", "u_melodieprince", "u_melodiexox"],
  };
  const names = prefixes[platform] ?? prefixes.instagram;
  return Array.from({ length: Math.min(count, 10) }, (_, i) => ({
    id: String(i),
    username: names[i % names.length] + (i >= names.length ? `_${i}` : ""),
    phone: `RF8N${String(10 + (i % 9)).padStart(2, "0")}XX${i}`,
    status: i === 3 ? "warming" : i === 7 ? "paused" : "active",
    dayInCurve: 30 + (i * 7) % 60,
    actions24h: 20 + (i * 11) % 30,
    followers: 1800 + (i * 230) % 1500,
    trend: Array.from({ length: 8 }, (_, t) => 18 + t * 3 + (i % 3)),
  }));
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function PlatformDetailPage({
  params,
}: {
  params: Promise<{ platform: string }>;
}) {
  const { platform } = use(params);
  const config = PLATFORM_CONFIGS[platform as Platform];

  if (!config) {
    notFound();
  }

  const accounts = generateAccountRows(config.platform, config.accountsActive);

  const columns: Column<AccountRow>[] = [
    {
      key: "username",
      header: "Account",
      render: (r) => (
        <div>
          <div className="font-mono text-white text-sm">@{r.username}</div>
          <div className="font-mono text-[10px] text-phantom-ghost">{r.phone}</div>
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (r) => <StatusBadge status={r.status} />,
    },
    {
      key: "dayInCurve",
      header: "Day",
      align: "right",
      render: (r) => (
        <span className="font-mono text-sm tabular-nums">{r.dayInCurve}</span>
      ),
    },
    {
      key: "actions24h",
      header: "Actions 24h",
      align: "right",
      render: (r) => (
        <span className="font-mono tabular-nums text-phantom-accent">{r.actions24h}</span>
      ),
    },
    {
      key: "followers",
      header: "Followers",
      align: "right",
      render: (r) => (
        <span className="font-mono tabular-nums text-sm">{r.followers.toLocaleString()}</span>
      ),
    },
    {
      key: "trend",
      header: "Trend",
      width: "100px",
      render: (r) => <Sparkline data={r.trend} height={28} />,
    },
  ];

  return (
    <div className="space-y-8">
      {/* Platform detail header */}
      <PlatformDetailHeader
        platform={config.platform}
        phase={config.phase}
        executionMode={config.executionMode}
        chatTier={config.chatTier}
        accountsActive={config.accountsActive}
        accountsMax={config.accountsMax}
        description={config.description}
        isLive={config.phase === 1}
      />

      {/* Metrics row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Actions today"
          value={config.metrics.actionsToday.toLocaleString()}
          accent
        />
        <MetricCard
          label="Success rate"
          value={`${(config.metrics.successRate * 100).toFixed(1)}%`}
        />
        <MetricCard
          label="Follow-back rate"
          value={`${(config.metrics.avgFollowBackRate * 100).toFixed(1)}%`}
        />
        <MetricCard
          label="DM open rate"
          value={`${(config.metrics.avgDmOpenRate * 100).toFixed(1)}%`}
        />
      </div>

      {/* Chat tier + Agent managers + Schedule — 3-col */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Chat tier info */}
        <Panel label="content tier" title="Chat tier rules">
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <ChatTierBadge tier={config.chatTier} size="md" />
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost mb-2">
                Allowed content
              </div>
              <ul className="space-y-1.5">
                {config.chatTierInfo.allowedContent.map((item) => (
                  <li key={item} className="flex items-start gap-2 text-xs text-phantom-ghost">
                    <span className="text-phantom-accent mt-0.5">›</span>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
            <div className="pt-3 border-t border-phantom-border">
              <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost mb-1">
                Banned phrases
              </div>
              <div className="font-mono text-2xl font-bold text-phantom-red">
                {config.chatTierInfo.bannedPhrasesCount}
              </div>
            </div>
            <div className="pt-3 border-t border-phantom-border">
              <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost mb-1">
                Escalation rule
              </div>
              <p className="text-xs text-phantom-ghost leading-relaxed">
                {config.chatTierInfo.escalationRule}
              </p>
            </div>
          </div>
        </Panel>

        {/* Agent specialists */}
        <Panel label="agent mesh" title="Supervises">
          <div className="space-y-2">
            {config.agentSpecialists.map((agent, i) => (
              <div
                key={agent}
                className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-phantom-panelHi border border-phantom-border"
              >
                <span className="phantom-dot phantom-dot-alive animate-phantom-pulse" />
                <span className="text-sm font-mono">{agent}</span>
                <span className="ml-auto text-[9px] text-phantom-ghost font-mono">
                  worker-{String(i + 1).padStart(2, "0")}
                </span>
              </div>
            ))}
          </div>
        </Panel>

        {/* Time slot schedule */}
        <Panel label="run schedule" title="Active hours today">
          <TimeSlotStrip
            activeHours={config.activeHours}
            label="Today's schedule"
          />
          <div className="mt-4 pt-4 border-t border-phantom-border">
            <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost mb-2">
              Performance trend (7d)
            </div>
            <Sparkline
              data={config.metrics.trend}
              color="hsl(162 100% 54%)"
              height={48}
              label="Actions"
            />
            <div className="flex items-center justify-between mt-1">
              {config.metrics.trend.map((v, i) => (
                <span key={i} className="text-[9px] font-mono text-phantom-ghost tabular-nums">
                  {v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v}
                </span>
              ))}
            </div>
          </div>
        </Panel>
      </div>

      {/* Platform settings */}
      <Panel label="platform configuration" title="Settings">
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {Object.entries(config.settings).map(([key, value]) => (
            <div
              key={key}
              className="bg-phantom-panelHi border border-phantom-border rounded-lg p-3"
            >
              <div className="text-[9px] uppercase tracking-[0.12em] text-phantom-ghost mb-1 font-medium">
                {key.replace(/_/g, " ")}
              </div>
              <div
                className={cn(
                  "font-mono text-sm font-semibold",
                  typeof value === "boolean"
                    ? value
                      ? "text-phantom-alive"
                      : "text-phantom-red"
                    : "text-phantom-accent"
                )}
              >
                {typeof value === "boolean"
                  ? value ? "true" : "false"
                  : String(value)}
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* Accounts table */}
      <Panel
        label={`${config.accountsActive} accounts`}
        title={`${config.platform.charAt(0).toUpperCase() + config.platform.slice(1)} account ledger`}
        subtitle={`Showing first 10 of ${config.accountsActive} accounts on this platform.`}
      >
        <DataTable columns={columns} rows={accounts} />
        {config.accountsActive > 10 && (
          <div className="mt-4 text-center">
            <button className="text-xs text-phantom-accent hover:underline">
              View all {config.accountsActive} accounts →
            </button>
          </div>
        )}
      </Panel>
    </div>
  );
}

function MetricCard({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className={cn("phantom-panel p-5", accent && "phantom-panel-accent")}>
      <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">{label}</div>
      <div className={cn("font-display font-bold text-3xl tabular-nums mt-2", accent && "phantom-accent-text")}>
        {value}
      </div>
    </div>
  );
}
