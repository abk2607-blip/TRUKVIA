import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { Plus, Star, X, RefreshCw } from "lucide-react";

const CHIP = {
  active: "bg-emerald-50 text-emerald-800 border-emerald-200",
  inactive: "bg-zinc-100 text-zinc-500 border-zinc-200",
  primary: "bg-amber-50 text-amber-900 border-amber-300",
};

function BankRow({ row, onSetPrimary, onDeactivate }) {
  return (
    <tr data-testid="company-bank-row" className="border-t border-zinc-100 hover:bg-zinc-50">
      <td className="p-2 font-mono text-xs">{row.bank_name || "—"}</td>
      <td className="p-2 font-mono text-xs" data-testid="masked-account-number">
        {row.masked_display || row.account_number}
      </td>
      <td className="p-2 font-mono text-xs">{row.ifsc || "—"}</td>
      <td className="p-2 text-xs">{row.account_type}</td>
      <td className="p-2 text-xs">
        <span className={`inline-flex items-center px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider border rounded-sm ${row.is_active ? CHIP.active : CHIP.inactive}`}>
          {row.is_active ? "Active" : "Inactive"}
        </span>
        {row.is_primary && (
          <span className={`ml-1 inline-flex items-center px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider border rounded-sm ${CHIP.primary}`}>
            <Star size={10} className="mr-1" /> Primary
          </span>
        )}
      </td>
      <td className="p-2 text-right space-x-2">
        {row.is_active && !row.is_primary && (
          <button data-testid="set-primary-btn" onClick={() => onSetPrimary(row.id)} className="text-xs px-2 py-1 border border-zinc-300 hover:bg-zinc-100">Set primary</button>
        )}
        {row.is_active && (
          <button data-testid="deactivate-btn" onClick={() => onDeactivate(row.id)} className="text-xs px-2 py-1 border border-rose-300 text-rose-800 hover:bg-rose-50">Deactivate</button>
        )}
      </td>
    </tr>
  );
}

export default function CompanyBankAccounts() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ bank_name: "", account_holder_name: "", account_number: "", ifsc: "", branch: "", account_type: "current", is_primary: false });

  const { data = [], isFetching } = useQuery({
    queryKey: ["company-banks"],
    queryFn: async () => (await api.get("/company-bank-accounts")).data,
  });

  const create = useMutation({
    mutationFn: async () => (await api.post("/company-bank-accounts", form)).data,
    onSuccess: () => { toast.success("Bank account added"); setShowForm(false); qc.invalidateQueries({ queryKey: ["company-banks"] }); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });
  const setPrimary = useMutation({
    mutationFn: async (id) => (await api.post(`/company-bank-accounts/${id}/set-primary`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["company-banks"] }),
  });
  const deactivate = useMutation({
    mutationFn: async (id) => (await api.post(`/company-bank-accounts/${id}/deactivate`, { reason: "user_deactivated" })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["company-banks"] }),
  });

  return (
    <div className="space-y-6" data-testid="company-bank-accounts-page">
      <div className="flex justify-between items-end">
        <div>
          <div className="text-[11px] uppercase tracking-[0.28em] font-bold text-zinc-500">
            <span className="telugu">కంపెనీ బ్యాంక్ ఖాతాలు</span>
            <span className="mx-1 text-zinc-300">·</span>Company Bank Accounts
          </div>
          <h1 className="mt-1 text-3xl font-black tracking-tight text-zinc-950">Company Bank Accounts</h1>
        </div>
        <button data-testid="add-bank-btn" onClick={() => setShowForm(true)} className="inline-flex items-center gap-2 px-4 py-2 bg-zinc-950 text-white text-sm font-semibold uppercase tracking-wider rounded-sm border border-zinc-950 hover:bg-white hover:text-zinc-950 transition-colors" style={{ outlineColor: "#FD7800" }}>
          <Plus size={16} /> Add Bank Account
        </button>
      </div>

      <table className="w-full text-sm border border-zinc-200">
        <thead className="bg-zinc-50 text-[10px] uppercase tracking-widest text-zinc-500">
          <tr><th className="text-left p-2">Bank</th><th className="text-left p-2">A/c No</th><th className="text-left p-2">IFSC</th><th className="text-left p-2">Type</th><th className="text-left p-2">Status</th><th className="text-right p-2">Actions</th></tr>
        </thead>
        <tbody>
          {data.map((r) => <BankRow key={r.id} row={r} onSetPrimary={(id) => setPrimary.mutate(id)} onDeactivate={(id) => deactivate.mutate(id)} />)}
          {data.length === 0 && !isFetching && (
            <tr><td colSpan={6} className="p-6 text-center text-zinc-500">No bank accounts yet.</td></tr>
          )}
        </tbody>
      </table>

      {showForm && (
        <div className="fixed inset-0 z-50 bg-zinc-900/50" onClick={() => setShowForm(false)}>
          <div data-testid="add-bank-form" className="absolute right-0 top-0 h-full w-full max-w-md bg-white shadow-2xl p-6 overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div className="text-[11px] uppercase tracking-widest font-bold text-zinc-500">New Bank Account</div>
              <button onClick={() => setShowForm(false)} className="w-8 h-8 flex items-center justify-center hover:bg-zinc-100 rounded-sm"><X size={18} /></button>
            </div>
            <div className="mt-4 space-y-3">
              {["bank_name", "account_holder_name", "account_number", "ifsc", "branch"].map((f) => (
                <label key={f} className="block text-xs">
                  <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">{f.replace(/_/g, " ")}</div>
                  <input data-testid={`field-${f}`} value={form[f]} onChange={(e) => setForm({ ...form, [f]: e.target.value })} className="mt-1 w-full border border-zinc-300 px-2 py-1 rounded-sm text-sm" />
                </label>
              ))}
              <label className="block text-xs">
                <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Account Type</div>
                <select value={form.account_type} onChange={(e) => setForm({ ...form, account_type: e.target.value })} className="mt-1 w-full border border-zinc-300 px-2 py-1 rounded-sm text-sm">
                  <option value="current">Current</option><option value="savings">Savings</option><option value="cc">CC</option><option value="od">OD</option>
                </select>
              </label>
              <label className="flex items-center gap-2 text-xs">
                <input type="checkbox" data-testid="field-is-primary" checked={form.is_primary} onChange={(e) => setForm({ ...form, is_primary: e.target.checked })} />
                Set as primary
              </label>
              <button data-testid="save-bank-btn" onClick={() => create.mutate()} className="w-full inline-flex items-center justify-center gap-2 px-4 py-3 bg-zinc-950 text-white text-sm font-semibold uppercase tracking-wider rounded-sm border border-zinc-950 hover:bg-white hover:text-zinc-950 transition-colors" style={{ outlineColor: "#FD7800" }}>
                <RefreshCw size={14} /> Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
