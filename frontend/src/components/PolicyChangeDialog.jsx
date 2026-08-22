import React, { useMemo, useState } from "react";
import { X, Loader2, ArrowRight, AlertTriangle, CheckCircle2 } from "lucide-react";
import { api } from "@/api";
import { toast } from "sonner";

const fmt = (n) =>
  Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/**
 * Iter105 · Customer Policy Change dialog.
 *
 * Two-stage flow:
 *   Stage 1  Confirmation — old vs new policy summary + Effective Date
 *            + "Apply to Previous Eligible Trips" checkbox (OFF by default).
 *   Stage 2  (only when the checkbox is ON) — preview table of eligible
 *            pending trips with per-row selection + old/new financials.
 *
 * On Save:
 *   OFF  → `onSaveMaster()` (parent handles PUT /customers).
 *   ON   → POST /policy-changes/apply with the selected trip ids.
 *
 * The dialog is deliberately isolated from the customer edit form — it
 * receives the old + new policy as props and does not mutate anything
 * beyond calling the callbacks below.
 */
export default function PolicyChangeDialog({
  customerId,
  customerName,
  oldPolicy,          // { default_freight_method, shortage_config }
  newPolicy,          // { default_freight_method, shortage_config }
  onClose,
  onDone,             // fired after a successful apply (parent refreshes)
  onSaveMaster,       // async () => void — used for OFF path
}) {
  const [applyToPrevious, setApplyToPrevious] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [preview, setPreview] = useState(null);
  const [selected, setSelected] = useState({}); // {trip_id: true}
  const [saving, setSaving] = useState(false);
  const [reason, setReason] = useState("");

  const effectiveFrom = (newPolicy?.shortage_config?.effective_from || "").trim();

  const oldSummary = useMemo(() => summarise(oldPolicy), [oldPolicy]);
  const newSummary = useMemo(() => summarise(newPolicy), [newPolicy]);

  const runPreview = async () => {
    if (!effectiveFrom) {
      toast.error("Effective Date is required");
      return;
    }
    setPreviewLoading(true);
    try {
      const { data } = await api.post("/policy-changes/preview", {
        customer_id: customerId,
        effective_from: effectiveFrom,
        new_policy: newPolicy,
      });
      setPreview(data);
      // Pre-select every eligible trip by default
      const next = {};
      (data.eligible_trips || []).forEach((t) => { next[t.trip_id] = true; });
      setSelected(next);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Preview failed");
    } finally {
      setPreviewLoading(false);
    }
  };

  const toggleApplyToPrevious = async (checked) => {
    setApplyToPrevious(checked);
    if (checked && !preview) {
      await runPreview();
    }
  };

  const selectedIds = useMemo(
    () => Object.entries(selected).filter(([, v]) => v).map(([k]) => k),
    [selected]
  );

  const handleSave = async () => {
    if (!effectiveFrom) {
      toast.error("Effective Date is required");
      return;
    }
    setSaving(true);
    try {
      if (!applyToPrevious) {
        await onSaveMaster();
        toast.success("Policy updated · pending trips left unchanged");
        onDone?.();
        return;
      }
      const { data } = await api.post("/policy-changes/apply", {
        customer_id: customerId,
        effective_from: effectiveFrom,
        new_policy: newPolicy,
        apply_to_previous: true,
        trip_ids: selectedIds,
        reason,
      });
      const n = data.updated_trip_count;
      toast.success(`Policy applied · ${n} trip${n === 1 ? "" : "s"} recomputed`);
      onDone?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Apply failed");
    } finally {
      setSaving(false);
    }
  };

  const disabled = saving || previewLoading;

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
         data-testid="policy-change-dialog">
      <div className="bg-white w-full max-w-5xl max-h-[92vh] flex flex-col shadow-2xl border border-zinc-200">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-200">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-amber-600 font-bold">
              Iter105 · Policy Change
            </div>
            <h2 className="text-lg font-black text-zinc-950 tracking-tight">
              {customerName}
            </h2>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-zinc-100 rounded"
                  data-testid="policy-change-close"
                  aria-label="Close">
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Old vs New summary */}
          <div className="grid md:grid-cols-2 gap-4">
            <PolicyCard title="Current policy" tone="zinc" summary={oldSummary} />
            <PolicyCard title="New policy" tone="emerald" summary={newSummary}
                        highlight />
          </div>

          {/* Effective date + checkbox */}
          <div className="border border-zinc-200 p-4 space-y-3">
            <div className="flex items-start gap-3">
              <div className="flex-1">
                <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">
                  Effective From
                </div>
                <div className={`mt-1 text-sm font-mono ${effectiveFrom ? "text-zinc-950" : "text-red-600"}`}>
                  {effectiveFrom || "— required —"}
                </div>
              </div>
              <label className="flex items-start gap-2 select-none cursor-pointer"
                     data-testid="apply-previous-toggle-label">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={applyToPrevious}
                  onChange={(e) => toggleApplyToPrevious(e.target.checked)}
                  data-testid="apply-previous-toggle"
                  disabled={!effectiveFrom}
                />
                <div className="text-sm">
                  <div className="font-semibold text-zinc-950">
                    Apply to previous eligible trips
                  </div>
                  <div className="text-xs text-zinc-500">
                    OFF: only future trips use the revised policy. ON: preview + explicit apply.
                  </div>
                </div>
              </label>
            </div>
            {!effectiveFrom && (
              <div className="text-xs text-red-600 flex items-center gap-1">
                <AlertTriangle size={12} /> Set the Effective Date on the customer form before applying.
              </div>
            )}
          </div>

          {/* Preview table — shown only when checkbox is ON */}
          {applyToPrevious && (
            <div className="border border-amber-200 bg-amber-50/40">
              <div className="px-4 py-2 flex items-center justify-between border-b border-amber-200">
                <div className="text-[10px] uppercase tracking-widest text-amber-700 font-bold">
                  Eligible pending trips · from {effectiveFrom || "—"}
                </div>
                {preview && (
                  <div className="text-xs text-zinc-600">
                    {preview.total_eligible} eligible ·{" "}
                    {preview.skipped_invoiced_count} invoiced (skipped) ·{" "}
                    {preview.skipped_historical_count} historical (skipped)
                  </div>
                )}
              </div>
              {previewLoading && (
                <div className="p-6 flex items-center justify-center text-zinc-600">
                  <Loader2 className="animate-spin mr-2" size={16} /> Loading preview...
                </div>
              )}
              {!previewLoading && preview && preview.eligible_trips?.length === 0 && (
                <div className="p-6 text-center text-sm text-zinc-500">
                  No eligible pending trips on or after {effectiveFrom}.
                </div>
              )}
              {!previewLoading && preview && preview.eligible_trips?.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs" data-testid="policy-change-preview-table">
                    <thead className="bg-white text-zinc-500 uppercase text-[10px]">
                      <tr>
                        <th className="p-2 text-left">
                          <input
                            type="checkbox"
                            checked={selectedIds.length === (preview.eligible_trips || []).length}
                            onChange={(e) => {
                              const next = {};
                              (preview.eligible_trips || []).forEach((t) => {
                                next[t.trip_id] = e.target.checked;
                              });
                              setSelected(next);
                            }}
                            data-testid="select-all-eligible"
                            aria-label="Select all"
                          />
                        </th>
                        <th className="p-2 text-left">Date</th>
                        <th className="p-2 text-left">Vehicle · LR</th>
                        <th className="p-2 text-left">Loading/Unload MT</th>
                        <th className="p-2 text-right">Old shortage ₹</th>
                        <th className="p-2 text-right">New shortage ₹</th>
                        <th className="p-2 text-right">Old freight ₹</th>
                        <th className="p-2 text-right">New freight ₹</th>
                        <th className="p-2 text-right">Δ Net ₹</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.eligible_trips.map((t) => {
                        const delta = t.delta_net_settlement;
                        return (
                          <tr key={t.trip_id}
                              className="border-t border-amber-100 hover:bg-white/60"
                              data-testid={`policy-change-preview-row-${t.trip_id}`}>
                            <td className="p-2">
                              <input
                                type="checkbox"
                                checked={!!selected[t.trip_id]}
                                onChange={(e) =>
                                  setSelected({ ...selected, [t.trip_id]: e.target.checked })
                                }
                                data-testid={`select-trip-${t.trip_id}`}
                                aria-label={`Select trip ${t.trip_id}`}
                              />
                            </td>
                            <td className="p-2 font-mono">{t.date}</td>
                            <td className="p-2">
                              <div className="font-semibold">{t.vehicle_number}</div>
                              <div className="text-[10px] text-zinc-500">{t.lr_number || "—"}</div>
                            </td>
                            <td className="p-2 font-mono">
                              {Number(t.loading_tons).toFixed(3)} / {Number(t.unloading_tons).toFixed(3)}
                            </td>
                            <td className="p-2 text-right font-mono">₹ {fmt(t.old.shortage_amount)}</td>
                            <td className="p-2 text-right font-mono text-emerald-700">
                              ₹ {fmt(t.new.shortage_amount)}
                            </td>
                            <td className="p-2 text-right font-mono">₹ {fmt(t.old.freight_amount)}</td>
                            <td className="p-2 text-right font-mono text-emerald-700">
                              ₹ {fmt(t.new.freight_amount)}
                            </td>
                            <td className={`p-2 text-right font-mono font-bold ${
                              delta > 0 ? "text-emerald-700" : delta < 0 ? "text-red-700" : "text-zinc-500"
                            }`}>
                              {delta > 0 ? "+" : ""}₹ {fmt(delta)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {applyToPrevious && preview && preview.eligible_trips?.length > 0 && (
                <div className="p-4 border-t border-amber-200 space-y-2">
                  <label className="block text-[10px] uppercase tracking-widest text-zinc-500 font-bold">
                    Reason for this policy change (optional but recommended)
                  </label>
                  <input
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="e.g. Updated allowance per contract amendment dated 01-Apr-2026"
                    className="w-full border border-zinc-300 px-3 py-2 text-sm"
                    data-testid="policy-change-reason"
                  />
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-zinc-200 flex items-center justify-between gap-3">
          <div className="text-xs text-zinc-500">
            {applyToPrevious && preview
              ? `${selectedIds.length} of ${preview.eligible_trips?.length || 0} selected`
              : "Historical trips + invoiced trips are always skipped."}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              disabled={disabled}
              className="px-4 py-2 text-sm border border-zinc-300 hover:bg-zinc-100 disabled:opacity-50"
              data-testid="policy-change-cancel">
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={disabled || !effectiveFrom || (applyToPrevious && selectedIds.length === 0)}
              className="px-4 py-2 text-sm bg-zinc-950 text-white font-semibold uppercase tracking-wider hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-2"
              data-testid="policy-change-save">
              {saving && <Loader2 className="animate-spin" size={14} />}
              {applyToPrevious ? (
                <>Apply to {selectedIds.length} trip{selectedIds.length === 1 ? "" : "s"} <ArrowRight size={14} /></>
              ) : (
                <>Save policy · future trips only <CheckCircle2 size={14} /></>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function summarise(p) {
  if (!p) return {};
  const sc = p.shortage_config || {};
  const method = sc.method === "full_after_limit"
    ? "Full shortage after limit exceeded"
    : "Net shortage above limit";
  const allowance = Number(sc.limit || 0) > 0
    ? `${sc.limit}${sc.limit_type === "kg" ? " KG" : " %"}`
    : "Uses Product Master allowance";
  return {
    freight: {
      per_ton_loading: "Per Ton · Loading Qty",
      per_ton_unloading: "Per Ton · Unloading Qty",
      per_ton_higher_of: "Per Ton · Higher of",
      fixed: "Fixed / Round-trip",
    }[p.default_freight_method] || p.default_freight_method || "—",
    method,
    allowance,
    effective_from: sc.effective_from || "—",
    active: sc.active !== false,
  };
}

function PolicyCard({ title, summary, tone = "zinc", highlight = false }) {
  const bg = highlight ? "bg-emerald-50 border-emerald-200" : "bg-zinc-50 border-zinc-200";
  return (
    <div className={`border ${bg} p-4 space-y-2`}>
      <div className={`text-[10px] uppercase tracking-widest font-bold ${
        tone === "emerald" ? "text-emerald-700" : "text-zinc-500"
      }`}>
        {title}
      </div>
      <Row k="Freight" v={summary.freight} />
      <Row k="Deduction" v={summary.method} />
      <Row k="Allowance" v={summary.allowance} />
      <Row k="Effective From" v={summary.effective_from} />
    </div>
  );
}

function Row({ k, v }) {
  return (
    <div className="flex items-baseline gap-3">
      <div className="text-[10px] uppercase tracking-widest text-zinc-500 w-28 flex-shrink-0">
        {k}
      </div>
      <div className="text-sm font-semibold text-zinc-950">{v || "—"}</div>
    </div>
  );
}
