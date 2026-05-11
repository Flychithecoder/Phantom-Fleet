"use client";

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { DollarSign } from "lucide-react";

const DATA = Array.from({ length: 30 }, (_, i) => ({
  day: `d${i + 1}`,
  primary: Math.round(60 + i * 12 + Math.sin(i / 2) * 25),
  secondary: Math.round(20 + i * 5 + Math.cos(i / 3) * 8),
  affiliate: Math.round(10 + i * 3 + Math.sin(i / 4) * 5),
}));

export function RevenueChart() {
  return (
    <div className="phantom-panel p-6">
      <div className="flex items-center justify-between mb-5">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Conversion revenue
          </div>
          <div className="text-lg font-display font-semibold mt-1 flex items-center gap-2">
            <DollarSign className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
            Attributed across all destinations (30d)
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1.5 text-phantom-ghost">
            <span className="w-3 h-0.5 rounded bg-phantom-accent" />
            Primary
          </span>
          <span className="flex items-center gap-1.5 text-phantom-ghost">
            <span className="w-3 h-0.5 rounded bg-phantom-magenta" />
            Secondary
          </span>
          <span className="flex items-center gap-1.5 text-phantom-ghost">
            <span className="w-3 h-0.5 rounded bg-phantom-amber" />
            Affiliate
          </span>
        </div>
      </div>
      <div className="h-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={DATA} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="primary" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="hsl(162 100% 54%)" stopOpacity={0.4} />
                <stop offset="100%" stopColor="hsl(162 100% 54%)" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="secondary" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="hsl(292 91% 68%)" stopOpacity={0.4} />
                <stop offset="100%" stopColor="hsl(292 91% 68%)" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="affiliate" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="hsl(38 92% 58%)" stopOpacity={0.4} />
                <stop offset="100%" stopColor="hsl(38 92% 58%)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="hsl(240 6% 18%)" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="day"
              stroke="hsl(240 5% 64.9%)"
              fontSize={10}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              stroke="hsl(240 5% 64.9%)"
              fontSize={10}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => `$${v}`}
            />
            <Tooltip
              contentStyle={{
                background: "hsl(240 6% 8%)",
                border: "1px solid hsl(240 6% 18%)",
                borderRadius: "0.5rem",
                fontSize: "12px",
              }}
              labelStyle={{ color: "hsl(240 5% 64.9%)" }}
            />
            <Area type="monotone" dataKey="primary" stroke="hsl(162 100% 54%)" strokeWidth={2} fill="url(#primary)" />
            <Area type="monotone" dataKey="secondary" stroke="hsl(292 91% 68%)" strokeWidth={2} fill="url(#secondary)" />
            <Area type="monotone" dataKey="affiliate" stroke="hsl(38 92% 58%)" strokeWidth={2} fill="url(#affiliate)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
