import Link from "next/link";
import { cn } from "@/lib/utils";
import { Smartphone } from "lucide-react";

export type PhoneState = "OFFLINE" | "ONLINE" | "PROXY_READY" | "BUSY";

export type PhoneCardData = {
  serial: string;
  model?: string;
  androidVersion?: string;
  state: PhoneState;
  platformCount: number;
  accountCount: number;
  proxyAssigned?: boolean;
  actionsToday?: number;
};

const STATE_STYLES: Record<PhoneState, string> = {
  OFFLINE: "border-phantom-red/30 bg-phantom-red/5",
  ONLINE: "border-yellow-400/30 bg-yellow-400/5",
  PROXY_READY: "border-phantom-accent/30 bg-phantom-accent/5 shadow-[0_0_16px_hsl(162_100%_54%/0.08)]",
  BUSY: "border-blue-400/30 bg-blue-400/5",
};

const STATE_DOT: Record<PhoneState, string> = {
  OFFLINE: "phantom-dot-critical",
  ONLINE: "bg-yellow-400 shadow-[0_0_8px_hsl(50_100%_50%/0.6)]",
  PROXY_READY: "phantom-dot-accent animate-phantom-pulse",
  BUSY: "bg-blue-400 shadow-[0_0_8px_hsl(210_100%_65%/0.6)]",
};

const STATE_LABEL_STYLES: Record<PhoneState, string> = {
  OFFLINE: "text-phantom-red",
  ONLINE: "text-yellow-400",
  PROXY_READY: "text-phantom-accent",
  BUSY: "text-blue-400",
};

export function PhoneCard({ phone }: { phone: PhoneCardData }) {
  return (
    <Link
      href={`/fleet/${phone.serial}`}
      className={cn(
        "block p-4 rounded-xl border transition-all duration-200 hover:scale-[1.02] hover:brightness-110 group",
        STATE_STYLES[phone.state]
      )}
    >
      {/* Status row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={cn("phantom-dot shrink-0", STATE_DOT[phone.state])} />
          <span className={cn("text-[10px] font-mono tracking-wider font-semibold", STATE_LABEL_STYLES[phone.state])}>
            {phone.state}
          </span>
        </div>
        <Smartphone className="w-3.5 h-3.5 text-phantom-ghost/40 group-hover:text-phantom-ghost transition-colors" strokeWidth={1.75} />
      </div>

      {/* Serial */}
      <div className="font-mono text-[10px] text-phantom-ghost truncate mb-3" title={phone.serial}>
        {phone.serial}
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <div className="text-xl font-display font-bold tabular-nums leading-none">
            {phone.platformCount}
          </div>
          <div className="text-[10px] text-phantom-ghost mt-0.5">platforms</div>
        </div>
        <div>
          <div className="text-xl font-display font-bold tabular-nums leading-none text-phantom-accent">
            {phone.accountCount}
          </div>
          <div className="text-[10px] text-phantom-ghost mt-0.5">accounts</div>
        </div>
      </div>

      {/* Model if present */}
      {phone.model && (
        <div className="mt-2.5 text-[10px] text-phantom-ghost/60 truncate">{phone.model}</div>
      )}
    </Link>
  );
}
