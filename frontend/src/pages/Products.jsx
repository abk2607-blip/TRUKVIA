import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, fmtCurrency } from "@/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X, Package } from "lucide-react";

const EMPTY = { name: "", hsn_sac: "996791", default_rate: 0, unit: "MT", notes: "", default_shortage_allowance_pct: 0 };

export default function Products() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);

  const { data: products = [] } = useQuery({
    queryKey: ["products"],
    queryFn: async () => (await api.get("/products")).data,
  });

  const save = useMutation({
    mutationFn: async () => {
      const payload = { ...form, default_rate: Number(form.default_rate), default_shortage_allowance_pct: Number(form.default_shortage_allowance_pct || 0) };
      return editing
        ? (await api.put(`/products/${editing.id}`, { ...editing, ...payload })).data
        : (await api.post("/products", payload)).data;
    },
    onSuccess: () => {
      toast.success(editing ? "Product updated" : "Product added");
      qc.invalidateQueries({ queryKey: ["products"] });
      setOpen(false); setEditing(null); setForm(EMPTY);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const del = useMutation({
    mutationFn: async (id) => (await api.delete(`/products/${id}`)).data,
    onSuccess: () => { toast.success("Deleted"); qc.invalidateQueries({ queryKey: ["products"] }); },
  });

  const openEdit = (p) => { setEditing(p); setForm({ ...EMPTY, ...p }); setOpen(true); };
  const openNew = () => { setEditing(null); setForm(EMPTY); setOpen(true); };

  return (
    <div className="space-y-6" data-testid="products-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Master</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">ప్రొడక్ట్‌లు</span>
            <span className="text-zinc-400"> · Products</span>
          </h1>
        </div>
        <button data-testid="add-product-btn" onClick={openNew} className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2">
          <Plus size={14} /> Add Product
        </button>
      </header>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
        <table className="w-full text-sm" data-testid="products-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-4 py-2 font-semibold">Name</th>
              <th className="text-left px-4 py-2 font-semibold">HSN/SAC</th>
              <th className="text-left px-4 py-2 font-semibold">Unit</th>
              <th className="text-right px-4 py-2 font-semibold">Default Rate</th>
              <th className="text-left px-4 py-2 font-semibold">Notes</th>
              <th className="text-right px-4 py-2 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p) => (
              <tr key={p.id} data-testid={`product-row-${p.id}`} className="border-t border-zinc-100">
                <td className="px-4 py-3 font-semibold flex items-center gap-2"><Package size={14} className="text-zinc-400" /> {p.name}</td>
                <td className="px-4 py-3 font-mono text-xs">{p.hsn_sac}</td>
                <td className="px-4 py-3 text-xs">{p.unit}</td>
                <td className="px-4 py-3 text-right font-mono">{fmtCurrency(p.default_rate)}</td>
                <td className="px-4 py-3 text-xs text-zinc-500">{p.notes}</td>
                <td className="px-4 py-3 text-right">
                  <button data-testid={`edit-product-${p.id}`} onClick={() => openEdit(p)} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-zinc-200 rounded-sm mr-2 hover:bg-zinc-950 hover:text-white">
                    <Pencil size={12} /> Edit
                  </button>
                  <button data-testid={`delete-product-${p.id}`} onClick={() => { if (window.confirm("Delete?")) del.mutate(p.id); }} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-50">
                    <Trash2 size={12} /> Delete
                  </button>
                </td>
              </tr>
            ))}
            {products.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-12 text-center text-zinc-400">No products. Add Bitumen VG 40, VG 30, Emulsion etc.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4" data-testid="product-modal">
          <div className="bg-white w-full max-w-md border border-zinc-950 rounded-sm">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
              <h3 className="font-bold">{editing ? "Edit Product" : "New Product"}</h3>
              <button onClick={() => setOpen(false)}><X size={18} /></button>
            </div>
            <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="p-5 space-y-3">
              <F label="Name · పేరు *"><input data-testid="product-name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={ic} placeholder="Bitumen VG 40" /></F>
              <F label="HSN/SAC"><input data-testid="product-hsn" value={form.hsn_sac} onChange={(e) => setForm({ ...form, hsn_sac: e.target.value })} className={ic} /></F>
              <F label="Unit"><input data-testid="product-unit" value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} className={ic} /></F>
              <F label="Default Rate (per unit)"><input data-testid="product-rate" type="number" step="0.01" min="0" value={form.default_rate} onChange={(e) => setForm({ ...form, default_rate: e.target.value })} className={ic} /></F>
              <F label="Default Shortage Allowance (%)"><input data-testid="product-shortage-pct" type="number" step="0.01" min="0" value={form.default_shortage_allowance_pct ?? 0} onChange={(e) => setForm({ ...form, default_shortage_allowance_pct: e.target.value })} className={ic} placeholder="e.g. 0.5 for Bitumen" /></F>
              <F label="Notes"><textarea rows={2} data-testid="product-notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={ic} /></F>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setOpen(false)} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
                <button data-testid="save-product-btn" type="submit" disabled={save.isPending} className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
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
