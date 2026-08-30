import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, API, fmtCurrency, fmtDate } from "@/api";
import { toast } from "sonner";
import {
  Search, Loader2, FileText, Truck, Wallet, ArrowUpRight, ArrowDownRight,
  Download, Share2, Filter, X, ChevronRight, ChevronDown, Bell, Plus, Send, Pencil, History
} from "lucide-react";
import PolicyChangeHistory from "@/components/PolicyChangeHistory";
import NoteCreateFromCustomerDialog from "@/components/NoteCreateFromCustomerDialog";
import { useCdnEnabled } from "@/hooks/useCdnEnabled";
import { useAuth } from "@/context/AuthContext";
import { FileMinus, FilePlus } from "lucide-react";

const inputCls = "w-full border border-zinc-300 px-2.5 py-1.5 rounded-sm text-xs focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";
const chipCls = "inline-flex items-center gap-1 text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded-full border";

// ---------- Reusable primitives ----------
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
function KV({ label, value, hint, tone = "zinc" }) {
  const bg = { zinc: "bg-zinc-50 border-zinc-200", rose: "bg-rose-50 border-rose-300", amber: "bg-amber-50 border-amber-300", indigo: "bg-indigo-50 border-indigo-300", emerald: "bg-emerald-50 border-emerald-300" }[tone] || "";
  return (
    <div className={`border rounded-sm p-2.5 min-w-[120px] ${bg}`}>
      <div className="text-[9px] uppercase tracking-[0.12em] font-bold text-zinc-500">{label}</div>
      <div className="font-mono text-base font-bold text-zinc-900 mt-0.5">{value}</div>
      {hint && <div className="text-[10px] text-zinc-400 mt-0.5">{hint}</div>}
    </div>
  );
}

// ---------- Summary strip ----------
function SummaryStrip({ summary }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 lg:grid-cols-10 gap-2" data-testid="customer-summary">
      <KV label="Trips" value={summary.trip_count} />
      <KV label="Quantity" value={`${summary.total_qty.toLocaleString()} MT`} />
      <KV label="Freight" value={fmtCurrency(summary.total_freight)} />
      <KV label="Diesel Recd" value={fmtCurrency(summary.total_diesel_received)} />
      <KV label="Advances" value={fmtCurrency(summary.total_advances)} />
      <KV label="Shortage" value={fmtCurrency(summary.total_shortage)} />
      <KV label="Excess" value={fmtCurrency(summary.total_excess)} />
      <KV label="Halting" value={fmtCurrency(summary.total_halting)} />
      <KV label="Billed" value={fmtCurrency(summary.total_billed)} />
      <KV label="Received" value={fmtCurrency(summary.total_received)} />
      <div className="border border-rose-300 bg-rose-50 rounded-sm p-2.5 col-span-2 md:col-span-1 lg:col-span-2">
        <div className="text-[9px] uppercase tracking-[0.12em] font-bold text-rose-700">Outstanding</div>
        <div className="font-mono text-lg font-black text-rose-800 mt-0.5">{fmtCurrency(summary.outstanding)}</div>
        <div className="text-[10px] text-zinc-500 mt-0.5">Uninvoiced: {fmtCurrency(summary.total_pending_uninvoiced)}</div>
      </div>
    </div>
  );
}

// ---------- Aging Buckets (Iter37) ----------
function AgingCards({ aging }) {
  if (!aging) return null;
  const items = [
    { key: "0_30", label: "0-30 Days", tone: "emerald" },
    { key: "31_60", label: "31-60 Days", tone: "amber" },
    { key: "61_90", label: "61-90 Days", tone: "rose" },
    { key: "90_plus", label: "90+ Days", tone: "rose" },
  ];
  return (
    <div className="grid grid-cols-4 gap-2" data-testid="aging-buckets">
      {items.map((it) => {
        const val = aging[it.key] || 0;
        const active = val > 0;
        const bg = active
          ? (it.tone === "emerald" ? "bg-emerald-50 border-emerald-300 text-emerald-800"
            : it.tone === "amber" ? "bg-amber-50 border-amber-300 text-amber-800"
            : "bg-rose-50 border-rose-300 text-rose-800")
          : "bg-zinc-50 border-zinc-200 text-zinc-400";
        return (
          <div key={it.key} data-testid={`aging-${it.key}`} className={`border rounded-sm p-2.5 ${bg}`}>
            <div className="text-[9px] uppercase tracking-[0.12em] font-bold">{it.label}</div>
            <div className="font-mono text-base font-bold mt-0.5">{fmtCurrency(val)}</div>
          </div>
        );
      })}
    </div>
  );
}

// ---------- Filter bar ----------
function FilterBar({ filters, setFilters, onReset }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-6 gap-2 items-end">
      <div><label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">From</label><input data-testid="filter-date-from" type="date" value={filters.date_from} onChange={(e) => setFilters({ ...filters, date_from: e.target.value })} className={inputCls} /></div>
      <div><label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">To</label><input data-testid="filter-date-to" type="date" value={filters.date_to} onChange={(e) => setFilters({ ...filters, date_to: e.target.value })} className={inputCls} /></div>
      <div>
        <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Invoice Status</label>
        <select data-testid="filter-inv-status" value={filters.invoice_status} onChange={(e) => setFilters({ ...filters, invoice_status: e.target.value })} className={inputCls}>
          <option value="all">All</option><option value="pending">Pending</option><option value="invoiced">Invoiced</option>
        </select>
      </div>
      <div>
        <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Payment Status</label>
        <select data-testid="filter-pay-status" value={filters.payment_status} onChange={(e) => setFilters({ ...filters, payment_status: e.target.value })} className={inputCls}>
          <option value="all">All</option><option value="unpaid">Unpaid</option><option value="partial">Partial</option><option value="paid">Paid</option>
        </select>
      </div>
      <div><label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Vehicle</label><input data-testid="filter-vehicle" placeholder="AP16TA1234" value={filters.vehicle_number} onChange={(e) => setFilters({ ...filters, vehicle_number: e.target.value.toUpperCase() })} className={inputCls} /></div>
      <div className="flex items-end"><button data-testid="filter-reset" onClick={onReset} className="w-full p-1.5 border border-zinc-300 rounded-sm text-zinc-600 hover:bg-zinc-950 hover:text-white text-xs uppercase tracking-wider font-bold flex items-center justify-center gap-1"><X size={11} /> Reset</button></div>
    </div>
  );
}

