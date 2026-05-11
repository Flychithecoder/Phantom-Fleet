"use client";

import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { MessageCircle } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

type ConvoStage = "matched" | "first_sent" | "replied" | "link_stage" | "converted";

const STAGE_LABELS: Record<ConvoStage, string> = {
  matched:     "Matched",
  first_sent:  "First Sent",
  replied:     "Replied",
  link_stage:  "Link Stage",
  converted:   "Converted",
};

const STAGE_COLORS: Record<ConvoStage, string> = {
  matched:     "bg-phantom-ghost/10 text-phantom-ghost border-phantom-ghost/20",
  first_sent:  "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/20",
  replied:     "bg-phantom-alive/10 text-phantom-alive border-phantom-alive/20",
  link_stage:  "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/20",
  converted:   "bg-phantom-magenta/10 text-phantom-magenta border-phantom-magenta/20",
};

const ACCOUNTS = [
  { id: "1",  name: "Chloe_B",      matchesWaiting: 8,  firstSentToday: 12, responsesRx: 8,  stage: "replied"     as ConvoStage, lastAction: "3m ago"  },
  { id: "2",  name: "Savannah_B",   matchesWaiting: 3,  firstSentToday: 9,  responsesRx: 7,  stage: "link_stage"  as ConvoStage, lastAction: "7m ago"  },
  { id: "3",  name: "Harper_B2",    matchesWaiting: 11, firstSentToday: 6,  responsesRx: 4,  stage: "first_sent"  as ConvoStage, lastAction: "14m ago" },
  { id: "4",  name: "Ivy_Rose",     matchesWaiting: 0,  firstSentToday: 14, responsesRx: 11, stage: "converted"   as ConvoStage, lastAction: "22m ago" },
  { id: "5",  name: "Piper_B",      matchesWaiting: 5,  firstSentToday: 8,  responsesRx: 5,  stage: "replied"     as ConvoStage, lastAction: "31m ago" },
  { id: "6",  name: "Zoe_Bumble",   matchesWaiting: 2,  firstSentToday: 11, responsesRx: 6,  stage: "link_stage"  as ConvoStage, lastAction: "45m ago" },
  { id: "7",  name: "Naomi_B",      matchesWaiting: 7,  firstSentToday: 4,  responsesRx: 2,  stage: "matched"     as ConvoStage, lastAction: "1h ago"  },
  { id: "8",  name: "Fiona_Gold",   matchesWaiting: 1,  firstSentToday: 13, responsesRx: 9,  stage: "replied"     as ConvoStage, lastAction: "1.2h ago"},
];

type MsgPerf = { id: string; template: string; sent: number; responses: number; rate: number; variant: "A" | "B" };

const FIRST_MSG_TEMPLATES: MsgPerf[] = [
  { id: "t1", template: "Hey! I noticed you love hiking too 🏔️ — what's your favourite trail?", sent: 184, responses: 143, rate: 77.7, variant: "A" },
  { id: "t2", template: "Ok wait, your dog in photo 3 is literally the cutest thing I've ever seen 🐶",  sent: 198, responses: 124, rate: 62.6, variant: "A" },
  { id: "t3", template: "I saw you work in [field] — I have so many questions 👀",                       sent: 156, responses: 118, rate: 75.6, variant: "B" },
  { id: "t4", template: "Two truths and a lie — go! I'll start once you guess mine 😏",                   sent: 172, responses: 96,  rate: 55.8, variant: "B" },
  { id: "t5", template: "Okay your taste in [show/book] is genuinely impressive, we need to talk",       sent: 143, responses: 101, rate: 70.6, variant: "A" },
];

