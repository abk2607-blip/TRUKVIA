import React, { useMemo, useState } from "react";
import { api, fmtCurrency } from "@/api";
import { toast } from "sonner";
import { X, Upload, CheckCircle2, AlertTriangle, XCircle, Link2 } from "lucide-react";
import { SearchableSelect } from "@/components/ui/searchable-select";

/* Iter147 P0 · Fleet-card Import Wizard.
 * ------------------------------------------------------------------
 * Flow: Upload → Preview (5 buckets) → Map vehicles inline →
 *       Confirm & Commit → per-row result.
 * Server enforces auto-detection, dup detection, and canonical write.
 * The wizard is purely a driver of that state machine. */

const BUCKET_META = {
  ready:                    { label: "Ready to Import",      color: "text-emerald-700 border-emerald-300 bg-emerald-50",   icon: CheckCircle2 },
  vehicle_mapping_required: { label: "Vehicle Mapping",       color: "text-sky-700 border-sky-300 bg-sky-50",              icon: Link2 },
  possible_duplicate:       { label: "Possible Duplicate",   color: "text-amber-700 border-amber-300 bg-amber-50",         icon: AlertTriangle },
  exact_duplicate:          { label: "Exact Duplicate",      color: "text-zinc-600 border-zinc-300 bg-zinc-50",            icon: XCircle },
  error:                    { label: "Error / Invalid",     color: "text-rose-700 border-rose-300 bg-rose-50",             icon: XCircle },
};