// ---------- Month grouping helper ----------
function groupByMonth(txns) {
  const monthNames = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const groups = {};
  for (const t of txns) {
    const d = (t.date || "").slice(0, 7);
    if (!groups[d]) {
      const [y, m] = d.split("-");
      const label = (d && y && m) ? `${monthNames[Number(m)-1] || "?"} ${y}` : "Undated";
      groups[d] = { key: d || "undated", label, items: [], total: 0 };
    }
    groups[d].items.push(t);
    if (t.type === "payment") groups[d].total += Number(t.amount || 0);
    else if (t.type === "trip" || t.type === "invoice") groups[d].total += Number(t.amount || 0);
  }
  return Object.values(groups).sort((a, b) => (a.key < b.key ? 1 : -1));
}

// ---------- Unified transaction row (used by All / Trip Ledger / Passbook) ----------
function TxnRow({ t, onClick, showType = true }) {
  return (
    <tr data-testid={`txn-row-${t.type}-${t.id}`} onClick={onClick} className="cursor-pointer hover:bg-amber-50/50 transition-colors border-t border-zinc-100">
      <td className="px-3 py-2.5 font-mono text-xs whitespace-nowrap">{fmtDate(t.date)}</td>
      {showType && (
        <td className="px-3 py-2.5"><div className="inline-flex items-center gap-1.5 text-xs font-semibold text-zinc-700 uppercase tracking-wider"><TypeIcon type={t.type} /> {t.type}</div></td>
      )}
      <td className="px-3 py-2.5 font-mono text-xs whitespace-nowrap"><span className={`inline-block font-mono text-[11px] font-bold px-2 py-0.5 rounded-sm border ${t.type === "trip" ? "bg-indigo-50 text-indigo-800 border-indigo-200" : t.type === "invoice" ? "bg-purple-50 text-purple-800 border-purple-200" : "bg-emerald-50 text-emerald-800 border-emerald-200"}`}>{t.ref || "—"}</span></td>
      <td className="px-3 py-2.5 text-xs">
        {t.type === "trip" ? (
          <div><div className="font-mono font-bold">{t.vehicle_number}</div><div className="text-[10px] text-zinc-500 truncate max-w-[220px]">{t.from_location} → {t.to_location}</div></div>
        ) : t.type === "invoice" ? (
          <div className="text-zinc-500">Invoice{t.due_date ? ` · due ${fmtDate(t.due_date)}` : ""}</div>
        ) : (
          <div className="text-zinc-500">Payment{t.mode ? ` · ${t.mode}` : ""}{t.note ? ` · ${t.note}` : ""}</div>
        )}
      </td>
      <td className="px-3 py-2.5 text-right font-mono text-xs">{t.type === "trip" ? `${Number(t.tons || 0).toFixed(2)}` : "—"}</td>
      <td className={`px-3 py-2.5 text-right font-mono text-sm font-bold ${t.type === "payment" ? "text-emerald-700" : "text-zinc-900"}`}>{t.type === "payment" ? "+ " : ""}{fmtCurrency(t.amount)}</td>
      <td className="px-3 py-2.5 text-center"><StatusChip type={t.type} status={t.status} /></td>
      <td className="px-3 py-2.5 text-center"><ChevronRight size={14} className="text-zinc-400" /></td>
    </tr>
  );
}

