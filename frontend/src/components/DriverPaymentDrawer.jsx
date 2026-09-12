import React, { useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { X } from "lucide-react";
import CompanySourceBankSelector from "./CompanySourceBankSelector";

/** Iter150I · DriverPaymentDrawer — thin new component.
 * Does NOT modify shared PaymentDrawer. Reuses CompanySourceBankSelector
 * and existing party-bank-accounts endpoint (Iter150G) for beneficiary. */
const AGAINST = ["advance", "salary_settlement", "reimbursement", "other"];
const MODES = ["Cash", "Bank", "UPI", "IMPS", "NEFT", "RTGS", "Cheque", "Other"];

export default function DriverPaymentDrawer({ driverId, driverName = "", open, onClose, onSaved }) {
  const qc = useQueryClient();
  const empty = {
    date: new Date().toISOString().slice(0, 10),
    amount: "", mode: "Bank", against: "other", ref_no: "", remarks: "",
    bank_account_id: "", company_bank_account_id: "",
  };
  const [form, setForm] = useState(empty);
  const [salaryHint, setSalaryHint] = useState(null);

  useEffect(() => { if (open) setForm(empty); /* eslint-disable-next-line */ }, [open, driverId]);

  const { data: pbaList = [] } = useQuery({
    queryKey: ["pba-driver", driverId],
    enabled: open && !!driverId,
    queryFn: async () => (await api.get(
      `/party-bank-accounts?party_type=driver&party_id=${driverId}`)).data,
  });

  // Salary-settlement advisory (never blocks)
  useEffect(() => {
    if (!open || !driverId) return;
    if (form.against !== "salary_settlement") { setSalaryHint(null); return; }
    const month = (form.date || "").slice(0, 7);
    (async () => {
      try {
        const r = await api.get(
          `/drivers/${driverId}/salary-settlement-hint?month=${month}`);
        setSalaryHint(r.data?.possible_duplicate ? r.data : null);
      } catch { setSalaryHint(null); }
    })();
  }, [open, driverId, form.against, form.date]);

  const isCash = form.mode === "Cash";
  const activePba = (pbaList || []).filter((r) => r.is_active);
  useEffect(() => {
    if (isCash) {
      setForm((f) => ({ ...f, bank_account_id: "", company_bank_account_id: "" }));
    } else if (!form.bank_account_id && activePba.length > 0) {
      const primary = activePba.find((r) => r.is_primary) || activePba[0];
      setForm((f) => ({ ...f, bank_account_id: primary.id }));
    }
  }, [isCash, activePba.length]); // eslint-disable-line

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        driver_id: driverId, date: form.date, amount: Number(form.amount),
        mode: form.mode, against: form.against, ref_no: form.ref_no,
        remarks: form.remarks,
        bank_account_id: isCash ? "" : (form.bank_account_id || ""),
        company_bank_account_id: isCash ? "" : (form.company_bank_account_id || ""),
      };
      return (await api.post(`/drivers/${driverId}/payments`, body)).data;
    },
    onSuccess: (p) => {
      toast.success("Driver payment recorded");
      qc.invalidateQueries({ queryKey: ["driver-payments", driverId] });
      qc.invalidateQueries({ queryKey: ["driver-ledger", driverId] });
      if (onSaved) onSaved(p);
      setForm(empty);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  if (!open) return null;
  const ic = "w-full border border-zinc-300 px-2 py-1.5 rounded-sm text-sm outline-none focus:border-zinc-950";
  const lc = "text-[10px] uppercase tracking-wider font-bold text-zinc-500";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4" data-testid="driver-payment-drawer">
      <div className="bg-white w-full max-w-2xl border border-zinc-950 rounded-sm">
        <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
          <div>
            <h3 className="font-bold">Driver Payment</h3>
            <div className="text-xs text-zinc-500">{driverName || driverId}</div>
          </div>
          <button onClick={onClose} data-testid="dpd-close"><X size={18} /></button>
        </div>
        <div className="p-5 grid grid-cols-1 md:grid-cols-3 gap-3">
          <div><label className={lc}>Date</label>
            <input type="date" data-testid="dpd-date" className={ic} value={form.date}
              onChange={(e) => setForm({ ...form, date: e.target.value })} /></div>
          <div><label className={lc}>Amount</label>
            <input type="number" data-testid="dpd-amount" className={ic} value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })} /></div>
          <div><label className={lc}>Mode</label>
            <select data-testid="dpd-mode" className={ic} value={form.mode}
              onChange={(e) => setForm({ ...form, mode: e.target.value })}>
              {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
            </select></div>
          <div><label className={lc}>Against</label>
            <select data-testid="dpd-against" className={ic} value={form.against}
              onChange={(e) => setForm({ ...form, against: e.target.value })}>
              {AGAINST.map((a) => <option key={a} value={a}>{a}</option>)}
            </select></div>
          <div><label className={lc}>Ref No.</label>
            <input data-testid="dpd-ref" className={ic} value={form.ref_no}
              onChange={(e) => setForm({ ...form, ref_no: e.target.value })} /></div>
          <div><label className={lc}>Remarks</label>
            <input data-testid="dpd-remarks" className={ic} value={form.remarks}
              onChange={(e) => setForm({ ...form, remarks: e.target.value })} /></div>
          {!isCash && (
            <div className="md:col-span-2"><label className={lc}>Beneficiary Bank</label>
              <select data-testid="dpd-beneficiary-bank" className={ic}
                value={form.bank_account_id}
                onChange={(e) => setForm({ ...form, bank_account_id: e.target.value })}>
                <option value="">— None —</option>
                {activePba.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.bank_name} · {r.masked_display} {r.is_primary ? "· Primary" : ""}
                  </option>))}
              </select></div>
          )}
          {!isCash && (
            <div className="md:col-span-1" data-testid="dpd-source-bank">
              <label className={lc}>Company Source Bank</label>
              <CompanySourceBankSelector value={form.company_bank_account_id}
                onChange={(v) => setForm({ ...form, company_bank_account_id: v })} />
            </div>
          )}
          {salaryHint && (
            <div className="md:col-span-3 p-2 border border-amber-300 bg-amber-50 text-xs text-amber-900 rounded-sm"
                 data-testid="dpd-salary-advisory">
              Advisory: existing settlement found for this driver/month —
              posting is still allowed.
            </div>
          )}
        </div>
        <div className="px-5 py-3 border-t bg-white flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-xs uppercase tracking-wider border rounded-sm">Cancel</button>
          <button data-testid="dpd-record-btn" disabled={save.isPending || !form.amount}
            onClick={() => save.mutate()}
            className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm disabled:opacity-50">
            {save.isPending ? "Saving…" : "Record Payment"}
          </button>
        </div>
      </div>
    </div>
  );
}
