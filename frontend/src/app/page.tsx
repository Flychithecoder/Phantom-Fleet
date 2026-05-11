"use client";

import { useEffect, useRef, useState } from "react";
import { KPICard } from "@/components/kpi-card";
import { FleetGrid } from "@/components/fleet-grid";
import { AgentFeed } from "@/components/agent-feed";
import { ClusterHeatmap } from "@/components/cluster-heatmap";
import { RevenueChart } from "@/components/revenue-chart";
import { ActionStream } from "@/components/action-stream";
import { Panel } from "@/components/panel";
import { cn } from "@/lib/utils";

// ─── Live Fleet Activity ──────────────────────────────────────────────────────

type ActionType = "follow" | "like" | "comment" | "dm";

type FleetEvent = {
  id: string;
  type: ActionType;
  account: string;
  text: string;
  time: string;
};

const DEMO_EVENTS: Omit<FleetEvent, "id">[] = [
  { type: "follow",  account: "@tatiana_xo44",   text: "followed @jordanfit92",              time: "just now" },
  { type: "like",    account: "@melodie_life",    text: "liked 3 posts from @brookefit",      time: "2s ago" },
  { type: "dm",      account: "@tatiana_sunx",    text: "sent DM → stage 2",                  time: "5s ago" },
  { type: "follow",  account: "@kira_glow22",     text: "followed @yogatanya_la",             time: "8s ago" },
  { type: "like",    account: "@daisy_vibesxx",   text: "liked 2 posts from @fitlife_brooke", time: "11s ago" },
  { type: "comment", account: "@noelle_rune",     text: "commented on @laurenfit_ reel",      time: "14s ago" },
  { type: "dm",      account: "@melodie_xo",      text: "sent DM → stage 1",                  time: "17s ago" },
  { type: "follow",  account: "@piper_aura",      text: "followed @sunsetswithsara",          time: "20s ago" },
  { type: "like",    account: "@vivienne_co",     text: "liked 4 posts from @nycfitgirl",     time: "23s ago" },
  { type: "dm",      account: "@tatiana_xo44",    text: "received reply — stage 3 triggered", time: "26s ago" },
  { type: "follow",  account: "@leila_xox3",      text: "followed @allisonlifts",             time: "30s ago" },
  { type: "comment", account: "@kira_glow22",     text: "commented on @miafitnessco post",    time: "34s ago" },
  { type: "like",    account: "@noelle_rune",     text: "liked 3 posts from @heather_gains",  time: "38s ago" },
  { type: "follow",  account: "@daisy_vibesxx",   text: "followed @carolinegirlboss",         time: "42s ago" },
  { type: "dm",      account: "@melodie_life",    text: "sent DM → stage 1",                  time: "46s ago" },
];

function typeDotClass(type: ActionType): string {
  switch (type) {
    case "follow":  return "bg-phantom-accent shadow-[0_0_6px_hsl(162_100%_54%/0.6)]";
    case "like":    return "bg-phantom-alive  shadow-[0_0_6px_hsl(120_100%_50%/0.4)]";
    case "comment": return "bg-phantom-amber  shadow-[0_0_6px_hsl(38_100%_60%/0.4)]";
    case "dm":      return "bg-phantom-magenta shadow-[0_0_6px_hsl(290_100%_70%/0.4)]";
  }
}

function typeLabel(type: ActionType): string {
  switch (type) {
    case "follow":  return "follow";
    case "like":    return "like";
    case "comment": return "comment";
    case "dm":      return "dm";
  }
}

