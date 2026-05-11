"use client";

import { useEffect, useState } from "react";

/**
 * Command palette stub — wires up Cmd+K globally.
 * Full cmdk-powered palette lives in Phase 1 build-out.
 */
export function CommandPalette() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((x) => !x);
      }
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-phantom-bg/80 backdrop-blur-md flex items-start justify-center pt-[12vh]"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-2xl phantom-panel-accent overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-5 border-b border-phantom-border flex items-center gap-3">
          <span className="text-phantom-ghost text-sm">›</span>
          <input
            autoFocus
            placeholder="Search accounts, personas, phones, agents..."
            className="flex-1 bg-transparent outline-none text-white placeholder:text-phantom-ghost text-base"
          />
          <kbd className="phantom-kbd">ESC</kbd>
        </div>
        <div className="p-4 text-sm text-phantom-ghost">
          <div className="text-[10px] uppercase tracking-[0.15em] mb-2 px-2">Quick actions</div>
          <ul className="space-y-1">
            <li className="px-3 py-2 rounded-md hover:bg-phantom-panelHi cursor-pointer">
              Pause all accounts on cluster alert
            </li>
            <li className="px-3 py-2 rounded-md hover:bg-phantom-panelHi cursor-pointer">
              Run audit harness
            </li>
            <li className="px-3 py-2 rounded-md hover:bg-phantom-panelHi cursor-pointer">
              Rotate proxy (force)
            </li>
            <li className="px-3 py-2 rounded-md hover:bg-phantom-panelHi cursor-pointer">
              Launch Fresh Target Agent for Tatiana
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}
