"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { CalendarDays, Clock, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";

type ContentType = "reel" | "story" | "post" | "thread" | "tiktok";
type Platform = "all" | "instagram" | "threads" | "tiktok" | "dating";

const TYPE_STYLES: Record<ContentType, { bg: string; text: string; border: string; label: string }> = {
  reel:   { bg: "bg-phantom-accent/20",  text: "text-phantom-accent",  border: "border-phantom-accent/30",  label: "Reel"   },
  story:  { bg: "bg-phantom-magenta/20", text: "text-phantom-magenta", border: "border-phantom-magenta/30", label: "Story"  },
  post:   { bg: "bg-phantom-alive/20",   text: "text-phantom-alive",   border: "border-phantom-alive/30",   label: "Post"   },
  thread: { bg: "bg-phantom-amber/20",   text: "text-phantom-amber",   border: "border-phantom-amber/30",   label: "Thread" },
  tiktok: { bg: "bg-blue-400/20",        text: "text-blue-400",        border: "border-blue-400/30",        label: "TikTok" },
};

const DAYS = [
  { label: "Mon", date: "Apr 14" }, { label: "Tue", date: "Apr 15" },
  { label: "Wed", date: "Apr 16" }, { label: "Thu", date: "Apr 17" },
  { label: "Fri", date: "Apr 18" }, { label: "Sat", date: "Apr 19" },
  { label: "Sun", date: "Apr 20" },
];

type CalEvent = { id: string; dayIndex: number; time: string; type: ContentType; platform: Platform; persona: string; accounts: number; preview: string; };

const EVENTS: CalEvent[] = [
  { id:"e1",  dayIndex:0, time:"7:00 AM",  type:"story",  platform:"instagram", persona:"Tatiana", accounts:47, preview:"Morning vibes" },
  { id:"e2",  dayIndex:0, time:"10:00 AM", type:"reel",   platform:"instagram", persona:"Melodie", accounts:22, preview:"GRWM: Monday reset" },
  { id:"e3",  dayIndex:0, time:"3:00 PM",  type:"thread", platform:"threads",   persona:"Tatiana", accounts:84, preview:"not me manifesting on a Mon" },
  { id:"e4",  dayIndex:0, time:"7:00 PM",  type:"tiktok", platform:"tiktok",    persona:"Tatiana", accounts:31, preview:"Night routine aesthetic" },
  { id:"e5",  dayIndex:1, time:"8:00 AM",  type:"post",   platform:"instagram", persona:"Melodie", accounts:19, preview:"Quote card: healing" },
  { id:"e6",  dayIndex:1, time:"12:00 PM", type:"reel",   platform:"tiktok",    persona:"Melodie", accounts:28, preview:"Lunch aesthetic" },
  { id:"e7",  dayIndex:1, time:"5:00 PM",  type:"story",  platform:"instagram", persona:"Tatiana", accounts:51, preview:"Poll: coffee or matcha?" },
  { id:"e8",  dayIndex:2, time:"9:00 AM",  type:"reel",   platform:"instagram", persona:"Tatiana", accounts:35, preview:"Soft morning routine" },
  { id:"e9",  dayIndex:2, time:"1:00 PM",  type:"thread", platform:"threads",   persona:"Melodie", accounts:91, preview:"the version of you 3 yrs ago" },
  { id:"e10", dayIndex:2, time:"6:00 PM",  type:"tiktok", platform:"tiktok",    persona:"Tatiana", accounts:24, preview:"Book review + vibe" },
  { id:"e11", dayIndex:2, time:"8:00 PM",  type:"post",   platform:"instagram", persona:"Melodie", accounts:16, preview:"Mood board: April aesthetic" },
  { id:"e12", dayIndex:3, time:"7:30 AM",  type:"story",  platform:"instagram", persona:"Tatiana", accounts:47, preview:"Thursday energy" },
  { id:"e13", dayIndex:3, time:"11:00 AM", type:"reel",   platform:"tiktok",    persona:"Melodie", accounts:33, preview:"Gym fit check" },
  { id:"e14", dayIndex:3, time:"4:00 PM",  type:"thread", platform:"threads",   persona:"Tatiana", accounts:76, preview:"the right person" },
  { id:"e15", dayIndex:4, time:"8:00 AM",  type:"reel",   platform:"instagram", persona:"Tatiana", accounts:40, preview:"Friday reset routine" },
  { id:"e16", dayIndex:4, time:"12:00 PM", type:"post",   platform:"instagram", persona:"Melodie", accounts:22, preview:"Weekend plans?" },
  { id:"e17", dayIndex:4, time:"7:00 PM",  type:"tiktok", platform:"tiktok",    persona:"Tatiana", accounts:29, preview:"Date night GRWM" },
  { id:"e18", dayIndex:4, time:"9:00 PM",  type:"thread", platform:"threads",   persona:"Melodie", accounts:88, preview:"Friday feelings" },
  { id:"e19", dayIndex:5, time:"10:00 AM", type:"reel",   platform:"instagram", persona:"Melodie", accounts:27, preview:"Weekend aesthetic" },
  { id:"e20", dayIndex:5, time:"2:00 PM",  type:"tiktok", platform:"tiktok",    persona:"Tatiana", accounts:31, preview:"Cozy day at home" },
  { id:"e21", dayIndex:5, time:"6:00 PM",  type:"story",  platform:"instagram", persona:"Tatiana", accounts:51, preview:"Saturday sunset" },
  { id:"e22", dayIndex:6, time:"9:00 AM",  type:"post",   platform:"instagram", persona:"Melodie", accounts:19, preview:"Sunday reset" },
  { id:"e23", dayIndex:6, time:"12:00 PM", type:"thread", platform:"threads",   persona:"Tatiana", accounts:82, preview:"healing is not linear" },
  { id:"e24", dayIndex:6, time:"5:00 PM",  type:"tiktok", platform:"tiktok",    persona:"Melodie", accounts:24, preview:"Week recap + gratitude" },
  { id:"e25", dayIndex:6, time:"8:00 PM",  type:"story",  platform:"instagram", persona:"Tatiana", accounts:47, preview:"Preparing for the week" },
];

