"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Rocket, CheckCircle2, AlertCircle, AlertTriangle, Circle, Loader2,
  MessageCircle, Film, Flame, Ghost, Hash, Instagram,
} from "lucide-react";
import { cn } from "@/lib/utils";

type GateStatus = "pass" | "warn" | "fail" | "pending";

type PlatformStatus = "scaffold" | "primitives" | "warming" | "ready";

type PlatformGate = {
  key: string;
  label: string;
  status: PlatformStatus;
  account_source: string;
  warming_days: number;
  account_count: number;
  detail: string;
  blocking: boolean;
};

type Gate = {
  key: string;
  label: string;
  status: GateStatus;
  detail: string;
  blocking: boolean;
};

type Readiness = {
  ready: boolean;
  phase1_ready: boolean;
  platforms: PlatformGate[];
  gates: Gate[];
  agents_total: number;
  agents_available: number;
  summary: string;
};

const PLATFORM_ICON: Record<string, React.ReactNode> = {
  threads:  <MessageCircle className="w-5 h-5" strokeWidth={1.75} />,
  reddit:   <Hash className="w-5 h-5" strokeWidth={1.75} />,
  tiktok:   <Film className="w-5 h-5" strokeWidth={1.75} />,
  snapchat: <Ghost className="w-5 h-5" strokeWidth={1.75} />,
  x:        <Hash className="w-5 h-5" strokeWidth={1.75} />,
  instagram: <Instagram className="w-5 h-5" strokeWidth={1.75} />,
};

const GATE_ICON: Record<GateStatus, React.ReactNode> = {
  pass:    <CheckCircle2 className="w-4 h-4 text-green-400" strokeWidth={1.75} />,
  warn:    <AlertTriangle className="w-4 h-4 text-phantom-amber" strokeWidth={1.75} />,
  fail:    <AlertCircle className="w-4 h-4 text-red-400" strokeWidth={1.75} />,
  pending: <Circle className="w-4 h-4 text-phantom-ghost" strokeWidth={1.75} />,
};

const PLATFORM_STATUS_COLOR: Record<PlatformStatus, string> = {
  scaffold:   "bg-phantom-panelHi text-phantom-ghost border-phantom-border",
  primitives: "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/30",
  warming:    "bg-sky-500/10 text-sky-300 border-sky-500/30",
  ready:      "bg-green-500/15 text-green-400 border-green-500/30",
};

