// Iter55 — Extracted verbatim from TripForm.jsx. Zero logic changes.
import React from "react";
import { toast } from "sonner";
import { fmtCurrency } from "@/api";

// ---------- Iter40: Dynamic Other Expenditure list backed by Expenditure Master ----------
export default function OtherExpenditures({ rows, types, onChange, onCreateType }) {
  const [draft, setDraft] = React.useState({
    date: new Date().toISOString().slice(0, 10),
    type: "",
    amount: "",
    remarks: "",
  });
  const [newType, setNewType] = React.useState("");
  const ic = "w-full border border-zinc-300 px-2 py-1.5 rounded-sm text-xs focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";

  const add = () => {
    const amt = Number(draft.amount || 0);
    const type = (draft.type || "").trim();
    if (!type || amt <= 0) {
      toast.error("Choose a type and enter an amount");
      return;
    }
    onChange([
      ...(rows || []),
      { id: `oe_${Date.now()}`, date: draft.date, type, amount: Number(amt.toFixed(2)), remarks: draft.remarks || "" },
    ]);
    setDraft({ ...draft, amount: "", remarks: "" });
  };
  const del = (id) => onChange((rows || []).filter((r) => r.id !== id));
  const addNewType = async () => {
    const n = (newType || "").trim();
    if (!n) return;
    const created = await onCreateType(n);
    if (created) {
      setDraft({ ...draft, type: created.name });
      setNewType("");
      toast.success(`Added "${created.name}" to Expenditure Master`);
    }
  };

  const total = (rows || []).reduce((s, r) => s + Number(r.amount || 0), 0);

  return (
    <div className="space-y-3" data-testid="other-expenditures">
      <div className="border border-zinc-200 rounded-sm p-3 bg-zinc-50">
        <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-2">Add Expenditure</div>
        <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
          <div>
            <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Date</label>
            <input data-testid="oe-date" type="date" value={draft.date} onChange={(e) => setDraft({ ...draft, date: e.target.value })} className={ic} />
          </div>
          <div className="md:col-span-2">
            <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Type · రకం</label>
            <select data-testid="oe-type" value={draft.type} onChange={(e) => setDraft({ ...draft, type: e.target.value })} className={ic}>
              <option value="">— Select type —</option>
              {(types || []).map((t) => (
                <option key={t.id} value={t.name}>{t.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Amount (₹)</label>
            <input data-testid="oe-amount" type="number" step="0.01" min="0" value={draft.amount} onChange={(e) => setDraft({ ...draft, amount: e.target.value })} className={ic} placeholder="0" />
          </div>
          <div className="md:col-span-2">
            <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Remarks</label>
            <input data-testid="oe-remarks" value={draft.remarks} onChange={(e) => setDraft({ ...draft, remarks: e.target.value })} className={ic} placeholder="Optional context" />
          </div>
          <div className="md:col-span-6 flex flex-col md:flex-row md:items-end gap-2 mt-1">
            <button type="button" data-testid="oe-add-btn" onClick={add} className="px-4 py-1.5 text-[10px] uppercase tracking-wider font-bold bg-emerald-600 text-white rounded-sm hover:bg-emerald-700">
              + Add Expenditure
            </button>
            <div className="flex items-center gap-2 flex-1 md:justify-end">
              <input
                data-testid="oe-new-type-input"
                value={newType}
                onChange={(e) => setNewType(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addNewType(); } }}
                className={`${ic} max-w-[220px]`}
                placeholder="Add new type to master…"
              />
              <button type="button" data-testid="oe-add-type-btn" onClick={addNewType} className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100">
                + Type
              </button>
            </div>
          </div>
        </div>
      </div>

      {(rows || []).length === 0 ? (
        <div className="text-xs text-zinc-500 italic px-2">No expenditures added yet.</div>
      ) : (
        <div className="border border-zinc-200 rounded-sm overflow-hidden">
          <table className="w-full text-xs" data-testid="oe-list">
            <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-wider">
              <tr>
                <th className="text-left px-3 py-2">Date</th>
                <th className="text-left px-3 py-2">Type</th>
                <th className="text-left px-3 py-2">Remarks</th>
                <th className="text-right px-3 py-2">Amount</th>
                <th className="w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {(rows || []).map((r) => (
                <tr key={r.id} data-testid={`oe-row-${r.id}`} className="hover:bg-amber-50/50">
                  <td className="px-3 py-2 font-mono">{r.date}</td>
                  <td className="px-3 py-2 font-bold">{r.type}</td>
                  <td className="px-3 py-2 text-zinc-600 italic">{r.remarks || "—"}</td>
                  <td className="px-3 py-2 text-right font-mono font-bold">{fmtCurrency(r.amount)}</td>
                  <td className="px-2 py-2 text-center">
                    <button type="button" data-testid={`oe-del-${r.id}`} onClick={() => del(r.id)} className="text-rose-600 hover:bg-rose-50 rounded p-1">×</button>
                  </td>
                </tr>
              ))}
              <tr className="bg-zinc-50 font-bold">
                <td colSpan={3} className="px-3 py-2 text-right uppercase tracking-wider text-[10px]">Total</td>
                <td className="px-3 py-2 text-right font-mono" data-testid="oe-total">{fmtCurrency(total)}</td>
                <td></td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
