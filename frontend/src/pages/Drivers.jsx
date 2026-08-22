import React, { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, fmtCurrency } from "@/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X, Truck, Wallet, Search } from "lucide-react";
import { Link } from "react-router-dom";

const EMPTY = { name: "", phone: "", license_number: "", notes: "" };

export default function Drivers() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [q, setQ] = useState(""); // Iter80 — restore master search

  const { data: drivers = [] } = useQuery({
    queryKey: ["drivers"],
    queryFn: async () => (await api.get("/drivers")).data,
  });

  const filteredDrivers = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return drivers;
    return drivers.filter((d) =>
      [d.name, d.phone, d.license_number]
        .filter(Boolean)
        .some((s) => String(s).toLowerCase().includes(query))
    );
  }, [drivers, q]);

  const save = useMutation({
    mutationFn: async () =>
      editing
        ? (await api.put(`/drivers/${editing.id}`, { ...editing, ...form })).data
        : (await api.post("/drivers", form)).data,
    onSuccess: () => {
      toast.success(editing ? "Driver updated" : "Driver added");
      qc.invalidateQueries({ queryKey: ["drivers"] });
      setOpen(false); setEditing(null); setForm(EMPTY);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const del = useMutation({
    mutationFn: async (id) => (await api.delete(`/drivers/${id}`)).data,
    onSuccess: () => { toast.success("Deleted"); qc.invalidateQueries({ queryKey: ["drivers"] }); },
  });

  const openEdit = (d) => { setEditing(d); setForm({ ...EMPTY, ...d }); setOpen(true); };
  const openNew = () => { setEditing(null); setForm(EMPTY); setOpen(true); };

  return (
    <div className="space-y-6" data-testid="drivers-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Master</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">డ్రైవర్లు</span>
            <span className="text-zinc-400"> · Drivers</span>
          </h1>
        </div>
        <button data-testid="add-driver-btn" onClick={openNew} className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2">
          <Plus size={14} /> Add Driver
        </button>
      </header>

      {/* Iter80 — master search bar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            data-testid="driver-search-input"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name, phone or license…"
            className="w-full border border-zinc-300 pl-9 pr-9 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white"
          />
          {q && (
            <button
              type="button"
              data-testid="driver-search-clear"
              onClick={() => setQ("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-rose-600"
            >
              <X size={14} />
            </button>
          )}
        </div>
        <div className="text-xs text-zinc-500" data-testid="driver-search-count">
          {q ? `${filteredDrivers.length} match${filteredDrivers.length === 1 ? "" : "es"}` : `${drivers.length} drivers`}
        </div>
      </div>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
        <table className="w-full text-sm" data-testid="drivers-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-4 py-2 font-semibold">Name</th>
              <th className="text-left px-4 py-2 font-semibold">Phone</th>
              <th className="text-left px-4 py-2 font-semibold">License</th>
              <th className="text-right px-4 py-2 font-semibold">Trips</th>
              <th className="text-right px-4 py-2 font-semibold">Tons</th>
              <th className="text-right px-4 py-2 font-semibold">Batta Total</th>
              <th className="text-right px-4 py-2 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredDrivers.map((d) => (
              <tr key={d.id} data-testid={`driver-row-${d.id}`} className="border-t border-zinc-100 hover:bg-zinc-50">
                <td className="px-4 py-3 font-semibold flex items-center gap-2">
                  <Truck size={14} className="text-zinc-400" />
                  {/* Iter104 · Option A — clicking the Name opens the existing
                      Driver Trip History details page. Existing History/Ledger/
                      Edit/Delete buttons untouched. */}
                  <Link
                    to={`/drivers/${d.id}/history`}
                    data-testid={`view-driver-${d.id}`}
                    className="hover:text-indigo-700 hover:underline"
                    title="View driver details"
                  >
                    {d.name}
                  </Link>
                </td>
                <td className="px-4 py-3 font-mono text-xs">{d.phone || "—"}</td>
                <td className="px-4 py-3 font-mono text-xs">{d.license_number || "—"}</td>
                <td className="px-4 py-3 text-right font-mono">{d.stats?.trips ?? 0}</td>
                <td className="px-4 py-3 text-right font-mono">{Number(d.stats?.tons ?? 0).toFixed(2)}</td>
                <td className="px-4 py-3 text-right font-mono text-amber-800">{fmtCurrency(d.stats?.batta ?? 0)}</td>
                <td className="px-4 py-3 text-right">
                  <Link to={`/drivers/${d.id}/history`} data-testid={`history-driver-${d.id}`} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-indigo-200 text-indigo-700 rounded-sm mr-2 hover:bg-indigo-50">
                    <Truck size={12} /> History
                  </Link>
                  <Link to={`/drivers/${d.id}/ledger`} data-testid={`ledger-driver-${d.id}`} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-emerald-200 text-emerald-700 rounded-sm mr-2 hover:bg-emerald-50">
                    <Wallet size={12} /> Ledger
                  </Link>
                  <button data-testid={`edit-driver-${d.id}`} onClick={() => openEdit(d)} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-zinc-200 rounded-sm mr-2 hover:bg-zinc-950 hover:text-white">
                    <Pencil size={12} /> Edit
                  </button>
                  <button data-testid={`delete-driver-${d.id}`} onClick={() => { if (window.confirm("Delete this driver?")) del.mutate(d.id); }} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-50">
                    <Trash2 size={12} /> Delete
                  </button>
                </td>
              </tr>
            ))}
            {filteredDrivers.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-12 text-center text-zinc-400">{q ? `No drivers match “${q}”.` : "No drivers yet. Add drivers to pick them from trip dropdowns."}</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4" data-testid="driver-modal">
          <div className="bg-white w-full max-w-md border border-zinc-950 rounded-sm">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
              <h3 className="font-bold">{editing ? "Edit Driver" : "New Driver"}</h3>
              <button onClick={() => setOpen(false)}><X size={18} /></button>
            </div>
            <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="p-5 space-y-3">
              <F label="Name · పేరు *"><input data-testid="driver-name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={ic} /></F>
              <F label="Phone · ఫోన్"><input data-testid="driver-phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className={ic} /></F>
              <F label="License No · లైసెన్స్"><input data-testid="driver-license" value={form.license_number} onChange={(e) => setForm({ ...form, license_number: e.target.value })} className={ic} /></F>
              <F label="Notes"><textarea rows={2} data-testid="driver-notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={ic} /></F>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setOpen(false)} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
                <button data-testid="save-driver-btn" type="submit" disabled={save.isPending} className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
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