export default function CalendarPage() {
  const [platformFilter, setPlatformFilter] = useState<Platform>("all");
  const filtered = platformFilter === "all" ? EVENTS : EVENTS.filter((e) => e.platform === platformFilter);
  const totalPosts = EVENTS.reduce((s, e) => s + e.accounts, 0);

  return (
    <div className="space-y-8">
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">Content calendar</div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <CalendarDays className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          Content <span className="phantom-accent-text">Calendar</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          7-day view of all scheduled content across Instagram, Threads, TikTok and dating platforms.
        </p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Scheduled This Week" value={String(EVENTS.length)} sub={totalPosts.toLocaleString() + " total posts"} />
        <KPICard label="Content Types" value="5" sub="reel, story, post, thread, tiktok" />
        <KPICard label="Next Post In" value="4 min" sub="Morning vibes" />
        <KPICard label="Peak Day" value="Wed" sub="11 items scheduled" />
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {(["all", "instagram", "threads", "tiktok", "dating"] as Platform[]).map((p) => (
          <button key={p} onClick={() => setPlatformFilter(p)}
            className={cn("px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors",
              platformFilter === p
                ? "bg-phantom-accent text-phantom-bg border-phantom-accent"
                : "text-phantom-ghost border-phantom-border bg-phantom-panelHi hover:text-white hover:border-phantom-accent/40")}>
            {p === "all" ? "All Platforms" : p.charAt(0).toUpperCase() + p.slice(1)}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-3">
          {(Object.entries(TYPE_STYLES) as [ContentType, (typeof TYPE_STYLES)[ContentType]][]).map(([key, val]) => (
            <span key={key} className={cn("flex items-center gap-1 text-[10px]", val.text)}>
              <span className={cn("w-2 h-2 rounded-sm inline-block", val.bg)} />
              {val.label}
            </span>
          ))}
        </div>
      </div>

      {/* 7-day grid */}
      <div className="phantom-panel overflow-hidden">
        <div className="px-5 py-3 border-b border-phantom-border">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">Week of Apr 14 to Apr 20, 2026</div>
        </div>
        <div className="grid grid-cols-7 divide-x divide-phantom-border">
          {DAYS.map((day, di) => {
            const dayEvents = filtered.filter((e) => e.dayIndex === di);
            return (
              <div key={day.label} className="min-h-[220px] p-2">
                <div className="text-center mb-2">
                  <div className="text-[10px] uppercase tracking-wider text-phantom-ghost">{day.label}</div>
                  <div className="text-xs text-white font-mono">{day.date}</div>
                </div>
                <div className="space-y-1">
                  {dayEvents.slice(0, 5).map((ev) => {
                    const s = TYPE_STYLES[ev.type];
                    return (
                      <div key={ev.id} className={cn("rounded px-1.5 py-1 cursor-pointer hover:opacity-75 transition-opacity", s.bg)}>
                        <div className={cn("text-[9px] font-mono", s.text)}>{ev.time}</div>
                        <div className="text-[10px] text-white truncate leading-tight mt-0.5">{ev.preview}</div>
                        <div className="text-[9px] text-phantom-ghost mt-0.5">{ev.accounts} accts</div>
                      </div>
                    );
                  })}
                  {dayEvents.length > 5 && <div className="text-[9px] text-center text-phantom-ghost">+{dayEvents.length - 5} more</div>}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Upcoming list */}
      <Panel label="upcoming" title="Next 10 Scheduled Posts">
        <div className="space-y-0">
          {EVENTS.slice(0, 10).map((ev) => {
            const s = TYPE_STYLES[ev.type];
            return (
              <div key={ev.id} className="flex items-center gap-3 py-2.5 border-b border-phantom-border/40 last:border-0">
                <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center shrink-0 text-[10px] font-bold", s.bg, s.text)}>
                  {s.label.slice(0, 1)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-white truncate">{ev.preview}</div>
                  <div className="text-[11px] text-phantom-ghost">{ev.persona} · {ev.accounts} accounts · {DAYS[ev.dayIndex].label} {DAYS[ev.dayIndex].date}</div>
                </div>
                <div className="flex items-center gap-1 text-xs font-mono text-phantom-ghost shrink-0">
                  <Clock className="w-3 h-3" />{ev.time}
                </div>
                <span className={cn("text-[10px] font-mono px-2 py-0.5 rounded border shrink-0", s.text, s.border, s.bg)}>
                  {s.label}
                </span>
                <CheckCircle2 className="w-4 h-4 text-phantom-ghost/30 shrink-0" />
              </div>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}