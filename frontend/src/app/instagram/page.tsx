"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  Instagram, Heart, HeartCrack, Ghost, AlertTriangle, CheckCircle2,
  RefreshCw, Activity, Clock, Link2, Snowflake, Flame, GraduationCap,
  XOctagon, RotateCw, Play, TrendingUp, Zap, Search, Hash, Compass,
  FlaskConical, ShieldCheck, Sun, Moon, CloudSun, Fingerprint, AlertOctagon,
  Globe, Lock, Unlock, Smartphone, GitBranch, Network, ShieldAlert, KeyRound,
  LogIn, Timer, UserMinus, Users, MessageSquare, Send, Ban,
} from "lucide-react";
import { cn } from "@/lib/utils";

type IGStatus = "healthy" | "watch" | "at_risk" | "shadowbanned";

type IGHealthRecord = {
  account_id: string;
  status: IGStatus;
  score: number;
  flags: string[];
  signals: {
    warmup_day: number;
    posts_in_ring: number;
    posts_last_48h: number;
    hours_since_last_post: number;
    has_threads_link: boolean;
    bridge_skipped_recent: number;
    bridge_queued_recent: number;
  };
  computed_at: string;
};

type IGHealthSummary = {
  rollup: {
    healthy: number; watch: number; at_risk: number; shadowbanned: number;
    total: number; last_scan_at: string | null; total_scans: number;
  };
  at_risk: IGHealthRecord[];
  flag_counts: Record<string, number>;
};

const STATUS_STYLES: Record<IGStatus, { bg: string; text: string; icon: React.ElementType }> = {
  healthy:      { bg: "border-green-500/30",       text: "text-green-400",       icon: Heart },
  watch:        { bg: "border-phantom-amber/40",   text: "text-phantom-amber",   icon: Activity },
  at_risk:      { bg: "border-orange-500/40",      text: "text-orange-400",      icon: AlertTriangle },
  shadowbanned: { bg: "border-red-500/50",         text: "text-red-400",         icon: Ghost },
};

const SCENARIOS: Array<{ label: string; signals: Partial<IGHealthRecord["signals"]> }> = [
  { label: "Fresh day-2", signals: { warmup_day: 2, posts_in_ring: 1, posts_last_48h: 1, hours_since_last_post: 6, has_threads_link: true } },
  { label: "Cadence collapse", signals: { warmup_day: 9, posts_in_ring: 4, posts_last_48h: 0, hours_since_last_post: 60, has_threads_link: true } },
  { label: "No Threads link", signals: { warmup_day: 10, posts_in_ring: 6, posts_last_48h: 3, hours_since_last_post: 4, has_threads_link: false } },
  { label: "Engagement ghost", signals: { warmup_day: 11, posts_in_ring: 8, posts_last_48h: 3, hours_since_last_post: 2, has_threads_link: true, bridge_skipped_recent: 8, bridge_queued_recent: 0 } },
  { label: "Dark account", signals: { warmup_day: 12, posts_in_ring: 10, posts_last_48h: 0, hours_since_last_post: 72, has_threads_link: false, bridge_skipped_recent: 10, bridge_queued_recent: 0 } },
];

type IGRecoveryRecord = {
  account_id: string;
  phase: "cooling_down" | "rewarming" | "graduated" | "retired";
  strikes: number;
  entered_at: string;
  cool_down_until: string;
  original_warmup_day: number;
  rewarm_actions_observed: number;
  graduated_at: string | null;
  retired_at: string | null;
  notes: string[];
};

type IGRecoveryStatus = {
  running: boolean;
  stats: {
    total_enrolled: number; total_graduated: number; total_retired: number;
    cooling_down: number; rewarming: number;
    last_tick_at: string | null; total_ticks: number;
  };
  config: {
    tick_sec: number; cool_down_sec: number;
    rewarm_posts_to_graduate: number; max_strikes: number;
  };
  records: IGRecoveryRecord[];
};

const PHASE_STYLES = {
  cooling_down: { icon: Snowflake, text: "text-sky-400",    bg: "border-sky-500/30" },
  rewarming:    { icon: Flame,     text: "text-orange-400", bg: "border-orange-500/30" },
  graduated:    { icon: GraduationCap, text: "text-green-400", bg: "border-green-500/30" },
  retired:      { icon: XOctagon,  text: "text-red-400",    bg: "border-red-500/40" },
} as const;

