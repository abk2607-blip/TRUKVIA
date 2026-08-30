import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, API, fmtCurrency, fmtDate } from "@/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { X, Download, Ban, Send } from "lucide-react";

const PERMS = {
  create_note: { owner: true, accountant: true, admin: true, viewer: false },
  issue_note: { owner: true, accountant: true, admin: true, viewer: false },
  cancel_note: { owner: true, admin: true, accountant: false, viewer: false },
};
function has(user, perm) {
  const role = user?.effective_role || user?.role;
  // Permissive-by-default: allow unless explicitly viewer. Backend enforces.
  if (role === "viewer") return false;
  if (!role) return true;
  return Boolean(PERMS[perm]?.[role]);
}

export default function NoteDetailDialog({ nid, onClose }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const [cancelReason, setCancelReason] = useState("");
  const [showCancel, setShowCancel] = useState(false);

  // Note kind is unknown — try credit first, fall back to debit.
  const { data: note, isLoading } = useQuery({
    queryKey: ["note", nid],
    queryFn: async () => {
      try {
        return (await api.get(`/credit-notes/${nid}`)).data;
      } catch {
        return (await api.get(`/debit-notes/${nid}`)).data;
      }
    },
  });

  const basePath = note?.kind === "debit" ? "/debit-notes" : "/credit-notes";
  const noteToken = note?.pdf_share_token; // not used today; PDF endpoint uses auth cookie/header

  const issueMut = useMutation({
    mutationFn: async () => (await api.post(`${basePath}/${nid}/issue`)).data,
    onSuccess: () => { toast.success("Issued"); qc.invalidateQueries(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });
  const cancelMut = useMutation({
    mutationFn: async () => (await api.post(`${basePath}/${nid}/cancel`, { reason: cancelReason.trim() })).data,
    onSuccess: () => { toast.success("Cancelled"); qc.invalidateQueries(); setShowCancel(false); onClose(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const downloadPdf = async () => {
    try {
      const r = await api.get(`${basePath}/${nid}/pdf`, { responseType: "blob" });
      const url = window.URL.createObjectURL(r.data);
      window.open(url, "_blank");
      setTimeout(() => window.URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "PDF unavailable");
    }
  };

  if (isLoading) {
    return (
      <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
           data-testid="note-detail-dialog">
        <div className="bg-white rounded-md p-6 text-sm">Loading…</div>
      </div>
    );
  }
  if (!note) return null;

  const kindLabel = note.kind === "debit" ? "Debit Note" : "Credit Note";
  const kindColor = note.kind === "debit" ? "bg-orange-50 border-orange-300 text-orange-800" : "bg-emerald-50 border-emerald-300 text-emerald-800";

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start sm:items-center justify-center p-2 overflow-y-auto"
         data-testid="note-detail-dialog"
         onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="bg-white rounded-md w-full max-w-2xl my-4 shadow-xl">
        <div className={`flex items-center justify-between px-4 py-3 border-b ${kindColor}`}>
          <div>
            <div className="font-bold">{kindLabel}</div>
            <div className="text-xs">{note.note_number || "(draft)"} · <span data-testid="note-detail-status-pill" className="uppercase font-semibold">{note.status}</span></div>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-white/50 rounded-sm"><X size={16} /></button>
        </div>

        <div className="p-4 space-y-3 text-sm">
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div><span className="text-zinc-500">Note date:</span> <span className="font-semibold">{fmtDate(note.note_date)}</span></div>
            <div><span className="text-zinc-500">Invoice:</span> <span className="font-semibold">{note.invoice_number_snapshot}</span></div>
            <div><span className="text-zinc-500">Reason code:</span> <span className="font-semibold">{note.reason_code}</span></div>
            <div><span className="text-zinc-500">Total:</span> <span className="font-semibold">{fmtCurrency(note.total_amount)}</span></div>
          </div>

          <div className="text-xs text-zinc-700 bg-zinc-50 border border-zinc-200 p-2 rounded-sm">
            <div className="text-zinc-500 uppercase tracking-wide font-semibold text-[10px]">Reason</div>
            {note.reason_text}
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wide font-bold text-zinc-500 mb-1">Line items</div>
            <table className="w-full text-xs border border-zinc-200">
              <thead className="bg-zinc-50">
                <tr>
                  <th className="p-1.5 text-left">Description</th>
                  <th className="p-1.5 text-right">Qty</th>
                  <th className="p-1.5 text-right">Rate</th>
                  <th className="p-1.5 text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {(note.lines || []).map((l, i) => (
                  <tr key={i} className="border-t border-zinc-100">
                    <td className="p-1.5">{l.description}</td>
                    <td className="p-1.5 text-right">{l.quantity}</td>
                    <td className="p-1.5 text-right">{fmtCurrency(l.rate)}</td>
                    <td className="p-1.5 text-right font-semibold">{fmtCurrency(l.taxable_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid grid-cols-2 gap-3 text-xs">
            <div><span className="text-zinc-500">Subtotal:</span> {fmtCurrency(note.subtotal)}</div>
            <div><span className="text-zinc-500">Total tax:</span> {fmtCurrency(note.total_tax)}</div>
            <div className="col-span-2 border-t pt-1 mt-1">
              <span className="text-zinc-500">Grand total:</span> <span className="font-bold">{fmtCurrency(note.total_amount)}</span>
              {note.rcm && <span className="ml-2 text-[10px] font-semibold bg-purple-100 text-purple-800 px-1 py-0.5 rounded-sm">RCM</span>}
            </div>
          </div>

          {note.status === "cancelled" && (
            <div className="bg-red-50 border border-red-200 rounded-sm p-2 text-xs">
              <div className="font-semibold text-red-800">Cancelled on {fmtDate(note.cancelled_at)}</div>
              <div className="text-red-700">{note.cancelled_reason}</div>
            </div>
          )}
        </div>

        <div className="flex flex-wrap justify-end gap-2 px-4 py-3 border-t bg-zinc-50">
          {(note.status === "issued" || note.status === "cancelled") && (
            <button
              data-testid="note-detail-pdf-download-btn"
              onClick={downloadPdf}
              className="inline-flex items-center gap-1 text-sm px-3 py-1.5 border border-zinc-300 rounded-sm hover:bg-white">
              <Download size={13} /> PDF
            </button>
          )}
          {note.status === "draft" && has(user, "issue_note") && (
            <button
              data-testid="note-detail-issue-btn"
              disabled={issueMut.isPending}
              onClick={() => issueMut.mutate()}
              className="inline-flex items-center gap-1 text-sm px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold rounded-sm disabled:opacity-40">
              <Send size={13} /> Issue
            </button>
          )}
          {note.status !== "cancelled" && has(user, "cancel_note") && !showCancel && (
            <button
              data-testid="note-detail-cancel-btn"
              onClick={() => setShowCancel(true)}
              className="inline-flex items-center gap-1 text-sm px-3 py-1.5 border border-red-300 bg-red-50 text-red-700 hover:bg-red-100 font-semibold rounded-sm">
              <Ban size={13} /> Cancel
            </button>
          )}
        </div>

        {showCancel && (
          <div className="border-t p-4 bg-red-50 space-y-2">
            <div className="text-xs font-semibold text-red-800">Cancellation reason (min 8 chars, mandatory)</div>
            <textarea
              data-testid="note-detail-cancel-reason-input"
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
              rows={2}
              className="w-full border border-red-300 px-2 py-1.5 text-sm rounded-sm"
            />
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowCancel(false)} className="text-sm px-3 py-1.5 border border-zinc-300 rounded-sm">Back</button>
              <button
                data-testid="note-detail-cancel-confirm"
                disabled={cancelReason.trim().length < 8 || cancelMut.isPending}
                onClick={() => cancelMut.mutate()}
                className="text-sm px-3 py-1.5 bg-red-600 text-white font-semibold rounded-sm disabled:opacity-40">
                Confirm cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
