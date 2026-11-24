"use client";
/**
 * FleetMirrorView — a phone's live screen from the Fleet Mirror hub, in Phantom Fleet's design language.
 *
 *   <FleetMirrorView serial="R5CRC08L4QM" control={false} />
 *
 * The component asks Phantom Fleet's backend for a one-time embed link
 * (GET /api/fleet-mirror/embed?serial=…&control=0&theme=phantom); the backend asks the hub with its API key,
 * which never reaches the browser. The link works once and expires after 2 minutes, so a fresh one is
 * fetched on every mount and on "Reconnect". theme=phantom makes the hub page use Phantom Fleet's tokens
 * (dark panel, neon accent, 12px radius, Inter stack) on a transparent background.
 *
 * The browser must trust the hub's certificate once (Fleet Mirror docs: "Trusting the hub certificate").
 */
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, RefreshCw, Smartphone } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  serial: string;
  control?: boolean;            // allow taps/keys from this view (the hub must allow control for the phone)
  minutes?: number;             // how long the embedded session may stay open (1-720, default 60)
  height?: number;              // frame height in px
  endpoint?: string;            // backend route returning {url}
  className?: string;
};

type State = "connecting" | "loading" | "live" | "error";

const STATE_LABEL: Record<State, string> = {
  connecting: "CONNECTING",
  loading: "LOADING",
  live: "LIVE",
  error: "UNAVAILABLE",
};

export default function FleetMirrorView({
  serial, control = false, minutes = 60, height = 720, endpoint = "/api/fleet-mirror/embed", className,
}: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<State>("connecting");
  const [nonce, setNonce] = useState(0);

  const load = useCallback(async () => {
    setUrl(null); setError(null); setState("connecting");
    try {
      const q = new URLSearchParams({ serial, control: control ? "1" : "0", minutes: String(minutes), theme: "phantom" });
      const r = await fetch(`${endpoint}?${q}`, { cache: "no-store" });
      if (!r.ok) {
        let msg = `${r.status}`;
        try { const b = await r.json(); msg = b.detail || b.error || msg; } catch { /* keep status */ }
        throw new Error(msg);
      }
      const body = await r.json();
      setUrl(body.url); setState("loading");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e)); setState("error");
    }
  }, [serial, control, minutes, endpoint]);

  useEffect(() => { load(); }, [load, nonce]);

  const dot = state === "live" ? "phantom-dot-alive" : state === "error" ? "phantom-dot-critical" : "phantom-dot-warning";

  return (
    <div className={cn("space-y-3", className)}>
      <div className="relative rounded-xl border border-phantom-border bg-phantom-bg/60 overflow-hidden" style={{ height }}>
        {url && (
          <iframe
            key={url}
            src={url}
            title={`Fleet Mirror live screen ${serial}`}
            onLoad={() => setState("live")}
            className={cn("absolute inset-0 w-full h-full border-0 transition-opacity duration-300",
              state === "live" ? "opacity-100" : "opacity-0")}
            style={{ background: "transparent", colorScheme: "dark" }}
            allow="clipboard-write"
            // the hub page needs its own cookie and scripts (WebCodecs); it cannot reach Phantom Fleet
            sandbox="allow-scripts allow-same-origin"
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
                  <div className="text-sm font-medium text-white">Live screen unavailable</div>
                  <div className="text-xs text-phantom-ghost mt-1 max-w-md break-words">{error}</div>
                </div>
              </>
            ) : (
              <>
                <div className="phantom-skeleton w-[min(220px,40%)] aspect-[9/18.5] rounded-xl flex items-center justify-center">
                  <Smartphone className="w-6 h-6 text-phantom-ghost/60" strokeWidth={1.5} />
                </div>
                <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                  {state === "connecting" ? "Connecting to Fleet Mirror" : "Starting video"}
                </div>
              </>
            )}
          </div>
        )}
      </div>
      <div className="flex items-center gap-3">
        <span className={cn("phantom-dot", dot)} />
        <span className="text-[10px] font-mono tracking-wider text-phantom-ghost">
          {STATE_LABEL[state]} · {control ? "CONTROL" : "VIEW ONLY"} · {serial}
        </span>
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => setNonce((n) => n + 1)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border bg-phantom-panelHi text-white border-phantom-border hover:bg-phantom-panelHi/80 transition-colors"
        >
          <RefreshCw className={cn("w-3.5 h-3.5", state === "connecting" && "animate-spin")} strokeWidth={1.75} />
          Reconnect
        </button>
      </div>
    </div>
  );
}
