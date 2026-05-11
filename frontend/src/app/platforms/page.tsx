import Link from "next/link";
import { Panel } from "@/components/panel";
import { PlatformBadge, type Platform } from "@/components/platform-badge";
import { ChatTierBadge, type ChatTier } from "@/components/chat-tier-badge";
import { Lock, Settings } from "lucide-react";
import { cn } from "@/lib/utils";

type Phase = 1 | 2 | 3 | 4 | 5;

type PlatformConfig = {
  platform: Platform;
  phase: Phase;
  accountsConfigured: number;
  maxCapacity: number;
  executionMode: "Background API" | "Foreground UI" | "Hybrid";
  chatTier: ChatTier;
  description: string;
  isLive: boolean;
};

const PLATFORMS: PlatformConfig[] = [
  {
    platform: "instagram",
    phase: 1,
    accountsConfigured: 97,
    maxCapacity: 114,
    executionMode: "Background API",
    chatTier: "FLIRTY_SFW",
    description: "Primary revenue driver. Tatiana persona. 97 accounts across 9 phones.",
    isLive: true,
  },
  {
    platform: "threads",
    phase: 1,
    accountsConfigured: 97,
    maxCapacity: 114,
    executionMode: "Background API",
    chatTier: "FLIRTY_SFW",
    description: "Mirrored from Instagram accounts. Cross-platform amplification.",
    isLive: true,
  },
  {
    platform: "reddit",
    phase: 1,
    accountsConfigured: 25,
    maxCapacity: 50,
    executionMode: "Background API",
    chatTier: "NSFW",
    description: "NSFW subreddit targeting. Melodie persona. Phase 1 running.",
    isLive: true,
  },
  {
    platform: "tiktok",
    phase: 2,
    accountsConfigured: 0,
    maxCapacity: 30,
    executionMode: "Foreground UI",
    chatTier: "FLIRTY_SFW",
    description: "Planned Phase 2 expansion. Foreground UI automation required.",
    isLive: false,
  },
  {
    platform: "telegram",
    phase: 2,
    accountsConfigured: 0,
    maxCapacity: 80,
    executionMode: "Background API",
    chatTier: "CASUAL_SFW",
    description: "High-volume messaging channel. Phase 2 roadmap.",
    isLive: false,
  },
  {
    platform: "x",
    phase: 2,
    accountsConfigured: 0,
    maxCapacity: 40,
    executionMode: "Background API",
    chatTier: "FLIRTY_SFW",
    description: "X/Twitter outreach. Phase 2 roadmap.",
    isLive: false,
  },
  {
    platform: "discord",
    phase: 3,
    accountsConfigured: 0,
    maxCapacity: 60,
    executionMode: "Background API",
    chatTier: "CASUAL_SFW",
    description: "Community-based funnel entry. Phase 3 roadmap.",
    isLive: false,
  },
  {
    platform: "bluesky",
    phase: 3,
    accountsConfigured: 0,
    maxCapacity: 50,
    executionMode: "Background API",
    chatTier: "FLIRTY_SFW",
    description: "Emerging platform with lower detection pressure. Phase 3.",
    isLive: false,
  },
  {
    platform: "dating",
    phase: 4,
    accountsConfigured: 0,
    maxCapacity: 20,
    executionMode: "Foreground UI",
    chatTier: "NSFW",
    description: "Dating app funnels (Grindr, Hinge, Tinder). Phase 4 roadmap.",
    isLive: false,
  },
];

const EXECUTION_MODE_STYLES: Record<string, string> = {
  "Background API": "bg-phantom-alive/10 text-phantom-alive border-phantom-alive/25",
  "Foreground UI": "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/25",
  "Hybrid": "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/25",
};

const PHASE_STYLES: Record<Phase, string> = {
  1: "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/25",
  2: "bg-phantom-ghost/10 text-phantom-ghost border-phantom-border",
  3: "bg-phantom-ghost/10 text-phantom-ghost border-phantom-border",
  4: "bg-phantom-ghost/10 text-phantom-ghost border-phantom-border",
  5: "bg-phantom-ghost/10 text-phantom-ghost border-phantom-border",
};