const EXPIRY_QUEUE = [
  { id: "e1", account: "Harper_B2", matchName: "Emma L.",  platform: "Bumble", expiresIn: "4h",  matchAge: "20h", priority: "high"   },
  { id: "e2", account: "Chloe_B",   matchName: "Ava R.",   platform: "Bumble", expiresIn: "6h",  matchAge: "18h", priority: "high"   },
  { id: "e3", account: "Naomi_B",   matchName: "Grace T.", platform: "Bumble", expiresIn: "8h",  matchAge: "16h", priority: "medium" },
  { id: "e4", account: "Piper_B",   matchName: "Lily K.",  platform: "Bumble", expiresIn: "11h", matchAge: "13h", priority: "medium" },
  { id: "e5", account: "Zoe_Bumble",matchName: "Mia S.",   platform: "Bumble", expiresIn: "14h", matchAge: "10h", priority: "low"    },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function BumbleManagementPage() {
  const maxRate = Math.max(...FIRST_MSG_TEMPLATES.map((t) => t.rate));

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Dating · Bumble
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <MessageCircle className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          Bumble <span className="phantom-accent-text">Management</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          31 female personas running Bumble — women must message first. Tracking first-move rate,
          opening line A/B tests, and expiry queue urgency.
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Active Profiles"  value="31"    sub="all female personas"   accent />
        <KPICard label="First-Move Rate"  value="89%"   delta={0.042}                      />
        <KPICard label="Matches Today"    value="9"     delta={-0.1}                       />
        <KPICard label="Response Rate"    value="67%"   delta={0.073}                      />
      </div>

      {/* Account table */}
      <Panel label="accounts" title="Profile Status" subtitle="31 active Bumble personas — conversation stage tracking">
        <div className="overflow-x-auto -mx-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                {["Profile", "Matches Waiting", "First Msgs Sent", "Responses Rx", "Conversation Stage", "Last Action"].map((h) => (
                  <th key={h} className="px-3 py-2.5 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ACCOUNTS.map((row) => (
                <tr key={row.id} className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors">
                  <td className="px-3 py-3 font-mono text-xs text-phantom-accent">{row.name}</td>
                  <td className="px-3 py-3 tabular-nums">
                    {row.matchesWaiting > 0
                      ? <span className={cn("font-bold", row.matchesWaiting >= 8 ? "text-phantom-amber" : "text-white")}>{row.matchesWaiting}</span>
                      : <span className="text-phantom-ghost">—</span>
                    }
                  </td>
                  <td className="px-3 py-3 tabular-nums text-phantom-ghost text-xs">{row.firstSentToday}</td>
                  <td className="px-3 py-3 tabular-nums font-semibold">{row.responsesRx}</td>
                  <td className="px-3 py-3">
                    <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-bold border", STAGE_COLORS[row.stage])}>
                      {STAGE_LABELS[row.stage]}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-phantom-ghost text-xs">{row.lastAction}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* First-message A/B + Expiry queue */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Template performance */}
        <div className="lg:col-span-2">
          <Panel label="A/B test" title="Opening Line Performance" subtitle="Response rates for first-message templates">
            <div className="space-y-4">
              {FIRST_MSG_TEMPLATES.sort((a, b) => b.rate - a.rate).map((t) => (
                <div key={t.id} className="space-y-1.5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-2 flex-1 min-w-0">
                      <span className={cn(
                        "mt-0.5 flex-shrink-0 px-1.5 py-0.5 rounded text-[9px] font-bold border",
                        t.variant === "A"
                          ? "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/20"
                          : "bg-phantom-magenta/10 text-phantom-magenta border-phantom-magenta/20"
                      )}>
                        {t.variant}
                      </span>
                      <p className="text-xs text-phantom-ghost leading-relaxed truncate">{t.template}</p>
                    </div>
                    <div className="flex-shrink-0 text-right">
                      <div className={cn(
                        "font-bold tabular-nums text-sm",
                        t.rate >= 75 ? "text-phantom-alive" : t.rate >= 65 ? "phantom-accent-text" : "text-phantom-amber"
                      )}>
                        {t.rate.toFixed(1)}%
                      </div>
                      <div className="text-[10px] text-phantom-ghost">{t.responses}/{t.sent}</div>
                    </div>
                  </div>
                  <div className="h-2 rounded-full bg-phantom-panelHi overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full",
                        t.rate === maxRate ? "bg-phantom-alive" : t.rate >= 70 ? "bg-phantom-accent" : "bg-phantom-amber"
                      )}
                      style={{ width: `${(t.rate / 100) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        {/* Expiry Queue */}
        <div>
          <Panel label="urgent" title="Expiry Queue" subtitle="Matches expiring — must send first message">
            <div className="space-y-3">
              <div className="flex items-center gap-2 p-2 rounded-lg bg-phantom-amber/10 border border-phantom-amber/20">
                <span className="text-phantom-amber text-xs font-bold">⚠</span>
                <span className="text-phantom-amber text-xs font-semibold">{EXPIRY_QUEUE.length} matches need action</span>
              </div>
              {EXPIRY_QUEUE.map((item) => (
                <div key={item.id} className={cn(
                  "p-3 rounded-lg border space-y-1.5",
                  item.priority === "high"
                    ? "bg-phantom-red/5 border-phantom-red/20"
                    : item.priority === "medium"
                    ? "bg-phantom-amber/5 border-phantom-amber/20"
                    : "bg-phantom-panelHi border-phantom-border/40"
                )}>
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs text-phantom-accent">{item.account}</span>
                    <span className={cn(
                      "text-xs font-bold tabular-nums",
                      item.priority === "high" ? "text-phantom-red" : item.priority === "medium" ? "text-phantom-amber" : "text-phantom-ghost"
                    )}>
                      {item.expiresIn}
                    </span>
                  </div>
                  <div className="text-xs text-white font-medium">{item.matchName}</div>
                  <div className="text-[11px] text-phantom-ghost">Matched {item.matchAge} ago</div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
