import React, { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate } from "@/api";
import { useAuth } from "@/context/AuthContext";
import { useCdnEnabled } from "@/hooks/useCdnEnabled";
import { FileMinus, Search } from "lucide-react";
import NoteDetailDialog from "@/components/NoteDetailDialog";

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

function KindBadge({ kind }) {
  const isDebit = kind === "debit";
  return (
    <span data-testid={`kind-badge-${kind}`}
      className={`inline-block text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 border rounded-sm ${isDebit ? "bg-orange-50 text-orange-800 border-orange-300" : "bg-emerald-50 text-emerald-800 border-emerald-300"}`}>
      {isDebit ? "DN" : "CN"}
    </span>
  );
}

export default function Notes() {
  const cdnEnabled = useCdnEnabled();
  const { user } = useAuth();
  // Permissive-by-default: hide only for explicit viewer role. Backend remains
  // the enforcement layer (mutations return 403 for insufficient perms).
  const role = user?.effective_role || user?.role;
  const canView = role !== "viewer";

  const [kindFilter, setKindFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [openNid, setOpenNid] = useState(null);

  const params = statusFilter !== "all" ? { status: statusFilter, limit: 500 } : { limit: 500 };
  const { data: creditNotes = [], isLoading: lc } = useQuery({
    queryKey: ["credit-notes", statusFilter],
    queryFn: async () => (await api.get("/credit-notes", { params })).data,
    enabled: Boolean(cdnEnabled && canView && (kindFilter === "all" || kindFilter === "credit")),
  });
  const { data: debitNotes = [], isLoading: ld } = useQuery({
    queryKey: ["debit-notes", statusFilter],
    queryFn: async () => (await api.get("/debit-notes", { params })).data,
    enabled: Boolean(cdnEnabled && canView && (kindFilter === "all" || kindFilter === "debit")),
  });

  const rows = useMemo(() => {
    let list = [];
    if (kindFilter === "all" || kindFilter === "credit") list = list.concat(creditNotes);
    if (kindFilter === "all" || kindFilter === "debit") list = list.concat(debitNotes);
    const s = search.trim().toLowerCase();
    if (s) {
      list = list.filter((n) =>
        (n.note_number || "").toLowerCase().includes(s) ||
        (n.reason_text || "").toLowerCase().includes(s) ||
        (n.invoice_number_snapshot || "").toLowerCase().includes(s)
      );
    }
    list.sort((a, b) => (b.note_date || "").localeCompare(a.note_date || ""));
    return list;
  }, [creditNotes, debitNotes, kindFilter, search]);

  if (!cdnEnabled) {
    return (
      <div data-testid="notes-feature-disabled" className="max-w-2xl mx-auto p-6">
        <div className="border border-zinc-200 rounded-md p-6 text-center bg-zinc-50">
          <FileMinus className="mx-auto text-zinc-400" size={40} />
          <div className="mt-3 font-bold text-zinc-800">Credit / Debit Notes feature is not enabled</div>
          <div className="mt-1 text-xs text-zinc-500">Contact your administrator to enable this feature.</div>
        </div>
      </div>
    );
  }

  if (!canView) {
    return (
      <div className="max-w-2xl mx-auto p-6">
        <div className="border border-zinc-200 rounded-md p-6 text-center">
          <div className="font-bold text-zinc-800">Access denied</div>
          <div className="mt-1 text-xs text-zinc-500">You do not have permission to view notes.</div>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="notes-page-root" className="p-4 sm:p-6 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-xl font-bold text-zinc-900">Credit / Debit Notes</h1>
        <div className="text-xs text-zinc-500">{rows.length} note{rows.length !== 1 ? "s" : ""}</div>
      </div>

      <div className="border border-zinc-200 rounded-md p-3 grid grid-cols-1 sm:grid-cols-4 gap-2">
        <label className="text-xs font-semibold text-zinc-700">
          Kind
          <select
            data-testid="notes-filter-kind"
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value)}
            className="mt-1 w-full border border-zinc-300 px-2 py-1.5 text-sm rounded-sm bg-white">
            <option value="all">All</option>
            <option value="credit">Credit Notes</option>
            <option value="debit">Debit Notes</option>
          </select>
        </label>
        <label className="text-xs font-semibold text-zinc-700">
          Status
          <select
            data-testid="notes-filter-status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="mt-1 w-full border border-zinc-300 px-2 py-1.5 text-sm rounded-sm bg-white">
            <option value="all">All</option>
            <option value="draft">Draft</option>
            <option value="issued">Issued</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </label>
        <label className="text-xs font-semibold text-zinc-700 sm:col-span-2">
          Search
          <div className="mt-1 relative">
            <Search size={14} className="absolute top-2.5 left-2 text-zinc-400" />
            <input
              data-testid="notes-search-input"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Note #, reason, or invoice #"
              className="w-full border border-zinc-300 pl-7 pr-2 py-1.5 text-sm rounded-sm"
            />
          </div>
        </label>
      </div>

      {(lc || ld) && <div className="text-xs text-zinc-500">Loading…</div>}

      {/* Desktop table */}
      <div className="hidden sm:block border border-zinc-200 rounded-md overflow-hidden" data-testid="notes-table">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 text-xs uppercase text-zinc-600">
            <tr>
              <th className="p-2 text-left">Note #</th>
              <th className="p-2 text-left">Kind</th>
              <th className="p-2 text-left">Date</th>
              <th className="p-2 text-left">Invoice #</th>
              <th className="p-2 text-right">Amount</th>
              <th className="p-2 text-left">Status</th>
              <th className="p-2 text-left">Reason</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={7} className="p-6 text-center text-zinc-500 italic">No notes match your filters.</td></tr>
            ) : rows.map((n) => (
              <tr
                key={n.id}
                data-testid={`notes-row-${n.id}`}
                onClick={() => setOpenNid(n.id)}
                className="border-t border-zinc-100 hover:bg-zinc-50 cursor-pointer">
                <td className="p-2 font-semibold">{n.note_number || <span className="text-zinc-400 italic">draft</span>}</td>
                <td className="p-2"><KindBadge kind={n.kind} /></td>
                <td className="p-2">{fmtDate(n.note_date)}</td>
                <td className="p-2">{n.invoice_number_snapshot}</td>
                <td className="p-2 text-right font-semibold">{fmtCurrency(n.total_amount)}</td>
                <td className="p-2"><StatusPill status={n.status} /></td>
                <td className="p-2 text-xs text-zinc-600 max-w-xs truncate">{n.reason_text}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile card list */}
      <div className="sm:hidden space-y-2" data-testid="notes-cards">
        {rows.length === 0 ? (
          <div className="text-center text-zinc-500 italic text-sm py-6">No notes match your filters.</div>
        ) : rows.map((n) => (
          <div
            key={n.id}
            data-testid={`notes-card-${n.id}`}
            onClick={() => setOpenNid(n.id)}
            className="border border-zinc-200 rounded-md p-3 hover:bg-zinc-50 cursor-pointer space-y-1">
            <div className="flex items-center justify-between">
              <div className="font-semibold text-sm">{n.note_number || "(draft)"}</div>
              <div className="flex items-center gap-1">
                <KindBadge kind={n.kind} />
                <StatusPill status={n.status} />
              </div>
            </div>
            <div className="text-xs text-zinc-600">Invoice: <span className="font-semibold">{n.invoice_number_snapshot}</span></div>
            <div className="flex justify-between text-xs">
              <span>{fmtDate(n.note_date)}</span>
              <span className="font-semibold">{fmtCurrency(n.total_amount)}</span>
            </div>
            <div className="text-xs text-zinc-600 truncate">{n.reason_text}</div>
          </div>
        ))}
      </div>

      {openNid && <NoteDetailDialog nid={openNid} onClose={() => setOpenNid(null)} />}
    </div>
  );
}
