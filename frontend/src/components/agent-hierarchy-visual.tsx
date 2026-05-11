"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

type Node = {
  id: string;
  label: string;
  sublabel?: string;
  tier: 0 | 1 | 2;
  col: number; // 0-indexed column within the tier
  totalCols: number;
};

const NODES: Node[] = [
  // Tier 0 — Chief
  { id: "chief", label: "Chief Agent", sublabel: "Gameplan + KPI arbiter", tier: 0, col: 0, totalCols: 1 },

  // Tier 1 — Platform Managers
  { id: "ig",       label: "IG Manager",       sublabel: "Instagram + Threads", tier: 1, col: 0, totalCols: 5 },
  { id: "reddit",   label: "Reddit Manager",   sublabel: "Subreddit fleet",     tier: 1, col: 1, totalCols: 5 },
  { id: "x",        label: "X Manager",        sublabel: "X / Twitter fleet",   tier: 1, col: 2, totalCols: 5 },
  { id: "tt",       label: "TikTok Manager",   sublabel: "Short-form video",    tier: 1, col: 3, totalCols: 5 },
  { id: "chat",     label: "Chat Manager",     sublabel: "DM + dating apps",    tier: 1, col: 4, totalCols: 5 },

  // Tier 2 — Specialists
  { id: "warm",     label: "Warming",          sublabel: "Account warming",     tier: 2, col: 0,  totalCols: 8 },
  { id: "target",   label: "Targeting",        sublabel: "Fresh daily targets", tier: 2, col: 1,  totalCols: 8 },
  { id: "content",  label: "Content",          sublabel: "Caption + media",     tier: 2, col: 2,  totalCols: 8 },
  { id: "finger",   label: "Fingerprint",      sublabel: "Cluster monitor",     tier: 2, col: 3,  totalCols: 8 },
  { id: "proxy",    label: "Proxy",            sublabel: "Rotation + cycling",  tier: 2, col: 4,  totalCols: 8 },
  { id: "recovery", label: "Recovery",         sublabel: "Account repair",      tier: 2, col: 5,  totalCols: 8 },
  { id: "funnel",   label: "Funnel",           sublabel: "Conversion track",    tier: 2, col: 6,  totalCols: 8 },
  { id: "audit",    label: "Audit",            sublabel: "CI gate + logs",      tier: 2, col: 7,  totalCols: 8 },
];

const EDGES: Array<[string, string]> = [
  ["chief", "ig"],
  ["chief", "reddit"],
  ["chief", "x"],
  ["chief", "tt"],
  ["chief", "chat"],
  ["ig", "warm"],
  ["ig", "content"],
  ["reddit", "target"],
  ["reddit", "content"],
  ["x", "content"],
  ["x", "proxy"],
  ["tt", "warm"],
  ["tt", "content"],
  ["chat", "funnel"],
  ["chief", "finger"],
  ["chief", "recovery"],
  ["chief", "audit"],
];

function getTierColor(tier: Node["tier"]) {
  if (tier === 0) return "hsl(162 100% 54%)";
  if (tier === 1) return "hsl(200 100% 56%)";
  return "hsl(240 5% 64.9%)";
}

function getTierBg(tier: Node["tier"]) {
  if (tier === 0) return "bg-phantom-accent/10 border-phantom-accent/40 text-white";
  if (tier === 1) return "bg-[hsl(200_100%_56%/0.1)] border-[hsl(200_100%_56%/0.35)] text-white";
  return "bg-phantom-panelHi border-phantom-border text-phantom-ghost";
}

