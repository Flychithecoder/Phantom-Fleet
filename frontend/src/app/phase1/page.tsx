"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Rocket, CheckCircle2, AlertCircle, AlertTriangle, Circle, Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";

type GateStatus = "pass" | "warn" | "fail" | "pending";

type Gate = {
  key: string;
  label: string;
  status: GateStatus;
  detail: string;
  blocking: boolean;
};

type Readiness = {
  ready: boolean;
  fleet_size: number;
  gates: Gate[];
  agents_total: number;
  agents_available: number;
  summary: string;
};

type LaunchResult = {
  started: boolean;
  warming_running: boolean;
  agents_started: string[];
  message: string;
};

const STATUS_ICON = {
  pass:    <CheckCircle2 className="w-4 h-4 text-green-400" strokeWidth={1.75} />,
  warn:    <AlertTriangle className="w-4 h-4 text-phantom-amber" strokeWidth={1.75} />,
  fail:    <AlertCircle className="w-4 h-4 text-red-400" strokeWidth={1.75} />,
  pending: <Circle className="w-4 h-4 text-phantom-ghost" strokeWidth={1.75} />,
} as const;

const STATUS_RING = {
  pass:    "border-green-500/30 bg-green-500/5",
  warn:    "border-phantom-amber/40 bg-phantom-amber/5",
  fail:    "border-red-500/40 bg-red-500/5",
  pending: "border-phantom-border bg-phantom-panelHi/30",
} as const;

export default function Phase1Page() {
  const [state, setState] = useState<Readiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [launching, setLaunching] = useState(false);
  const [launchMsg, setLaunchMsg] = useState<string | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);

  const load = useCallback(() => {
    fetch("/api/phase1/readiness")
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
      const r = await fetch("/api/phase1/start", { method: "POST" });
      if (!r.ok) {
        const err = await r.json();
        setLaunchError(
          typeof err?.detail === "object"
            ? (err.detail.summary ?? JSON.stringify(err.detail))
            : String(err?.detail ?? "launch failed"),
        );
      } else {
        const d: LaunchResult = await r.json();
        setLaunchMsg(
          `${d.message}. ${d.agents_started.length} agents enabled: ${d.agents_started.join(", ")}`,
        );
      }
      load();
    } catch (e) {
      setLaunchError(String(e));
    } finally {
      setLaunching(false);
    }
  };

  const blockingBlockers = (state?.gates ?? []).filter(
    (g) => g.blocking && g.status !== "pass",
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Phase 1 · IG MVP
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <Rocket className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          Launch <span className="phantom-accent-text">readiness</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-2xl">
          Every blocking gate must be green before Phase 1 fires. Non-blocking gates
          surface warnings but won&rsquo;t stop the launch — review each one and pull
          the trigger when you&rsquo;re ready.
        </p>
      </div>

      {/* Launch strip */}
      {state && (
        <div className={cn("phantom-panel p-5 flex items-start gap-4 border",
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
            {launching ? "Launching…" : "Start Phase 1"}
          </button>
        </div>
      )}

      {loading && !state && (
        <div className="phantom-panel p-5 flex items-center gap-3 text-phantom-ghost text-sm">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading readiness…
        </div>
      )}

      {/* Summary tiles */}
      {state && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <SummaryTile label="Fleet size" value={state.fleet_size.toString()} tone="accent" />
          <SummaryTile
            label="Agents registered"
            value={`${state.agents_available}/${state.agents_total}`}
            tone={state.agents_available === state.agents_total ? "accent" : "amber"}
          />
          <SummaryTile
            label="Gates passing"
            value={`${state.gates.filter((g) => g.status === "pass").length}/${state.gates.length}`}
            tone="accent"
          />
          <SummaryTile
            label="Blocking issues"
            value={blockingBlockers.length.toString()}
            tone={blockingBlockers.length === 0 ? "accent" : "red"}
          />
        </div>
      )}

      {/* Gates list */}
      {state && (
        <div className="phantom-panel overflow-hidden">
          <div className="px-5 py-3 border-b border-phantom-border bg-phantom-panelHi/40">
            <span className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
              Readiness gates
            </span>
          </div>
          <div className="divide-y divide-phantom-border/30">
            {state.gates.map((g) => (
              <div
                key={g.key}
                className={cn(
                  "px-5 py-3 flex items-start gap-3 border-l-2 transition-colors",
                  g.status === "pass" ? "border-l-green-500/60" :
                  g.status === "warn" ? "border-l-phantom-amber/60" :
                  g.status === "fail" ? "border-l-red-500/60" :
                  "border-l-phantom-border",
                )}
              >
                <div className={cn(
                  "w-7 h-7 rounded-md flex items-center justify-center shrink-0 border",
                  STATUS_RING[g.status],
                )}>
                  {STATUS_ICON[g.status]}
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

function SummaryTile({
  label, value, tone,
}: {
  label: string;
  value: string;
  tone: "accent" | "amber" | "red";
}) {
  const tc =
    tone === "red"   ? "text-red-400" :
    tone === "amber" ? "text-phantom-amber" :
                       "text-phantom-accent";
  return (
    <div className="phantom-panel p-4">
      <div className={cn("text-2xl font-display font-bold tabular-nums", tc)}>{value}</div>
      <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em] mt-0.5">{label}</div>
    </div>
  );
}
