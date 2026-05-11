"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { FunnelViz } from "@/components/funnel-viz";
import { RevenueChart } from "@/components/revenue-chart";
import { DollarSign, ChevronDown, ChevronRight, ArrowRight, TrendingUp, MessageCircle, Clock, Link as LinkIcon, CheckCircle2, XCircle } from "lucide-react";
import { cn, fmtUSD } from "@/lib/utils";

// ─── Types ───────────────────────────────────────────────────────────────────

type FunnelStage = {
  label: string;
  count: number;
  color?: string;
};

type PersonaFunnel = {
  persona: string;
  platform: string;
  stages: FunnelStage[];
  revenue: number;
  conversions: number;
};

// ─── Data ────────────────────────────────────────────────────────────────────

const MAIN_FUNNEL: FunnelStage[] = [
  { label: "Scraped targets", count: 28_400, color: "bg-phantom-ghost" },
  { label: "Follow actions sent", count: 4_512 },
  { label: "Profile visits received", count: 2_840, color: "bg-phantom-magenta" },
  { label: "Follow-backs", count: 1_118 },
  { label: "DM sent", count: 384 },
  { label: "Link clicked", count: 127, color: "bg-phantom-amber" },
  { label: "Converted (sub / purchase)", count: 43, color: "bg-phantom-accent" },
];

const PERSONA_FUNNELS: PersonaFunnel[] = [
  {
    persona: "Tatiana",
    platform: "Instagram / Threads",
    stages: [
      { label: "Follow actions", count: 2_640 },
      { label: "Profile visits", count: 1_640 },
      { label: "Follow-backs", count: 680 },
      { label: "DMs sent", count: 224 },
      { label: "Link clicks", count: 76 },
      { label: "Converted", count: 27, color: "bg-phantom-accent" },
    ],
    revenue: 4_860,
    conversions: 27,
  },
  {
    persona: "Melodie",
    platform: "Instagram / Reddit",
    stages: [
      { label: "Follow actions", count: 1_872 },
      { label: "Profile visits", count: 1_200 },
      { label: "Follow-backs", count: 438 },
      { label: "DMs sent", count: 160 },
      { label: "Link clicks", count: 51 },
      { label: "Converted", count: 16, color: "bg-phantom-magenta" },
    ],
    revenue: 2_720,
    conversions: 16,
  },
];

// ─── DM Funnel Tracker data ──────────────────────────────────────────────────

type DmStage = "cold" | "warm" | "cta_sent" | "converted" | "dead";

type DmConversation = {
  id: string;
  account: string;
  persona: string;
  target: string;
  stage: DmStage;
  messages: number;
  lastMsg: string;
  replyRate: number;
  ctaSent: boolean;
  ctaClicked: boolean;
  hoursToConvert: number | null;
  startedHoursAgo: number;
};

