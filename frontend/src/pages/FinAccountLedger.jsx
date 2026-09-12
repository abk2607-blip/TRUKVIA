import React, { useState, useMemo } from "react";
import { useParams, useSearchParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency } from "@/api";
import { BookOpen, ArrowLeft, ChevronRight, X, ArrowUpRight, ArrowDownRight } from "lucide-react";

function _isoToday() {
  return new Date().toISOString().slice(0, 10);
}
function _isoDaysAgo(days) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function DirBadge({ direction }) {
  const isIn = direction === "in";
  return (
    <span
      data-testid={`dir-badge-${direction}`}
      className={`inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 border rounded-sm ${
        isIn ? "bg-emerald-50 text-emerald-800 border-emerald-300"
             : "bg-rose-50 text-rose-800 border-rose-300"
      }`}
    >
      {isIn ? <ArrowDownRight size={11} /> : <ArrowUpRight size={11} />}
      {isIn ? "Dr" : "Cr"}
    </span>
  );
}

function SourceDrillDialog({ open, onClose, sourceType, sourceId }) {
  const enabled = !!(open && sourceType && sourceId);
  const source = useQuery({
    queryKey: ["fin-source", sourceType, sourceId],
    queryFn: async () => (await api.get(
      `/fin/source/${encodeURIComponent(sourceType)}/${encodeURIComponent(sourceId)}`
    )).data,
    enabled,
    retry: false,
  });
  const legs = useQuery({
    queryKey: ["fin-source-legs", sourceType, sourceId],
    queryFn: async () => (await api.get(
      `/fin/source-legs/${encodeURIComponent(sourceType)}/${encodeURIComponent(sourceId)}`
    )).data,
    enabled,
    retry: false,
  });
  if (!open) return null;
  return (
    <div
      data-testid="source-drill-dialog"
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
              Source drill-through
            </div>
            <h2 className="text-lg font-bold tracking-tight">
              {sourceType} · <span className="font-mono text-zinc-600">{sourceId}</span>
            </h2>
          </div>
          <button
            data-testid="source-drill-close"
            className="p-1 hover:bg-zinc-100 rounded"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>
        <div className="p-5 space-y-5">
          <section>
            <h3 className="text-xs uppercase tracking-widest text-zinc-500 font-bold mb-2">
              Authoritative source document
            </h3>
            {source.isLoading && <p className="text-sm text-zinc-500">Loading…</p>}
            {source.isError && (
              <p data-testid="source-drill-error" className="text-sm text-rose-700">
                {source.error?.response?.data?.detail || "Source not found"}
              </p>
            )}
            {source.data && (
              <pre
                data-testid="source-drill-doc"
                className="text-[11px] leading-relaxed bg-zinc-50 border border-zinc-200 rounded p-3 overflow-x-auto max-h-64"
              >{JSON.stringify(source.data.doc, null, 2)}</pre>
            )}
          </section>
          <section>
            <h3 className="text-xs uppercase tracking-widest text-zinc-500 font-bold mb-2">
              Projected financial legs ({legs.data?.count ?? "—"})
            </h3>
            {legs.data && (
              <div className="border border-zinc-200 rounded overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-zinc-50 border-b border-zinc-200">
                    <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-500">
                      <th className="px-3 py-2">Date</th>
                      <th className="px-3 py-2">Account</th>
                      <th className="px-3 py-2">Dr/Cr</th>
                      <th className="px-3 py-2 text-right">Amount</th>
                      <th className="px-3 py-2">Counter</th>
                    </tr>
                  </thead>
                  <tbody data-testid="source-drill-legs">
                    {legs.data.legs.map((l) => (
                      <tr key={l.id} className="border-b border-zinc-100">
                        <td className="px-3 py-2 font-mono text-[11px]">{l.txn_date}</td>
                        <td className="px-3 py-2 font-mono text-[11px]">{l.account_code}</td>
                        <td className="px-3 py-2"><DirBadge direction={l.direction} /></td>
                        <td className="px-3 py-2 text-right font-mono">{fmtCurrency(l.amount)}</td>
                        <td className="px-3 py-2 font-mono text-[11px] text-zinc-500">{l.counter_account_code || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

export default function FinAccountLedger() {
  const { code } = useParams();
  const [sp, setSp] = useSearchParams();
  const [dateFrom, setDateFrom] = useState(sp.get("date_from") || _isoDaysAgo(30));
  const [dateTo, setDateTo] = useState(sp.get("date_to") || _isoToday());
  const [drill, setDrill] = useState(null);

  const applyRange = (from, to) => {
    setDateFrom(from);
    setDateTo(to);
    const next = new URLSearchParams(sp);
    next.set("date_from", from);
    next.set("date_to", to);
    setSp(next, { replace: true });
  };

  const ledger = useQuery({
    queryKey: ["fin-account-ledger", code, dateFrom, dateTo],
    queryFn: async () => (await api.get("/fin/day-book", {
      params: {
        date_from: dateFrom,
        date_to: dateTo,
        account_code: code,
        limit: 5000,
      },
    })).data,
    enabled: !!(code && dateFrom && dateTo),
  });

  // Sort ascending for running-balance display.
  const rowsAsc = useMemo(() => {
    if (!ledger.data?.rows) return [];
    return [...ledger.data.rows].sort((a, b) => {
      if (a.txn_date !== b.txn_date) return a.txn_date.localeCompare(b.txn_date);
      return (a.created_at || "").localeCompare(b.created_at || "");
    });
  }, [ledger.data]);

  const rowsWithBalance = useMemo(() => {
    let bal = 0;
    return rowsAsc.map((r) => {
      const amt = Number(r.amount || 0);
      if (r.direction === "in") bal += amt;
      else bal -= amt;
      return { ...r, _running: bal };
    });
  }, [rowsAsc]);

  const totals = ledger.data?.totals?.[code] || { in: 0, out: 0, net: 0 };

  return (
    <div className="space-y-6" data-testid="fin-account-ledger-page">
      <header className="border-b border-zinc-200 pb-4">
        <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold flex items-center gap-2">
          <BookOpen size={12} /> Iter150C · Financial Traceability
        </div>
        <div className="mt-1 flex items-center gap-3">
          <Link
            to="/fin/day-book"
            className="text-xs text-zinc-500 hover:text-zinc-950 inline-flex items-center gap-1"
            data-testid="fin-back-to-day-book"
          >
            <ArrowLeft size={12} /> Day Book
          </Link>
        </div>
        <h1 className="mt-1 text-4xl font-black tracking-tighter">
          Account Ledger <span className="text-zinc-400">·</span>{" "}
          <span className="font-mono" data-testid="fin-account-ledger-code">{code}</span>
        </h1>
      </header>

      <section className="grid gap-3 md:grid-cols-4 items-end">
        <div>
          <label className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">From</label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => applyRange(e.target.value, dateTo)}
            className="mt-1 w-full text-sm border border-zinc-300 rounded px-2 py-1.5"
            data-testid="fin-account-ledger-date-from"
          />
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">To</label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => applyRange(dateFrom, e.target.value)}
            className="mt-1 w-full text-sm border border-zinc-300 rounded px-2 py-1.5"
            data-testid="fin-account-ledger-date-to"
          />
        </div>
        <div
          className="bg-zinc-50 border border-zinc-200 rounded px-3 py-2 text-[11px]"
          data-testid="fin-account-ledger-summary"
        >
          <div className="uppercase tracking-widest text-zinc-500 font-bold text-[10px]">Debits · Credits · Net</div>
          <div className="mt-1 font-mono text-zinc-900">
            {fmtCurrency(totals.in)} · {fmtCurrency(totals.out)} ·{" "}
            <span className={totals.net >= 0 ? "text-emerald-800 font-semibold" : "text-rose-800 font-semibold"}>
              {fmtCurrency(totals.net)}
            </span>
          </div>
        </div>
        <div className="text-[11px] text-zinc-500">
          {rowsWithBalance.length} legs
        </div>
      </section>

      <section className="border border-zinc-200 rounded overflow-x-auto">
        <table className="w-full text-xs" data-testid="fin-account-ledger-table">
          <thead className="bg-zinc-50 border-b border-zinc-200">
            <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-500">
              <th className="px-3 py-2">Date</th>
              <th className="px-3 py-2">Dr/Cr</th>
              <th className="px-3 py-2 text-right">Debit</th>
              <th className="px-3 py-2 text-right">Credit</th>
              <th className="px-3 py-2 text-right">Running</th>
              <th className="px-3 py-2">Counter</th>
              <th className="px-3 py-2">Source</th>
              <th className="px-3 py-2">Narration</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {ledger.isLoading && (
              <tr><td colSpan={9} className="px-3 py-8 text-center text-zinc-500 text-sm">Loading…</td></tr>
            )}
            {ledger.isError && (
              <tr><td colSpan={9} className="px-3 py-8 text-center text-rose-700 text-sm">
                {ledger.error?.response?.data?.detail || "Failed to load ledger"}
              </td></tr>
            )}
            {ledger.data && rowsWithBalance.length === 0 && (
              <tr><td colSpan={9} className="px-3 py-8 text-center text-zinc-500 text-sm" data-testid="fin-account-ledger-empty">
                No legs on this account in the selected window.
              </td></tr>
            )}
            {rowsWithBalance.map((r) => (
              <tr key={r.id} className="border-b border-zinc-100 hover:bg-zinc-50">
                <td className="px-3 py-2 font-mono text-[11px]">{r.txn_date}</td>
                <td className="px-3 py-2"><DirBadge direction={r.direction} /></td>
                <td className="px-3 py-2 text-right font-mono">
                  {r.direction === "in" ? fmtCurrency(r.amount) : ""}
                </td>
                <td className="px-3 py-2 text-right font-mono">
                  {r.direction === "out" ? fmtCurrency(r.amount) : ""}
                </td>
                <td className={`px-3 py-2 text-right font-mono font-semibold ${
                  r._running >= 0 ? "text-emerald-800" : "text-rose-800"
                }`}>{fmtCurrency(r._running)}</td>
                <td className="px-3 py-2 font-mono text-[11px] text-zinc-500">{r.counter_account_code || "—"}</td>
                <td className="px-3 py-2 text-[11px] text-zinc-600">
                  <span className="font-semibold">{r.source_type}</span>
                  <span className="text-zinc-400"> · </span>
                  <span className="font-mono">{(r.source_id || "").slice(0, 24)}</span>
                </td>
                <td className="px-3 py-2 text-zinc-700 max-w-md truncate">{r.narration || "—"}</td>
                <td className="px-3 py-2">
                  <button
                    className="text-[11px] font-semibold text-zinc-700 hover:text-zinc-950 inline-flex items-center gap-0.5"
                    data-testid={`fin-account-ledger-drill-${r.id}`}
                    onClick={() => setDrill({ source_type: r.source_type, source_id: r.source_id })}
                  >
                    Drill <ChevronRight size={12} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <SourceDrillDialog
        open={!!drill}
        onClose={() => setDrill(null)}
        sourceType={drill?.source_type}
        sourceId={drill?.source_id}
      />
    </div>
  );
}
