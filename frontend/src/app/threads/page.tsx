"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  MessageCircle, Link2, Send, Repeat2, UserPlus, Loader2, Clock,
  CheckCircle2, AlertTriangle, Activity, Zap, Play, Square, ArrowRightLeft,
  Eye, MousePointerClick, DollarSign, Trophy, TrendingUp, Brain, Radio, Instagram,
  ShieldCheck, AlertCircle, Circle, FlaskConical, Heart, HeartCrack, Ghost,
  Snowflake, Flame, GraduationCap, XOctagon, RotateCw, ExternalLink, Database,
  Bot, Search, Hash, Reply as ReplyIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

type ThreadsAccount = {
  account_id: string;
  handle: string;
  ig_account_id: string;
  linked_at: string;
  warmup_day: number;
  can_cross_post: boolean;
};

type ThreadsList = { accounts: ThreadsAccount[]; total: number };

type IGAccount = {
  account_id: string;
  username: string;
  platform: string;
  warmup_day: number;
};

type Budget = {
  day: number; follow: number; reply: number; repost: number; post: number; total: number;
};

type CurveDay = Budget;

type Status = {
  platform: string;
  linked_accounts: number;
  pending_actions: number;
  warming_days: number;
  status: string;
  package: string;
};

type ExecStatus = {
  running: boolean;
  started_at: string | null;
  stopped_at: string | null;
  dispatched: number;
  failed: number;
  last_error: string | null;
};

type QueueEntry = {
  action_id: string;
  account_id: string;
  kind: string;
  target: string;
  body: string;
  route: string;
  status: string;
  date: string;
  queued_at: string;
  dispatched_at: string | null;
  phone_serial: string | null;
  error: string | null;
};

type QueueView = {
  queued: number;
  dispatched: number;
  failed: number;
  entries: QueueEntry[];
};

type FunnelCounts = {
  reply_posted: number;
  post_posted: number;
  profile_view: number;
  bio_link_click: number;
  subscribe: number;
};

type FunnelRates = {
  reply_to_view: number;
  view_to_click: number;
  click_to_sub: number;
  reply_to_sub: number;
};

type AccountFunnel = {
  threads_account_id: string;
  counts: FunnelCounts;
  rates: FunnelRates;
};

type FunnelSummary = {
  totals: AccountFunnel;
  accounts: number;
  top: AccountFunnel[];
  ring_size: number;
};

type PlanEntry = {
  account_id: string;
  kind: string;
  target: string;
  body: string;
  reason: string;
};

type OrchStatus = {
  running: boolean;
  last_run_at: string | null;
  total_runs: number;
  total_enqueued: number;
  last_plan: PlanEntry[];
};

type BridgeStats = {
  events_in: number;
  replies_out: number;
  skipped_budget: number;
  skipped_no_link: number;
  skipped_gate: number;
  last_action_id: string | null;
};

type IGEventRow = {
  ig_account_id: string;
  post_id: string;
  caption: string;
  source: string;
  ts: string;
};

type HealthSignals = {
  reply_posted: number; profile_view: number; bio_link_click: number; subscribe: number;
  reply_to_view_rate: number; dispatched: number; failed: number;
  dispatch_failure_rate: number; queued_pending: number; stalled_count: number;
  warmup_day: number; hours_since_dispatch: number;
};
type AccountHealth = {
  account_id: string; status: "healthy" | "watch" | "at_risk" | "shadowbanned";
  score: number; flags: string[]; signals: HealthSignals; computed_at: string;
};
type HealthRollup = {
  healthy: number; watch: number; at_risk: number; shadowbanned: number;
  total: number; last_scan_at: string | null; total_scans: number;
};
type HealthSummary = {
  rollup: HealthRollup;
  at_risk: AccountHealth[];
  flag_counts: Record<string, number>;
};

type RecoveryRecord = {
  account_id: string;
  phase: "cooling_down" | "rewarming" | "graduated" | "retired";
  strikes: number;
  entered_at: string;
  cool_down_until: string;
  original_warmup_day: number;
  rewarm_baseline_replies: number;
  rewarm_actions_observed: number;
  graduated_at: string | null;
  retired_at: string | null;
  notes: string[];
};
type RecoveryStats = {
  total_enrolled: number; total_graduated: number; total_retired: number;
  cooling_down: number; rewarming: number;
  last_tick_at: string | null; total_ticks: number;
};
type RecoverySummary = {
  running: boolean;
  stats: RecoveryStats;
  config: { tick_sec: number; cool_down_sec: number;
            rewarm_graduate_replies: number; max_strikes: number };
  records: RecoveryRecord[];
};

type AgentRun = {
  run_id: string; agent_name: string; account_id: string; kind: string;
  status: string; iterations: number; cost_usd: number;
  started_at: string; ended_at: string | null; error: string;
  audit: Array<Record<string, unknown>>;
};
type AgentSummary = {
  config: {
    name: string; max_iterations: number; max_usd_per_run: number;
    max_usd_per_session: number; allowed_tools: string[];
    confirmation_required: string[];
  };
  runs: { total: number; by_status: Record<string, number>; total_cost: number; avg_iters: number };
  recent: AgentRun[];
};

type ProbeResult = {
  probe_id: string; kind: "search_reach" | "hashtag_reach" | "reply_visibility";
  account_id: string; searcher_id: string; found: boolean; detail: string;
  checked_at: string;
};
type ProbeSummary = {
  running: boolean;
  stats: { total_run: number; total_found: number; total_hidden: number;
           last_run_at: string | null; hidden_rate: number };
  tick_sec: number;
  recent: ProbeResult[];
};

type RebalancerStatus = {
  running: boolean;
  stats: { level: "green" | "yellow" | "red"; total_ticks: number; total_alerts: number; last_transition: string | null };
  snapshot: { total: number; shadowbanned: number; at_risk: number; shadowban_rate: number; hidden_rate: number; enrollment_burst: number };
  throttles: { plan_per_tick_multiplier: number; linking_allowed: boolean };
  events: Array<{ topic: string; reason: string; ts: string }>;
};

type Persistence = {
  enabled: boolean;
  funnel_events: number;
  health_snapshots: number;
  recovery_records: number;
  ig_events: number;
  error?: boolean | null;
};

type AuditCheck = {
  key: string;
  label: string;
  status: "pass" | "warn" | "fail";
  detail: string;
  metrics: Record<string, unknown>;
};

type AuditReport = {
  ran_at: string;
  n_personas: number;
  pass_count: number;
  warn_count: number;
  fail_count: number;
  duration_ms: number;
  passed: boolean;
  checks: AuditCheck[];
};

const ACTION_META = [
  { kind: "post",   label: "Post",   icon: Send,      color: "text-cyan-400"   },
  { kind: "reply",  label: "Reply",  icon: MessageCircle, color: "text-purple-400" },
  { kind: "repost", label: "Repost", icon: Repeat2,   color: "text-orange-400" },
  { kind: "follow", label: "Follow", icon: UserPlus,  color: "text-green-400"  },
] as const;

type ActionKind = typeof ACTION_META[number]["kind"];

