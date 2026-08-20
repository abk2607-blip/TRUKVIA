// Iter100 · Override Reason Dialog — mandatory reason capture for every
// manually overridden financial field on the Trip Form. Blocks Save until
// each override row carries a non-empty reason. Reasons are POSTed to
// /api/trips/{tid}/field-override after the trip save succeeds.
import React, { useEffect, useState } from "react";
import { fmtCurrency } from "@/api";
import { X, AlertTriangle } from "lucide-react";

export default function OverrideReasonDialog({
  open,
  overrides,          // [{ field, label, system_value, final_value, reason }]
  onCancel,
  onConfirm,          // (reasonsByField: Record<string,string>) => void
}) {
  const [reasons, setReasons] = useState({});

  // Seed reasons from any values already carried by the incoming overrides.
  useEffect(() => {
    if (!open) return;
    const seed = {};
    (overrides || []).forEach((o) => {
      seed[o.field] = o.reason || "";
    });
    setReasons(seed);
  }, [open, overrides]);

  if (!open) return null;

  const canConfirm = (overrides || []).every(
    (o) => (reasons[o.field] || "").trim().length > 0,
  );

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
      data-testid="override-reason-dialog"
    >
      <div className="bg-white w-full max-w-2xl max-h-[90vh] flex flex-col rounded-sm border border-zinc-950 shadow-2xl">
        <header className="flex items-center gap-3 border-b border-zinc-200 px-5 py-4">
          <div className="w-9 h-9 rounded-sm bg-amber-100 border border-amber-300 flex items-center justify-center">
            <AlertTriangle size={18} className="text-amber-700" />
          </div>
          <div className="flex-1">
            <div className="text-[10px] uppercase tracking-[0.15em] text-zinc-500 font-bold">
              Mandatory Override Justification
            </div>
            <h2 className="text-lg font-black tracking-tight">
              {overrides.length} field{overrides.length === 1 ? "" : "s"} manually overridden
            </h2>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="p-2 border border-zinc-200 rounded-sm hover:bg-zinc-50"
            data-testid="override-dialog-close"
          >
            <X size={16} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <p className="text-xs text-zinc-600">
            You have modified computed financial values away from what the system calculated.
            A reason is required for every override for the audit trail.
          </p>

          {overrides.map((o) => {
            const diff = Number(o.final_value) - Number(o.system_value);
            const diffClass = diff > 0 ? "text-emerald-700" : diff < 0 ? "text-rose-700" : "text-zinc-500";
            return (
              <div
                key={o.field}
                className="border border-zinc-200 rounded-sm p-3 space-y-2"
                data-testid={`override-row-${o.field}`}
              >
                <div className="flex items-baseline justify-between">
                  <div className="text-xs uppercase tracking-wider font-bold text-zinc-950">
                    {o.label}
                  </div>
                  <div className="text-[10px] text-zinc-500 font-mono">{o.field}</div>
                </div>
                <div className="grid grid-cols-3 gap-3 text-xs tabular-nums">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-zinc-500">System</div>
                    <div className="font-mono text-zinc-700">{fmtCurrency(o.system_value)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-zinc-500">Final</div>
                    <div className="font-mono font-bold text-zinc-950">{fmtCurrency(o.final_value)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-zinc-500">Δ Difference</div>
                    <div className={`font-mono font-bold ${diffClass}`}>
                      {diff >= 0 ? "+" : ""}{fmtCurrency(diff)}
                    </div>
                  </div>
                </div>
                <div>
                  <label className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">
                    Reason <span className="text-rose-600">*</span>
                  </label>
                  <textarea
                    data-testid={`override-reason-input-${o.field}`}
                    rows={2}
                    value={reasons[o.field] || ""}
                    onChange={(e) => setReasons({ ...reasons, [o.field]: e.target.value })}
                    placeholder="e.g. Client accepted higher shortage rate — WhatsApp confirmed on 15-Feb"
                    className="w-full mt-1 border border-zinc-300 rounded-sm px-2 py-2 text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none"
                  />
                </div>
              </div>
            );
          })}
        </div>

        <footer className="border-t border-zinc-200 px-5 py-3 flex items-center justify-between gap-3">
          <div className="text-[11px] text-zinc-500">
            {canConfirm
              ? "All reasons captured — ready to save."
              : "Provide a reason for every overridden field to continue."}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onCancel}
              data-testid="override-dialog-cancel"
              className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-50"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!canConfirm}
              onClick={() => onConfirm(reasons)}
              data-testid="override-dialog-confirm"
              className="px-6 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Confirm &amp; Save Trip
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