const DM_CONVERSATIONS: DmConversation[] = [
  { id:"d1",  account:"@tatiannalifee",       persona:"Tatiana", target:"@jordanfit92",     stage:"converted",  messages:9,  lastMsg:"omg finally checked it out 🔥",     replyRate:88, ctaSent:true,  ctaClicked:true,  hoursToConvert:14, startedHoursAgo:18 },
  { id:"d2",  account:"@melodieeeprincesss",  persona:"Melodie", target:"@brookefit",       stage:"cta_sent",   messages:6,  lastMsg:"sounds interesting tbh",             replyRate:75, ctaSent:true,  ctaClicked:false, hoursToConvert:null, startedHoursAgo:9  },
  { id:"d3",  account:"@tatianamusee",        persona:"Tatiana", target:"@yogatanya_la",    stage:"warm",       messages:4,  lastMsg:"haha yes girl same energy",          replyRate:66, ctaSent:false, ctaClicked:false, hoursToConvert:null, startedHoursAgo:6  },
  { id:"d4",  account:"@hackerhoneytatii",    persona:"Tatiana", target:"@fitlife_brooke",  stage:"converted",  messages:11, lastMsg:"just subscribed bestie!!",           replyRate:91, ctaSent:true,  ctaClicked:true,  hoursToConvert:22, startedHoursAgo:27 },
  { id:"d5",  account:"@u_melodieee",         persona:"Melodie", target:"@laurenfit_",      stage:"cold",       messages:1,  lastMsg:"hey 👀",                             replyRate:0,  ctaSent:false, ctaClicked:false, hoursToConvert:null, startedHoursAgo:2  },
  { id:"d6",  account:"@tatiana_xo44",        persona:"Tatiana", target:"@nycfitgirl",      stage:"warm",       messages:5,  lastMsg:"wait are you actually from ny?",     replyRate:80, ctaSent:false, ctaClicked:false, hoursToConvert:null, startedHoursAgo:11 },
  { id:"d7",  account:"@melodie_life",        persona:"Melodie", target:"@allisonlifts",    stage:"cta_sent",   messages:7,  lastMsg:"i'll check it out later",            replyRate:71, ctaSent:true,  ctaClicked:false, hoursToConvert:null, startedHoursAgo:15 },
  { id:"d8",  account:"@kira_glow22",         persona:"Tatiana", target:"@carolinegirlboss",stage:"dead",       messages:3,  lastMsg:"[no reply in 48h]",                  replyRate:33, ctaSent:false, ctaClicked:false, hoursToConvert:null, startedHoursAgo:52 },
  { id:"d9",  account:"@tatiannalifee",       persona:"Tatiana", target:"@sunsetswithsara", stage:"converted",  messages:8,  lastMsg:"ok subbed!! where else are you?",   replyRate:87, ctaSent:true,  ctaClicked:true,  hoursToConvert:19, startedHoursAgo:24 },
  { id:"d10", account:"@melodieeeprincesss",  persona:"Melodie", target:"@miafitnessco",    stage:"warm",       messages:3,  lastMsg:"you seem super cool actually",       replyRate:66, ctaSent:false, ctaClicked:false, hoursToConvert:null, startedHoursAgo:7  },
  { id:"d11", account:"@noelle_rune",         persona:"Tatiana", target:"@heather_gains",   stage:"cta_sent",   messages:5,  lastMsg:"link? 👀",                           replyRate:80, ctaSent:true,  ctaClicked:false, hoursToConvert:null, startedHoursAgo:8  },
  { id:"d12", account:"@daisy_vibesxx",       persona:"Melodie", target:"@brookefit",       stage:"cold",       messages:2,  lastMsg:"oh hey! you follow me?",             replyRate:50, ctaSent:false, ctaClicked:false, hoursToConvert:null, startedHoursAgo:3  },
];

const STAGE_META: Record<DmStage, { label: string; color: string; bg: string; border: string }> = {
  cold:      { label: "Cold",      color: "text-phantom-ghost",   bg: "bg-phantom-ghost/10",   border: "border-phantom-ghost/20"   },
  warm:      { label: "Warm",      color: "text-phantom-amber",   bg: "bg-phantom-amber/10",   border: "border-phantom-amber/20"   },
  cta_sent:  { label: "CTA Sent",  color: "text-phantom-magenta", bg: "bg-phantom-magenta/10", border: "border-phantom-magenta/20" },
  converted: { label: "Converted", color: "text-phantom-accent",  bg: "bg-phantom-accent/10",  border: "border-phantom-accent/20"  },
  dead:      { label: "Dead",      color: "text-phantom-red",     bg: "bg-red-500/10",         border: "border-red-500/20"         },
};

// ─── OF Attribution data ─────────────────────────────────────────────────────

type OFAttribution = {
  account: string;
  persona: string;
  platform: string;
  subs: number;
  revenue: number;
  avgSubValue: number;
  weeklyTrend: number[]; // 7 days
};

