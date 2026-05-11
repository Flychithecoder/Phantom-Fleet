"use client";

import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { CalendarDays } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

type PostStatus = "queued" | "posted" | "failed";

const STATUS_STYLES: Record<PostStatus, { bg: string; text: string; border: string }> = {
  queued: { bg: "bg-blue-500/10",           text: "text-blue-300",        border: "border-blue-500/20"          },
  posted: { bg: "bg-phantom-alive/10",      text: "text-phantom-alive",   border: "border-phantom-alive/20"     },
  failed: { bg: "bg-phantom-red/10",        text: "text-phantom-red",     border: "border-phantom-red/20"       },
};

const CONTENT_QUEUE = [
  { id: "1",  title: "Morning routine #wellness",    persona: "@luna_aesthetic", accounts: 12, scheduled: "Today 08:00",  hashtags: "#lifestyle #morning",   region: "US", status: "posted" as PostStatus },
  { id: "2",  title: "GRWM night out",               persona: "@mia_vibes_xo",  accounts: 8,  scheduled: "Today 10:30",  hashtags: "#grwm #fashion",        region: "UK", status: "posted" as PostStatus },
  { id: "3",  title: "Fit check Sunday",             persona: "@nova_daily",    accounts: 15, scheduled: "Today 12:00",  hashtags: "#fitcheck #style",      region: "US", status: "queued" as PostStatus },
  { id: "4",  title: "Skincare unboxing haul",       persona: "@jade_glowup",   accounts: 10, scheduled: "Today 14:15",  hashtags: "#skincare #haul",       region: "CA", status: "queued" as PostStatus },
  { id: "5",  title: "What I eat in a day 🥗",       persona: "@grace_fit_life",accounts: 6,  scheduled: "Today 16:00",  hashtags: "#whatieatinaday #food", region: "AU", status: "queued" as PostStatus },
  { id: "6",  title: "Apartment tour NYC",           persona: "@aria_content",  accounts: 9,  scheduled: "Today 18:45",  hashtags: "#apartmenttour #nyc",   region: "US", status: "queued" as PostStatus },
  { id: "7",  title: "Study with me 3hr session",    persona: "@swift_emma",    accounts: 11, scheduled: "Today 20:00",  hashtags: "#studywithme #school",  region: "UK", status: "failed" as PostStatus },
  { id: "8",  title: "London cafe vlog",             persona: "@nova_daily",    accounts: 7,  scheduled: "Tomorrow 09:00",hashtags: "#london #cafe #vlog",   region: "UK", status: "queued" as PostStatus },
];

const TOP_VIDEOS = [
  { id: "v1", title: "Morning routine #wellness",  views: "142K", likeRate: 8.4, commentRate: 1.2, shareRate: 2.1 },
  { id: "v2", title: "GRWM night out",             views: "98K",  likeRate: 7.9, commentRate: 0.9, shareRate: 1.8 },
  { id: "v3", title: "Fit check Sunday",           views: "87K",  likeRate: 6.2, commentRate: 0.7, shareRate: 1.4 },
  { id: "v4", title: "Skincare unboxing haul",     views: "74K",  likeRate: 5.8, commentRate: 1.4, shareRate: 1.1 },
  { id: "v5", title: "Apartment tour NYC",         views: "61K",  likeRate: 4.9, commentRate: 0.6, shareRate: 0.9 },
];

