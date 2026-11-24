"use client";
/**
 * Mirroring → Phone Wall: the full Fleet Mirror wall inside Phantom Fleet (every phone on every host PC:
 * tiles, large view, control, drag-select, sync, batch tools, sliders, tabs, tags, dialogs), in Phantom
 * Fleet's style. The backend mints a one-time link with the Fleet Mirror "ui" key; the key never reaches the
 * browser. Phones outside that key's "may control" list are view-only here.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Expand, MonitorSmartphone, RefreshCw, Shrink } from "lucide-react";
import { cn } from "@/lib/utils";

type State = "connecting" | "loading" | "live" | "error";

export default function PhoneWallPage() {
  const [url, setUrl] = useState<string | null>(null);
  const [state, setState] = useState<State>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [full, setFull] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setUrl(null); setError(null); setState("connecting");
    try {
      const r = await fetch("/api/fleet-mirror/embed-wall?minutes=480", { cache: "no-store" });
      if (!r.ok) {
        let msg = `${r.status}`;
        try { const b = await r.json(); msg = b.detail || b.error || msg; } catch { /* keep status */ }
        throw new Error(msg);
      }
      setUrl((await r.json()).url); setState("loading");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e)); setState("error");
    }
  }, []);
  useEffect(() => { load(); }, [load, nonce]);

  useEffect(() => {
    const onFs = () => setFull(document.fullscreenElement === box.current);
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);
  const toggleFull = () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else box.current?.requestFullscreen().catch(() => {});
  };

  const dot = state === "live" ? "phantom-dot-alive" : state === "error" ? "phantom-dot-critical" : "phantom-dot-warning";

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">Mirroring</div>
          <h1 className="font-display text-3xl font-bold mt-1 tracking-tight flex items-center gap-3">
            <MonitorSmartphone className="w-8 h-8 text-phantom-accent" strokeWidth={1.5} />
            Phone Wall
            <span className={cn("phantom-dot ml-1", dot)} />
          </h1>
          <div className="text-xs text-phantom-ghost mt-1">
            Every phone on every host PC, live. Double-click a phone for the large view; select several to act on them together.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setNonce((n) => n + 1)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border bg-phantom-panelHi text-white border-phantom-border hover:bg-phantom-panelHi/80 transition-colors"
          >
            <RefreshCw className={cn("w-4 h-4", state === "connecting" && "animate-spin")} strokeWidth={1.75} />
            Reconnect
          </button>
          <button
            onClick={toggleFull}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border bg-phantom-accent/15 text-phantom-accent border-phantom-accent/30 hover:bg-phantom-accent/25 transition-colors"
          >
            {full ? <Shrink className="w-4 h-4" strokeWidth={1.75} /> : <Expand className="w-4 h-4" strokeWidth={1.75} />}
            {full ? "Exit full screen" : "Full screen"}
          </button>
        </div>
      </div>

      <div ref={box} className="phantom-panel relative overflow-hidden p-0" style={{ height: full ? "100vh" : "calc(100vh - 13rem)", minHeight: 560 }}>
        {url && (
          <iframe
            key={url}
            src={url}
            title="Fleet Mirror phone wall"
            onLoad={() => setState("live")}
            className={cn("absolute inset-0 w-full h-full border-0 transition-opacity duration-300", state === "live" ? "opacity-100" : "opacity-0")}
            style={{ background: "transparent", colorScheme: "dark" }}
            allow="clipboard-write; fullscreen"
            sandbox="allow-scripts allow-same-origin allow-downloads allow-forms allow-modals allow-popups"
          />
        )}
        {state !== "live" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 p-6 text-center">
            {state === "error" ? (
              <>
                <div className="w-12 h-12 rounded-xl border border-phantom-red/30 bg-phantom-red/10 flex items-center justify-center">
                  <AlertTriangle className="w-5 h-5 text-phantom-red" strokeWidth={1.75} />
                </div>
                <div>
                  <div className="text-sm font-medium text-white">Phone wall unavailable</div>
                  <div className="text-xs text-phantom-ghost mt-1 max-w-md break-words">{error}</div>
                </div>
              </>
            ) : (
              <>
                <div className="grid grid-cols-6 gap-2 w-[min(520px,70%)]">
                  {Array.from({ length: 12 }).map((_, i) => (
                    <div key={i} className="phantom-skeleton aspect-[9/18.5] rounded-lg" />
                  ))}
                </div>
                <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                  {state === "connecting" ? "Connecting to Fleet Mirror" : "Loading the wall"}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
