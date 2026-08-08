import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X, FileText } from "lucide-react";
import { StateSelect } from "@/lib/states";

const EMPTY = { name: "", address: "", phone: "", gstin: "", pan: "", state: "" };

export default function Customers() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);

  const { data: customers = [], isLoading } = useQuery({
    queryKey: ["customers"],
    queryFn: async () => (await api.get("/customers")).data,
  });

  const save = useMutation({
    mutationFn: async () => {
      if (editing) {
        return (await api.put(`/customers/${editing.id}`, { ...editing, ...form })).data;
      }
      return (await api.post("/customers", form)).data;
    },
    onSuccess: () => {
      toast.success(editing ? "Customer updated" : "Customer created");
      qc.invalidateQueries({ queryKey: ["customers"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setOpen(false); setEditing(null); setForm(EMPTY);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed to save"),
  });

  const del = useMutation({
    mutationFn: async (id) => (await api.delete(`/customers/${id}`)).data,
    onSuccess: () => { toast.success("Deleted"); qc.invalidateQueries({ queryKey: ["customers"] }); },
  });

  const openEdit = (c) => { setEditing(c); setForm({ ...EMPTY, ...c }); setOpen(true); };
  const openNew = () => { setEditing(null); setForm(EMPTY); setOpen(true); };

  return (
    <div className="space-y-6" data-testid="customers-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Master</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">కస్టమర్లు</span>
            <span className="text-zinc-400"> · Customers</span>
          </h1>
        </div>
        <button data-testid="add-customer-btn" onClick={openNew} className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2">
          <Plus size={14} /> Add Customer
        </button>
      </header>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
        <table className="w-full text-sm" data-testid="customers-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-4 py-2 font-semibold">Name</th>
              <th className="text-left px-4 py-2 font-semibold">GSTIN</th>
              <th className="text-left px-4 py-2 font-semibold">Phone</th>
              <th className="text-left px-4 py-2 font-semibold">State</th>
              <th className="text-right px-4 py-2 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {customers.map((c) => (
              <tr key={c.id} data-testid={`customer-row-${c.id}`} className="border-t border-zinc-100">
                <td className="px-4 py-3 font-semibold">{c.name}</td>
                <td className="px-4 py-3 font-mono text-xs">{c.gstin || "—"}</td>
                <td className="px-4 py-3">{c.phone || "—"}</td>
                <td className="px-4 py-3">{c.state || "—"}</td>
                <td className="px-4 py-3 text-right">
                  <Link data-testid={`history-customer-${c.id}`} to={`/customers/history/${c.id}`} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-indigo-300 text-indigo-700 rounded-sm mr-2 hover:bg-indigo-600 hover:text-white transition">
                    <FileText size={12} /> History
                  </Link>
                  <button data-testid={`edit-customer-${c.id}`} onClick={() => openEdit(c)} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-zinc-200 rounded-sm mr-2 hover:bg-zinc-950 hover:text-white">
                    <Pencil size={12} /> Edit
                  </button>
                  <button data-testid={`delete-customer-${c.id}`} onClick={() => { if (window.confirm("Delete this customer?")) del.mutate(c.id); }} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-50">
                    <Trash2 size={12} /> Delete
                  </button>
                </td>
              </tr>
            ))}
            {!isLoading && customers.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-12 text-center text-zinc-400">No customers yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4" data-testid="customer-modal">
          <div className="bg-white w-full max-w-lg border border-zinc-950 rounded-sm">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
              <h3 className="font-bold">{editing ? "Edit Customer" : "New Customer"}</h3>
              <button onClick={() => setOpen(false)} data-testid="close-customer-modal"><X size={18} /></button>
            </div>
            <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="p-5 space-y-3">
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Name / పేరు *</label>
                <input data-testid="customer-input-name" required value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none" />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
                  GSTIN <span className="text-emerald-700 normal-case">(auto-fills State &amp; PAN)</span>
                </label>
                <input data-testid="customer-input-gstin" value={form.gstin || ""}
                  onChange={async (e) => {
                    const v = e.target.value.toUpperCase();
                    const next = { ...form, gstin: v };
                    if (v.length === 15) {
                      try {
                        const { data } = await api.get("/gstin/lookup", { params: { gstin: v } });
                        if (data.valid_format) {
                          if (data.state) next.state = data.state;
                          if (data.pan) next.pan = data.pan;
                          if (data.checksum_ok) toast.success(`GSTIN valid · ${data.state}`);
                          else toast.warning("GSTIN format ok but checksum failed");
                        } else {
                          toast.error("Invalid GSTIN format");
                        }
                      } catch {}
                    }
                    setForm(next);
                  }}
                  placeholder="e.g. 37AAECR5210P2Z2"
                  maxLength={15}
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm font-mono uppercase focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none" />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">PAN</label>
                <input data-testid="customer-input-pan" value={form.pan || ""} onChange={(e) => setForm({ ...form, pan: e.target.value.toUpperCase() })}
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm font-mono uppercase focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none" />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Phone / ఫోన్</label>
                <input data-testid="customer-input-phone" value={form.phone || ""} onChange={(e) => setForm({ ...form, phone: e.target.value })}
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none" />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">State / రాష్ట్రం</label>
                <StateSelect
                  value={form.state}
                  onChange={(v) => setForm({ ...form, state: v })}
                  dataTestId="customer-input-state"
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white"
                />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Address / చిరునామా</label>
                <textarea
                  data-testid="customer-input-address"
                  rows={2}
                  value={form.address || ""}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none"
                />
              </div>
              <div className="flex gap-2 justify-end pt-2">
                <button type="button" onClick={() => setOpen(false)} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
                <button data-testid="save-customer-btn" type="submit" disabled={save.isPending} className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
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
