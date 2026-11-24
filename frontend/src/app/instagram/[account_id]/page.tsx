"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Instagram, ArrowLeft, Heart, HeartCrack, Ghost, Activity, Clock,
  Link2, Snowflake, Flame, GraduationCap, XOctagon, RefreshCw,
  MessageCircle, AlertTriangle, UserPlus, ThumbsUp, Eye, Send,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";

type Phase = "cooling_down" | "rewarming" | "graduated" | "retired";

type Dossier = {
  account: {
    account_id: string; username: string; platform: string;
    status: string; warmup_day: number;
  };
  linked_threads: {
    account_id: string; handle: string; warmup_day: number; status: string;
  } | null;
  health: {
    status: "healthy" | "watch" | "at_risk" | "shadowbanned";
    score: number; flags: string[];
    signals: {
      warmup_day: number; posts_in_ring: number; posts_last_48h: number;
      hours_since_last_post: number; has_threads_link: boolean;
      bridge_skipped_recent: number; bridge_queued_recent: number;
    };
    computed_at: string;
  } | null;
  recovery: {
    account_id: string; phase: Phase; strikes: number;
    entered_at: string; cool_down_until: string;
    original_warmup_day: number; rewarm_actions_observed: number;
    graduated_at: string | null; retired_at: string | null;
    notes: string[];
  } | null;
  bus_events: Array<{
    ig_account_id: string; post_id: string; caption: string;
    source: string; ts: string;
  }>;
  bridge_stats: {
    events_in: number; replies_out: number;
    skipped_budget: number; skipped_no_link: number; skipped_gate: number;
    last_action_id: string | null;
  } | null;
  budget: { day: number; follow: number; like: number; story_view: number; post: number; total: number };
  curve:  Array<{ day: number; follow: number; like: number; story_view: number; post: number; total: number }>;
};

const HEALTH_STYLES = {
  healthy:      { text: "text-green-400",       bg: "border-green-500/30",       icon: Heart },
  watch:        { text: "text-phantom-amber",   bg: "border-phantom-amber/40",   icon: Activity },
  at_risk:      { text: "text-orange-400",      bg: "border-orange-500/40",      icon: AlertTriangle },
  shadowbanned: { text: "text-red-400",         bg: "border-red-500/50",         icon: Ghost },
} as const;

const PHASE_STYLES = {
  cooling_down: { text: "text-sky-400",    bg: "border-sky-500/30",    icon: Snowflake },
  rewarming:    { text: "text-orange-400", bg: "border-orange-500/30", icon: Flame },
  graduated:    { text: "text-green-400",  bg: "border-green-500/30",  icon: GraduationCap },
  retired:      { text: "text-red-400",    bg: "border-red-500/40",    icon: XOctagon },
} as const;

