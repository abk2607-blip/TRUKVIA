import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, API, fmtCurrency, fmtDate } from "@/api";
import { toast } from "sonner";
import {
  Search, Loader2, FileText, Truck, Wallet, ArrowUpRight, ArrowDownRight,
  Download, Share2, Filter, X, ChevronRight, Calendar
} from "lucide-react";

// ---------- helpers ----------
const inputCls = "w-full border border-zinc-300 px-2.5 py-1.5 rounded-sm text-xs focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";
const chipCls = "inline-flex items-center gap-1 text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded-full border";

function StatusChip({ type, status }) {
  if (type === "trip") {
    return status === "invoiced"
      ? <span className={`${chipCls} bg-emerald-50 text-emerald-800 border-emerald-300`}>Invoiced</span>
      : <span className={`${chipCls} bg-amber-50 text-amber-800 border-amber-300`}>Pending</span>;
  }
  if (type === "invoice") {
    if (status === "paid") return <span className={`${chipCls} bg-emerald-50 text-emerald-800 border-emerald-300`}>Paid</span>;
    if (status === "partial") return <span className={`${chipCls} bg-blue-50 text-blue-800 border-blue-300`}>Partial</span>;
    return <span className={`${chipCls} bg-rose-50 text-rose-800 border-rose-300`}>Unpaid</span>;
  }
  return <span className={`${chipCls} bg-indigo-50 text-indigo-800 border-indigo-300`}>Received</span>;
}

function TypeIcon({ type }) {
  if (type === "trip") return <Truck size={13} className="text-zinc-700" />;
  if (type === "invoice") return <FileText size={13} className="text-indigo-700" />;
  return <Wallet size={13} className="text-emerald-700" />;
}

// ---------- Summary strip ----------
function SummaryStrip({ summary }) {
  const kv = (label, value, hint = null, tone = "zinc") => (
    <div className={`border border-${tone}-200 bg-${tone}-50 rounded-sm p-2.5 min-w-[130px]`}>
      <div className="text-[9px] uppercase tracking-[0.12em] font-bold text-zinc-500">{label}</div>
      <div className="font-mono text-base font-bold text-zinc-900 mt-0.5">{value}</div>
      {hint && <div className="text-[10px] text-zinc-400 mt-0.5">{hint}</div>}
    </div>
  );
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 lg:grid-cols-10 gap-2" data-testid="customer-summary">
      {kv("Trips", summary.trip_count)}
      {kv("Quantity", `${summary.total_qty.toLocaleString()} MT`)}
      {kv("Freight", fmtCurrency(summary.total_freight))}
      {kv("Diesel Recd", fmtCurrency(summary.total_diesel_received))}
      {kv("Advances", fmtCurrency(summary.total_advances))}
      {kv("Shortage", fmtCurrency(summary.total_shortage))}
      {kv("Excess", fmtCurrency(summary.total_excess))}
      {kv("Halting", fmtCurrency(summary.total_halting))}
      {kv("Billed", fmtCurrency(summary.total_billed))}
      {kv("Received", fmtCurrency(summary.total_received))}
      <div className="border border-rose-300 bg-rose-50 rounded-sm p-2.5 min-w-[130px] col-span-2 md:col-span-1 lg:col-span-2">
        <div className="text-[9px] uppercase tracking-[0.12em] font-bold text-rose-700">Outstanding</div>
        <div className="font-mono text-lg font-black text-rose-800 mt-0.5">{fmtCurrency(summary.outstanding)}</div>
        <div className="text-[10px] text-zinc-500 mt-0.5">Uninvoiced: {fmtCurrency(summary.total_pending_uninvoiced)}</div>
      </div>
    </div>
  );
}

