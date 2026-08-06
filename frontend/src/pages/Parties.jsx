import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X, MapPin } from "lucide-react";
import { StateSelect } from "@/lib/states";

const EMPTY = {
  party_type: "both",
  name: "",
  contact_person: "",
  phone: "",
  email: "",
  gstin: "",
  pan: "",
  address: "",
  state: "",
  pincode: "",
  linked_customer_id: null,
  notes: "",
};

const inputCls =
  "mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none";

export default function Parties() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [filter, setFilter] = useState("all"); // all | consignor | consignee

  const { data: parties = [] } = useQuery({
    queryKey: ["parties"],
    queryFn: async () => (await api.get("/parties")).data,
  });
  const { data: customers = [] } = useQuery({
    queryKey: ["customers"],
    queryFn: async () => (await api.get("/customers")).data,
  });

  const filtered = parties.filter((p) => {
    if (filter === "all") return true;
    return p.party_type === filter || p.party_type === "both";
  });

  const save = useMutation({
    mutationFn: async () => {
      const body = { ...form, linked_customer_id: form.linked_customer_id || null };
      if (editing) return (await api.put(`/parties/${editing.id}`, body)).data;
      return (await api.post("/parties", body)).data;
    },
    onSuccess: () => {
      toast.success(editing ? "Party updated" : "Party added");
      qc.invalidateQueries({ queryKey: ["parties"] });
      setOpen(false);
      setEditing(null);
      setForm(EMPTY);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const del = useMutation({
    mutationFn: async (id) => (await api.delete(`/parties/${id}`)).data,
    onSuccess: () => {
      toast.success("Party deleted");
      qc.invalidateQueries({ queryKey: ["parties"] });
    },
  });

  const openNew = () => {
    setEditing(null);
    setForm(EMPTY);
    setOpen(true);
  };
  const openEdit = (p) => {
    setEditing(p);
    setForm({ ...EMPTY, ...p });
    setOpen(true);
  };

  return (
    <div className="space-y-6" data-testid="parties-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Address Book</div>
          <h1 className="text-3xl font-black tracking-tighter">
            <span className="telugu">కన్‌సైనర్ / కన్‌సైనీ</span>
            <span className="text-zinc-400"> · Consignor / Consignee</span>
          </h1>
        </div>
        <button data-testid="add-party-btn" onClick={openNew} className="inline-flex items-center gap-2 px-4 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800">
          <Plus size={14} /> New Party
        </button>
      </header>

      <div className="flex items-center gap-2 text-xs" data-testid="party-filter-tabs">
        {["all", "consignor", "consignee"].map((k) => (
          <button
            key={k}
            data-testid={`party-filter-${k}`}
            onClick={() => setFilter(k)}
            className={`px-3 py-1.5 uppercase tracking-wider font-semibold rounded-sm border ${filter === k ? "bg-zinc-950 text-white border-zinc-950" : "bg-white border-zinc-200 text-zinc-500 hover:border-zinc-950"}`}
          >
            {k}
          </button>
        ))}
      </div>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-x-auto">
        <table className="w-full text-sm" data-testid="parties-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-4 py-2">Name</th>
              <th className="text-left px-4 py-2">Type</th>
              <th className="text-left px-4 py-2">State</th>
              <th className="text-left px-4 py-2">GSTIN</th>
              <th className="text-left px-4 py-2">Phone</th>
              <th className="text-left px-4 py-2">Linked Customer</th>
              <th className="text-right px-4 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((p) => {
              const linkedName = customers.find((c) => c.id === p.linked_customer_id)?.name;
              return (
                <tr key={p.id} className="border-t border-zinc-100">
                  <td className="px-4 py-3 font-semibold">{p.name}</td>
                  <td className="px-4 py-3">
                    <span className="text-[10px] uppercase tracking-wider bg-zinc-100 px-2 py-0.5 rounded-sm">{p.party_type}</span>
                  </td>
                  <td className="px-4 py-3"><span className="inline-flex items-center gap-1"><MapPin size={11} className="text-zinc-400" />{p.state || "—"}</span></td>
                  <td className="px-4 py-3 font-mono text-xs">{p.gstin || "—"}</td>
                  <td className="px-4 py-3 font-mono text-xs">{p.phone || "—"}</td>
                  <td className="px-4 py-3 text-xs">{linkedName || "—"}</td>
                  <td className="px-4 py-3 text-right">
                    <button data-testid={`edit-party-${p.id}`} onClick={() => openEdit(p)} className="text-xs px-2 py-1 border border-zinc-200 rounded-sm hover:bg-zinc-950 hover:text-white mr-1"><Pencil size={11} /></button>
                    <button data-testid={`delete-party-${p.id}`} onClick={() => window.confirm("Delete party?") && del.mutate(p.id)} className="text-xs px-2 py-1 border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-50"><Trash2 size={11} /></button>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-12 text-center text-zinc-400 text-sm">No {filter === "all" ? "" : filter} entries. Click "New Party" to add one.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4" data-testid="party-modal">
          <div className="bg-white w-full max-w-2xl border border-zinc-950 rounded-sm max-h-[92vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200 sticky top-0 bg-white">
              <h3 className="font-bold">{editing ? "Edit Party" : "New Party"}</h3>
              <button onClick={() => setOpen(false)} data-testid="close-party-modal"><X size={18} /></button>
            </div>
            <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
              <F label="Party Type *">
                <select data-testid="party-input-type" value={form.party_type} onChange={(e) => setForm({ ...form, party_type: e.target.value })} className={inputCls + " bg-white"}>
                  <option value="both">Both (Consignor & Consignee)</option>
                  <option value="consignor">Consignor (Loading Point)</option>
                  <option value="consignee">Consignee (Unloading Point)</option>
                </select>
              </F>
              <F label="Name *">
                <input data-testid="party-input-name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={inputCls} />
              </F>
              <F label="Contact Person">
                <input data-testid="party-input-contact" value={form.contact_person} onChange={(e) => setForm({ ...form, contact_person: e.target.value })} className={inputCls} />
              </F>
              <F label="Phone">
                <input data-testid="party-input-phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className={inputCls} />
              </F>
              <F label="Email">
                <input data-testid="party-input-email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className={inputCls} />
              </F>
              <F label="GSTIN">
                <input data-testid="party-input-gstin" value={form.gstin} onChange={(e) => setForm({ ...form, gstin: e.target.value })} className={inputCls} />
              </F>
              <F label="PAN">
                <input data-testid="party-input-pan" value={form.pan} onChange={(e) => setForm({ ...form, pan: e.target.value })} className={inputCls} />
              </F>
              <F label="Pincode">
                <input data-testid="party-input-pincode" value={form.pincode} onChange={(e) => setForm({ ...form, pincode: e.target.value })} className={inputCls} />
              </F>
              <F label="State">
                <StateSelect value={form.state} onChange={(v) => setForm({ ...form, state: v })} dataTestId="party-input-state" className={inputCls + " bg-white"} />
              </F>
              <F label="Linked Customer (optional)">
                <select data-testid="party-input-customer" value={form.linked_customer_id || ""} onChange={(e) => setForm({ ...form, linked_customer_id: e.target.value || null })} className={inputCls + " bg-white"}>
                  <option value="">-- Not Linked --</option>
                  {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </F>
              <div className="md:col-span-2">
                <F label="Address">
                  <textarea data-testid="party-input-address" rows={2} value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} className={inputCls} />
                </F>
              </div>
              <div className="md:col-span-2">
                <F label="Notes">
                  <input data-testid="party-input-notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={inputCls} />
                </F>
              </div>
              <div className="md:col-span-2 flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setOpen(false)} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-200 rounded-sm">Cancel</button>
                <button data-testid="save-party-btn" type="submit" disabled={save.isPending} className="px-4 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
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

function F({ label, children }) {
  return (
    <div>
      <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">{label}</label>
      {children}
    </div>
  );
}
