import { cn } from "@/lib/utils";

export type ChatTier =
  | "PROFESSIONAL"
  | "CASUAL_SFW"
  | "FLIRTY_SFW"
  | "MIXED"
  | "NSFW";

const TIER_STYLES: Record<ChatTier, string> = {
  PROFESSIONAL: "bg-blue-400/10 text-blue-400 border-blue-400/25",
  CASUAL_SFW: "bg-phantom-alive/10 text-phantom-alive border-phantom-alive/25",
  FLIRTY_SFW: "bg-phantom-magenta/10 text-phantom-magenta border-phantom-magenta/25",
  MIXED: "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/25",
  NSFW: "bg-phantom-red/10 text-phantom-red border-phantom-red/25",
};

const TIER_LABELS: Record<ChatTier, string> = {
  PROFESSIONAL: "PROFESSIONAL",
  CASUAL_SFW: "CASUAL SFW",
  FLIRTY_SFW: "FLIRTY SFW",
  MIXED: "MIXED",
  NSFW: "NSFW",
};

export function ChatTierBadge({
  tier,
  size = "sm",
}: {
  tier: ChatTier;
  size?: "xs" | "sm" | "md";
}) {
  const textSizes = { xs: "text-[8px]", sm: "text-[9px]", md: "text-[10px]" };
  return (
    <span
      className={cn(
        "inline-flex items-center px-1.5 py-0.5 rounded border font-mono font-semibold tracking-wider",
        textSizes[size],
        TIER_STYLES[tier]
      )}
    >
      {TIER_LABELS[tier]}
    </span>
  );
}