// ---------- Filter bar ----------
function FilterBar({ filters, setFilters, onReset }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-6 gap-2 items-end">
      <div>
        <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">From</label>
        <input data-testid="filter-date-from" type="date" value={filters.date_from} onChange={(e) => setFilters({ ...filters, date_from: e.target.value })} className={inputCls} />
      </div>
      <div>
        <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">To</label>
        <input data-testid="filter-date-to" type="date" value={filters.date_to} onChange={(e) => setFilters({ ...filters, date_to: e.target.value })} className={inputCls} />
      </div>
      <div>
        <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Txn Type</label>
        <select data-testid="filter-txn-type" value={filters.txn_type} onChange={(e) => setFilters({ ...filters, txn_type: e.target.value })} className={inputCls}>
          <option value="all">All</option>
          <option value="trip">Trips</option>
          <option value="invoice">Invoices</option>
          <option value="payment">Payments</option>
        </select>
      </div>
      <div>
        <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Invoice Status</label>
        <select data-testid="filter-inv-status" value={filters.invoice_status} onChange={(e) => setFilters({ ...filters, invoice_status: e.target.value })} className={inputCls}>
          <option value="all">All</option>
          <option value="pending">Pending</option>
          <option value="invoiced">Invoiced</option>
        </select>
      </div>
      <div>
        <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Payment Status</label>
        <select data-testid="filter-pay-status" value={filters.payment_status} onChange={(e) => setFilters({ ...filters, payment_status: e.target.value })} className={inputCls}>
          <option value="all">All</option>
          <option value="unpaid">Unpaid</option>
          <option value="partial">Partial</option>
          <option value="paid">Paid</option>
        </select>
      </div>
      <div className="flex gap-2">
        <input data-testid="filter-vehicle" placeholder="Vehicle No" value={filters.vehicle_number} onChange={(e) => setFilters({ ...filters, vehicle_number: e.target.value.toUpperCase() })} className={inputCls} />
        <button data-testid="filter-reset" onClick={onReset} className="p-1.5 border border-zinc-300 rounded-sm text-zinc-600 hover:bg-zinc-950 hover:text-white" title="Reset">
          <X size={12} />
        </button>
      </div>
    </div>
  );
}

