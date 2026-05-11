"use client";

import { cn } from "@/lib/utils";
import { ReactNode } from "react";

export type Column<T> = {
  key: keyof T | string;
  header: string;
  align?: "left" | "right" | "center";
  width?: string;
  render?: (row: T) => ReactNode;
};

/**
 * Lightweight data table with premium dark styling.
 * For Phase 1 sophistication, swap to @tanstack/react-table.
 */
export function DataTable<T extends { id: string }>({
  columns,
  rows,
  onRowClick,
  rowClassName,
}: {
  columns: Column<T>[];
  rows: T[];
  onRowClick?: (row: T) => void;
  rowClassName?: (row: T) => string;
}) {
  return (
    <div className="overflow-x-auto -mx-2">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-phantom-border">
            {columns.map((col) => (
              <th
                key={String(col.key)}
                className={cn(
                  "px-3 py-2.5 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium",
                  col.align === "right" && "text-right",
                  col.align === "center" && "text-center",
                  col.align !== "right" && col.align !== "center" && "text-left",
                )}
                style={{ width: col.width }}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              onClick={() => onRowClick?.(row)}
              className={cn(
                "border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors",
                onRowClick && "cursor-pointer",
                rowClassName?.(row),
              )}
            >
              {columns.map((col) => (
                <td
                  key={String(col.key)}
                  className={cn(
                    "px-3 py-3",
                    col.align === "right" && "text-right",
                    col.align === "center" && "text-center",
                  )}
                >
                  {col.render
                    ? col.render(row)
                    : String((row as Record<string, unknown>)[String(col.key)] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
