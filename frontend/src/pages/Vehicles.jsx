import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X, Truck, AlertTriangle, CheckCircle2 } from "lucide-react";

const EMPTY = {
  vehicle_number: "", owner_name: "", make_model: "", capacity_tons: 0,
  rc_expiry: "", fc_expiry: "", insurance_expiry: "", permit_expiry: "", puc_expiry: "",
  notes: "",
};

const DOCS = [
  ["rc_expiry", "RC"],
  ["fc_expiry", "FC"],
  ["insurance_expiry", "Insurance"],
  ["permit_expiry", "Permit"],
  ["puc_expiry", "PUC"],
];

export default function Vehicles() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);

  const { data: vehicles = [] } = useQuery({
    queryKey: ["vehicles"],
    queryFn: async () => (await api.get("/vehicles")).data,
  });

  const save = useMutation({
    mutationFn: async () => {
      const payload = { ...form, capacity_tons: Number(form.capacity_tons) };
      return editing
        ? (await api.put(`/vehicles/${editing.id}`, { ...editing, ...payload })).data
        : (await api.post("/vehicles", payload)).data;
    },
    onSuccess: () => {
      toast.success(editing ? "Vehicle updated" : "Vehicle added");
      qc.invalidateQueries({ queryKey: ["vehicles"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setOpen(false); setEditing(null); setForm(EMPTY);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const del = useMutation({
    mutationFn: async (id) => (await api.delete(`/vehicles/${id}`)).data,
    onSuccess: () => { toast.success("Deleted"); qc.invalidateQueries({ queryKey: ["vehicles"] }); },
  });

  const openEdit = (v) => { setEditing(v); setForm({ ...EMPTY, ...v }); setOpen(true); };
  const openNew = () => { setEditing(null); setForm(EMPTY); setOpen(true); };

  return (
    <div className="space-y-6" data-testid="vehicles-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Master</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">వాహనాలు</span>
            <span className="text-zinc-400"> · Vehicles</span>
          </h1>
        </div>
        <button data-testid="add-vehicle-btn" onClick={openNew} className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2">
          <Plus size={14} /> Add Vehicle
        </button>
      </header>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-x-auto">
        <table className="w-full text-sm" data-testid="vehicles-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-3 py-2 font-semibold">Vehicle</th>
              <th className="text-left px-3 py-2 font-semibold">Owner</th>
              <th className="text-left px-3 py-2 font-semibold">Make/Model</th>
              <th className="text-right px-3 py-2 font-semibold">Cap (T)</th>
              {DOCS.map(([, label]) => (
                <th key={label} className="text-left px-3 py-2 font-semibold">{label}</th>
              ))}
              <th className="text-right px-3 py-2 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {vehicles.map((v) => (
              <tr key={v.id} data-testid={`vehicle-row-${v.id}`} className="border-t border-zinc-100">
                <td className="px-3 py-3 font-mono font-bold flex items-center gap-2"><Truck size={14} className="text-zinc-400" /> {v.vehicle_number}</td>
                <td className="px-3 py-3 text-xs">{v.owner_name || "—"}</td>
                <td className="px-3 py-3 text-xs">{v.make_model || "—"}</td>
                <td className="px-3 py-3 text-right font-mono">{Number(v.capacity_tons || 0).toFixed(1)}</td>
                {DOCS.map(([field]) => {
                  const a = v.alerts?.[field];
                  return (
                    <td key={field} className="px-3 py-3 text-xs">
                      {a ? (
                        <ExpiryBadge alert={a} />
                      ) : <span className="text-zinc-400">—</span>}
                    </td>
                  );
                })}
                <td className="px-3 py-3 text-right whitespace-nowrap">
                  <button data-testid={`edit-vehicle-${v.id}`} onClick={() => openEdit(v)} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-zinc-200 rounded-sm mr-2 hover:bg-zinc-950 hover:text-white">
                    <Pencil size={12} /> Edit
                  </button>
                  <button data-testid={`delete-vehicle-${v.id}`} onClick={() => { if (window.confirm("Delete?")) del.mutate(v.id); }} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-50">
                    <Trash2 size={12} /> Delete
                  </button>
                </td>
              </tr>
            ))}
            {vehicles.length === 0 && (
              <tr><td colSpan={11} className="px-4 py-12 text-center text-zinc-400">No vehicles registered.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4" data-testid="vehicle-modal">
          <div className="bg-white w-full max-w-2xl border border-zinc-950 rounded-sm">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
              <h3 className="font-bold">{editing ? "Edit Vehicle" : "New Vehicle"}</h3>
              <button onClick={() => setOpen(false)}><X size={18} /></button>
            </div>
            <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="p-5 grid grid-cols-1 md:grid-cols-2 gap-3">
              <F label="Vehicle Number *"><input data-testid="vehicle-number" required value={form.vehicle_number} onChange={(e) => setForm({ ...form, vehicle_number: e.target.value.toUpperCase() })} className={ic} placeholder="AP16TA1234" /></F>
              <F label="Owner Name"><input data-testid="vehicle-owner" value={form.owner_name} onChange={(e) => setForm({ ...form, owner_name: e.target.value })} className={ic} /></F>
              <F label="Make/Model"><input data-testid="vehicle-model" value={form.make_model} onChange={(e) => setForm({ ...form, make_model: e.target.value })} className={ic} placeholder="Tata LPT 3118" /></F>
              <F label="Capacity (Tons)"><input data-testid="vehicle-capacity" type="number" step="0.1" min="0" value={form.capacity_tons} onChange={(e) => setForm({ ...form, capacity_tons: e.target.value })} className={ic} /></F>
              {DOCS.map(([field, label]) => (
                <F key={field} label={`${label} Expiry`}>
                  <input data-testid={`vehicle-${field}`} type="date" value={form[field] || ""} onChange={(e) => setForm({ ...form, [field]: e.target.value })} className={ic} />
                </F>
              ))}
              <div className="md:col-span-2">
                <F label="Notes"><textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={ic} /></F>
              </div>
              <div className="md:col-span-2 flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setOpen(false)} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
                <button data-testid="save-vehicle-btn" type="submit" disabled={save.isPending} className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
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

function ExpiryBadge({ alert }) {
  const style =
    alert.status === "expired"
      ? "bg-rose-50 border-rose-300 text-rose-800"
      : alert.status === "expiring"
      ? "bg-amber-50 border-amber-300 text-amber-800"
      : "bg-emerald-50 border-emerald-300 text-emerald-800";
  const Icon = alert.status === "ok" ? CheckCircle2 : AlertTriangle;
  return (
    <div className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm border font-mono ${style}`}>
      <Icon size={10} />
      <span>{alert.date}</span>
      <span className="text-[10px]">({alert.days >= 0 ? `${alert.days}d` : `${Math.abs(alert.days)}d ago`})</span>
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