// ---------- Transactions Table ----------
function TransactionsTable({ txns }) {
  const nav = useNavigate();
  const onClick = (t) => {
    if (t.type === "trip") nav(`/trips/${t.id}/view`);
    else if (t.type === "invoice") nav(`/invoices/${t.id}`);
    else if (t.type === "payment" && t.invoice_id) nav(`/invoices/${t.invoice_id}`);
  };
  if (!txns.length) {
    return <div className="border border-zinc-200 bg-zinc-50 rounded-sm p-8 text-center text-sm text-zinc-500">No transactions in the selected filters.</div>;
  }
  return (
    <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="transactions-table">
          <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-[0.12em] sticky top-0 z-10">
            <tr>
              <th className="text-left px-3 py-2.5 font-bold">Date</th>
              <th className="text-left px-3 py-2.5 font-bold">Type</th>
              <th className="text-left px-3 py-2.5 font-bold">Ref #</th>
              <th className="text-left px-3 py-2.5 font-bold">Vehicle / Route</th>
              <th className="text-right px-3 py-2.5 font-bold">Qty</th>
              <th className="text-right px-3 py-2.5 font-bold">Amount</th>
              <th className="text-center px-3 py-2.5 font-bold">Status</th>
              <th className="text-center px-3 py-2.5 font-bold w-8"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {txns.map((t, idx) => (
              <tr
                key={`${t.type}-${t.id}-${idx}`}
                data-testid={`txn-row-${t.type}-${t.id}`}
                onClick={() => onClick(t)}
                className={`${idx % 2 === 0 ? "bg-white" : "bg-zinc-50/60"} hover:bg-amber-50/50 cursor-pointer transition-colors`}
              >
                <td className="px-3 py-2.5 font-mono text-xs whitespace-nowrap">{fmtDate(t.date)}</td>
                <td className="px-3 py-2.5">
                  <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-zinc-700 uppercase tracking-wider">
                    <TypeIcon type={t.type} /> {t.type}
                  </div>
                </td>
                <td className="px-3 py-2.5 font-mono text-xs whitespace-nowrap">
                  <span className={`inline-block font-mono text-[11px] font-bold px-2 py-0.5 rounded-sm border ${t.type === "trip" ? "bg-indigo-50 text-indigo-800 border-indigo-200" : t.type === "invoice" ? "bg-purple-50 text-purple-800 border-purple-200" : "bg-emerald-50 text-emerald-800 border-emerald-200"}`}>
                    {t.ref || "—"}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-xs">
                  {t.type === "trip" ? (
                    <div>
                      <div className="font-mono font-bold">{t.vehicle_number}</div>
                      <div className="text-[10px] text-zinc-500 truncate max-w-[220px]">{t.from_location} → {t.to_location}</div>
                    </div>
                  ) : t.type === "invoice" ? (
                    <div className="text-zinc-500">Invoice{t.due_date ? ` · due ${fmtDate(t.due_date)}` : ""}</div>
                  ) : (
                    <div className="text-zinc-500">Payment{t.mode ? ` · ${t.mode}` : ""}{t.note ? ` · ${t.note}` : ""}</div>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right font-mono text-xs">
                  {t.type === "trip" ? `${Number(t.tons || 0).toFixed(2)}` : "—"}
                </td>
                <td className={`px-3 py-2.5 text-right font-mono text-sm font-bold ${t.type === "payment" ? "text-emerald-700" : "text-zinc-900"}`}>
                  {t.type === "payment" ? "+ " : ""}{fmtCurrency(t.amount)}
                </td>
                <td className="px-3 py-2.5 text-center">
                  <StatusChip type={t.type} status={t.status} />
                </td>
                <td className="px-3 py-2.5 text-center">
                  <ChevronRight size={14} className="text-zinc-400" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------- Left Panel: Customers List ----------
function CustomersList({ customers, selectedId, onSelect, search, setSearch, balances }) {
  const q = search.trim().toLowerCase();
  const filtered = q
    ? customers.filter((c) => c.name.toLowerCase().includes(q) || (c.phone || "").includes(q) || (c.gstin || "").toLowerCase().includes(q))
    : customers;
  return (
    <aside className="w-full md:w-80 flex-shrink-0 border border-zinc-200 bg-white rounded-sm flex flex-col max-h-[calc(100vh-140px)]">
      <div className="p-3 border-b border-zinc-200 flex items-center gap-2 flex-shrink-0">
        <Search size={14} className="text-zinc-400" />
        <input
          data-testid="customer-search"
          placeholder="Search Party…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 bg-transparent outline-none text-sm"
        />
      </div>
      <div className="overflow-y-auto flex-1">
        {filtered.length === 0 && <div className="p-6 text-center text-xs text-zinc-400">No customers found</div>}
        {filtered.map((c) => {
          const bal = balances?.[c.id] || 0;
          return (
            <button
              key={c.id}
              data-testid={`customer-row-${c.id}`}
              onClick={() => onSelect(c.id)}
              className={`w-full flex items-center justify-between gap-2 px-3 py-3 border-b border-zinc-100 text-left hover:bg-amber-50/50 transition-colors ${selectedId === c.id ? "bg-indigo-50 border-l-4 border-l-indigo-600" : ""}`}
            >
              <div className="min-w-0 flex-1">
                <div className="font-bold text-sm truncate">{c.name}</div>
                <div className="text-[10px] uppercase tracking-wider text-zinc-500 mt-0.5">Customer</div>
              </div>
              <div className="text-right">
                <div className={`font-mono text-sm font-bold ${bal > 0 ? "text-rose-700" : bal < 0 ? "text-emerald-700" : "text-zinc-700"}`}>
                  {fmtCurrency(Math.abs(bal))}
                </div>
                {bal > 0 && <ArrowUpRight size={12} className="ml-auto text-rose-600" />}
                {bal < 0 && <ArrowDownRight size={12} className="ml-auto text-emerald-600" />}
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

// ---------- Main Page ----------
export default function CustomerHistory() {
  const params = useParams();
  const nav = useNavigate();
  const [selectedId, setSelectedId] = useState(params.id || null);
  const [search, setSearch] = useState("");
  const emptyFilters = { date_from: "", date_to: "", txn_type: "all", invoice_status: "all", payment_status: "all", vehicle_number: "" };
  const [filters, setFilters] = useState(emptyFilters);
  const [sharing, setSharing] = useState(false);

  const { data: customers = [], isLoading: loadingCust } = useQuery({
    queryKey: ["customers"],
    queryFn: async () => (await api.get("/customers")).data,
  });

  // Auto-select first customer if none is selected
  useEffect(() => {
    if (!selectedId && customers.length) {
      setSelectedId(customers[0].id);
    }
  }, [customers, selectedId]);

  // Sync URL with selection
  useEffect(() => {
    if (selectedId && params.id !== selectedId) {
      nav(`/customers/history/${selectedId}`, { replace: true });
    }
  }, [selectedId]); // eslint-disable-line

  const queryParams = useMemo(() => {
    const p = {};
    Object.entries(filters).forEach(([k, v]) => { if (v && v !== "all") p[k] = v; });
    return p;
  }, [filters]);

  const { data: history, isLoading: loadingHist, refetch } = useQuery({
    queryKey: ["customer-history", selectedId, queryParams],
    queryFn: async () => (await api.get(`/customers/${selectedId}/transactions`, { params: queryParams })).data,
    enabled: !!selectedId,
  });

  const balances = useMemo(() => {
    // Sum outstanding across customers for the left-panel display — best-effort lightweight compute.
    // For now, we rely on server data if available; else zero.
    return {};
  }, [customers]);

  const downloadStatement = () => {
    if (!selectedId) return;
    const p = new URLSearchParams();
    if (filters.date_from) p.set("date_from", filters.date_from);
    if (filters.date_to) p.set("date_to", filters.date_to);
    const q = p.toString();
    window.open(`${API}/customers/${selectedId}/statement.pdf${q ? `?${q}` : ""}`, "_blank");
  };
  const shareStatement = async () => {
    if (!selectedId) return;
    setSharing(true);
    try {
      const p = {};
      if (filters.date_from) p.date_from = filters.date_from;
      if (filters.date_to) p.date_to = filters.date_to;
      const { data } = await api.post(`/customers/${selectedId}/share-statement`, null, { params: p });
      window.open(data.whatsapp_url, "_blank");
      toast.success("Statement ready to share on WhatsApp");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Share failed");
    } finally {
      setSharing(false);
    }
  };

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between border-b border-zinc-200 pb-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Ledger</div>
          <h1 className="text-3xl font-black tracking-tighter">
            <span className="telugu">కస్టమర్ లావాదేవీలు</span>
            <span className="text-zinc-400"> · Customer Transaction History</span>
          </h1>
        </div>
      </header>

      <div className="flex flex-col md:flex-row gap-4">
        <CustomersList
          customers={customers}
          selectedId={selectedId}
          onSelect={(id) => { setSelectedId(id); setFilters(emptyFilters); }}
          search={search}
          setSearch={setSearch}
          balances={balances}
        />

        {/* Right Panel */}
        <main className="flex-1 min-w-0 space-y-4">
          {loadingCust && <div className="text-sm text-zinc-500 flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading…</div>}
          {!selectedId && !loadingCust && (
            <div className="border border-zinc-200 bg-zinc-50 rounded-sm p-10 text-center text-sm text-zinc-500">
              Select a customer from the list to view their transaction history.
            </div>
          )}

          {selectedId && history && (
            <>
              {/* Customer Header */}
              <div className="border border-zinc-200 bg-white rounded-sm p-4 flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Customer</div>
                  <h2 data-testid="customer-name" className="text-2xl font-black tracking-tight truncate">{history.customer.name}</h2>
                  <div className="text-xs text-zinc-500 mt-1 space-x-2">
                    {history.customer.gstin && <span>GSTIN: <span className="font-mono text-zinc-700">{history.customer.gstin}</span></span>}
                    {history.customer.phone && <span>· {history.customer.phone}</span>}
                    {history.customer.state && <span>· {history.customer.state}</span>}
                  </div>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  <button data-testid="download-statement-btn" onClick={downloadStatement} className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider px-3 py-2 border border-zinc-950 text-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white transition font-bold">
                    <Download size={12} /> PDF Statement
                  </button>
                  <button data-testid="share-statement-btn" onClick={shareStatement} disabled={sharing} className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider px-3 py-2 border border-emerald-500 bg-emerald-50 text-emerald-800 rounded-sm hover:bg-emerald-100 transition font-bold disabled:opacity-50">
                    {sharing ? <Loader2 size={12} className="animate-spin" /> : <Share2 size={12} />} WhatsApp
                  </button>
                </div>
              </div>

              {/* Summary Strip */}
              <SummaryStrip summary={history.summary} />

              {/* Filter Bar */}
              <div className="border border-zinc-200 bg-zinc-50/50 rounded-sm p-3">
                <div className="text-[10px] uppercase tracking-[0.12em] font-bold text-zinc-500 mb-2 flex items-center gap-1"><Filter size={11} /> Filters</div>
                <FilterBar filters={filters} setFilters={setFilters} onReset={() => setFilters(emptyFilters)} />
              </div>

              {/* Transactions */}
              {loadingHist ? (
                <div className="text-sm text-zinc-500 flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading transactions…</div>
              ) : (
                <TransactionsTable txns={history.transactions} />
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