export default function PlatformsPage() {
  const activePlatforms = PLATFORMS.filter((p) => p.isLive);
  const plannedPlatforms = PLATFORMS.filter((p) => !p.isLive);
  const totalAccounts = PLATFORMS.reduce((s, p) => s + p.accountsConfigured, 0);
  const totalCapacity = PLATFORMS.reduce((s, p) => s + p.maxCapacity, 0);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Platform mesh
          </div>
          <h1 className="font-display text-4xl font-bold mt-2 tracking-tight">
            Platform <span className="phantom-accent-text">Overview</span>
          </h1>
          <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
            {activePlatforms.length} platforms live · {plannedPlatforms.length} on roadmap ·{" "}
            {totalAccounts} of {totalCapacity} total capacity slots filled.
          </p>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-phantom-ghost font-mono">
          <span className="phantom-dot phantom-dot-alive animate-phantom-pulse" />
          <span>{activePlatforms.length} live</span>
          <span className="mx-2 text-phantom-border">|</span>
          <span className="phantom-dot bg-phantom-ghost" />
          <span>{plannedPlatforms.length} planned</span>
        </div>
      </div>

      {/* Active platforms */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-4">
          Phase 1 — Live
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {activePlatforms.map((p) => (
            <PlatformCard key={p.platform} config={p} />
          ))}
        </div>
      </div>

      {/* Planned platforms */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-4">
          Phase 2–4 — Roadmap
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {plannedPlatforms.map((p) => (
            <PlatformCard key={p.platform} config={p} />
          ))}
        </div>
      </div>
    </div>
  );
}

function PlatformCard({ config }: { config: PlatformConfig }) {
  const utilPct = config.maxCapacity > 0
    ? (config.accountsConfigured / config.maxCapacity) * 100
    : 0;
  const isLocked = !config.isLive;

  return (
    <div
      className={cn(
        "phantom-panel p-5 flex flex-col gap-4 relative overflow-hidden transition-all duration-200",
        isLocked ? "opacity-60" : "hover:border-phantom-accent/30"
      )}
    >
      {/* Lock overlay for planned */}
      {isLocked && (
        <div className="absolute top-3 right-3">
          <Lock className="w-3.5 h-3.5 text-phantom-ghost" />
        </div>
      )}

      {/* Platform header */}
      <div className="flex items-start justify-between pr-5">
        <PlatformBadge platform={config.platform} size="md" />
        <span
          className={cn(
            "text-[9px] font-mono tracking-wider px-2 py-0.5 rounded border",
            PHASE_STYLES[config.phase]
          )}
        >
          PHASE {config.phase}
        </span>
      </div>

      {/* Description */}
      <p className="text-xs text-phantom-ghost leading-relaxed">{config.description}</p>

      {/* Account capacity bar */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] text-phantom-ghost">Accounts</span>
          <span className="text-[10px] font-mono tabular-nums text-phantom-ghost">
            {config.accountsConfigured} / {config.maxCapacity}
          </span>
        </div>
        <div className="h-1.5 rounded-full bg-phantom-panelHi overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{
              width: `${utilPct}%`,
              background: config.isLive ? "hsl(162 100% 54%)" : "hsl(240 5% 64.9%)",
              boxShadow: config.isLive ? "0 0 8px hsl(162 100% 54% / 0.4)" : undefined,
            }}
          />
        </div>
      </div>

      {/* Badges row */}
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className={cn(
            "text-[8px] font-mono tracking-wider px-1.5 py-0.5 rounded border",
            EXECUTION_MODE_STYLES[config.executionMode]
          )}
        >
          {config.executionMode === "Background API" ? "BG API" : config.executionMode === "Foreground UI" ? "FG UI" : "HYBRID"}
        </span>
        <ChatTierBadge tier={config.chatTier} size="xs" />
        {config.isLive && (
          <div className="flex items-center gap-1 ml-auto">
            <span className="phantom-dot phantom-dot-alive animate-phantom-pulse" />
            <span className="text-[9px] text-phantom-ghost">Live</span>
          </div>
        )}
      </div>

      {/* Configure button */}
      <div className="pt-1 border-t border-phantom-border">
        {config.isLive ? (
          <Link
            href={`/platforms/${config.platform}`}
            className="flex items-center gap-1.5 text-xs text-phantom-accent hover:underline font-medium"
          >
            <Settings className="w-3 h-3" />
            Configure
          </Link>
        ) : (
          <span className="flex items-center gap-1.5 text-xs text-phantom-ghost cursor-not-allowed">
            <Lock className="w-3 h-3" />
            Phase {config.phase} — not yet active
          </span>
        )}
      </div>
    </div>
  );
}