export default function FuelImportWizard({ source, vehicles, onClose, onSuccess }) {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [preview, setPreview] = useState(null); // { source, rows, counts, unmapped_refs }
  const [activeBucket, setActiveBucket] = useState("ready");
  const [overrides, setOverrides] = useState({});          // row_index -> "keep" | "skip"
  const [rowMaps, setRowMaps] = useState({});              // source_vehicle_ref -> vehicle_id (staged during wizard)

  const doPreview = async () => {
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post("/fuel-import/preview", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      if ((data.source || "").toLowerCase() !== source) {
        toast.error(`File appears to be ${(data.source || "unknown").toUpperCase()} — expected ${source.toUpperCase()}`);
      }
      setPreview(data);
      const firstNonZero = ["ready", "vehicle_mapping_required", "possible_duplicate", "exact_duplicate", "error"]
        .find((b) => (data.counts?.[b] || 0) > 0) || "ready";
      setActiveBucket(firstNonZero);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Preview failed");
      setPreview(null);
    } finally {
      setUploading(false);
    }
  };

  const saveMapping = async (sref, vehicleId) => {
    try {
      const veh = vehicles.find((v) => v.id === vehicleId);
      await api.post("/fuel/vehicle-maps", {
        source, source_vehicle_ref: sref, vehicle_id: vehicleId,
      });
      setRowMaps((m) => ({ ...m, [sref]: { vehicle_id: vehicleId, vehicle_number: veh?.vehicle_number || "" } }));
      toast.success(`Mapped ${sref} → ${veh?.vehicle_number || vehicleId}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to save mapping");
    }
  };

  const rowsForCommit = useMemo(() => {
    if (!preview) return [];
    return preview.rows
      .map((r) => {
        // Apply staged in-wizard mapping if the row was originally unmapped.
        if (!r.resolved_vehicle_id && rowMaps[r.source_vehicle_ref]) {
          return {
            ...r,
            bucket: "ready",
            resolved_vehicle_id: rowMaps[r.source_vehicle_ref].vehicle_id,
            resolved_vehicle_number: rowMaps[r.source_vehicle_ref].vehicle_number,
          };
        }
        return r;
      })
      .filter((r) => {
        if (r.bucket === "exact_duplicate" || r.bucket === "error") return false;
        if (r.bucket === "possible_duplicate" && overrides[r.row_index] !== "keep") return false;
        if (!r.resolved_vehicle_id) return false;
        return true;
      });
  }, [preview, overrides, rowMaps]);

  const doCommit = async () => {
    if (!preview) return;
    if (rowsForCommit.length === 0) {
      toast.error("Nothing to import. Map unmapped vehicles or approve possible duplicates.");
      return;
    }
    setCommitting(true);
    try {
      const { data } = await api.post("/fuel-import/commit", {
        source, rows: rowsForCommit,
      });
      toast.success(`Imported ${data.created} · ${data.duplicate} duplicate · ${data.failed} failed`);
      onSuccess?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Import commit failed");
    } finally {
      setCommitting(false);
    }
  };

  const visibleRows = preview?.rows.filter((r) => {
    // If a mapping was staged, force the row into ready bucket
    if (activeBucket === "ready") {
      return r.bucket === "ready" || (r.bucket === "vehicle_mapping_required" && rowMaps[r.source_vehicle_ref]);
    }
    if (activeBucket === "vehicle_mapping_required") {
      return r.bucket === "vehicle_mapping_required" && !rowMaps[r.source_vehicle_ref];
    }
    return r.bucket === activeBucket;
  }) || [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-3 md:p-6"
         data-testid="fuel-import-wizard">
      {/* Iter147 P0 UAT-fix (2026-09-09) · Desktop-friendly modal:
          w-[95vw] h-[85vh] gives operators room to comfortably read
          IOCL/BPCL Diesel rows and all preview columns without
          horizontal squeezing. Vertical scroll stays internal. */}
      <div
        data-testid="fuel-import-wizard-shell"
        className="bg-white w-[95vw] max-w-[1600px] h-[85vh] border border-zinc-950 rounded-sm flex flex-col overflow-hidden"
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
          <div>
            <div className="text-[10px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Fleet-card Import</div>
            <h3 className="font-bold text-lg">Import {source.toUpperCase()} Diesel</h3>
          </div>
          <button data-testid="close-wizard-btn" onClick={onClose}><X size={18} /></button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {!preview && (
            <div className="p-6 space-y-4">
              <div className="border-2 border-dashed border-zinc-300 rounded-sm p-8 text-center bg-white">
                <Upload size={32} className="mx-auto text-zinc-400" />
                <div className="mt-2 text-sm font-semibold">
                  Upload the ORIGINAL {source.toUpperCase()} statement file
                </div>
                <div className="text-xs text-zinc-500 mt-1">
                  {source === "iocl" ? "IOCL: legacy .xls file (Customer Transaction Details Report)"
                                     : "BPCL: .xlsx file (Sale Transaction history report)"}
                </div>
                <label className="inline-flex items-center gap-2 mt-4 px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm cursor-pointer hover:bg-zinc-800">
                  {file ? file.name : "Choose file"}
                  <input
                    data-testid="wizard-file-input"
                    type="file"
                    accept={source === "iocl" ? ".xls" : ".xlsx"}
                    className="hidden"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                  />
                </label>
                {file && (
                  <div className="mt-2 text-xs text-zinc-500">{(file.size / 1024).toFixed(1)} KB</div>
                )}
              </div>
              <div className="flex justify-end">
                <button
                  data-testid="wizard-preview-btn"
                  disabled={!file || uploading}
                  onClick={doPreview}
                  className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50"
                >
                  {uploading ? "Parsing…" : "Preview"}
                </button>
              </div>
            </div>
          )}

          {preview && (
            <div className="p-4 space-y-4">
              {/* Bucket tabs */}
              <div className="flex flex-wrap gap-2" data-testid="wizard-buckets">
                {Object.entries(BUCKET_META).map(([k, meta]) => {
                  const isMappedNow = k === "ready"
                    ? preview.counts.ready + Object.values(rowMaps).length
                    : k === "vehicle_mapping_required"
                      ? Math.max(0, preview.counts.vehicle_mapping_required - Object.values(rowMaps).length)
                      : preview.counts[k];
                  const Icon = meta.icon;
                  return (
                    <button
                      key={k}
                      data-testid={`bucket-${k}`}
                      onClick={() => setActiveBucket(k)}
                      className={`inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider border rounded-sm ${activeBucket === k ? "bg-zinc-950 text-white border-zinc-950" : `${meta.color} hover:opacity-80`}`}
                    >
                      <Icon size={14} /> {meta.label} <span className="font-mono font-bold">{isMappedNow || 0}</span>
                    </button>
                  );
                })}
              </div>

              {/* Rows table — wrapped so long tables scroll horizontally only when required */}
              <div className="border border-zinc-200 rounded-sm overflow-auto">
                <table className="w-full text-xs min-w-[1100px]" data-testid="wizard-rows-table">
                  <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
                    <tr>
                      <th className="text-left px-3 py-2">Row</th>
                      <th className="text-left px-3 py-2">Date</th>
                      <th className="text-left px-3 py-2">Src Vehicle Ref</th>
                      <th className="text-left px-3 py-2">TRUKVIA Vehicle</th>
                      <th className="text-right px-3 py-2">Litres</th>
                      <th className="text-right px-3 py-2">Rate</th>
                      <th className="text-right px-3 py-2">Amount</th>
                      <th className="text-left px-3 py-2">Txn Ref</th>
                      <th className="text-left px-3 py-2">Note</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono">
                    {visibleRows.length === 0 && (
                      <tr><td colSpan={9} className="px-4 py-8 text-center text-zinc-400">
                        No rows in this bucket.
                      </td></tr>
                    )}
                    {visibleRows.map((r) => {
                      const staged = rowMaps[r.source_vehicle_ref];
                      const vehId = staged?.vehicle_id || r.resolved_vehicle_id || "";
                      const vehNum = staged?.vehicle_number || r.resolved_vehicle_number || "";
                      return (
                        <tr key={`${r.row_index}:${r.source_txn_ref}`} data-testid={`wizard-row-${r.row_index}`} className="border-t border-zinc-100">
                          <td className="px-3 py-1.5">{r.row_index}</td>
                          <td className="px-3 py-1.5">{r.date}</td>
                          <td className="px-3 py-1.5 font-semibold">{r.source_vehicle_ref}</td>
                          <td className="px-3 py-1.5 min-w-[240px]">
                            {activeBucket === "vehicle_mapping_required" ? (
                              /* Iter147 P0 UAT-fix (2026-09-09) · Reuses the
                                 shared shadcn SearchableSelect combobox
                                 (same pattern as Quick Op / Expense Register)
                                 so operators can type-to-search a TRUKVIA
                                 vehicle instead of scrolling a long list.
                                 Selecting once persists a FuelVehicleMap
                                 keyed by (source, source_vehicle_ref) and
                                 the staged mapping applies to every row
                                 with the same source_vehicle_ref in this
                                 preview via `rowMaps` lookup below. */
                              <SearchableSelect
                                testId={`map-select-${r.row_index}`}
                                value={staged?.vehicle_id || ""}
                                placeholder="Search TRUKVIA vehicle…"
                                emptyText="No matching vehicles"
                                allowClear={false}
                                onChange={(v) => v && saveMapping(r.source_vehicle_ref, v)}
                                options={vehicles.map((v) => ({
                                  value: v.id,
                                  label: v.vehicle_number,
                                  secondary: (v.vehicle_type || "").toUpperCase() === "SUPPLIER"
                                    ? `${v.supplier_name || "Supplier"} · Supplier`
                                    : (v.driver_name || (v.vehicle_type || "").toUpperCase()),
                                  keywords: [v.vehicle_number, v.driver_name, v.supplier_name]
                                    .filter(Boolean),
                                }))}
                              />
                            ) : (
                              <span className="font-semibold">{vehNum || "—"}</span>
                            )}
                          </td>
                          <td className="px-3 py-1.5 text-right">{Number(r.litres || 0).toFixed(2)}</td>
                          <td className="px-3 py-1.5 text-right">{fmtCurrency(r.rate || 0)}</td>
                          <td className="px-3 py-1.5 text-right font-semibold">{fmtCurrency(r.amount || 0)}</td>
                          <td className="px-3 py-1.5 text-xs">{r.source_txn_ref || "—"}</td>
                          <td className="px-3 py-1.5 text-xs">
                            {r.bucket === "error" && <span className="text-rose-700">{r.error}</span>}
                            {r.bucket === "exact_duplicate" && <span className="text-zinc-500">{r.duplicate_reason}</span>}
                            {r.bucket === "possible_duplicate" && (
                              <div className="space-y-1">
                                <div className="text-amber-700">
                                  {r.possible_matches?.length || 0} similar existing txn(s)
                                </div>
                                {r.possible_matches?.slice(0, 2).map((m, i) => (
                                  <div key={i} className="text-[10px] text-zinc-500">
                                    • {m.source_label}: {m.date} {fmtCurrency(m.amount)} · {m.narration}
                                  </div>
                                ))}
                                <label className="inline-flex items-center gap-1 text-[11px] mt-1">
                                  <input
                                    type="checkbox"
                                    data-testid={`override-${r.row_index}`}
                                    checked={overrides[r.row_index] === "keep"}
                                    onChange={(e) => setOverrides({ ...overrides, [r.row_index]: e.target.checked ? "keep" : "skip" })}
                                  />
                                  Import anyway
                                </label>
                              </div>
                            )}
                            {r.bucket === "ready" && <span className="text-emerald-700">OK</span>}
                            {r.bucket === "vehicle_mapping_required" && !staged && (
                              <span className="text-sky-700">Pick a TRUKVIA vehicle to map & auto-resolve future uploads</span>
                            )}
                            {r.bucket === "vehicle_mapping_required" && staged && (
                              <span className="text-emerald-700">Mapped · will be imported</span>
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
          <div className="text-xs text-zinc-500">
            {preview ? (
              <>
                Rows selected for import: <span className="font-bold text-zinc-950" data-testid="commit-count">{rowsForCommit.length}</span>
                {" · "}Total in file: <span className="font-bold">{preview.total_rows}</span>
              </>
            ) : "Choose a statement file to preview the buckets."}
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm"
            >Cancel</button>
            {preview && (
              <button
                data-testid="wizard-commit-btn"
                onClick={doCommit}
                disabled={committing || rowsForCommit.length === 0}
                className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50"
              >
                {committing ? "Importing…" : `Confirm & Import (${rowsForCommit.length})`}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
