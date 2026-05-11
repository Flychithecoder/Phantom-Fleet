"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * Live action stream — the "firehose" view of every action executing
 * across the fleet. Connects to /ws/fleet (BackgroundWorker broadcasts
 * every completed action). Falls back to synthetic demo events when the
 * WebSocket is unavailable (local dev / backend offline).
 */

type ActionKind =
  | "follow" | "unfollow" | "like" | "story_view" | "comment"
  | "send_dm" | "post" | "scroll" | "subscribe" | "upvote"
  | "submit_post" | "join" | "get_posts";

type StreamEvent = {
  id: string;
  kind: ActionKind;
  account: string;
  account_id?: string;
  phone: string;
  platform: string;
  success: boolean;
  ts: number;
};

const KIND_STYLES: Record<string, { label: string; color: string }> = {
  follow:      { label: "follow",      color: "text-phantom-accent" },
  unfollow:    { label: "unfollow",    color: "text-phantom-ghost" },
  like:        { label: "like",        color: "text-phantom-alive" },
  story_view:  { label: "story view",  color: "text-phantom-magenta" },
  comment:     { label: "comment",     color: "text-phantom-amber" },
  send_dm:     { label: "dm",          color: "text-phantom-accent" },
  post:        { label: "post",        color: "text-phantom-alive" },
  scroll:      { label: "scroll",      color: "text-phantom-ghost" },
  subscribe:   { label: "subscribe",   color: "text-phantom-accent" },
  upvote:      { label: "upvote",      color: "text-phantom-alive" },
  submit_post: { label: "post",        color: "text-phantom-alive" },
  join:        { label: "join",        color: "text-phantom-accent" },
  get_posts:   { label: "scrape",      color: "text-phantom-ghost" },
};

// Fallback synthetic events for demo / backend-offline mode
const DEMO_ACCOUNTS = [
  "tatiannalifee", "tatianamusee", "tatianazenn", "tatianapowerr",
  "melodieeeprincesss", "melodieeedream", "cutie.melodieee",
  "hackerhoneytatii", "codefairytatii", "softiemelodieee",
];
const DEMO_PHONES = ["RF8N81XYX4J", "RF8N90FZ0LV", "RF8N61Z9FZB", "RF8N71RBF2H", "RF8N50EM1WK"];
const DEMO_KINDS: ActionKind[] = ["follow", "like", "story_view", "comment", "send_dm"];

function makeDemoEvent(): StreamEvent {
  return {
    id: Math.random().toString(36).slice(2, 10),
    kind: DEMO_KINDS[Math.floor(Math.random() * DEMO_KINDS.length)],
    account: DEMO_ACCOUNTS[Math.floor(Math.random() * DEMO_ACCOUNTS.length)],
    phone: DEMO_PHONES[Math.floor(Math.random() * DEMO_PHONES.length)],
    platform: "instagram",
    success: true,
    ts: Date.now(),
  };
}

// WS_URL derived in useEffect (client-only) so SSR never touches window.
// Port 8002 = phantomfleet-backend host mapping (8000/8001 taken by Reddit panel).

export function ActionStream() {
  // Start empty — populated client-side in useEffect to avoid SSR/hydration mismatch.
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const demoTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Seed with demo events immediately on mount (client-only, safe from hydration).
    setEvents(Array.from({ length: 8 }, makeDemoEvent));

    const WS_URL = `ws://${window.location.hostname}:8002/ws/fleet`;
    let ws: WebSocket;
    let pingInterval: ReturnType<typeof setInterval>;

    const connect = () => {
      try {
        ws = new WebSocket(WS_URL);
        wsRef.current = ws;

        ws.onopen = () => {
          setConnected(true);
          // Stop demo events once real data flows
          if (demoTimerRef.current) {
            clearInterval(demoTimerRef.current);
            demoTimerRef.current = null;
          }
          // Keep-alive ping every 25s
          pingInterval = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) ws.send("ping");
          }, 25_000);
        };

        ws.onmessage = (msg) => {
          try {
            const raw = JSON.parse(msg.data as string);
            if (raw.type !== "action") return;
            const e: StreamEvent = {
              id: `${raw.account_id}-${raw.ts_iso}`,
              kind: (raw.action ?? "follow") as ActionKind,
              account: raw.account_id ?? "—",
              account_id: raw.account_id,
              phone: raw.phone ?? "—",
              platform: raw.platform ?? "instagram",
              success: raw.success ?? true,
              ts: Date.now(),
            };
            setEvents((prev) => [e, ...prev].slice(0, 20));
          } catch {
            // Ignore malformed frames
          }
        };

        ws.onclose = () => {
          setConnected(false);
          clearInterval(pingInterval);
          // Restart demo events as fallback
          if (!demoTimerRef.current) {
            demoTimerRef.current = setInterval(() => {
              setEvents((prev) => [makeDemoEvent(), ...prev].slice(0, 20));
            }, 1_300);
          }
          // Reconnect after 5s
          setTimeout(connect, 5_000);
        };

        ws.onerror = () => ws.close();
      } catch {
        // WebSocket not available (SSR / blocked) — stay in demo mode
      }
    };

    connect();

    // Demo fallback while connecting
    demoTimerRef.current = setInterval(() => {
      if (!connected) {
        setEvents((prev) => [makeDemoEvent(), ...prev].slice(0, 20));
      }
    }, 1_300);

    return () => {
      wsRef.current?.close();
      if (demoTimerRef.current) clearInterval(demoTimerRef.current);
      clearInterval(pingInterval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="phantom-panel flex flex-col h-full max-h-[520px]">
      <div className="p-6 border-b border-phantom-border flex items-center justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Action stream · firehose
          </div>
          <div className="text-lg font-display font-semibold mt-1">Live fleet activity</div>
        </div>
        <span
          className={cn(
            "phantom-dot animate-phantom-pulse",
            connected ? "phantom-dot-accent" : "phantom-dot-amber"
          )}
        />
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-1.5">
        {events.map((e, idx) => {
          const style = KIND_STYLES[e.kind] ?? { label: e.kind, color: "text-phantom-ghost" };
          const opacity = 1 - idx * 0.05;
          return (
            <div
              key={e.id}
              className="flex items-baseline gap-3 text-xs font-mono py-0.5 transition-opacity"
              style={{ opacity: Math.max(0.3, opacity) }}
            >
              <span className={cn("font-semibold w-20 shrink-0", style.color)}>
                {style.label}
              </span>
              <span className="text-white truncate">@{e.account}</span>
              <span className="text-phantom-ghost/50 text-[10px] shrink-0">{e.platform}</span>
              {!e.success && (
                <span className="text-red-400 text-[10px] shrink-0">✗</span>
              )}
              <span className="ml-auto text-phantom-ghost/60 text-[10px]">{e.phone.slice(-6)}</span>
            </div>
          );
        })}
      </div>
      <div className="px-6 py-3 border-t border-phantom-border text-[10px] text-phantom-ghost flex justify-between">
        <span>{connected ? "live · real-time" : "demo mode"}</span>
        <span>showing last 20 events</span>
      </div>
    </div>
  );
}
