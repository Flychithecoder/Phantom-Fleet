"use client";

import { Line, LineChart, ResponsiveContainer, Tooltip } from "recharts";

/**
 * Ultra-compact sparkline — used inside table cells and KPI cards.
 * 80-140px wide, no axes, single-color, optional hover tooltip.
 */
export function Sparkline({
  data,
  color = "hsl(162 100% 54%)",
  height = 40,
  label,
}: {
  data: number[];
  color?: string;
  height?: number;
  label?: string;
}) {
  const chartData = data.map((v, i) => ({ x: i, y: v }));
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
          <Line
            type="monotone"
            dataKey="y"
            stroke={color}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          {label && (
            <Tooltip
              contentStyle={{
                background: "hsl(240 6% 8%)",
                border: "1px solid hsl(240 6% 18%)",
                borderRadius: "0.5rem",
                fontSize: "10px",
                padding: "4px 8px",
              }}
              formatter={(v) => [v, label]}
              labelFormatter={() => ""}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
