// Iter99 · Phase 4 — Compact "[Overridden]" badge that shows a popover with
// System vs Final, reason and audit metadata on hover/click.
import React, { useState } from "react";
import { fmtCurrency } from "@/api";

export default function OverrideBadge({ trip, field, className = "" }) {
  const [open, setOpen] = useState(false);
  const overrides = (trip?.field_overrides || []).filter((o) => o.field === field);
  if (!overrides.length) return null;
  // Show the latest entry for this field
  const o = overrides[overrides.length - 1];

  return (
    <span className={`inline-flex items-center gap-1 relative ${className}`} data-testid={`override-badge-${field}`}>
      <button
        type="button"
        onClick={() => setOpen((s) => !s)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        className="text-[9px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded-sm bg-amber-100 text-amber-800 border border-amber-300 hover:bg-amber-200"
      >
        ✎ Overridden
      </button>
      {open && (
        <div
          className="absolute top-full right-0 mt-1 z-50 w-64 bg-white border border-zinc-950 rounded-sm shadow-lg p-3 text-left"
          data-testid={`override-details-${field}`}
        >
          <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-2">{o.label || field}</div>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between"><span className="text-zinc-500">System Value:</span> <span className="font-mono">{fmtCurrency(o.system_value)}</span></div>
            <div className="flex justify-between"><span className="text-zinc-500">Final Value:</span> <span className="font-mono font-bold">{fmtCurrency(o.final_value)}</span></div>
            <div className="pt-1 border-t border-zinc-100"><span className="text-zinc-500">Reason:</span><br/><span className="text-zinc-800">{o.reason || "—"}</span></div>
            <div className="pt-1 border-t border-zinc-100 text-[10px] text-zinc-500">
              By {o.modified_by || "—"}<br/>
              {o.modified_at ? new Date(o.modified_at).toLocaleString() : ""}
            </div>
            {overrides.length > 1 && (
              <div className="pt-1 border-t border-zinc-100 text-[10px] text-zinc-500">
                +{overrides.length - 1} earlier override{overrides.length > 2 ? "s" : ""} for this field
              </div>
            )}
          </div>
        </div>
      )}
    </span>
  );
}
