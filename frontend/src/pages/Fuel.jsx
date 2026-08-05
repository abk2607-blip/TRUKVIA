import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate } from "@/api";
import { toast } from "sonner";
import { Plus, Trash2, X, Fuel as FuelIcon, TrendingUp } from "lucide-react";

const EMPTY = {
  date: new Date().toISOString().slice(0, 10),
  vehicle_id: "", vehicle_number: "",
  litres: 0, rate_per_litre: 0, amount: 0,
  odometer: 0, station_name: "", notes: "",
};

export default function Fuel() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);

  const { data: entries = [] } = useQuery({
    queryKey: ["fuel"],
    queryFn: async () => (await api.get("/fuel")).data,
  });
  const { data: summary } = useQuery({
    queryKey: ["fuel-summary"],
    queryFn: async () => (await api.get("/fuel/summary")).data,
  });
  const { data: vehicles = [] } = useQuery({
    queryKey: ["vehicles"],
    queryFn: async () => (await api.get("/vehicles")).data,
  });

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        ...form,
        litres: Number(form.litres),
        rate_per_litre: Number(form.rate_per_litre),
        amount: Number(form.amount) || Number(form.litres) * Number(form.rate_per_litre),
        odometer: Number(form.odometer || 0),
      };
      return (await api.post("/fuel", payload)).data;
    },
    onSuccess: () => {
      toast.success("Fuel entry added");
      qc.invalidateQueries({ queryKey: ["fuel"] });
      qc.invalidateQueries({ queryKey: ["fuel-summary"] });
      setOpen(false); setForm(EMPTY);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const del = useMutation({
    mutationFn: async (id) => (await api.delete(`/fuel/${id}`)).data,
    onSuccess: () => { toast.success("Deleted"); qc.invalidateQueries({ queryKey: ["fuel"] }); qc.invalidateQueries({ queryKey: ["fuel-summary"] }); },
  });

  const openNew = () => { setForm(EMPTY); setOpen(true); };
  const liveAmt = (Number(form.litres) || 0) * (Number(form.rate_per_litre) || 0);

  return (
    <div className="space-y-6" data-testid="fuel-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Log</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">డీజిల్ లాగ్</span>
            <span className="text-zinc-400"> · Fuel Log</span>
          </h1>
        </div>
        <button data-testid="add-fuel-btn" onClick={openNew} className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2">
          <Plus size={14} /> New Fill
        </button>
      </header>

      {summary?.by_vehicle?.length > 0 && (
        <section className="border border-zinc-200 bg-white rounded-sm">
          <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider flex items-center gap-2">
            <TrendingUp size={14} /> By Vehicle
          </div>
          <table className="w-full text-sm" data-testid="fuel-summary-table">
            <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="text-left px-4 py-2">Vehicle</th>
                <th className="text-right px-4 py-2">Fills</th>
                <th className="text-right px-4 py-2">Litres</th>
                <th className="text-right px-4 py-2">Amount</th>
                <th className="text-right px-4 py-2">KM Run</th>
                <th className="text-right px-4 py-2">Km/Litre</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {summary.by_vehicle.map((s) => (
                <tr key={s.vehicle_number} className="border-t border-zinc-100">
                  <td className="px-4 py-2 font-semibold">{s.vehicle_number}</td>
                  <td className="px-4 py-2 text-right">{s.entries}</td>
                  <td className="px-4 py-2 text-right">{s.litres.toFixed(2)}</td>
                  <td className="px-4 py-2 text-right">{fmtCurrency(s.amount)}</td>
                  <td className="px-4 py-2 text-right">{s.km_run.toFixed(0)}</td>
                  <td className={`px-4 py-2 text-right font-bold ${s.km_per_litre >= 3 ? "text-emerald-700" : s.km_per_litre > 0 ? "text-amber-700" : "text-zinc-400"}`}>
                    {s.km_per_litre > 0 ? s.km_per_litre.toFixed(2) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="border border-zinc-200 bg-white rounded-sm">
        <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider flex items-center gap-2">
          <FuelIcon size={14} /> Fill-up Log
        </div>
        <table className="w-full text-sm" data-testid="fuel-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-4 py-2">Date</th>
              <th className="text-left px-4 py-2">Vehicle</th>
              <th className="text-right px-4 py-2">Litres</th>
              <th className="text-right px-4 py-2">Rate</th>
              <th className="text-right px-4 py-2">Amount</th>
              <th className="text-right px-4 py-2">Odo</th>
              <th className="text-left px-4 py-2">Station</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {entries.map((f) => (
              <tr key={f.id} data-testid={`fuel-row-${f.id}`} className="border-t border-zinc-100">
                <td className="px-4 py-2 text-xs">{fmtDate(f.date)}</td>
                <td className="px-4 py-2 font-semibold">{f.vehicle_number}</td>
                <td className="px-4 py-2 text-right">{Number(f.litres).toFixed(2)}</td>
                <td className="px-4 py-2 text-right">{fmtCurrency(f.rate_per_litre)}</td>
                <td className="px-4 py-2 text-right font-semibold">{fmtCurrency(f.amount)}</td>
                <td className="px-4 py-2 text-right">{f.odometer ? Number(f.odometer).toFixed(0) : "—"}</td>
                <td className="px-4 py-2 text-xs text-zinc-600">{f.station_name || "—"}</td>
                <td className="px-4 py-2 text-right">
                  <button data-testid={`delete-fuel-${f.id}`} onClick={() => { if (window.confirm("Delete?")) del.mutate(f.id); }} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-50">
                    <Trash2 size={12} />
                  </button>
                </td>
              </tr>
            ))}
            {entries.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-zinc-400">No fuel entries yet.</td></tr>
            )}
          </tbody>
        </table>
      </section>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4" data-testid="fuel-modal">
          <div className="bg-white w-full max-w-lg border border-zinc-950 rounded-sm">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
              <h3 className="font-bold">New Fuel Fill</h3>
              <button onClick={() => setOpen(false)}><X size={18} /></button>
            </div>
            <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="p-5 grid grid-cols-1 md:grid-cols-2 gap-3">
              <F label="Date *"><input required data-testid="fuel-date" type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={ic} /></F>
              <F label="Vehicle *">
                <select
                  data-testid="fuel-vehicle"
                  required
                  value={form.vehicle_id || form.vehicle_number}
                  onChange={(e) => {
                    const v = vehicles.find((x) => x.id === e.target.value);
                    if (v) setForm({ ...form, vehicle_id: v.id, vehicle_number: v.vehicle_number });
                    else setForm({ ...form, vehicle_id: "", vehicle_number: e.target.value });
                  }}
                  className={ic}
                >
                  <option value="">-- Select --</option>
                  {vehicles.map((v) => <option key={v.id} value={v.id}>{v.vehicle_number}</option>)}
                </select>
              </F>
              <F label="Litres *"><input required data-testid="fuel-litres" type="number" step="0.01" min="0" value={form.litres} onChange={(e) => setForm({ ...form, litres: e.target.value })} className={ic} /></F>
              <F label="Rate (₹/L) *"><input required data-testid="fuel-rate" type="number" step="0.01" min="0" value={form.rate_per_litre} onChange={(e) => setForm({ ...form, rate_per_litre: e.target.value })} className={ic} /></F>
              <F label="Amount (auto)">
                <div className={`${ic} bg-amber-50 font-mono font-bold`}>{fmtCurrency(liveAmt)}</div>
              </F>
              <F label="Odometer"><input data-testid="fuel-odo" type="number" step="0.01" min="0" value={form.odometer} onChange={(e) => setForm({ ...form, odometer: e.target.value })} className={ic} /></F>
              <div className="md:col-span-2">
                <F label="Station"><input data-testid="fuel-station" value={form.station_name} onChange={(e) => setForm({ ...form, station_name: e.target.value })} className={ic} placeholder="HP - NH16 Bypass" /></F>
              </div>
              <div className="md:col-span-2 flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setOpen(false)} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
                <button data-testid="save-fuel-btn" type="submit" disabled={save.isPending} className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
                  {save.isPending ? "Saving..." : "Save"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
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
