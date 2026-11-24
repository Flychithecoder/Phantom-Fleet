"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft, MessageCircle, Instagram, Heart, Ghost, Eye, AlertTriangle,
  Snowflake, Flame, GraduationCap, XOctagon, RotateCw, Loader2, Activity,
  CheckCircle2, Repeat2, UserPlus, Send, Radio, TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";

type Account = {
  account_id: string; handle: string; platform: string; status: string;
  ig_account_id: string; ig_handle: string; ig_warmup_day: number;
  linked_at: string; warmup_day: number; can_cross_post: boolean;
};
type Budget = { day: number; follow: number; reply: number; repost: number; post: number; total: number };
type Funnel = {
  threads_account_id: string;
  counts: { reply_posted: number; post_posted: number; profile_view: number; bio_link_click: number; subscribe: number };
  rates: { reply_to_view: number; view_to_click: number; click_to_sub: number; reply_to_sub: number };
};
type HealthSignals = {
  reply_posted: number; profile_view: number; bio_link_click: number; subscribe: number;
  reply_to_view_rate: number; dispatched: number; failed: number;
  dispatch_failure_rate: number; queued_pending: number; stalled_count: number;
  warmup_day: number; hours_since_dispatch: number;
};
type Health = {
  account_id: string; status: "healthy" | "watch" | "at_risk" | "shadowbanned";
  score: number; flags: string[]; signals: HealthSignals; computed_at: string;
};
type Recovery = {
  account_id: string; phase: "cooling_down" | "rewarming" | "graduated" | "retired";
  strikes: number; entered_at: string; cool_down_until: string;
  original_warmup_day: number; rewarm_baseline_replies: number;
  rewarm_actions_observed: number; graduated_at: string | null;
  retired_at: string | null; notes: string[];
};
type QueueEntry = {
  action_id?: string; account_id: string; kind: string; target?: string;
  body?: string; status: string; queued_at?: string; dispatched_at?: string;
  reason?: string; planner?: string;
};
type BridgeEvent = { ig_account_id: string; post_id: string; caption: string; source: string; ts: string };
type Dossier = {
  account: Account; budget: Budget; curve: Budget[]; funnel: Funnel;
  health: Health | null; recovery: Recovery | null;
  queue: QueueEntry[]; bridge_events: BridgeEvent[];
};

const KIND_ICONS: Record<string, typeof Send> = {
  post: Send, reply: MessageCircle, repost: Repeat2, follow: UserPlus,
};

