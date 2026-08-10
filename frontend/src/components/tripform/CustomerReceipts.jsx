// Iter55 — Extracted verbatim from TripForm.jsx. Zero logic changes.
import React from "react";
import { fmtCurrency } from "@/api";

// ---------- Iter39: Repeatable Customer Receipts (Diesel + Advance) ----------
export default function CustomerReceipts({ receipts, onChange }) {
  const [draft, setDraft] = React.useState({
    date: new Date().toISOString().slice(0, 10),
    type: "diesel",
    litres: "", rate: "", amount: "",
    mode: "Cash", ref_no: "", remarks: "",
  });
  const add = () => {
    const t = draft.type;
    const amt = t === "diesel"
      ? Number(draft.litres || 0) * Number(draft.rate || 0)
      : Number(draft.amount || 0);
    if (amt <= 0) return;
    const row = {
      id: `rcpt_${Date.now()}`,
      date: draft.date,
      type: t,
      amount: Number(amt.toFixed(2)),
      remarks: draft.remarks || "",
      ...(t === "diesel" ? { litres: Number(draft.litres), rate: Number(draft.rate) } : {}),
      ...(t === "advance" ? { mode: draft.mode, ref_no: draft.ref_no } : {}),
    };
    onChange([...(receipts || []), row]);
    setDraft({ ...draft, litres: "", rate: "", amount: "", ref_no: "", remarks: "" });
  };
  const del = (id) => onChange((receipts || []).filter((r) => r.id !== id));
  const ic = "w-full border border-zinc-300 px-2 py-1.5 rounded-sm text-xs focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";
  return (
    <div className="space-y-3" data-testid="customer-receipts">
      {/* Add row */}
      <div className="border border-zinc-200 rounded-sm p-3 bg-zinc-50">
        <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-2">Add Receipt</div>
        <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
          <div>
            <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Date</label>
            <input data-testid="cr-date" type="date" value={draft.date} onChange={(e) => setDraft({ ...draft, date: e.target.value })} className={ic} />
          </div>
          <div>
            <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Type</label>
            <select data-testid="cr-type" value={draft.type} onChange={(e) => setDraft({ ...draft, type: e.target.value })} className={ic}>
              <option value="diesel">Diesel</option>
              <option value="advance">Advance</option>
            </select>
          </div>
          {draft.type === "diesel" ? (
            <>
              <div>
                <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Litres</label>
                <input data-testid="cr-litres" type="number" step="0.01" min="0" value={draft.litres} onChange={(e) => setDraft({ ...draft, litres: e.target.value })} className={ic} placeholder="280" />
              </div>
              <div>
                <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Rate (₹/L)</label>
                <input data-testid="cr-rate" type="number" step="0.01" min="0" value={draft.rate} onChange={(e) => setDraft({ ...draft, rate: e.target.value })} className={ic} placeholder="104.24" />
              </div>
              <div>
                <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Total (auto)</label>
                <input value={draft.litres && draft.rate ? `₹ ${(Number(draft.litres) * Number(draft.rate)).toFixed(2)}` : ""} readOnly className={`${ic} bg-zinc-100 font-mono font-bold`} />
              </div>
            </>
          ) : (
            <>
              <div>
                <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Amount (₹)</label>
                <input data-testid="cr-amount" type="number" step="0.01" min="0" value={draft.amount} onChange={(e) => setDraft({ ...draft, amount: e.target.value })} className={ic} placeholder="20000" />
              </div>
              <div>
                <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Mode</label>
                <select data-testid="cr-mode" value={draft.mode} onChange={(e) => setDraft({ ...draft, mode: e.target.value })} className={ic}>
                  {["Cash", "Bank", "UPI", "IMPS", "NEFT", "Cash to Driver", "Other"].map((m) => <option key={m}>{m}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Ref / Txn No</label>
                <input data-testid="cr-refno" value={draft.ref_no} onChange={(e) => setDraft({ ...draft, ref_no: e.target.value })} className={ic} placeholder="Optional" />
              </div>
            </>
          )}
          <div className="flex items-end">
            <button type="button" data-testid="cr-add-btn" onClick={add} className="w-full px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold bg-emerald-600 text-white rounded-sm hover:bg-emerald-700">+ Add</button>
          </div>
          <div className="md:col-span-6">
            <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Remarks</label>
            <input data-testid="cr-remarks" value={draft.remarks} onChange={(e) => setDraft({ ...draft, remarks: e.target.value })} className={ic} placeholder="Optional notes (e.g. paid at HPCL Kondapalli / txn ref / receipt no)" />
          </div>
        </div>
      </div>

      {/* Existing receipts table */}
      {(receipts || []).length === 0 ? (
        <div className="text-xs text-zinc-500 italic px-2">No receipts added yet.</div>
      ) : (
        <div className="border border-zinc-200 rounded-sm overflow-hidden">
          <table className="w-full text-xs" data-testid="cr-list">
            <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-wider">
              <tr>
                <th className="text-left px-3 py-2">Date</th>
                <th className="text-left px-3 py-2">Type</th>
                <th className="text-left px-3 py-2">Details</th>
                <th className="text-right px-3 py-2">Amount</th>
                <th className="text-left px-3 py-2">Mode / Ref</th>
                <th className="w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {(receipts || []).map((r) => (
                <tr key={r.id} data-testid={`cr-row-${r.id}`} className="hover:bg-amber-50/50">
                  <td className="px-3 py-2 font-mono">{r.date}</td>
                  <td className="px-3 py-2 uppercase font-bold text-[10px]">
                    <span className={`px-2 py-0.5 rounded-sm border ${r.type === "diesel" ? "bg-orange-50 text-orange-800 border-orange-200" : "bg-blue-50 text-blue-800 border-blue-200"}`}>{r.type}</span>
                  </td>
                  <td className="px-3 py-2 text-zinc-600">
                    <div>
                      {r.type === "diesel"
                        ? `${r.litres} L × ₹${Number(r.rate).toFixed(2)}`
                        : (r.mode || "—")}
                    </div>
                    {r.remarks && <div className="text-[10px] text-zinc-500 italic mt-0.5">{r.remarks}</div>}
                  </td>
                  <td className="px-3 py-2 text-right font-mono font-bold">{fmtCurrency(r.amount)}</td>
                  <td className="px-3 py-2 text-zinc-600 text-[11px]">
                    {r.type === "advance" ? `${r.mode || "—"}${r.ref_no ? ` · ${r.ref_no}` : ""}` : "Customer Diesel"}
                  </td>
                  <td className="px-2 py-2 text-center">
                    <button type="button" data-testid={`cr-del-${r.id}`} onClick={() => del(r.id)} className="text-rose-600 hover:bg-rose-50 rounded p-1">×</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