function LiveActivityFeed() {
  const [events, setEvents] = useState<FleetEvent[]>([]);
  const [isLive, setIsLive] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const demoIndexRef = useRef(0);
  const demoIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  function prependEvent(evt: Omit<FleetEvent, "id">) {
    const newEvent: FleetEvent = {
      ...evt,
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    };
    setEvents((prev) => [newEvent, ...prev].slice(0, 20));
  }

  function startDemo() {
    if (demoIntervalRef.current) return;
    // Seed with a few initial events immediately
    const seed = DEMO_EVENTS.slice(0, 5);
    seed.forEach((e) => {
      setEvents((prev) => [
        { ...e, id: `seed-${Math.random().toString(36).slice(2, 7)}` },
        ...prev,
      ].slice(0, 20));
    });
    demoIndexRef.current = 5 % DEMO_EVENTS.length;

    demoIntervalRef.current = setInterval(() => {
      const evt = DEMO_EVENTS[demoIndexRef.current % DEMO_EVENTS.length];
      demoIndexRef.current = (demoIndexRef.current + 1) % DEMO_EVENTS.length;
      prependEvent(evt);
    }, 2500);
  }

  function stopDemo() {
    if (demoIntervalRef.current) {
      clearInterval(demoIntervalRef.current);
      demoIntervalRef.current = null;
    }
  }

  useEffect(() => {
    function connectWs() {
      try {
        const ws = new WebSocket("ws://localhost:8001/ws/fleet");
        wsRef.current = ws;

        ws.onopen = () => {
          setIsLive(true);
          stopDemo();
        };

        ws.onmessage = (e) => {
          try {
            const data = JSON.parse(e.data) as Omit<FleetEvent, "id">;
            prependEvent(data);
          } catch {
            // ignore malformed frames
          }
        };

        ws.onerror = () => {
          setIsLive(false);
          ws.close();
        };

        ws.onclose = () => {
          setIsLive(false);
          wsRef.current = null;
          startDemo();
        };
      } catch {
        // WebSocket not available (SSR or blocked)
        setIsLive(false);
        startDemo();
      }
    }

    connectWs();

    return () => {
      stopDemo();
      wsRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Panel
      label="live fleet activity"
      title="Fleet Activity Feed"
      subtitle="Real-time action stream from all 219 accounts across all platforms."
      actions={
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-mono tracking-wider border",
              isLive
                ? "bg-phantom-alive/10 text-phantom-alive border-phantom-alive/30"
                : "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/30",
            )}
          >
            <span
              className={cn(
                "w-1.5 h-1.5 rounded-full flex-shrink-0",
                isLive ? "bg-phantom-alive animate-pulse" : "bg-phantom-amber animate-pulse",
              )}
            />
            {isLive ? "LIVE" : "DEMO"}
          </span>
        </div>
      }
    >
      <div
        ref={scrollRef}
        className="max-h-64 overflow-y-auto space-y-1 pr-1 scrollbar-thin scrollbar-thumb-phantom-border scrollbar-track-transparent"
      >
        {events.length === 0 && (
          <div className="flex items-center justify-center h-20 text-phantom-ghost text-sm">
            Connecting to fleet...
          </div>
        )}
        {events.map((evt) => (
          <div
            key={evt.id}
            className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-phantom-panelHi/30 transition-colors group"
          >
            {/* Action type dot */}
            <span
              className={cn(
                "w-2 h-2 rounded-full flex-shrink-0",
                typeDotClass(evt.type),
              )}
            />
            {/* Type label */}
            <span className="text-[10px] font-mono uppercase tracking-wider text-phantom-ghost w-14 flex-shrink-0">
              {typeLabel(evt.type)}
            </span>
            {/* Account */}
            <span className="font-mono text-xs text-phantom-accent w-32 flex-shrink-0 truncate">
              {evt.account}
            </span>
            {/* Description */}
            <span className="text-xs text-phantom-ghost flex-1 truncate">
              {evt.text}
            </span>
            {/* Time */}
            <span className="text-[10px] font-mono text-phantom-ghost/60 flex-shrink-0 w-16 text-right">
              {evt.time}
            </span>
          </div>
        ))}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-5 mt-4 pt-4 border-t border-phantom-border">
        {(["follow", "like", "comment", "dm"] as ActionType[]).map((type) => (
          <div key={type} className="flex items-center gap-1.5">
            <span className={cn("w-2 h-2 rounded-full flex-shrink-0", typeDotClass(type))} />
            <span className="text-[10px] font-mono text-phantom-ghost capitalize">{type}</span>
          </div>
        ))}
        <div className="ml-auto text-[10px] font-mono text-phantom-ghost">
          {isLive ? "ws://localhost:8001/ws/fleet" : "demo mode · WebSocket offline"}
        </div>
      </div>
    </Panel>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function OverviewPage() {
  return (
    <div className="space-y-8">
      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Command center
          </div>
          <h1 className="font-display text-4xl font-bold mt-2 tracking-tight">
            Fleet <span className="phantom-accent-text">Overview</span>
          </h1>
          <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
            Invisible automation at fleet scale. 19 devices, 219 accounts, 14 autonomous agents.
            All phones simultaneous, all ranges LogNormal-sampled, all fingerprints cluster-audited.
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-2">
            <span className="phantom-dot phantom-dot-alive animate-phantom-pulse" />
            <span className="text-xs text-phantom-ghost">All systems operational</span>
          </div>
          <div className="text-[10px] text-phantom-ghost font-mono">
            audit_harness · last pass 2h ago · 10,000 synthetic personas · PASSED
          </div>
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          label="Active accounts"
          value="219"
          delta={0.023}
          sub="Tatiana 97 · Melodie 122"
          accent
        />
        <KPICard
          label="Fresh targets today"
          value="4,280"
          delta={0.112}
          sub="2,140 Tatiana · 2,140 Melodie"
        />
        <KPICard
          label="Actions today"
          value="4,512"
          delta={0.086}
          sub="~22 per account · within curve"
        />
        <KPICard
          label="Account survival (30d)"
          value="99.4%"
          delta={0.001}
          sub="1 of 219 suspended"
        />
      </div>

      {/* Fleet map — full width */}
      <FleetGrid />

      {/* Cluster heatmap + Agent feed */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <ClusterHeatmap />
        </div>
        <div>
          <AgentFeed />
        </div>
      </div>

      {/* Live action stream — firehose */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <RevenueChart />
        </div>
        <div>
          <ActionStream />
        </div>
      </div>

      {/* Live Fleet Activity WebSocket feed */}
      <LiveActivityFeed />
    </div>
  );
}
