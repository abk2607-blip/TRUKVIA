import React, { useState } from "react";
import { api, fmtCurrency } from "@/api";
import { toast } from "sonner";
import { X } from "lucide-react";

/* Iter147 P0 · Manual Fuel entry — canonical Expense writer.
 * Same accounting path as Quick Op / Fleet-card Import. No paired
 * db.fuel row. Reused by the Unified Fuel Log. */

const EMPTY = () => ({
  date: new Date().toISOString().slice(0, 10),
  vehicle_id: "",
  litres: "", rate: "", station_name: "",
  odometer: "", remarks: "",
});

export default function ManualFuelDialog({ vehicles, onClose, onSuccess }) {
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);

  const liveAmt = (Number(form.litres) || 0) * (Number(form.rate) || 0);

  const save = async (e) => {
    e.preventDefault();
    if (!form.vehicle_id) return toast.error("Select a vehicle");
    if (!(Number(form.litres) > 0) || !(Number(form.rate) > 0)) {
      return toast.error("Litres and rate must both be > 0");
    }
    setSaving(true);
    try {
      await api.post("/fuel-manual", {
        date: form.date,
        vehicle_id: form.vehicle_id,
        litres: Number(form.litres),
        rate: Number(form.rate),
        station_name: form.station_name,
        odometer: Number(form.odometer) || 0,
        remarks: form.remarks,
      });
      toast.success(`Manual Diesel entry saved · ${fmtCurrency(liveAmt)}`);
      onSuccess?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4"
         data-testid="manual-fuel-dialog">
      <div className="bg-white w-full max-w-lg border border-zinc-950 rounded-sm">
        <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
          <div>
            <div className="text-[10px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Canonical Expense</div>
            <h3 className="font-bold">Manual Diesel Entry</h3>
          </div>
          <button onClick={onClose} data-testid="close-manual-btn"><X size={18} /></button>
        </div>
        <form onSubmit={save} className="p-5 grid grid-cols-1 md:grid-cols-2 gap-3">
          <F label="Date *">
            <input required data-testid="manual-date" type="date" value={form.date}
              onChange={(e) => setForm({ ...form, date: e.target.value })} className={ic} />
          </F>
          <F label="Vehicle *">
            <select required data-testid="manual-vehicle" value={form.vehicle_id}
              onChange={(e) => setForm({ ...form, vehicle_id: e.target.value })} className={ic}>
              <option value="">-- select --</option>
              {vehicles.map((v) => <option key={v.id} value={v.id}>{v.vehicle_number}</option>)}
            </select>
          </F>
          <F label="Litres *">
            <input required data-testid="manual-litres" type="number" step="0.01" min="0" value={form.litres}
              onChange={(e) => setForm({ ...form, litres: e.target.value })} className={ic} />
          </F>
          <F label="Rate (₹/L) *">
            <input required data-testid="manual-rate" type="number" step="0.01" min="0" value={form.rate}
              onChange={(e) => setForm({ ...form, rate: e.target.value })} className={ic} />
          </F>
          <F label="Amount (server-authoritative)">
            <div className={`${ic} bg-amber-50 font-mono font-bold`} data-testid="manual-amount">{fmtCurrency(liveAmt)}</div>
          </F>
          <F label="Odometer">
            <input data-testid="manual-odometer" type="number" step="0.01" min="0" value={form.odometer}
              onChange={(e) => setForm({ ...form, odometer: e.target.value })} className={ic} />
          </F>
          <div className="md:col-span-2">
            <F label="Fuel Station">
              <input data-testid="manual-station" value={form.station_name}
                onChange={(e) => setForm({ ...form, station_name: e.target.value })}
                className={ic} placeholder="HP - NH16 Bypass" />
            </F>
          </div>
          <div className="md:col-span-2">
            <F label="Remarks">
              <input data-testid="manual-remarks" value={form.remarks}
                onChange={(e) => setForm({ ...form, remarks: e.target.value })} className={ic} />
            </F>
          </div>
          <div className="md:col-span-2 flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose}
              className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
            <button data-testid="save-manual-fuel-btn" type="submit" disabled={saving}
              className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
              {saving ? "Saving…" : "Save Diesel Entry"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

const ic = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";

function F({ label, children }) {
  return (
    <div>
      <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">{label}</label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
