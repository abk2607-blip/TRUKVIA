import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "@/api";
import { toast } from "sonner";
import { Plus, Star, X } from "lucide-react";

const PARTY_LABEL = { supplier: "Supplier", vendor: "Vendor", mechanic: "Mechanic", driver: "Driver", customer: "Customer" };

export default function PartyBankAccounts() {
  const { partyType, partyId } = useParams();
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ bank_name: "", account_holder_name: "", account_number: "", ifsc: "", branch: "", account_type: "savings", is_primary: false });

  const { data = [], isFetching } = useQuery({
    queryKey: ["party-banks", partyType, partyId],
    queryFn: async () => (await api.get(`/party-bank-accounts?party_type=${partyType}&party_id=${partyId}`)).data,
    enabled: Boolean(partyType && partyId),
  });

  const create = useMutation({
    mutationFn: async () => (await api.post("/party-bank-accounts", { ...form, party_type: partyType, party_id: partyId })).data,
    onSuccess: () => { toast.success("Bank account added"); setShowForm(false); qc.invalidateQueries({ queryKey: ["party-banks", partyType, partyId] }); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });
  const setPrimary = useMutation({
    mutationFn: async (id) => (await api.post(`/party-bank-accounts/${id}/set-primary`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["party-banks", partyType, partyId] }),
  });
  const deactivate = useMutation({
    mutationFn: async (id) => (await api.post(`/party-bank-accounts/${id}/deactivate`, { reason: "user_deactivated" })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["party-banks", partyType, partyId] }),
  });

  return (
    <div className="space-y-6" data-testid="party-bank-accounts-page">
      <div className="flex justify-between items-end">
        <div>
          <div className="text-[11px] uppercase tracking-[0.28em] font-bold text-zinc-500">
            <span className="telugu">బ్యాంక్ ఖాతాలు</span>
            <span className="mx-1 text-zinc-300">·</span>{PARTY_LABEL[partyType] || partyType} Bank Accounts
          </div>
          <h1 className="mt-1 text-3xl font-black tracking-tight text-zinc-950">{PARTY_LABEL[partyType] || partyType} Bank Accounts</h1>
          <div className="text-xs text-zinc-500 mt-1 font-mono">{partyType}:{partyId}</div>
        </div>
        <button data-testid="add-party-bank-btn" onClick={() => setShowForm(true)} className="inline-flex items-center gap-2 px-4 py-2 bg-zinc-950 text-white text-sm font-semibold uppercase tracking-wider rounded-sm border border-zinc-950 hover:bg-white hover:text-zinc-950 transition-colors" style={{ outlineColor: "#FD7800" }}>
          <Plus size={16} /> Add
        </button>
      </div>

      <table className="w-full text-sm border border-zinc-200">
        <thead className="bg-zinc-50 text-[10px] uppercase tracking-widest text-zinc-500">
          <tr><th className="text-left p-2">Bank</th><th className="text-left p-2">A/c No</th><th className="text-left p-2">IFSC</th><th className="text-left p-2">Type</th><th className="text-left p-2">Status</th><th className="text-right p-2">Actions</th></tr>
        </thead>
        <tbody>
          {data.map((r) => (
            <tr key={r.id} data-testid="party-bank-row" className="border-t border-zinc-100 hover:bg-zinc-50">
              <td className="p-2 font-mono text-xs">{r.bank_name || "—"}</td>
              <td className="p-2 font-mono text-xs" data-testid="masked-account-number">{r.masked_display || r.account_number}</td>
              <td className="p-2 font-mono text-xs">{r.ifsc || "—"}</td>
              <td className="p-2 text-xs">{r.account_type}</td>
              <td className="p-2 text-xs">
                <span className={`inline-flex items-center px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider border rounded-sm ${r.is_active ? "bg-emerald-50 text-emerald-800 border-emerald-200" : "bg-zinc-100 text-zinc-500 border-zinc-200"}`}>
                  {r.is_active ? "Active" : "Inactive"}
                </span>
                {r.is_primary && <span className="ml-1 inline-flex items-center px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider border rounded-sm bg-amber-50 text-amber-900 border-amber-300"><Star size={10} className="mr-1" /> Primary</span>}
              </td>
              <td className="p-2 text-right space-x-2">
                {r.is_active && !r.is_primary && <button data-testid="set-primary-btn" onClick={() => setPrimary.mutate(r.id)} className="text-xs px-2 py-1 border border-zinc-300 hover:bg-zinc-100">Set primary</button>}
                {r.is_active && <button data-testid="deactivate-btn" onClick={() => deactivate.mutate(r.id)} className="text-xs px-2 py-1 border border-rose-300 text-rose-800 hover:bg-rose-50">Deactivate</button>}
              </td>
            </tr>
          ))}
          {data.length === 0 && !isFetching && (<tr><td colSpan={6} className="p-6 text-center text-zinc-500">No bank accounts yet.</td></tr>)}
        </tbody>
      </table>

      {showForm && (
        <div className="fixed inset-0 z-50 bg-zinc-900/50" onClick={() => setShowForm(false)}>
          <div data-testid="add-party-bank-form" className="absolute right-0 top-0 h-full w-full max-w-md bg-white shadow-2xl p-6 overflow-auto" onClick={(e) => e.stopPropagation()}>
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
              <label className="flex items-center gap-2 text-xs">
                <input type="checkbox" data-testid="field-is-primary" checked={form.is_primary} onChange={(e) => setForm({ ...form, is_primary: e.target.checked })} />
                Set as primary
              </label>
              <button data-testid="save-party-bank-btn" onClick={() => create.mutate()} className="w-full inline-flex items-center justify-center gap-2 px-4 py-3 bg-zinc-950 text-white text-sm font-semibold uppercase tracking-wider rounded-sm border border-zinc-950 hover:bg-white hover:text-zinc-950 transition-colors" style={{ outlineColor: "#FD7800" }}>Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
