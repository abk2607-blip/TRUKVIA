import React, { useMemo, useState } from "react";
import { api, fmtCurrency } from "@/api";
import { toast } from "sonner";
import { X, Upload, CheckCircle2, AlertTriangle, XCircle, Link2, Eye } from "lucide-react";
import { SearchableSelect } from "@/components/ui/searchable-select";

/* Iter148 P0 · FASTag Toll Import Wizard.
 * ------------------------------------------------------------------
 * Flow: Upload → Auto-detect (IDFC / LIVQ) → Preview (5 buckets) →
 *       Row-scoped vehicle mapping → Confirm & Commit → results.
 *
 * Iter148 UAT-FIX (Q2 · possible-duplicate handling):
 *   - Possible-duplicate rows require an EXPLICIT per-row decision
 *     (Import Anyway / Skip). No decision → commit is BLOCKED so a
 *     valid source Toll can never be silently excluded.
 *   - Amber banner surfaces the unreviewed count at the top.
 *   - Footer shows the full breakdown of what will be imported vs
 *     skipped by category.
 *   - Match details (existing canonical/legacy row) are shown inline
 *     with each possible-duplicate row so the operator can compare
 *     source vs existing before deciding.
 *   - Exact-duplicate remains a hard block (unchanged).
 */

const BUCKET_META = {
  ready:                    { label: "Ready to Import",   color: "text-emerald-700 border-emerald-300 bg-emerald-50",   icon: CheckCircle2 },
  vehicle_mapping_required: { label: "Vehicle Mapping",   color: "text-sky-700 border-sky-300 bg-sky-50",              icon: Link2 },
  possible_duplicate:       { label: "Possible Duplicate",color: "text-amber-700 border-amber-300 bg-amber-50",         icon: AlertTriangle },
  exact_duplicate:          { label: "Exact Duplicate",   color: "text-zinc-600 border-zinc-300 bg-zinc-50",            icon: XCircle },
  error:                    { label: "Error / Invalid",   color: "text-rose-700 border-rose-300 bg-rose-50",             icon: XCircle },
};