export default function InstagramAccountDrill({ params }: { params: Promise<{ account_id: string }> }) {
  const { account_id } = use(params);
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`/api/platforms/instagram/accounts/${account_id}/dossier`);
      if (!r.ok) {
        setError(`${r.status} ${await r.text()}`);
        return;
      }
      setDossier((await r.json()) as Dossier);
      setError(null);
    } catch (e: any) {
      setError(String(e));
    }
  }, [account_id]);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  if (error) {
    return (
      <div className="p-6 max-w-[1400px] mx-auto">
        <div className="phantom-panel p-4 border-red-500/40 text-red-400 font-mono text-sm">
          {error}
          <div className="mt-2">
            <Link href="/instagram" className="text-pink-400 hover:underline">
              ← back to Instagram
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (!dossier) {
    return (
      <div className="p-6 text-phantom-ghost font-mono text-sm">
        loading dossier for {account_id}…
      </div>
    );
  }

  const h = dossier.health;
  const r = dossier.recovery;
  const healthStyle = h ? HEALTH_STYLES[h.status] : null;
  const phaseStyle = r ? PHASE_STYLES[r.phase] : null;
  const HealthIcon = healthStyle?.icon;
  const PhaseIcon = phaseStyle?.icon;

  return (
    <div className="p-6 space-y-5 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/instagram" className="text-phantom-ghost hover:text-phantom-mist">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <Instagram className="w-6 h-6 text-pink-400" />
        <div className="flex-1">
          <h1 className="text-xl font-bold text-phantom-mist">
            {dossier.account.username || dossier.account.account_id}
          </h1>
          <p className="text-[11px] text-phantom-ghost font-mono">
            {dossier.account.account_id} · day {dossier.account.warmup_day} · {dossier.account.status}
          </p>
        </div>
        <button onClick={load} className="phantom-btn flex items-center gap-2 text-xs">
          <RefreshCw className="w-3 h-3" /> refresh
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Health card */}
        <div className={cn("phantom-panel p-4", healthStyle?.bg)}>
          <div className="flex items-center gap-2 mb-3">
            {HealthIcon && <HealthIcon className={cn("w-4 h-4", healthStyle!.text)} />}
            <span className={cn("text-[11px] uppercase tracking-wider font-mono font-bold", healthStyle?.text)}>
              Health · {h?.status ?? "unknown"}
            </span>
            {h && <span className={cn("ml-auto text-2xl font-bold font-mono", healthStyle?.text)}>{h.score}</span>}
          </div>
          {h ? (
            <>
              <div className="grid grid-cols-2 gap-2 text-[11px] font-mono text-phantom-ghost">
                <div>warmup day <span className="text-phantom-mist">{h.signals.warmup_day}</span></div>
                <div>posts in ring <span className="text-phantom-mist">{h.signals.posts_in_ring}</span></div>
                <div>last 48h <span className="text-phantom-mist">{h.signals.posts_last_48h}</span></div>
                <div>idle <span className="text-phantom-mist">{h.signals.hours_since_last_post}h</span></div>
                <div>Threads link <span className={h.signals.has_threads_link ? "text-green-400" : "text-red-400"}>{h.signals.has_threads_link ? "yes" : "no"}</span></div>
                <div>bridge skipped <span className="text-phantom-mist">{h.signals.bridge_skipped_recent}</span></div>
              </div>
              <div className="mt-2 flex gap-1 flex-wrap">
                {h.flags.length === 0 ? (
                  <span className="text-[10px] text-phantom-ghost font-mono">no flags</span>
                ) : h.flags.map((f) => (
                  <span key={f} className="px-2 py-0.5 bg-phantom-charcoal/80 border border-phantom-amber/40 text-phantom-amber text-[10px] font-mono rounded">
                    {f}
                  </span>
                ))}
              </div>
            </>
          ) : (
            <div className="text-[11px] text-phantom-ghost">no health record yet — run a scan</div>
          )}
        </div>

        {/* Recovery card */}
        <div className={cn("phantom-panel p-4", phaseStyle?.bg ?? "border-phantom-charcoal")}>
          <div className="flex items-center gap-2 mb-3">
            {PhaseIcon ? <PhaseIcon className={cn("w-4 h-4", phaseStyle!.text)} /> : <GraduationCap className="w-4 h-4 text-phantom-ghost" />}
            <span className={cn("text-[11px] uppercase tracking-wider font-mono font-bold", phaseStyle?.text ?? "text-phantom-ghost")}>
              Recovery · {r?.phase.replace("_", " ") ?? "not enrolled"}
            </span>
          </div>
          {r ? (
            <>
              <div className="grid grid-cols-2 gap-2 text-[11px] font-mono text-phantom-ghost">
                <div>strikes <span className="text-phantom-mist">{r.strikes}</span></div>
                <div>from day <span className="text-phantom-mist">{r.original_warmup_day}</span></div>
                <div>entered <span className="text-phantom-mist">{new Date(r.entered_at).toLocaleString()}</span></div>
                <div>cool-down to <span className="text-phantom-mist">{new Date(r.cool_down_until).toLocaleString()}</span></div>
                {r.phase === "rewarming" && (
                  <div className="col-span-2">rewarm posts observed <span className="text-orange-400 font-bold">{r.rewarm_actions_observed}</span></div>
                )}
                {r.graduated_at && <div className="col-span-2 text-green-400">graduated {new Date(r.graduated_at).toLocaleString()}</div>}
                {r.retired_at && <div className="col-span-2 text-red-400">retired {new Date(r.retired_at).toLocaleString()}</div>}
              </div>
              <div className="mt-3 text-[10px] text-phantom-ghost font-mono space-y-0.5">
                {r.notes.slice(-4).map((n, i) => (
                  <div key={i}>· {n}</div>
                ))}
              </div>
            </>
          ) : (
            <div className="text-[11px] text-phantom-ghost">not in recovery — healthy account path</div>
          )}
        </div>
      </div>

      {/* Today's budget */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3">
          <TrendingUp className="w-4 h-4 text-pink-400" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            Today's budget — day {dossier.budget.day} of 28 (LogNormal, SHA256-seeded)
          </span>
          <span className="ml-auto text-[10px] text-phantom-ghost font-mono">total {dossier.budget.total}</span>
        </div>
        <div className="grid grid-cols-4 gap-3">
          {([
            { k: "follow",     icon: UserPlus, color: "text-sky-400",     bg: "border-sky-500/30" },
            { k: "like",       icon: ThumbsUp, color: "text-pink-400",    bg: "border-pink-500/30" },
            { k: "story_view", icon: Eye,      color: "text-purple-400",  bg: "border-purple-500/30" },
            { k: "post",       icon: Send,     color: "text-green-400",   bg: "border-green-500/30" },
          ] as const).map(({ k, icon: Icon, color, bg }) => (
            <div key={k} className={cn("phantom-panel p-3", bg)}>
              <div className={cn("flex items-center gap-1 text-[10px] uppercase tracking-wider font-mono", color)}>
                <Icon className="w-3 h-3" />{k.replace("_", " ")}
              </div>
              <div className={cn("text-3xl font-bold mt-1", color)}>{dossier.budget[k]}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 28-day warming curve */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3">
          <Activity className="w-4 h-4 text-phantom-mist" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            28-day warming curve (this account)
          </span>
        </div>
        <div className="flex items-end gap-1 h-36">
          {dossier.curve.map((d) => {
            const maxTotal = Math.max(1, ...dossier.curve.map((x) => x.total));
            const h = Math.max(3, (d.total / maxTotal) * 110);
            const isToday = d.day === dossier.account.warmup_day;
            return (
              <div key={d.day} className="flex-1 flex flex-col items-center gap-1 h-full justify-end" title={`day ${d.day}: follow ${d.follow} · like ${d.like} · story ${d.story_view} · post ${d.post}`}>
                <div className={cn("w-full rounded-sm",
                  isToday ? "bg-pink-400" : d.day <= dossier.account.warmup_day ? "bg-emerald-500/70" : "bg-slate-600/60")}
                  style={{ height: `${h}px` }}
                />
                <div className={cn("text-[9px] font-mono leading-none", isToday ? "text-pink-400 font-bold" : "text-phantom-ghost")}>{d.day}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Linked Threads */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3">
          <Link2 className="w-4 h-4 text-phantom-mist" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            Linked Threads account
          </span>
        </div>
        {dossier.linked_threads ? (
          <div className="flex items-center gap-3 text-[11px] font-mono">
            <MessageCircle className="w-4 h-4 text-phantom-emerald" />
            <Link href={`/threads/${dossier.linked_threads.account_id}`} className="text-phantom-emerald hover:underline">
              {dossier.linked_threads.handle || dossier.linked_threads.account_id}
            </Link>
            <span className="text-phantom-ghost">day {dossier.linked_threads.warmup_day}</span>
            <span className="text-phantom-ghost">· {dossier.linked_threads.status}</span>
          </div>
        ) : (
          <div className="text-[11px] text-red-400 font-mono">No Threads account linked. Day-7+ without link flags no_threads_link.</div>
        )}
      </div>

      {/* Bridge stats */}
      {dossier.bridge_stats && (
        <div className="phantom-panel p-4">
          <div className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono mb-3">
            IG → Threads bridge (fleet-wide)
          </div>
          <div className="grid grid-cols-5 gap-3 text-[11px] font-mono">
            <div className="phantom-panel p-2 border-phantom-charcoal">
              <div className="text-[10px] uppercase text-phantom-ghost">events in</div>
              <div className="text-xl font-bold text-phantom-mist">{dossier.bridge_stats.events_in}</div>
            </div>
            <div className="phantom-panel p-2 border-green-500/20">
              <div className="text-[10px] uppercase text-green-400">replies out</div>
              <div className="text-xl font-bold text-green-400">{dossier.bridge_stats.replies_out}</div>
            </div>
            <div className="phantom-panel p-2 border-phantom-amber/20">
              <div className="text-[10px] uppercase text-phantom-amber">no budget</div>
              <div className="text-xl font-bold text-phantom-amber">{dossier.bridge_stats.skipped_budget}</div>
            </div>
            <div className="phantom-panel p-2 border-red-500/20">
              <div className="text-[10px] uppercase text-red-400">no link</div>
              <div className="text-xl font-bold text-red-400">{dossier.bridge_stats.skipped_no_link}</div>
            </div>
            <div className="phantom-panel p-2 border-sky-500/20">
              <div className="text-[10px] uppercase text-sky-400">day-7 gate</div>
              <div className="text-xl font-bold text-sky-400">{dossier.bridge_stats.skipped_gate}</div>
            </div>
          </div>
        </div>
      )}

      {/* IG bus events for this account */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-2 mb-3">
          <Clock className="w-4 h-4 text-phantom-mist" />
          <span className="text-[11px] uppercase tracking-wider text-phantom-mist font-mono">
            IG post bus — this account ({dossier.bus_events.length})
          </span>
        </div>
        {dossier.bus_events.length === 0 ? (
          <div className="text-[11px] text-phantom-ghost font-mono">No bus events yet. Fire an IG post from the main /threads page to see it land here.</div>
        ) : (
          <div className="space-y-1">
            {dossier.bus_events.slice(0, 50).map((e) => (
              <div key={e.post_id} className="flex items-center gap-3 text-[11px] font-mono py-1 border-b border-phantom-charcoal/40">
                <span className="text-phantom-ghost w-32 truncate">{new Date(e.ts).toLocaleString()}</span>
                <span className="text-pink-400 w-28 truncate">{e.source}</span>
                <span className="text-phantom-mist w-40 truncate">{e.post_id}</span>
                <span className="text-phantom-ghost flex-1 truncate">{e.caption}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
