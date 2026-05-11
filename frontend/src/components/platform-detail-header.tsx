import { cn } from "@/lib/utils";
import type { Platform } from "@/components/platform-badge";
import { PlatformBadge } from "@/components/platform-badge";
import { ChatTierBadge, type ChatTier } from "@/components/chat-tier-badge";

type ExecutionMode = "Background API" | "Foreground UI" | "Hybrid";
type Phase = 1 | 2 | 3 | 4 | 5;

const EXECUTION_MODE_STYLES: Record<ExecutionMode, string> = {
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

export function PlatformDetailHeader({
  platform,
  phase,
  executionMode,
  chatTier,
  accountsActive,
  accountsMax,
  description,
  isLive = false,
}: {
  platform: Platform;
  phase: Phase;
  executionMode: ExecutionMode;
  chatTier: ChatTier;
  accountsActive: number;
  accountsMax: number;
  description?: string;
  isLive?: boolean;
}) {
  const utilizationPct = accountsMax > 0 ? (accountsActive / accountsMax) * 100 : 0;

  return (
    <div className="flex flex-col gap-5">
      {/* Title row */}
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-4">
          <div className="mt-1">
            <PlatformBadge platform={platform} size="md" showLabel={false} />
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
              Platform configuration
            </div>
            <h1 className="font-display text-4xl font-bold mt-1 tracking-tight capitalize">
              {platform === "x" ? "X (Twitter)" : platform.charAt(0).toUpperCase() + platform.slice(1)}
            </h1>
            {description && (
              <p className="text-phantom-ghost mt-1.5 text-sm max-w-xl">{description}</p>
            )}
          </div>
        </div>

        {/* Status badges */}
        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "text-[9px] font-mono tracking-wider px-2 py-0.5 rounded border",
                PHASE_STYLES[phase]
              )}
            >
              PHASE {phase}
            </span>
            <span
              className={cn(
                "text-[9px] font-mono tracking-wider px-2 py-0.5 rounded border",
                EXECUTION_MODE_STYLES[executionMode]
              )}
            >
              {executionMode.toUpperCase()}
            </span>
          </div>
          <ChatTierBadge tier={chatTier} size="sm" />
          {isLive && (
            <div className="flex items-center gap-1.5 text-xs text-phantom-ghost">
              <span className="phantom-dot phantom-dot-alive animate-phantom-pulse" />
              <span>Live</span>
            </div>
          )}
        </div>
      </div>

      {/* Capacity bar */}
      <div className="phantom-panel p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">
            Account capacity
          </span>
          <span className="text-sm font-mono tabular-nums">
            <span className="text-white font-semibold">{accountsActive.toLocaleString()}</span>
            <span className="text-phantom-ghost"> / {accountsMax.toLocaleString()}</span>
          </span>
        </div>
        <div className="h-2 rounded-full bg-phantom-panelHi overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{
              width: `${utilizationPct}%`,
              background: utilizationPct > 80
                ? "hsl(38 92% 58%)"
                : "hsl(162 100% 54%)",
              boxShadow: `0 0 12px ${utilizationPct > 80 ? "hsl(38 92% 58% / 0.4)" : "hsl(162 100% 54% / 0.4)"}`,
            }}
          />
        </div>
        <div className="text-[10px] text-phantom-ghost mt-1.5">
          {utilizationPct.toFixed(0)}% utilized · {accountsMax - accountsActive} slots available
        </div>
      </div>
    </div>
  );
}