export default function TollImportWizard({ vehicles, onClose, onSuccess }) {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [preview, setPreview] = useState(null);
  const [activeBucket, setActiveBucket] = useState("ready");
  const [overrides, setOverrides] = useState({});          // row_index -> "keep" | "skip"
  const [rowSelections, setRowSelections] = useState({});  // row_index -> {vehicle_id, vehicle_number}
  const [confirmOpen, setConfirmOpen] = useState(false);

  const doPreview = async () => {
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post("/toll-import/preview", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setPreview(data);
      setOverrides({});
      const firstNonZero = ["ready", "vehicle_mapping_required", "possible_duplicate", "exact_duplicate", "error"]
        .find((b) => (data.counts?.[b] || 0) > 0) || "ready";
      setActiveBucket(firstNonZero);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Preview failed");
      setPreview(null);
    } finally { setUploading(false); }
  };

  const selectVehicleForRow = (rowIndex, vehicleId) => {
    const veh = vehicles.find((v) => v.id === vehicleId);
    if (!veh) return;
    setRowSelections((m) => ({
      ...m,
      [rowIndex]: { vehicle_id: vehicleId, vehicle_number: veh.vehicle_number || "" },
    }));
  };
  const clearRowSelection = (rowIndex) => {
    setRowSelections((m) => { const c = { ...m }; delete c[rowIndex]; return c; });
  };

  // Possible-duplicate accounting: EXPLICIT per-row decision.
  const possibleDupRows = useMemo(
    () => (preview?.rows || []).filter((r) => r.bucket === "possible_duplicate"),
    [preview],
  );
  const unreviewedPossibleDupRows = useMemo(
    () => possibleDupRows.filter((r) => overrides[r.row_index] !== "keep" && overrides[r.row_index] !== "skip"),
    [possibleDupRows, overrides],
  );
  const possibleDupKeepCount = useMemo(
    () => possibleDupRows.filter((r) => overrides[r.row_index] === "keep").length,
    [possibleDupRows, overrides],
  );
  const possibleDupSkipCount = useMemo(
    () => possibleDupRows.filter((r) => overrides[r.row_index] === "skip").length,
    [possibleDupRows, overrides],
  );

  const rowsForCommit = useMemo(() => {
    if (!preview) return [];
    return preview.rows
      .map((r) => {
        const sel = rowSelections[r.row_index];
        if (sel) return { ...r, bucket: "ready",
                          resolved_vehicle_id: sel.vehicle_id,
                          resolved_vehicle_number: sel.vehicle_number };
        return r;
      })
      .filter((r) => {
        if (r.bucket === "exact_duplicate" || r.bucket === "error") return false;
        if (r.bucket === "possible_duplicate" && overrides[r.row_index] !== "keep") return false;
        return !!r.resolved_vehicle_id;
      });
  }, [preview, overrides, rowSelections]);

  const attemptCommit = () => {
    if (!preview || rowsForCommit.length === 0) {
      if (unreviewedPossibleDupRows.length > 0) {
        return toast.error(`${unreviewedPossibleDupRows.length} possible-duplicate row(s) need a decision (Import Anyway or Skip) before you can commit.`);
      }
      return toast.error("Nothing to import. Map unmapped vehicles or review possible duplicates.");
    }
    if (unreviewedPossibleDupRows.length > 0) {
      setConfirmOpen(true);
      setActiveBucket("possible_duplicate");
      return;
    }
    doCommit();
  };

  const doCommit = async () => {
    setConfirmOpen(false);
    setCommitting(true);
    try {
      const { data } = await api.post("/toll-import/commit", {
        vendor: preview.vendor, rows: rowsForCommit,
      });
      const skipped = possibleDupSkipCount + unreviewedPossibleDupRows.length;
      const parts = [`Imported ${data.created}`];
      if (data.duplicate) parts.push(`${data.duplicate} exact duplicate`);
      if (skipped) parts.push(`${skipped} possible dup skipped`);
      if (data.failed) parts.push(`${data.failed} failed`);
      toast.success(parts.join(" · "));
      onSuccess?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Import commit failed");
    } finally { setCommitting(false); }
  };

  const visibleRows = preview?.rows.filter((r) => {
    const sel = rowSelections[r.row_index];
    if (activeBucket === "ready")
      return r.bucket === "ready" || (r.bucket === "vehicle_mapping_required" && sel);
    if (activeBucket === "vehicle_mapping_required")
      return r.bucket === "vehicle_mapping_required" && !sel;
    return r.bucket === activeBucket;
  }) || [];

  const totalToSkip = preview
    ? (preview.counts.exact_duplicate || 0)
      + (preview.counts.error || 0)
      + possibleDupSkipCount + unreviewedPossibleDupRows.length
    : 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-3 md:p-6"
         data-testid="toll-import-wizard">
      <div data-testid="toll-import-wizard-shell"
        className="bg-white w-[95vw] max-w-[1600px] h-[85vh] border border-zinc-950 rounded-sm flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
          <div>
            <div className="text-[10px] uppercase tracking-[0.15em] text-zinc-500 font-bold">FASTag Statement Import · v148-uat</div>
            <h3 className="font-bold text-lg">Upload Tolls · {preview?.vendor ? preview.vendor.toUpperCase() : "IDFC / LIVQ"}</h3>
          </div>
          <button data-testid="close-toll-wizard-btn" onClick={onClose}><X size={18}/></button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {!preview && (
            <div className="p-6 space-y-4">
              <div className="border-2 border-dashed border-zinc-300 rounded-sm p-8 text-center bg-white">
                <Upload size={32} className="mx-auto text-zinc-400"/>
                <div className="mt-2 text-sm font-semibold">Upload the ORIGINAL FASTag statement</div>
                <div className="text-xs text-zinc-500 mt-1">Vendor auto-detected from the file (IDFC / LIVQ).</div>
                <label className="inline-flex items-center gap-2 mt-4 px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm cursor-pointer hover:bg-zinc-800">
                  {file ? file.name : "Choose file"}
                  <input data-testid="toll-file-input" type="file" accept=".xlsx" className="hidden"
                         onChange={(e) => setFile(e.target.files?.[0] || null)}/>
                </label>
                {file && <div className="mt-2 text-xs text-zinc-500">{(file.size/1024).toFixed(1)} KB</div>}
              </div>
              <div className="flex justify-end">
                <button data-testid="toll-preview-btn" disabled={!file || uploading} onClick={doPreview}
                  className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
                  {uploading ? "Parsing…" : "Preview"}
                </button>
              </div>
            </div>
          )}
          {preview && (
            <div className="p-4 space-y-4">
              {/* Iter148 UAT-FIX · Q2 · Possible-duplicate REVIEW BANNER */}
              {unreviewedPossibleDupRows.length > 0 && (
                <div className="border-2 border-amber-400 bg-amber-50 rounded-sm p-3 flex items-start gap-3"
                     data-testid="toll-possible-dup-banner">
                  <AlertTriangle size={20} className="text-amber-700 shrink-0 mt-0.5"/>
                  <div className="flex-1 text-xs text-amber-900">
                    <div className="font-bold uppercase tracking-wider text-amber-900">
                      {unreviewedPossibleDupRows.length} row(s) need a duplicate decision
                    </div>
                    <div className="mt-1">
                      These rows look similar to an existing Toll entry (±1 day / ±2 % amount, same vehicle).
                      No valid source transaction will be silently excluded — you MUST explicitly choose
                      <span className="font-bold"> Import Anyway</span> or <span className="font-bold">Skip</span> for each,
                      before commit is enabled.
                    </div>
                  </div>
                  <button data-testid="toll-review-possible-dup-btn"
                    onClick={() => setActiveBucket("possible_duplicate")}
                    className="inline-flex items-center gap-1 px-3 py-1.5 text-[11px] uppercase tracking-wider bg-amber-700 text-white rounded-sm hover:bg-amber-800">
                    <Eye size={12}/> Review now
                  </button>
                </div>
              )}

              <div className="flex flex-wrap gap-2" data-testid="toll-buckets">
                {Object.entries(BUCKET_META).map(([k, meta]) => {
                  const selCount = Object.keys(rowSelections).length;
                  const count = k === "ready" ? preview.counts.ready + selCount
                    : k === "vehicle_mapping_required" ? Math.max(0, preview.counts.vehicle_mapping_required - selCount)
                    : preview.counts[k];
                  const Icon = meta.icon;
                  const unreviewedHere = k === "possible_duplicate" && unreviewedPossibleDupRows.length > 0;
                  return (
                    <button key={k} data-testid={`toll-bucket-${k}`} onClick={() => setActiveBucket(k)}
                      className={`inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider border rounded-sm ${activeBucket === k ? "bg-zinc-950 text-white border-zinc-950" : `${meta.color} hover:opacity-80`} ${unreviewedHere ? "ring-2 ring-amber-500 ring-offset-1" : ""}`}>
                      <Icon size={14}/> {meta.label} <span className="font-mono font-bold">{count || 0}</span>
                      {unreviewedHere && (
                        <span data-testid="toll-bucket-possible-dup-unreviewed"
                              className="ml-1 px-1.5 py-0.5 text-[9px] rounded-sm bg-amber-600 text-white font-bold">
                          {unreviewedPossibleDupRows.length} unreviewed
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
              <div className="border border-zinc-200 rounded-sm overflow-auto">
                <table className="w-full text-xs min-w-[1100px]" data-testid="toll-rows-table">
                  <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
                    <tr>
                      <th className="text-left px-3 py-2">Row</th>
                      <th className="text-left px-3 py-2">Date</th>
                      <th className="text-left px-3 py-2">Truck Number</th>
                      <th className="text-left px-3 py-2">TRUKVIA Vehicle</th>
                      <th className="text-right px-3 py-2">Amount</th>
                      <th className="text-left px-3 py-2">Description / Plaza</th>
                      <th className="text-left px-3 py-2">Txn ID</th>
                      <th className="text-left px-3 py-2">Vendor</th>
                      <th className="text-left px-3 py-2">Status</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono">
                    {visibleRows.length === 0 && (
                      <tr><td colSpan={9} className="px-4 py-8 text-center text-zinc-400">No rows in this bucket.</td></tr>
                    )}
                    {visibleRows.map((r) => {
                      const sel = rowSelections[r.row_index];
                      const vehId = sel?.vehicle_id || r.resolved_vehicle_id || "";
                      const vehNum = sel?.vehicle_number || r.resolved_vehicle_number || "";
                      const isAuto = !sel && !!r.resolved_vehicle_id;
                      const decision = overrides[r.row_index]; // "keep" | "skip" | undefined
                      return (
                        <tr key={`${r.row_index}:${r.source_txn_ref}`} data-testid={`toll-row-${r.row_index}`}
                            className={`border-t border-zinc-100 ${r.bucket === "possible_duplicate" && !decision ? "bg-amber-50/40" : ""}`}>
                          <td className="px-3 py-1.5">{r.row_index}</td>
                          <td className="px-3 py-1.5">{r.date}</td>
                          <td className="px-3 py-1.5 font-semibold">{r.source_vehicle_raw || r.source_vehicle_ref}</td>
                          <td className="px-3 py-1.5 min-w-[260px]">
                            {(r.bucket === "exact_duplicate" || r.bucket === "error") ? (
                              <span className="font-semibold">{vehNum || "—"}</span>
                            ) : (
                              <div className="space-y-1">
                                <SearchableSelect
                                  testId={`toll-map-${r.row_index}`}
                                  value={vehId}
                                  placeholder="Search TRUKVIA vehicle…"
                                  emptyText="No matching vehicles"
                                  allowClear={true}
                                  onChange={(v) => v ? selectVehicleForRow(r.row_index, v) : clearRowSelection(r.row_index)}
                                  options={vehicles.map((v) => ({
                                    value: v.id, label: v.vehicle_number,
                                    secondary: (v.vehicle_type || "").toUpperCase() === "SUPPLIER"
                                      ? `${v.supplier_name || "Supplier"} · Supplier`
                                      : (v.driver_name || (v.vehicle_type || "").toUpperCase()),
                                    keywords: [v.vehicle_number, v.driver_name, v.supplier_name].filter(Boolean),
                                  }))}
                                />
                                {isAuto && (
                                  <div className="text-[10px] text-amber-700" data-testid={`toll-auto-hint-${r.row_index}`}>
                                    Auto-resolved by Truck Number. Editable per row.
                                  </div>
                                )}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-1.5 text-right font-semibold">{fmtCurrency(r.amount || 0)}</td>
                          <td className="px-3 py-1.5 text-xs">{r.plaza || r.description || "—"}</td>
                          <td className="px-3 py-1.5 text-xs">{r.source_txn_ref}</td>
                          <td className="px-3 py-1.5 text-xs uppercase">{r.source}</td>
                          <td className="px-3 py-1.5 text-xs min-w-[300px]">
                            {r.bucket === "error" && <span className="text-rose-700">{r.error}</span>}
                            {r.bucket === "exact_duplicate" && (
                              <span className="text-zinc-500" data-testid={`toll-exact-dup-reason-${r.row_index}`}>
                                {r.duplicate_reason || "Already imported earlier"}
                              </span>
                            )}
                            {r.bucket === "possible_duplicate" && (
                              <div className="space-y-1.5">
                                <div className="text-amber-700 font-semibold uppercase text-[10px] tracking-wider">
                                  {r.possible_matches?.length || 0} similar existing entry
                                </div>
                                {(r.possible_matches || []).map((m, i) => (
                                  <div key={i} data-testid={`toll-possible-match-${r.row_index}-${i}`}
                                       className="text-[11px] text-amber-900 border border-amber-200 bg-amber-50 rounded-sm px-2 py-1">
                                    <span className="font-bold">{m.source_label || m.kind}</span>
                                    <span className="mx-1">·</span>
                                    <span>{m.date}</span>
                                    <span className="mx-1">·</span>
                                    <span className="font-mono">{fmtCurrency(m.amount || 0)}</span>
                                    <span className="mx-1">·</span>
                                    <span>{m.vehicle_number}</span>
                                    {m.narration && (
                                      <div className="text-zinc-600 text-[10px] mt-0.5 truncate">{m.narration}</div>
                                    )}
                                  </div>
                                ))}
                                <div className="flex items-center gap-3 pt-1">
                                  <label className="inline-flex items-center gap-1 text-[11px]">
                                    <input type="radio" name={`toll-dup-${r.row_index}`}
                                      data-testid={`toll-override-keep-${r.row_index}`}
                                      checked={decision === "keep"}
                                      onChange={() => setOverrides({ ...overrides, [r.row_index]: "keep" })}/>
                                    <span className="text-emerald-700 font-semibold">Import Anyway</span>
                                  </label>
                                  <label className="inline-flex items-center gap-1 text-[11px]">
                                    <input type="radio" name={`toll-dup-${r.row_index}`}
                                      data-testid={`toll-override-skip-${r.row_index}`}
                                      checked={decision === "skip"}
                                      onChange={() => setOverrides({ ...overrides, [r.row_index]: "skip" })}/>
                                    <span className="text-zinc-700">Skip</span>
                                  </label>
                                  {!decision && (
                                    <span data-testid={`toll-decision-pending-${r.row_index}`}
                                          className="text-[10px] uppercase tracking-wider text-amber-700 font-bold">
                                      · decision required
                                    </span>
                                  )}
                                </div>
                              </div>
                            )}
                            {r.bucket === "ready" && <span className="text-emerald-700">{sel ? `Row ${r.row_index} → ${sel.vehicle_number}` : "OK"}</span>}
                            {r.bucket === "vehicle_mapping_required" && !sel && (
                              <span className="text-sky-700">Pick a TRUKVIA vehicle for THIS row</span>
                            )}
                            {r.bucket === "vehicle_mapping_required" && sel && (
                              <span className="text-emerald-700">Row {r.row_index} → {sel.vehicle_number} · will be imported</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
        <div className="border-t border-zinc-200 px-5 py-3 flex items-center justify-between">
          <div className="text-xs text-zinc-500" data-testid="toll-commit-footer">
            {preview ? (
              <div className="space-y-0.5">
                <div>
                  <span className="text-emerald-700 font-bold" data-testid="toll-footer-import-count">Import {rowsForCommit.length}</span>
                  <span className="mx-2">·</span>
                  <span className="text-zinc-500">Skip <span data-testid="toll-footer-skip-count" className="font-bold">{totalToSkip}</span></span>
                  {unreviewedPossibleDupRows.length > 0 && (
                    <>
                      <span className="mx-2">·</span>
                      <span className="text-amber-700 font-bold" data-testid="toll-footer-pending-review">
                        {unreviewedPossibleDupRows.length} pending review
                      </span>
                    </>
                  )}
                </div>
                <div className="text-[10px] text-zinc-500">
                  <span data-testid="toll-footer-breakdown">
                    Ready {preview.counts.ready + Object.keys(rowSelections).length}
                    <span className="mx-1">·</span>
                    Possible Dup: keep {possibleDupKeepCount} / skip {possibleDupSkipCount} / pending {unreviewedPossibleDupRows.length}
                    <span className="mx-1">·</span>
                    Exact Dup {preview.counts.exact_duplicate || 0}
                    <span className="mx-1">·</span>
                    Errors {preview.counts.error || 0}
                  </span>
                </div>
              </div>
            ) : "Choose a statement to preview."}
          </div>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
            {preview && (
              <button data-testid="toll-commit-btn" onClick={attemptCommit}
                disabled={committing || rowsForCommit.length === 0}
                className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
                {committing ? "Importing…" : `Confirm & Import (${rowsForCommit.length})`}
              </button>
            )}
          </div>
        </div>

        {confirmOpen && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-zinc-900/50 p-6"
               data-testid="toll-commit-confirm-dialog">
            <div className="bg-white border-2 border-amber-500 rounded-sm p-5 max-w-md w-full space-y-3">
              <div className="flex items-center gap-2 text-amber-800">
                <AlertTriangle size={20}/>
                <div className="font-bold uppercase tracking-wider text-sm">Possible duplicates need review</div>
              </div>
              <div className="text-xs text-zinc-700">
                <span className="font-bold">{unreviewedPossibleDupRows.length}</span> row(s) are flagged as possible
                duplicates and still have <span className="font-bold">no decision</span>. If you commit now, those
                rows will NOT be imported. Review each row and pick <span className="font-bold">Import Anyway</span>
                &nbsp;or&nbsp;<span className="font-bold">Skip</span> so nothing is silently excluded.
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button data-testid="toll-commit-confirm-review"
                  onClick={() => { setConfirmOpen(false); setActiveBucket("possible_duplicate"); }}
                  className="px-3 py-1.5 text-[11px] uppercase tracking-wider bg-amber-700 text-white rounded-sm hover:bg-amber-800">
                  Review now
                </button>
                <button data-testid="toll-commit-confirm-proceed"
                  onClick={doCommit}
                  className="px-3 py-1.5 text-[11px] uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-50">
                  Import {rowsForCommit.length} anyway (skip the {unreviewedPossibleDupRows.length} pending)
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
