import React, { useState } from "react";
import { NavLink, Routes, Route, Navigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, API, fmtCurrency, fmtDate } from "@/api";
import { FileText, TrendingUp, Scale, Download, Landmark, Handshake } from "lucide-react";

const tabs = [
  { to: "ledger", te: "లెడ్జర్", en: "Ledger", icon: FileText, testid: "tab-ledger" },
  { to: "pl", te: "లాభ-నష్టం", en: "P&L", icon: TrendingUp, testid: "tab-pl" },
  { to: "supplier-pl", te: "సప్లయర్ P&L", en: "Supplier P&L", icon: Handshake, testid: "tab-supplier-pl" },
  { to: "balance-sheet", te: "బ్యాలెన్స్ షీట్", en: "Balance Sheet", icon: Scale, testid: "tab-balance-sheet" },
  { to: "gstr1", te: "GSTR-1", en: "GSTR-1", icon: Landmark, testid: "tab-gstr1" },
];

export default function Reports() {
  return (
    <div className="space-y-6" data-testid="reports-page">
      <header className="border-b border-zinc-200 pb-4">
        <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Reports</div>
        <h1 className="mt-1 text-4xl font-black tracking-tighter">
          <span className="telugu">రిపోర్ట్‌లు</span>
          <span className="text-zinc-400"> · Reports</span>
        </h1>
      </header>

      <nav className="flex gap-2 border-b border-zinc-200">
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            data-testid={t.testid}
            className={({ isActive }) =>
              `inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold border-b-2 -mb-px ${
                isActive ? "border-zinc-950 text-zinc-950" : "border-transparent text-zinc-500 hover:text-zinc-950"
              }`
            }
          >
            <t.icon size={14} />
            <span><span className="telugu">{t.te}</span> · {t.en}</span>
          </NavLink>
        ))}
      </nav>

      <Routes>
        <Route index element={<Navigate to="ledger" replace />} />
        <Route path="ledger" element={<LedgerReport />} />
        <Route path="pl" element={<PLReport />} />
        <Route path="supplier-pl" element={<SupplierPLReport />} />
        <Route path="balance-sheet" element={<BalanceSheetReport />} />
        <Route path="gstr1" element={<GSTR1Report />} />
      </Routes>
    </div>
  );
}