export default function ThreadsPage() {
  const [accounts, setAccounts] = useState<ThreadsAccount[]>([]);
  const [igAccounts, setIgAccounts] = useState<IGAccount[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [exec, setExec] = useState<ExecStatus | null>(null);
  const [queueView, setQueueView] = useState<QueueView | null>(null);
  const [crossPostIG, setCrossPostIG] = useState("");
  const [crossPostBody, setCrossPostBody] = useState("");
  const [crossPosting, setCrossPosting] = useState(false);
  const [funnel, setFunnel] = useState<FunnelSummary | null>(null);
  const [accountFunnel, setAccountFunnel] = useState<AccountFunnel | null>(null);
  const [orch, setOrch] = useState<OrchStatus | null>(null);
  const [planning, setPlanning] = useState(false);
  const [bridge, setBridge] = useState<BridgeStats | null>(null);
  const [igEvents, setIgEvents] = useState<IGEventRow[]>([]);
  const [simIG, setSimIG] = useState("");
  const [simCaption, setSimCaption] = useState("");
  const [simulating, setSimulating] = useState(false);
  const [simResult, setSimResult] = useState<string | null>(null);
  const [audit, setAudit] = useState<AuditReport | null>(null);
  const [auditing, setAuditing] = useState(false);
  const [auditN, setAuditN] = useState(10_000);
  const [health, setHealth] = useState<HealthSummary | null>(null);
  const [scanning, setScanning] = useState(false);
  const [simHealth, setSimHealth] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<RecoverySummary | null>(null);
  const [recoveryTicking, setRecoveryTicking] = useState(false);
  const [persistence, setPersistence] = useState<Persistence | null>(null);
  const [rebalancer, setRebalancer] = useState<RebalancerStatus | null>(null);
  const [agentSummary, setAgentSummary] = useState<AgentSummary | null>(null);
  const [probes, setProbes] = useState<ProbeSummary | null>(null);
  const [probesTicking, setProbesTicking] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [curve, setCurve] = useState<CurveDay[] | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [linking, setLinking] = useState<string | null>(null);
  const [acting, setActing] = useState(false);
  const [actionTarget, setActionTarget] = useState("");
  const [actionBody, setActionBody] = useState("");

  const loadAll = useCallback(async () => {
    const [a, s, igr, ex, q, f, o, br, ige] = await Promise.all([
      fetch("/api/platforms/threads/accounts").then((r) => r.json()),
      fetch("/api/platforms/threads/status").then((r) => r.json()),
      fetch("/api/accounts?platform=instagram").then((r) => r.json()).catch(() => ({ accounts: [] })),
      fetch("/api/platforms/threads/executor/status").then((r) => r.json()),
      fetch("/api/platforms/threads/queue").then((r) => r.json()),
      fetch("/api/platforms/threads/funnel/summary").then((r) => r.json()).catch(() => null),
      fetch("/api/platforms/threads/orchestrator/status").then((r) => r.json()).catch(() => null),
      fetch("/api/platforms/threads/bridge/status").then((r) => r.json()).catch(() => null),
      fetch("/api/platforms/threads/ig-events?limit=20").then((r) => r.json()).catch(() => []),
    ]);
    setAccounts((a as ThreadsList).accounts ?? []);
    setStatus(s as Status);
    setIgAccounts((igr.accounts ?? []).slice(0, 25));
    setExec(ex as ExecStatus);
    setQueueView(q as QueueView);
    setFunnel(f as FunnelSummary);
    setOrch(o as OrchStatus);
    setBridge(br as BridgeStats);
    setIgEvents((ige as IGEventRow[]) ?? []);
  }, []);

  const simulateIG = async () => {
    if (!simIG) return;
    setSimulating(true);
    setSimResult(null);
    try {
      const r = await fetch("/api/platforms/threads/ig-event", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ig_account_id: simIG,
          caption: simCaption || "simulated IG post",
          source: "manual",
        }),
      });
      const d = await r.json();
      if (!r.ok) {
        setSimResult(`error: ${JSON.stringify(d)}`);
      } else {
        const outcome = (d.outcomes?.[0] ?? {});
        setSimResult(
          outcome.result?.queued
            ? `✓ reply enqueued → ${outcome.result.action_id}`
            : `• bridge skipped: ${outcome.result?.skipped ?? "unknown"}`,
        );
        setSimCaption("");
      }
      loadAll();
    } finally { setSimulating(false); }
  };

  const setIGDay = async (id: string, day: number) => {
    await fetch(`/api/platforms/threads/accounts/${id}/warmup?day=${day}`, { method: "POST" });
    loadAll();
  };

  const planNow = async () => {
    setPlanning(true);
    try {
      await fetch("/api/platforms/threads/orchestrator/run", { method: "POST" });
      loadAll();
    } finally { setPlanning(false); }
  };

  const toggleOrch = async () => {
    const endpoint = orch?.running ? "stop" : "start";
    await fetch(`/api/platforms/threads/orchestrator/${endpoint}`, { method: "POST" });
    loadAll();
  };

  useEffect(() => {
    loadAll();
    const t = setInterval(loadAll, 4000);
    return () => clearInterval(t);
  }, [loadAll]);

  useEffect(() => {
    fetch("/api/platforms/threads/audit/last")
      .then((r) => r.json())
      .then((d) => d && setAudit(d as AuditReport))
      .catch(() => {});
  }, []);

  const runAudit = async () => {
    setAuditing(true);
    try {
      const r = await fetch(`/api/platforms/threads/audit/run?n=${auditN}`, { method: "POST" });
      const d = (await r.json()) as AuditReport;
      setAudit(d);
    } finally { setAuditing(false); }
  };

  const loadHealth = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/threads/health/summary").then((r) => r.json());
      setHealth(d as HealthSummary);
    } catch {}
  }, []);

  useEffect(() => { loadHealth(); const t = setInterval(loadHealth, 8000); return () => clearInterval(t); }, [loadHealth]);

  const scanHealth = async () => {
    setScanning(true);
    try {
      const d = await fetch("/api/platforms/threads/health/scan", { method: "POST" }).then((r) => r.json());
      setHealth(d as HealthSummary);
    } finally { setScanning(false); }
  };

  const loadProbes = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/threads/probes/status?limit=20").then((r) => r.json());
      setProbes(d as ProbeSummary);
    } catch {}
  }, []);

  useEffect(() => { loadProbes(); const t = setInterval(loadProbes, 6000); return () => clearInterval(t); }, [loadProbes]);

  const runProbes = async () => {
    setProbesTicking(true);
    try {
      await fetch("/api/platforms/threads/probes/tick", { method: "POST" });
      loadProbes();
      loadHealth();
    } finally { setProbesTicking(false); }
  };

  const loadAgent = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/threads/agent/runs?limit=15").then((r) => r.json());
      setAgentSummary(d as AgentSummary);
    } catch {}
  }, []);

  useEffect(() => { loadAgent(); const t = setInterval(loadAgent, 5000); return () => clearInterval(t); }, [loadAgent]);

  const loadPersistence = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/threads/persistence/status").then((r) => r.json());
      setPersistence(d as Persistence);
    } catch {}
  }, []);

  useEffect(() => { loadPersistence(); const t = setInterval(loadPersistence, 10000); return () => clearInterval(t); }, [loadPersistence]);

  const loadRebalancer = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/threads/rebalancer/status").then((r) => r.json());
      setRebalancer(d as RebalancerStatus);
    } catch {}
  }, []);
  useEffect(() => { loadRebalancer(); const t = setInterval(loadRebalancer, 5000); return () => clearInterval(t); }, [loadRebalancer]);

  const loadRecovery = useCallback(async () => {
    try {
      const d = await fetch("/api/platforms/threads/recovery/status").then((r) => r.json());
      setRecovery(d as RecoverySummary);
    } catch {}
  }, []);

  useEffect(() => { loadRecovery(); const t = setInterval(loadRecovery, 6000); return () => clearInterval(t); }, [loadRecovery]);

  const tickRecovery = async () => {
    setRecoveryTicking(true);
    try {
      const d = await fetch("/api/platforms/threads/recovery/tick", { method: "POST" }).then((r) => r.json());
      setRecovery(d as RecoverySummary);
      loadHealth();
    } finally { setRecoveryTicking(false); }
  };

  const skipCooldown = async (accountId: string) => {
    await fetch(`/api/platforms/threads/recovery/${accountId}/skip-cooldown`, { method: "POST" });
    loadRecovery();
  };

  const forceGraduate = async (accountId: string) => {
    await fetch(`/api/platforms/threads/recovery/${accountId}/graduate`, { method: "POST" });
    loadRecovery();
  };

  const simulateHealth = async (accountId: string, scenario: string) => {
    setSimHealth(null);
    try {
      const r = await fetch("/api/platforms/threads/health/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: accountId, scenario }),
      });
      const d = (await r.json()) as AccountHealth;
      setSimHealth(`${accountId.slice(0, 8)} → ${d.status} (score ${d.score}) [${d.flags.join(", ") || "clean"}]`);
      loadHealth();
    } catch (e) {
      setSimHealth(`error: ${String(e)}`);
    }
  };

  const toggleExecutor = async () => {
    const endpoint = exec?.running ? "stop" : "start";
    await fetch(`/api/platforms/threads/executor/${endpoint}`, { method: "POST" });
    loadAll();
  };

  const crossPost = async () => {
    if (!crossPostIG || !crossPostBody) return;
    setCrossPosting(true);
    setActionError(null); setActionMsg(null);
    try {
      const r = await fetch("/api/platforms/threads/cross-post", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ig_account_id: crossPostIG, reply_body: crossPostBody }),
      });
      const d = await r.json();
      if (!r.ok) {
        setActionError(typeof d.detail === "object" ? JSON.stringify(d.detail) : String(d.detail));
      } else {
        setActionMsg(`Cross-posted → ${d.action_id}`);
        setCrossPostBody("");
      }
      loadAll();
    } finally { setCrossPosting(false); }
  };

  useEffect(() => {
    if (!selected) { setBudget(null); setCurve(null); setAccountFunnel(null); return; }
    Promise.all([
      fetch(`/api/platforms/threads/budget/${selected}`).then((r) => r.json()),
      fetch(`/api/platforms/threads/curve/${selected}`).then((r) => r.json()),
      fetch(`/api/platforms/threads/funnel/${selected}`).then((r) => r.json()).catch(() => null),
    ]).then(([b, c, af]) => {
      setBudget(b as Budget);
      setCurve((c as { days: CurveDay[] }).days ?? null);
      setAccountFunnel(af as AccountFunnel);
    });
  }, [selected, actionMsg, funnel]);

  const fireFunnelEvent = async (kind: "profile_view" | "bio_link_click" | "subscribe") => {
    if (!selected) return;
    await fetch("/api/platforms/threads/funnel/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, threads_account_id: selected }),
    });
    loadAll();
  };

  const link = async (igId: string) => {
    setLinking(igId);
    try {
      const r = await fetch("/api/platforms/threads/link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ig_account_id: igId }),
      });
      if (!r.ok) {
        const d = await r.json();
        setActionError(typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail));
      }
      loadAll();
    } finally { setLinking(null); }
  };

  const dispatch = async (kind: ActionKind) => {
    if (!selected) return;
    setActing(true);
    setActionError(null); setActionMsg(null);
    try {
      const r = await fetch(`/api/platforms/threads/${kind}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: selected, target: actionTarget, body: actionBody }),
      });
      const d = await r.json();
      if (!r.ok) {
        setActionError(typeof d.detail === "object" ? JSON.stringify(d.detail) : String(d.detail ?? "action failed"));
      } else {
        setActionMsg(`${kind} queued → ${d.action_id}`);
        setActionTarget(""); setActionBody("");
      }
      loadAll();
    } finally { setActing(false); }
  };

  const advanceDay = async () => {
    if (!selected) return;
    await fetch(`/api/platforms/threads/advance-day/${selected}`, { method: "POST" });
    loadAll();
    setActionMsg("Warmup day advanced.");
  };

  const unlinkedIG = useMemo(() => {
    const linked = new Set(accounts.map((a) => a.ig_account_id));
    return igAccounts.filter((i) => !linked.has(i.account_id));
  }, [accounts, igAccounts]);

  const selectedAccount = accounts.find((a) => a.account_id === selected);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Phase 2 · Platform
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <MessageCircle className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          Threads <span className="phantom-accent-text">command</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-2xl">
          One Threads account per IG account. 14-day LogNormal warming curve.
          Cross-post from IG once the IG parent passes day 7.
        </p>
      </div>

      {/* Status strip */}
      {status && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Tile label="Linked accounts" value={status.linked_accounts.toString()} />
          <Tile label="Pending actions" value={status.pending_actions.toString()} />
          <Tile label="Warming curve" value={`${status.warming_days}d`} />
          <Tile label="Platform state" value={status.status}
                tone={status.status === "warming" ? "accent" : "amber"} />
        </div>
      )}

      {/* Executor strip */}
      {exec && (
        <div className={cn(
          "phantom-panel p-4 flex items-center gap-4 border",
          exec.running ? "border-green-500/30 bg-green-500/5" : "border-phantom-border",
        )}>
          <div className={cn(
            "w-10 h-10 rounded-lg flex items-center justify-center shrink-0 border",
            exec.running
              ? "bg-green-500/15 border-green-500/30"
              : "bg-phantom-panelHi border-phantom-border",
          )}>
            <Zap className={cn("w-5 h-5", exec.running ? "text-green-400" : "text-phantom-ghost")} strokeWidth={1.75} />
          </div>
          <div className="flex-1 min-w-0">
            <div className={cn("text-sm font-semibold",
              exec.running ? "text-green-400" : "text-phantom-ghost")}>
              Executor {exec.running ? "running" : "stopped"}
            </div>
            <div className="text-[11px] text-phantom-ghost font-mono mt-0.5">
              dispatched: {exec.dispatched} · failed: {exec.failed}
              {exec.last_error && ` · ${exec.last_error.slice(0, 60)}`}
            </div>
          </div>
          <button
            onClick={toggleExecutor}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold bg-phantom-panelHi border border-phantom-border hover:bg-phantom-panel"
          >
            {exec.running ? <Square className="w-3 h-3 text-red-400" /> : <Play className="w-3 h-3 text-green-400" />}
            {exec.running ? "Stop" : "Start"}
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Linked accounts */}
        <div className="phantom-panel overflow-hidden">
          <div className="px-5 py-3 border-b border-phantom-border bg-phantom-panelHi/40 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
              Linked Threads accounts ({accounts.length})
            </span>
          </div>
          {accounts.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-phantom-ghost">
              No Threads accounts linked yet. Link an IG account from the right.
            </div>
          ) : (
            <div className="divide-y divide-phantom-border/30 max-h-96 overflow-y-auto">
              {accounts.map((a) => (
                <button
                  key={a.account_id}
                  onClick={() => setSelected(a.account_id)}
                  className={cn(
                    "w-full px-5 py-3 flex items-center gap-3 text-left transition-colors",
                    selected === a.account_id
                      ? "bg-phantom-accent/5 border-l-2 border-l-phantom-accent"
                      : "hover:bg-phantom-panelHi/40 border-l-2 border-l-transparent",
                  )}
                >
                  <MessageCircle className="w-4 h-4 text-phantom-ghost shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-white truncate">
                      @{a.handle || a.account_id}
                    </div>
                    <div className="text-[10px] text-phantom-ghost">
                      IG: {a.ig_account_id.slice(0, 16)}… · day {a.warmup_day}/{status?.warming_days ?? 14}
                    </div>
                  </div>
                  {a.can_cross_post ? (
                    <CheckCircle2 className="w-4 h-4 text-green-400" />
                  ) : (
                    <AlertTriangle className="w-4 h-4 text-phantom-amber" />
                  )}
                  <Link
                    href={`/threads/${a.account_id}`}
                    onClick={(e) => e.stopPropagation()}
                    className="flex items-center gap-1 text-[10px] text-phantom-ghost hover:text-phantom-accent px-1.5 py-0.5 rounded hover:bg-phantom-accent/10"
                    title="Open account dossier"
                  >
                    <ExternalLink className="w-3 h-3" /> Drill
                  </Link>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Link new */}
        <div className="phantom-panel overflow-hidden">
          <div className="px-5 py-3 border-b border-phantom-border bg-phantom-panelHi/40">
            <span className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
              IG accounts without Threads ({unlinkedIG.length})
            </span>
          </div>
          {unlinkedIG.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-phantom-ghost">
              All IG accounts are linked to Threads.
            </div>
          ) : (
            <div className="divide-y divide-phantom-border/30 max-h-96 overflow-y-auto">
              {unlinkedIG.map((i) => (
                <div key={i.account_id} className="px-5 py-3 flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-white truncate">@{i.username}</div>
                    <div className="text-[10px] text-phantom-ghost">IG day {i.warmup_day}</div>
                  </div>
                  <button
                    onClick={() => link(i.account_id)}
                    disabled={linking === i.account_id}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold bg-phantom-accent/15 text-phantom-accent border border-phantom-accent/30 hover:bg-phantom-accent/25 disabled:opacity-50"
                  >
                    {linking === i.account_id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Link2 className="w-3 h-3" />}
                    Link
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Health / shadowban detector */}
      <div className="phantom-panel p-5">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <Heart className="w-4 h-4 text-phantom-accent" />
          <h2 className="text-sm font-semibold">Account health · shadowban detector</h2>
          <span className="text-[10px] text-phantom-ghost">
            Funnel decay · dispatch failures · queue stall · warming stagnation. Orchestrator skips shadowbanned, dampens at_risk.
          </span>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={scanHealth}
              disabled={scanning}
              className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold bg-phantom-accent/15 text-phantom-accent border border-phantom-accent/30 hover:bg-phantom-accent/25 disabled:opacity-50"
            >
              {scanning ? <Loader2 className="w-3 h-3 animate-spin" /> : <Activity className="w-3 h-3" />}
              Scan fleet
            </button>
          </div>
        </div>
        {health ? (
          <>
            <div className="grid grid-cols-4 gap-2 mb-3">
              <div className="p-3 rounded-md border border-green-500/30 bg-green-500/5">
                <div className="flex items-center gap-1.5 text-[10px] text-green-400 uppercase tracking-wider">
                  <Heart className="w-3 h-3" /> Healthy
                </div>
                <div className="text-2xl font-mono text-green-400 mt-1">{health.rollup.healthy}</div>
              </div>
              <div className="p-3 rounded-md border border-phantom-amber/30 bg-phantom-amber/5">
                <div className="flex items-center gap-1.5 text-[10px] text-phantom-amber uppercase tracking-wider">
                  <Eye className="w-3 h-3" /> Watch
                </div>
                <div className="text-2xl font-mono text-phantom-amber mt-1">{health.rollup.watch}</div>
              </div>
              <div className="p-3 rounded-md border border-orange-500/30 bg-orange-500/5">
                <div className="flex items-center gap-1.5 text-[10px] text-orange-400 uppercase tracking-wider">
                  <AlertTriangle className="w-3 h-3" /> At risk
                </div>
                <div className="text-2xl font-mono text-orange-400 mt-1">{health.rollup.at_risk}</div>
              </div>
              <div className="p-3 rounded-md border border-red-500/30 bg-red-500/5">
                <div className="flex items-center gap-1.5 text-[10px] text-red-400 uppercase tracking-wider">
                  <Ghost className="w-3 h-3" /> Shadowbanned
                </div>
                <div className="text-2xl font-mono text-red-400 mt-1">{health.rollup.shadowbanned}</div>
              </div>
            </div>

            {Object.keys(health.flag_counts).length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-3">
                {Object.entries(health.flag_counts).map(([flag, n]) => (
                  <span
                    key={flag}
                    className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-phantom-panelHi border border-phantom-border text-phantom-ghost"
                  >
                    {flag} · {n}
                  </span>
                ))}
              </div>
            )}

            <div className="text-[10px] text-phantom-ghost mb-2 font-mono">
              Last scan: {health.rollup.last_scan_at ? new Date(health.rollup.last_scan_at).toLocaleTimeString() : "never"}
              {" · "}Total scans: {health.rollup.total_scans}
              {" · "}Fleet size: {health.rollup.total}
            </div>

            {health.at_risk.length > 0 ? (
              <div className="rounded-md border border-phantom-border overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-phantom-panelHi text-[10px] uppercase text-phantom-ghost">
                    <tr>
                      <th className="text-left px-3 py-2">Account</th>
                      <th className="text-left px-3 py-2">Status</th>
                      <th className="text-right px-3 py-2">Score</th>
                      <th className="text-left px-3 py-2">Flags</th>
                      <th className="text-right px-3 py-2">Replies · Views</th>
                      <th className="text-right px-3 py-2">R→V</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-phantom-border/30">
                    {health.at_risk.map((h) => (
                      <tr key={h.account_id}>
                        <td className="px-3 py-2 font-mono text-[11px]">{h.account_id.slice(0, 12)}…</td>
                        <td className="px-3 py-2">
                          <span className={cn(
                            "text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded",
                            h.status === "shadowbanned" ? "text-red-400 bg-red-500/10" :
                            h.status === "at_risk"      ? "text-orange-400 bg-orange-500/10" :
                            h.status === "watch"        ? "text-phantom-amber bg-phantom-amber/10" :
                                                          "text-green-400 bg-green-500/10",
                          )}>
                            {h.status}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{h.score}</td>
                        <td className="px-3 py-2 text-[10px] text-phantom-ghost">{h.flags.join(", ") || "—"}</td>
                        <td className="px-3 py-2 text-right font-mono text-[11px]">
                          {h.signals.reply_posted} · {h.signals.profile_view}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-[11px]">
                          {(h.signals.reply_to_view_rate * 100).toFixed(1)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-[11px] text-phantom-ghost flex items-center gap-2 p-2">
                <CheckCircle2 className="w-3 h-3 text-green-400" />
                No accounts at risk. Fleet is clean.
              </div>
            )}

            {accounts.length > 0 && (
              <div className="mt-3 p-3 rounded-md border border-phantom-border bg-phantom-panelHi">
                <div className="text-[10px] text-phantom-ghost uppercase tracking-wider mb-2">
                  Trip a flag (dev only)
                </div>
                <div className="flex flex-wrap gap-1.5 items-center text-[11px]">
                  <span className="text-phantom-ghost">on</span>
                  <span className="font-mono">{accounts[0].account_id.slice(0, 10)}…</span>
                  <span className="text-phantom-ghost">→</span>
                  {["funnel_ghost", "reply_sink", "dispatch_fail", "queue_stall"].map((sc) => (
                    <button
                      key={sc}
                      onClick={() => simulateHealth(accounts[0].account_id, sc)}
                      className="px-2 py-1 rounded bg-phantom-panel border border-phantom-border hover:border-phantom-accent/50 text-[10px] font-mono"
                    >
                      {sc}
                    </button>
                  ))}
                </div>
                {simHealth && (
                  <div className="text-[11px] font-mono text-phantom-accent mt-2">{simHealth}</div>
                )}
              </div>
            )}
          </>
        ) : (
          <div className="text-[11px] text-phantom-ghost flex items-center gap-2">
            <Circle className="w-3 h-3" /> No scan yet. Click Scan fleet.
          </div>
        )}
      </div>

      {/* Active probes */}
      {probes && (
        <div className="phantom-panel p-5">
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <Search className="w-4 h-4 text-phantom-accent" />
            <h2 className="text-sm font-semibold">Active shadowban probes</h2>
            <span className="text-[10px] text-phantom-ghost">
              Search / hashtag / reply visibility — searcher-side look-ups run from healthy fleet accounts.
            </span>
            <div className="ml-auto flex items-center gap-2">
              <span className={cn("text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded",
                probes.running ? "text-green-400 bg-green-500/10" : "text-phantom-ghost bg-phantom-panelHi")}>
                {probes.running ? "running" : "stopped"}
              </span>
              <button
                onClick={runProbes}
                disabled={probesTicking}
                className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold bg-phantom-accent/15 text-phantom-accent border border-phantom-accent/30 hover:bg-phantom-accent/25 disabled:opacity-50"
              >
                {probesTicking ? <Loader2 className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />}
                Sweep now
              </button>
            </div>
          </div>
          <div className="grid grid-cols-4 gap-2 mb-3">
            <div className="p-3 rounded-md border border-phantom-border bg-phantom-panelHi">
              <div className="text-[10px] uppercase tracking-wider text-phantom-ghost">Total probes</div>
              <div className="text-2xl font-mono text-phantom-accent mt-1">{probes.stats.total_run}</div>
            </div>
            <div className="p-3 rounded-md border border-green-500/30 bg-green-500/5">
              <div className="text-[10px] uppercase tracking-wider text-green-400">Found</div>
              <div className="text-2xl font-mono text-green-400 mt-1">{probes.stats.total_found}</div>
            </div>
            <div className="p-3 rounded-md border border-red-500/30 bg-red-500/5">
              <div className="text-[10px] uppercase tracking-wider text-red-400">Hidden</div>
              <div className="text-2xl font-mono text-red-400 mt-1">{probes.stats.total_hidden}</div>
            </div>
            <div className="p-3 rounded-md border border-phantom-amber/30 bg-phantom-amber/5">
              <div className="text-[10px] uppercase tracking-wider text-phantom-amber">Hidden rate</div>
              <div className="text-2xl font-mono text-phantom-amber mt-1">{(probes.stats.hidden_rate * 100).toFixed(1)}%</div>
            </div>
          </div>
          <div className="text-[10px] text-phantom-ghost mb-2 font-mono">
            Tick: {probes.tick_sec}s · Last run:{" "}
            {probes.stats.last_run_at ? new Date(probes.stats.last_run_at).toLocaleTimeString() : "never"}
          </div>
          {probes.recent.length > 0 ? (
            <div className="rounded-md border border-phantom-border overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-phantom-panelHi text-[10px] uppercase text-phantom-ghost">
                  <tr>
                    <th className="text-left px-3 py-2">Kind</th>
                    <th className="text-left px-3 py-2">Suspect</th>
                    <th className="text-left px-3 py-2">Searcher</th>
                    <th className="text-center px-3 py-2">Result</th>
                    <th className="text-right px-3 py-2">When</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-phantom-border/30">
                  {probes.recent.slice(0, 15).map((r) => {
                    const Icon = r.kind === "search_reach" ? Search
                               : r.kind === "hashtag_reach" ? Hash
                               : ReplyIcon;
                    return (
                      <tr key={r.probe_id}>
                        <td className="px-3 py-2 text-[11px] flex items-center gap-1.5">
                          <Icon className="w-3 h-3 text-phantom-accent" />
                          {r.kind}
                        </td>
                        <td className="px-3 py-2 font-mono text-[11px]">{r.account_id.slice(0, 12)}…</td>
                        <td className="px-3 py-2 font-mono text-[10px] text-phantom-ghost">{r.searcher_id.slice(0, 12)}…</td>
                        <td className="px-3 py-2 text-center">
                          <span className={cn("text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded",
                            r.found ? "text-green-400 bg-green-500/10" : "text-red-400 bg-red-500/10")}>
                            {r.found ? "found" : "hidden"}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right text-[10px] font-mono text-phantom-ghost">
                          {new Date(r.checked_at).toLocaleTimeString()}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-[11px] text-phantom-ghost">No probe results yet. Click Sweep now to run one tick.</div>
          )}
        </div>
      )}

      {/* ThreadsAgent — CLAUDE.md agent frame */}
      {agentSummary && (
        <div className="phantom-panel p-5">
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <Bot className="w-4 h-4 text-phantom-accent" />
            <h2 className="text-sm font-semibold">ThreadsAgent · dispatch frame</h2>
            <span className="text-[10px] text-phantom-ghost">
              CLAUDE.md agent-audit: named tool allowlist, iteration cap, per-run + session cost caps, audit log.
            </span>
            <div className="ml-auto flex items-center gap-2 text-[10px] font-mono">
              <span className="text-phantom-ghost">cap</span>
              <span className="text-phantom-accent">${agentSummary.config.max_usd_per_run.toFixed(2)}/run</span>
              <span className="text-phantom-ghost">·</span>
              <span className="text-phantom-accent">${agentSummary.config.max_usd_per_session.toFixed(2)}/session</span>
              <span className="text-phantom-ghost">·</span>
              <span className="text-phantom-accent">max {agentSummary.config.max_iterations} iters</span>
            </div>
          </div>
          <div className="grid grid-cols-4 gap-2 mb-3">
            <div className="p-3 rounded-md border border-phantom-border bg-phantom-panelHi">
              <div className="text-[10px] uppercase tracking-wider text-phantom-ghost">Runs</div>
              <div className="text-2xl font-mono text-phantom-accent mt-1">{agentSummary.runs.total}</div>
            </div>
            <div className="p-3 rounded-md border border-green-500/30 bg-green-500/5">
              <div className="text-[10px] uppercase tracking-wider text-green-400">Success</div>
              <div className="text-2xl font-mono text-green-400 mt-1">{agentSummary.runs.by_status.success ?? 0}</div>
            </div>
            <div className="p-3 rounded-md border border-red-500/30 bg-red-500/5">
              <div className="text-[10px] uppercase tracking-wider text-red-400">Failed / blocked</div>
              <div className="text-2xl font-mono text-red-400 mt-1">
                {(agentSummary.runs.by_status.failed ?? 0)
                  + (agentSummary.runs.by_status.blocked_confirmation ?? 0)
                  + (agentSummary.runs.by_status.cost_exceeded ?? 0)}
              </div>
            </div>
            <div className="p-3 rounded-md border border-phantom-amber/30 bg-phantom-amber/5">
              <div className="text-[10px] uppercase tracking-wider text-phantom-amber">Total cost</div>
              <div className="text-2xl font-mono text-phantom-amber mt-1">${agentSummary.runs.total_cost.toFixed(4)}</div>
            </div>
          </div>
          <div className="flex flex-wrap gap-1 mb-3">
            {agentSummary.config.allowed_tools.map((t) => (
              <span key={t} className="text-[10px] font-mono px-2 py-0.5 rounded bg-phantom-panelHi border border-phantom-border text-phantom-ghost">
                {t}
              </span>
            ))}
          </div>
          {agentSummary.recent.length > 0 ? (
            <div className="rounded-md border border-phantom-border overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-phantom-panelHi text-[10px] uppercase text-phantom-ghost">
                  <tr>
                    <th className="text-left px-3 py-2">Run</th>
                    <th className="text-left px-3 py-2">Account</th>
                    <th className="text-left px-3 py-2">Kind</th>
                    <th className="text-left px-3 py-2">Status</th>
                    <th className="text-right px-3 py-2">Iters</th>
                    <th className="text-right px-3 py-2">Cost</th>
                    <th className="text-right px-3 py-2">When</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-phantom-border/30">
                  {agentSummary.recent.map((r) => (
                    <tr key={r.run_id}>
                      <td className="px-3 py-2 font-mono text-[10px] text-phantom-ghost">{r.run_id.slice(0, 8)}</td>
                      <td className="px-3 py-2 font-mono text-[11px]">{r.account_id.slice(0, 12)}…</td>
                      <td className="px-3 py-2 text-[11px]">{r.kind}</td>
                      <td className="px-3 py-2">
                        <span className={cn(
                          "text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded",
                          r.status === "success"              ? "text-green-400 bg-green-500/10" :
                          r.status === "failed"               ? "text-red-400 bg-red-500/10" :
                          r.status === "cost_exceeded"        ? "text-phantom-amber bg-phantom-amber/10" :
                          r.status === "blocked_confirmation" ? "text-blue-400 bg-blue-500/10" :
                                                                "text-phantom-ghost bg-phantom-panelHi")}>
                          {r.status}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono">{r.iterations}/{agentSummary.config.max_iterations}</td>
                      <td className="px-3 py-2 text-right font-mono text-[11px]">${r.cost_usd.toFixed(4)}</td>
                      <td className="px-3 py-2 text-right font-mono text-[10px] text-phantom-ghost">
                        {new Date(r.started_at).toLocaleTimeString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-[11px] text-phantom-ghost">No agent runs yet. The orchestrator routes every planned action through this agent.</div>
          )}
        </div>
      )}

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
            Fleet rebalancer · {rebalancer.stats.level}
          </span>
          <span className="text-phantom-ghost">plan ×{rebalancer.throttles.plan_per_tick_multiplier.toFixed(2)}</span>
          <span className="text-phantom-ghost">·</span>
          <span className="text-phantom-ghost">linking {rebalancer.throttles.linking_allowed ? "allowed" : "paused"}</span>
          <span className="text-phantom-ghost">·</span>
          <span className="text-phantom-ghost">shadowban {(rebalancer.snapshot.shadowban_rate*100).toFixed(0)}%</span>
          <span className="text-phantom-ghost">·</span>
          <span className="text-phantom-ghost">hidden {(rebalancer.snapshot.hidden_rate*100).toFixed(0)}%</span>
          <span className="text-phantom-ghost">·</span>
          <span className="text-phantom-ghost">enroll burst {rebalancer.snapshot.enrollment_burst}</span>
          <span className="text-phantom-ghost">·</span>
          <span className="text-phantom-ghost">ticks {rebalancer.stats.total_ticks}</span>
          <span className="text-phantom-ghost">·</span>
          <span className="text-phantom-ghost">alerts {rebalancer.stats.total_alerts}</span>
        </div>
      )}

      {/* Persistence strip */}
      <div className={cn(
        "phantom-panel p-3 flex items-center gap-3 flex-wrap text-[11px] font-mono",
        persistence?.enabled
          ? "border-green-500/30"
          : "border-phantom-amber/30",
      )}>
        <Database className={cn("w-4 h-4",
          persistence?.enabled ? "text-green-400" : "text-phantom-amber")} />
        <span className={cn("uppercase tracking-wider",
          persistence?.enabled ? "text-green-400" : "text-phantom-amber")}>
          Persistence · {persistence?.enabled ? "ON" : "OFF (in-memory only)"}
        </span>
        {persistence?.enabled ? (
          <>
            <span className="text-phantom-ghost">funnel: {persistence.funnel_events}</span>
            <span className="text-phantom-ghost">·</span>
            <span className="text-phantom-ghost">health: {persistence.health_snapshots}</span>
            <span className="text-phantom-ghost">·</span>
            <span className="text-phantom-ghost">recovery: {persistence.recovery_records}</span>
            <span className="text-phantom-ghost">·</span>
            <span className="text-phantom-ghost">IG events: {persistence.ig_events}</span>
          </>
        ) : (
          <span className="text-phantom-ghost">
            A restart will wipe funnel, health, recovery, and IG bus state. Bring up Postgres (DATABASE_URL + migrations/009) to turn on.
          </span>
        )}
      </div>

      {/* Recovery agent */}
      <div className="phantom-panel p-5">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <RotateCw className="w-4 h-4 text-phantom-accent" />
          <h2 className="text-sm font-semibold">Shadowban recovery agent</h2>
          <span className="text-[10px] text-phantom-ghost">
            Enrolls shadowbanned → cool-down → rewarm (day 1) → graduate or strike. Three strikes = retire.
          </span>
          <div className="ml-auto flex items-center gap-2">
            <span className={cn("text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded",
              recovery?.running ? "text-green-400 bg-green-500/10" : "text-phantom-ghost bg-phantom-panelHi")}>
              {recovery?.running ? "running" : "stopped"}
            </span>
            <button
              onClick={tickRecovery}
              disabled={recoveryTicking}
              className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold bg-phantom-accent/15 text-phantom-accent border border-phantom-accent/30 hover:bg-phantom-accent/25 disabled:opacity-50"
            >
              {recoveryTicking ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCw className="w-3 h-3" />}
              Tick now
            </button>
          </div>
        </div>
        {recovery ? (
          <>
            <div className="grid grid-cols-5 gap-2 mb-3">
              <div className="p-3 rounded-md border border-blue-500/30 bg-blue-500/5">
                <div className="flex items-center gap-1.5 text-[10px] text-blue-400 uppercase tracking-wider">
                  <Snowflake className="w-3 h-3" /> Cool-down
                </div>
                <div className="text-2xl font-mono text-blue-400 mt-1">{recovery.stats.cooling_down}</div>
              </div>
              <div className="p-3 rounded-md border border-orange-500/30 bg-orange-500/5">
                <div className="flex items-center gap-1.5 text-[10px] text-orange-400 uppercase tracking-wider">
                  <Flame className="w-3 h-3" /> Rewarming
                </div>
                <div className="text-2xl font-mono text-orange-400 mt-1">{recovery.stats.rewarming}</div>
              </div>
              <div className="p-3 rounded-md border border-green-500/30 bg-green-500/5">
                <div className="flex items-center gap-1.5 text-[10px] text-green-400 uppercase tracking-wider">
                  <GraduationCap className="w-3 h-3" /> Graduated
                </div>
                <div className="text-2xl font-mono text-green-400 mt-1">{recovery.stats.total_graduated}</div>
              </div>
              <div className="p-3 rounded-md border border-red-500/30 bg-red-500/5">
                <div className="flex items-center gap-1.5 text-[10px] text-red-400 uppercase tracking-wider">
                  <XOctagon className="w-3 h-3" /> Retired
                </div>
                <div className="text-2xl font-mono text-red-400 mt-1">{recovery.stats.total_retired}</div>
              </div>
              <div className="p-3 rounded-md border border-phantom-border bg-phantom-panelHi">
                <div className="text-[10px] text-phantom-ghost uppercase tracking-wider">Enrolled</div>
                <div className="text-2xl font-mono text-phantom-accent mt-1">{recovery.stats.total_enrolled}</div>
              </div>
            </div>
            <div className="text-[10px] text-phantom-ghost mb-2 font-mono">
              Cool-down: {recovery.config.cool_down_sec}s · Rewarm→graduate: {recovery.config.rewarm_graduate_replies} replies ·
              Max strikes: {recovery.config.max_strikes} ·
              Last tick: {recovery.stats.last_tick_at ? new Date(recovery.stats.last_tick_at).toLocaleTimeString() : "never"}
            </div>
            {recovery.records.length > 0 ? (
              <div className="rounded-md border border-phantom-border overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-phantom-panelHi text-[10px] uppercase text-phantom-ghost">
                    <tr>
                      <th className="text-left px-3 py-2">Account</th>
                      <th className="text-left px-3 py-2">Phase</th>
                      <th className="text-right px-3 py-2">Strikes</th>
                      <th className="text-left px-3 py-2">Progress</th>
                      <th className="text-left px-3 py-2">Notes</th>
                      <th className="text-right px-3 py-2">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-phantom-border/30">
                    {recovery.records.map((r) => (
                      <tr key={r.account_id}>
                        <td className="px-3 py-2 font-mono text-[11px]">{r.account_id.slice(0, 14)}…</td>
                        <td className="px-3 py-2">
                          <span className={cn(
                            "text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded",
                            r.phase === "cooling_down" ? "text-blue-400 bg-blue-500/10" :
                            r.phase === "rewarming"    ? "text-orange-400 bg-orange-500/10" :
                            r.phase === "graduated"    ? "text-green-400 bg-green-500/10" :
                                                         "text-red-400 bg-red-500/10",
                          )}>{r.phase}</span>
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{r.strikes}/{recovery.config.max_strikes}</td>
                        <td className="px-3 py-2 text-[11px] font-mono">
                          {r.phase === "cooling_down" && (
                            <span>until {new Date(r.cool_down_until).toLocaleTimeString()}</span>
                          )}
                          {r.phase === "rewarming" && (
                            <span>{r.rewarm_actions_observed}/{recovery.config.rewarm_graduate_replies} replies</span>
                          )}
                          {r.phase === "graduated" && r.graduated_at && (
                            <span className="text-green-400">at {new Date(r.graduated_at).toLocaleTimeString()}</span>
                          )}
                          {r.phase === "retired" && r.retired_at && (
                            <span className="text-red-400">at {new Date(r.retired_at).toLocaleTimeString()}</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-[10px] text-phantom-ghost max-w-[260px] truncate">
                          {r.notes[r.notes.length - 1] ?? "—"}
                        </td>
                        <td className="px-3 py-2 text-right space-x-1">
                          {r.phase === "cooling_down" && (
                            <button
                              onClick={() => skipCooldown(r.account_id)}
                              className="px-2 py-0.5 rounded border border-phantom-border text-[10px] hover:border-phantom-accent/50"
                            >skip cooldown</button>
                          )}
                          {(r.phase === "cooling_down" || r.phase === "rewarming") && (
                            <button
                              onClick={() => forceGraduate(r.account_id)}
                              className="px-2 py-0.5 rounded border border-phantom-border text-[10px] hover:border-phantom-accent/50"
                            >graduate</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-[11px] text-phantom-ghost flex items-center gap-2 p-2">
                <CheckCircle2 className="w-3 h-3 text-green-400" />
                No accounts in recovery. The agent enrolls shadowbanned accounts automatically.
              </div>
            )}
          </>
        ) : (
          <div className="text-[11px] text-phantom-ghost flex items-center gap-2">
            <Circle className="w-3 h-3" /> Loading recovery state…
          </div>
        )}
      </div>

      {/* Audit harness */}
      <div className="phantom-panel p-5">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <FlaskConical className="w-4 h-4 text-phantom-accent" />
          <h2 className="text-sm font-semibold">Monte Carlo audit harness</h2>
          <span className="text-[10px] text-phantom-ghost">
            CLAUDE.md §Fleet-scale audit gate — N-persona distribution coverage.
          </span>
          <div className="ml-auto flex items-center gap-2">
            <select
              value={auditN}
              onChange={(e) => setAuditN(Number(e.target.value))}
              className="px-2 py-1 rounded-md bg-phantom-panelHi border border-phantom-border text-[11px]"
            >
              <option value={1000}>N = 1,000</option>
              <option value={10000}>N = 10,000</option>
              <option value={25000}>N = 25,000</option>
            </select>
            <button
              onClick={runAudit}
              disabled={auditing}
              className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold bg-phantom-accent/15 text-phantom-accent border border-phantom-accent/30 hover:bg-phantom-accent/25 disabled:opacity-50"
            >
              {auditing ? <Loader2 className="w-3 h-3 animate-spin" /> : <FlaskConical className="w-3 h-3" />}
              Run audit
            </button>
          </div>
        </div>
        {audit ? (
          <>
            <div className={cn(
              "flex items-center gap-3 p-3 rounded-md border mb-3",
              audit.passed
                ? "bg-green-500/5 border-green-500/30"
                : "bg-red-500/5 border-red-500/30",
            )}>
              {audit.passed
                ? <ShieldCheck className="w-5 h-5 text-green-400" />
                : <AlertCircle className="w-5 h-5 text-red-400" />}
              <div className="flex-1">
                <div className={cn("text-sm font-semibold",
                  audit.passed ? "text-green-400" : "text-red-400")}>
                  {audit.passed ? "All distribution checks passed" : "Audit gate FAILED"}
                </div>
                <div className="text-[10px] text-phantom-ghost font-mono mt-0.5">
                  {audit.n_personas.toLocaleString()} personas · {audit.duration_ms.toFixed(0)}ms ·
                  {" "}pass {audit.pass_count} · warn {audit.warn_count} · fail {audit.fail_count}
                </div>
              </div>
              <div className="text-[10px] text-phantom-ghost font-mono">
                {new Date(audit.ran_at).toLocaleTimeString()}
              </div>
            </div>
            <div className="divide-y divide-phantom-border/30">
              {audit.checks.map((c) => (
                <div key={c.key} className="py-2 flex items-start gap-3">
                  {c.status === "pass"
                    ? <CheckCircle2 className="w-4 h-4 text-green-400 shrink-0 mt-0.5" />
                    : c.status === "warn"
                      ? <AlertTriangle className="w-4 h-4 text-phantom-amber shrink-0 mt-0.5" />
                      : <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{c.label}</span>
                      <span className={cn(
                        "text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded",
                        c.status === "pass" ? "text-green-400 bg-green-500/10" :
                        c.status === "warn" ? "text-phantom-amber bg-phantom-amber/10" :
                                               "text-red-400 bg-red-500/10",
                      )}>
                        {c.status}
                      </span>
                    </div>
                    <div className="text-[11px] text-phantom-ghost mt-0.5">{c.detail}</div>
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="text-[11px] text-phantom-ghost flex items-center gap-2">
            <Circle className="w-3 h-3" /> No audit run yet. Click Run audit to sweep.
          </div>
        )}
      </div>

      {/* IG → Threads bridge panel */}
      {bridge && (
        <div className="phantom-panel p-5">
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <Radio className="w-4 h-4 text-phantom-accent" />
            <h2 className="text-sm font-semibold">IG → Threads auto bridge</h2>
            <span className="text-[11px] text-phantom-ghost font-mono">
              events: {bridge.events_in} · replies: {bridge.replies_out}
              {" · skipped "}
              (budget {bridge.skipped_budget} · no-link {bridge.skipped_no_link} · day-7 {bridge.skipped_gate})
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-2 items-start">
            <select
              value={simIG}
              onChange={(e) => setSimIG(e.target.value)}
              className="md:col-span-2 px-3 py-2 rounded-md bg-phantom-panelHi border border-phantom-border text-xs"
            >
              <option value="">— simulate IG post from —</option>
              {igAccounts.map((i) => (
                <option key={i.account_id} value={i.account_id}>
                  @{i.username} · day {i.warmup_day}
                </option>
              ))}
            </select>
            <input
              value={simCaption}
              onChange={(e) => setSimCaption(e.target.value)}
              placeholder="caption (optional)"
              className="md:col-span-2 px-3 py-2 rounded-md bg-phantom-panelHi border border-phantom-border text-xs"
            />
            <button
              onClick={simulateIG}
              disabled={simulating || !simIG}
              className={cn(
                "flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-xs font-semibold border",
                simulating || !simIG
                  ? "bg-phantom-panelHi text-phantom-ghost border-phantom-border cursor-not-allowed"
                  : "bg-phantom-accent/15 text-phantom-accent border-phantom-accent/30 hover:bg-phantom-accent/25",
              )}
            >
              {simulating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Instagram className="w-3 h-3" />}
              Fire IG post
            </button>
          </div>
          {simIG && (() => {
            const ig = igAccounts.find((i) => i.account_id === simIG);
            if (!ig) return null;
            const needsBump = ig.warmup_day < 7;
            return needsBump ? (
              <div className="mt-2 text-[11px] text-phantom-amber flex items-center gap-2">
                IG @{ig.username} is at day {ig.warmup_day} — day-7 gate will skip the bridge.
                <button
                  onClick={() => setIGDay(ig.account_id, 8)}
                  className="px-2 py-0.5 rounded text-[10px] bg-phantom-amber/15 text-phantom-amber border border-phantom-amber/30 hover:bg-phantom-amber/25"
                >
                  bump to day 8
                </button>
              </div>
            ) : null;
          })()}
          {simResult && (
            <div className="mt-2 text-[11px] font-mono text-phantom-ghost">{simResult}</div>
          )}
          {igEvents.length > 0 && (
            <div className="mt-4 max-h-40 overflow-y-auto divide-y divide-phantom-border/30">
              {igEvents.map((e, i) => (
                <div key={`${e.post_id}-${i}`} className="py-1.5 flex items-center gap-3 text-xs">
                  <code className="text-phantom-accent font-mono">{e.post_id.slice(0, 16)}</code>
                  <span className="text-phantom-ghost">from {e.ig_account_id.slice(0, 16)}</span>
                  {e.caption && <span className="text-phantom-ghost italic truncate max-w-[280px]">&ldquo;{e.caption}&rdquo;</span>}
                  <span className="ml-auto text-[10px] text-phantom-ghost font-mono">
                    {new Date(e.ts).toLocaleTimeString()} · {e.source}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Orchestrator panel */}
      {orch && (
        <div className="phantom-panel p-5">
          <div className="flex items-center gap-3 flex-wrap mb-3">
            <Brain className="w-5 h-5 text-phantom-accent" />
            <h2 className="text-sm font-semibold">Orchestrator</h2>
            <span className={cn(
              "text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded",
              orch.running ? "text-green-400 bg-green-500/10" : "text-phantom-ghost bg-phantom-panelHi",
            )}>
              {orch.running ? "running" : "stopped"}
            </span>
            <span className="text-[11px] text-phantom-ghost font-mono">
              runs: {orch.total_runs} · enqueued: {orch.total_enqueued}
              {orch.last_run_at && ` · last ${new Date(orch.last_run_at).toLocaleTimeString()}`}
            </span>
            <div className="ml-auto flex items-center gap-2">
              <button onClick={toggleOrch}
                className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs bg-phantom-panelHi border border-phantom-border hover:bg-phantom-panel">
                {orch.running ? <Square className="w-3 h-3 text-red-400" /> : <Play className="w-3 h-3 text-green-400" />}
                {orch.running ? "Stop" : "Start"}
              </button>
              <button onClick={planNow} disabled={planning}
                className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold bg-phantom-accent/15 text-phantom-accent border border-phantom-accent/30 hover:bg-phantom-accent/25 disabled:opacity-50">
                {planning ? <Loader2 className="w-3 h-3 animate-spin" /> : <Brain className="w-3 h-3" />}
                Plan now
              </button>
            </div>
          </div>
          {orch.last_plan.length === 0 ? (
            <div className="text-[11px] text-phantom-ghost">
              No plan yet — click &ldquo;Plan now&rdquo; to run one tick.
            </div>
          ) : (
            <div className="space-y-1">
              {orch.last_plan.map((p, i) => (
                <div key={`${p.account_id}-${i}`} className="flex items-center gap-3 text-xs">
                  <span className="font-mono uppercase tracking-wider text-[9px] px-1.5 py-0.5 rounded bg-phantom-panelHi text-phantom-accent border border-phantom-border">
                    {p.kind}
                  </span>
                  <code className="text-phantom-ghost">{p.account_id.slice(0, 16)}</code>
                  {p.target && <span className="text-phantom-ghost">→ {p.target}</span>}
                  {p.body && <span className="text-phantom-ghost italic truncate max-w-[280px]">&ldquo;{p.body}&rdquo;</span>}
                  <span className="ml-auto text-[10px] text-phantom-ghost font-mono">{p.reason}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Funnel overview */}
      {funnel && (
        <div className="phantom-panel p-5">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp className="w-4 h-4 text-phantom-accent" />
            <h2 className="text-sm font-semibold">Funnel · IG post → Threads reply → bio → sub</h2>
            <span className="ml-auto text-[10px] text-phantom-ghost">
              {funnel.accounts} account(s) tracked
            </span>
          </div>
          <FunnelBar counts={funnel.totals.counts} rates={funnel.totals.rates} />
          {funnel.top.length > 0 && (
            <div className="mt-4">
              <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-2 flex items-center gap-2">
                <Trophy className="w-3 h-3" /> Top accounts by reply→sub rate
              </div>
              <div className="space-y-1">
                {funnel.top.map((row) => (
                  <div key={row.threads_account_id} className="flex items-center gap-3 text-xs">
                    <code className="text-phantom-accent font-mono">
                      {row.threads_account_id.slice(0, 16)}
                    </code>
                    <span className="text-phantom-ghost">
                      {row.counts.reply_posted} replies · {row.counts.profile_view} views ·
                      {" "}{row.counts.bio_link_click} clicks · {row.counts.subscribe} subs
                    </span>
                    <span className="ml-auto font-mono text-green-400">
                      {(row.rates.reply_to_sub * 100).toFixed(2)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Cross-post bridge */}
      <div className="phantom-panel p-5">
        <div className="flex items-center gap-2 mb-3">
          <ArrowRightLeft className="w-4 h-4 text-phantom-accent" />
          <h2 className="text-sm font-semibold">IG → Threads cross-post</h2>
          <span className="text-[10px] text-phantom-ghost">
            Enqueues a reply from the Threads account linked to the chosen IG account.
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <select
            value={crossPostIG}
            onChange={(e) => setCrossPostIG(e.target.value)}
            className="px-3 py-2 rounded-md bg-phantom-panelHi border border-phantom-border text-xs"
          >
            <option value="">— pick IG account —</option>
            {igAccounts.map((i) => (
              <option key={i.account_id} value={i.account_id}>@{i.username}</option>
            ))}
          </select>
          <input
            value={crossPostBody}
            onChange={(e) => setCrossPostBody(e.target.value)}
            placeholder="Threads reply body (links, funnel CTA…)"
            className="md:col-span-2 px-3 py-2 rounded-md bg-phantom-panelHi border border-phantom-border text-xs"
          />
        </div>
        <div className="flex items-center justify-end mt-2">
          <button
            onClick={crossPost}
            disabled={crossPosting || !crossPostIG || !crossPostBody}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold border",
              crossPosting || !crossPostIG || !crossPostBody
                ? "bg-phantom-panelHi text-phantom-ghost border-phantom-border cursor-not-allowed"
                : "bg-phantom-accent/15 text-phantom-accent border-phantom-accent/30 hover:bg-phantom-accent/25",
            )}
          >
            {crossPosting ? <Loader2 className="w-3 h-3 animate-spin" /> : <ArrowRightLeft className="w-3 h-3" />}
            Cross-post
          </button>
        </div>
      </div>

      {/* Queue table */}
      {queueView && queueView.entries.length > 0 && (
        <div className="phantom-panel overflow-hidden">
          <div className="px-5 py-3 border-b border-phantom-border bg-phantom-panelHi/40 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
              Action queue · queued {queueView.queued} · dispatched {queueView.dispatched} · failed {queueView.failed}
            </span>
          </div>
          <div className="divide-y divide-phantom-border/30 max-h-80 overflow-y-auto">
            {queueView.entries.slice().reverse().map((e) => (
              <div key={e.action_id} className="px-5 py-2 flex items-center gap-3 text-xs">
                <span className={cn(
                  "font-mono uppercase tracking-wider px-1.5 py-0.5 rounded text-[9px]",
                  e.status === "dispatched" ? "text-green-400 bg-green-500/10" :
                  e.status === "failed"     ? "text-red-400 bg-red-500/10" :
                                              "text-phantom-amber bg-phantom-amber/10",
                )}>
                  {e.status}
                </span>
                <span className="font-mono text-phantom-accent">{e.kind}</span>
                <span className="text-phantom-ghost">{e.account_id.slice(0, 14)}…</span>
                {e.target && <span className="text-phantom-ghost">→ {e.target}</span>}
                {e.phone_serial && <span className="text-[10px] text-phantom-ghost">on {e.phone_serial}</span>}
                <span className="ml-auto text-[10px] text-phantom-ghost font-mono">
                  {e.dispatched_at ? new Date(e.dispatched_at).toLocaleTimeString() : new Date(e.queued_at).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Selected account console */}
      {selectedAccount && budget && (
        <div className="phantom-panel p-5 space-y-4">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <div className="text-sm font-semibold text-white">
                @{selectedAccount.handle} · <span className="text-phantom-ghost">day {budget.day}</span>
              </div>
              <div className="text-[11px] text-phantom-ghost mt-0.5">
                {selectedAccount.can_cross_post
                  ? "IG parent past day 7 — replies unblocked."
                  : "IG parent below day 7 — replies gated."}
              </div>
            </div>
            <button onClick={advanceDay}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-phantom-panelHi border border-phantom-border hover:bg-phantom-panel">
              <Clock className="w-3 h-3" /> Advance day
            </button>
          </div>

          {/* Budget tiles */}
          <div className="grid grid-cols-4 gap-2">
            {ACTION_META.map((m) => {
              const b = budget[m.kind as keyof Budget] as number;
              const Icon = m.icon;
              return (
                <div key={m.kind} className="phantom-panel p-3 text-center">
                  <Icon className={cn("w-4 h-4 mx-auto", m.color)} />
                  <div className={cn("text-xl font-display font-bold mt-1 tabular-nums",
                    b === 0 ? "text-phantom-ghost" : m.color)}>{b}</div>
                  <div className="text-[9px] text-phantom-ghost uppercase tracking-wider mt-0.5">
                    {m.label} today
                  </div>
                </div>
              );
            })}
          </div>

          {/* Action composer */}
          <div className="space-y-2">
            <input
              value={actionTarget}
              onChange={(e) => setActionTarget(e.target.value)}
              placeholder="target @handle (for reply/repost/follow)"
              className="w-full px-3 py-2 rounded-md bg-phantom-panelHi border border-phantom-border text-xs font-mono"
            />
            <textarea
              value={actionBody}
              onChange={(e) => setActionBody(e.target.value)}
              placeholder="post or reply body…"
              className="w-full h-20 px-3 py-2 rounded-md bg-phantom-panelHi border border-phantom-border text-xs"
            />
            <div className="flex items-center gap-2 flex-wrap">
              {ACTION_META.map((m) => {
                const Icon = m.icon;
                return (
                  <button
                    key={m.kind}
                    onClick={() => dispatch(m.kind)}
                    disabled={acting}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold bg-phantom-panelHi border border-phantom-border hover:bg-phantom-panel disabled:opacity-50"
                  >
                    <Icon className={cn("w-3 h-3", m.color)} />
                    {m.label}
                  </button>
                );
              })}
            </div>
            {actionMsg && <div className="text-[11px] font-mono text-green-400">{actionMsg}</div>}
            {actionError && <div className="text-[11px] font-mono text-red-400">{actionError}</div>}
          </div>

          {/* Per-account funnel */}
          {accountFunnel && (
            <div>
              <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-2 flex items-center gap-2">
                <TrendingUp className="w-3 h-3" /> This account&rsquo;s funnel
              </div>
              <FunnelBar counts={accountFunnel.counts} rates={accountFunnel.rates} />
              <div className="flex items-center gap-2 mt-3 flex-wrap">
                <span className="text-[10px] text-phantom-ghost mr-2">
                  Simulate downstream events:
                </span>
                <button
                  onClick={() => fireFunnelEvent("profile_view")}
                  className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] bg-phantom-panelHi border border-phantom-border hover:bg-phantom-panel"
                >
                  <Eye className="w-3 h-3 text-sky-400" /> profile_view
                </button>
                <button
                  onClick={() => fireFunnelEvent("bio_link_click")}
                  className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] bg-phantom-panelHi border border-phantom-border hover:bg-phantom-panel"
                >
                  <MousePointerClick className="w-3 h-3 text-purple-400" /> bio_link_click
                </button>
                <button
                  onClick={() => fireFunnelEvent("subscribe")}
                  className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] bg-phantom-panelHi border border-phantom-border hover:bg-phantom-panel"
                >
                  <DollarSign className="w-3 h-3 text-green-400" /> subscribe
                </button>
              </div>
            </div>
          )}

          {/* 14-day curve preview */}
          {curve && (
            <div>
              <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-2 flex items-center gap-2">
                <Activity className="w-3 h-3" /> 14-day warming curve
              </div>
              <div className="grid grid-cols-14 gap-1" style={{gridTemplateColumns:"repeat(14,minmax(0,1fr))"}}>
                {curve.map((d) => {
                  const active = d.day === budget.day;
                  const max = Math.max(...curve.map((x) => x.total));
                  const h = max === 0 ? 0 : (d.total / max) * 100;
                  return (
                    <div key={d.day} className="flex flex-col items-center gap-1" title={`Day ${d.day}: ${d.total}`}>
                      <div className="w-full h-12 flex items-end">
                        <div
                          className={cn(
                            "w-full rounded-sm transition-all",
                            active ? "bg-phantom-accent" : "bg-phantom-accent/30",
                          )}
                          style={{ height: `${h}%` }}
                        />
                      </div>
                      <div className={cn("text-[8px] tabular-nums",
                        active ? "text-phantom-accent font-bold" : "text-phantom-ghost")}>
                        {d.day}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FunnelBar({
  counts, rates,
}: { counts: FunnelCounts; rates: FunnelRates }) {
  const stages = [
    { key: "reply_posted",   label: "Replies",  value: counts.reply_posted,   color: "bg-phantom-accent/70",   text: "text-phantom-accent" },
    { key: "profile_view",   label: "Views",    value: counts.profile_view,   color: "bg-sky-500/70",           text: "text-sky-300",        rate: rates.reply_to_view },
    { key: "bio_link_click", label: "Clicks",   value: counts.bio_link_click, color: "bg-purple-500/70",        text: "text-purple-300",     rate: rates.view_to_click },
    { key: "subscribe",      label: "Subs",     value: counts.subscribe,      color: "bg-green-500/70",         text: "text-green-300",      rate: rates.click_to_sub },
  ] as const;
  const max = Math.max(1, ...stages.map((s) => s.value));
  return (
    <div className="space-y-1.5">
      {stages.map((s, i) => (
        <div key={s.key} className="flex items-center gap-3">
          <div className="w-16 text-[10px] text-phantom-ghost uppercase tracking-wider">
            {s.label}
          </div>
          <div className="flex-1 h-4 rounded bg-phantom-panelHi overflow-hidden">
            <div className={cn("h-full rounded", s.color)}
                 style={{ width: `${Math.max(2, (s.value / max) * 100)}%` }} />
          </div>
          <div className={cn("w-12 text-right text-xs font-mono tabular-nums font-semibold", s.text)}>
            {s.value}
          </div>
          <div className="w-14 text-right text-[10px] font-mono text-phantom-ghost">
            {i === 0 ? "—" : `${(((s as {rate?: number}).rate ?? 0) * 100).toFixed(1)}%`}
          </div>
        </div>
      ))}
      <div className="flex items-center justify-end mt-2 text-[10px] text-phantom-ghost">
        End-to-end reply → sub:
        <span className="ml-1.5 font-mono font-semibold text-green-400">
          {(rates.reply_to_sub * 100).toFixed(2)}%
        </span>
      </div>
    </div>
  );
}

function Tile({
  label, value, tone = "accent",
}: { label: string; value: string; tone?: "accent" | "amber" }) {
  return (
    <div className="phantom-panel p-4">
      <div className={cn(
        "text-2xl font-display font-bold tabular-nums",
        tone === "amber" ? "text-phantom-amber" : "text-phantom-accent",
      )}>{value}</div>
      <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em] mt-0.5">
        {label}
      </div>
    </div>
  );
}
