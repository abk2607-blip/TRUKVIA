import React, { useState } from "react";
import { api, fmtDate } from "@/api";
import { toast } from "sonner";
import { X } from "lucide-react";
import { SearchableSelect } from "@/components/ui/searchable-select";

/* Iter147 P0 UAT · Post-import Vehicle Correction.
 * ------------------------------------------------------------------
 * Narrow, row-level correction dialog for a canonical fleet-card
 * imported Diesel Expense. Reuses:
 *   • PATCH /api/expenses/{eid}/fleet-card-vehicle
 *   • Shared SearchableSelect combobox
 * The persistent FuelVehicleMap is upserted ONLY when the operator
 * explicitly opts in via the checkbox — never silently. */

export default function EditFleetVehicleDialog({ row, vehicles, onClose, onSuccess }) {
  const [newVid, setNewVid] = useState(row.vehicle_id || "");
  const [persist, setPersist] = useState(false);
  const [saving, setSaving] = useState(false);
  const currentVehNum = row.vehicle_number || "—";
  const newVeh = vehicles.find((v) => v.id === newVid);
  const disabled = !newVid || newVid === row.vehicle_id;

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.patch(`/expenses/${row.id}/fleet-card-vehicle`, {
        vehicle_id: newVid,
        persist_mapping: persist,
      });
      if (data?.unchanged) {
        toast.info("No change — same vehicle already assigned.");
      } else {
        toast.success(
          `Vehicle updated: ${data.previous_vehicle_number || "—"} → ${newVeh?.vehicle_number || newVid}`,
        );
      }
      onSuccess?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to update vehicle");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4"
         data-testid="edit-fleet-vehicle-dialog">
      <div className="bg-white w-full max-w-lg border border-zinc-950 rounded-sm">
        <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
          <div>
            <div className="text-[10px] uppercase tracking-[0.15em] text-zinc-500 font-bold">
              Fleet-card Correction · Row-Level
            </div>
            <h3 className="font-bold">Edit Vehicle · {row.source_label}</h3>
          </div>
          <button onClick={onClose} data-testid="close-edit-vehicle-btn"><X size={18} /></button>
        </div>

        <div className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3 text-xs font-mono">
            <F label="Date">{fmtDate(row.date)}</F>
            <F label="Txn Ref">{row.source_txn_ref || "—"}</F>
            <F label="Litres">{Number(row.litres || 0).toFixed(2)}</F>
            <F label="Amount">₹ {Number(row.amount || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</F>
            <F label="Station" className="col-span-2">{row.station_name || "—"}</F>
          </div>

          <div className="border-t border-zinc-200 pt-3 space-y-2">
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Current Vehicle</div>
              <div className="mt-1 font-mono font-bold" data-testid="current-vehicle-number">{currentVehNum}</div>
            </div>
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">New Vehicle *</div>
              <div className="mt-1">
                <SearchableSelect
                  testId="edit-vehicle-select"
                  value={newVid}
                  placeholder="Search TRUKVIA vehicle…"
                  emptyText="No matching vehicles"
                  allowClear={false}
                  onChange={(v) => v && setNewVid(v)}
                  options={vehicles.map((v) => ({
                    value: v.id,
                    label: v.vehicle_number,
                    secondary: (v.vehicle_type || "").toUpperCase() === "SUPPLIER"
                      ? `${v.supplier_name || "Supplier"} · Supplier`
                      : (v.driver_name || (v.vehicle_type || "").toUpperCase()),
                    keywords: [v.vehicle_number, v.driver_name, v.supplier_name].filter(Boolean),
                  }))}
                />
              </div>
            </div>
            <label className="flex items-start gap-2 text-[11px] text-zinc-600 pt-1 select-none">
              <input
                type="checkbox"
                data-testid="persist-mapping-checkbox"
                checked={persist}
                onChange={(e) => setPersist(e.target.checked)}
              />
              <span>
                Save this vehicle mapping for <b>future uploads</b> of the same fleet-card
                identifier. <span className="text-zinc-400">(Off = row-only correction — no
                effect on past or future rows sharing this source ref.)</span>
              </span>
            </label>
          </div>

          <div className="text-[10px] text-zinc-500 border-t border-zinc-200 pt-3 font-mono">
            Source identity preserved · date · litres · amount · station · txn ref · source_key<br />
            Vehicle Cost / Expense Register / Trip Cost reflect the correction automatically.
          </div>
        </div>

        <div className="border-t border-zinc-200 px-5 py-3 flex justify-end gap-2">
          <button onClick={onClose}
            className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">
            Cancel
          </button>
          <button
            data-testid="save-fleet-vehicle-btn"
            onClick={save}
            disabled={disabled || saving}
            className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save Vehicle"}
          </button>
        </div>
      </div>
    </div>
  );
}

function F({ label, children, className = "" }) {
  return (
    <div className={className}>
      <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">{label}</div>
      <div className="mt-1">{children}</div>
    </div>
  );
}
