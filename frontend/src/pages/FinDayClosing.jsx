import React, { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, fmtCurrency } from "@/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Lock, Unlock, ChevronRight, ChevronDown, Info, X, AlertTriangle } from "lucide-react";

function _isoToday() {
  return new Date().toISOString().slice(0, 10);
}

function StatusPill({ status }) {
  const isClosed = status === "closed";
  return (
    <span
      data-testid={`fin-day-closing-status-${status}`}
      className={`inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 border rounded-sm ${
        isClosed ? "bg-emerald-50 text-emerald-800 border-emerald-300"
                 : "bg-amber-50 text-amber-900 border-amber-300"
      }`}
    >
      {isClosed ? <Lock size={11} /> : <Unlock size={11} />}
      {status}
    </span>
  );
}

function ClosureDrawer({ closeDate, onClose, canReopen, onReopen }) {
  const details = useQuery({
    queryKey: ["fin-day-closure", closeDate],
    queryFn: async () => (await api.get(`/fin/day-closures/${closeDate}`)).data,
    enabled: !!closeDate,
    retry: false,
  });
  const late = useQuery({
    queryKey: ["fin-day-closure-late", closeDate],
    queryFn: async () => (await api.get(`/fin/day-closures/${closeDate}/late-entries`)).data,
    enabled: !!closeDate,
    retry: false,
  });
  if (!closeDate) return null;
  const snap = details.data?.snapshot || {};
  const snapRows = Object.entries(snap)
    .map(([code, t]) => ({ code, ...t }))
    .sort((a, b) => Math.abs(b.net) - Math.abs(a.net));

  return (
    <div
      data-testid="fin-day-closing-drawer"
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-md border border-zinc-200 shadow-xl max-w-4xl w-full mt-8"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-200 px-5 py-3">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">
              Closure detail
            </div>
            <h2 className="text-lg font-bold tracking-tight">
              {closeDate} ·{" "}
              {details.data && <StatusPill status={details.data.status} />}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            {canReopen && details.data?.status === "closed" && (
              <button
                data-testid="fin-day-closing-reopen-btn"
                onClick={() => onReopen(closeDate)}
                className="text-xs font-semibold px-3 py-1.5 border border-amber-300 bg-amber-50 text-amber-900 rounded hover:bg-amber-100"
              >
                <Unlock size={11} className="inline mr-1" /> Reopen
              </button>
            )}
            <button
              data-testid="fin-day-closing-drawer-close"
              onClick={onClose}
              className="p-1 hover:bg-zinc-100 rounded"
            >
              <X size={18} />
            </button>
          </div>
        </div>
        <div className="p-5 space-y-5">
          {details.data && (
            <div className="text-[11px] text-zinc-600 space-y-0.5" data-testid="fin-day-closing-metadata">
              <div>Closed at: <span className="font-mono">{details.data.closed_at}</span></div>
              <div>Closed by: <span className="font-mono">{details.data.closed_by}</span></div>
              {details.data.close_notes && <div>Notes: {details.data.close_notes}</div>}
              {details.data.reopened_at && (
                <div className="text-amber-900">
                  Reopened at: <span className="font-mono">{details.data.reopened_at}</span> · by{" "}
                  <span className="font-mono">{details.data.reopened_by}</span> · reason: {details.data.reopen_reason}
                </div>
              )}
              <div>Legs at close: <span className="font-mono">{details.data.snapshot_source_count}</span></div>
            </div>
          )}

          <section>
            <h3 className="text-xs uppercase tracking-widest text-zinc-500 font-bold mb-2">
              Immutable close snapshot ({snapRows.length} accounts)
            </h3>
            <div className="border border-zinc-200 rounded overflow-x-auto">
              <table className="w-full text-xs" data-testid="fin-day-closing-snapshot-table">
                <thead className="bg-zinc-50 border-b border-zinc-200">
                  <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-500">
                    <th className="px-3 py-2">Account</th>
                    <th className="px-3 py-2 text-right">Debit (in)</th>
                    <th className="px-3 py-2 text-right">Credit (out)</th>
                    <th className="px-3 py-2 text-right">Net</th>
                  </tr>
                </thead>
                <tbody>
                  {snapRows.map((r) => (
                    <tr key={r.code} className="border-b border-zinc-100">
                      <td className="px-3 py-2 font-mono text-[11px] font-semibold">{r.code}</td>
                      <td className="px-3 py-2 text-right font-mono">{fmtCurrency(r.in)}</td>
                      <td className="px-3 py-2 text-right font-mono">{fmtCurrency(r.out)}</td>
                      <td className={`px-3 py-2 text-right font-mono font-semibold ${r.net >= 0 ? "text-emerald-800" : "text-rose-800"}`}>
                        {fmtCurrency(r.net)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h3 className="text-xs uppercase tracking-widest text-zinc-500 font-bold mb-2 flex items-center gap-2">
              Late entries since close ({late.data?.count ?? "—"})
              {late.data?.count > 0 && (
                <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 bg-amber-100 text-amber-900 border border-amber-300 rounded-sm">
                  <AlertTriangle size={10} /> drift
                </span>
              )}
            </h3>
            {late.data && (
              <div className="border border-zinc-200 rounded overflow-x-auto">
                <table className="w-full text-xs" data-testid="fin-day-closing-late-entries">
                  <thead className="bg-zinc-50 border-b border-zinc-200">
                    <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-500">
                      <th className="px-3 py-2">Business date</th>
                      <th className="px-3 py-2 text-right">Days late</th>
                      <th className="px-3 py-2">Account</th>
                      <th className="px-3 py-2 text-right">Amount</th>
                      <th className="px-3 py-2">Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(late.data.rows || []).slice(0, 200).map((l) => (
                      <tr key={l.id} className="border-b border-zinc-100">
                        <td className="px-3 py-2 font-mono text-[11px]">{l.txn_date}</td>
                        <td className="px-3 py-2 text-right font-mono">{l.days_late}</td>
                        <td className="px-3 py-2 font-mono text-[11px]">{l.account_code}</td>
                        <td className="px-3 py-2 text-right font-mono">{fmtCurrency(l.amount)}</td>
                        <td className="px-3 py-2 text-[11px] text-zinc-600">
                          <span className="font-semibold">{l.source_type}</span>
                          <span className="text-zinc-400"> · </span>
                          <span className="font-mono">{(l.source_id || "").slice(0, 20)}</span>
                        </td>
                      </tr>
                    ))}
                    {late.data.count === 0 && (
                      <tr>
                        <td colSpan={5} className="px-3 py-6 text-center text-zinc-500 text-sm" data-testid="fin-day-closing-late-empty">
                          No late entries. Live totals match the snapshot.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {details.data?.history?.length > 1 && (
            <section>
              <h3 className="text-xs uppercase tracking-widest text-zinc-500 font-bold mb-2">
                Reopen / re-close history
              </h3>
              <ol className="text-[11px] space-y-1" data-testid="fin-day-closing-history">
                {details.data.history.map((h, i) => (
                  <li key={i} className="flex items-center gap-2">
                    <span className="font-semibold uppercase tracking-wide">{h.event}</span>
                    <span className="font-mono text-zinc-500">{h.at}</span>
                    <span className="text-zinc-500">by {h.by}</span>
                    {h.reason && <span className="text-amber-900">· {h.reason}</span>}
                  </li>
                ))}
              </ol>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

export default function FinDayClosing() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const isOwner = (user?.effective_role || user?.role || "").toLowerCase() === "owner";
  const [closeDate, setCloseDate] = useState(_isoToday());
  const [notes, setNotes] = useState("");
  const [drawerDate, setDrawerDate] = useState(null);

  const closures = useQuery({
    queryKey: ["fin-day-closures"],
    queryFn: async () => (await api.get("/fin/day-closures", { params: { limit: 500 } })).data,
  });

  const closeM = useMutation({
    mutationFn: async () => (await api.post("/fin/day-closures", {
      close_date: closeDate, close_notes: notes,
    })).data,
    onSuccess: (d) => {
      toast.success(`Day ${d.close_date} closed · snapshot: ${d.snapshot_source_count} legs`);
      setNotes("");
      qc.invalidateQueries({ queryKey: ["fin-day-closures"] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Close failed"),
  });

  const reopenM = useMutation({
    mutationFn: async ({ date, reason }) => (await api.post(
      `/fin/day-closures/${date}/reopen`, { reopen_reason: reason },
    )).data,
    onSuccess: (d) => {
      toast.success(`Day ${d.close_date} reopened`);
      qc.invalidateQueries({ queryKey: ["fin-day-closures"] });
      qc.invalidateQueries({ queryKey: ["fin-day-closure", d.close_date] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Reopen failed"),
  });

  const requestReopen = (date) => {
    const reason = window.prompt(`Reopen ${date}?\nProvide a reason:`, "");
    if (reason && reason.trim()) {
      reopenM.mutate({ date, reason: reason.trim() });
    }
  };

  const rows = closures.data?.rows || [];

  return (
    <div className="space-y-6" data-testid="fin-day-closing-page">
      <header className="border-b border-zinc-200 pb-4">
        <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold flex items-center gap-2">
          <Lock size={12} /> Iter150D · Financial Control
        </div>
        <h1 className="mt-1 text-4xl font-black tracking-tighter">
          Day Closing <span className="text-zinc-400">·</span>{" "}
          <span className="text-zinc-500 text-2xl font-bold">Financial checkpoint</span>
        </h1>
        <div className="mt-3 flex items-start gap-2 bg-amber-50 border border-amber-300 rounded p-3 text-[12px] text-amber-900 max-w-3xl" data-testid="fin-day-closing-helper">
          <Info size={14} className="mt-0.5 shrink-0" />
          <div>
            <strong>Not a data-entry lock.</strong> Any past business date remains
            enterable across every canonical source type — even after closing.
            The snapshot captured at close time is immutable; late entries appear
            under their true business date and are surfaced in <em>Late entries
            since close</em>.
          </div>
        </div>
      </header>

      {isOwner && (
        <section className="border border-zinc-200 rounded p-4 bg-zinc-50" data-testid="fin-day-closing-close-panel">
          <h2 className="text-xs uppercase tracking-widest text-zinc-500 font-bold mb-3">
            Close a day (owner only)
          </h2>
          <div className="grid gap-3 md:grid-cols-3 items-end">
            <div>
              <label className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">Close date</label>
              <input
                type="date"
                value={closeDate}
                max={_isoToday()}
                onChange={(e) => setCloseDate(e.target.value)}
                className="mt-1 w-full text-sm border border-zinc-300 rounded px-2 py-1.5 bg-white"
                data-testid="fin-day-closing-close-date"
              />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">Notes (optional)</label>
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Business context for this close"
                className="mt-1 w-full text-sm border border-zinc-300 rounded px-2 py-1.5 bg-white"
                data-testid="fin-day-closing-close-notes"
              />
            </div>
            <div>
              <button
                onClick={() => closeM.mutate()}
                disabled={!closeDate || closeM.isPending}
                className="w-full text-sm font-semibold bg-zinc-950 text-white rounded px-3 py-1.5 hover:bg-zinc-800 disabled:bg-zinc-400"
                data-testid="fin-day-closing-close-btn"
              >
                {closeM.isPending ? "Closing…" : <><Lock size={12} className="inline mr-1" /> Close this day</>}
              </button>
            </div>
          </div>
        </section>
      )}

      <section>
        <h2 className="text-xs uppercase tracking-widest text-zinc-500 font-bold mb-2">
          Closures ({rows.length})
        </h2>
        <div className="border border-zinc-200 rounded overflow-x-auto">
          <table className="w-full text-xs" data-testid="fin-day-closing-list">
            <thead className="bg-zinc-50 border-b border-zinc-200">
              <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-500">
                <th className="px-3 py-2">Date</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Closed at</th>
                <th className="px-3 py-2">Closed by</th>
                <th className="px-3 py-2 text-right">Legs @close</th>
                <th className="px-3 py-2">Notes</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {closures.isLoading && (
                <tr><td colSpan={7} className="px-3 py-8 text-center text-zinc-500 text-sm">Loading…</td></tr>
              )}
              {closures.data && rows.length === 0 && (
                <tr><td colSpan={7} className="px-3 py-8 text-center text-zinc-500 text-sm" data-testid="fin-day-closing-empty">
                  No closures yet. Close today or a past business day to start.
                </td></tr>
              )}
              {rows.map((r) => (
                <tr key={r.close_date} data-testid={`fin-day-closing-row-${r.close_date}`}
                    className="border-b border-zinc-100 hover:bg-zinc-50 cursor-pointer"
                    onClick={() => setDrawerDate(r.close_date)}>
                  <td className="px-3 py-2 font-mono text-[11px] font-semibold">{r.close_date}</td>
                  <td className="px-3 py-2"><StatusPill status={r.status} /></td>
                  <td className="px-3 py-2 font-mono text-[11px]">{r.closed_at}</td>
                  <td className="px-3 py-2 font-mono text-[11px]">{r.closed_by}</td>
                  <td className="px-3 py-2 text-right font-mono">{r.snapshot_source_count}</td>
                  <td className="px-3 py-2 text-zinc-700 max-w-md truncate">{r.close_notes || "—"}</td>
                  <td className="px-3 py-2">
                    <span className="text-[11px] font-semibold text-zinc-700 hover:text-zinc-950 inline-flex items-center gap-0.5">
                      View <ChevronRight size={12} />
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <ClosureDrawer
        closeDate={drawerDate}
        onClose={() => setDrawerDate(null)}
        canReopen={isOwner}
        onReopen={requestReopen}
      />
    </div>
  );
}
