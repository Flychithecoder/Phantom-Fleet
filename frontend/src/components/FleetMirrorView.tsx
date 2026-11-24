"use client";
/**
 * FleetMirrorView — a phone's live screen from the Fleet Mirror hub, inside Phantom Fleet's Next.js UI.
 *
 *   <FleetMirrorView serial="R5CRC08L4QM" control={false} />
 *
 * How it works: the component asks Phantom Fleet's own backend for an embed link
 * (GET /api/fleet-mirror/embed?serial=...&control=0), and the backend asks the hub with its API key
 * (FleetMirrorClient.embed_url). The link is single-use and valid for 2 minutes, so a fresh one is
 * fetched on every mount / "Reconnect". The API key never reaches the browser.
 *
 * The browser must trust the hub's certificate once (see README.md, "Trusting the hub certificate"),
 * otherwise the frame shows a certificate error. Video needs WebCodecs (Chrome, Edge, Electron).
 */
import { useCallback, useEffect, useState } from "react";

type Props = {
  serial: string;
  control?: boolean;            // allow taps/keys from this view (the hub must allow control for the phone)
  minutes?: number;             // how long the embedded session may stay open (1-720, default 60)
  height?: number | string;     // frame height (width follows the phone's shape)
  endpoint?: string;            // backend route that returns {url}; default /api/fleet-mirror/embed
  className?: string;
};

export default function FleetMirrorView({
  serial, control = false, minutes = 60, height = 640, endpoint = "/api/fleet-mirror/embed", className,
}: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const load = useCallback(async () => {
    setUrl(null); setError(null);
    try {
      const q = new URLSearchParams({ serial, control: control ? "1" : "0", minutes: String(minutes) });
      const r = await fetch(`${endpoint}?${q}`, { cache: "no-store" });
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      const body = await r.json();
      setUrl(body.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [serial, control, minutes, endpoint]);

  useEffect(() => { load(); }, [load, nonce]);

  return (
    <div className={className} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {url ? (
        <iframe
          key={url}
          src={url}
          title={`Fleet Mirror ${serial}`}
          style={{ width: "100%", height, border: 0, borderRadius: 12, background: "#111" }}
          allow="clipboard-write"
          // same-origin + scripts: the hub page needs its own cookie and WebCodecs; it cannot reach Phantom Fleet
          sandbox="allow-scripts allow-same-origin"
        />
      ) : (
        <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center", opacity: 0.7 }}>
          {error ? `Fleet Mirror: ${error}` : "Connecting to Fleet Mirror…"}
        </div>
      )}
      <button type="button" onClick={() => setNonce(n => n + 1)} style={{ alignSelf: "flex-end", fontSize: 12 }}>
        Reconnect
      </button>
    </div>
  );
}
