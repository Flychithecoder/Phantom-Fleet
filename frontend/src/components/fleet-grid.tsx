"use client";

import { cn } from "@/lib/utils";

type PhoneState = "active" | "idle" | "warming" | "cooldown" | "recovery" | "offline";

type Phone = {
  serial: string;
  persona: string;
  state: PhoneState;
  accountCount: number;
  actionsToday: number;
};

const DEMO_PHONES: Phone[] = [
  { serial: "RF8N81XYX4J", persona: "Tatiana", state: "active", accountCount: 15, actionsToday: 312 },
  { serial: "RF8N90FZ0LV", persona: "Melodie", state: "active", accountCount: 26, actionsToday: 487 },
  { serial: "RF8N61Z9FZB", persona: "Tatiana", state: "active", accountCount: 16, actionsToday: 328 },
  { serial: "RF8N71RBF2H", persona: "Melodie", state: "active", accountCount: 16, actionsToday: 298 },
  { serial: "RF8N20VWNHM", persona: "Melodie", state: "warming", accountCount: 14, actionsToday: 142 },
  { serial: "RF8N50EM1WK", persona: "Tatiana", state: "warming", accountCount: 14, actionsToday: 138 },
  { serial: "RF8N30B5FAD", persona: "Melodie", state: "active", accountCount: 12, actionsToday: 238 },
  { serial: "RF8N70R01XT", persona: "Tatiana", state: "active", accountCount: 12, actionsToday: 231 },
  { serial: "RF8N11BB1MN", persona: "Melodie", state: "cooldown", accountCount: 10, actionsToday: 89 },
  { serial: "RF8N21A0X5Y", persona: "Melodie", state: "active", accountCount: 10, actionsToday: 194 },
  { serial: "RF8N3075H7Y", persona: "Melodie", state: "active", accountCount: 10, actionsToday: 187 },
  { serial: "RF8N4057ELK", persona: "Melodie", state: "active", accountCount: 9, actionsToday: 176 },
  { serial: "RF8N406NLWK", persona: "Tatiana", state: "active", accountCount: 9, actionsToday: 172 },
  { serial: "RF8N10J57DA", persona: "Tatiana", state: "active", accountCount: 9, actionsToday: 168 },
  { serial: "RF8N501E82B", persona: "Melodie", state: "active", accountCount: 8, actionsToday: 151 },
  { serial: "RF8N10B574B", persona: "Melodie", state: "active", accountCount: 18, actionsToday: 342 },
  { serial: "RF8N81VR6DT", persona: "Melodie", state: "idle", accountCount: 4, actionsToday: 24 },
  { serial: "RF8N10J56NB", persona: "Tatiana", state: "idle", accountCount: 4, actionsToday: 21 },
  { serial: "53c8e3ad", persona: "Tatiana", state: "recovery", accountCount: 3, actionsToday: 0 },
];

const STATE_STYLES: Record<PhoneState, string> = {
  active: "border-phantom-alive/30 bg-phantom-alive/5 shadow-[0_0_16px_hsl(142_71%_45%/0.1)]",
  warming: "border-phantom-accent/30 bg-phantom-accent/5 shadow-[0_0_16px_hsl(162_100%_54%/0.1)]",
  idle: "border-phantom-border bg-phantom-panel/50",
  cooldown: "border-phantom-amber/30 bg-phantom-amber/5",
  recovery: "border-phantom-magenta/30 bg-phantom-magenta/5",
  offline: "border-phantom-red/30 bg-phantom-red/5",
};

const STATE_LABELS: Record<PhoneState, string> = {
  active: "ACTIVE",
  warming: "WARMING",
  idle: "IDLE",
  cooldown: "COOLDOWN",
  recovery: "RECOVERY",
  offline: "OFFLINE",
};

const STATE_DOTS: Record<PhoneState, string> = {
  active: "phantom-dot-alive",
  warming: "phantom-dot-accent",
  idle: "bg-phantom-ghost/40",
  cooldown: "phantom-dot-warning",
  recovery: "bg-phantom-magenta shadow-[0_0_8px_hsl(292_91%_68%/0.6)]",
  offline: "phantom-dot-critical",
};

export function FleetGrid() {
  return (
    <div className="phantom-panel p-6">
      <div className="flex items-center justify-between mb-5">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Fleet map
          </div>
          <div className="text-lg font-display font-semibold mt-1">
            19 devices · 219 accounts · all phones simultaneous
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-phantom-ghost">
          <span className="flex items-center gap-1.5">
            <span className="phantom-dot phantom-dot-alive" />
            Active
          </span>
          <span className="flex items-center gap-1.5">
            <span className="phantom-dot phantom-dot-accent" />
            Warming
          </span>
          <span className="flex items-center gap-1.5">
            <span className="phantom-dot phantom-dot-warning" />
            Cooldown
          </span>
          <span className="flex items-center gap-1.5">
            <span className="phantom-dot bg-phantom-magenta" />
            Recovery
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
        {DEMO_PHONES.map((p) => (
          <div
            key={p.serial}
            className={cn(
              "p-3 rounded-lg border transition-all cursor-pointer hover:scale-[1.02] hover:brightness-110",
              STATE_STYLES[p.state]
            )}
          >
            <div className="flex items-center justify-between mb-2">
              <span className={cn("phantom-dot", STATE_DOTS[p.state])} />
              <span className="text-[9px] font-mono tracking-wider text-phantom-ghost">
                {STATE_LABELS[p.state]}
              </span>
            </div>
            <div className="font-mono text-[10px] text-phantom-ghost truncate" title={p.serial}>
              {p.serial}
            </div>
            <div className="flex items-baseline gap-1 mt-2">
              <span className="text-xl font-display font-bold tabular-nums">{p.accountCount}</span>
              <span className="text-[10px] text-phantom-ghost">accts</span>
            </div>
            <div className="text-[10px] text-phantom-ghost mt-1">{p.persona}</div>
            <div className="flex items-baseline gap-1 mt-1">
              <span className="text-xs font-mono tabular-nums text-phantom-accent">{p.actionsToday}</span>
              <span className="text-[9px] text-phantom-ghost">actions today</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
