// Iter91 — Reusable Supplier Diesel / Advance entry table.
// Handles both "local mode" (new trip, no id yet — mutates form array in-place
// via setForm) and "persisted mode" (trip already saved — CRUD via API).
import React, { useState } from "react";
import { api, fmtCurrency } from "@/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X } from "lucide-react";
import { inputCls } from "./tripFormDefaults";

const MODES = ["Cash", "Bank", "UPI", "IMPS", "NEFT", "Other"];

const emptyDiesel = () => ({
  id: `sde_local_${Math.random().toString(36).slice(2, 10)}`,
  date: new Date().toISOString().slice(0, 10),
  quantity: "", rate: "", amount: "",
  mode: "", reference: "", remarks: "",
});
const emptyAdvance = () => ({
  id: `sae_local_${Math.random().toString(36).slice(2, 10)}`,
  date: new Date().toISOString().slice(0, 10),
  amount: "", mode: "", reference: "", remarks: "",
});

export default function SupplierEntriesTable({
  kind,          // 'diesel' | 'advance'
  entries = [],
  tripId,        // null when new trip
  onLocalChange, // (updated entries) => void (local mode)
  onServerRefresh, // (updated trip) => void (persisted mode)
}) {
  const isDiesel = kind === "diesel";
  const label = isDiesel ? "Diesel" : "Advance";
  const testPrefix = isDiesel ? "sup-diesel" : "sup-advance";
  const endpoint = isDiesel ? "supplier-diesel" : "supplier-advance";

  const [editing, setEditing] = useState(null);  // entry being edited (id ref)
  const [showModal, setShowModal] = useState(false);
  const [modalForm, setModalForm] = useState(isDiesel ? emptyDiesel() : emptyAdvance());
  const [saving, setSaving] = useState(false);

  const active = (entries || []).filter((e) => !e.deleted);
  const total = active.reduce((s, e) => s + Number(e.amount || 0), 0);

  const openAdd = () => {
    setEditing(null);
    setModalForm(isDiesel ? emptyDiesel() : emptyAdvance());
    setShowModal(true);
  };
  const openEdit = (e) => {
    setEditing(e.id);
    setModalForm({ ...e });
    setShowModal(true);
  };
  const closeModal = () => { setShowModal(false); setEditing(null); };

  const commitLocal = (nextList) => {
    onLocalChange && onLocalChange(nextList);
  };

  const save = async () => {
    let amt = Number(modalForm.amount || 0);
    if (isDiesel) {
      const q = Number(modalForm.quantity || 0);
      const r = Number(modalForm.rate || 0);
      if ((!amt || amt <= 0) && q > 0 && r > 0) amt = q * r;
    }
    if (!amt || amt <= 0) {
      toast.error("Amount required");
      return;
    }
    const payload = { ...modalForm, amount: amt };
    setSaving(true);
    try {
      if (tripId) {
        // Persisted mode — API round-trip
        if (editing) {
          const r = await api.put(`/trips/${tripId}/${endpoint}/${editing}`, payload);
          onServerRefresh && onServerRefresh(r.data);
          toast.success(`${label} entry updated`);
        } else {
          const r = await api.post(`/trips/${tripId}/${endpoint}`, payload);
          onServerRefresh && onServerRefresh(r.data);
          toast.success(`${label} entry added`);
        }
      } else {
        // Local mode — mutate the form array
        const next = [...(entries || [])];
        if (editing) {
          const i = next.findIndex((e) => e.id === editing);
          if (i >= 0) next[i] = { ...next[i], ...payload };
        } else {
          next.push({ ...payload, deleted: false });
        }
        commitLocal(next);
      }
      closeModal();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const del = async (entry) => {
    const reason = window.prompt(`Reason for deleting this ${label.toLowerCase()} entry?`) || "";
    if (!reason.trim()) {
      toast.error("Reason required");
      return;
    }
    try {
      if (tripId) {
        const r = await api.delete(`/trips/${tripId}/${endpoint}/${entry.id}`, {
          params: { reason: reason.trim() },
        });
        onServerRefresh && onServerRefresh(r.data);
        toast.success(`${label} entry removed`);
      } else {
        // Local mode — hard-remove is fine since nothing has been persisted yet.
        const next = (entries || []).filter((e) => e.id !== entry.id);
        commitLocal(next);
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    }
  };

  return (
    <div className="border border-zinc-200 bg-zinc-50 rounded-sm p-3" data-testid={`${testPrefix}-block`}>
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] uppercase tracking-wider font-bold text-zinc-700">
          Supplier {label} Entries
          {tripId ? null : <span className="ml-2 text-[10px] font-normal text-zinc-500 normal-case">(will save with the trip)</span>}
        </div>
        <button
          type="button"
          data-testid={`${testPrefix}-add-btn`}
          onClick={openAdd}
          className="inline-flex items-center gap-1 px-3 py-1.5 text-[11px] uppercase tracking-wider font-bold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800"
        >
          <Plus size={12} /> Add {label}
        </button>
      </div>

      {active.length === 0 ? (
        <div className="text-xs text-zinc-500 italic py-2" data-testid={`${testPrefix}-empty`}>
          No {label.toLowerCase()} entries yet. Click <b>Add {label}</b> to record one.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid={`${testPrefix}-table`}>
            <thead className="text-[10px] uppercase text-zinc-500">
              <tr className="border-b border-zinc-200">
                <th className="text-left py-1.5 px-2">Date</th>
                {isDiesel && <th className="text-right py-1.5 px-2">Qty (L)</th>}
                {isDiesel && <th className="text-right py-1.5 px-2">Rate</th>}
                <th className="text-right py-1.5 px-2">Amount</th>
                <th className="text-left py-1.5 px-2">Mode</th>
                <th className="text-left py-1.5 px-2">Ref</th>
                <th className="text-left py-1.5 px-2">Remarks</th>
                <th className="py-1.5 px-2 w-16"></th>
              </tr>
            </thead>
            <tbody>
              {active.map((e) => (
                <tr key={e.id} className="border-b border-zinc-100 hover:bg-white" data-testid={`${testPrefix}-row-${e.id}`}>
                  <td className="py-1.5 px-2 font-mono">{e.date || "—"}</td>
                  {isDiesel && <td className="py-1.5 px-2 text-right font-mono">{Number(e.quantity || 0) || "—"}</td>}
                  {isDiesel && <td className="py-1.5 px-2 text-right font-mono">{Number(e.rate || 0) || "—"}</td>}
                  <td className="py-1.5 px-2 text-right font-mono font-bold">{fmtCurrency(e.amount)}</td>
                  <td className="py-1.5 px-2">{e.mode || "—"}</td>
                  <td className="py-1.5 px-2">{e.reference || "—"}</td>
                  <td className="py-1.5 px-2 max-w-[160px] truncate" title={e.remarks || ""}>{e.remarks || "—"}</td>
                  <td className="py-1.5 px-2 flex justify-end gap-1">
                    <button type="button" onClick={() => openEdit(e)} className="p-1 hover:bg-zinc-200 rounded-sm" title="Edit" data-testid={`${testPrefix}-edit-${e.id}`}>
                      <Pencil size={12} />
                    </button>
                    <button type="button" onClick={() => del(e)} className="p-1 hover:bg-rose-100 text-rose-700 rounded-sm" title="Delete" data-testid={`${testPrefix}-del-${e.id}`}>
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              ))}
              <tr className="bg-zinc-100 font-bold">
                <td colSpan={isDiesel ? 3 : 1} className="py-2 px-2 text-right uppercase text-[10px] tracking-wider">Total</td>
                <td className="py-2 px-2 text-right font-mono" data-testid={`${testPrefix}-total`}>{fmtCurrency(total)}</td>
                <td colSpan={4}></td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/50 backdrop-blur-sm p-4" data-testid={`${testPrefix}-modal`}>
          <div className="bg-white w-full max-w-md border border-zinc-950 rounded-sm flex flex-col max-h-[90vh]">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200 shrink-0">
              <h3 className="font-bold text-sm uppercase tracking-wider">{editing ? "Edit" : "Add"} {label}</h3>
              <button onClick={closeModal} data-testid={`${testPrefix}-modal-close`}><X size={16} /></button>
            </div>
            <div className="p-5 space-y-3 overflow-y-auto flex-1">
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Date *</label>
                <input type="date" value={modalForm.date || ""} onChange={(e) => setModalForm({ ...modalForm, date: e.target.value })} className={inputCls} data-testid={`${testPrefix}-modal-date`} />
              </div>
              {isDiesel && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Quantity (Litres)</label>
                    <input type="number" step="0.01" min="0" value={modalForm.quantity ?? ""} onChange={(e) => setModalForm({ ...modalForm, quantity: e.target.value })} className={inputCls} data-testid={`${testPrefix}-modal-qty`} />
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Rate (₹/L)</label>
                    <input type="number" step="0.01" min="0" value={modalForm.rate ?? ""} onChange={(e) => setModalForm({ ...modalForm, rate: e.target.value })} className={inputCls} data-testid={`${testPrefix}-modal-rate`} />
                  </div>
                </div>
              )}
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Amount (₹) *</label>
                <input type="number" step="0.01" min="0" value={modalForm.amount ?? ""} onChange={(e) => setModalForm({ ...modalForm, amount: e.target.value })} className={inputCls}
                  placeholder={isDiesel ? "Auto = Qty × Rate if blank" : "Advance amount"} data-testid={`${testPrefix}-modal-amount`} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Mode</label>
                  <select value={modalForm.mode || ""} onChange={(e) => setModalForm({ ...modalForm, mode: e.target.value })} className={inputCls} data-testid={`${testPrefix}-modal-mode`}>
                    <option value="">—</option>
                    {MODES.map((m) => (<option key={m} value={m}>{m}</option>))}
                  </select>
                </div>
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Reference / Txn #</label>
                  <input value={modalForm.reference || ""} onChange={(e) => setModalForm({ ...modalForm, reference: e.target.value })} className={inputCls} data-testid={`${testPrefix}-modal-ref`} />
                </div>
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Remarks</label>
                <input value={modalForm.remarks || ""} onChange={(e) => setModalForm({ ...modalForm, remarks: e.target.value })} className={inputCls} data-testid={`${testPrefix}-modal-remarks`} />
              </div>
            </div>
            <div className="flex justify-end gap-2 px-5 py-3 border-t border-zinc-200 shrink-0">
              <button type="button" onClick={closeModal} className="px-4 py-2 text-xs uppercase tracking-wider font-bold border border-zinc-300 rounded-sm">Cancel</button>
              <button type="button" onClick={save} disabled={saving} data-testid={`${testPrefix}-modal-save`} className="px-4 py-2 text-xs uppercase tracking-wider font-bold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
                {saving ? "Saving…" : (editing ? "Update" : "Add")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
