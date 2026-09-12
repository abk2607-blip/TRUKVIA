import React, { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency } from "@/api";
import { BookOpen, ChevronRight, X, Filter, ArrowUpRight, ArrowDownRight } from "lucide-react";

const SOURCE_TYPES = [
  { v: "", l: "All sources" },
  { v: "invoice", l: "Invoice" },
  { v: "credit_debit_note", l: "Credit/Debit Note" },
  { v: "supplier_payment", l: "Supplier Payment" },
  { v: "vendor_payment", l: "Vendor Payment" },
  { v: "mechanic_payment", l: "Mechanic Payment" },
  { v: "expense", l: "Expense" },
  { v: "vendor_bill", l: "Vendor Bill" },
  { v: "mechanic_work_order", l: "Mechanic Work Order" },
  { v: "trip_customer_receipt", l: "Trip Customer Receipt" },
  { v: "wallet_recharge", l: "Wallet Recharge" },
  { v: "wallet_transfer", l: "Wallet Transfer" },
  { v: "wallet_adjustment", l: "Wallet Adjustment" },
];

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
            {legs.isLoading && <p className="text-sm text-zinc-500">Loading…</p>}
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
                      <th className="px-3 py-2">Narration</th>
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
                        <td className="px-3 py-2 text-zinc-700">{l.narration || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot className="bg-zinc-50 border-t border-zinc-200">
                    <tr className="text-[11px]">
                      <td colSpan={3} className="px-3 py-2 font-bold text-right">Totals</td>
                      <td className="px-3 py-2 text-right font-mono">
                        Dr {fmtCurrency(legs.data.totals.in)} · Cr {fmtCurrency(legs.data.totals.out)}
                      </td>
                      <td colSpan={2} className="px-3 py-2 font-mono text-right">
                        Net {fmtCurrency(legs.data.totals.net)}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

export default function FinDayBook() {
  const [dateFrom, setDateFrom] = useState(_isoDaysAgo(30));
  const [dateTo, setDateTo] = useState(_isoToday());
  const [sourceType, setSourceType] = useState("");
  const [accountCode, setAccountCode] = useState("");
  const [drill, setDrill] = useState(null); // { source_type, source_id }

  const accounts = useQuery({
    queryKey: ["fin-accounts"],
    queryFn: async () => (await api.get("/fin/accounts")).data,
  });

  const dayBook = useQuery({
    queryKey: ["fin-day-book", dateFrom, dateTo, sourceType, accountCode],
    queryFn: async () => (await api.get("/fin/day-book", {
      params: {
        date_from: dateFrom,
        date_to: dateTo,
        ...(sourceType ? { source_type: sourceType } : {}),
        ...(accountCode ? { account_code: accountCode } : {}),
        limit: 5000,
      },
    })).data,
    enabled: !!(dateFrom && dateTo),
  });

  const totalsSorted = useMemo(() => {
    if (!dayBook.data?.totals) return [];
    return Object.entries(dayBook.data.totals)
      .map(([code, t]) => ({ code, ...t }))
      .sort((a, b) => Math.abs(b.net) - Math.abs(a.net));
  }, [dayBook.data]);

  return (
    <div className="space-y-6" data-testid="fin-day-book-page">
      <header className="border-b border-zinc-200 pb-4">
        <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold flex items-center gap-2">
          <BookOpen size={12} /> Iter150C · Financial Traceability
        </div>
        <h1 className="mt-1 text-4xl font-black tracking-tighter">
          Canonical <span className="text-zinc-400">Financial Day Book</span>
        </h1>
        <p className="mt-2 text-sm text-zinc-600 max-w-3xl">
          Every projected FinTxn leg between two dates. One source of truth ·
          drill from any leg to its authoritative document + full leg set.
        </p>
      </header>

      <section className="grid gap-3 md:grid-cols-5 items-end">
        <div>
          <label className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">From</label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="mt-1 w-full text-sm border border-zinc-300 rounded px-2 py-1.5"
            data-testid="fin-day-book-date-from"
          />
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">To</label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="mt-1 w-full text-sm border border-zinc-300 rounded px-2 py-1.5"
            data-testid="fin-day-book-date-to"
          />
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">Source</label>
          <select
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value)}
            className="mt-1 w-full text-sm border border-zinc-300 rounded px-2 py-1.5"
            data-testid="fin-day-book-source-type"
          >
            {SOURCE_TYPES.map((s) => (
              <option key={s.v} value={s.v}>{s.l}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">Account</label>
          <select
            value={accountCode}
            onChange={(e) => setAccountCode(e.target.value)}
            className="mt-1 w-full text-sm border border-zinc-300 rounded px-2 py-1.5"
            data-testid="fin-day-book-account-code"
          >
            <option value="">All accounts</option>
            {(accounts.data || []).map((a) => (
              <option key={a.code} value={a.code}>{a.code}</option>
            ))}
          </select>
        </div>
        <div className="text-[11px] text-zinc-500 flex items-center gap-1.5">
          <Filter size={12} />
          {dayBook.data ? `${dayBook.data.count} legs` : "—"}
        </div>
      </section>

      {totalsSorted.length > 0 && (
        <section
          className="border border-zinc-200 rounded overflow-x-auto"
          data-testid="fin-day-book-totals"
        >
          <table className="w-full text-xs">
            <thead className="bg-zinc-50 border-b border-zinc-200">
              <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-500">
                <th className="px-3 py-2">Account</th>
                <th className="px-3 py-2 text-right">Debits (in)</th>
                <th className="px-3 py-2 text-right">Credits (out)</th>
                <th className="px-3 py-2 text-right">Net</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {totalsSorted.map((t) => (
                <tr key={t.code} className="border-b border-zinc-100">
                  <td className="px-3 py-2 font-mono text-[11px] font-semibold">{t.code}</td>
                  <td className="px-3 py-2 text-right font-mono">{fmtCurrency(t.in)}</td>
                  <td className="px-3 py-2 text-right font-mono">{fmtCurrency(t.out)}</td>
                  <td className={`px-3 py-2 text-right font-mono font-semibold ${
                    t.net >= 0 ? "text-emerald-800" : "text-rose-800"
                  }`}>{fmtCurrency(t.net)}</td>
                  <td className="px-3 py-2">
                    <Link
                      to={`/fin/accounts/${t.code}?date_from=${dateFrom}&date_to=${dateTo}`}
                      className="text-[11px] font-semibold text-zinc-700 hover:text-zinc-950 inline-flex items-center gap-0.5"
                      data-testid={`fin-account-link-${t.code}`}
                    >
                      Ledger <ChevronRight size={12} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="border border-zinc-200 rounded overflow-x-auto">
        <table className="w-full text-xs" data-testid="fin-day-book-table">
          <thead className="bg-zinc-50 border-b border-zinc-200">
            <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-500">
              <th className="px-3 py-2">Date</th>
              <th className="px-3 py-2">Account</th>
              <th className="px-3 py-2">Dr/Cr</th>
              <th className="px-3 py-2 text-right">Amount</th>
              <th className="px-3 py-2">Counter</th>
              <th className="px-3 py-2">Source</th>
              <th className="px-3 py-2">Narration</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {dayBook.isLoading && (
              <tr><td colSpan={8} className="px-3 py-8 text-center text-zinc-500 text-sm">Loading…</td></tr>
            )}
            {dayBook.isError && (
              <tr><td colSpan={8} className="px-3 py-8 text-center text-rose-700 text-sm">
                {dayBook.error?.response?.data?.detail || "Failed to load Day Book"}
              </td></tr>
            )}
            {dayBook.data && dayBook.data.rows.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-8 text-center text-zinc-500 text-sm" data-testid="fin-day-book-empty">
                No legs in this window.
              </td></tr>
            )}
            {(dayBook.data?.rows || []).map((r) => (
              <tr key={r.id} className="border-b border-zinc-100 hover:bg-zinc-50">
                <td className="px-3 py-2 font-mono text-[11px]">{r.txn_date}</td>
                <td className="px-3 py-2 font-mono text-[11px] font-semibold">{r.account_code}</td>
                <td className="px-3 py-2"><DirBadge direction={r.direction} /></td>
                <td className="px-3 py-2 text-right font-mono">{fmtCurrency(r.amount)}</td>
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
                    data-testid={`fin-day-book-drill-${r.id}`}
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