const OF_ATTRIBUTIONS: OFAttribution[] = [
  { account:"@tatiannalifee",      persona:"Tatiana", platform:"Instagram", subs:8,  revenue:1_440, avgSubValue:180, weeklyTrend:[0,1,0,2,1,2,2] },
  { account:"@melodieeeprincesss", persona:"Melodie", platform:"Instagram", subs:6,  revenue:1_020, avgSubValue:170, weeklyTrend:[1,0,1,1,0,2,1] },
  { account:"@hackerhoneytatii",   persona:"Tatiana", platform:"Threads",   subs:5,  revenue:900,   avgSubValue:180, weeklyTrend:[0,0,1,2,0,1,1] },
  { account:"@tatianamusee",       persona:"Tatiana", platform:"Instagram", subs:4,  revenue:720,   avgSubValue:180, weeklyTrend:[0,1,0,1,1,0,1] },
  { account:"@u_melodieee",        persona:"Melodie", platform:"Reddit",    subs:3,  revenue:510,   avgSubValue:170, weeklyTrend:[0,0,0,1,1,0,1] },
  { account:"@tatiana_sunx",       persona:"Tatiana", platform:"Instagram", subs:3,  revenue:540,   avgSubValue:180, weeklyTrend:[1,0,0,1,0,1,0] },
  { account:"@melodie_life",       persona:"Melodie", platform:"Instagram", subs:2,  revenue:340,   avgSubValue:170, weeklyTrend:[0,0,1,0,0,1,0] },
  { account:"@daisy_vibesxx",      persona:"Tatiana", platform:"Instagram", subs:2,  revenue:360,   avgSubValue:180, weeklyTrend:[0,1,0,0,1,0,0] },
];

const OF_DAYS = ["M","T","W","T","F","S","S"];

// ─── Mini bar sparkline ───────────────────────────────────────────────────────

function WeekBar({ data, color = "bg-phantom-accent" }: { data: number[]; color?: string }) {
  const max = Math.max(...data, 1);
  return (
    <div className="flex items-end gap-px h-5">
      {data.map((v, i) => (
        <div key={i} className="flex flex-col items-center gap-px w-3">
          <div
            className={cn("w-full rounded-sm min-h-[2px]", v > 0 ? color : "bg-phantom-border/40")}
            style={{ height: `${Math.max(2, (v / max) * 20)}px` }}
          />
        </div>
      ))}
    </div>
  );
}

// Top performers
const TOP_ACCOUNTS = [
  { username: "melodieeeprincesss", persona: "Melodie", conversions: 6, revenue: 1_020, platform: "Instagram" },
  { username: "tatiannalifee", persona: "Tatiana", conversions: 5, revenue: 900, platform: "Instagram" },
  { username: "tatianamusee", persona: "Tatiana", conversions: 4, revenue: 720, platform: "Instagram" },
  { username: "hackerhoneytatii", persona: "Tatiana", conversions: 3, revenue: 540, platform: "Threads" },
  { username: "u_melodieee", persona: "Melodie", conversions: 3, revenue: 510, platform: "Reddit" },
];

// ─── Stage-to-stage arrow component ─────────────────────────────────────────

