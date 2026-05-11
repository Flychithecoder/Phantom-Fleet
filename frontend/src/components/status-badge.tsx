import { cn } from "@/lib/utils";

type Status =
  | "active"
  | "warming"
  | "re_wake"
  | "paused"
  | "cooldown"
  | "recovery"
  | "dead"
  | "idle"
  | "offline"
  | "imported"
  | "flagged";

const STYLES: Record<Status, string> = {
  active: "bg-phantom-alive/10 text-phantom-alive border-phantom-alive/30",
  warming: "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/30",
  re_wake: "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/30",
  paused: "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/30",
  cooldown: "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/30",
  recovery: "bg-phantom-magenta/10 text-phantom-magenta border-phantom-magenta/30",
  dead: "bg-phantom-red/10 text-phantom-red border-phantom-red/30",
  idle: "bg-phantom-panelHi text-phantom-ghost border-phantom-border",
  offline: "bg-phantom-panelHi text-phantom-ghost border-phantom-border",
  imported: "bg-phantom-panelHi text-phantom-ghost border-phantom-border",
  flagged: "bg-phantom-red/10 text-phantom-red border-phantom-red/30",
};

const LABELS: Record<Status, string> = {
  active: "ACTIVE",
  warming: "WARMING",
  re_wake: "RE-WAKE",
  paused: "PAUSED",
  cooldown: "COOLDOWN",
  recovery: "RECOVERY",
  dead: "DEAD",
  idle: "IDLE",
  offline: "OFFLINE",
  imported: "IMPORTED",
  flagged: "FLAGGED",
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-mono tracking-wider border",
        STYLES[status],
      )}
    >
      {LABELS[status]}
    </span>
  );
}