// ---------- All Tab (unified list with month grouping) ----------
function AllTab({ txns, onOpen }) {
  const [collapsed, setCollapsed] = useState({});
  const groups = groupByMonth(txns);
  if (!txns.length) return <div className="border border-zinc-200 bg-zinc-50 rounded-sm p-8 text-center text-sm text-zinc-500">No transactions.</div>;
  return (
    <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="transactions-table">
          <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-[0.12em] sticky top-0 z-10">
            <tr>
              <th className="text-left px-3 py-2.5 font-bold">Date</th>
              <th className="text-left px-3 py-2.5 font-bold">Type</th>
              <th className="text-left px-3 py-2.5 font-bold">Ref #</th>
              <th className="text-left px-3 py-2.5 font-bold">Details</th>
              <th className="text-right px-3 py-2.5 font-bold">Qty</th>
              <th className="text-right px-3 py-2.5 font-bold">Amount</th>
              <th className="text-center px-3 py-2.5 font-bold">Status</th>
              <th className="w-8"></th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <React.Fragment key={g.key}>
                <tr data-testid={`month-header-${g.key}`} onClick={() => setCollapsed((s) => ({ ...s, [g.key]: !s[g.key] }))} className="cursor-pointer bg-zinc-100 hover:bg-zinc-200 sticky top-9 z-[9]">
                  <td colSpan={8} className="px-3 py-2 text-xs font-bold text-zinc-800 uppercase tracking-wider">
                    <div className="flex items-center gap-2">
                      {collapsed[g.key] ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                      <span>{g.label}</span>
                      <span className="text-[10px] font-mono text-zinc-500 ml-2">{g.items.length} txns · {fmtCurrency(g.total)}</span>
                    </div>
                  </td>
                </tr>
                {!collapsed[g.key] && g.items.map((t, idx) => (
                  <TxnRow key={`${t.type}-${t.id}-${idx}`} t={t} onClick={() => onOpen(t)} />
                ))}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------- Trip Ledger Tab ----------
function TripLedgerTab({ trips, invoices, onOpen }) {
  const invMap = useMemo(() => Object.fromEntries(invoices.map((i) => [i.id, i])), [invoices]);
  if (!trips.length) return <div className="border border-zinc-200 bg-zinc-50 rounded-sm p-8 text-center text-sm text-zinc-500">No trips.</div>;
  return (
    <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="trip-ledger-table">
          <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-[0.12em]">
            <tr>
              <th className="text-left px-3 py-2.5">Date</th>
              <th className="text-left px-3 py-2.5">LR#</th>
              <th className="text-left px-3 py-2.5">Vehicle</th>
              <th className="text-left px-3 py-2.5">Route</th>
              <th className="text-right px-3 py-2.5">Tons</th>
              <th className="text-right px-3 py-2.5">Freight</th>
              <th className="text-right px-3 py-2.5">Diesel Recd</th>
              <th className="text-right px-3 py-2.5">Advance</th>
              <th className="text-center px-3 py-2.5">Invoice</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {trips.map((t) => (
              <tr key={t.id} data-testid={`trip-ledger-row-${t.id}`} onClick={() => onOpen({ type: "trip", ...t })} className="cursor-pointer hover:bg-amber-50/50">
                <td className="px-3 py-2.5 font-mono text-xs">{fmtDate(t.date)}</td>
                <td className="px-3 py-2.5"><span className="font-mono text-[11px] font-bold px-2 py-0.5 bg-indigo-50 text-indigo-800 border border-indigo-200 rounded-sm">{t.lr_number || "—"}</span></td>
                <td className="px-3 py-2.5 font-mono font-bold">{t.vehicle_number}</td>
                <td className="px-3 py-2.5 text-xs">{t.from_location} → {t.to_location}</td>
                <td className="px-3 py-2.5 text-right font-mono">{Number(t.tons).toFixed(2)}</td>
                <td className="px-3 py-2.5 text-right font-mono font-bold">{fmtCurrency(t.freight_amount)}</td>
                <td className="px-3 py-2.5 text-right font-mono text-xs">{fmtCurrency(t.customer_diesel_received)}</td>
                <td className="px-3 py-2.5 text-right font-mono text-xs">{fmtCurrency(t.customer_advance_received)}</td>
                <td className="px-3 py-2.5 text-center">
                  {t.invoice_id ? <span className="font-mono text-[10px] text-purple-800 font-bold">{invMap[t.invoice_id]?.invoice_number || "→"}</span> : <span className="text-[10px] text-amber-700 font-bold">PENDING</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------- Invoice Ledger Tab (with drill-down to trip LRs) ----------
function InvoiceLedgerTab({ invoices, trips, onOpen }) {
  const [expanded, setExpanded] = useState({});
  if (!invoices.length) return <div className="border border-zinc-200 bg-zinc-50 rounded-sm p-8 text-center text-sm text-zinc-500">No invoices.</div>;
  const tripsByInv = trips.reduce((acc, t) => {
    if (t.invoice_id) (acc[t.invoice_id] = acc[t.invoice_id] || []).push(t);
    return acc;
  }, {});
  return (
    <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
      <table className="w-full text-sm" data-testid="invoice-ledger-table">
        <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-[0.12em]">
          <tr>
            <th className="w-8"></th>
            <th className="text-left px-3 py-2.5">Date</th>
            <th className="text-left px-3 py-2.5">Invoice #</th>
            <th className="text-right px-3 py-2.5">Total</th>
            <th className="text-right px-3 py-2.5">Paid</th>
            <th className="text-right px-3 py-2.5">Balance</th>
            <th className="text-center px-3 py-2.5">Status</th>
            <th className="text-center px-3 py-2.5">Trips</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100">
          {invoices.map((inv) => {
            const isOpen = expanded[inv.id];
            const linked = tripsByInv[inv.id] || [];
            return (
              <React.Fragment key={inv.id}>
                <tr data-testid={`invoice-ledger-row-${inv.id}`} className="hover:bg-amber-50/50">
                  <td className="px-1 text-center"><button onClick={() => setExpanded((s) => ({ ...s, [inv.id]: !s[inv.id] }))} className="p-1 rounded hover:bg-zinc-200" data-testid={`invoice-expand-${inv.id}`}>{isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</button></td>
                  <td className="px-3 py-2.5 font-mono text-xs cursor-pointer" onClick={() => onOpen({ type: "invoice", id: inv.id, invoice_id: inv.id })}>{fmtDate(inv.date)}</td>
                  <td className="px-3 py-2.5"><span className="font-mono text-[11px] font-bold px-2 py-0.5 bg-purple-50 text-purple-800 border border-purple-200 rounded-sm">{inv.invoice_number}</span></td>
                  <td className="px-3 py-2.5 text-right font-mono font-bold">{fmtCurrency(inv.total)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-emerald-700">{fmtCurrency(inv.amount_paid)}</td>
                  <td className="px-3 py-2.5 text-right font-mono font-bold text-rose-700">{fmtCurrency(inv.balance_due)}</td>
                  <td className="px-3 py-2.5 text-center"><StatusChip type="invoice" status={inv.payment_status} /></td>
                  <td className="px-3 py-2.5 text-center text-xs font-mono">{linked.length}</td>
                </tr>
                {isOpen && linked.map((t) => (
                  <tr key={`${inv.id}-${t.id}`} data-testid={`invoice-drill-${inv.id}-${t.id}`} className="bg-zinc-50/70 hover:bg-amber-50/40 cursor-pointer" onClick={() => onOpen({ type: "trip", id: t.id })}>
                    <td></td>
                    <td className="px-3 py-1.5 font-mono text-[11px] text-zinc-500">{fmtDate(t.date)}</td>
                    <td className="px-3 py-1.5" colSpan={2}>
                      <span className="font-mono text-[10px] font-bold px-2 py-0.5 bg-indigo-50 text-indigo-800 border border-indigo-200 rounded-sm mr-2">{t.lr_number || "—"}</span>
                      <span className="text-xs">{t.vehicle_number} · {t.from_location} → {t.to_location}</span>
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-xs">{Number(t.tons).toFixed(2)} MT</td>
                    <td className="px-3 py-1.5 text-right font-mono text-xs font-bold">{fmtCurrency(t.freight_amount)}</td>
                    <td colSpan={2} className="px-3 py-1.5 text-center text-[10px] text-zinc-500">↳ Trip</td>
                  </tr>
                ))}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------- Monthly Balances Tab ----------
function MonthlyBalancesTab({ customerId }) {
  const { data, isLoading } = useQuery({
    queryKey: ["monthly-balances", customerId],
    queryFn: async () => (await api.get(`/customers/${customerId}/monthly-balances`)).data,
    enabled: !!customerId,
  });
  if (isLoading) return <div className="text-sm text-zinc-500 flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading…</div>;
  const months = data?.months || [];
  if (!months.length) return <div className="border border-zinc-200 bg-zinc-50 rounded-sm p-8 text-center text-sm text-zinc-500">No monthly data.</div>;
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="monthly-balances-grid">
      {months.map((m) => {
        const [y, mm] = m.month.split("-");
        const label = `${["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][Number(mm)-1] || "?"} ${y || ""}`;
        return (
          <div key={m.month} data-testid={`monthly-card-${m.month}`} className="border border-zinc-200 rounded-sm p-3 bg-white">
            <div className="flex items-center justify-between mb-2">
              <div className="font-bold text-sm">{label}</div>
              <div className="text-[10px] uppercase font-bold text-zinc-500">{m.trip_count} trips · {m.quantity.toFixed(2)} MT</div>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div><div className="text-[9px] uppercase text-zinc-500 font-bold">Freight</div><div className="font-mono font-bold">{fmtCurrency(m.freight)}</div></div>
              <div><div className="text-[9px] uppercase text-zinc-500 font-bold">Billed</div><div className="font-mono font-bold">{fmtCurrency(m.billed)}</div></div>
              <div><div className="text-[9px] uppercase text-zinc-500 font-bold text-emerald-700">Received</div><div className="font-mono font-bold text-emerald-700">{fmtCurrency(m.received)}</div></div>
              <div><div className="text-[9px] uppercase text-zinc-500 font-bold text-rose-700">Balance</div><div className="font-mono font-bold text-rose-700">{fmtCurrency(m.balance)}</div></div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------- Add Payment Drawer (right slide-in) ----------
function AddPaymentDrawer({ customer, invoices, onClose, onSaved }) {
  const [form, setForm] = useState({
    amount: "", date: new Date().toISOString().slice(0, 10),
    mode: "Cash", note: "", received_by_driver: false,
  });
  const [photoDataUrl, setPhotoDataUrl] = useState("");
  const [allocOn, setAllocOn] = useState(false);
  const [allocations, setAllocations] = useState({});
  const outstandingInvs = invoices.filter((i) => Number(i.balance_due || 0) > 0);

  const save = useMutation({
    mutationFn: async () => {
      const body = { ...form, amount: Number(form.amount || 0) };
      if (allocOn) body.allocations = Object.entries(allocations).filter(([, v]) => Number(v) > 0).map(([k, v]) => ({ invoice_id: k, amount: Number(v) }));
      if (photoDataUrl) body.photo_data_url = photoDataUrl;
      return (await api.post(`/customers/${customer.id}/add-payment`, body)).data;
    },
    onSuccess: (d) => {
      const bits = [`${d.applied.length} invoice(s) updated`];
      if (d.amount_unallocated > 0.01) bits.push(`₹${d.amount_unallocated.toFixed(2)} added as advance`);
      if (d.photo_url) bits.push("photo saved");
      toast.success(`Payment applied — ${bits.join(", ")}`);
      onSaved?.();
      onClose?.();
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Payment failed"),
  });

  const onPhotoPick = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) {
      toast.error("Photo too large — keep it under 4MB");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setPhotoDataUrl(reader.result);
    reader.readAsDataURL(file);
  };

  return (
    <div className="fixed inset-0 z-[70] flex" data-testid="add-payment-drawer">
      <div className="flex-1 bg-zinc-900/40 backdrop-blur-sm" onClick={onClose}></div>
      <div className="w-full max-w-md bg-white border-l border-zinc-950 h-full flex flex-col">
        <div className="px-5 py-3 border-b border-zinc-200 flex items-center justify-between">
          <div>
            <div className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">Add Party Payment</div>
            <h3 className="font-bold text-base">{customer.name}</h3>
          </div>
          <button onClick={onClose} data-testid="close-payment-drawer"><X size={18} /></button>
        </div>
        <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="p-5 space-y-4 overflow-y-auto flex-1">
          <div>
            <label className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">Payment Amount</label>
            <div className="relative"><span className="absolute left-3 top-2.5 text-zinc-500">₹</span><input required autoFocus data-testid="pay-amount" type="number" step="0.01" min="0.01" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} className={`${inputCls} pl-6 text-base py-2.5`} placeholder="Enter Amount" /></div>
          </div>
          <div>
            <label className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">Payment Method</label>
            <select data-testid="pay-mode" value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })} className={`${inputCls} py-2.5`}>
              {["Cash", "Cheque", "UPI", "Bank Transfer", "Fuel", "Others"].map((m) => <option key={m}>{m}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">Payment Date</label>
            <input data-testid="pay-date" type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={`${inputCls} py-2.5`} />
          </div>
          <div>
            <label className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">Notes</label>
            <textarea data-testid="pay-note" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} rows={2} className={inputCls} placeholder="Enter Notes" />
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input data-testid="pay-driver-toggle" type="checkbox" checked={form.received_by_driver} onChange={(e) => setForm({ ...form, received_by_driver: e.target.checked })} />
            <span className="text-xs font-semibold">Received By Driver</span>
          </label>

          {/* Photo Capture */}
          <div className="border border-zinc-200 rounded-sm p-3 bg-zinc-50">
            <div className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider mb-2">Payment Receipt Photo (optional)</div>
            {photoDataUrl ? (
              <div className="relative">
                <img src={photoDataUrl} alt="Receipt" className="max-h-48 rounded-sm border border-zinc-300" data-testid="pay-photo-preview" />
                <button type="button" onClick={() => setPhotoDataUrl("")} data-testid="pay-photo-remove" className="absolute top-1 right-1 bg-zinc-950 text-white rounded-full p-1 hover:bg-rose-600">
                  <X size={12} />
                </button>
              </div>
            ) : (
              <label className="cursor-pointer inline-flex items-center gap-2 text-xs uppercase tracking-wider font-bold px-3 py-1.5 border border-zinc-400 rounded-sm hover:bg-zinc-950 hover:text-white hover:border-zinc-950">
                <Plus size={12} />
                <span>Attach / Capture Photo</span>
                <input data-testid="pay-photo-input" type="file" accept="image/*" capture="environment" onChange={onPhotoPick} className="hidden" />
              </label>
            )}
            <div className="text-[10px] text-zinc-500 mt-1.5">Snap cash / cheque / UPI screenshot for audit trail.</div>
          </div>

          {outstandingInvs.length > 0 && (
            <div className="border border-zinc-200 rounded-sm p-3 bg-zinc-50">
              <label className="flex items-center gap-2 cursor-pointer mb-2">
                <input data-testid="pay-alloc-toggle" type="checkbox" checked={allocOn} onChange={(e) => setAllocOn(e.target.checked)} />
                <span className="text-xs font-bold uppercase tracking-wider text-zinc-700">Choose Trips / Invoices to allocate</span>
              </label>
              {!allocOn ? (
                <div className="text-[11px] text-zinc-500">Default: oldest invoices first.</div>
              ) : (
                <div className="space-y-1 max-h-40 overflow-y-auto">
                  {outstandingInvs.map((i) => (
                    <div key={i.id} className="flex items-center gap-2 text-xs">
                      <span className="font-mono flex-1 truncate">{i.invoice_number} · {fmtDate(i.date)} · Bal {fmtCurrency(i.balance_due)}</span>
                      <input data-testid={`pay-alloc-${i.id}`} type="number" step="0.01" min="0" max={i.balance_due} placeholder="0" value={allocations[i.id] || ""} onChange={(e) => setAllocations({ ...allocations, [i.id]: e.target.value })} className="w-24 border border-zinc-300 px-2 py-1 rounded-sm text-xs" />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </form>
        <div className="p-4 border-t border-zinc-200 flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Close</button>
          <button data-testid="pay-save-btn" onClick={() => save.mutate()} disabled={save.isPending || !form.amount} className="px-4 py-2 text-xs uppercase tracking-wider bg-emerald-600 text-white rounded-sm hover:bg-emerald-700 disabled:opacity-50 font-bold">
            {save.isPending ? "Saving…" : "Save Payment"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------- Bulk Reminder Modal ----------
function BulkReminderModal({ onClose }) {
  const { data, isLoading } = useQuery({
    queryKey: ["bulk-reminders"],
    queryFn: async () => (await api.get("/customers/bulk-reminder")).data,
  });
  const reminders = data?.reminders || [];
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4" data-testid="bulk-reminder-modal">
      <div className="bg-white w-full max-w-3xl max-h-[90vh] border border-zinc-950 rounded-sm flex flex-col">
        <div className="px-5 py-3 border-b border-zinc-200 flex items-center justify-between">
          <div>
            <div className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">Bulk Payment Reminders</div>
            <h3 className="font-bold text-base">Send WhatsApp reminders to customers with outstanding balance</h3>
          </div>
          <button onClick={onClose} data-testid="close-bulk-reminder"><X size={18} /></button>
        </div>
        {isLoading ? <div className="p-8 text-center"><Loader2 size={16} className="animate-spin inline mr-2" /> Loading…</div> : (
          <div className="overflow-y-auto flex-1 p-4">
            {reminders.length === 0 ? <div className="text-center py-8 text-sm text-zinc-500">No customers with outstanding balance 🎉</div> : (
              <>
                <div className="mb-3 flex items-center justify-between">
                  <div className="text-xs text-zinc-600">{data.total_customers} customers · Total outstanding: <span className="font-bold text-rose-700">{fmtCurrency(data.total_outstanding)}</span></div>
                  <button data-testid="send-all-reminders" onClick={() => {
                    reminders.forEach((r, i) => setTimeout(() => window.open(r.whatsapp_url, "_blank"), i * 350));
                    toast.success(`Opening ${reminders.length} WhatsApp windows…`);
                  }} className="text-xs uppercase font-bold tracking-wider px-3 py-1.5 bg-emerald-600 text-white rounded-sm hover:bg-emerald-700 inline-flex items-center gap-1"><Send size={11} /> Send All</button>
                </div>
                <table className="w-full text-sm">
                  <thead className="bg-zinc-100 text-[10px] uppercase font-bold text-zinc-600">
                    <tr><th className="text-left px-3 py-2">Customer</th><th className="text-left px-3 py-2">Phone</th><th className="text-right px-3 py-2">Balance</th><th className="text-right px-3 py-2">Oldest</th><th className="text-center px-3 py-2">Action</th></tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100">
                    {reminders.map((r) => (
                      <tr key={r.customer_id} data-testid={`reminder-row-${r.customer_id}`}>
                        <td className="px-3 py-2 font-semibold">{r.customer_name}</td>
                        <td className="px-3 py-2 font-mono text-xs">{r.phone || "—"}</td>
                        <td className="px-3 py-2 text-right font-mono font-bold text-rose-700">{fmtCurrency(r.balance)}</td>
                        <td className="px-3 py-2 text-right text-xs text-zinc-500">{r.oldest_days}d</td>
                        <td className="px-3 py-2 text-center">
                          <button data-testid={`reminder-send-${r.customer_id}`} onClick={() => window.open(r.whatsapp_url, "_blank")} className="text-[10px] uppercase font-bold px-2 py-1 border border-emerald-500 text-emerald-700 rounded-sm hover:bg-emerald-50 inline-flex items-center gap-1"><Send size={10} /> WhatsApp</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------- Party Details Tab (Iter38) ----------
function PartyDetailsTab({ customer, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [f, setF] = useState({
    name: customer.name || "", phone: customer.phone || "", email: customer.email || "",
    gstin: customer.gstin || "", pan: customer.pan || "",
    address: customer.address || "", state: customer.state || "", pincode: customer.pincode || "",
    opening_balance: customer.opening_balance || 0, notes: customer.notes || "",
    reminder_enabled: customer.reminder_enabled !== false,
  });
  const save = useMutation({
    mutationFn: async () => (await api.put(`/customers/${customer.id}`, {
      ...f, opening_balance: Number(f.opening_balance || 0),
    })).data,
    onSuccess: () => { toast.success("Party updated"); setEditing(false); onSaved?.(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Save failed"),
  });
  const R = ({ label, value, editable, k, type = "text" }) => (
    <div className="border-b border-zinc-100 py-2.5">
      <div className="text-[10px] uppercase tracking-[0.12em] font-bold text-zinc-500">{label}</div>
      {editing && editable ? (
        <input data-testid={`pd-${k}`} type={type} value={f[k] || ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} className={`${inputCls} mt-1`} />
      ) : (
        <div className="text-sm font-semibold text-zinc-900 mt-0.5">{value || <span className="text-zinc-300">—</span>}</div>
      )}
    </div>
  );
  return (
    <div className="border border-zinc-200 bg-white rounded-sm p-5" data-testid="party-details-tab">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.12em] font-bold text-zinc-500">Party Profile</div>
          <h3 className="text-xl font-black tracking-tight">{customer.name}</h3>
        </div>
        {!editing ? (
          <button data-testid="pd-edit-btn" onClick={() => setEditing(true)} className="text-xs uppercase tracking-wider font-bold px-3 py-1.5 border border-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white">Quick Edit</button>
        ) : (
          <div className="flex gap-2">
            <button onClick={() => { setEditing(false); setF({ ...customer }); }} className="text-xs uppercase tracking-wider font-bold px-3 py-1.5 border border-zinc-300 rounded-sm">Cancel</button>
            <button data-testid="pd-save-btn" onClick={() => save.mutate()} disabled={save.isPending} className="text-xs uppercase tracking-wider font-bold px-3 py-1.5 bg-emerald-600 text-white rounded-sm hover:bg-emerald-700 disabled:opacity-50">{save.isPending ? "Saving…" : "Save"}</button>
          </div>
        )}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
        <R label="Name" value={customer.name} editable k="name" />
        <R label="Primary Contact" value={customer.phone} editable k="phone" />
        <R label="Email" value={customer.email} editable k="email" type="email" />
        <R label="GSTIN" value={customer.gstin} editable k="gstin" />
        <R label="PAN" value={customer.pan} editable k="pan" />
        <R label="Pincode" value={customer.pincode} editable k="pincode" />
        <R label="State" value={customer.state} editable k="state" />
        <R label="Opening Balance (₹)" value={customer.opening_balance ? fmtCurrency(customer.opening_balance) : "0"} editable k="opening_balance" type="number" />
        <div className="md:col-span-2">
          <R label="Address" value={customer.address} editable k="address" />
        </div>
        <div className="md:col-span-2">
          <R label="Notes" value={customer.notes} editable k="notes" />
        </div>
        <div className="md:col-span-2 pt-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input data-testid="pd-reminder-toggle" type="checkbox" checked={f.reminder_enabled} disabled={!editing} onChange={(e) => setF({ ...f, reminder_enabled: e.target.checked })} />
            <span className="text-xs font-semibold uppercase tracking-wider">Include in Nightly WhatsApp Reminder Digest</span>
          </label>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-2 pt-4 border-t border-zinc-200">
        <KV label="Advance on Account" value={fmtCurrency(customer.advance_balance || 0)} tone={customer.advance_balance > 0 ? "emerald" : "zinc"} />
        <KV label="Opening Balance" value={fmtCurrency(customer.opening_balance || 0)} />
        <KV label="Customer Since" value={fmtDate(customer.created_at) || "—"} />
        <KV label="Party ID" value={customer.id.slice(-8).toUpperCase()} />
      </div>
    </div>
  );
}

// ---------- Left Panel: Customers with balance ----------
function CustomersList({ customers, selectedId, onSelect, search, setSearch }) {
  const q = search.trim().toLowerCase();
  const filtered = q
    ? customers.filter((c) => c.name.toLowerCase().includes(q) || (c.phone || "").includes(q) || (c.gstin || "").toLowerCase().includes(q))
    : customers;
  return (
    <aside className="w-full md:w-80 flex-shrink-0 border border-zinc-200 bg-white rounded-sm flex flex-col max-h-[calc(100vh-140px)]">
      <div className="p-3 border-b border-zinc-200 flex items-center gap-2 flex-shrink-0"><Search size={14} className="text-zinc-400" /><input data-testid="customer-search" placeholder="Search Party…" value={search} onChange={(e) => setSearch(e.target.value)} className="flex-1 bg-transparent outline-none text-sm" /></div>
      <div className="overflow-y-auto flex-1">
        {filtered.length === 0 && <div className="p-6 text-center text-xs text-zinc-400">No customers found</div>}
        {filtered.map((c) => {
          const bal = c.outstanding_balance || 0;
          return (
            <button key={c.id} data-testid={`customer-row-${c.id}`} onClick={() => onSelect(c.id)} className={`w-full flex items-center justify-between gap-2 px-3 py-3 border-b border-zinc-100 text-left hover:bg-amber-50/50 transition-colors ${selectedId === c.id ? "bg-indigo-50 border-l-4 border-l-indigo-600" : ""}`}>
              <div className="min-w-0 flex-1">
                <div className="font-bold text-sm truncate">{c.name}</div>
                <div className="text-[10px] uppercase tracking-wider text-zinc-500 mt-0.5">Customer</div>
              </div>
              <div className="text-right flex items-center gap-1">
                <div className={`font-mono text-sm font-bold ${bal > 0 ? "text-rose-700" : "text-zinc-500"}`}>{fmtCurrency(bal)}</div>
                {bal > 0 && <ArrowUpRight size={12} className="text-rose-600" />}
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

// ---------- Iter104b · Profile + Billing Policy read-only card ----------
const _FM_LABELS = {
  per_ton_loading: "Per Ton · Loading Qty",
  per_ton_unloading: "Per Ton · Unloading Qty",
  per_ton_higher_of: "Per Ton · Higher of Loading / Unloading",
  fixed: "Fixed / Round Trip",
};
const _SM_LABELS = {
  net_shortage: "Net Shortage (deduct only excess above limit)",
  full_after_limit: "Full Shortage After Limit Exceeded",
};
function CustomerProfileAndPolicyCard({ customer }) {
  const fm = (customer.default_freight_method || "per_ton_loading").toLowerCase();
  const sc = customer.shortage_config || {};
  const scLimit = Number(sc.limit || 0);
  const hasCustom = scLimit > 0;
  const [historyOpen, setHistoryOpen] = useState(false);
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="customer-view-profile-policy">
      {/* Profile ----------------------------------------------------- */}
      <div className="border border-zinc-200 bg-white rounded-sm p-4" data-testid="customer-view-profile">
        <div className="text-[10px] uppercase tracking-[0.12em] font-bold text-zinc-500 mb-2">Customer Profile</div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          <_L k="Name" v={customer.name} testid="cvp-name" bold />
          <_L k="GSTIN" v={customer.gstin} testid="cvp-gstin" mono />
          <_L k="PAN" v={customer.pan} testid="cvp-pan" mono />
          <_L k="State" v={customer.state} testid="cvp-state" />
          <_L k="Pincode" v={customer.pincode} testid="cvp-pincode" mono />
          <_L k="Phone" v={customer.phone} testid="cvp-phone" mono />
          <_L k="Email" v={customer.email} testid="cvp-email" />
          <_L k="Opening Balance" v={fmtCurrency(customer.opening_balance || 0)} testid="cvp-opening" mono />
          <div className="col-span-2">
            <_L k="Billing Address" v={customer.address} testid="cvp-address" wrap />
          </div>
          {customer.notes && <div className="col-span-2"><_L k="Notes" v={customer.notes} testid="cvp-notes" wrap /></div>}
        </dl>
      </div>

      {/* Current Billing Policy ------------------------------------- */}
      <div className="border border-zinc-200 bg-white rounded-sm p-4" data-testid="customer-view-policy">
        <div className="flex items-center justify-between mb-2">
          <div className="text-[10px] uppercase tracking-[0.12em] font-bold text-zinc-500">Current Billing Policy</div>
          {/* Iter105 · Phase B — Policy Change History launcher */}
          <button
            onClick={() => setHistoryOpen(true)}
            className="inline-flex items-center gap-1 text-[10px] uppercase tracking-widest font-bold px-2 py-1 border border-amber-500 text-amber-700 hover:bg-amber-50"
            data-testid="open-policy-history-btn">
            <History size={12} /> Policy History
          </button>
        </div>
        <dl className="grid grid-cols-1 gap-y-2 text-xs">
          <_L k="Freight Calculation Method" v={_FM_LABELS[fm] || fm} testid="cvp-freight-method" bold />
          <_L k="Shortage Deduction Method" v={_SM_LABELS[(sc.method || "net_shortage")] || (sc.method || "—")} testid="cvp-shortage-method" bold />
          <div className={`border rounded-sm p-2 mt-1 ${hasCustom ? "bg-amber-50 border-amber-300" : "bg-zinc-50 border-zinc-200"}`}>
            <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-600">Shortage Allowance</div>
            {hasCustom ? (
              <>
                <div className="text-sm font-bold text-amber-900 mt-0.5" data-testid="cvp-custom-allowance">
                  Custom · {scLimit}{sc.limit_type === "kg" ? " KG" : " %"} of Loaded Qty
                </div>
                <div className="text-[10px] text-amber-800 mt-0.5">Overrides Product Master allowance for this customer.</div>
              </>
            ) : (
              <div className="text-sm font-bold text-zinc-800 mt-0.5" data-testid="cvp-product-fallback">
                Uses Product Master allowance (per product default_shortage_allowance_pct)
              </div>
            )}
          </div>
          <_L k="Effective From" v={sc.effective_from ? fmtDate(sc.effective_from) : "—"} testid="cvp-effective-from" />
          <_L k="Policy Status" v={sc.active === false ? "Inactive" : "Active"} testid="cvp-policy-status" tone={sc.active === false ? "rose" : "emerald"} />
          {sc.remarks && <_L k="Policy Remarks" v={sc.remarks} testid="cvp-policy-remarks" wrap />}
        </dl>
      </div>

      {historyOpen && (
        <PolicyChangeHistory
          customerId={customer.id}
          customerName={customer.name}
          onClose={() => setHistoryOpen(false)}
        />
      )}
    </div>
  );
}
function _L({ k, v, testid, bold, mono, wrap, tone }) {
  const toneCls = tone === "emerald" ? "text-emerald-700" : tone === "rose" ? "text-rose-700" : "text-zinc-800";
  return (
    <div className={wrap ? "" : "min-w-0"}>
      <dt className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">{k}</dt>
      <dd data-testid={testid} className={`${mono ? "font-mono" : ""} ${bold ? "font-bold" : ""} ${toneCls} ${wrap ? "whitespace-pre-wrap" : "truncate"}`}>
        {v || "—"}
      </dd>
    </div>
  );
}

// ---------- MAIN ----------
export default function CustomerHistory() {
  const params = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState(params.id || null);
  const [search, setSearch] = useState("");
  const emptyFilters = { date_from: "", date_to: "", invoice_status: "all", payment_status: "all", vehicle_number: "" };
  const [filters, setFilters] = useState(emptyFilters);
  const [tab, setTab] = useState("all");   // all | trips | invoices | passbook | monthly
  const [showPayment, setShowPayment] = useState(false);
  const [showBulk, setShowBulk] = useState(false);
  const [sharing, setSharing] = useState(false);
  // Iter132c C2b — Customer-based CN/DN entry (gated by cdnEnabled probe).
  const [noteKind, setNoteKind] = useState(null); // "credit" | "debit" | null
  const cdnEnabled = useCdnEnabled();

  const { data: customers = [], isLoading: loadingCust } = useQuery({
    queryKey: ["customers", "with-balance"],
    queryFn: async () => (await api.get("/customers", { params: { with_balance: true } })).data,
  });

  useEffect(() => {
    if (!selectedId && customers.length) setSelectedId(customers[0].id);
  }, [customers, selectedId]);
  useEffect(() => {
    if (selectedId && params.id !== selectedId) nav(`/customers/history/${selectedId}`, { replace: true });
  }, [selectedId]); // eslint-disable-line

  const queryParams = useMemo(() => {
    const p = {};
    Object.entries(filters).forEach(([k, v]) => { if (v && v !== "all") p[k] = v; });
    return p;
  }, [filters]);

  const { data: history, isLoading: loadingHist } = useQuery({
    queryKey: ["customer-history", selectedId, queryParams],
    queryFn: async () => (await api.get(`/customers/${selectedId}/transactions`, { params: queryParams })).data,
    enabled: !!selectedId,
  });

  const openTxn = (t) => {
    if (t.type === "trip") nav(`/trips/${t.id}/view`);
    else if (t.type === "invoice") nav(`/invoices/${t.id}`);
    else if (t.type === "payment" && t.invoice_id) nav(`/invoices/${t.invoice_id}`);
  };

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
    } catch (e) { toast.error(e?.response?.data?.detail || "Share failed"); }
    finally { setSharing(false); }
  };

  const tabs = [
    { id: "all", label: "All · Passbook", te: "అన్నీ" },
    { id: "trips", label: "Trip Ledger", te: "ట్రిప్‌లు" },
    { id: "invoices", label: "Invoice Ledger", te: "ఇన్వాయిస్‌లు" },
    { id: "monthly", label: "Monthly Balances", te: "మంత్లీ" },
    { id: "details", label: "Party Details", te: "వివరాలు" },
  ];

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between border-b border-zinc-200 pb-3 gap-3 flex-wrap">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Ledger</div>
          <h1 className="text-3xl font-black tracking-tighter"><span className="telugu">కస్టమర్ లావాదేవీలు</span><span className="text-zinc-400"> · Customer Transaction History</span></h1>
        </div>
        <button data-testid="bulk-reminder-btn" onClick={() => setShowBulk(true)} className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider px-3 py-2 border border-amber-500 bg-amber-50 text-amber-800 rounded-sm hover:bg-amber-100 transition font-bold">
          <Bell size={12} /> Bulk Reminders
        </button>
      </header>

      <div className="flex flex-col md:flex-row gap-4">
        <CustomersList customers={customers} selectedId={selectedId} onSelect={(id) => { setSelectedId(id); setFilters(emptyFilters); }} search={search} setSearch={setSearch} />

        <main className="flex-1 min-w-0 space-y-4">
          {loadingCust && <div className="text-sm text-zinc-500 flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading…</div>}
          {!selectedId && !loadingCust && <div className="border border-zinc-200 bg-zinc-50 rounded-sm p-10 text-center text-sm text-zinc-500">Select a customer from the list.</div>}

          {selectedId && history && (
            <>
              {/* Customer Header + Actions */}
              <div className="border border-zinc-200 bg-white rounded-sm p-4 flex items-start justify-between gap-4 flex-wrap">
                <div className="min-w-0">
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Customer</div>
                  <h2 data-testid="customer-name" className="text-2xl font-black tracking-tight truncate">{history.customer.name}</h2>
                  <div className="text-xs text-zinc-500 mt-1 space-x-2">
                    {history.customer.gstin && <span>GSTIN: <span className="font-mono text-zinc-700">{history.customer.gstin}</span></span>}
                    {history.customer.phone && <span>· {history.customer.phone}</span>}
                    {history.customer.state && <span>· {history.customer.state}</span>}
                    {Number(history.customer.advance_balance || 0) > 0 && (
                      <span data-testid="advance-chip" className="ml-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider font-bold bg-emerald-50 text-emerald-800 border border-emerald-300">
                        Advance on Account · {fmtCurrency(history.customer.advance_balance)}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex gap-2 flex-shrink-0 flex-wrap">
                  {/* Iter104b — Edit routes to Customers page with ?edit= param so the
                      existing modal opens; on save Customers.jsx returns to this view. */}
                  <button
                    data-testid="customer-view-edit-btn"
                    onClick={() => nav(`/customers?edit=${selectedId}&returnTo=history`)}
                    className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider px-3 py-2 border border-zinc-950 text-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white font-bold"
                    title="Edit customer profile & policy"
                  >
                    <Pencil size={12} /> Edit
                  </button>
                  <button data-testid="add-payment-btn" onClick={() => setShowPayment(true)} className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider px-3 py-2 bg-blue-600 text-white rounded-sm hover:bg-blue-700 font-bold"><Plus size={12} /> Add Payment</button>
                  <button data-testid="add-trip-btn" onClick={() => nav(`/trips/new?customer_id=${selectedId}`)} className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider px-3 py-2 bg-emerald-600 text-white rounded-sm hover:bg-emerald-700 font-bold"><Plus size={12} /> Add Trip</button>
                  {cdnEnabled && (
                    <>
                      <button
                        data-testid="customer-add-credit-note-btn"
                        onClick={() => setNoteKind("credit")}
                        title="Issue a Credit Note against one of this customer's invoices"
                        className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider px-3 py-2 border border-emerald-600 text-emerald-700 bg-white rounded-sm hover:bg-emerald-600 hover:text-white font-bold">
                        <FileMinus size={12} /> Credit Note
                      </button>
                      <button
                        data-testid="customer-add-debit-note-btn"
                        onClick={() => setNoteKind("debit")}
                        title="Issue a Debit Note against one of this customer's invoices"
                        className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider px-3 py-2 border border-orange-600 text-orange-700 bg-white rounded-sm hover:bg-orange-600 hover:text-white font-bold">
                        <FilePlus size={12} /> Debit Note
                      </button>
                    </>
                  )}
                  <button data-testid="download-statement-btn" onClick={downloadStatement} className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider px-3 py-2 border border-zinc-950 text-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white font-bold"><Download size={12} /> PDF</button>
                  <button data-testid="share-statement-btn" onClick={shareStatement} disabled={sharing} className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider px-3 py-2 border border-emerald-500 bg-emerald-50 text-emerald-800 rounded-sm hover:bg-emerald-100 font-bold disabled:opacity-50">{sharing ? <Loader2 size={12} className="animate-spin" /> : <Share2 size={12} />} WhatsApp</button>
                </div>
              </div>

              {/* Iter104b — Customer Profile + Current Billing Policy (read-only) */}
              <CustomerProfileAndPolicyCard customer={history.customer} />

              <SummaryStrip summary={history.summary} />
              {/* Iter133 L2 · Adjustments summary strip (uses aggregate totals only; no backend change). */}
              {history.summary && ((Number(history.summary.credits_total) || 0) > 0 || (Number(history.summary.debits_total) || 0) > 0) && (
                <div
                  data-testid="passbook-adjustments-strip"
                  className="border border-amber-200 bg-amber-50 rounded-sm px-3 py-2 text-xs text-zinc-800 flex items-center gap-2 flex-wrap"
                >
                  <span className="font-bold uppercase tracking-wider text-zinc-600">Adjustments applied:</span>
                  {(Number(history.summary.credits_total) || 0) > 0 && (
                    <span data-testid="passbook-adj-cn" className="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm border border-red-300 bg-red-50 text-red-800 font-mono font-semibold">
                      − {fmtCurrency(history.summary.credits_total)} (Credit Notes)
                    </span>
                  )}
                  {(Number(history.summary.debits_total) || 0) > 0 && (
                    <span data-testid="passbook-adj-dn" className="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm border border-blue-300 bg-blue-50 text-blue-800 font-mono font-semibold">
                      + {fmtCurrency(history.summary.debits_total)} (Debit Notes)
                    </span>
                  )}
                  <span className="text-[10px] text-zinc-500">Detailed CN/DN available on the Notes page.</span>
                </div>
              )}
              <AgingCards aging={history.summary.aging} />

              <div className="border border-zinc-200 bg-zinc-50/50 rounded-sm p-3">
                <div className="text-[10px] uppercase tracking-[0.12em] font-bold text-zinc-500 mb-2 flex items-center gap-1"><Filter size={11} /> Filters</div>
                <FilterBar filters={filters} setFilters={setFilters} onReset={() => setFilters(emptyFilters)} />
              </div>

              {/* Tabs */}
              <div className="border-b border-zinc-200 flex gap-1" data-testid="ledger-tabs">
                {tabs.map((t) => (
                  <button
                    key={t.id}
                    data-testid={`ledger-tab-${t.id}`}
                    onClick={() => setTab(t.id)}
                    className={`px-4 py-2 text-xs uppercase tracking-wider font-bold border-b-2 transition ${tab === t.id ? "border-indigo-600 text-indigo-700" : "border-transparent text-zinc-500 hover:text-zinc-800"}`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              {loadingHist ? (
                <div className="text-sm text-zinc-500 flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading transactions…</div>
              ) : (
                <>
                  {tab === "all" && <AllTab txns={history.transactions} onOpen={openTxn} />}
                  {tab === "trips" && <TripLedgerTab trips={history.trips} invoices={history.invoices} onOpen={openTxn} />}
                  {tab === "invoices" && <InvoiceLedgerTab invoices={history.invoices} trips={history.trips} onOpen={openTxn} />}
                  {tab === "monthly" && <MonthlyBalancesTab customerId={selectedId} />}
                  {tab === "details" && <PartyDetailsTab customer={history.customer} onSaved={() => { qc.invalidateQueries({ queryKey: ["customer-history", selectedId] }); qc.invalidateQueries({ queryKey: ["customers", "with-balance"] }); }} />}
                </>
              )}
            </>
          )}
        </main>
      </div>

      {showPayment && history && (
        <AddPaymentDrawer
          customer={history.customer}
          invoices={history.invoices}
          onClose={() => setShowPayment(false)}
          onSaved={() => { qc.invalidateQueries({ queryKey: ["customer-history", selectedId] }); qc.invalidateQueries({ queryKey: ["customers", "with-balance"] }); }}
        />
      )}
      {showBulk && <BulkReminderModal onClose={() => setShowBulk(false)} />}
      {noteKind && selectedId && (
        <NoteCreateFromCustomerDialog
          kind={noteKind}
          customerId={selectedId}
          onClose={() => {
            setNoteKind(null);
            qc.invalidateQueries({ queryKey: ["customer-history", selectedId] });
            qc.invalidateQueries({ queryKey: ["customers", "with-balance"] });
          }}
        />
      )}
    </div>
  );
}
