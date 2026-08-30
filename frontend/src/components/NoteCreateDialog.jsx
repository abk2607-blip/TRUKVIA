import React, { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, fmtCurrency } from "@/api";
import { toast } from "sonner";
import { X, Plus, Trash2 } from "lucide-react";
import { reasonsFor } from "@/constants/noteReasonCodes";

export default function NoteCreateDialog({ kind, invoice, onClose }) {
  const qc = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);
  const [noteDate, setNoteDate] = useState(today);
  const [reasonCode, setReasonCode] = useState(reasonsFor(kind)[0].value);
  const [reasonText, setReasonText] = useState("");
  const [deadlineOverrideReason, setDeadlineOverrideReason] = useState("");
  const [lines, setLines] = useState([{ description: "", quantity: 1, rate: "" }]);

  const updateLine = (i, patch) => {
    const next = [...lines];
    next[i] = { ...next[i], ...patch };
    setLines(next);
  };
  const addLine = () => setLines([...lines, { description: "", quantity: 1, rate: "" }]);
  const removeLine = (i) => setLines(lines.filter((_, ix) => ix !== i));

  // Statutory deadline warning (30-Nov of FY following invoice's FY)
  const invDate = invoice?.invoice_date;
  const deadline = React.useMemo(() => {
    if (!invDate) return null;
    const d = new Date(invDate);
    const year = d.getUTCMonth() >= 3 ? d.getUTCFullYear() + 1 : d.getUTCFullYear();
    return `${year}-11-30`;
  }, [invDate]);
  const pastDeadline = deadline && noteDate > deadline;

  const subtotal = lines.reduce((s, l) => s + (Number(l.quantity) || 0) * (Number(l.rate) || 0), 0);

  const submit = useMutation({
    mutationFn: async () => {
      const path = kind === "credit" ? "/credit-notes" : "/debit-notes";
      const payload = {
        invoice_id: invoice.id,
        note_date: noteDate,
        reason_code: reasonCode,
        reason_text: reasonText.trim(),
        lines: lines.filter((l) => l.description && l.rate).map((l) => ({
          description: l.description,
          quantity: Number(l.quantity) || 1,
          rate: Number(l.rate),
        })),
      };
      if (pastDeadline) payload.deadline_override_reason = deadlineOverrideReason.trim();
      return (await api.post(path, payload)).data;
    },
    onSuccess: () => {
      toast.success(`${kind === "credit" ? "Credit" : "Debit"} Note created`);
      qc.invalidateQueries();
      onClose();
    },
    onError: (e) => toast.error(e?.response?.data?.detail || e.message || "Failed"),
  });

  const canSubmit =
    reasonText.trim().length >= 8 &&
    lines.some((l) => l.description && Number(l.rate) > 0) &&
    (!pastDeadline || deadlineOverrideReason.trim().length >= 8);

  const kindLabel = kind === "credit" ? "Credit Note" : "Debit Note";
  const kindColor = kind === "credit" ? "bg-emerald-50 border-emerald-300 text-emerald-800" : "bg-orange-50 border-orange-300 text-orange-800";

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start sm:items-center justify-center p-2 overflow-y-auto"
         data-testid="note-create-dialog"
         onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="bg-white rounded-md w-full max-w-2xl my-4 shadow-xl">
        <div className={`flex items-center justify-between px-4 py-3 border-b ${kindColor}`}>
          <div className="font-bold" data-testid="note-create-kind-badge">Issue {kindLabel}</div>
          <button onClick={onClose} className="p-1 hover:bg-white/50 rounded-sm" data-testid="note-create-close">
            <X size={16} />
          </button>
        </div>

        <div className="p-4 space-y-3">
          <div className="text-xs text-zinc-600 bg-zinc-50 border border-zinc-200 rounded-sm p-2">
            Linked invoice: <span className="font-semibold">{invoice?.invoice_number}</span>
            {" · "}Total: <span className="font-semibold">{fmtCurrency(invoice?.total_amount)}</span>
            {" · "}Effective balance: <span className="font-semibold">{fmtCurrency(invoice?.effective_balance_due ?? invoice?.balance_due)}</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="text-xs font-semibold text-zinc-700">
              Note date
              <input
                type="date"
                data-testid="note-create-note-date"
                value={noteDate}
                onChange={(e) => setNoteDate(e.target.value)}
                className="mt-1 w-full border border-zinc-300 px-2 py-1.5 text-sm rounded-sm"
              />
            </label>
            <label className="text-xs font-semibold text-zinc-700">
              Reason code
              <select
                data-testid="note-create-reason-code"
                value={reasonCode}
                onChange={(e) => setReasonCode(e.target.value)}
                className="mt-1 w-full border border-zinc-300 px-2 py-1.5 text-sm rounded-sm bg-white">
                {reasonsFor(kind).map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </label>
          </div>

          <label className="text-xs font-semibold text-zinc-700 block">
            Reason detail (min 8 characters, mandatory)
            <textarea
              data-testid="note-create-reason-text"
              value={reasonText}
              onChange={(e) => setReasonText(e.target.value)}
              rows={2}
              className="mt-1 w-full border border-zinc-300 px-2 py-1.5 text-sm rounded-sm"
              placeholder="e.g. Rate correction as per revised PO"
            />
            <span className={`text-[10px] ${reasonText.trim().length >= 8 ? "text-emerald-600" : "text-zinc-500"}`}>
              {reasonText.trim().length}/8+
            </span>
          </label>

          {pastDeadline && (
            <div className="bg-yellow-50 border border-yellow-300 rounded-sm p-2 text-xs space-y-2">
              <div className="font-bold text-yellow-900">⚠ Past statutory deadline ({deadline})</div>
              <div className="text-yellow-800">Owner override is required. Provide reason (min 8 chars):</div>
              <textarea
                data-testid="note-create-deadline-override-reason"
                value={deadlineOverrideReason}
                onChange={(e) => setDeadlineOverrideReason(e.target.value)}
                rows={2}
                className="w-full border border-yellow-400 px-2 py-1.5 text-sm rounded-sm"
              />
            </div>
          )}

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-xs font-semibold text-zinc-700 uppercase">Line items</div>
              <button
                data-testid="note-create-line-add"
                type="button"
                onClick={addLine}
                className="inline-flex items-center gap-1 text-xs border border-zinc-300 px-2 py-1 rounded-sm hover:bg-zinc-50">
                <Plus size={12} /> Add line
              </button>
            </div>
            <div className="space-y-1.5">
              {lines.map((l, i) => (
                <div key={i} className="grid grid-cols-12 gap-1.5 items-center">
                  <input
                    data-testid={`note-create-line-${i}-desc`}
                    placeholder="Description"
                    value={l.description}
                    onChange={(e) => updateLine(i, { description: e.target.value })}
                    className="col-span-6 border border-zinc-300 px-2 py-1.5 text-xs rounded-sm"
                  />
                  <input
                    data-testid={`note-create-line-${i}-qty`}
                    type="number"
                    placeholder="Qty"
                    value={l.quantity}
                    onChange={(e) => updateLine(i, { quantity: e.target.value })}
                    className="col-span-2 border border-zinc-300 px-2 py-1.5 text-xs rounded-sm"
                  />
                  <input
                    data-testid={`note-create-line-${i}-rate`}
                    type="number"
                    placeholder="Rate"
                    value={l.rate}
                    onChange={(e) => updateLine(i, { rate: e.target.value })}
                    className="col-span-3 border border-zinc-300 px-2 py-1.5 text-xs rounded-sm"
                  />
                  <button
                    type="button"
                    onClick={() => removeLine(i)}
                    disabled={lines.length === 1}
                    className="col-span-1 p-1.5 text-zinc-500 hover:text-red-600 disabled:opacity-30"
                    data-testid={`note-create-line-${i}-remove`}>
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
            <div className="text-right text-xs font-semibold text-zinc-700">
              Subtotal: {fmtCurrency(subtotal)}
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 px-4 py-3 border-t bg-zinc-50">
          <button
            onClick={onClose}
            className="text-sm px-3 py-1.5 border border-zinc-300 rounded-sm hover:bg-white">
            Cancel
          </button>
          <button
            data-testid="note-create-submit"
            disabled={!canSubmit || submit.isPending}
            onClick={() => submit.mutate()}
            className={`text-sm px-3 py-1.5 font-semibold rounded-sm text-white ${kind === "credit" ? "bg-emerald-600 hover:bg-emerald-700" : "bg-orange-600 hover:bg-orange-700"} disabled:opacity-40`}>
            {submit.isPending ? "Submitting…" : `Issue ${kindLabel}`}
          </button>
        </div>
      </div>
    </div>
  );
}
