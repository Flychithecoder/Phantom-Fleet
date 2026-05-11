"use client";

import { Bot } from "lucide-react";
import { cn } from "@/lib/utils";

type AgentEvent = {
  id: string;
  agent: string;
  action: string;
  target?: string;
  ts: string;
  status: "success" | "running" | "blocked" | "error";
};

const DEMO_EVENTS: AgentEvent[] = [
  { id: "1", agent: "fingerprint_monitor", action: "scanning 20-dim histogram", ts: "now", status: "running" },
  { id: "2", agent: "source_discovery", action: "scored 47 candidate sources", target: "Tatiana", ts: "2s ago", status: "success" },
  { id: "3", agent: "fresh_target", action: "pulled 2,140 targets for today", target: "Melodie", ts: "18s ago", status: "success" },
  { id: "4", agent: "warming", action: "daily plans issued", target: "219 accts", ts: "45s ago", status: "success" },
  { id: "5", agent: "proxy_orchestrator", action: "rotated IP on block signal", target: "tatianamusee", ts: "1m ago", status: "success" },
  { id: "6", agent: "content", action: "caption rejected (llm tell)", target: "melodieewave", ts: "2m ago", status: "blocked" },
  { id: "7", agent: "dm", action: "replied to 4 inbound", target: "Melodie cohort", ts: "3m ago", status: "success" },
  { id: "8", agent: "funnel_conversion", action: "attributed $49 OF sub", target: "tatianaonfire", ts: "4m ago", status: "success" },
  { id: "9", agent: "recovery", action: "auto-reboot + reauth", target: "RF8N11BB1MN", ts: "6m ago", status: "success" },
  { id: "10", agent: "audit_harness", action: "10K persona simulation", ts: "10m ago", status: "success" },
];

const STATUS_DOT: Record<AgentEvent["status"], string> = {
  success: "phantom-dot-alive",
  running: "phantom-dot-accent animate-phantom-pulse",
  blocked: "phantom-dot-warning",
  error: "phantom-dot-critical",
};

export function AgentFeed() {
  return (
    <div className="phantom-panel flex flex-col h-full max-h-[520px]">
      <div className="p-6 border-b border-phantom-border flex items-center justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Agent mesh · live feed
          </div>
          <div className="text-lg font-display font-semibold mt-1 flex items-center gap-2">
            <Bot className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
            14 agents running
          </div>
        </div>
        <span className="phantom-dot phantom-dot-accent animate-phantom-pulse" />
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
        {DEMO_EVENTS.map((e) => (
          <div key={e.id} className="flex items-start gap-3 text-sm">
            <span className={cn("phantom-dot mt-1.5 shrink-0", STATUS_DOT[e.status])} />
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="font-mono text-[11px] text-phantom-accent">{e.agent}</span>
                <span className="text-white truncate">{e.action}</span>
                {e.target && (
                  <span className="font-mono text-[11px] text-phantom-ghost truncate">
                    › {e.target}
                  </span>
                )}
              </div>
              <div className="text-[10px] text-phantom-ghost mt-0.5">{e.ts}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