export default function Phase2Page() {
  const [state, setState] = useState<Readiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [launching, setLaunching] = useState(false);
  const [launchMsg, setLaunchMsg] = useState<string | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);

  const load = useCallback(() => {
    fetch("/api/phase2/readiness")
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((d: Readiness) => setState(d))
      .catch(() => setState(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15_000);
    return () => clearInterval(t);
  }, [load]);

  const launch = async () => {
    setLaunching(true);
    setLaunchMsg(null);
    setLaunchError(null);
    try {
      const r = await fetch("/api/phase2/start", { method: "POST" });
      const d = await r.json();
      if (!r.ok) {
        setLaunchError(
          typeof d?.detail === "object"
            ? (d.detail.summary ?? JSON.stringify(d.detail))
            : String(d?.detail ?? "launch failed"),
        );
      } else {
        setLaunchMsg(d.message ?? "Phase 2 launched.");
      }
      load();
    } catch (e) {
      setLaunchError(String(e));
    } finally {
      setLaunching(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Phase 2 · Parity expansion (Weeks 7-12)
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <Rocket className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          Parity <span className="phantom-accent-text">roster</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-2xl">
          Threads, Reddit, TikTok, Snapchat, X/Twitter — plus DM, Content and
          Funnel agents cross-platform. Phase 2 unlocks once Phase 1 is live
          and the fleet + proxy farm hit scale.
        </p>
      </div>

      {/* Launch strip */}
      {state && (
        <div className={cn(
          "phantom-panel p-5 flex items-start gap-4 border",
          state.ready
            ? "border-green-500/30 bg-green-500/5"
            : "border-red-500/30 bg-red-500/5",
        )}>
          <div className={cn(
            "w-12 h-12 rounded-xl flex items-center justify-center shrink-0 border",
            state.ready
              ? "bg-green-500/15 border-green-500/30"
              : "bg-red-500/15 border-red-500/30",
          )}>
            <Rocket className={cn("w-6 h-6", state.ready ? "text-green-400" : "text-red-400")} strokeWidth={1.75} />
          </div>
          <div className="flex-1 min-w-0">
            <div className={cn("font-semibold text-base",
              state.ready ? "text-green-400" : "text-red-400")}>
              {state.ready ? "Cleared for launch" : "Launch blocked"}
            </div>
            <div className="text-xs text-phantom-ghost mt-1">{state.summary}</div>
            {!state.phase1_ready && (
              <div className="text-[11px] text-red-400 mt-2 font-mono">
                Phase 1 is not cleared — Phase 2 can&rsquo;t launch until Phase 1 is live.
              </div>
            )}
            {launchMsg && (
              <div className="text-xs text-green-400 mt-2 font-mono">{launchMsg}</div>
            )}
            {launchError && (
              <div className="text-xs text-red-400 mt-2 font-mono">{launchError}</div>
            )}
          </div>
          <button
            onClick={launch}
            disabled={!state.ready || launching}
            className={cn(
              "flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold border transition-colors",
              state.ready
                ? "bg-green-500/15 text-green-400 border-green-500/30 hover:bg-green-500/25"
                : "bg-phantom-panelHi text-phantom-ghost border-phantom-border cursor-not-allowed",
              launching && "opacity-70",
            )}
          >
            {launching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Rocket className="w-4 h-4" strokeWidth={2} />}
            {launching ? "Launching…" : "Start Phase 2"}
          </button>
        </div>
      )}

      {loading && !state && (
        <div className="phantom-panel p-5 flex items-center gap-3 text-phantom-ghost text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading readiness…
        </div>
      )}

      {/* Platform cards */}
      {state && (
        <div>
          <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-2">
            Platform roster
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {state.platforms.map((p) => (
              <div key={p.key} className="phantom-panel p-4 flex flex-col gap-2">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-phantom-panelHi border border-phantom-border flex items-center justify-center text-phantom-accent shrink-0">
                    {PLATFORM_ICON[p.key] ?? <Hash className="w-5 h-5" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold">{p.label}</div>
                    <div className="text-[10px] text-phantom-ghost uppercase tracking-wider">
                      {p.account_source.replace("_", " ")} · warm {p.warming_days}d
                    </div>
                  </div>
                  <span className={cn(
                    "text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded border",
                    PLATFORM_STATUS_COLOR[p.status],
                  )}>
                    {p.status}
                  </span>
                </div>
                <div className="text-xs text-phantom-ghost">{p.detail}</div>
                <div className="flex items-center justify-between mt-1">
                  <span className="text-[10px] text-phantom-ghost uppercase tracking-wider">
                    Accounts
                  </span>
                  <span className={cn(
                    "text-sm font-display font-bold tabular-nums",
                    p.account_count > 0 ? "text-phantom-accent" : "text-phantom-ghost",
                  )}>
                    {p.account_count}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Cross-cutting gates */}
      {state && (
        <div className="phantom-panel overflow-hidden">
          <div className="px-5 py-3 border-b border-phantom-border bg-phantom-panelHi/40">
            <span className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
              Cross-cutting gates
            </span>
          </div>
          <div className="divide-y divide-phantom-border/30">
            {state.gates.map((g) => (
              <div
                key={g.key}
                className={cn(
                  "px-5 py-3 flex items-start gap-3 border-l-2",
                  g.status === "pass" ? "border-l-green-500/60" :
                  g.status === "warn" ? "border-l-phantom-amber/60" :
                  g.status === "fail" ? "border-l-red-500/60" :
                  "border-l-phantom-border",
                )}
              >
                <div className="w-7 h-7 rounded-md flex items-center justify-center shrink-0 border border-phantom-border bg-phantom-panelHi/30">
                  {GATE_ICON[g.status]}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-white">{g.label}</span>
                    {g.blocking && (
                      <span className="text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded border border-phantom-border bg-phantom-panelHi text-phantom-ghost">
                        Blocking
                      </span>
                    )}
                    <span className={cn(
                      "text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded",
                      g.status === "pass" ? "text-green-400 bg-green-500/10" :
                      g.status === "warn" ? "text-phantom-amber bg-phantom-amber/10" :
                      g.status === "fail" ? "text-red-400 bg-red-500/10" :
                      "text-phantom-ghost bg-phantom-panelHi",
                    )}>
                      {g.status}
                    </span>
                  </div>
                  <div className="text-xs text-phantom-ghost mt-1">{g.detail}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
