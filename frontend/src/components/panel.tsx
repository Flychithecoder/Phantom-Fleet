import { cn } from "@/lib/utils";
import { ReactNode } from "react";

/**
 * Canonical panel wrapper — header with label + optional actions + children body.
 * Every page section uses this for consistent visual language.
 */
export function Panel({
  label,
  title,
  subtitle,
  actions,
  children,
  className,
  accent = false,
  dense = false,
}: {
  label?: string;
  title?: ReactNode;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  accent?: boolean;
  dense?: boolean;
}) {
  return (
    <section className={cn(accent ? "phantom-panel-accent" : "phantom-panel", dense ? "p-4" : "p-6", className)}>
      {(label || title || actions) && (
        <header className="flex items-start justify-between mb-5">
          <div>
            {label && (
              <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                {label}
              </div>
            )}
            {title && (
              <div className="text-lg font-display font-semibold mt-1">{title}</div>
            )}
            {subtitle && (
              <div className="text-xs text-phantom-ghost mt-1 max-w-lg">{subtitle}</div>
            )}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}
