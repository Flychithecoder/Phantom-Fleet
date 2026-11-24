"use client";

import { useState, useEffect } from "react";
import { Panel } from "@/components/panel";
import { Image as ImageIcon } from "lucide-react";
import { cn } from "@/lib/utils";

type ContentItem = {
  id: string;
  type: "reel" | "story" | "post";
  persona: string;
  score: number;
  used: boolean;
  views: number;
};

// Deterministic fallback — no Math.random() (CLAUDE.md distribution discipline).
// Real values come from GET /api/content-vault; this seeds the page before the
// fetch returns and anchors the empty-backend state.
const FALLBACK_ITEMS: ContentItem[] = Array.from({ length: 12 }, (_, i) => ({
  id: `c${i}`,
  type: (i % 3 === 0 ? "reel" : i % 3 === 1 ? "story" : "post") as ContentItem["type"],
  persona: i % 2 === 0 ? "Tatiana" : "Melodie",
  // Deterministic score: 0.62..0.98 via a fixed hash on index
  score: 0.62 + ((i * 37) % 36) / 100,
  used: i < 4,
  // Deterministic views: index-derived, no Math.random
  views: 500 + ((i * 419) % 50) * 100,
}));

export default function ContentPage() {
  const [items, setItems] = useState<ContentItem[]>(FALLBACK_ITEMS);
  const [pending, setPending] = useState<number>(47);
  const [weekly, setWeekly] = useState<number>(12);

  useEffect(() => {
    fetch("/api/content-vault/items?limit=12")
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((d) => {
        if (d?.items?.length) {
          setItems(d.items.map((raw: Record<string, unknown>) => ({
            id: String(raw.id ?? raw.content_id ?? ""),
            type: (raw.type as ContentItem["type"]) ?? "post",
            persona: String(raw.persona ?? "—"),
            score: Number(raw.score ?? raw.fit_score ?? 0),
            used: Boolean(raw.used ?? false),
            views: Number(raw.views ?? 0),
          })));
        }
        if (typeof d?.pending === "number") setPending(d.pending);
        if (typeof d?.this_week === "number") setWeekly(d.this_week);
      })
      .catch(() => {});
  }, []);

  return (
    <div className="space-y-8">
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Creative ops
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <ImageIcon className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          Content <span className="phantom-accent-text">Vault</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Pulled from the Scaler Pro Content Vault. Per-persona fit-scored, per-post caption generated,
          per-post metadata spoofed before upload. No hashtags. No LLM tells.
        </p>
      </div>

      <Panel
        label="vault queue"
        title={`${pending} items pending · ${weekly} items this week`}
      >
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {items.map((c) => (
            <div key={c.id} className="phantom-panel-hi rounded-lg overflow-hidden group cursor-pointer hover:scale-[1.02] transition-transform">
              <div className="aspect-[9/16] bg-gradient-to-br from-phantom-magenta/20 via-phantom-accent/10 to-transparent flex items-center justify-center relative">
                <ImageIcon className="w-10 h-10 text-phantom-ghost/30" strokeWidth={1.2} />
                <div className="absolute top-2 left-2">
                  <span className={cn(
                    "text-[9px] font-mono tracking-wider px-2 py-0.5 rounded-md border",
                    c.type === "reel" && "bg-phantom-accent/20 text-phantom-accent border-phantom-accent/30",
                    c.type === "story" && "bg-phantom-magenta/20 text-phantom-magenta border-phantom-magenta/30",
                    c.type === "post" && "bg-phantom-amber/20 text-phantom-amber border-phantom-amber/30",
                  )}>
                    {c.type.toUpperCase()}
                  </span>
                </div>
                {c.used && (
                  <div className="absolute top-2 right-2 text-[9px] font-mono text-phantom-alive bg-phantom-alive/10 border border-phantom-alive/30 px-1.5 py-0.5 rounded">
                    USED
                  </div>
                )}
              </div>
              <div className="p-2.5">
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-phantom-ghost">{c.persona}</span>
                  <span className="font-mono tabular-nums text-phantom-accent">
                    {Math.round(c.score * 100)}
                  </span>
                </div>
                <div className="text-[10px] text-phantom-ghost mt-1">
                  {c.views.toLocaleString()} views
                </div>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