// Heatmap: hours 6am–midnight × regions US/UK/AU  (0=cold, 3=hottest)
const HEATMAP_HOURS = ["6am", "8am", "10am", "12pm", "2pm", "4pm", "6pm", "8pm", "10pm", "12am"];
const HEATMAP_DATA: Record<string, number[]> = {
  US: [1, 2, 3, 2, 2, 3, 3, 3, 2, 1],
  UK: [0, 1, 2, 3, 2, 2, 3, 3, 2, 1],
  AU: [1, 3, 3, 2, 1, 1, 2, 2, 3, 2],
};
const HEAT_COLORS = [
  "bg-phantom-panelHi border-phantom-border text-phantom-ghost/40",
  "bg-blue-900/40 border-blue-700/20 text-blue-300/60",
  "bg-phantom-accent/20 border-phantom-accent/20 text-phantom-accent/80",
  "bg-phantom-accent/50 border-phantom-accent/30 text-phantom-accent",
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function TikTokContentPage() {
  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          TikTok · content
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <CalendarDays className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Content <span className="phantom-accent-text">Schedule</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-alive/10 border border-phantom-alive/20 text-phantom-alive text-xs font-semibold">
            124 posts today
          </span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Cross-account video scheduling, performance analytics, and optimal posting time distribution across regions.
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Posts Today"         value="124"    delta={0.094}  sub="vs yesterday"                 />
        <KPICard label="Avg Views / Post"    value="8.4K"   delta={0.052}  sub="7-day average"                />
        <KPICard label="Top Hashtag"         value="#lifestyle" sub="2.1M reach this week"                   />
        <KPICard label="Scheduled This Week" value="847"    sub="across all accounts"     accent             />
      </div>

      {/* Content queue table */}
      <Panel label="queue" title="Content Queue">
        <div className="overflow-x-auto -mx-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                {["Video", "Persona", "Accounts", "Scheduled", "Hashtags", "Region", "Status"].map((h) => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CONTENT_QUEUE.map((row) => {
                const s = STATUS_STYLES[row.status];
                return (
                  <tr key={row.id} className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors">
                    <td className="px-3 py-3 text-xs text-white font-medium max-w-[180px] truncate">{row.title}</td>
                    <td className="px-3 py-3 font-mono text-xs text-phantom-accent">{row.persona}</td>
                    <td className="px-3 py-3 text-xs tabular-nums text-white font-semibold">{row.accounts}</td>
                    <td className="px-3 py-3 text-xs text-phantom-ghost tabular-nums">{row.scheduled}</td>
                    <td className="px-3 py-3 text-xs text-phantom-ghost max-w-[140px] truncate">{row.hashtags}</td>
                    <td className="px-3 py-3 text-xs text-white">{row.region}</td>
                    <td className="px-3 py-3">
                      <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-semibold border capitalize", s.bg, s.text, s.border)}>
                        {row.status}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Two-column: top performing + heatmap */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top performing videos */}
        <Panel label="performance" title="Top Performing Videos">
          <div className="space-y-4">
            {TOP_VIDEOS.map((v, i) => (
              <div key={v.id} className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-[11px] font-bold text-phantom-ghost w-4 flex-shrink-0">#{i + 1}</span>
                    <span className="text-xs text-white truncate">{v.title}</span>
                  </div>
                  <span className="font-mono text-xs font-bold phantom-accent-text flex-shrink-0">{v.views}</span>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { label: "Likes",    val: v.likeRate    },
                    { label: "Comments", val: v.commentRate },
                    { label: "Shares",   val: v.shareRate   },
                  ].map((m) => (
                    <div key={m.label} className="space-y-1">
                      <div className="flex justify-between text-[10px] text-phantom-ghost">
                        <span>{m.label}</span>
                        <span className="tabular-nums">{m.val}%</span>
                      </div>
                      <div className="h-1 rounded-full bg-phantom-border overflow-hidden">
                        <div
                          className="h-full rounded-full bg-phantom-accent/60"
                          style={{ width: `${(m.val / 10) * 100}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Panel>

        {/* Posting time heatmap */}
        <Panel label="optimal posting times" title="Regional Time Heatmap">
          <div className="space-y-4">
            {Object.entries(HEATMAP_DATA).map(([region, vals]) => (
              <div key={region} className="space-y-1.5">
                <div className="text-[11px] uppercase tracking-wider text-phantom-ghost font-semibold">{region}</div>
                <div className="grid grid-cols-10 gap-1">
                  {vals.map((heat, i) => (
                    <div
                      key={i}
                      className={cn("h-8 rounded border flex items-center justify-center text-[9px] font-medium", HEAT_COLORS[heat])}
                      title={HEATMAP_HOURS[i]}
                    >
                      {HEATMAP_HOURS[i].replace("am", "").replace("pm", "")}
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <div className="flex items-center gap-3 pt-2 border-t border-phantom-border/40">
              <span className="text-[10px] text-phantom-ghost uppercase tracking-wider">Intensity:</span>
              {["Cold", "Low", "Med", "Hot"].map((l, i) => (
                <div key={l} className="flex items-center gap-1">
                  <div className={cn("w-3 h-3 rounded", HEAT_COLORS[i].split(" ")[0])} />
                  <span className="text-[10px] text-phantom-ghost">{l}</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
