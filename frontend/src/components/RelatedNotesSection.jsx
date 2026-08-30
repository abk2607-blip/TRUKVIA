import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate } from "@/api";
import { useAuth } from "@/context/AuthContext";
import { useCdnEnabled } from "@/hooks/useCdnEnabled";
import { Plus, FileMinus, FilePlus } from "lucide-react";
import NoteCreateDialog from "@/components/NoteCreateDialog";
import NoteDetailDialog from "@/components/NoteDetailDialog";

const NOTE_PERMS = { owner: true, accountant: true, admin: true, viewer: false };

function StatusPill({ status }) {
  const cls = {
    draft: "bg-zinc-100 text-zinc-700 border-zinc-300",
    issued: "bg-emerald-50 text-emerald-700 border-emerald-300",
    cancelled: "bg-red-50 text-red-700 border-red-300",
  }[status] || "bg-zinc-100 text-zinc-700 border-zinc-300";
  return (
    <span data-testid={`chip-status-${status}`}
      className={`inline-block text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 border rounded-sm ${cls}`}>
      {status}
    </span>
  );
}

export default function RelatedNotesSection({ invoice }) {
  const cdnEnabled = useCdnEnabled();
  const { user } = useAuth();
  const role = user?.effective_role || user?.role;
  // Permissive-by-default: allow unless explicitly viewer. Backend enforces perms.
  const canCreate = role !== "viewer";

  const [createKind, setCreateKind] = useState(null); // "credit" | "debit" | null
  const [openNid, setOpenNid] = useState(null);

  const { data: notes = [] } = useQuery({
    queryKey: ["invoice-notes", invoice?.id],
    queryFn: async () => (await api.get(`/invoices/${invoice.id}/notes`)).data,
    enabled: Boolean(invoice?.id && cdnEnabled),
  });

  if (!cdnEnabled) return null;

  const credits = notes.filter((n) => n.kind === "credit");
  const debits = notes.filter((n) => n.kind === "debit");
  const creditsTotal = Number(invoice?.credits_total || 0);
  const debitsTotal = Number(invoice?.debits_total || 0);
  const effBal = Number(invoice?.effective_balance_due ?? invoice?.balance_due ?? 0);
  const hasAdjustments = creditsTotal > 0 || debitsTotal > 0;

  return (
    <div data-testid="related-notes-section" className="border border-zinc-200 rounded-md p-4 space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="text-sm font-bold text-zinc-900 uppercase tracking-wide">Related Notes</h3>
        {canCreate && (
          <div className="flex gap-2">
            <button
              data-testid="issue-credit-note-btn"
              onClick={() => setCreateKind("credit")}
              className="inline-flex items-center gap-1.5 text-xs font-semibold border border-emerald-300 bg-emerald-50 text-emerald-800 hover:bg-emerald-100 px-2.5 py-1.5 rounded-sm">
              <FileMinus size={14} /> Issue Credit Note
            </button>
            <button
              data-testid="issue-debit-note-btn"
              onClick={() => setCreateKind("debit")}
              className="inline-flex items-center gap-1.5 text-xs font-semibold border border-orange-300 bg-orange-50 text-orange-800 hover:bg-orange-100 px-2.5 py-1.5 rounded-sm">
              <FilePlus size={14} /> Issue Debit Note
            </button>
          </div>
        )}
      </div>

      {hasAdjustments && (
        <div data-testid="effective-balance-line" className="text-xs text-zinc-700 bg-amber-50 border border-amber-200 px-2 py-1.5 rounded-sm">
          Adjustments: <span className="text-emerald-700">−CN {fmtCurrency(creditsTotal)}</span>
          {" · "}
          <span className="text-orange-700">+DN {fmtCurrency(debitsTotal)}</span>
          {" · Effective outstanding "}
          <span className="font-bold">{fmtCurrency(effBal)}</span>
        </div>
      )}

      {notes.length === 0 ? (
        <div className="text-xs text-zinc-500 italic">No notes for this invoice yet.</div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {notes.map((n) => (
            <button
              key={n.id}
              data-testid={`related-notes-chip-${n.id}`}
              onClick={() => setOpenNid(n.id)}
              className={`text-left border rounded-sm px-2.5 py-1.5 text-xs hover:bg-zinc-50 ${n.kind === "credit" ? "border-emerald-200" : "border-orange-200"}`}>
              <div className="font-semibold text-zinc-900">
                {n.note_number || "(draft)"} · {n.kind === "credit" ? "CN" : "DN"}
              </div>
              <div className="text-zinc-600 flex items-center gap-1.5">
                {fmtCurrency(n.total_amount)} · {fmtDate(n.note_date)}
                <StatusPill status={n.status} />
              </div>
            </button>
          ))}
        </div>
      )}

      {createKind && (
        <NoteCreateDialog
          kind={createKind}
          invoice={invoice}
          onClose={() => setCreateKind(null)}
        />
      )}
      {openNid && (
        <NoteDetailDialog nid={openNid} onClose={() => setOpenNid(null)} />
      )}
    </div>
  );
}
