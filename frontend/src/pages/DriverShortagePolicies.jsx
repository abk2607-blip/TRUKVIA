// Iter59 · Phase A — Driver Shortage Policy Master (effective-dated).
import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate } from "@/api";
import { toast } from "sonner";
import { Plus, X, Edit3, Save, Ban } from "lucide-react";

const EMPTY_POLICY = {
  name: "", shortage_limit_kg: 100, unit: "KG",
  effective_from: new Date().toISOString().slice(0, 10),
  effective_to: "", product_category: "", active: true, remarks: "",
};

export default function DriverShortagePolicies() {
  const qc = useQueryClient();
  const [editing, setEditing] = React.useState(null); // null | "new" | policy.id
  const [form, setForm] = React.useState(EMPTY_POLICY);

  const { data: policies = [], isLoading } = useQuery({
    queryKey: ["driver-shortage-policies"],
    queryFn: async () => (await api.get("/driver-shortage-policies")).data,
  });

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        ...form,
        shortage_limit_kg: Number(form.shortage_limit_kg || 0),
        effective_to: form.effective_to || null,
        product_category: form.product_category || null,
        remarks: form.remarks || null,
      };
      if (editing === "new")
        return (await api.post("/driver-shortage-policies", payload)).data;
      return (await api.put(`/driver-shortage-policies/${editing}`, payload)).data;
    },
    onSuccess: () => {
      toast.success(editing === "new" ? "Policy created" : "Policy updated");
      qc.invalidateQueries({ queryKey: ["driver-shortage-policies"] });
      setEditing(null); setForm(EMPTY_POLICY);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Save failed"),
  });

  const deactivate = useMutation({
    mutationFn: async (pid) => (await api.delete(`/driver-shortage-policies/${pid}`)).data,
    onSuccess: () => { toast.success("Policy deactivated"); qc.invalidateQueries({ queryKey: ["driver-shortage-policies"] }); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const ic = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";

  const openEdit = (p) => {
    setForm({
      name: p.name, shortage_limit_kg: p.shortage_limit_kg, unit: p.unit,
      effective_from: p.effective_from, effective_to: p.effective_to || "",
      product_category: p.product_category || "", active: p.active,
      remarks: p.remarks || "",
    });
    setEditing(p.id);
  };

  return (
    <div className="space-y-6" data-testid="policies-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Drivers · Configuration</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">షార్టేజ్ పాలసీ</span>
            <span className="text-zinc-400"> · Driver Shortage Policies</span>
          </h1>
          <p className="text-xs text-zinc-500 mt-2 max-w-2xl">
            Effective-dated. Every Trip snapshots the policy applicable to its <b>Trip Date</b>.
            Future policy edits do <b>NOT</b> retroactively change old Trips.
          </p>
        </div>
        <button
          data-testid="new-policy-btn"
          onClick={() => { setEditing("new"); setForm(EMPTY_POLICY); }}
          className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2"
        >
          <Plus size={14} /> New Policy
        </button>
      </header>

      {editing !== null && (
        <div className="border border-zinc-950 bg-white rounded-sm p-5" data-testid="policy-form">
          <div className="flex items-center justify-between mb-4">
            <div className="text-sm font-bold uppercase tracking-wider">
              {editing === "new" ? "+ Create Policy" : "Edit Policy"}
            </div>
            <button onClick={() => { setEditing(null); setForm(EMPTY_POLICY); }} className="p-1 text-zinc-500 hover:text-zinc-950"><X size={16} /></button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Policy Name *</label>
              <input data-testid="policy-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={ic} placeholder="Standard Bitumen 100KG" />
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Shortage Limit (KG) *</label>
              <input data-testid="policy-limit" type="number" step="0.001" min="0" value={form.shortage_limit_kg} onChange={(e) => setForm({ ...form, shortage_limit_kg: e.target.value })} className={ic} />
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Unit</label>
              <input value={form.unit} readOnly className={`${ic} bg-zinc-100`} />
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Effective From *</label>
              <input data-testid="policy-effective-from" type="date" value={form.effective_from} onChange={(e) => setForm({ ...form, effective_from: e.target.value })} className={ic} />
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Effective To (optional)</label>
              <input data-testid="policy-effective-to" type="date" value={form.effective_to} onChange={(e) => setForm({ ...form, effective_to: e.target.value })} className={ic} placeholder="Leave blank for open-ended" />
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Product Category (optional)</label>
              <input data-testid="policy-category" value={form.product_category} onChange={(e) => setForm({ ...form, product_category: e.target.value })} className={ic} placeholder="e.g. Bitumen VG 40 (blank = all)" />
            </div>
            <div className="md:col-span-2">
              <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Remarks</label>
              <input data-testid="policy-remarks" value={form.remarks} onChange={(e) => setForm({ ...form, remarks: e.target.value })} className={ic} placeholder="Approval reference, board note etc." />
            </div>
            <div className="flex items-end">
              <label className="inline-flex items-center gap-2 text-xs font-semibold cursor-pointer">
                <input data-testid="policy-active" type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} className="accent-emerald-500" />
                Active
              </label>
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <button onClick={() => { setEditing(null); setForm(EMPTY_POLICY); }} className="px-3 py-2 text-xs uppercase tracking-wider font-bold border border-zinc-300 rounded-sm">Cancel</button>
            <button
              data-testid="save-policy-btn"
              onClick={() => save.mutate()}
              disabled={save.isPending || !form.name || !form.effective_from}
              className="px-4 py-2 text-xs uppercase tracking-wider font-bold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-40 inline-flex items-center gap-1"
            >
              <Save size={12} /> {save.isPending ? "Saving…" : "Save Policy"}
            </button>
          </div>
        </div>
      )}

      <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
        <table className="w-full text-sm" data-testid="policies-table">
          <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-wider">
            <tr>
              <th className="text-left px-4 py-3">Policy</th>
              <th className="text-right px-4 py-3">Limit</th>
              <th className="text-left px-4 py-3">Effective</th>
              <th className="text-left px-4 py-3">Category</th>
              <th className="text-center px-4 py-3">Version</th>
              <th className="text-center px-4 py-3">Status</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {isLoading ? (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-zinc-400 text-xs">Loading…</td></tr>
            ) : policies.length === 0 ? (
              <tr><td colSpan={7} className="px-4 py-12 text-center text-zinc-400 text-xs" data-testid="policies-empty">
                No policies yet. Click "+ New Policy" to add your first shortage rule.
              </td></tr>
            ) : policies.map((p) => (
              <tr key={p.id} data-testid={`policy-row-${p.id}`} className={p.active ? "" : "opacity-50"}>
                <td className="px-4 py-3 font-bold">{p.name}{p.remarks && <div className="text-[10px] text-zinc-500 italic">{p.remarks}</div>}</td>
                <td className="px-4 py-3 text-right font-mono font-bold">{Number(p.shortage_limit_kg).toFixed(1)} {p.unit}</td>
                <td className="px-4 py-3 font-mono text-xs">
                  {fmtDate(p.effective_from)}
                  {p.effective_to && <> → {fmtDate(p.effective_to)}</>}
                  {!p.effective_to && <span className="text-zinc-400"> → open</span>}
                </td>
                <td className="px-4 py-3 text-xs">{p.product_category || <span className="text-zinc-400 italic">All products</span>}</td>
                <td className="px-4 py-3 text-center font-mono text-xs">v{p.version}</td>
                <td className="px-4 py-3 text-center">
                  {p.active ? (
                    <span className="inline-block text-[10px] uppercase tracking-wider bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded-full font-bold">Active</span>
                  ) : (
                    <span className="inline-block text-[10px] uppercase tracking-wider bg-zinc-100 text-zinc-500 px-2 py-0.5 rounded-full font-bold">Inactive</span>
                  )}
                </td>
                <td className="px-4 py-3 text-right">
                  <button data-testid={`edit-policy-${p.id}`} onClick={() => openEdit(p)} className="p-1.5 border border-zinc-200 rounded-sm text-zinc-600 hover:bg-zinc-950 hover:text-white transition mr-1" title="Edit"><Edit3 size={12} /></button>
                  {p.active && (
                    <button
                      data-testid={`deactivate-policy-${p.id}`}
                      onClick={() => { if (window.confirm(`Deactivate policy "${p.name}"? Old Trips referencing this policy will retain their historical snapshot.`)) deactivate.mutate(p.id); }}
                      className="p-1.5 border border-rose-200 rounded-sm text-rose-700 hover:bg-rose-600 hover:text-white transition"
                      title="Deactivate"
                    ><Ban size={12} /></button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
