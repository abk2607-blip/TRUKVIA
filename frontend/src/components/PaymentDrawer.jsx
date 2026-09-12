import React, { useState, useEffect } from "react";
import { useMutation, useQueryClient, useQuery } from "@tanstack/react-query";
import { api, errMsg } from "@/api";
import { toast } from "sonner";
import { X } from "lucide-react";
import CompanySourceBankSelector from "./CompanySourceBankSelector";

/**
 * Iter133 · Turn 3 · Slice A — Reusable Payment Quick-Entry Drawer.
 *
 * Props:
 *   partyType: "vendor" | "mechanic"       (required)
 *   partyId:   string                       (required)
 *   partyName: string                       (label only)
 *   open:      boolean
 *   onClose:   () => void
 *   onSaved:   (payment) => void
 *   prefill:   { billOrWo? : {id, number, amount, outstanding?}, amount? }
 *
 * Backend contracts:
 *   POST /api/vendors/{vid}/payments
 *   POST /api/mechanics/{mid}/payments
 *
 * INVARIANT: Creating a Payment must never create/modify an Expense.
 * The backend routers do not touch expenses. This drawer only calls
 * the payment endpoint — nothing else.
 */
export default function PaymentDrawer({
  partyType, partyId, partyName = "", open, onClose, onSaved, prefill = {},
}) {
  const qc = useQueryClient();
  const isVendor = partyType === "vendor";
  const url = isVendor
    ? `/vendors/${partyId}/payments`
    : `/mechanics/${partyId}/payments`;
  const openBillsUrl = isVendor
    ? `/vendor-bills?vendor_id=${partyId}`
    : `/mechanic-work-orders?mechanic_id=${partyId}`;

  const today = () => new Date().toISOString().slice(0, 10);
  const initialForm = () => ({
    type: "payment_out",
    date: today(),
    amount: "",
    mode: "Bank",
    ref_no: "",
    against: prefill.billOrWo ? (isVendor ? "bill" : "work_order") : "outstanding",
    linked_id: prefill.billOrWo?.id || "",
    remarks: "",
    company_bank_account_id: "",
  });
  const [form, setForm] = useState(initialForm());
  useEffect(() => { if (open) setForm(initialForm()); /* eslint-disable-next-line */ }, [open, partyId]);

  const openList = useQuery({
    queryKey: [isVendor ? "vendor-bills" : "mechanic-work-orders", partyId, "open"],
    queryFn: async () => (await api.get(openBillsUrl)).data,
    enabled: open && !!partyId,
  });

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        [isVendor ? "vendor_id" : "mechanic_id"]: partyId,
        type: form.type,
        date: form.date,
        amount: Number(form.amount),
        mode: form.mode,
        ref_no: form.ref_no,
        against: form.against,
        remarks: form.remarks,
      };
      if (form.linked_id) {
        if (isVendor) body.vendor_bill_id = form.linked_id;
        else body.mechanic_work_order_id = form.linked_id;
      }
      if (form.company_bank_account_id) body.company_bank_account_id = form.company_bank_account_id;
      return (await api.post(url, body)).data;
    },
    onSuccess: (data) => {
      toast.success("Payment saved");
      qc.invalidateQueries({ queryKey: [`${partyType}-ledger`, partyId] });
      qc.invalidateQueries({ queryKey: ["vehicle-repair-history"] });
      if (onSaved) onSaved(data);
      onClose();
    },
    onError: (e) => toast.error(errMsg(e, "Payment failed")),
  });

  if (!open) return null;

  const validAmount = Number(form.amount) > 0;
  const validDate = !!form.date;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/60 p-4" data-testid="payment-drawer">
      <div className="bg-white w-full max-w-lg border rounded-sm">
        <div className="flex items-center justify-between px-5 py-3 border-b">
          <div>
            <h3 className="font-bold">+ {isVendor ? "Vendor" : "Mechanic"} Payment</h3>
            <div className="text-xs text-zinc-500">{partyName || partyId}</div>
          </div>
          <button onClick={onClose} data-testid="payment-drawer-close"><X size={18} /></button>
        </div>
        <div className="p-5 space-y-3 max-h-[70vh] overflow-y-auto">
          {prefill.billOrWo && (
            <div className="text-xs bg-amber-50 border border-amber-200 rounded-sm p-2" data-testid="payment-prefill">
              Against <b>{isVendor ? "Bill" : "Work Order"} {prefill.billOrWo.number || prefill.billOrWo.id}</b> ·
              Amount ₹{Number(prefill.billOrWo.amount || 0).toLocaleString("en-IN")}
              {prefill.billOrWo.outstanding !== undefined && (
                <> · Outstanding ₹{Number(prefill.billOrWo.outstanding).toLocaleString("en-IN")}</>
              )}
              <div className="text-[10px] text-zinc-500 mt-1">You can enter a partial amount — the payment does NOT change Vehicle Cost.</div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <F label="Type *">
              <select data-testid="payment-type" value={form.type}
                onChange={(e) => setForm((f) => ({ ...f, type: e.target.value }))} className={ic}>
                <option value="payment_out">Payment Out (we pay)</option>
                <option value="receipt_in">Receipt In (refund/return)</option>
              </select>
            </F>
            <F label="Date *">
              <input data-testid="payment-date" type="date" value={form.date}
                onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))} className={ic} />
            </F>
            <F label="Amount * (₹)">
              <input data-testid="payment-amount" type="number" step="0.01" min="0.01" value={form.amount}
                onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))} className={ic}
                placeholder="e.g. 10000" />
            </F>
            <F label="Mode">
              <select data-testid="payment-mode" value={form.mode}
                onChange={(e) => setForm((f) => ({ ...f, mode: e.target.value }))} className={ic}>
                {["Bank", "Cash", "UPI", "IMPS", "NEFT", "RTGS", "Cheque", "Other"].map((x) =>
                  <option key={x} value={x}>{x}</option>)}
              </select>
            </F>
            <F label="Ref / UTR">
              <input data-testid="payment-ref" value={form.ref_no}
                onChange={(e) => setForm((f) => ({ ...f, ref_no: e.target.value }))} className={ic} />
            </F>
            <F label={isVendor ? "Against Bill (optional)" : "Against Work Order (optional)"}>
              <select data-testid="payment-linked"
                value={form.linked_id}
                onChange={(e) => setForm((f) => ({
                  ...f,
                  linked_id: e.target.value,
                  against: e.target.value ? (isVendor ? "bill" : "work_order") : "outstanding",
                }))} className={ic}>
                <option value="">— Outstanding (no specific {isVendor ? "bill" : "WO"}) —</option>
                {(openList.data || []).map((b) => (
                  <option key={b.id} value={b.id}>
                    {isVendor
                      ? `${b.bill_number || b.id} · ${b.bill_date} · ₹${Number(b.bill_amount || 0).toLocaleString("en-IN")}`
                      : `${b.id} · ${b.work_date} · ₹${Number(b.amount || 0).toLocaleString("en-IN")}`}
                  </option>
                ))}
              </select>
            </F>
          </div>
          <F label="Company Source Bank (optional)">
            <CompanySourceBankSelector
              value={form.company_bank_account_id}
              onChange={(v) => setForm((f) => ({ ...f, company_bank_account_id: v }))}
            />
          </F>
          <F label="Remarks">
            <input data-testid="payment-remarks" value={form.remarks}
              onChange={(e) => setForm((f) => ({ ...f, remarks: e.target.value }))} className={ic} />
          </F>
          <p className="text-[11px] text-zinc-500 border-t pt-2" data-testid="payment-invariant-note">
            <b>Vehicle Cost does not change.</b> A payment only settles the payable — the vendor/mechanic
            outstanding drops; the Expense (cost) row is not touched.
          </p>
        </div>
        <div className="px-5 py-3 border-t bg-white flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-xs uppercase tracking-wider border rounded-sm">Cancel</button>
          <button data-testid="save-payment-btn"
            disabled={save.isPending || !validAmount || !validDate}
            onClick={() => save.mutate()}
            className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
            {save.isPending ? "Saving…" : "Save Payment"}
          </button>
        </div>
      </div>
    </div>
  );
}

const ic = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm outline-none focus:border-zinc-950 bg-white";
function F({ label, children }) {
  return (
    <div>
      <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">{label}</label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
