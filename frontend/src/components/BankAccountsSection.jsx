import React, { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";

/** Iter150H2 · BankAccountsSection — master-embedded multi-bank UX.
 * Reuses Iter150G endpoints; NO new endpoint. Two modes:
 *   <BankAccountsSection kind="company" />
 *   <BankAccountsSection kind="party" partyType="supplier|vendor|mechanic|driver|customer" partyId={id} />
 */
const EMPTY = {
  account_holder_name: "", bank_name: "", account_number: "",
  ifsc: "", branch: "", account_type: "savings", is_primary: false,
};

export default function BankAccountsSection({ kind, partyType, partyId }) {
  const qc = useQueryClient();
  const isCompany = kind === "company";
  const disabled = !isCompany && !partyId;

  const listUrl = isCompany
    ? "/company-bank-accounts?include_inactive=1"
    : `/party-bank-accounts?party_type=${partyType}&party_id=${partyId}&include_inactive=1`;
  const qKey = isCompany ? ["cba-master"] : ["pba-master", partyType, partyId];

  const { data = [], isLoading } = useQuery({
    queryKey: qKey, queryFn: async () => (await api.get(listUrl)).data,
    enabled: !disabled,
  });

  const [showAdd, setShowAdd] = useState(false);
  const [replacing, setReplacing] = useState(null); // account id being replaced
  const [editing, setEditing] = useState(null); // account object being edited
  const [form, setForm] = useState(EMPTY);

  const invalidate = () => qc.invalidateQueries({ queryKey: qKey });

  const create = useMutation({
    mutationFn: async () => {
      const body = isCompany ? { ...form } : { ...form, party_type: partyType, party_id: partyId };
      return (await api.post(isCompany ? "/company-bank-accounts" : "/party-bank-accounts", body)).data;
    },
    onSuccess: () => { toast.success("Bank account added"); setShowAdd(false); setForm(EMPTY); invalidate(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed to add"),
  });

  const edit = useMutation({
    mutationFn: async () => {
      const body = { bank_name: form.bank_name, branch: form.branch,
                     account_holder_name: form.account_holder_name, ifsc: form.ifsc };
      const url = isCompany ? `/company-bank-accounts/${editing.id}` : `/party-bank-accounts/${editing.id}`;
      return (await api.put(url, body)).data;
    },
    onSuccess: () => { toast.success("Updated"); setEditing(null); setForm(EMPTY); invalidate(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed to edit"),
  });

  const setPrimary = useMutation({
    mutationFn: async (bid) => (await api.post(
      isCompany ? `/company-bank-accounts/${bid}/set-primary` : `/party-bank-accounts/${bid}/set-primary`, {})).data,
    onSuccess: () => { toast.success("Primary updated"); invalidate(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const deactivate = useMutation({
    mutationFn: async (bid) => (await api.post(
      isCompany ? `/company-bank-accounts/${bid}/deactivate` : `/party-bank-accounts/${bid}/deactivate`,
      { reason: "master-form deactivation" })).data,
    onSuccess: () => { toast.success("Deactivated"); invalidate(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const replace = useMutation({
    mutationFn: async () => {
      const body = { reason: "master-form replace", ...form };
      return (await api.post(
        isCompany ? `/company-bank-accounts/${replacing}/replace` : `/party-bank-accounts/${replacing}/replace`,
        body)).data;
    },
    onSuccess: () => { toast.success("Replaced"); setReplacing(null); setForm(EMPTY); invalidate(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const reveal = async (bid) => {
    try {
      const r = await api.get(isCompany ? `/company-bank-accounts/${bid}/reveal` : `/party-bank-accounts/${bid}/reveal`);
      toast.success(`Account: ${r.data.account_number || "—"}`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Not permitted"); }
  };

  const active = useMemo(() => (data || []).filter(r => r.is_active), [data]);
  const inactive = useMemo(() => (data || []).filter(r => !r.is_active), [data]);

  if (disabled) {
    return (
      <div className="border border-zinc-200 bg-zinc-50 rounded-sm p-4" data-testid="bank-section-disabled">
        <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-1">Bank Accounts</div>
        <div className="text-xs text-zinc-500">Save this record first to add bank accounts.</div>
      </div>
    );
  }

  const testidRoot = isCompany ? "company-bank-section" : `party-bank-section-${partyType}`;

  return (
    <div className="border border-zinc-200 bg-white rounded-sm p-4" data-testid={testidRoot}>
      <div className="flex items-center justify-between mb-3">
        <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500">Bank Accounts · బ్యాంక్ ఖాతాలు</div>
        <button type="button" data-testid={`${testidRoot}-add-btn`}
          onClick={() => { setForm(EMPTY); setShowAdd(true); }}
          className="px-3 py-1 text-xs uppercase tracking-wider bg-amber-600 text-white rounded-sm hover:bg-amber-700">
          + Add Another Bank Account
        </button>
      </div>

      {isLoading && <div className="text-xs text-zinc-400 py-6 text-center">Loading…</div>}
      {!isLoading && data.length === 0 && (
        <div className="text-xs text-zinc-400 py-6 text-center" data-testid={`${testidRoot}-empty`}>
          No bank accounts yet. Click <b>+ Add Another Bank Account</b> to add one.
        </div>
      )}

      {(active.concat(inactive)).map((r) => (
        <div key={r.id} data-testid={`${testidRoot}-row-${r.id}`}
          className={`border rounded-sm p-3 mb-2 ${r.is_active ? "border-zinc-200 bg-white" : "border-zinc-200 bg-zinc-50 opacity-70"}`}>
          <div className="flex flex-wrap items-center gap-3 justify-between">
            <div className="text-sm">
              <div className="font-bold">{r.bank_name || "—"}
                {r.is_primary && r.is_active && (
                  <span className="ml-2 px-1.5 py-0.5 text-[9px] font-bold uppercase bg-emerald-600 text-white rounded-sm">Primary</span>)}
                {r.is_active
                  ? <span className="ml-1 px-1.5 py-0.5 text-[9px] font-bold uppercase bg-zinc-100 text-zinc-700 rounded-sm">Active</span>
                  : <span className="ml-1 px-1.5 py-0.5 text-[9px] font-bold uppercase bg-zinc-200 text-zinc-500 rounded-sm">Inactive</span>}
              </div>
              <div className="text-xs text-zinc-600 mt-1 font-mono">
                {r.masked_display || r.account_number || "—"} · IFSC {r.ifsc || "—"} · {r.branch || "—"}
              </div>
              <div className="text-[11px] text-zinc-500">Holder: {r.account_holder_name || "—"}</div>
            </div>
            <div className="flex gap-1 text-[10px]">
              {r.is_active && !r.is_primary &&
                <button type="button" onClick={() => setPrimary.mutate(r.id)}
                  data-testid={`${testidRoot}-setprimary-${r.id}`}
                  className="px-2 py-1 uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-50">Set Primary</button>}
              {r.is_active &&
                <button type="button" onClick={() => { setEditing(r); setForm({ ...EMPTY, ...r }); }}
                  data-testid={`${testidRoot}-edit-${r.id}`}
                  className="px-2 py-1 uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-50">Edit</button>}
              {r.is_active &&
                <button type="button" onClick={() => { setForm(EMPTY); setReplacing(r.id); }}
                  data-testid={`${testidRoot}-replace-${r.id}`}
                  className="px-2 py-1 uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-50">Replace</button>}
              {r.is_active &&
                <button type="button" onClick={() => window.confirm("Deactivate this bank account?") && deactivate.mutate(r.id)}
                  data-testid={`${testidRoot}-deactivate-${r.id}`}
                  className="px-2 py-1 uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-50 text-zinc-700">Deactivate</button>}
              <button type="button" onClick={() => reveal(r.id)}
                data-testid={`${testidRoot}-reveal-${r.id}`}
                className="px-2 py-1 uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-50">Reveal</button>
            </div>
          </div>
        </div>
      ))}

      {(showAdd || replacing || editing) && (
        <BankForm form={form} setForm={setForm} testidRoot={testidRoot}
          mode={editing ? "edit" : replacing ? "replace" : "add"}
          onCancel={() => { setShowAdd(false); setReplacing(null); setEditing(null); setForm(EMPTY); }}
          onSubmit={() => {
            if (editing) edit.mutate();
            else if (replacing) replace.mutate();
            else create.mutate();
          }}
          disabled={create.isPending || replace.isPending || edit.isPending} />
      )}
    </div>
  );
}

function BankForm({ form, setForm, mode, onCancel, onSubmit, disabled, testidRoot }) {
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const ic = "w-full border border-zinc-300 px-2 py-1.5 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";
  const lc = "text-[9px] uppercase font-bold text-zinc-500 tracking-wider";
  return (
    <div className="border border-amber-300 bg-amber-50 rounded-sm p-3 mt-2" data-testid={`${testidRoot}-form`}>
      <div className="text-[11px] font-bold uppercase tracking-wider mb-2 text-amber-900">
        {mode === "edit" ? "Edit Bank Account" : mode === "replace" ? "Replace Bank Account · new details" : "Add New Bank Account"}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
        <div><label className={lc}>Account Holder</label>
          <input data-testid={`${testidRoot}-form-holder`} value={form.account_holder_name || ""} onChange={set("account_holder_name")} className={ic} /></div>
        <div><label className={lc}>Bank Name</label>
          <input data-testid={`${testidRoot}-form-bank`} value={form.bank_name || ""} onChange={set("bank_name")} className={ic} /></div>
        <div><label className={lc}>Account Number{mode === "edit" ? " (locked · use Replace)" : ""}</label>
          <input data-testid={`${testidRoot}-form-account`} disabled={mode === "edit"}
            value={form.account_number || ""} onChange={set("account_number")} className={ic} /></div>
        <div><label className={lc}>IFSC</label>
          <input data-testid={`${testidRoot}-form-ifsc`} value={form.ifsc || ""} onChange={(e) => setForm((f) => ({ ...f, ifsc: e.target.value.toUpperCase() }))} className={ic} /></div>
        <div><label className={lc}>Branch</label>
          <input data-testid={`${testidRoot}-form-branch`} value={form.branch || ""} onChange={set("branch")} className={ic} /></div>
        <div><label className={lc}>Account Type</label>
          <select data-testid={`${testidRoot}-form-type`} value={form.account_type || "savings"} onChange={set("account_type")} className={ic}>
            <option value="savings">Savings</option><option value="current">Current</option>
            <option value="cc">Cash Credit</option><option value="od">Overdraft</option>
          </select></div>
        {mode === "add" && <label className="flex items-center gap-2 text-xs mt-4">
          <input type="checkbox" data-testid={`${testidRoot}-form-primary`}
            checked={!!form.is_primary} onChange={(e) => setForm((f) => ({ ...f, is_primary: e.target.checked }))} />
          Set as primary</label>}
      </div>
      <div className="flex justify-end gap-2 mt-3">
        <button type="button" onClick={onCancel} className="px-3 py-1 text-[10px] uppercase tracking-wider border rounded-sm">Cancel</button>
        <button type="button" onClick={onSubmit} disabled={disabled}
          data-testid={`${testidRoot}-form-save`}
          className="px-3 py-1 text-[10px] uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
          {mode === "edit" ? "Save" : mode === "replace" ? "Replace" : "Add"}
        </button>
      </div>
    </div>
  );
}
