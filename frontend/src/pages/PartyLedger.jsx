import React, { useState, useMemo } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";

/**
 * Iter133 · Turn 2C — Party Ledger (Vendor OR Mechanic) + Admin correction.
 * Route: /vendor-ledger/:id  or  /mechanic-ledger/:id
 * Reads DERIVED ledger from Bills/WOs + Payments (never Expense).
 * Admin/Owner sees "Correct" button on each payment row.
 */
export default function PartyLedger({ partyType }) {
  const { id } = useParams();
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = ["owner", "admin"].includes((user?.effective_role || "").toLowerCase());

  const base = partyType === "vendor" ? "vendors" : "mechanics";
  const paymentsBase = partyType === "vendor" ? "vendor-payments" : "mechanic-payments";
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [showReversed, setShowReversed] = useState(false);
  const [correcting, setCorrecting] = useState(null); // payment row or null
  const [mode, setMode] = useState("attribute"); // "attribute" | "amount"
  const [form, setForm] = useState({});

  const params = useMemo(() => {
    const p = {};
    if (from) p.from = from;
    if (to) p.to = to;
    if (showReversed) p.include_reversed = true;
    return p;
  }, [from, to, showReversed]);

  const ledger = useQuery({
    queryKey: [`${partyType}-ledger`, id, params],
    queryFn: async () => (await api.get(`/${base}/${id}/ledger`, { params })).data,
  });

  const applyCorrection = useMutation({
    mutationFn: async () => {
      const key = `pcr-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      const url = mode === "amount"
        ? `/${paymentsBase}/${correcting.id}/correct-amount`
        : `/${paymentsBase}/${correcting.id}/correct`;
      const body = mode === "amount"
        ? { new_amount: parseFloat(form.new_amount),
            correction_reason: form.correction_reason,
            force_reconciled_override: !!form.force_override,
            expected_correction_count: correcting.correction_count ?? 0 }
        : { changes: form.changes || {},
            correction_reason: form.correction_reason,
            force_reconciled_override: !!form.force_override,
            expected_correction_count: correcting.correction_count ?? 0 };
      return (await api.post(url, body, { headers: { "Idempotency-Key": key } })).data;
    },
    onSuccess: () => {
      toast.success("Correction applied");
      qc.invalidateQueries({ queryKey: [`${partyType}-ledger`, id] });
      setCorrecting(null); setForm({}); setMode("attribute");
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Correction failed"),
  });

  const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;

  return (
    <div className="p-6 space-y-4" data-testid="party-ledger">
      <h1 className="text-2xl font-semibold">
        {partyType === "vendor" ? "Vendor" : "Mechanic"} Ledger — {ledger.data?.[`${partyType}_name`] || id}
      </h1>
      <div className="bg-white border rounded-lg p-4 flex flex-wrap gap-3 items-end">
        <label className="text-sm">From
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)}
            className="ml-2 border rounded px-2 py-1" data-testid="filter-from" />
        </label>
        <label className="text-sm">To
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)}
            className="ml-2 border rounded px-2 py-1" data-testid="filter-to" />
        </label>
        <label className="text-sm flex items-center gap-1">
          <input type="checkbox" checked={showReversed}
            onChange={(e) => setShowReversed(e.target.checked)}
            data-testid="show-reversed" />
          Show reversed payments
        </label>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Kpi label="Total Debit" value={fmt(ledger.data?.total_debit)} testid="kpi-debit" />
        <Kpi label="Total Credit" value={fmt(ledger.data?.total_credit)} testid="kpi-credit" />
        <Kpi label="Outstanding" value={fmt(ledger.data?.outstanding)} testid="kpi-outstanding" />
        <Kpi label="Advance" value={fmt(ledger.data?.advance)} testid="kpi-advance" />
      </div>

      <div className="bg-white border rounded-lg p-4 overflow-x-auto" data-testid="ledger-table">
        {ledger.isLoading ? <div>Loading…</div> :
         (ledger.data?.entries || []).length === 0 ? <div className="text-zinc-400">No entries.</div> :
         <table className="w-full text-sm">
           <thead className="bg-zinc-50">
             <tr className="text-left">
               <th className="py-2 px-2">Date</th>
               <th className="py-2 px-2">Kind</th>
               <th className="py-2 px-2">Ref</th>
               <th className="py-2 px-2">Narration</th>
               <th className="py-2 px-2 text-right">Debit</th>
               <th className="py-2 px-2 text-right">Credit</th>
               <th className="py-2 px-2 text-right">Balance</th>
               {isAdmin && <th className="py-2 px-2 text-right">Action</th>}
             </tr>
           </thead>
           <tbody>
             {ledger.data.entries.map((e, i) => (
               <tr key={i} className={"border-t " + (e.is_reversed ? "opacity-50 line-through" : "")}
                   data-testid={`ledger-row-${i}`}>
                 <td className="py-2 px-2">{e.date}</td>
                 <td className="py-2 px-2">{e.kind}</td>
                 <td className="py-2 px-2 font-mono text-xs">{e.ref}</td>
                 <td className="py-2 px-2">{e.narration}</td>
                 <td className="py-2 px-2 text-right">{e.debit ? fmt(e.debit) : "—"}</td>
                 <td className="py-2 px-2 text-right">{e.credit ? fmt(e.credit) : "—"}</td>
                 <td className="py-2 px-2 text-right font-medium">{fmt(e.balance)}</td>
                 {isAdmin && (
                   <td className="py-2 px-2 text-right">
                     {e.kind === "payment" && !e.is_reversed && (
                       <button
                         data-testid={`correct-btn-${e.id}`}
                         onClick={() => { setCorrecting(e); setMode("attribute"); setForm({ changes: {} }); }}
                         className="text-xs px-2 py-1 border rounded hover:bg-zinc-950 hover:text-white"
                       >Correct</button>
                     )}
                   </td>
                 )}
               </tr>
             ))}
           </tbody>
         </table>}
      </div>

      {correcting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/60 p-4"
             data-testid="correction-modal">
          <div className="bg-white w-full max-w-lg border rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">Correct Payment {correcting.id}</h3>
              <button onClick={() => { setCorrecting(null); setForm({}); }}
                      className="text-zinc-500">×</button>
            </div>
            <div className="flex gap-3 text-sm">
              <label><input type="radio" checked={mode === "attribute"}
                            onChange={() => setMode("attribute")} data-testid="mode-attribute"/> Attribute</label>
              <label><input type="radio" checked={mode === "amount"}
                            onChange={() => setMode("amount")} data-testid="mode-amount"/> Amount (reversal + new)</label>
            </div>
            {mode === "attribute" ? (
              <div className="space-y-2 text-sm">
                <label className="block">New Ref/UTR
                  <input className="w-full border rounded px-2 py-1"
                         data-testid="new-ref"
                         onChange={(e) => setForm((f) => ({ ...f, changes: { ...(f.changes||{}), ref_no: e.target.value } }))} />
                </label>
                <label className="block">New Remarks
                  <input className="w-full border rounded px-2 py-1"
                         data-testid="new-remarks"
                         onChange={(e) => setForm((f) => ({ ...f, changes: { ...(f.changes||{}), remarks: e.target.value } }))} />
                </label>
              </div>
            ) : (
              <label className="block text-sm">New Amount (₹)
                <input type="number" className="w-full border rounded px-2 py-1"
                       data-testid="new-amount"
                       onChange={(e) => setForm((f) => ({ ...f, new_amount: e.target.value }))} />
              </label>
            )}
            <label className="block text-sm">Correction reason (min 10 chars, mandatory)
              <textarea className="w-full border rounded px-2 py-1"
                        data-testid="correction-reason"
                        rows={2}
                        onChange={(e) => setForm((f) => ({ ...f, correction_reason: e.target.value }))} />
            </label>
            <label className="flex gap-2 items-center text-sm">
              <input type="checkbox"
                     onChange={(e) => setForm((f) => ({ ...f, force_override: e.target.checked }))}
                     data-testid="force-override" />
              Force override reconciled payment
            </label>
            <div className="flex justify-end gap-2">
              <button className="px-3 py-1 border rounded"
                      onClick={() => { setCorrecting(null); setForm({}); }}
                      data-testid="cancel-correction">Cancel</button>
              <button className="px-3 py-1 bg-zinc-950 text-white rounded"
                      onClick={() => applyCorrection.mutate()}
                      disabled={applyCorrection.isPending}
                      data-testid="submit-correction">
                {applyCorrection.isPending ? "Applying…" : "Apply Correction"}
              </button>
            </div>
          </div>
        </div>
      )}

      <p className="text-xs text-zinc-400" data-testid="source-note">
        Ledger reads Bills / Work Orders + Payments only. Expense collection is NEVER read as
        ledger truth. Amount corrections create a reversal + fresh row so the real cashbook
        history is preserved.
      </p>
    </div>
  );
}

function Kpi({ label, value, testid }) {
  return (
    <div className="bg-white border rounded-lg p-4" data-testid={testid}>
      <div className="text-xs text-zinc-500 uppercase">{label}</div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
    </div>
  );
}
