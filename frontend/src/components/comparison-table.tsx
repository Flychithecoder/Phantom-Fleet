import { Check, X } from "lucide-react";
import { cn } from "@/lib/utils";

const ROWS: Array<{ category: string; feature: string; onimator: string | boolean; phantom: string | boolean }> = [
  { category: "Execution", feature: "Real-device automation",                 onimator: true,  phantom: true },
  { category: "Execution", feature: "Native Kotlin Accessibility Service",    onimator: false, phantom: true },
  { category: "Execution", feature: "5-10x faster tap / type primitives",     onimator: false, phantom: true },
  { category: "Execution", feature: "Bezier-curve swipes",                    onimator: false, phantom: true },

  { category: "Anti-detect", feature: "Live fleet cluster monitoring",        onimator: false, phantom: true },
  { category: "Anti-detect", feature: "10K-persona Monte Carlo CI gate",      onimator: false, phantom: true },
  { category: "Anti-detect", feature: "20-dim fingerprint audit",             onimator: false, phantom: true },
  { category: "Anti-detect", feature: "LogNormal distribution sampling",      onimator: "partial", phantom: true },
  { category: "Anti-detect", feature: "LLM detection-tell filter on captions",onimator: false, phantom: true },
  { category: "Anti-detect", feature: "Cross-field contradiction detection",  onimator: false, phantom: true },

  { category: "Persona",   feature: "Cross-platform persona primitive",       onimator: false, phantom: true },
  { category: "Persona",   feature: "Per-persona biometric profile",          onimator: false, phantom: true },
  { category: "Persona",   feature: "Account replacement preserves persona",  onimator: false, phantom: true },

  { category: "Agents",    feature: "AI Chat Agent",                          onimator: true,  phantom: true },
  { category: "Agents",    feature: "Source Discovery Agent (auto)",          onimator: false, phantom: true },
  { category: "Agents",    feature: "Fresh Target Agent (90d dedup)",         onimator: false, phantom: true },
  { category: "Agents",    feature: "Fingerprint Monitor Agent",              onimator: false, phantom: true },
  { category: "Agents",    feature: "Recovery + Replacement Agents",          onimator: false, phantom: true },
  { category: "Agents",    feature: "Funnel Conversion Agent",                onimator: false, phantom: true },
  { category: "Agents",    feature: "Growth Strategy Agent (weekly KPI)",     onimator: false, phantom: true },

  { category: "Targeting", feature: "Static scraped target pool",             onimator: true,  phantom: false },
  { category: "Targeting", feature: "Fresh daily targets",                    onimator: false, phantom: true },
  { category: "Targeting", feature: "Auto source-discovery",                  onimator: false, phantom: true },
  { category: "Targeting", feature: "Zero hashtag usage",                     onimator: false, phantom: true },

  { category: "Platform",  feature: "Instagram",                              onimator: true,  phantom: true },
  { category: "Platform",  feature: "TikTok",                                 onimator: true,  phantom: "Phase 2" },
  { category: "Platform",  feature: "Reddit",                                 onimator: true,  phantom: "Phase 2" },
  { category: "Platform",  feature: "Threads",                                onimator: true,  phantom: "Phase 2" },
  { category: "Platform",  feature: "Snapchat",                               onimator: true,  phantom: "Phase 3" },
  { category: "Platform",  feature: "Tinder / Bumble",                        onimator: "broken", phantom: "Phase 3" },

  { category: "Attribution", feature: "Link-click attribution per persona",   onimator: false, phantom: true },
  { category: "Attribution", feature: "Conversion attribution (any funnel)",  onimator: false, phantom: true },
  { category: "Attribution", feature: "Multi-destination support (store / sub / lead / etc.)", onimator: false, phantom: true },
  { category: "Attribution", feature: "Per-persona ROI tracking",             onimator: false, phantom: true },

  { category: "Ops",       feature: "Event-sourced audit log",                onimator: false, phantom: true },
  { category: "Ops",       feature: "Self-hosted, no kill switch",            onimator: false, phantom: true },
  { category: "Ops",       feature: "Multi-tenant white-label",               onimator: false, phantom: "Phase 3" },
  { category: "Ops",       feature: "Modern Next.js dashboard",               onimator: false, phantom: true },
];

function Cell({ value }: { value: string | boolean }) {
  if (value === true) {
    return <Check className="w-4 h-4 text-phantom-accent mx-auto" strokeWidth={2.5} />;
  }
  if (value === false) {
    return <X className="w-4 h-4 text-phantom-ghost/40 mx-auto" strokeWidth={2} />;
  }
  // string
  const isPhase = typeof value === "string" && value.startsWith("Phase");
  const isBroken = value === "broken";
  const isPartial = value === "partial";
  return (
    <span className={cn(
      "text-[10px] font-mono tracking-wider px-2 py-0.5 rounded-md border",
      isPhase && "text-phantom-accent bg-phantom-accent/10 border-phantom-accent/30",
      isBroken && "text-phantom-red bg-phantom-red/10 border-phantom-red/30",
      isPartial && "text-phantom-amber bg-phantom-amber/10 border-phantom-amber/30",
      !isPhase && !isBroken && !isPartial && "text-phantom-ghost",
    )}>
      {value.toUpperCase()}
    </span>
  );
}

export function ComparisonTable() {
  let currentCategory = "";
  return (
    <div className="phantom-panel overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-phantom-border">
            <th className="px-6 py-4 text-left text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
              Feature
            </th>
            <th className="px-6 py-4 text-center text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium w-[180px]">
              Onimator
            </th>
            <th className="px-6 py-4 text-center text-[10px] uppercase tracking-[0.15em] font-medium w-[180px] bg-phantom-accent/5">
              <span className="phantom-accent-text">Phantom Fleet</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row, i) => {
            const showCategoryHeader = row.category !== currentCategory;
            currentCategory = row.category;
            return (
              <>
                {showCategoryHeader && (
                  <tr key={`cat-${i}`}>
                    <td colSpan={3} className="px-6 pt-6 pb-2">
                      <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                        {row.category}
                      </div>
                    </td>
                  </tr>
                )}
                <tr key={i} className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/20">
                  <td className="px-6 py-3 text-sm">{row.feature}</td>
                  <td className="px-6 py-3 text-center"><Cell value={row.onimator} /></td>
                  <td className="px-6 py-3 text-center bg-phantom-accent/5"><Cell value={row.phantom} /></td>
                </tr>
              </>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