/* ------------------ Supplier P&L ------------------ */
function SupplierPLReport() {
  const today = new Date();
  const firstDay = new Date(today.getFullYear(), today.getMonth(), 1).toISOString().slice(0, 10);
  const [start, setStart] = useState(firstDay);
  const [end, setEnd] = useState(today.toISOString().slice(0, 10));

  const { data, refetch, isFetching } = useQuery({
    queryKey: ["supplier-pl", start, end],
    queryFn: async () => (await api.get("/reports/supplier-pl", { params: { start, end } })).data,
  });

  return (
    <div className="space-y-4" data-testid="supplier-pl-tab">
      <div className="border border-zinc-200 bg-white rounded-sm p-4 grid grid-cols-1 md:grid-cols-3 gap-3">
        <FieldWrap label="From"><input data-testid="spl-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className={ic} /></FieldWrap>
        <FieldWrap label="To"><input data-testid="spl-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className={ic} /></FieldWrap>
        <div className="flex items-end">
          <button data-testid="run-spl-btn" onClick={() => refetch()} disabled={isFetching} className="w-full px-3 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800">
            {isFetching ? "Running..." : "Refresh"}
          </button>
        </div>
      </div>

      {data && (
        <div className="border border-zinc-200 bg-white rounded-sm" data-testid="spl-result">
          <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider flex items-center justify-between">
            <span>Supplier Profitability</span>
            <span className="text-xs text-zinc-500 font-normal">
              {data.totals.trips} trips · Profit: <span className="font-bold text-emerald-800">{fmtCurrency(data.totals.profit)}</span>
            </span>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="text-left px-4 py-2">Supplier</th>
                <th className="text-right px-4 py-2">Trips</th>
                <th className="text-right px-4 py-2">Tons</th>
                <th className="text-right px-4 py-2">Customer Freight</th>
                <th className="text-right px-4 py-2">Supplier Freight</th>
                <th className="text-right px-4 py-2">Profit</th>
                <th className="text-right px-4 py-2">Margin %</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {(data.suppliers || []).map((s) => (
                <tr key={s.supplier_name} className="border-t border-zinc-100">
                  <td className="px-4 py-2 font-semibold">{s.supplier_name}</td>
                  <td className="px-4 py-2 text-right">{s.trips}</td>
                  <td className="px-4 py-2 text-right">{s.tons.toFixed(2)}</td>
                  <td className="px-4 py-2 text-right">{fmtCurrency(s.customer_freight)}</td>
                  <td className="px-4 py-2 text-right text-rose-700">{fmtCurrency(s.supplier_freight)}</td>
                  <td className={`px-4 py-2 text-right font-bold ${s.profit >= 0 ? "text-emerald-800" : "text-rose-800"}`}>{fmtCurrency(s.profit)}</td>
                  <td className="px-4 py-2 text-right">{s.margin_pct}%</td>
                </tr>
              ))}
              {(data.suppliers || []).length === 0 && (
                <tr><td colSpan={7} className="px-4 py-10 text-center text-zinc-400 text-sm">No supplier trips in this period.</td></tr>
              )}
            </tbody>
            {(data.suppliers || []).length > 0 && (
              <tfoot>
                <tr className="bg-amber-50 border-t-2 border-zinc-950">
                  <td className="px-4 py-2 font-bold">TOTAL</td>
                  <td className="px-4 py-2 text-right font-bold">{data.totals.trips}</td>
                  <td className="px-4 py-2 text-right font-bold">{data.totals.tons.toFixed(2)}</td>
                  <td className="px-4 py-2 text-right font-bold">{fmtCurrency(data.totals.customer_freight)}</td>
                  <td className="px-4 py-2 text-right font-bold">{fmtCurrency(data.totals.supplier_freight)}</td>
                  <td className="px-4 py-2 text-right font-bold text-emerald-800">{fmtCurrency(data.totals.profit)}</td>
                  <td className="px-4 py-2 text-right"></td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </div>
  );
}

/* ------------------ GSTR-1 ------------------ */
function GSTR1Report() {
  const now = new Date();
  const defaultMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [month, setMonth] = useState(defaultMonth);

  const { data, refetch, isFetching } = useQuery({
    queryKey: ["gstr1", month],
    queryFn: async () => (await api.get("/reports/gstr1", { params: { month } })).data,
    enabled: Boolean(month),
  });

  const downloadCSV = () => {
    if (!data) return;
    const header = ["Type", "Invoice", "Date", "Customer", "GSTIN", "State", "State Code", "POS", "RCM", "Taxable", "CGST", "SGST", "IGST", "Total"];
    const rows = [];
    const push = (r, type) => rows.push([
      type, r.invoice_number, r.invoice_date, r.customer_name, r.gstin, r.state, r.state_code, r.place_of_supply, r.reverse_charge,
      r.taxable_value, r.cgst, r.sgst, r.igst, r.total,
    ]);
    (data.b2b || []).forEach((r) => push(r, "B2B"));
    (data.b2c || []).forEach((r) => push(r, "B2C"));
    const csv = [header, ...rows].map((row) => row.map((c) => `"${(c ?? "").toString().replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `gstr1_${month}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4" data-testid="gstr1-tab">
      <div className="border border-zinc-200 bg-white rounded-sm p-4 grid grid-cols-1 md:grid-cols-3 gap-3">
        <FieldWrap label="Month">
          <input data-testid="gstr1-month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} className={ic} />
        </FieldWrap>
        <div className="flex items-end gap-2">
          <button data-testid="run-gstr1-btn" onClick={() => refetch()} disabled={isFetching} className="flex-1 px-3 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800">
            {isFetching ? "Running..." : "Refresh"}
          </button>
          {data && (
            <button data-testid="gstr1-csv-btn" onClick={downloadCSV} className="p-2 border border-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white" title="Download CSV">
              <Download size={16} />
            </button>
          )}
        </div>
      </div>

      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3" data-testid="gstr1-totals">
            <Kpi label="Invoices" value={data.invoice_count} />
            <Kpi label="Taxable" value={fmtCurrency(data.totals.taxable)} />
            <Kpi label="CGST" value={fmtCurrency(data.totals.cgst)} />
            <Kpi label="SGST" value={fmtCurrency(data.totals.sgst)} />
            <Kpi label="IGST" value={fmtCurrency(data.totals.igst)} />
          </div>

          <div className="border border-zinc-200 bg-white rounded-sm">
            <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">By State (POS)</div>
            <table className="w-full text-sm">
              <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
                <tr>
                  <th className="text-left px-4 py-2">State</th>
                  <th className="text-left px-4 py-2">Code</th>
                  <th className="text-right px-4 py-2">Invoices</th>
                  <th className="text-right px-4 py-2">Taxable</th>
                  <th className="text-right px-4 py-2">CGST</th>
                  <th className="text-right px-4 py-2">SGST</th>
                  <th className="text-right px-4 py-2">IGST</th>
                  <th className="text-right px-4 py-2">Total</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {(data.by_state || []).map((s) => (
                  <tr key={s.state_code} className="border-t border-zinc-100">
                    <td className="px-4 py-2">{s.state || "—"}</td>
                    <td className="px-4 py-2 font-semibold">{s.state_code}</td>
                    <td className="px-4 py-2 text-right">{s.invoices}</td>
                    <td className="px-4 py-2 text-right">{fmtCurrency(s.taxable)}</td>
                    <td className="px-4 py-2 text-right">{fmtCurrency(s.cgst)}</td>
                    <td className="px-4 py-2 text-right">{fmtCurrency(s.sgst)}</td>
                    <td className="px-4 py-2 text-right">{fmtCurrency(s.igst)}</td>
                    <td className="px-4 py-2 text-right font-bold">{fmtCurrency(s.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="border border-zinc-200 bg-white rounded-sm">
            <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">B2B Invoices ({(data.b2b || []).length})</div>
            <div className="overflow-x-auto">
              <GstTable rows={data.b2b || []} />
            </div>
          </div>

          {(data.b2c || []).length > 0 && (
            <div className="border border-zinc-200 bg-white rounded-sm">
              <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">B2C Invoices ({(data.b2c || []).length})</div>
              <div className="overflow-x-auto">
                <GstTable rows={data.b2c || []} />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function GstTable({ rows }) {
  return (
    <table className="w-full text-sm">
      <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
        <tr>
          <th className="text-left px-3 py-2">Invoice</th>
          <th className="text-left px-3 py-2">Date</th>
          <th className="text-left px-3 py-2">Customer</th>
          <th className="text-left px-3 py-2">GSTIN</th>
          <th className="text-left px-3 py-2">POS</th>
          <th className="text-left px-3 py-2">RCM</th>
          <th className="text-right px-3 py-2">Taxable</th>
          <th className="text-right px-3 py-2">CGST</th>
          <th className="text-right px-3 py-2">SGST</th>
          <th className="text-right px-3 py-2">IGST</th>
          <th className="text-right px-3 py-2">Total</th>
        </tr>
      </thead>
      <tbody className="font-mono">
        {rows.map((r) => (
          <tr key={r.invoice_number} className="border-t border-zinc-100">
            <td className="px-3 py-1.5 font-semibold text-xs">{r.invoice_number}</td>
            <td className="px-3 py-1.5 text-xs">{r.invoice_date}</td>
            <td className="px-3 py-1.5 text-xs">{r.customer_name}</td>
            <td className="px-3 py-1.5 text-xs">{r.gstin || "—"}</td>
            <td className="px-3 py-1.5 text-xs">{r.state_code || "—"}</td>
            <td className="px-3 py-1.5 text-xs">{r.reverse_charge}</td>
            <td className="px-3 py-1.5 text-right">{fmtCurrency(r.taxable_value)}</td>
            <td className="px-3 py-1.5 text-right">{fmtCurrency(r.cgst)}</td>
            <td className="px-3 py-1.5 text-right">{fmtCurrency(r.sgst)}</td>
            <td className="px-3 py-1.5 text-right">{fmtCurrency(r.igst)}</td>
            <td className="px-3 py-1.5 text-right font-bold">{fmtCurrency(r.total)}</td>
          </tr>
        ))}
        {rows.length === 0 && (
          <tr><td colSpan={11} className="px-4 py-6 text-center text-zinc-400 text-sm">No records.</td></tr>
        )}
      </tbody>
    </table>
  );
}

function Kpi({ label, value }) {
  return (
    <div className="border border-zinc-200 bg-white p-3 rounded-sm">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">{label}</div>
      <div className="mt-1 font-mono text-base font-bold">{value}</div>
    </div>
  );
}

/* ------------------ Ledger ------------------ */
function LedgerReport() {
  const [customerId, setCustomerId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const { data: customers = [] } = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get("/customers")).data });
  const { data, refetch, isFetching } = useQuery({
    queryKey: ["ledger", customerId, start, end],
    queryFn: async () => (await api.get("/reports/ledger", { params: { customer_id: customerId, start: start || undefined, end: end || undefined } })).data,
    enabled: false,
  });

  const run = () => { if (customerId) refetch(); };
  const pdfUrl = customerId ? `${API}/reports/ledger/pdf?customer_id=${customerId}${start ? `&start=${start}` : ""}${end ? `&end=${end}` : ""}` : null;

  return (
    <div className="space-y-4" data-testid="ledger-tab">
      <div className="border border-zinc-200 bg-white rounded-sm p-4 grid grid-cols-1 md:grid-cols-4 gap-3">
        <FieldWrap label="Customer *">
          <select data-testid="ledger-customer" value={customerId} onChange={(e) => setCustomerId(e.target.value)} className={ic}>
            <option value="">-- Select --</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </FieldWrap>
        <FieldWrap label="From (optional)">
          <input data-testid="ledger-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className={ic} />
        </FieldWrap>
        <FieldWrap label="To (optional)">
          <input data-testid="ledger-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className={ic} />
        </FieldWrap>
        <div className="flex items-end gap-2">
          <button data-testid="run-ledger-btn" disabled={!customerId || isFetching} onClick={run} className="flex-1 px-3 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
            {isFetching ? "Running..." : "Run"}
          </button>
          {pdfUrl && data && (
            <a data-testid="ledger-pdf-btn" href={pdfUrl} target="_blank" rel="noreferrer" className="p-2 border border-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white" title="Download PDF"><Download size={16} /></a>
          )}
        </div>
      </div>

      {data && (
        <div className="border border-zinc-200 bg-white rounded-sm" data-testid="ledger-result">
          <div className="px-5 py-3 border-b border-zinc-200 flex items-center justify-between">
            <div>
              <div className="text-xs font-bold uppercase tracking-wider text-zinc-500">Customer</div>
              <div className="font-bold">{data.customer.name}</div>
            </div>
            <div className="text-right">
              <div className="text-xs font-bold uppercase tracking-wider text-zinc-500">Closing Balance</div>
              <div className="font-mono text-xl font-bold text-amber-800">{fmtCurrency(data.closing_balance)}</div>
            </div>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="text-left px-4 py-2">Date</th>
                <th className="text-left px-4 py-2">Ref</th>
                <th className="text-left px-4 py-2">Particulars</th>
                <th className="text-right px-4 py-2">Debit</th>
                <th className="text-right px-4 py-2">Credit</th>
                <th className="text-right px-4 py-2">Balance</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              <tr className="bg-zinc-50 border-t border-zinc-100">
                <td colSpan={5} className="px-4 py-2 text-xs font-bold">Opening Balance</td>
                <td className="px-4 py-2 text-right font-bold">{fmtCurrency(data.opening_balance)}</td>
              </tr>
              {data.entries.map((e, i) => (
                <tr key={i} className="border-t border-zinc-100">
                  <td className="px-4 py-1.5 text-xs">{fmtDate(e.date)}</td>
                  <td className="px-4 py-1.5 text-xs font-semibold">{e.reference}</td>
                  <td className="px-4 py-1.5 text-xs">{e.particulars}</td>
                  <td className="px-4 py-1.5 text-right">{e.debit ? fmtCurrency(e.debit) : ""}</td>
                  <td className="px-4 py-1.5 text-right text-emerald-700">{e.credit ? fmtCurrency(e.credit) : ""}</td>
                  <td className="px-4 py-1.5 text-right font-semibold">{fmtCurrency(e.balance)}</td>
                </tr>
              ))}
              <tr className="bg-amber-50 border-t border-zinc-300">
                <td colSpan={3} className="px-4 py-2 font-bold">TOTAL</td>
                <td className="px-4 py-2 text-right font-bold">{fmtCurrency(data.total_debit)}</td>
                <td className="px-4 py-2 text-right font-bold text-emerald-700">{fmtCurrency(data.total_credit)}</td>
                <td className="px-4 py-2 text-right font-bold">{fmtCurrency(data.closing_balance)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ------------------ P&L ------------------ */
function PLReport() {
  const today = new Date();
  const firstDay = new Date(today.getFullYear(), today.getMonth(), 1).toISOString().slice(0, 10);
  const [start, setStart] = useState(firstDay);
  const [end, setEnd] = useState(today.toISOString().slice(0, 10));

  const { data, refetch, isFetching } = useQuery({
    queryKey: ["pl", start, end],
    queryFn: async () => (await api.get("/reports/pl", { params: { start, end } })).data,
  });

  return (
    <div className="space-y-4" data-testid="pl-tab">
      <div className="border border-zinc-200 bg-white rounded-sm p-4 grid grid-cols-1 md:grid-cols-3 gap-3">
        <FieldWrap label="From">
          <input data-testid="pl-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className={ic} />
        </FieldWrap>
        <FieldWrap label="To">
          <input data-testid="pl-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className={ic} />
        </FieldWrap>
        <div className="flex items-end">
          <button data-testid="run-pl-btn" onClick={() => refetch()} disabled={isFetching} className="w-full px-3 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800">
            {isFetching ? "Running..." : "Refresh"}
          </button>
        </div>
      </div>

      {data && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4" data-testid="pl-result">
          <div className="lg:col-span-2 border border-zinc-200 bg-white rounded-sm">
            <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">P&L Statement</div>
            <table className="w-full text-sm">
              <tbody className="font-mono">
                <tr className="bg-emerald-50"><td className="px-4 py-2 font-bold">Freight Revenue</td><td className="px-4 py-2 text-right font-bold text-emerald-800">{fmtCurrency(data.revenue)}</td></tr>
                <tr className="border-t border-zinc-100"><td className="px-4 py-1.5 pl-8 text-zinc-600">Diesel</td><td className="px-4 py-1.5 text-right">{fmtCurrency(data.expenses.diesel)}</td></tr>
                <tr className="border-t border-zinc-100"><td className="px-4 py-1.5 pl-8 text-zinc-600">Toll</td><td className="px-4 py-1.5 text-right">{fmtCurrency(data.expenses.toll)}</td></tr>
                <tr className="border-t border-zinc-100"><td className="px-4 py-1.5 pl-8 text-zinc-600">Driver Batta</td><td className="px-4 py-1.5 text-right">{fmtCurrency(data.expenses.batta)}</td></tr>
                <tr className="border-t border-zinc-100"><td className="px-4 py-1.5 pl-8 text-zinc-600">Repairs</td><td className="px-4 py-1.5 text-right">{fmtCurrency(data.expenses.repair)}</td></tr>
                <tr className="border-t border-zinc-100"><td className="px-4 py-1.5 pl-8 text-zinc-600">Other</td><td className="px-4 py-1.5 text-right">{fmtCurrency(data.expenses.other)}</td></tr>
                <tr className="bg-rose-50 border-t border-zinc-200"><td className="px-4 py-2 font-bold">Total Expenses</td><td className="px-4 py-2 text-right font-bold text-rose-800">{fmtCurrency(data.expenses.total)}</td></tr>
                <tr className="bg-amber-50 border-t-2 border-zinc-950"><td className="px-4 py-3 font-black text-base">NET PROFIT</td><td className="px-4 py-3 text-right font-black text-base">{fmtCurrency(data.net_profit)}</td></tr>
                <tr><td className="px-4 py-1.5 text-xs text-zinc-500">Margin</td><td className="px-4 py-1.5 text-right text-xs text-zinc-500">{data.margin_pct}%</td></tr>
                <tr><td className="px-4 py-1.5 text-xs text-zinc-500">Trips in period</td><td className="px-4 py-1.5 text-right text-xs text-zinc-500">{data.trip_count}</td></tr>
              </tbody>
            </table>
          </div>
          <div className="border border-zinc-200 bg-white rounded-sm">
            <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">By Customer</div>
            <div className="divide-y divide-zinc-100 max-h-[500px] overflow-y-auto">
              {(data.per_customer || []).map((c) => (
                <div key={c.customer_id} className="px-5 py-3">
                  <div className="flex justify-between items-baseline">
                    <div className="font-semibold text-sm">{c.customer_name}</div>
                    <div className="font-mono text-sm font-bold">{fmtCurrency(c.revenue)}</div>
                  </div>
                  <div className="text-[10px] text-zinc-500 uppercase tracking-wider mt-0.5">
                    {c.trips} trips · {c.tons.toFixed(2)} tons · profit <span className={c.profit >= 0 ? "text-emerald-700" : "text-rose-700"}>{fmtCurrency(c.profit)}</span>
                  </div>
                </div>
              ))}
              {(data.per_customer || []).length === 0 && <div className="px-5 py-8 text-center text-zinc-400 text-sm">No data in this period.</div>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------ Balance Sheet ------------------ */
function BalanceSheetReport() {
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));

  const { data, refetch, isFetching } = useQuery({
    queryKey: ["balance-sheet", asOf],
    queryFn: async () => (await api.get("/reports/balance-sheet", { params: { as_of: asOf } })).data,
  });

  return (
    <div className="space-y-4" data-testid="bs-tab">
      <div className="border border-zinc-200 bg-white rounded-sm p-4 grid grid-cols-1 md:grid-cols-3 gap-3">
        <FieldWrap label="As of">
          <input data-testid="bs-asof" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className={ic} />
        </FieldWrap>
        <div className="flex items-end md:col-span-2">
          <button data-testid="run-bs-btn" onClick={() => refetch()} disabled={isFetching} className="px-3 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800">
            {isFetching ? "Running..." : "Refresh"}
          </button>
        </div>
      </div>

      {data && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="bs-result">
          <div className="border border-zinc-200 bg-white rounded-sm">
            <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider bg-emerald-50">Assets · ఆస్తులు</div>
            <table className="w-full text-sm">
              <tbody className="font-mono">
                <tr><td className="px-4 py-2">Cash & Bank</td><td className="px-4 py-2 text-right">{fmtCurrency(data.assets.cash_and_bank)}</td></tr>
                <tr className="border-t border-zinc-100"><td className="px-4 py-2">Sundry Debtors (Receivables)</td><td className="px-4 py-2 text-right">{fmtCurrency(data.assets.sundry_debtors)}</td></tr>
                <tr className="border-t-2 border-zinc-950 bg-emerald-50"><td className="px-4 py-2 font-bold">Total Assets</td><td className="px-4 py-2 text-right font-bold">{fmtCurrency(data.assets.total)}</td></tr>
              </tbody>
            </table>
          </div>
          <div className="border border-zinc-200 bg-white rounded-sm">
            <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider bg-rose-50">Equity & Liabilities · ఈక్విటీ</div>
            <table className="w-full text-sm">
              <tbody className="font-mono">
                <tr><td className="px-4 py-2">Retained Earnings (Net Profit)</td><td className="px-4 py-2 text-right">{fmtCurrency(data.equity.retained_earnings)}</td></tr>
                <tr className="border-t border-zinc-100"><td className="px-4 py-2">Owner's Capital (plug)</td><td className="px-4 py-2 text-right">{fmtCurrency(data.equity.owners_capital)}</td></tr>
                <tr className="border-t border-zinc-100"><td className="px-4 py-2">Current Liabilities</td><td className="px-4 py-2 text-right">{fmtCurrency(data.liabilities.total)}</td></tr>
                <tr className="border-t-2 border-zinc-950 bg-amber-50"><td className="px-4 py-2 font-bold">Total Equity + Liabilities</td><td className="px-4 py-2 text-right font-bold">{fmtCurrency(data.equity.total + data.liabilities.total)}</td></tr>
              </tbody>
            </table>
          </div>
          <div className="md:col-span-2 text-xs text-zinc-500 italic">{data.note}</div>
        </div>
      )}
    </div>
  );
}

const ic = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";
function FieldWrap({ label, children }) {
  return (
    <div>
      <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">{label}</label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