function StageTransition({ from, to }: { from: FunnelStage; to: FunnelStage }) {
  const rate = from.count > 0 ? ((to.count / from.count) * 100).toFixed(1) : "0.0";
  const isGood = parseFloat(rate) >= 25;
  return (
    <div className="flex items-center justify-center gap-2 py-0.5">
      <ArrowRight className="w-3 h-3 text-phantom-border" />
      <span
        className={cn(
          "text-[9px] font-mono tabular-nums",
          isGood ? "text-phantom-alive" : "text-phantom-ghost"
        )}
      >
        {rate}% pass-through
      </span>
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function FunnelPage() {
  const [expandedPersona, setExpandedPersona] = useState<string | null>("Tatiana");

  const totalRevenue = PERSONA_FUNNELS.reduce((s, p) => s + p.revenue, 0);
  const totalConversions = MAIN_FUNNEL[MAIN_FUNNEL.length - 1].count;
  const overallCvr = MAIN_FUNNEL[0].count > 0
    ? ((totalConversions / MAIN_FUNNEL[0].count) * 100).toFixed(3)
    : "0.0";

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Revenue attribution
          </div>
          <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
            <DollarSign className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
            Fan <span className="phantom-accent-text">Funnel</span>
          </h1>
          <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
            Every conversion — subscription, store purchase, lead capture, affiliate click —
            attributed back to the persona and account that drove it.
          </p>
        </div>
        {/* Summary badges */}
        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-2 text-xs text-phantom-ghost">
            <TrendingUp className="w-3.5 h-3.5 text-phantom-alive" />
            <span>{overallCvr}% end-to-end CVR</span>
          </div>
          <div className="font-mono text-[10px] text-phantom-ghost">
            scraped → converted · 24h window
          </div>
        </div>
      </div>

      {/* Macro KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="phantom-panel-accent p-5">
          <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">Revenue today</div>
          <div className="phantom-metric-lg mt-2 phantom-accent-text">{fmtUSD(totalRevenue)}</div>
        </div>
        <div className="phantom-panel p-5">
          <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">Conversions</div>
          <div className="phantom-metric-lg mt-2">{totalConversions}</div>
        </div>
        <div className="phantom-panel p-5">
          <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">Revenue / conv.</div>
          <div className="phantom-metric-lg mt-2 text-phantom-magenta">
            {fmtUSD(totalConversions > 0 ? totalRevenue / totalConversions : 0)}
          </div>
        </div>
        <div className="phantom-panel p-5">
          <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">Cost / conversion</div>
          <div className="phantom-metric-lg mt-2 text-phantom-amber">$4.28</div>
          <div className="text-[10px] text-phantom-ghost mt-1">Full-stack ops</div>
        </div>
      </div>

      {/* Main waterfall + Totals side panel */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Panel
          label="conversion waterfall"
          title="24h funnel"
          subtitle="From scraped target to subscription."
          className="lg:col-span-2"
        >
          <FunnelViz stages={MAIN_FUNNEL} />
          {/* Stage-to-stage conversion rates */}
          <div className="mt-6 pt-4 border-t border-phantom-border">
            <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost mb-3">
              Stage transitions
            </div>
            <div className="space-y-0.5">
              {MAIN_FUNNEL.slice(0, -1).map((stage, i) => (
                <div key={stage.label} className="flex items-center gap-3 text-xs">
                  <span className="text-phantom-ghost w-40 truncate shrink-0">{stage.label}</span>
                  <ChevronRight className="w-3 h-3 text-phantom-border shrink-0" />
                  <span className="text-phantom-ghost flex-1">{MAIN_FUNNEL[i + 1].label}</span>
                  <span
                    className={cn(
                      "font-mono tabular-nums text-[10px]",
                      (MAIN_FUNNEL[i + 1].count / stage.count) > 0.3
                        ? "text-phantom-alive"
                        : (MAIN_FUNNEL[i + 1].count / stage.count) > 0.1
                        ? "text-phantom-amber"
                        : "text-phantom-ghost"
                    )}
                  >
                    {((MAIN_FUNNEL[i + 1].count / stage.count) * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </Panel>

        {/* Revenue totals */}
        <Panel label="conversion totals" title="30-day revenue">
          <div className="space-y-5">
            {PERSONA_FUNNELS.map((pf) => (
              <div key={pf.persona}>
                <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">
                  {pf.persona}
                </div>
                <div
                  className={cn(
                    "phantom-metric text-3xl mt-1.5",
                    pf.persona === "Tatiana" ? "text-phantom-accent" : "text-phantom-magenta"
                  )}
                >
                  {fmtUSD(pf.revenue)}
                </div>
                <div className="text-xs text-phantom-ghost mt-0.5">
                  {pf.conversions} conversions · {pf.platform}
                </div>
              </div>
            ))}
            <div className="pt-4 border-t border-phantom-border">
              <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">
                Total attributed
              </div>
              <div className="phantom-metric-lg mt-1.5">{fmtUSD(totalRevenue)}</div>
              <div className="text-xs text-phantom-ghost mt-0.5">
                vs target {fmtUSD(5_000)}
              </div>
            </div>
          </div>
        </Panel>
      </div>

      {/* Per-persona funnel breakdown */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-4">
          Per-persona funnel breakdown
        </div>
        <div className="space-y-3">
          {PERSONA_FUNNELS.map((pf) => (
            <div key={pf.persona} className="phantom-panel overflow-hidden">
              {/* Accordion header */}
              <button
                onClick={() =>
                  setExpandedPersona(expandedPersona === pf.persona ? null : pf.persona)
                }
                className="w-full flex items-center justify-between p-5 hover:bg-phantom-panelHi/30 transition-colors"
              >
                <div className="flex items-center gap-4">
                  <div className="text-sm font-display font-semibold">{pf.persona}</div>
                  <span className="text-xs text-phantom-ghost">{pf.platform}</span>
                  <span
                    className={cn(
                      "text-xs font-mono tabular-nums",
                      pf.persona === "Tatiana" ? "text-phantom-accent" : "text-phantom-magenta"
                    )}
                  >
                    {fmtUSD(pf.revenue)}
                  </span>
                  <span className="text-xs text-phantom-ghost">{pf.conversions} conversions</span>
                </div>
                <ChevronDown
                  className={cn(
                    "w-4 h-4 text-phantom-ghost transition-transform duration-200",
                    expandedPersona === pf.persona && "rotate-180"
                  )}
                />
              </button>
              {/* Expanded funnel */}
              {expandedPersona === pf.persona && (
                <div className="px-5 pb-5 border-t border-phantom-border">
                  <div className="pt-4">
                    <FunnelViz stages={pf.stages} />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Top performing accounts */}
      <Panel
        label="top performers"
        title="Best performing accounts"
        subtitle="Ranked by conversions in last 30 days."
      >
        <div className="overflow-x-auto -mx-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                <th className="px-3 py-2.5 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left">Rank</th>
                <th className="px-3 py-2.5 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left">Account</th>
                <th className="px-3 py-2.5 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left">Persona</th>
                <th className="px-3 py-2.5 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left">Platform</th>
                <th className="px-3 py-2.5 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-right">Conversions</th>
                <th className="px-3 py-2.5 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-right">Revenue</th>
              </tr>
            </thead>
            <tbody>
              {TOP_ACCOUNTS.map((a, i) => (
                <tr
                  key={a.username}
                  className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors"
                >
                  <td className="px-3 py-3">
                    <span
                      className={cn(
                        "font-mono text-sm font-bold tabular-nums",
                        i === 0
                          ? "text-phantom-accent"
                          : i === 1
                          ? "text-phantom-ghost"
                          : "text-phantom-ghost/60"
                      )}
                    >
                      #{i + 1}
                    </span>
                  </td>
                  <td className="px-3 py-3 font-mono text-xs text-white">@{a.username}</td>
                  <td className="px-3 py-3 text-xs text-phantom-ghost">{a.persona}</td>
                  <td className="px-3 py-3 text-xs text-phantom-ghost">{a.platform}</td>
                  <td className="px-3 py-3 text-right font-mono tabular-nums text-phantom-accent font-semibold">
                    {a.conversions}
                  </td>
                  <td className="px-3 py-3 text-right font-mono tabular-nums font-bold">
                    {fmtUSD(a.revenue)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* DM Funnel Tracker */}
      <Panel
        label="dm funnel tracker"
        title="DM Conversation Pipeline"
        subtitle="Per-account conversation stage, reply rate, and CTA performance."
        actions={
          <div className="flex items-center gap-3 text-[10px] font-mono text-phantom-ghost">
            {(["converted","cta_sent","warm","cold","dead"] as DmStage[]).map((s) => (
              <span key={s} className={cn("flex items-center gap-1", STAGE_META[s].color)}>
                <span className={cn("w-1.5 h-1.5 rounded-full inline-block", STAGE_META[s].bg.replace("/10",""))} />
                {STAGE_META[s].label}
              </span>
            ))}
          </div>
        }
      >
        {/* Stage summary strip */}
        <div className="grid grid-cols-5 gap-3 mb-5">
          {(["converted","cta_sent","warm","cold","dead"] as DmStage[]).map((s) => {
            const count = DM_CONVERSATIONS.filter((d) => d.stage === s).length;
            const m = STAGE_META[s];
            return (
              <div key={s} className={cn("rounded-lg p-3 border text-center", m.bg, m.border)}>
                <div className={cn("text-xl font-bold font-mono", m.color)}>{count}</div>
                <div className="text-[10px] text-phantom-ghost mt-0.5">{m.label}</div>
              </div>
            );
          })}
        </div>

        {/* Conversation table */}
        <div className="overflow-x-auto -mx-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                {["Account","Target","Stage","Msgs","Reply Rate","CTA","Last Message","Started"].map((h) => (
                  <th key={h} className="px-3 py-2 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left whitespace-nowrap">{h}</th>
                ))}
                <th className="px-3 py-2 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-right whitespace-nowrap">Time to conv.</th>
              </tr>
            </thead>
            <tbody>
              {DM_CONVERSATIONS.map((d) => {
                const m = STAGE_META[d.stage];
                return (
                  <tr key={d.id} className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors">
                    <td className="px-3 py-2.5 font-mono text-xs text-phantom-accent whitespace-nowrap">{d.account}</td>
                    <td className="px-3 py-2.5 font-mono text-[11px] text-phantom-ghost whitespace-nowrap">{d.target}</td>
                    <td className="px-3 py-2.5">
                      <span className={cn("text-[10px] font-mono px-2 py-0.5 rounded border", m.color, m.bg, m.border)}>
                        {m.label}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-center">{d.messages}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-1.5">
                        <div className="w-12 h-1.5 rounded-full bg-phantom-border overflow-hidden">
                          <div
                            className={cn("h-full rounded-full", d.replyRate >= 70 ? "bg-phantom-alive" : d.replyRate >= 40 ? "bg-phantom-amber" : "bg-phantom-red")}
                            style={{ width: `${d.replyRate}%` }}
                          />
                        </div>
                        <span className="text-[10px] font-mono text-phantom-ghost">{d.replyRate}%</span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-1">
                        {d.ctaSent
                          ? d.ctaClicked
                            ? <CheckCircle2 className="w-3.5 h-3.5 text-phantom-accent" />
                            : <LinkIcon className="w-3.5 h-3.5 text-phantom-magenta" />
                          : <XCircle className="w-3.5 h-3.5 text-phantom-ghost/30" />
                        }
                        <span className="text-[10px] font-mono text-phantom-ghost">
                          {d.ctaSent ? (d.ctaClicked ? "clicked" : "sent") : "—"}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-[11px] text-phantom-ghost max-w-[180px] truncate">{d.lastMsg}</td>
                    <td className="px-3 py-2.5 text-[10px] font-mono text-phantom-ghost whitespace-nowrap">
                      {d.startedHoursAgo}h ago
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono text-[11px]">
                      {d.hoursToConvert !== null
                        ? <span className="text-phantom-accent">{d.hoursToConvert}h</span>
                        : <span className="text-phantom-ghost/40">—</span>
                      }
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* CTA stats footer */}
        <div className="flex items-center gap-6 mt-4 pt-4 border-t border-phantom-border text-[10px] font-mono text-phantom-ghost">
          <span>
            CTA sent: <span className="text-phantom-magenta">{DM_CONVERSATIONS.filter(d => d.ctaSent).length}</span>
          </span>
          <span>
            CTA clicked: <span className="text-phantom-accent">{DM_CONVERSATIONS.filter(d => d.ctaClicked).length}</span>
          </span>
          <span>
            Click rate: <span className="text-white">
              {((DM_CONVERSATIONS.filter(d => d.ctaClicked).length / Math.max(1, DM_CONVERSATIONS.filter(d => d.ctaSent).length)) * 100).toFixed(0)}%
            </span>
          </span>
          <span>
            Avg reply rate: <span className="text-phantom-amber">
              {(DM_CONVERSATIONS.reduce((s, d) => s + d.replyRate, 0) / DM_CONVERSATIONS.length).toFixed(0)}%
            </span>
          </span>
          <span>
            Avg time to convert: <span className="text-phantom-alive">
              {(DM_CONVERSATIONS.filter(d => d.hoursToConvert !== null).reduce((s, d) => s + (d.hoursToConvert ?? 0), 0) / Math.max(1, DM_CONVERSATIONS.filter(d => d.hoursToConvert !== null).length)).toFixed(0)}h
            </span>
          </span>
        </div>
      </Panel>

      {/* OF Link Attribution */}
      <Panel
        label="of attribution"
        title="OnlyFans Link Attribution"
        subtitle="Which accounts drove which subscriptions — revenue traced to source."
        actions={
          <div className="flex items-center gap-3">
            <span className="text-[10px] font-mono text-phantom-ghost">Last 7 days</span>
            <div className="flex items-center gap-1 text-[10px] font-mono text-phantom-ghost">
              {OF_DAYS.map((d, i) => <span key={i} className="w-5 text-center text-phantom-ghost/60">{d}</span>)}
            </div>
          </div>
        }
      >
        {/* Persona revenue split */}
        <div className="grid grid-cols-2 gap-4 mb-6">
          {["Tatiana","Melodie"].map((persona) => {
            const rows = OF_ATTRIBUTIONS.filter(r => r.persona === persona);
            const total = rows.reduce((s, r) => s + r.revenue, 0);
            const totalSubs = rows.reduce((s, r) => s + r.subs, 0);
            const isT = persona === "Tatiana";
            return (
              <div key={persona} className={cn("rounded-xl border p-4", isT ? "bg-phantom-accent/5 border-phantom-accent/20" : "bg-phantom-magenta/5 border-phantom-magenta/20")}>
                <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">{persona}</div>
                <div className={cn("text-2xl font-bold font-mono mt-1", isT ? "text-phantom-accent" : "text-phantom-magenta")}>{fmtUSD(total)}</div>
                <div className="text-xs text-phantom-ghost mt-0.5">{totalSubs} subs · {rows.length} accounts</div>
                <div className="flex items-end gap-px h-4 mt-3">
                  {Array.from({ length: 7 }, (_, i) => {
                    const dayTotal = rows.reduce((s, r) => s + r.weeklyTrend[i], 0);
                    const maxDay = 4;
                    return (
                      <div key={i} className={cn("flex-1 rounded-sm min-h-[2px]", isT ? "bg-phantom-accent" : "bg-phantom-magenta")}
                        style={{ height: `${Math.max(2, (dayTotal / maxDay) * 16)}px`, opacity: dayTotal > 0 ? 1 : 0.2 }} />
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        {/* Attribution table */}
        <div className="overflow-x-auto -mx-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                <th className="px-3 py-2 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left">Account</th>
                <th className="px-3 py-2 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left">Persona</th>
                <th className="px-3 py-2 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left">Platform</th>
                <th className="px-3 py-2 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-right">Subs</th>
                <th className="px-3 py-2 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-right">Avg Sub $</th>
                <th className="px-3 py-2 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-right">Revenue</th>
                <th className="px-3 py-2 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-center">7d Trend</th>
                <th className="px-3 py-2 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left">Rev %</th>
              </tr>
            </thead>
            <tbody>
              {OF_ATTRIBUTIONS.map((row) => {
                const totalRevAll = OF_ATTRIBUTIONS.reduce((s, r) => s + r.revenue, 0);
                const pct = ((row.revenue / totalRevAll) * 100).toFixed(1);
                const isT = row.persona === "Tatiana";
                return (
                  <tr key={row.account} className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors">
                    <td className="px-3 py-2.5 font-mono text-xs text-phantom-accent">{row.account}</td>
                    <td className="px-3 py-2.5 text-xs text-phantom-ghost">{row.persona}</td>
                    <td className="px-3 py-2.5 text-xs text-phantom-ghost">{row.platform}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-sm font-bold">{row.subs}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-xs text-phantom-ghost">{fmtUSD(row.avgSubValue)}</td>
                    <td className="px-3 py-2.5 text-right font-mono font-bold">
                      <span className={isT ? "text-phantom-accent" : "text-phantom-magenta"}>{fmtUSD(row.revenue)}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex justify-center">
                        <WeekBar data={row.weeklyTrend} color={isT ? "bg-phantom-accent" : "bg-phantom-magenta"} />
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-1.5">
                        <div className="w-16 h-1.5 rounded-full bg-phantom-border overflow-hidden">
                          <div
                            className={cn("h-full rounded-full", isT ? "bg-phantom-accent" : "bg-phantom-magenta")}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="text-[10px] font-mono text-phantom-ghost">{pct}%</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Attribution totals */}
        <div className="flex items-center justify-between mt-4 pt-4 border-t border-phantom-border">
          <div className="flex items-center gap-6 text-[10px] font-mono text-phantom-ghost">
            <span>Total attributed: <span className="text-white font-bold">{fmtUSD(OF_ATTRIBUTIONS.reduce((s, r) => s + r.revenue, 0))}</span></span>
            <span>Total subs: <span className="text-phantom-accent font-bold">{OF_ATTRIBUTIONS.reduce((s, r) => s + r.subs, 0)}</span></span>
            <span>Avg $ / sub: <span className="text-phantom-alive font-bold">{fmtUSD(OF_ATTRIBUTIONS.reduce((s, r) => s + r.revenue, 0) / Math.max(1, OF_ATTRIBUTIONS.reduce((s, r) => s + r.subs, 0)))}</span></span>
          </div>
          <div className="text-[10px] font-mono text-phantom-ghost">
            Attribution window: 30d
          </div>
        </div>
      </Panel>

      {/* Revenue chart */}
      <RevenueChart />
    </div>
  );
}