export default function InstagramPage() {
  const [summary, setSummary] = useState<IGHealthSummary | null>(null);
  const [scanning, setScanning] = useState(false);
  const [simResult, setSimResult] = useState<IGHealthRecord | null>(null);
  const [recovery, setRecovery] = useState<IGRecoveryStatus | null>(null);
  const [ticking, setTicking] = useState(false);
  const [funnel, setFunnel] = useState<any>(null);
  const [probes, setProbes] = useState<any>(null);
  const [agentCfg, setAgentCfg] = useState<any>(null);
  const [agentRuns, setAgentRuns] = useState<any>(null);
  const [executor, setExecutor] = useState<any>(null);
  const [diurnal, setDiurnal] = useState<any>(null);
  const [identity, setIdentity] = useState<any>(null);
  const [proxy, setProxy] = useState<any>(null);
  const [drift, setDrift] = useState<any>(null);
  const [lattice, setLattice] = useState<any>(null);
  const [checkpoint, setCheckpoint] = useState<any>(null);
  const [session, setSession] = useState<any>(null);
  const [unfollow, setUnfollow] = useState<any>(null);
  const [dm, setDm] = useState<any>(null);
  const [orch, setOrch] = useState<any>(null);
  const [planning, setPlanning] = useState(false);
  const [rebalancer, setRebalancer] = useState<any>(null);

  const load = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/health/summary").then((r) => r.json());
      setSummary(d as IGHealthSummary);
    } catch {}
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);

  const loadRecovery = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/recovery/status").then((r) => r.json());
      setRecovery(d as IGRecoveryStatus);
    } catch {}
  }, []);
  useEffect(() => {
    loadRecovery();
    const t = setInterval(loadRecovery, 5000);
    return () => clearInterval(t);
  }, [loadRecovery]);

  const tickRecovery = useCallback(async () => {
    setTicking(true);
    try {
      await fetch("/api/platforms/instagram/recovery/tick", { method: "POST" });
      await loadRecovery();
    } finally {
      setTicking(false);
    }
  }, [loadRecovery]);

  const graduate = useCallback(async (acc: string) => {
    await fetch(`/api/platforms/instagram/recovery/${acc}/graduate`, { method: "POST" });
    await loadRecovery();
  }, [loadRecovery]);

  const loadFunnel = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/funnel/summary").then((r) => r.json());
      setFunnel(d);
    } catch {}
  }, []);
  useEffect(() => { loadFunnel(); const t = setInterval(loadFunnel, 5000); return () => clearInterval(t); }, [loadFunnel]);

  const loadRebalancer = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/rebalancer/status").then((r) => r.json());
      setRebalancer(d);
    } catch {}
  }, []);
  useEffect(() => { loadRebalancer(); const t = setInterval(loadRebalancer, 5000); return () => clearInterval(t); }, [loadRebalancer]);

  const loadOrch = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/orchestrator/status").then((r) => r.json());
      setOrch(d);
    } catch {}
  }, []);
  useEffect(() => { loadOrch(); const t = setInterval(loadOrch, 5000); return () => clearInterval(t); }, [loadOrch]);

  const planNow = useCallback(async () => {
    setPlanning(true);
    try {
      await fetch("/api/platforms/instagram/orchestrator/plan-now", { method: "POST" });
      await loadOrch();
    } finally { setPlanning(false); }
  }, [loadOrch]);

  const loadProbes = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/probes/status?limit=20").then((r) => r.json());
      setProbes(d);
    } catch {}
  }, []);
  useEffect(() => { loadProbes(); const t = setInterval(loadProbes, 6000); return () => clearInterval(t); }, [loadProbes]);

  const loadAgent = useCallback(async () => {
    try {
      const [cfg, runs] = await Promise.all([
        fetch("/api/platforms/instagram/agent/config").then((r) => r.json()),
        fetch("/api/platforms/instagram/agent/runs?limit=12").then((r) => r.json()),
      ]);
      setAgentCfg(cfg); setAgentRuns(runs);
    } catch {}
  }, []);
  useEffect(() => { loadAgent(); const t = setInterval(loadAgent, 5000); return () => clearInterval(t); }, [loadAgent]);

  const loadExecutor = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/executor/status").then((r) => r.json());
      setExecutor(d);
    } catch {}
  }, []);
  useEffect(() => { loadExecutor(); const t = setInterval(loadExecutor, 3000); return () => clearInterval(t); }, [loadExecutor]);
  const loadDiurnal = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/diurnal/summary").then((r) => r.json());
      setDiurnal(d);
    } catch {}
  }, []);
  useEffect(() => { loadDiurnal(); const t = setInterval(loadDiurnal, 30000); return () => clearInterval(t); }, [loadDiurnal]);

  const loadIdentity = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/identity/summary").then((r) => r.json());
      setIdentity(d);
    } catch {}
  }, []);
  useEffect(() => { loadIdentity(); const t = setInterval(loadIdentity, 10000); return () => clearInterval(t); }, [loadIdentity]);
  const rescanIdentity = useCallback(async () => {
    await fetch("/api/platforms/instagram/identity/scan", { method: "POST" });
    await loadIdentity();
  }, [loadIdentity]);

  const loadProxy = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/proxy/summary").then((r) => r.json());
      setProxy(d);
    } catch {}
  }, []);
  useEffect(() => { loadProxy(); const t = setInterval(loadProxy, 8000); return () => clearInterval(t); }, [loadProxy]);
  const tickProxy = useCallback(async () => {
    await fetch("/api/platforms/instagram/proxy/tick", { method: "POST" });
    await loadProxy();
  }, [loadProxy]);
  const rotateProxy = useCallback(async (accountId: string) => {
    await fetch(`/api/platforms/instagram/proxy/${accountId}/rotate`, { method: "POST" });
    await loadProxy();
  }, [loadProxy]);

  const loadDrift = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/drift/summary").then((r) => r.json());
      setDrift(d);
    } catch {}
  }, []);
  useEffect(() => { loadDrift(); const t = setInterval(loadDrift, 8000); return () => clearInterval(t); }, [loadDrift]);
  const scanDrift = useCallback(async () => {
    await fetch("/api/platforms/instagram/drift/scan", { method: "POST" });
    await loadDrift();
  }, [loadDrift]);
  const snapshotDrift = useCallback(async (serial: string) => {
    await fetch(`/api/platforms/instagram/drift/${encodeURIComponent(serial)}/snapshot`, { method: "POST" });
    await loadDrift();
  }, [loadDrift]);

  const loadLattice = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/lattice/summary").then((r) => r.json());
      setLattice(d);
    } catch {}
  }, []);
  useEffect(() => { loadLattice(); const t = setInterval(loadLattice, 8000); return () => clearInterval(t); }, [loadLattice]);
  const planLattice = useCallback(async () => {
    await fetch("/api/platforms/instagram/lattice/plan", { method: "POST" });
    await loadLattice();
  }, [loadLattice]);

  const loadCheckpoint = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/checkpoint/summary").then((r) => r.json());
      setCheckpoint(d);
    } catch {}
  }, []);
  useEffect(() => { loadCheckpoint(); const t = setInterval(loadCheckpoint, 8000); return () => clearInterval(t); }, [loadCheckpoint]);

  const loadSession = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/session/summary").then((r) => r.json());
      setSession(d);
    } catch {}
  }, []);
  useEffect(() => { loadSession(); const t = setInterval(loadSession, 8000); return () => clearInterval(t); }, [loadSession]);
  const tickSession = useCallback(async () => {
    await fetch("/api/platforms/instagram/session/tick", { method: "POST" });
    await loadSession();
  }, [loadSession]);
  const complete2fa = useCallback(async (aid: string) => {
    await fetch(`/api/platforms/instagram/session/${aid}/complete-2fa`, { method: "POST" });
    await loadSession();
  }, [loadSession]);

  const loadUnfollow = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/unfollow/summary").then((r) => r.json());
      setUnfollow(d);
    } catch {}
  }, []);
  useEffect(() => { loadUnfollow(); const t = setInterval(loadUnfollow, 8000); return () => clearInterval(t); }, [loadUnfollow]);
  const tickUnfollow = useCallback(async () => {
    await fetch("/api/platforms/instagram/unfollow/tick", { method: "POST" });
    await loadUnfollow();
  }, [loadUnfollow]);
  const loadDm = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/instagram/dm/summary").then((r) => r.json());
      setDm(d);
    } catch {}
  }, []);
  useEffect(() => { loadDm(); const t = setInterval(loadDm, 8000); return () => clearInterval(t); }, [loadDm]);
  const tickDm = useCallback(async () => {
    await fetch("/api/platforms/instagram/dm/tick", { method: "POST" });
    await loadDm();
  }, [loadDm]);

  const toggleExecutor = useCallback(async () => {
    const url = executor?.running ? "/api/platforms/instagram/executor/stop" : "/api/platforms/instagram/executor/start";
    await fetch(url, { method: "POST" });
    await loadExecutor();
  }, [executor, loadExecutor]);

  const tickProbes = useCallback(async () => {
    await fetch("/api/platforms/instagram/probes/tick", { method: "POST" });
    await loadProbes();
  }, [loadProbes]);

  const fireFunnelDemo = useCallback(async () => {
    const seq = [
      { kind: "post_posted",    n: 1  },
      { kind: "impression",     n: 80 },
      { kind: "profile_view",   n: 12 },
      { kind: "bio_link_click", n: 3  },
      { kind: "threads_tap",    n: 2  },
    ];
    for (const { kind, n } of seq) {
      for (let i = 0; i < n; i++) {
        await fetch("/api/platforms/instagram/funnel/record", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind, ig_account_id: "demo-ig-funnel" }),
        });
      }
    }
    await loadFunnel();
  }, [loadFunnel]);

  const skipCooldown = useCallback(async (acc: string) => {
    await fetch(`/api/platforms/instagram/recovery/${acc}/skip-cooldown`, { method: "POST" });
    await loadRecovery();
  }, [loadRecovery]);

  const scan = useCallback(async () => {
    setScanning(true);
    try {
      await fetch("/api/platforms/instagram/health/scan", { method: "POST" });
      await load();
    } finally {
      setScanning(false);
    }
  }, [load]);

  const runScenario = useCallback(async (sig: Partial<IGHealthRecord["signals"]>) => {
    const body = {
      warmup_day: 1, posts_in_ring: 0, posts_last_48h: 0,
      hours_since_last_post: 0, has_threads_link: true,
      bridge_skipped_recent: 0, bridge_queued_recent: 0,
      ...sig,
    };
    const d = await fetch("/api/platforms/instagram/health/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json());
    setSimResult({
      account_id: "simulate",
      status: d.status,
      score: d.score,
      flags: d.flags,
      signals: d.signals,
      computed_at: new Date().toISOString(),
    });
  }, []);

  const r = summary?.rollup;

  return (
    <div className="p-6 space-y-5 max-w-[1400px] mx-auto">
      <div className="flex items-center gap-3">
        <Instagram className="w-6 h-6 text-pink-400" />
        <div>
          <h1 className="text-xl font-bold text-phantom-mist">Instagram</h1>
          <p className="text-[11px] text-phantom-ghost font-mono">
            Phase 2 · health detector live · scan {r?.total_scans ?? 0} · last {r?.last_scan_at ? new Date(r.last_scan_at).toLocaleTimeString() : "—"}
          </p>
        </div>
        <button
          onClick={scan}
          disabled={scanning}
          className="ml-auto phantom-btn flex items-center gap-2 text-xs"
        >
          <RefreshCw className={cn("w-4 h-4", scanning && "animate-spin")} />
          Rescan now
        </button>
      </div>

      {/* Fleet rebalancer banner */}
      {rebalancer && (
        <div className={cn(
          "phantom-panel p-3 flex items-center gap-3 flex-wrap text-[11px] font-mono",
          rebalancer.stats.level === "green" && "border-green-500/30",
          rebalancer.stats.level === "yellow" && "border-phantom-amber/40",
          rebalancer.stats.level === "red" && "border-red-500/50",
        )}>
          <ShieldCheck className={cn("w-4 h-4",
            rebalancer.stats.level === "green" && "text-green-400",
            rebalancer.stats.level === "yellow" && "text-phantom-amber",
            rebalancer.stats.level === "red" && "text-red-400",
          )} />
          <span className={cn("uppercase tracking-wider font-bold",
            rebalancer.stats.level === "green" && "text-green-400",
            rebalancer.stats.level === "yellow" && "text-phantom-amber",
            rebalancer.stats.level === "red" && "text-red-400",
          )}>
            IG fleet rebalancer · {rebalancer.stats.level}
          </span>
          <span className="text-phantom-ghost">plan ×{rebalancer.throttles.plan_per_tick_multiplier.toFixed(2)}</span>
          <span className="text-phantom-ghost">·</span>
          <span className="text-phantom-ghost">linking {rebalancer.throttles.linking_allowed ? "allowed" : "paused"}</span>
          <span className="text-phantom-ghost">·</span>
          <span className="text-phantom-ghost">shadowban {((rebalancer.snapshot?.shadowban_rate ?? 0) * 100).toFixed(0)}%</span>
          <span className="text-phantom-ghost">·</span>
          <span className="text-phantom-ghost">hidden {((rebalancer.snapshot?.hidden_rate ?? 0) * 100).toFixed(0)}%</span>
          <span className="text-phantom-ghost">·</span>
          <span className="text-phantom-ghost">enroll burst {rebalancer.snapshot?.enrollment_burst ?? 0}</span>
          <span className="text-phantom-ghost">·</span>
          <span className="text-phantom-ghost">ticks {rebalancer.stats.total_ticks}</span>
          <span className="text-phantom-ghost">·</span>
          <span className="text-phantom-ghost">alerts {rebalancer.stats.total_alerts}</span>
        </div>
      )}

      {/* Rollup tiles */}
      <div className="grid grid-cols-4 gap-3">
        {(["healthy", "watch", "at_risk", "shadowbanned"] as IGStatus[]).map((s) => {
          const style = STATUS_STYLES[s];
          const Icon = style.icon;
          const count = r ? r[s] : 0;
          return (
            <div key={s} className={cn("phantom-panel p-4", style.bg)}>
              <div className={cn("flex items-center gap-2 text-[10px] uppercase tracking-wider font-mono", style.text)}>
                <Icon className="w-4 h-4" />
                {s.replace("_", " ")}
              </div>
              <div className={cn("text-3xl font-bold mt-1", style.text)}>{count}</div>
              <div className="text-[10px] text-phantom-ghost font-mono mt-1">
                of {r?.total ?? 0} active
              </div>
            </div>
          );
        })}
      </div>

      {/* Flag chips */}
      <div className="phantom-panel p-4">
        <div className="text-[10px] uppercase tracking-wider text-phantom-ghost font-mono mb-2">
          Flags firing (fleet-wide)
        </div>
        <div className="flex gap-2 flex-wrap">
          {summary && Object.keys(summary.flag_counts).length === 0 && (
            <span className="text-[11px] text-phantom-ghost">No flags lit. Every IG account in the healthy / watch band.</span>
          )}
          {summary && Object.entries(summary.flag_counts).map(([flag, n]) => (
            <span key={flag} className="px-2 py-1 bg-phantom-charcoal/60 border border-phantom-amber/30 text-phantom-amber text-[10px] font-mono rounded">
              {flag} · {n}
            </span>
          ))}
        </div>
      </div>

      {/* Orchestrator */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <Activity className="w-4 h-4 text-pink-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            IG orchestrator
          </span>
          {orch?.running && (
            <span className="px-2 py-0.5 bg-green-500/10 border border-green-500/30 text-green-400 text-[10px] font-mono rounded">RUNNING</span>
          )}
          <span className="text-[10px] text-phantom-ghost font-mono">
            tick {orch?.tick_sec ?? "?"}s · plan ≤ {orch?.plan_per_tick ?? "?"} per tick · runs {orch?.total_runs ?? 0} · enqueued {orch?.total_enqueued ?? 0}
          </span>
          <button onClick={planNow} disabled={planning} className="ml-auto phantom-btn flex items-center gap-2 text-xs">
            <Play className={cn("w-3 h-3", planning && "animate-pulse")} /> Plan now
          </button>
        </div>
        {orch?.last_plan && orch.last_plan.length > 0 ? (
          <div className="space-y-1">
            {orch.last_plan.map((p: any) => (
              <div key={p.account_id + p.kind} className="flex items-center gap-3 text-[11px] font-mono py-1 border-b border-phantom-charcoal/40">
                <span className="text-pink-400 uppercase tracking-wider w-24">{p.kind}</span>
                <Link href={`/instagram/${p.account_id}`} className="text-phantom-emerald hover:underline w-40 truncate">{p.account_id}</Link>
                <span className="text-phantom-ghost w-40 truncate">{p.target || "—"}</span>
                <span className="text-phantom-ghost flex-1 truncate">{p.reason}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[11px] text-phantom-ghost">No plan yet. Click "Plan now" once IG accounts are seeded with warmup day &gt; 0.</div>
        )}
      </div>

      {/* At-risk table */}
      <div className="phantom-panel p-4">
        <div className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono mb-3 flex items-center gap-2">
          <HeartCrack className="w-4 h-4 text-orange-400" />
          At-risk & shadowbanned accounts
        </div>
        {summary && summary.at_risk.length === 0 ? (
          <div className="text-[11px] text-phantom-ghost">Nothing in the watch/at-risk/shadowbanned band. Fleet IG side is clean.</div>
        ) : (
          <div className="space-y-1">
            {summary?.at_risk.map((h) => {
              const style = STATUS_STYLES[h.status];
              return (
                <div key={h.account_id} className="flex items-center gap-3 text-[11px] font-mono py-1 border-b border-phantom-charcoal/40">
                  <span className={cn("uppercase tracking-wider w-24", style.text)}>{h.status}</span>
                  <Link href={`/instagram/${h.account_id}`} className="text-phantom-emerald hover:underline w-40 truncate">{h.account_id}</Link>
                  <span className={cn("w-12 text-right font-bold", style.text)}>{h.score}</span>
                  <span className="text-phantom-ghost flex items-center gap-1"><Clock className="w-3 h-3" />day {h.signals.warmup_day}</span>
                  <span className="text-phantom-ghost">posts {h.signals.posts_in_ring}/48h {h.signals.posts_last_48h}</span>
                  <span className="text-phantom-ghost flex items-center gap-1">
                    <Link2 className="w-3 h-3" />
                    {h.signals.has_threads_link ? "linked" : "no link"}
                  </span>
                  <span className="text-phantom-ghost flex-1 truncate">{h.flags.join(" · ")}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Active probes panel */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <FlaskConical className="w-4 h-4 text-purple-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            IG active probes · handle search · hashtag page · explore surface
          </span>
          {probes?.running && (
            <span className="px-2 py-0.5 bg-green-500/10 border border-green-500/30 text-green-400 text-[10px] font-mono rounded">RUNNING</span>
          )}
          <span className="text-[10px] text-phantom-ghost font-mono">
            tick 120s · penalties 20/30/45 · hidden merged into health
          </span>
          <button onClick={tickProbes} className="ml-auto phantom-btn flex items-center gap-2 text-xs">
            <Play className="w-3 h-3" /> Sweep now
          </button>
        </div>
        <div className="grid grid-cols-4 gap-3 mb-3">
          {([
            { label: "runs",     value: probes?.stats.total_run ?? 0,    icon: Play,       color: "text-sky-400",     bg: "border-sky-500/30" },
            { label: "found",    value: probes?.stats.total_found ?? 0,  icon: CheckCircle2, color: "text-green-400", bg: "border-green-500/30" },
            { label: "hidden",   value: probes?.stats.total_hidden ?? 0, icon: Ghost,      color: "text-red-400",     bg: "border-red-500/30" },
            { label: "hidden %", value: ((probes?.stats.hidden_rate ?? 0) * 100).toFixed(1) + "%", icon: AlertTriangle, color: "text-phantom-amber", bg: "border-phantom-amber/30" },
          ] as const).map(({ label, value, icon: Icon, color, bg }) => (
            <div key={label} className={cn("phantom-panel p-3", bg)}>
              <div className={cn("flex items-center gap-1 text-[10px] uppercase tracking-wider font-mono", color)}>
                <Icon className="w-3 h-3" /> {label}
              </div>
              <div className={cn("text-2xl font-bold mt-1", color)}>{value}</div>
            </div>
          ))}
        </div>
        {probes && probes.recent && probes.recent.length > 0 ? (
          <div className="space-y-1">
            {probes.recent.slice(0, 10).map((r: any) => {
              const KindIcon = r.kind === "handle_search" ? Search : r.kind === "hashtag_page" ? Hash : Compass;
              return (
                <div key={r.probe_id} className="flex items-center gap-3 text-[11px] font-mono py-1 border-b border-phantom-charcoal/40">
                  <KindIcon className="w-3 h-3 text-purple-400" />
                  <span className="text-phantom-mist w-28 truncate">{r.kind}</span>
                  <span className="text-phantom-ghost w-32 truncate">{r.account_id}</span>
                  <span className="text-phantom-ghost w-32 truncate">via {r.searcher_id}</span>
                  <span className={cn(r.found ? "text-green-400" : "text-red-400", "w-16 font-bold")}>{r.found ? "found" : "hidden"}</span>
                  <span className="text-phantom-ghost flex-1 truncate">{r.detail}</span>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-[11px] text-phantom-ghost">No probe results yet. Seed IG accounts, then run a sweep.</div>
        )}
      </div>

      {/* IG unfollow discipline panel */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <UserMinus className="w-4 h-4 text-rose-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            IG unfollow discipline · dwell · follow-back window · daily cap · ratio guard
          </span>
          {unfollow?.stats?.ratio_tripped > 0 && (
            <span className="px-2 py-0.5 bg-phantom-amber/10 border border-phantom-amber/50 text-phantom-amber text-[10px] font-mono rounded">
              RATIO TRIP × {unfollow.stats.ratio_tripped}
            </span>
          )}
          <span className="text-[10px] text-phantom-ghost font-mono">
            dwell {unfollow?.stats?.min_dwell_h ?? 48}h · wait {unfollow?.stats?.window_h ?? 72}h · cap {unfollow?.stats?.daily_cap ?? 10}/d · trip ratio ≥ {unfollow?.stats?.ratio_trip ?? 3}
          </span>
          <button onClick={tickUnfollow} className="ml-auto phantom-btn flex items-center gap-2 text-xs">
            <RotateCw className="w-3 h-3" /> Tick
          </button>
        </div>
        {unfollow && (
          <>
            <div className="grid grid-cols-6 gap-3 mb-3">
              {([
                { label: "follows",    value: unfollow.stats?.total_follows ?? 0,  color: "text-phantom-mist",  bg: "border-phantom-charcoal/70" },
                { label: "pending",    value: unfollow.stats?.pending ?? 0,        color: "text-phantom-amber", bg: "border-phantom-amber/30" },
                { label: "follow-back", value: unfollow.stats?.follow_back ?? 0,   color: "text-green-400",     bg: "border-green-500/30" },
                { label: "retained",   value: unfollow.stats?.retained ?? 0,       color: "text-sky-400",       bg: "border-sky-500/30" },
                { label: "candidates", value: unfollow.stats?.candidates ?? 0,     color: "text-rose-400",      bg: "border-rose-500/30" },
                { label: "queued",     value: unfollow.stats?.enqueued_today ?? 0, color: "text-red-400",       bg: "border-red-500/30" },
              ] as const).map(({ label, value, color, bg }) => (
                <div key={label} className={cn("phantom-panel p-3", bg)}>
                  <div className={cn("text-[10px] uppercase tracking-wider font-mono", color)}>{label}</div>
                  <div className={cn("text-2xl font-bold mt-1", color)}>{value}</div>
                </div>
              ))}
            </div>
            {unfollow.actors?.length > 0 && (
              <div className="space-y-1">
                <div className="text-[10px] uppercase tracking-wider text-phantom-ghost font-mono mb-1">per-actor</div>
                {unfollow.actors.slice(0, 8).map((a: any) => (
                  <div key={a.actor_id} className="flex items-center gap-3 text-[11px] font-mono py-1 border-b border-phantom-charcoal/40">
                    <Users className="w-3 h-3 text-phantom-mist" />
                    <span className="text-phantom-mist w-40 truncate">{a.actor_id}</span>
                    <span className="text-phantom-ghost w-24">{a.follows} follows</span>
                    <span className="text-green-400 w-24">{a.retained} retain</span>
                    <span className="text-rose-400 w-24">{a.candidates} cand</span>
                    <span className={cn("w-24", a.ratio && a.ratio > 3 ? "text-phantom-amber" : "text-phantom-ghost")}>
                      ratio {a.ratio === null ? "—" : (a.ratio === Infinity || a.ratio > 999 ? "∞" : a.ratio.toFixed(2))}
                    </span>
                    <span className="text-phantom-ghost flex-1">cap {a.cap}/d</span>
                  </div>
                ))}
              </div>
            )}
            {unfollow.events?.length > 0 && (
              <div className="mt-3 pt-2 border-t border-phantom-charcoal/40">
                <div className="text-[10px] uppercase tracking-wider text-phantom-ghost font-mono mb-1">recent events</div>
                <div className="space-y-0.5">
                  {unfollow.events.slice(0, 6).map((e: any, i: number) => (
                    <div key={i} className="flex items-center gap-2 text-[10px] font-mono text-phantom-ghost">
                      <span className={cn("w-32",
                        e.event === "follow" && "text-sky-400",
                        e.event === "follow_back" && "text-green-400",
                        e.event === "retained" && "text-fuchsia-400",
                        e.event === "queued_unfollow" && "text-red-400",
                      )}>{e.event}</span>
                      <span className="w-40 truncate">{e.actor_id}</span>
                      <span className="flex-1 truncate">{e.detail}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* IG DM flow panel */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <MessageSquare className="w-4 h-4 text-fuchsia-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            IG DM · templates · cooldown · content guard · opt-out memory
          </span>
          {dm?.stats?.blocked > 0 && (
            <span className="px-2 py-0.5 bg-phantom-amber/10 border border-phantom-amber/50 text-phantom-amber text-[10px] font-mono rounded">
              {dm.stats.blocked} BLOCKED
            </span>
          )}
          {dm?.stats?.opted_out > 0 && (
            <span className="px-2 py-0.5 bg-red-500/10 border border-red-500/50 text-red-400 text-[10px] font-mono rounded">
              {dm.stats.opted_out} OPT-OUT
            </span>
          )}
          <span className="text-[10px] text-phantom-ghost font-mono">
            cap {dm?.stats?.daily_cap ?? 8}/actor/d · cooldown {dm?.stats?.cooldown_min ?? 30}m · tmpl cap {dm?.stats?.template_cap ?? 50}/d · reply {((dm?.stats?.reply_rate ?? 0) * 100).toFixed(1)}%
          </span>
          <button onClick={tickDm} className="ml-auto phantom-btn flex items-center gap-2 text-xs">
            <RotateCw className="w-3 h-3" /> Tick
          </button>
        </div>
        {dm && (
          <>
            <div className="grid grid-cols-6 gap-3 mb-3">
              {([
                { label: "total",       value: dm.stats?.total ?? 0,        color: "text-phantom-mist",  bg: "border-phantom-charcoal/70" },
                { label: "sent",        value: dm.stats?.sent ?? 0,         color: "text-sky-400",       bg: "border-sky-500/30" },
                { label: "replied",     value: dm.stats?.replied ?? 0,      color: "text-green-400",     bg: "border-green-500/30" },
                { label: "blocked",     value: dm.stats?.blocked ?? 0,      color: "text-phantom-amber", bg: "border-phantom-amber/30" },
                { label: "opt-out",     value: dm.stats?.opted_out ?? 0,    color: "text-red-400",       bg: "border-red-500/30" },
                { label: "suppress",    value: dm.stats?.suppress_pairs ?? 0, color: "text-rose-400",    bg: "border-rose-500/30" },
              ] as const).map(({ label, value, color, bg }) => (
                <div key={label} className={cn("phantom-panel p-3", bg)}>
                  <div className={cn("text-[10px] uppercase tracking-wider font-mono", color)}>{label}</div>
                  <div className={cn("text-2xl font-bold mt-1", color)}>{value}</div>
                </div>
              ))}
            </div>
            {dm.block_reasons && Object.keys(dm.block_reasons).length > 0 && (
              <div className="mb-3 flex items-center gap-2 flex-wrap">
                <Ban className="w-3 h-3 text-phantom-amber" />
                <span className="text-[10px] uppercase tracking-wider text-phantom-ghost font-mono">block reasons:</span>
                {Object.entries(dm.block_reasons).map(([reason, count]) => (
                  <span key={reason} className="px-2 py-0.5 bg-phantom-charcoal/50 border border-phantom-amber/30 text-phantom-amber text-[10px] font-mono rounded">
                    {reason} × {String(count)}
                  </span>
                ))}
              </div>
            )}
            {dm.recent?.length > 0 && (
              <div className="pt-2 border-t border-phantom-charcoal/40">
                <div className="text-[10px] uppercase tracking-wider text-phantom-ghost font-mono mb-1">recent drafts</div>
                <div className="space-y-0.5">
                  {dm.recent.slice(0, 8).map((r: any, i: number) => (
                    <div key={i} className="flex items-center gap-2 text-[10px] font-mono text-phantom-ghost">
                      <Send className={cn("w-3 h-3",
                        r.state === "sent" && "text-sky-400",
                        r.state === "replied" && "text-green-400",
                        r.state === "blocked" && "text-phantom-amber",
                      )} />
                      <span className="w-28 truncate">{r.actor_id}</span>
                      <span className="w-28 truncate text-phantom-mist">{r.recipient_handle}</span>
                      <span className={cn("w-20",
                        r.state === "sent" && "text-sky-400",
                        r.state === "replied" && "text-green-400",
                        r.state === "blocked" && "text-phantom-amber",
                      )}>{r.state}</span>
                      <span className="flex-1 truncate">{r.block_reason ?? r.body?.slice(0, 60)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* IG session manager panel */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <LogIn className="w-4 h-4 text-emerald-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            IG session · state machine · TTL · 2FA · executor gate
          </span>
          {session?.stats?.by_state?.two_factor_pending > 0 && (
            <span className="px-2 py-0.5 bg-phantom-amber/10 border border-phantom-amber/50 text-phantom-amber text-[10px] font-mono rounded">
              {session.stats.by_state.two_factor_pending} 2FA PENDING
            </span>
          )}
          {session?.stats?.by_state?.locked > 0 && (
            <span className="px-2 py-0.5 bg-red-500/10 border border-red-500/50 text-red-400 text-[10px] font-mono rounded">
              {session.stats.by_state.locked} LOCKED
            </span>
          )}
          <span className="text-[10px] text-phantom-ghost font-mono">
            TTL {session?.stats?.ttl_days ?? 7}d · aging ≥ {(session?.stats?.aging_threshold ?? 0.6) * 100}% · 2FA op timeout {session?.stats?.two_fa_timeout_hours ?? 24}h
          </span>
          <button onClick={tickSession} className="ml-auto phantom-btn flex items-center gap-2 text-xs">
            <Timer className="w-3 h-3" /> Tick
          </button>
        </div>
        {session && (
          <>
            <div className="grid grid-cols-7 gap-2 mb-3">
              {([
                { label: "fresh",   value: session.stats?.by_state?.fresh ?? 0,                   color: "text-phantom-ghost", bg: "border-phantom-charcoal/70" },
                { label: "active",  value: session.stats?.by_state?.active ?? 0,                  color: "text-green-400",     bg: "border-green-500/30" },
                { label: "aging",   value: session.stats?.by_state?.aging ?? 0,                   color: "text-phantom-amber", bg: "border-phantom-amber/30" },
                { label: "expired", value: session.stats?.by_state?.expired ?? 0,                 color: "text-orange-400",    bg: "border-orange-500/30" },
                { label: "2FA",     value: session.stats?.by_state?.two_factor_pending ?? 0,      color: "text-phantom-amber", bg: "border-phantom-amber/30" },
                { label: "pwd rst", value: session.stats?.by_state?.password_reset_required ?? 0, color: "text-fuchsia-400",   bg: "border-fuchsia-500/30" },
                { label: "locked",  value: session.stats?.by_state?.locked ?? 0,                  color: "text-red-400",       bg: "border-red-500/30" },
              ] as const).map(({ label, value, color, bg }) => (
                <div key={label} className={cn("phantom-panel p-2", bg)}>
                  <div className={cn("text-[10px] uppercase tracking-wider font-mono", color)}>{label}</div>
                  <div className={cn("text-xl font-bold mt-1", color)}>{value}</div>
                </div>
              ))}
            </div>
            {session.two_fa_waiting?.length > 0 && (
              <div className="mb-3">
                <div className="text-[10px] uppercase tracking-wider text-phantom-amber font-mono mb-1">2FA awaiting operator</div>
                <div className="space-y-1">
                  {session.two_fa_waiting.map((w: any) => (
                    <div key={w.account_id} className="flex items-center gap-3 text-[11px] font-mono py-1 border-b border-phantom-charcoal/40">
                      <KeyRound className="w-3 h-3 text-phantom-amber" />
                      <span className="text-phantom-mist w-40 truncate">{w.account_id}</span>
                      <span className="text-phantom-ghost w-28">waiting {w.waiting_min}m</span>
                      <button onClick={() => complete2fa(w.account_id)} className="phantom-btn text-[10px] px-2 py-0.5 flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3" /> complete
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {session.soon_expiring?.length > 0 && (
              <div className="mb-3">
                <div className="text-[10px] uppercase tracking-wider text-phantom-amber font-mono mb-1">soon expiring</div>
                <div className="flex flex-wrap gap-1.5">
                  {session.soon_expiring.map((s: any) => (
                    <span key={s.account_id} className="px-2 py-0.5 bg-phantom-amber/10 border border-phantom-amber/30 text-phantom-amber text-[10px] font-mono rounded">
                      {s.account_id} · {s.hours_left}h
                    </span>
                  ))}
                </div>
              </div>
            )}
            {session.events?.length > 0 && (
              <div className="pt-2 border-t border-phantom-charcoal/40">
                <div className="text-[10px] uppercase tracking-wider text-phantom-ghost font-mono mb-1">recent events</div>
                <div className="space-y-0.5">
                  {session.events.slice(0, 8).map((e: any, i: number) => (
                    <div key={i} className="flex items-center gap-2 text-[10px] font-mono text-phantom-ghost">
                      <span className={cn("w-32",
                        e.event === "login_ok" && "text-green-400",
                        e.event === "login_fail" && "text-red-400",
                        e.event === "two_factor_pending" && "text-phantom-amber",
                        e.event === "2fa_complete" && "text-green-400",
                        e.event === "locked" && "text-red-400",
                        e.event === "expired" && "text-orange-400",
                        e.event === "aging" && "text-phantom-amber",
                      )}>{e.event}</span>
                      <span className="w-40 truncate">{e.account_id}</span>
                      <span className="flex-1 truncate">{e.detail}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* IG checkpoint handler panel */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <ShieldAlert className="w-4 h-4 text-orange-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            IG checkpoint handler · classifier · routed action · burst alarm
          </span>
          {checkpoint?.stats?.burst_alerts > 0 && (
            <span className="px-2 py-0.5 bg-red-500/10 border border-red-500/50 text-red-400 text-[10px] font-mono rounded">
              BURST ×{checkpoint.stats.burst_alerts}
            </span>
          )}
          <span className="text-[10px] text-phantom-ghost font-mono">
            burst ≥ {checkpoint?.stats?.burst_threshold ?? 5} in {checkpoint?.stats?.burst_window_min ?? 15}min · 10 kinds
          </span>
        </div>
        {checkpoint && (
          <>
            <div className="grid grid-cols-5 gap-3 mb-3">
              {([
                { label: "events",     value: checkpoint.stats?.total ?? 0,          color: "text-phantom-mist",  bg: "border-phantom-charcoal/70" },
                { label: "warn accts", value: checkpoint.stats?.accounts_warn ?? 0,  color: "text-phantom-amber", bg: "border-phantom-amber/30" },
                { label: "fail accts", value: checkpoint.stats?.accounts_fail ?? 0,  color: "text-orange-400",    bg: "border-orange-500/30" },
                { label: "halt accts", value: checkpoint.stats?.accounts_halt ?? 0,  color: "text-red-400",       bg: "border-red-500/30" },
                { label: "burst",      value: checkpoint.stats?.burst_alerts ?? 0,   color: "text-red-400",       bg: "border-red-500/30" },
              ] as const).map(({ label, value, color, bg }) => (
                <div key={label} className={cn("phantom-panel p-3", bg)}>
                  <div className={cn("text-[10px] uppercase tracking-wider font-mono", color)}>{label}</div>
                  <div className={cn("text-2xl font-bold mt-1", color)}>{value}</div>
                </div>
              ))}
            </div>
            {checkpoint.stats?.by_kind && Object.keys(checkpoint.stats.by_kind).length > 0 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {Object.entries(checkpoint.stats.by_kind).map(([kind, n]) => (
                  <span key={kind} className="px-2 py-0.5 bg-orange-500/10 border border-orange-500/30 text-orange-300 text-[10px] font-mono rounded">
                    {kind} · {String(n)}
                  </span>
                ))}
              </div>
            )}
            {checkpoint.stats?.by_action && Object.keys(checkpoint.stats.by_action).length > 0 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {Object.entries(checkpoint.stats.by_action).map(([action, n]) => (
                  <span key={action} className={cn("px-2 py-0.5 text-[10px] font-mono rounded border",
                    action === "retire" && "bg-red-500/10 border-red-500/30 text-red-300",
                    action === "enroll_recovery" && "bg-fuchsia-500/10 border-fuchsia-500/30 text-fuchsia-300",
                    action === "operator_review" && "bg-phantom-amber/10 border-phantom-amber/30 text-phantom-amber",
                    action === "self_resolve" && "bg-green-500/10 border-green-500/30 text-green-300",
                  )}>
                    {action} · {String(n)}
                  </span>
                ))}
              </div>
            )}
            {checkpoint.recent?.length ? (
              <div className="space-y-1">
                {checkpoint.recent.slice(0, 8).map((e: any) => (
                  <div key={e.event_id} className="flex items-center gap-3 text-[11px] font-mono py-1 border-b border-phantom-charcoal/40">
                    <KeyRound className={cn("w-3 h-3",
                      e.severity === "halt" && "text-red-400",
                      e.severity === "fail" && "text-orange-400",
                      e.severity === "warn" && "text-phantom-amber",
                      e.severity === "info" && "text-green-400")} />
                    <span className={cn("w-14 font-bold",
                      e.severity === "halt" && "text-red-400",
                      e.severity === "fail" && "text-orange-400",
                      e.severity === "warn" && "text-phantom-amber",
                      e.severity === "info" && "text-green-400")}>{e.severity}</span>
                    <span className="text-orange-300 w-40 truncate">{e.kind}</span>
                    <span className="text-phantom-mist w-36 truncate">{e.account_id}</span>
                    <span className="text-phantom-ghost w-28 truncate">{e.action}</span>
                    <span className="text-phantom-ghost flex-1 truncate">{e.signature}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[11px] text-phantom-ghost">No checkpoints seen yet — fleet is quiet.</div>
            )}
          </>
        )}
      </div>

      {/* IG engagement lattice panel */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <Network className="w-4 h-4 text-teal-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            IG engagement lattice · in/out caps · reciprocity · proxy diversity · country affinity
          </span>
          {lattice?.stats?.unsafe_targets > 0 && (
            <span className="px-2 py-0.5 bg-red-500/10 border border-red-500/50 text-red-400 text-[10px] font-mono rounded">
              {lattice.stats.unsafe_targets} OVER-CAP
            </span>
          )}
          {lattice?.config && (
            <span className="text-[10px] text-phantom-ghost font-mono">
              in {lattice.config.in_degree_cap}/d · out {lattice.config.out_degree_cap}/d · recip {lattice.config.reciprocity_h}h · actor w ≥ {lattice.config.min_actor_w}
            </span>
          )}
          <button onClick={planLattice} className="ml-auto phantom-btn flex items-center gap-2 text-xs">
            <Zap className="w-3 h-3" /> Plan
          </button>
        </div>
        {lattice && (
          <>
            <div className="grid grid-cols-5 gap-3 mb-3">
              {([
                { label: "safe actors", value: lattice.stats?.accounts_safe ?? 0,  color: "text-phantom-mist",  bg: "border-phantom-charcoal/70" },
                { label: "planned",     value: lattice.stats?.total_planned ?? 0,  color: "text-teal-400",      bg: "border-teal-500/30" },
                { label: "last plan",   value: lattice.stats?.last_plan_size ?? 0, color: "text-green-400",     bg: "border-green-500/30" },
                { label: "runs",        value: lattice.stats?.total_runs ?? 0,     color: "text-sky-400",       bg: "border-sky-500/30" },
                { label: "over-cap",    value: lattice.stats?.unsafe_targets ?? 0, color: "text-red-400",       bg: "border-red-500/30" },
              ] as const).map(({ label, value, color, bg }) => (
                <div key={label} className={cn("phantom-panel p-3", bg)}>
                  <div className={cn("text-[10px] uppercase tracking-wider font-mono", color)}>{label}</div>
                  <div className={cn("text-2xl font-bold mt-1", color)}>{value}</div>
                </div>
              ))}
            </div>
            <div className="mb-3 flex flex-wrap gap-1.5">
              {([
                ["in-cap",     lattice.stats?.skipped_in_cap,  "border-phantom-amber/30 text-phantom-amber"],
                ["reciprocity", lattice.stats?.skipped_recip,  "border-pink-500/30 text-pink-300"],
                ["proxy dupe", lattice.stats?.skipped_proxy,   "border-indigo-500/30 text-indigo-300"],
                ["health",     lattice.stats?.skipped_health,  "border-red-500/30 text-red-300"],
                ["diurnal",    lattice.stats?.skipped_tz,      "border-amber-500/30 text-amber-300"],
                ["country",    lattice.stats?.skipped_country, "border-sky-500/30 text-sky-300"],
              ] as const).map(([label, n, cls]) => (
                <span key={String(label)} className={cn("px-2 py-0.5 border text-[10px] font-mono rounded bg-phantom-charcoal/30", cls as string)}>
                  skip {label} · {String(n ?? 0)}
                </span>
              ))}
            </div>
            {lattice.hotspots?.length > 0 && (
              <div className="mb-3">
                <div className="text-[10px] uppercase tracking-wider text-phantom-ghost font-mono mb-1">today hotspots (most inbound)</div>
                <div className="flex flex-wrap gap-1.5">
                  {lattice.hotspots.map((h: any) => (
                    <span key={h.target_id} className="px-2 py-0.5 bg-teal-500/10 border border-teal-500/30 text-teal-300 text-[10px] font-mono rounded">
                      {h.target_id} · {h.likes_today}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {lattice.recent_edges?.length ? (
              <div className="space-y-1">
                {lattice.recent_edges.slice(0, 8).map((e: any, i: number) => (
                  <div key={i} className="flex items-center gap-3 text-[11px] font-mono py-1 border-b border-phantom-charcoal/40">
                    <Network className="w-3 h-3 text-teal-400" />
                    <span className="text-phantom-mist w-40 truncate">{e.actor_id}</span>
                    <span className="text-phantom-ghost w-4">→</span>
                    <span className="text-teal-300 w-40 truncate">{e.target_id}</span>
                    <span className="text-phantom-ghost w-20">{e.kind}</span>
                    <span className="text-phantom-ghost flex-1 truncate">{e.created_at}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[11px] text-phantom-ghost">No edges planned yet. Click Plan.</div>
            )}
          </>
        )}
      </div>

      {/* IG device drift panel */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <GitBranch className="w-4 h-4 text-fuchsia-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            IG device drift · per-phone fingerprint baseline · hysteretic trip
          </span>
          {drift?.stats?.tripped > 0 && (
            <span className="px-2 py-0.5 bg-red-500/10 border border-red-500/50 text-red-400 text-[10px] font-mono rounded">
              {drift.stats.tripped} TRIPPED
            </span>
          )}
          <span className="text-[10px] text-phantom-ghost font-mono">
            trip streak {drift?.stats?.trip_streak ?? 2} · 10 dimensions · fail/warn/info tiers
          </span>
          <button onClick={scanDrift} className="ml-auto phantom-btn flex items-center gap-2 text-xs">
            <RotateCw className="w-3 h-3" /> Scan
          </button>
        </div>
        {drift && (
          <>
            <div className="grid grid-cols-4 gap-3 mb-3">
              {([
                { label: "phones",   value: drift.stats?.total_phones ?? 0, icon: Smartphone, color: "text-phantom-mist",  bg: "border-phantom-charcoal/70" },
                { label: "stable",   value: drift.stats?.stable ?? 0,       icon: CheckCircle2, color: "text-green-400",   bg: "border-green-500/30" },
                { label: "drifting", value: drift.stats?.drifting ?? 0,     icon: Activity,    color: "text-phantom-amber", bg: "border-phantom-amber/30" },
                { label: "tripped",  value: drift.stats?.tripped ?? 0,      icon: AlertOctagon, color: "text-red-400",      bg: "border-red-500/30" },
              ] as const).map(({ label, value, icon: Icon, color, bg }) => (
                <div key={label} className={cn("phantom-panel p-3", bg)}>
                  <div className={cn("flex items-center gap-1 text-[10px] uppercase tracking-wider font-mono", color)}>
                    <Icon className="w-3 h-3" /> {label}
                  </div>
                  <div className={cn("text-2xl font-bold mt-1", color)}>{value}</div>
                </div>
              ))}
            </div>
            {drift.tripped_counts && Object.keys(drift.tripped_counts).length > 0 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {Object.entries(drift.tripped_counts).map(([dim, n]) => (
                  <span key={dim} className="px-2 py-0.5 bg-fuchsia-500/10 border border-fuchsia-500/30 text-fuchsia-300 text-[10px] font-mono rounded">
                    {dim} · {String(n)}
                  </span>
                ))}
              </div>
            )}
            {drift.tripped?.length ? (
              <div className="space-y-1">
                {drift.tripped.slice(0, 8).map((t: any, i: number) => (
                  <div key={i} className="flex items-center gap-3 text-[11px] font-mono py-1 border-b border-phantom-charcoal/40">
                    <AlertOctagon className={cn("w-3 h-3",
                      t.severity === "fail" && "text-red-400",
                      t.severity === "warn" && "text-phantom-amber",
                      t.severity === "info" && "text-sky-400")} />
                    <span className={cn("w-16 font-bold",
                      t.severity === "fail" && "text-red-400",
                      t.severity === "warn" && "text-phantom-amber",
                      t.severity === "info" && "text-sky-400")}>{t.severity}</span>
                    <span className="text-phantom-mist w-40 truncate">{t.phone_serial}</span>
                    <span className="text-fuchsia-300 w-28">{t.dimension}</span>
                    <span className="text-phantom-ghost w-28 truncate">was {String(t.baseline)}</span>
                    <span className="text-red-300 w-28 truncate">now {String(t.current)}</span>
                    <span className="text-phantom-ghost w-14">×{t.streak}</span>
                    <button onClick={() => snapshotDrift(t.phone_serial)} className="phantom-btn text-[10px] px-2 py-0.5 flex items-center gap-1">
                      <RotateCw className="w-3 h-3" /> rebase
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[11px] text-green-400">No drift tripped — every phone matches its baseline.</div>
            )}
          </>
        )}
      </div>

      {/* IG proxy pinning panel */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <Globe className="w-4 h-4 text-indigo-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            IG proxy pinning · country-scoped LRU · 24h quarantine · live-reuse alarm
          </span>
          {proxy?.stats?.cross_reuse_live > 0 && (
            <span className="px-2 py-0.5 bg-red-500/10 border border-red-500/50 text-red-400 text-[10px] font-mono rounded">
              CROSS REUSE × {proxy.stats.cross_reuse_live}
            </span>
          )}
          <span className="text-[10px] text-phantom-ghost font-mono">
            TTL {proxy?.stats?.pin_ttl_hours ?? 72}h · quarantine {proxy?.stats?.quarantine_hours ?? 24}h
          </span>
          <button onClick={tickProxy} className="ml-auto phantom-btn flex items-center gap-2 text-xs">
            <RotateCw className="w-3 h-3" /> Tick
          </button>
        </div>
        {proxy && (
          <>
            <div className="grid grid-cols-5 gap-3 mb-3">
              {([
                { label: "pool",           value: proxy.stats?.pool_size ?? 0,        icon: Globe,      color: "text-phantom-mist",  bg: "border-phantom-charcoal/70" },
                { label: "pinned",         value: proxy.stats?.pinned ?? 0,           icon: Lock,       color: "text-green-400",     bg: "border-green-500/30" },
                { label: "rotated",        value: proxy.stats?.rotated_total ?? 0,    icon: RotateCw,   color: "text-sky-400",       bg: "border-sky-500/30" },
                { label: "denied",         value: proxy.stats?.denied_total ?? 0,     icon: AlertOctagon, color: "text-phantom-amber", bg: "border-phantom-amber/30" },
                { label: "live reuse",     value: proxy.stats?.cross_reuse_live ?? 0, icon: Ghost,      color: "text-red-400",       bg: "border-red-500/30" },
              ] as const).map(({ label, value, icon: Icon, color, bg }) => (
                <div key={label} className={cn("phantom-panel p-3", bg)}>
                  <div className={cn("flex items-center gap-1 text-[10px] uppercase tracking-wider font-mono", color)}>
                    <Icon className="w-3 h-3" /> {label}
                  </div>
                  <div className={cn("text-2xl font-bold mt-1", color)}>{value}</div>
                </div>
              ))}
            </div>
            <div className="mb-3 flex flex-wrap gap-1.5">
              {Object.entries(proxy.pool_country || {}).map(([c, n]) => (
                <span key={`pool-${c}`} className="px-2 py-0.5 bg-indigo-500/10 border border-indigo-500/30 text-indigo-300 text-[10px] font-mono rounded">
                  pool {c} · {String(n)}
                </span>
              ))}
              {Object.entries(proxy.pinned_country || {}).map(([c, n]) => (
                <span key={`pin-${c}`} className="px-2 py-0.5 bg-green-500/10 border border-green-500/30 text-green-300 text-[10px] font-mono rounded">
                  pinned {c} · {String(n)}
                </span>
              ))}
              {proxy.unpinned_live?.length > 0 && (
                <span className="px-2 py-0.5 bg-phantom-amber/10 border border-phantom-amber/30 text-phantom-amber text-[10px] font-mono rounded">
                  unpinned live · {proxy.unpinned_live.length}
                </span>
              )}
            </div>
            {proxy.pins?.length ? (
              <div className="space-y-1">
                {proxy.pins.slice(0, 8).map((p: any) => (
                  <div key={p.account_id} className="flex items-center gap-3 text-[11px] font-mono py-1 border-b border-phantom-charcoal/40">
                    <Lock className="w-3 h-3 text-green-400" />
                    <span className="text-phantom-mist w-40 truncate">{p.account_id}</span>
                    <span className="text-indigo-300 w-56 truncate">{p.proxy_id}</span>
                    <span className="text-phantom-ghost w-10">{p.country}</span>
                    <span className="text-phantom-ghost w-20">rot {p.rotations}</span>
                    <span className="text-phantom-ghost flex-1 truncate">{p.source}</span>
                    <button onClick={() => rotateProxy(p.account_id)} className="phantom-btn text-[10px] px-2 py-0.5 flex items-center gap-1">
                      <RotateCw className="w-3 h-3" /> rotate
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[11px] text-phantom-ghost">No pins yet. Add proxies to the pool and tick.</div>
            )}
            {proxy.events?.length > 0 && (
              <div className="mt-3 pt-2 border-t border-phantom-charcoal/40">
                <div className="text-[10px] uppercase tracking-wider text-phantom-ghost font-mono mb-1">recent events</div>
                <div className="space-y-0.5">
                  {proxy.events.slice(0, 6).map((e: any, i: number) => (
                    <div key={i} className="flex items-center gap-2 text-[10px] font-mono text-phantom-ghost">
                      <span className={cn(
                        "w-14",
                        e.kind === "pin" && "text-green-400",
                        e.kind === "rotate" && "text-sky-400",
                        e.kind === "deny" && "text-red-400",
                        e.kind === "release" && "text-phantom-amber",
                      )}>{e.kind}</span>
                      <span className="w-40 truncate">{e.account_id}</span>
                      <span className="w-48 truncate">{e.proxy_id}</span>
                      <span className="flex-1 truncate">{e.reason}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* IG identity pair-check panel */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <Fingerprint className="w-4 h-4 text-rose-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            IG identity pair-check · locale×tz · device×OS · carrier×HNI · AppCloner cert
          </span>
          <span className="text-[10px] text-phantom-ghost font-mono">
            fixes CLAUDE.md bugs #1 + #2 · 6 rules · merged into health
          </span>
          <button onClick={rescanIdentity} className="ml-auto phantom-btn flex items-center gap-2 text-xs">
            <RotateCw className="w-3 h-3" /> Rescan
          </button>
        </div>
        {identity && (
          <>
            <div className="grid grid-cols-4 gap-3 mb-3">
              {([
                { label: "accounts", value: identity.stats?.total ?? 0,   color: "text-phantom-mist",  bg: "border-phantom-charcoal/70" },
                { label: "clean",    value: identity.stats?.clean ?? 0,    color: "text-green-400",     bg: "border-green-500/30" },
                { label: "warn",     value: identity.stats?.warn ?? 0,     color: "text-phantom-amber", bg: "border-phantom-amber/30" },
                { label: "fail",     value: identity.stats?.fail ?? 0,     color: "text-red-400",       bg: "border-red-500/30" },
              ] as const).map(({ label, value, color, bg }) => (
                <div key={label} className={cn("phantom-panel p-3", bg)}>
                  <div className={cn("text-[10px] uppercase tracking-wider font-mono", color)}>{label}</div>
                  <div className={cn("text-2xl font-bold mt-1", color)}>{value}</div>
                </div>
              ))}
            </div>
            {identity.rule_counts && Object.keys(identity.rule_counts).length > 0 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {Object.entries(identity.rule_counts).map(([rule, n]) => (
                  <span key={rule} className="px-2 py-0.5 bg-rose-500/10 border border-rose-500/30 text-rose-300 text-[10px] font-mono rounded">
                    {rule} · {String(n)}
                  </span>
                ))}
              </div>
            )}
            {identity.fails?.length ? (
              <div className="space-y-1">
                {identity.fails.slice(0, 8).map((f: any) => (
                  <div key={f.account_id} className="flex items-start gap-3 text-[11px] font-mono py-1 border-b border-phantom-charcoal/40">
                    <AlertOctagon className="w-3 h-3 text-red-400 mt-0.5" />
                    <span className="text-phantom-mist w-40 truncate">{f.username || f.account_id}</span>
                    <div className="flex-1 flex flex-col gap-0.5">
                      {f.violations.map((v: any, i: number) => (
                        <span key={i} className={cn(v.severity === "fail" ? "text-red-400" : "text-phantom-amber")}>
                          [{v.rule}] {v.message}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[11px] text-green-400">No contradictions — every IG persona pair-checks clean.</div>
            )}
          </>
        )}
      </div>

      {/* IG diurnal schedule panel */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <CloudSun className="w-4 h-4 text-amber-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            IG diurnal schedule · chronotype × local hour · gate on sleep
          </span>
          {diurnal && (
            <span className="text-[10px] text-phantom-ghost font-mono">
              UTC {String(diurnal.hour_utc).padStart(2, "0")}:00 · skip &lt; {(diurnal.skip_threshold * 100).toFixed(0)}% · fixes bug #4 (flat timing)
            </span>
          )}
        </div>
        {diurnal && (
          <>
            <div className="grid grid-cols-5 gap-3 mb-3">
              {([
                { label: "accounts",   value: diurnal.total,                                                 icon: Activity,   color: "text-phantom-mist",  bg: "border-phantom-charcoal/70" },
                { label: "larks",      value: diurnal.chronotypes?.morning_lark ?? 0,                        icon: Sun,        color: "text-amber-400",     bg: "border-amber-500/30" },
                { label: "standard",   value: diurnal.chronotypes?.standard ?? 0,                            icon: CloudSun,   color: "text-sky-400",       bg: "border-sky-500/30" },
                { label: "owls",       value: diurnal.chronotypes?.night_owl ?? 0,                           icon: Moon,       color: "text-purple-400",    bg: "border-purple-500/30" },
                { label: "mean weight", value: (diurnal.mean_weight_now ?? 0).toFixed(2),                    icon: TrendingUp, color: "text-green-400",     bg: "border-green-500/30" },
              ] as const).map(({ label, value, icon: Icon, color, bg }) => (
                <div key={label} className={cn("phantom-panel p-3", bg)}>
                  <div className={cn("flex items-center gap-1 text-[10px] uppercase tracking-wider font-mono", color)}>
                    <Icon className="w-3 h-3" /> {label}
                  </div>
                  <div className={cn("text-2xl font-bold mt-1", color)}>{value}</div>
                </div>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="phantom-panel p-3 border-green-500/30">
                <div className="text-[10px] uppercase tracking-wider font-mono text-green-400">awake (≥10%)</div>
                <div className="text-2xl font-bold mt-1 text-green-400">{diurnal.awake} / {diurnal.total}</div>
              </div>
              <div className="phantom-panel p-3 border-amber-500/30">
                <div className="text-[10px] uppercase tracking-wider font-mono text-amber-400">peak-active (≥50%)</div>
                <div className="text-2xl font-bold mt-1 text-amber-400">{diurnal.active} / {diurnal.total}</div>
              </div>
            </div>
          </>
        )}
      </div>

      {/* IG executor panel */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <Zap className="w-4 h-4 text-yellow-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            IG executor · drains ig_queue → mirror → APK · LogNormal delays
          </span>
          {executor?.running && (
            <span className="px-2 py-0.5 bg-green-500/10 border border-green-500/30 text-green-400 text-[10px] font-mono rounded">RUNNING</span>
          )}
          {!executor?.running && executor && (
            <span className="px-2 py-0.5 bg-red-500/10 border border-red-500/30 text-red-400 text-[10px] font-mono rounded">STOPPED</span>
          )}
          <span className="text-[10px] text-phantom-ghost font-mono">
            tick {executor?.tick_sec ?? 2}s · delays 5s–1200s · one action/tick per account
          </span>
          <button onClick={toggleExecutor} className="ml-auto phantom-btn flex items-center gap-2 text-xs">
            {executor?.running ? <><XOctagon className="w-3 h-3" /> Stop</> : <><Play className="w-3 h-3" /> Start</>}
          </button>
        </div>
        {executor && (
          <div className="grid grid-cols-6 gap-3">
            {([
              { label: "dispatched", value: executor.dispatched,              color: "text-green-400",     bg: "border-green-500/30" },
              { label: "failed",     value: executor.failed,                  color: "text-red-400",       bg: "border-red-500/30" },
              { label: "follow",     value: executor.by_kind?.follow ?? 0,    color: "text-sky-400",       bg: "border-sky-500/30" },
              { label: "like",       value: executor.by_kind?.like ?? 0,      color: "text-pink-400",      bg: "border-pink-500/30" },
              { label: "story_view", value: executor.by_kind?.story_view ?? 0, color: "text-purple-400",   bg: "border-purple-500/30" },
              { label: "post",       value: executor.by_kind?.post ?? 0,      color: "text-emerald-400",   bg: "border-emerald-500/30" },
            ] as const).map(({ label, value, color, bg }) => (
              <div key={label} className={cn("phantom-panel p-3", bg)}>
                <div className={cn("text-[10px] uppercase tracking-wider font-mono", color)}>{label}</div>
                <div className={cn("text-2xl font-bold mt-1", color)}>{value}</div>
              </div>
            ))}
          </div>
        )}
        {executor?.last_error && (
          <div className="mt-2 text-[10px] text-red-400 font-mono">last error · {executor.last_error}</div>
        )}
      </div>

      {/* IG agent frame panel */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <ShieldCheck className="w-4 h-4 text-cyan-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            InstagramAgent · CLAUDE.md guardrails · every dispatch wrapped
          </span>
          {agentCfg && (
            <span className="text-[10px] text-phantom-ghost font-mono">
              iter cap {agentCfg.max_iterations} · run cap ${agentCfg.max_usd_per_run} · session cap ${agentCfg.max_usd_per_session}
            </span>
          )}
        </div>
        {agentCfg && (
          <div className="mb-3 flex flex-wrap gap-1.5">
            {agentCfg.allowed_tools.map((t: string) => (
              <span key={t} className="px-2 py-0.5 bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-[10px] font-mono rounded">
                {t}
              </span>
            ))}
            {agentCfg.confirmation_required_for.map((t: string) => (
              <span key={t} className="px-2 py-0.5 bg-red-500/10 border border-red-500/30 text-red-300 text-[10px] font-mono rounded">
                confirm · {t}
              </span>
            ))}
          </div>
        )}
        {agentRuns && (
          <div className="grid grid-cols-4 gap-3 mb-3">
            {([
              { label: "runs",         value: agentRuns.summary.total,                                         color: "text-cyan-400",      bg: "border-cyan-500/30" },
              { label: "success",      value: agentRuns.summary.by_status?.success ?? 0,                      color: "text-green-400",     bg: "border-green-500/30" },
              { label: "avg iters",    value: (agentRuns.summary.avg_iters ?? 0).toFixed(2),                  color: "text-phantom-mist",  bg: "border-phantom-charcoal/70" },
              { label: "total cost",   value: "$" + (agentRuns.summary.total_cost ?? 0).toFixed(4),           color: "text-phantom-amber", bg: "border-phantom-amber/30" },
            ] as const).map(({ label, value, color, bg }) => (
              <div key={label} className={cn("phantom-panel p-3", bg)}>
                <div className={cn("text-[10px] uppercase tracking-wider font-mono", color)}>{label}</div>
                <div className={cn("text-2xl font-bold mt-1", color)}>{value}</div>
              </div>
            ))}
          </div>
        )}
        {agentRuns?.recent?.length ? (
          <div className="space-y-1">
            {agentRuns.recent.slice(0, 10).map((r: any) => (
              <div key={r.run_id} className="flex items-center gap-3 text-[11px] font-mono py-1 border-b border-phantom-charcoal/40">
                <span className={cn(
                  "w-20 font-bold",
                  r.status === "success" && "text-green-400",
                  r.status === "cost_exceeded" && "text-phantom-amber",
                  r.status === "failed" && "text-red-400",
                  r.status === "blocked_confirmation" && "text-orange-400",
                )}>{r.status}</span>
                <span className="text-phantom-mist w-20 truncate">{r.kind}</span>
                <span className="text-phantom-ghost w-36 truncate">{r.account_id}</span>
                <span className="text-phantom-ghost w-16">iter {r.iterations}</span>
                <span className="text-phantom-ghost w-20">${r.cost_usd.toFixed(4)}</span>
                <span className="text-phantom-ghost flex-1 truncate">{r.audit?.length ?? 0} audit events</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[11px] text-phantom-ghost">No agent runs yet. Trigger /orchestrator/plan-now.</div>
        )}
      </div>

      {/* Funnel panel */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <TrendingUp className="w-4 h-4 text-pink-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            IG funnel · post → impression → profile view → bio click → threads tap
          </span>
          <span className="text-[10px] text-phantom-ghost font-mono">
            {funnel?.accounts ?? 0} accounts tracked · {funnel?.ring_size ?? 0} events in ring
          </span>
          <button onClick={fireFunnelDemo} className="ml-auto phantom-btn flex items-center gap-2 text-xs">
            <Zap className="w-3 h-3" /> Fire demo funnel
          </button>
        </div>
        {funnel && (() => {
          const c = funnel.totals.counts;
          const r = funnel.totals.rates;
          const steps: Array<{ key: string; label: string; count: number; color: string }> = [
            { key: "post_posted",    label: "posts",         count: c.post_posted,    color: "bg-sky-500/60" },
            { key: "impression",     label: "impressions",   count: c.impression,     color: "bg-pink-500/60" },
            { key: "profile_view",   label: "profile views", count: c.profile_view,   color: "bg-purple-500/60" },
            { key: "bio_link_click", label: "bio clicks",    count: c.bio_link_click, color: "bg-orange-500/60" },
            { key: "threads_tap",    label: "threads taps",  count: c.threads_tap,    color: "bg-emerald-500/60" },
          ];
          const maxCount = Math.max(1, ...steps.map((s) => s.count));
          return (
            <>
              <div className="space-y-2 mb-3">
                {steps.map((s) => (
                  <div key={s.key} className="flex items-center gap-3 text-[11px] font-mono">
                    <span className="text-phantom-ghost w-32 truncate">{s.label}</span>
                    <div className="flex-1 bg-phantom-charcoal/40 rounded-sm h-5 relative overflow-hidden">
                      <div className={cn("h-full rounded-sm", s.color)} style={{ width: `${(s.count / maxCount) * 100}%` }} />
                      <span className="absolute inset-y-0 left-2 flex items-center text-phantom-mist">{s.count.toLocaleString()}</span>
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex gap-4 text-[11px] font-mono flex-wrap">
                <span className="text-phantom-ghost">impression → view <span className="text-phantom-mist">{(r.impression_to_view * 100).toFixed(2)}%</span></span>
                <span className="text-phantom-ghost">view → bio click <span className="text-phantom-mist">{(r.view_to_bio_click * 100).toFixed(2)}%</span></span>
                <span className="text-phantom-ghost">view → threads <span className="text-phantom-mist">{(r.view_to_threads * 100).toFixed(2)}%</span></span>
                <span className="text-phantom-ghost">post → threads (end-to-end) <span className="text-green-400 font-bold">{r.post_to_threads.toFixed(2)}x</span></span>
              </div>
            </>
          );
        })()}
      </div>

      {/* Recovery agent */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <RotateCw className="w-4 h-4 text-orange-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            Shadowban recovery agent
          </span>
          {recovery?.running && (
            <span className="px-2 py-0.5 bg-green-500/10 border border-green-500/30 text-green-400 text-[10px] font-mono rounded">RUNNING</span>
          )}
          <span className="text-[10px] text-phantom-ghost font-mono">
            cool-down {recovery ? Math.round(recovery.config.cool_down_sec / 3600) : "?"}h · graduate at {recovery?.config.rewarm_posts_to_graduate ?? "?"} posts · max strikes {recovery?.config.max_strikes ?? "?"}
          </span>
          <button
            onClick={tickRecovery}
            disabled={ticking}
            className="ml-auto phantom-btn flex items-center gap-2 text-xs"
          >
            <Play className={cn("w-3 h-3", ticking && "animate-pulse")} />
            Tick now
          </button>
        </div>
        <div className="grid grid-cols-5 gap-3 mb-3">
          {([
            { k: "cooling_down",  n: recovery?.stats.cooling_down ?? 0 },
            { k: "rewarming",     n: recovery?.stats.rewarming ?? 0 },
            { k: "graduated",     n: recovery?.stats.total_graduated ?? 0 },
            { k: "retired",       n: recovery?.stats.total_retired ?? 0 },
          ] as const).map(({ k, n }) => {
            const style = PHASE_STYLES[k];
            const Icon = style.icon;
            return (
              <div key={k} className={cn("phantom-panel p-3", style.bg)}>
                <div className={cn("flex items-center gap-1 text-[10px] uppercase tracking-wider font-mono", style.text)}>
                  <Icon className="w-3 h-3" />{k.replace("_", " ")}
                </div>
                <div className={cn("text-2xl font-bold mt-1", style.text)}>{n}</div>
              </div>
            );
          })}
          <div className="phantom-panel p-3 border-phantom-charcoal">
            <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider font-mono text-phantom-ghost">
              <Activity className="w-3 h-3" /> enrolled
            </div>
            <div className="text-2xl font-bold mt-1 text-phantom-mist">{recovery?.stats.total_enrolled ?? 0}</div>
          </div>
        </div>
        {recovery && recovery.records.length > 0 ? (
          <div className="space-y-1">
            {recovery.records.map((r) => {
              const style = PHASE_STYLES[r.phase];
              return (
                <div key={r.account_id} className="flex items-center gap-3 text-[11px] font-mono py-1 border-b border-phantom-charcoal/40">
                  <span className={cn("uppercase tracking-wider w-24", style.text)}>{r.phase.replace("_", " ")}</span>
                  <Link href={`/instagram/${r.account_id}`} className="text-phantom-emerald hover:underline w-32 truncate">{r.account_id}</Link>
                  <span className="text-phantom-ghost">strikes {r.strikes}/{recovery.config.max_strikes}</span>
                  <span className="text-phantom-ghost">from day {r.original_warmup_day}</span>
                  {r.phase === "rewarming" && (
                    <span className="text-orange-400">rewarm posts {r.rewarm_actions_observed}/{recovery.config.rewarm_posts_to_graduate}</span>
                  )}
                  <span className="text-phantom-ghost flex-1 truncate">{r.notes.slice(-1)[0] ?? ""}</span>
                  {r.phase === "cooling_down" && (
                    <button onClick={() => skipCooldown(r.account_id)} className="text-[10px] text-sky-400 hover:underline">skip cool-down</button>
                  )}
                  {(r.phase === "cooling_down" || r.phase === "rewarming") && (
                    <button onClick={() => graduate(r.account_id)} className="text-[10px] text-green-400 hover:underline">force graduate</button>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-[11px] text-phantom-ghost">No IG accounts in recovery. The agent enrolls automatically when health detects a shadowban.</div>
        )}
      </div>

      {/* Dev scenarios */}
      <div className="phantom-panel p-4">
        <div className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono mb-3">
          Dev scenarios — simulate a signal profile
        </div>
        <div className="flex gap-2 flex-wrap mb-3">
          {SCENARIOS.map((sc) => (
            <button
              key={sc.label}
              onClick={() => runScenario(sc.signals)}
              className="px-2 py-1 bg-phantom-charcoal/60 border border-phantom-charcoal text-phantom-mist text-[10px] font-mono rounded hover:border-pink-400/40"
            >
              {sc.label}
            </button>
          ))}
        </div>
        {simResult && (
          <div className={cn("p-3 text-[11px] font-mono border", STATUS_STYLES[simResult.status].bg)}>
            <div className="flex items-center gap-3">
              <span className={cn("uppercase tracking-wider font-bold", STATUS_STYLES[simResult.status].text)}>
                {simResult.status}
              </span>
              <span className={cn("font-bold", STATUS_STYLES[simResult.status].text)}>score {simResult.score}</span>
              <span className="text-phantom-ghost">day {simResult.signals.warmup_day}</span>
              <span className="text-phantom-ghost">posts {simResult.signals.posts_in_ring}</span>
              <span className="text-phantom-ghost">48h {simResult.signals.posts_last_48h}</span>
              <span className="text-phantom-ghost">idle {simResult.signals.hours_since_last_post}h</span>
              <span className="text-phantom-ghost">{simResult.signals.has_threads_link ? "linked" : "no link"}</span>
            </div>
            <div className="mt-1 flex gap-2 flex-wrap">
              {simResult.flags.length === 0 ? (
                <span className="text-phantom-ghost">No flags lit — clean scenario.</span>
              ) : simResult.flags.map((f) => (
                <span key={f} className="px-2 py-0.5 bg-phantom-charcoal/80 border border-phantom-amber/30 text-phantom-amber text-[10px] rounded">
                  {f}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
