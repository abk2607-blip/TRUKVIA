// Iter55 — Extracted from TripForm.jsx. Iter75 — mobile-collapsible sections.
import React, { useState } from "react";
import { ChevronDown } from "lucide-react";

/**
 * Section — collapsible on mobile (default open), always open on md+.
 * Keeps the exact same visual + testid contract on desktop.
 */
export function Section({ title, children, defaultOpen = true, testId }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="border border-zinc-200 bg-white rounded-sm" data-testid={testId}>
      {/* Mobile: clickable header that toggles */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="md:hidden w-full flex items-center justify-between gap-3 px-4 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider text-left min-h-[52px] active:bg-zinc-50"
      >
        <span className="flex-1 min-w-0 truncate">{title}</span>
        <ChevronDown
          size={18}
          className={`text-zinc-500 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {/* Desktop: static header, always visible */}
      <div className="hidden md:block px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">
        {title}
      </div>
      {/* Body */}
      <div className={`${open ? "block" : "hidden"} md:block p-4 sm:p-5`}>{children}</div>
    </section>
  );
}

export function Field({ label, required, children }) {
  return (
    <div>
      <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
        {label}{required && " *"}
      </label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