export default function ThreadsDrillPage() {
  const params = useParams<{ account_id: string }>();
  const router = useRouter();
  const id = params.account_id;
  const [d, setD] = useState<Dossier | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`/api/platforms/threads/accounts/${id}/dossier`);
      if (!r.ok) {
        setErr(`HTTP ${r.status}: ${await r.text()}`);
        return;
      }
      setD(await r.json() as Dossier);
      setErr(null);
    } catch (e) {
      setErr(String(e));
    }
  }, [id]);

  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t); }, [load]);

  if (err) {
    return (
      <div className="p-6 space-y-3">
        <button onClick={() => router.push("/threads")}
          className="text-xs text-phantom-ghost flex items-center gap-1 hover:text-phantom-accent">
          <ArrowLeft className="w-3 h-3" /> Back to Threads
        </button>
        <div className="phantom-panel p-5 text-sm text-red-400">{err}</div>
      </div>
    );
  }

  if (!d) {
    return (
      <div className="p-6 flex items-center gap-2 text-sm text-phantom-ghost">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading dossier…
      </div>
    );
  }

  const { account, budget, curve, funnel, health, recovery, queue, bridge_events } = d;
  const maxCurveTotal = Math.max(...curve.map((c) => c.total), 1);

  const refresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <button onClick={() => router.push("/threads")}
            className="text-[11px] text-phantom-ghost flex items-center gap-1 hover:text-phantom-accent mb-2">
            <ArrowLeft className="w-3 h-3" /> Back to Threads
          </button>
          <div className="flex items-center gap-2">
            <MessageCircle className="w-5 h-5 text-phantom-accent" />
            <h1 className="text-xl font-bold">
              {account.handle || account.account_id.slice(0, 14)}
            </h1>
            <span className={cn("text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded",
              account.status === "active"   ? "text-green-400 bg-green-500/10" :
              account.status === "paused"   ? "text-blue-400 bg-blue-500/10" :
              account.status === "retired"  ? "text-red-400 bg-red-500/10" :
                                              "text-phantom-ghost bg-phantom-panelHi")}>
              {account.status}
            </span>
          </div>
          <div className="text-[11px] text-phantom-ghost font-mono mt-1 flex items-center gap-3">
            <span>{account.account_id}</span>
            {account.ig_handle && (
              <span className="flex items-center gap-1">
                <Instagram className="w-3 h-3" /> {account.ig_handle} · IG day {account.ig_warmup_day}
                {account.can_cross_post && <span className="text-green-400">· cross-post OK</span>}
              </span>
            )}
          </div>
        </div>
        <button onClick={refresh} disabled={refreshing}
          className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold bg-phantom-panelHi border border-phantom-border hover:border-phantom-accent/50">
          {refreshing ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCw className="w-3 h-3" />}
          Refresh
        </button>
      </div>

      {/* Top row: Health + Recovery */}
      <div className="grid grid-cols-2 gap-4">
        {/* Health */}
        <div className="phantom-panel p-5">
          <div className="flex items-center gap-2 mb-3">
            <Heart className="w-4 h-4 text-phantom-accent" />
            <h2 className="text-sm font-semibold">Health</h2>
            {health && (
              <span className={cn("ml-auto text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded",
                health.status === "healthy"      ? "text-green-400 bg-green-500/10" :
                health.status === "watch"        ? "text-phantom-amber bg-phantom-amber/10" :
                health.status === "at_risk"      ? "text-orange-400 bg-orange-500/10" :
                                                   "text-red-400 bg-red-500/10")}>
                {health.status} · score {health.score}
              </span>
            )}
          </div>
          {health ? (
            <>
              {health.flags.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {health.flags.map((f) => (
                    <span key={f} className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/30">
                      {f}
                    </span>
                  ))}
                </div>
              )}
              <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[11px] font-mono">
                <div className="text-phantom-ghost">reply_posted</div>
                <div className="text-right">{health.signals.reply_posted}</div>
                <div className="text-phantom-ghost">profile_view</div>
                <div className="text-right">{health.signals.profile_view}</div>
                <div className="text-phantom-ghost">bio_link_click</div>
                <div className="text-right">{health.signals.bio_link_click}</div>
                <div className="text-phantom-ghost">subscribe</div>
                <div className="text-right">{health.signals.subscribe}</div>
                <div className="text-phantom-ghost">reply→view rate</div>
                <div className="text-right">{(health.signals.reply_to_view_rate * 100).toFixed(1)}%</div>
                <div className="text-phantom-ghost">dispatched · failed</div>
                <div className="text-right">{health.signals.dispatched} · {health.signals.failed}</div>
                <div className="text-phantom-ghost">queue · stalled</div>
                <div className="text-right">{health.signals.queued_pending} · {health.signals.stalled_count}</div>
                <div className="text-phantom-ghost">hours since dispatch</div>
                <div className="text-right">{health.signals.hours_since_dispatch.toFixed(1)}</div>
              </div>
            </>
          ) : (
            <div className="text-[11px] text-phantom-ghost">No health scan yet.</div>
          )}
        </div>

        {/* Recovery */}
        <div className="phantom-panel p-5">
          <div className="flex items-center gap-2 mb-3">
            <RotateCw className="w-4 h-4 text-phantom-accent" />
            <h2 className="text-sm font-semibold">Recovery</h2>
            {recovery && (
              <span className={cn("ml-auto text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded flex items-center gap-1",
                recovery.phase === "cooling_down" ? "text-blue-400 bg-blue-500/10" :
                recovery.phase === "rewarming"    ? "text-orange-400 bg-orange-500/10" :
                recovery.phase === "graduated"    ? "text-green-400 bg-green-500/10" :
                                                    "text-red-400 bg-red-500/10")}>
                {recovery.phase === "cooling_down" && <Snowflake className="w-3 h-3" />}
                {recovery.phase === "rewarming" && <Flame className="w-3 h-3" />}
                {recovery.phase === "graduated" && <GraduationCap className="w-3 h-3" />}
                {recovery.phase === "retired" && <XOctagon className="w-3 h-3" />}
                {recovery.phase}
              </span>
            )}
          </div>
          {recovery ? (
            <>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[11px] font-mono mb-3">
                <div className="text-phantom-ghost">strikes</div>
                <div className="text-right">{recovery.strikes}/3</div>
                <div className="text-phantom-ghost">entered</div>
                <div className="text-right">{new Date(recovery.entered_at).toLocaleString()}</div>
                {recovery.phase === "cooling_down" && (
                  <>
                    <div className="text-phantom-ghost">cool-down until</div>
                    <div className="text-right">{new Date(recovery.cool_down_until).toLocaleString()}</div>
                  </>
                )}
                {recovery.phase === "rewarming" && (
                  <>
                    <div className="text-phantom-ghost">replies observed</div>
                    <div className="text-right">{recovery.rewarm_actions_observed}/10</div>
                  </>
                )}
                {recovery.graduated_at && (<><div className="text-phantom-ghost">graduated</div><div className="text-right">{new Date(recovery.graduated_at).toLocaleString()}</div></>)}
                {recovery.retired_at && (<><div className="text-phantom-ghost">retired</div><div className="text-right">{new Date(recovery.retired_at).toLocaleString()}</div></>)}
                <div className="text-phantom-ghost">original day</div>
                <div className="text-right">{recovery.original_warmup_day}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-phantom-ghost mb-1">Timeline</div>
                <ol className="space-y-1">
                  {recovery.notes.map((n, i) => (
                    <li key={i} className="text-[11px] font-mono text-phantom-ghost flex gap-2">
                      <span className="text-phantom-accent">·</span> {n}
                    </li>
                  ))}
                </ol>
              </div>
            </>
          ) : (
            <div className="text-[11px] text-phantom-ghost flex items-center gap-2">
              <CheckCircle2 className="w-3 h-3 text-green-400" />
              Account is not in the recovery agent.
            </div>
          )}
        </div>
      </div>

      {/* Warming curve */}
      <div className="phantom-panel p-5">
        <div className="flex items-center gap-2 mb-3">
          <TrendingUp className="w-4 h-4 text-phantom-accent" />
          <h2 className="text-sm font-semibold">14-day warming curve</h2>
          <span className="text-[10px] text-phantom-ghost">
            LogNormal-sampled daily budgets. Current day shaded.
          </span>
          <span className="ml-auto text-[10px] font-mono text-phantom-ghost">
            today total: {budget.total} · day {account.warmup_day}
          </span>
        </div>
        <div className="flex gap-1 items-end h-28">
          {curve.map((c) => (
            <div key={c.day} className="flex-1 flex flex-col items-center gap-1">
              <div className="flex-1 w-full flex items-end gap-0.5">
                <div className="flex-1 bg-phantom-accent/70 rounded-sm"
                     style={{ height: `${(c.follow / maxCurveTotal) * 100}%` }} />
                <div className="flex-1 bg-blue-400/70 rounded-sm"
                     style={{ height: `${(c.reply / maxCurveTotal) * 100}%` }} />
                <div className="flex-1 bg-purple-400/70 rounded-sm"
                     style={{ height: `${(c.repost / maxCurveTotal) * 100}%` }} />
                <div className="flex-1 bg-orange-400/70 rounded-sm"
                     style={{ height: `${(c.post / maxCurveTotal) * 100}%` }} />
              </div>
              <div className={cn("text-[9px] font-mono",
                c.day === account.warmup_day ? "text-phantom-accent font-bold" : "text-phantom-ghost")}>
                {c.day}
              </div>
            </div>
          ))}
        </div>
        <div className="flex gap-3 mt-2 text-[10px] font-mono text-phantom-ghost">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-phantom-accent/70" /> follow</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-blue-400/70" /> reply</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-purple-400/70" /> repost</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-orange-400/70" /> post</span>
        </div>
      </div>

      {/* Funnel */}
      <div className="phantom-panel p-5">
        <div className="flex items-center gap-2 mb-3">
          <TrendingUp className="w-4 h-4 text-phantom-accent" />
          <h2 className="text-sm font-semibold">Funnel · reply → view → click → sub</h2>
          <span className="ml-auto text-[10px] font-mono text-phantom-ghost">
            end-to-end: {(funnel.rates.reply_to_sub * 100).toFixed(2)}%
          </span>
        </div>
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: "Replies", n: funnel.counts.reply_posted, rate: 100, colorBg: "bg-phantom-accent/20", colorText: "text-phantom-accent" },
            { label: "Views", n: funnel.counts.profile_view, rate: funnel.rates.reply_to_view * 100, colorBg: "bg-blue-400/20", colorText: "text-blue-400" },
            { label: "Clicks", n: funnel.counts.bio_link_click, rate: funnel.rates.view_to_click * 100, colorBg: "bg-purple-400/20", colorText: "text-purple-400" },
            { label: "Subs", n: funnel.counts.subscribe, rate: funnel.rates.click_to_sub * 100, colorBg: "bg-green-500/20", colorText: "text-green-400" },
          ].map((s) => (
            <div key={s.label} className={cn("p-3 rounded-md border border-phantom-border", s.colorBg)}>
              <div className="text-[10px] uppercase tracking-wider text-phantom-ghost">{s.label}</div>
              <div className={cn("text-2xl font-mono", s.colorText)}>{s.n}</div>
              <div className="text-[10px] font-mono text-phantom-ghost">{s.rate.toFixed(1)}%</div>
            </div>
          ))}
        </div>
      </div>

      {/* Queue */}
      <div className="phantom-panel p-5">
        <div className="flex items-center gap-2 mb-3">
          <Activity className="w-4 h-4 text-phantom-accent" />
          <h2 className="text-sm font-semibold">Action queue</h2>
          <span className="ml-auto text-[10px] font-mono text-phantom-ghost">
            {queue.length} entries · {queue.filter((q) => q.status === "queued").length} queued ·
            {" "}{queue.filter((q) => q.status === "dispatched").length} dispatched ·
            {" "}{queue.filter((q) => q.status === "failed").length} failed
          </span>
        </div>
        {queue.length > 0 ? (
          <div className="rounded-md border border-phantom-border overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-phantom-panelHi text-[10px] uppercase text-phantom-ghost">
                <tr>
                  <th className="text-left px-3 py-2">Kind</th>
                  <th className="text-left px-3 py-2">Target</th>
                  <th className="text-left px-3 py-2">Body</th>
                  <th className="text-left px-3 py-2">Status</th>
                  <th className="text-left px-3 py-2">Planner</th>
                  <th className="text-right px-3 py-2">Queued</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-phantom-border/30">
                {queue.slice(0, 20).map((q, i) => {
                  const Icon = KIND_ICONS[q.kind] ?? Send;
                  return (
                    <tr key={q.action_id ?? i}>
                      <td className="px-3 py-2"><Icon className="w-3 h-3 text-phantom-accent" /></td>
                      <td className="px-3 py-2 font-mono text-[11px]">{q.target || "—"}</td>
                      <td className="px-3 py-2 text-[11px] text-phantom-ghost truncate max-w-[220px]">{q.body || "—"}</td>
                      <td className="px-3 py-2">
                        <span className={cn("text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded",
                          q.status === "dispatched" ? "text-green-400 bg-green-500/10" :
                          q.status === "failed"     ? "text-red-400 bg-red-500/10" :
                                                      "text-phantom-amber bg-phantom-amber/10")}>
                          {q.status}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-[10px] text-phantom-ghost">{q.planner || "—"}</td>
                      <td className="px-3 py-2 text-right text-[10px] font-mono text-phantom-ghost">
                        {q.queued_at ? new Date(q.queued_at).toLocaleTimeString() : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-[11px] text-phantom-ghost">No queue entries for this account.</div>
        )}
      </div>

      {/* Bridge events */}
      <div className="phantom-panel p-5">
        <div className="flex items-center gap-2 mb-3">
          <Radio className="w-4 h-4 text-phantom-accent" />
          <h2 className="text-sm font-semibold">IG bridge events</h2>
          <span className="ml-auto text-[10px] text-phantom-ghost">
            IG posts from this account's parent. Each triggers a cross-post from day 7.
          </span>
        </div>
        {bridge_events.length > 0 ? (
          <ol className="divide-y divide-phantom-border/30">
            {bridge_events.slice(0, 15).map((e) => (
              <li key={e.post_id} className="py-2 flex gap-3 items-center text-[11px]">
                <span className="font-mono text-phantom-ghost">{new Date(e.ts).toLocaleTimeString()}</span>
                <span className="font-mono text-phantom-accent">{e.post_id.slice(0, 14)}</span>
                <span className="text-phantom-ghost truncate flex-1">{e.caption || "—"}</span>
                <span className="text-[10px] font-mono uppercase text-phantom-ghost">{e.source}</span>
              </li>
            ))}
          </ol>
        ) : (
          <div className="text-[11px] text-phantom-ghost">No IG events for this parent yet.</div>
        )}
      </div>
    </div>
  );
}