export function AgentHierarchyVisual({ className }: { className?: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [nodePositions, setNodePositions] = useState<Record<string, { cx: number; cy: number }>>({});

  // After mount, measure node positions relative to the container
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const positions: Record<string, { cx: number; cy: number }> = {};
    NODES.forEach((n) => {
      const el = container.querySelector<HTMLElement>(`[data-node-id="${n.id}"]`);
      if (!el) return;
      const r = el.getBoundingClientRect();
      const cr = container.getBoundingClientRect();
      positions[n.id] = {
        cx: r.left - cr.left + r.width / 2,
        cy: r.top - cr.top + r.height / 2,
      };
    });
    setNodePositions(positions);
  });

  const isHighlighted = (id: string) => {
    if (!hoveredId) return false;
    return (
      id === hoveredId ||
      EDGES.some(([a, b]) => (a === hoveredId && b === id) || (b === hoveredId && a === id))
    );
  };

  return (
    <div
      ref={containerRef}
      className={cn("relative phantom-panel p-8 overflow-hidden", className)}
    >
      {/* SVG edges layer */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none"
        style={{ zIndex: 0 }}
      >
        <defs>
          <marker id="arrowhead" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill="hsl(162 100% 54% / 0.4)" />
          </marker>
        </defs>
        {EDGES.map(([a, b]) => {
          const pa = nodePositions[a];
          const pb = nodePositions[b];
          if (!pa || !pb) return null;
          const highlighted = hoveredId
            ? a === hoveredId || b === hoveredId
            : false;
          return (
            <line
              key={`${a}-${b}`}
              x1={pa.cx}
              y1={pa.cy}
              x2={pb.cx}
              y2={pb.cy}
              stroke={highlighted ? "hsl(162 100% 54% / 0.7)" : "hsl(240 6% 18% / 0.8)"}
              strokeWidth={highlighted ? 1.5 : 0.8}
              strokeDasharray={highlighted ? undefined : "4 4"}
              markerEnd="url(#arrowhead)"
              style={{ transition: "stroke 0.2s, stroke-width 0.2s" }}
            />
          );
        })}
      </svg>

      {/* Tier rows */}
      <div className="relative" style={{ zIndex: 1 }}>
        {/* Tier labels */}
        {[
          { tier: 0, label: "Chief Agent", desc: "Owns the gameplan" },
          { tier: 1, label: "Platform Managers", desc: "Per-platform orchestration" },
          { tier: 2, label: "Specialists", desc: "Domain-specific execution" },
        ].map(({ tier, label, desc }) => {
          const tierNodes = NODES.filter((n) => n.tier === tier);
          return (
            <div key={tier} className={cn("mb-10", tier < 2 && "")}>
              {/* Row header */}
              <div className="flex items-center gap-3 mb-4">
                <div
                  className="text-[9px] uppercase tracking-[0.15em] font-mono px-2 py-0.5 rounded border"
                  style={{
                    color: getTierColor(tier as Node["tier"]),
                    borderColor: `${getTierColor(tier as Node["tier"])}40`,
                    backgroundColor: `${getTierColor(tier as Node["tier"])}10`,
                  }}
                >
                  Tier {tier}
                </div>
                <div className="text-xs font-display font-semibold">{label}</div>
                <div className="text-xs text-phantom-ghost">&mdash; {desc}</div>
              </div>

              {/* Node row */}
              <div
                className={cn(
                  "flex gap-3",
                  tier === 0 && "justify-center",
                  tier === 1 && "justify-center",
                  tier === 2 && "flex-wrap justify-center"
                )}
              >
                {tierNodes.map((n) => (
                  <button
                    key={n.id}
                    data-node-id={n.id}
                    onMouseEnter={() => setHoveredId(n.id)}
                    onMouseLeave={() => setHoveredId(null)}
                    className={cn(
                      "relative px-4 py-3 rounded-lg border text-left transition-all cursor-default",
                      tier === 0 && "min-w-[180px]",
                      tier === 1 && "min-w-[130px]",
                      tier === 2 && "min-w-[110px]",
                      getTierBg(n.tier),
                      isHighlighted(n.id) &&
                        "border-phantom-accent/60 shadow-[0_0_16px_hsl(162_100%_54%/0.2)]",
                      hoveredId && !isHighlighted(n.id) && "opacity-30"
                    )}
                  >
                    {/* Glow dot */}
                    {n.tier === 0 && (
                      <span className="absolute top-2 right-2 phantom-dot phantom-dot-accent animate-phantom-pulse" />
                    )}
                    <div className="font-display font-semibold text-sm">{n.label}</div>
                    {n.sublabel && (
                      <div className="text-[10px] text-phantom-ghost mt-0.5">{n.sublabel}</div>
                    )}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="mt-2 flex items-center gap-6 text-[10px] text-phantom-ghost font-mono border-t border-phantom-border pt-4">
        <span>Hover a node to trace connections</span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-4 border-t border-dashed border-phantom-border" />
          Inactive edge
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-4 border-t border-phantom-accent" />
          Active edge
        </span>
      </div>
    </div>
  );
}
