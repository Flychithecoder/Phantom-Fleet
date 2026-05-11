"use client";

import { useEffect, useState } from "react";

/**
 * Live ticker — numbers drift slightly every 2 seconds so the dashboard
 * feels alive even without a WebSocket connection. Use only for ambient
 * counters (actions per minute, targets scraped, etc.) — never for financial
 * or KPI values where real data is required.
 */
export function LiveTicker({
  base,
  format = "int",
  prefix = "",
  suffix = "",
  className = "",
}: {
  base: number;
  format?: "int" | "usd" | "pct";
  prefix?: string;
  suffix?: string;
  className?: string;
}) {
  const [value, setValue] = useState(base);

  useEffect(() => {
    const tick = () => {
      // small drift — +/- 0.5% max per tick
      setValue((v) => Math.max(0, v + (Math.random() - 0.45) * Math.max(1, v * 0.005)));
    };
    const id = setInterval(tick, 2000);
    return () => clearInterval(id);
  }, []);

  const display = (() => {
    if (format === "usd") return `$${Math.round(value).toLocaleString()}`;
    if (format === "pct") return `${value.toFixed(1)}%`;
    return Math.round(value).toLocaleString();
  })();

  return (
    <span className={`tabular-nums font-mono ${className}`}>
      {prefix}
      {display}
      {suffix}
    </span>
  );
}
