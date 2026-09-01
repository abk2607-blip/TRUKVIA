import React, { useState, useEffect, useRef } from "react";
import { NavLink, Routes, Route, Navigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, API, fmtCurrency, fmtDate } from "@/api";
import { FileText, TrendingUp, Scale, Download, Landmark, Handshake, Clock, MessageCircle, Truck, Printer, ClipboardList, Archive, CheckCircle2, FileWarning, AlertTriangle, ChevronDown, Info } from "lucide-react";
import HaltingReport from "@/pages/HaltingReport";
import { downloadBulkAllCopiesZip } from "@/utils/pdfDownload";
import { useCdnEnabled } from "@/hooks/useCdnEnabled";
import { toast } from "sonner";

const tabs = [
  { to: "ledger", te: "లెడ్జర్", en: "Ledger", icon: FileText, testid: "tab-ledger" },
  { to: "pl", te: "లాభ-నష్టం", en: "P&L", icon: TrendingUp, testid: "tab-pl" },
  { to: "supplier-pl", te: "సప్లయర్ P&L", en: "Supplier P&L", icon: Handshake, testid: "tab-supplier-pl" },
  { to: "supplier-statement", te: "సప్లయర్ స్టేట్‌మెంట్", en: "Supplier Statement", icon: Truck, testid: "tab-supplier-statement" },
  { to: "lr-register", te: "LR రిజిస్టర్", en: "LR Register", icon: ClipboardList, testid: "tab-lr-register" },
  { to: "halting", te: "హాల్టింగ్", en: "Halting", icon: Clock, testid: "tab-halting" },
  { to: "balance-sheet", te: "బ్యాలెన్స్ షీట్", en: "Balance Sheet", icon: Scale, testid: "tab-balance-sheet" },
  { to: "gstr1", te: "GSTR-1", en: "GSTR-1", icon: Landmark, testid: "tab-gstr1" },
  { to: "gstr1-9b", te: "GSTR-1 §9B", en: "GSTR-1 §9B (CN/DN)", icon: FileWarning, testid: "tab-gstr1-9b", requiresCdn: true },
];

export default function Reports() {
  const cdnEnabled = useCdnEnabled();
  const visibleTabs = tabs.filter((t) => !t.requiresCdn || cdnEnabled);
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
        {visibleTabs.map((t) => (
          <NavLink
            key={t.to}
            to={`/reports/${t.to}`}
            end
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
        <Route path="supplier-statement" element={<SupplierStatementReport />} />
        <Route path="lr-register" element={<LRRegisterReport />} />
        <Route path="halting" element={<HaltingReport />} />
        <Route path="balance-sheet" element={<BalanceSheetReport />} />
        <Route path="gstr1" element={<GSTR1Report />} />
        <Route path="gstr1-9b" element={<GSTR19BReport />} />
      </Routes>
    </div>
  );
}

/* ------------------ Supplier Statement (Iter44) ------------------ */
function SupplierStatementReport() {
  const today = new Date();
  const _fmt = (d) => d.toISOString().slice(0, 10);
  const monthStart = _fmt(new Date(today.getFullYear(), today.getMonth(), 1));
  const monthEnd = _fmt(today);
  const [supplier, setSupplier] = useState("");
  const [start, setStart] = useState(monthStart);
  const [end, setEnd] = useState(monthEnd);
  const [openingMode, setOpeningMode] = useState("master"); // Iter47 Phase 3

  const { data: suppliers = [] } = useQuery({
    queryKey: ["suppliers-list"],
    queryFn: async () => (await api.get("/reports/suppliers")).data,
  });

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["supplier-statement", supplier, start, end, openingMode],
    enabled: !!supplier,
    queryFn: async () =>
      (await api.get("/reports/supplier-statement", { params: { supplier_name: supplier, start, end, opening_mode: openingMode } })).data,
  });

  const setThisMonth = () => {
    setStart(_fmt(new Date(today.getFullYear(), today.getMonth(), 1)));
    setEnd(_fmt(today));
  };
  const setLastMonth = () => {
    const y = today.getMonth() === 0 ? today.getFullYear() - 1 : today.getFullYear();
    const m = today.getMonth() === 0 ? 11 : today.getMonth() - 1;
    setStart(_fmt(new Date(y, m, 1)));
    setEnd(_fmt(new Date(y, m + 1, 0)));
  };
  const setPrevMonth = () => {
    const [ys, ms] = start.split("-").map(Number);
    const y = ms === 1 ? ys - 1 : ys;
    const m = ms === 1 ? 12 : ms - 1;
    setStart(`${y}-${String(m).padStart(2, "0")}-01`);
    setEnd(`${y}-${String(m).padStart(2, "0")}-${String(new Date(y, m, 0).getDate()).padStart(2, "0")}`);
  };

  const downloadPdf = async () => {
    if (!supplier) return;
    const resp = await api.get("/reports/supplier-statement.pdf", {
      params: { supplier_name: supplier, start, end, opening_mode: openingMode }, responseType: "blob",
    });
    const url = URL.createObjectURL(new Blob([resp.data], { type: "application/pdf" }));
    const a = document.createElement("a"); a.href = url;
    a.download = `supplier_statement_${supplier.replace(/\s+/g, "_")}_${start}_${end}.pdf`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  };
  const openPrint = async () => {
    if (!supplier) return;
    const resp = await api.get("/reports/supplier-statement.pdf", {
      params: { supplier_name: supplier, start, end, opening_mode: openingMode }, responseType: "blob",
    });
    const url = URL.createObjectURL(new Blob([resp.data], { type: "application/pdf" }));
    const w = window.open(url, "_blank");
    if (w) setTimeout(() => { try { w.print(); } catch (_) {} }, 800);
  };
  const shareWa = async () => {
    if (!supplier) return;
    try {
      const { data: r } = await api.post("/reports/supplier-statement/share", null, {
        params: { supplier_name: supplier, start, end, opening_mode: openingMode },
      });
      window.open(r.whatsapp_url, "_blank", "noopener");
      const { toast } = await import("sonner");
      if (!r.supplier_mobile_available) {
        toast.info(`No saved mobile for ${supplier} — WhatsApp opened without a recipient. Add mobile in Vehicles master.`);
      } else {
        toast.success(`WhatsApp ready — ${r.supplier_mobile}`);
      }
    } catch (e) {
      const { toast } = await import("sonner");
      toast.error(e?.response?.data?.detail || "Share failed");
    }
  };

  return (
    <div className="space-y-4" data-testid="supplier-statement-tab">
      {/* Selectors */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end bg-zinc-50 border border-zinc-200 rounded-sm p-4">
        <div>
          <label className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">Supplier · సప్లయర్</label>
          <select
            data-testid="ss-supplier-select"
            value={supplier}
            onChange={(e) => setSupplier(e.target.value)}
            className="mt-1 w-full border border-zinc-300 px-2 py-1.5 rounded-sm text-sm bg-white focus:border-zinc-950 outline-none"
          >
            <option value="">— Select supplier —</option>
            {suppliers.map((s) => (
              <option key={s.name} value={s.name}>{s.name}{s.mobile ? ` (${s.mobile})` : ""}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">From</label>
          <input data-testid="ss-start" type="date" value={start} onChange={(e) => setStart(e.target.value)}
            className="mt-1 w-full border border-zinc-300 px-2 py-1.5 rounded-sm text-sm bg-white" />
        </div>
        <div>
          <label className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">To</label>
          <input data-testid="ss-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)}
            className="mt-1 w-full border border-zinc-300 px-2 py-1.5 rounded-sm text-sm bg-white" />
        </div>
        <div className="md:col-span-2 flex flex-wrap gap-2 items-center">
          <button type="button" data-testid="ss-this-month" onClick={setThisMonth} className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100">This Month</button>
          <button type="button" data-testid="ss-last-month" onClick={setLastMonth} className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100">Last Month</button>
          <button type="button" data-testid="ss-prev-month" onClick={setPrevMonth} className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100">◀ Prev</button>
          <select data-testid="ss-opening-mode" value={openingMode} onChange={(e) => setOpeningMode(e.target.value)}
            title="How to compute Opening Balance"
            className="px-2 py-1.5 text-[10px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100 bg-white">
            <option value="master">Opening: From Master</option>
            <option value="carry_forward">Opening: Carry Forward</option>
          </select>
          <button type="button" data-testid="ss-refresh" onClick={() => refetch()} disabled={!supplier || isFetching}
            className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold bg-zinc-950 text-white rounded-sm disabled:opacity-50">
            {isFetching ? "Loading…" : "Generate"}
          </button>
        </div>
      </div>

      {/* Action bar */}
      {supplier && data && data.trips.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 border border-zinc-200 bg-white rounded-sm px-4 py-3">
          <div>
            <div className="text-lg font-bold">{data.supplier.name}
              {data.supplier.mobile && <span className="text-xs text-zinc-500 font-normal ml-2">· {data.supplier.mobile}</span>}
            </div>
            <div className="text-[11px] text-zinc-500">
              {data.company.name} · {data.period.start} → {data.period.end} · {data.totals.trips} trip(s)
            </div>
          </div>
          <div className="flex gap-2">
            <button data-testid="ss-download-pdf" onClick={downloadPdf} className="inline-flex items-center gap-1 px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100"><Download size={12} /> PDF</button>
            <button data-testid="ss-print" onClick={openPrint} className="inline-flex items-center gap-1 px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100"><Printer size={12} /> Print</button>
            <button data-testid="ss-wa" onClick={shareWa} className="inline-flex items-center gap-1 px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold bg-emerald-600 text-white rounded-sm hover:bg-emerald-700"><MessageCircle size={12} /> WhatsApp</button>
          </div>
        </div>
      )}

      {/* View */}
      {!supplier && (
        <div className="text-center text-sm text-zinc-500 py-12 border border-dashed border-zinc-300 rounded-sm">
          Select a supplier + month to generate the statement.
        </div>
      )}
      {supplier && isLoading && (
        <div className="text-center text-sm text-zinc-500 py-12">Loading…</div>
      )}
      {supplier && data && data.trips.length === 0 && !data.deep && (
        <div className="text-center text-sm text-zinc-500 py-12 border border-dashed border-zinc-300 rounded-sm">
          No supplier trips found for <b>{supplier}</b> in this period.
        </div>
      )}

      {supplier && data && data.deep && (
        /* Iter47 Phase 3 — Deep Monthly Statement Blocks (always shown when supplier is selected) */
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-2" data-testid="ss-deep-blocks">
          <div className="border-2 border-zinc-950 bg-white rounded-sm p-4">
            <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-1">Opening Balance</div>
            <div className="font-mono text-xl font-bold" data-testid="ss-opening-balance">
              {fmtCurrency(Math.abs(data.deep.opening_balance))} <span className={data.deep.opening_type === "advance" ? "text-emerald-700" : "text-rose-700"}>{data.deep.opening_type === "advance" ? "Cr" : "Dr"}</span>
            </div>
            <div className="text-[10px] text-zinc-500 mt-1">
              Source: {data.deep.opening_source === "carry_forward" ? "Carry-forward from previous period" : "Supplier master opening balance"}
            </div>
            <div className="mt-3 pt-3 border-t border-zinc-200 space-y-1 text-[11px]">
              <div className="flex justify-between"><span>Debits (Freight + Bonus)</span><span className="font-mono font-bold">{fmtCurrency(data.deep.movements_debit)}</span></div>
              <div className="flex justify-between"><span>Credits (Adv+Diesel+Ded+Pay)</span><span className="font-mono font-bold">-{fmtCurrency(data.deep.movements_credit)}</span></div>
              {data.deep.payments_out_total > 0 && (
                <div className="flex justify-between text-zinc-500 pl-3"><span>↳ Payments Made</span><span className="font-mono">-{fmtCurrency(data.deep.payments_out_total)}</span></div>
              )}
              {data.deep.payments_in_total > 0 && (
                <div className="flex justify-between text-zinc-500 pl-3"><span>↳ Receipts Back</span><span className="font-mono">+{fmtCurrency(data.deep.payments_in_total)}</span></div>
              )}
            </div>
          </div>
          <div className={`border-2 rounded-sm p-4 ${data.deep.closing_type === "advance" ? "border-emerald-500 bg-emerald-50" : "border-rose-500 bg-rose-50"}`}>
            <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-1">Closing Balance</div>
            <div className="font-mono text-3xl font-bold" data-testid="ss-closing-balance">
              {fmtCurrency(Math.abs(data.deep.closing_balance))} <span className={data.deep.closing_type === "advance" ? "text-emerald-700" : "text-rose-700"}>{data.deep.closing_type === "advance" ? "Cr" : "Dr"}</span>
            </div>
            <div className="text-[10px] text-zinc-500 mt-1">
              {data.deep.closing_type === "advance" ? "We are in advance — supplier owes us" : "Payable — we owe supplier"}
            </div>
            <div className="mt-3 pt-3 border-t border-zinc-200 text-[11px] text-zinc-600">
              <span className="italic">Formula:</span> Opening ({fmtCurrency(Math.abs(data.deep.opening_balance))} {data.deep.opening_type === "advance" ? "Cr" : "Dr"}) + Debits − Credits = Closing
            </div>
          </div>
        </div>
      )}

      {supplier && data && data.trips.length > 0 && (
        <>
          {/* Summary KPI grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <SsKpi label="Total Trips" v={data.totals.trips} data-testid="ss-kpi-trips" />
            <SsKpi label="Loading Qty (MT)" v={data.totals.load_tons.toFixed(3)} />
            <SsKpi label="Customer Freight" v={fmtCurrency(data.totals.customer_freight)} />
            <SsKpi label="Supplier Freight" v={fmtCurrency(data.totals.supplier_freight)} />
            <SsKpi label="Advance" v={fmtCurrency(data.totals.supplier_advance)} />
            <SsKpi label="Diesel Funded" v={fmtCurrency(data.totals.supplier_diesel)} />
            <SsKpi label="Cust. Diesel Adj" v={fmtCurrency(data.totals.customer_diesel)} />
            <SsKpi label="Halting" v={fmtCurrency(data.totals.halting)} />
            <SsKpi label="Shortage Ded." v={fmtCurrency(data.totals.supplier_shortage)} />
            <SsKpi label="Other Recov." v={fmtCurrency(data.totals.supplier_recovery)} />
            <SsKpi label="Other Income" v={fmtCurrency(data.totals.supplier_income)} />
            <SsKpi label="Net Payable" v={fmtCurrency(data.totals.net_payable)} highlight testid="ss-kpi-net-payable" />
          </div>

          {/* Trip-wise details table */}
          <div className="overflow-x-auto border border-zinc-200 rounded-sm bg-white">
            <table className="w-full text-xs">
              <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-wider">
                <tr>
                  <th className="text-left px-2 py-2">Date</th>
                  <th className="text-left px-2 py-2">LR / Vehicle</th>
                  <th className="text-left px-2 py-2">Customer</th>
                  <th className="text-left px-2 py-2">Route</th>
                  <th className="text-left px-2 py-2">Product</th>
                  <th className="text-right px-2 py-2">Load</th>
                  <th className="text-right px-2 py-2">Unload</th>
                  <th className="text-right px-2 py-2">S/E</th>
                  <th className="text-right px-2 py-2">KM</th>
                  <th className="text-right px-2 py-2">Rate</th>
                  <th className="text-right px-2 py-2">Freight</th>
                  <th className="text-right px-2 py-2">Adv</th>
                  <th className="text-right px-2 py-2">Diesel</th>
                  <th className="text-right px-2 py-2">Cust.Dsl</th>
                  <th className="text-right px-2 py-2">Halt</th>
                  <th className="text-right px-2 py-2">Ded/Rec</th>
                  <th className="text-right px-2 py-2">Net</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 font-mono">
                {data.trips.map((r) => (
                  <React.Fragment key={r.trip_id}>
                    <tr data-testid={`ss-row-${r.trip_id}`} className="hover:bg-amber-50">
                      <td className="px-2 py-1.5">{r.date}</td>
                      <td className="px-2 py-1.5">
                        <div className="font-bold">{r.lr_number || "—"}</div>
                        <div className="text-[10px] text-zinc-500">{r.vehicle_number}</div>
                      </td>
                      <td className="px-2 py-1.5">{r.customer_name}</td>
                      <td className="px-2 py-1.5 text-zinc-600">{r.from_location || "?"} → {r.to_location || "?"}</td>
                      <td className="px-2 py-1.5 text-zinc-600">{r.product || "—"}</td>
                      <td className="px-2 py-1.5 text-right">{r.loaded_qty.toFixed(2)}</td>
                      <td className="px-2 py-1.5 text-right">{r.unloaded_qty.toFixed(2)}</td>
                      <td className="px-2 py-1.5 text-right">
                        {r.shortage_qty > 0 && <span className="text-rose-700">-{r.shortage_qty.toFixed(3)}</span>}
                        {r.excess_qty > 0 && <span className="text-emerald-700">+{r.excess_qty.toFixed(3)}</span>}
                        {r.shortage_qty === 0 && r.excess_qty === 0 && "—"}
                      </td>
                      <td className="px-2 py-1.5 text-right">{r.distance_kms || "—"}</td>
                      <td className="px-2 py-1.5 text-right">{r.supplier_rate ? fmtCurrency(r.supplier_rate) : "—"}</td>
                      <td className="px-2 py-1.5 text-right">{fmtCurrency(r.supplier_freight)}</td>
                      <td className="px-2 py-1.5 text-right">{fmtCurrency(r.supplier_advance)}</td>
                      <td className="px-2 py-1.5 text-right">{fmtCurrency(r.supplier_diesel)}</td>
                      <td className="px-2 py-1.5 text-right">{fmtCurrency(r.customer_diesel)}</td>
                      <td className="px-2 py-1.5 text-right">
                        {r.halting_amount > 0
                          ? <span title={`${r.halting_days} days × ₹${r.halting_rate}`}>{fmtCurrency(r.halting_amount)}</span>
                          : "—"}
                      </td>
                      <td className="px-2 py-1.5 text-right">{fmtCurrency(r.supplier_shortage_deduction + r.supplier_other_recoveries)}</td>
                      <td className="px-2 py-1.5 text-right font-bold">{fmtCurrency(r.supplier_net_payable)}</td>
                    </tr>
                    {r.settlement_remarks && (
                      <tr className="bg-amber-50/50">
                        <td colSpan={17} className="px-3 py-1 text-[10px] italic text-zinc-600">↳ {r.settlement_remarks}</td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
                <tr className="bg-amber-50 font-bold border-t-2 border-zinc-950">
                  <td className="px-2 py-2">TOTAL</td>
                  <td className="px-2 py-2">{data.totals.trips} trip(s)</td>
                  <td className="px-2 py-2"></td>
                  <td className="px-2 py-2"></td>
                  <td className="px-2 py-2"></td>
                  <td className="px-2 py-2 text-right">{data.totals.load_tons.toFixed(2)}</td>
                  <td className="px-2 py-2 text-right">{data.totals.unload_tons.toFixed(2)}</td>
                  <td className="px-2 py-2 text-right">—</td>
                  <td className="px-2 py-2 text-right">{data.totals.distance.toFixed(0)}</td>
                  <td className="px-2 py-2 text-right">—</td>
                  <td className="px-2 py-2 text-right">{fmtCurrency(data.totals.supplier_freight)}</td>
                  <td className="px-2 py-2 text-right">{fmtCurrency(data.totals.supplier_advance)}</td>
                  <td className="px-2 py-2 text-right">{fmtCurrency(data.totals.supplier_diesel)}</td>
                  <td className="px-2 py-2 text-right">{fmtCurrency(data.totals.customer_diesel)}</td>
                  <td className="px-2 py-2 text-right">{fmtCurrency(data.totals.halting)}</td>
                  <td className="px-2 py-2 text-right">{fmtCurrency(data.totals.supplier_shortage + data.totals.supplier_recovery)}</td>
                  <td className="px-2 py-2 text-right">{fmtCurrency(data.totals.net_payable)}</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Closing summary block */}
          <div className="border border-amber-300 bg-amber-50/50 rounded-sm p-4">
            <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-2">Closing Summary</div>
            <div className="font-mono text-sm space-y-1 max-w-lg">
              <ClosingRow k="Total Supplier Freight" v={data.totals.supplier_freight} />
              <ClosingRow k="Less: Advance" v={-data.totals.supplier_advance} />
              <ClosingRow k="Less: Diesel Funded" v={-data.totals.supplier_diesel} />
              <ClosingRow k="Less: Customer Diesel Adjustment" v={-data.totals.customer_diesel} />
              <ClosingRow k="Less: Shortage Deducted" v={-data.totals.supplier_shortage} />
              <ClosingRow k="Less: Other Recoveries" v={-data.totals.supplier_recovery} />
              <ClosingRow k="Add: Bonus / Other Income" v={data.totals.supplier_income} />
              <ClosingRow k="Add: Halting Charges" v={data.totals.halting} />
              <div className="flex justify-between border-t-2 border-zinc-950 mt-2 pt-2 font-bold text-base">
                <span>Net Payable to Supplier</span>
                <span data-testid="ss-closing-net">{fmtCurrency(data.totals.net_payable)}</span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function SsKpi({ label, v, highlight = false, testid }) {
  return (
    <div className={`border rounded-sm p-3 ${highlight ? "border-amber-400 bg-amber-50" : "border-zinc-200 bg-white"}`} data-testid={testid}>
      <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">{label}</div>
      <div className="mt-1 font-mono font-bold text-sm">{v}</div>
    </div>
  );
}

function ClosingRow({ k, v }) {
  const neg = v < 0;
  return (
    <div className="flex justify-between">
      <span className="text-zinc-600">{k}</span>
      <span className={neg ? "text-rose-700" : ""}>{neg ? `(${fmtCurrency(-v)})` : fmtCurrency(v)}</span>
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
                <th className="text-right px-4 py-2">Advance</th>
                <th className="text-right px-4 py-2">Other Recov.</th>
                <th className="text-right px-4 py-2">Net Payable</th>
                <th className="text-right px-4 py-2">Profit</th>
                <th className="text-right px-4 py-2">Margin %</th>
                <th className="text-right px-4 py-2">Statement</th>
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
                  <td className="px-4 py-2 text-right">{fmtCurrency(s.supplier_advance || 0)}</td>
                  <td className="px-4 py-2 text-right">{fmtCurrency(s.supplier_other_recoveries || 0)}</td>
                  <td className="px-4 py-2 text-right font-semibold">{fmtCurrency(s.net_payable || 0)}</td>
                  <td className={`px-4 py-2 text-right font-bold ${s.profit >= 0 ? "text-emerald-800" : "text-rose-800"}`}>{fmtCurrency(s.profit)}</td>
                  <td className="px-4 py-2 text-right">{s.margin_pct}%</td>
                  <td className="px-4 py-2 text-right">
                    <div className="inline-flex items-center gap-1">
                      <SupplierStatementBtn name={s.supplier_name} start={start} end={end} />
                      <SupplierStatementWABtn name={s.supplier_name} start={start} end={end} />
                    </div>
                  </td>
                </tr>
              ))}
              {(data.suppliers || []).length === 0 && (
                <tr><td colSpan={11} className="px-4 py-10 text-center text-zinc-400 text-sm">No supplier trips in this period.</td></tr>
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
                  <td className="px-4 py-2 text-right font-bold">{fmtCurrency(data.totals.supplier_advance || 0)}</td>
                  <td className="px-4 py-2 text-right font-bold">{fmtCurrency(data.totals.supplier_other_recoveries || 0)}</td>
                  <td className="px-4 py-2 text-right font-bold">{fmtCurrency(data.totals.net_payable || 0)}</td>
                  <td className="px-4 py-2 text-right font-bold text-emerald-800">{fmtCurrency(data.totals.profit)}</td>
                  <td className="px-4 py-2 text-right"></td>
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

/* ------------------ Supplier Statement Download Button ------------------ */
function SupplierStatementBtn({ name, start, end }) {
  const [loading, setLoading] = React.useState(false);
  const download = async () => {
    setLoading(true);
    try {
      const resp = await api.get("/reports/supplier-statement.pdf", {
        params: { supplier_name: name, start, end },
        responseType: "blob",
      });
      const url = URL.createObjectURL(new Blob([resp.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `supplier_statement_${name.replace(/\s+/g, "_")}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      const msg = detail || "Statement download failed";
      try { const { toast } = await import("sonner"); toast.error(msg); } catch { alert(msg); }
    } finally {
      setLoading(false);
    }
  };
  return (
    <button
      type="button"
      data-testid={`supplier-statement-btn-${name.toLowerCase().replace(/\s+/g, "-")}`}
      onClick={download}
      disabled={loading}
      className="inline-flex items-center gap-1 px-2 py-1 text-[10px] uppercase tracking-wider font-bold border border-zinc-300 bg-white text-zinc-800 rounded-sm hover:bg-zinc-100 disabled:opacity-50"
      title={`Download PDF statement for ${name}`}
    >
      <Download size={11} /> PDF
    </button>
  );
}

/* ------------------ Supplier Statement WhatsApp Share Button ------------------ */
function SupplierStatementWABtn({ name, start, end }) {
  const [loading, setLoading] = React.useState(false);
  const share = async () => {
    setLoading(true);
    try {
      const { data } = await api.post("/reports/supplier-statement/share", null, {
        params: { supplier_name: name, start, end },
      });
      // Open WhatsApp deeplink
      window.open(data.whatsapp_url, "_blank", "noopener");
      const { toast } = await import("sonner");
      if (!data.supplier_mobile_available) {
        toast.info(`No saved mobile for ${name} — WhatsApp opened without a recipient. Add supplier mobile in Vehicles.`);
      } else {
        toast.success(`WhatsApp ready — ${data.supplier_mobile}`);
      }
    } catch (e) {
      const detail = e?.response?.data?.detail;
      const { toast } = await import("sonner");
      toast.error(detail || "WhatsApp share failed");
    } finally {
      setLoading(false);
    }
  };
  return (
    <button
      type="button"
      data-testid={`supplier-statement-wa-btn-${name.toLowerCase().replace(/\s+/g, "-")}`}
      onClick={share}
      disabled={loading}
      className="inline-flex items-center gap-1 px-2 py-1 text-[10px] uppercase tracking-wider font-bold border border-emerald-300 bg-emerald-50 text-emerald-800 rounded-sm hover:bg-emerald-100 disabled:opacity-50"
      title={`Share ${name} statement via WhatsApp`}
    >
      <MessageCircle size={11} /> WA
    </button>
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

          {/* Iter133 L2 · totals_by_type breakdown cards */}
          {data.totals_by_type && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 px-5 py-3 border-b border-zinc-200 bg-zinc-50/60" data-testid="ledger-totals-by-type">
              <div className="border border-zinc-200 bg-white rounded-sm p-2" data-testid="tbt-invoice">
                <div className="text-[9px] uppercase tracking-wider font-bold text-zinc-500">Invoiced</div>
                <div className="font-mono text-sm font-bold text-zinc-900">{fmtCurrency(data.totals_by_type.invoice || 0)}</div>
              </div>
              <div className="border border-blue-200 bg-blue-50 rounded-sm p-2" data-testid="tbt-debit-note">
                <div className="text-[9px] uppercase tracking-wider font-bold text-blue-700">Debit Notes</div>
                <div className="font-mono text-sm font-bold text-blue-900">{fmtCurrency(data.totals_by_type.debit_note || 0)}</div>
              </div>
              <div className="border border-red-200 bg-red-50 rounded-sm p-2" data-testid="tbt-credit-note">
                <div className="text-[9px] uppercase tracking-wider font-bold text-red-700">Credit Notes</div>
                <div className="font-mono text-sm font-bold text-red-900">{fmtCurrency(data.totals_by_type.credit_note || 0)}</div>
              </div>
              <div className="border border-emerald-200 bg-emerald-50 rounded-sm p-2" data-testid="tbt-payment">
                <div className="text-[9px] uppercase tracking-wider font-bold text-emerald-700">Payments</div>
                <div className="font-mono text-sm font-bold text-emerald-900">{fmtCurrency(data.totals_by_type.payment || 0)}</div>
              </div>
            </div>
          )}

          {/* Iter133 L2 · Adjustments summary strip (only when CN or DN present) */}
          {data.totals_by_type && ((data.totals_by_type.credit_note || 0) > 0 || (data.totals_by_type.debit_note || 0) > 0) && (
            <div className="px-5 py-2 text-xs text-zinc-700 bg-amber-50 border-b border-amber-200" data-testid="ledger-adjustments-strip">
              <span className="font-bold uppercase tracking-wider text-zinc-600">Adjustments this period:</span>{" "}
              {(data.totals_by_type.credit_note || 0) > 0 && (
                <span className="text-red-700 font-mono font-semibold" data-testid="ledger-adj-cn">
                  − {fmtCurrency(data.totals_by_type.credit_note)} (Credit Notes)
                </span>
              )}
              {(data.totals_by_type.credit_note || 0) > 0 && (data.totals_by_type.debit_note || 0) > 0 && (
                <span className="mx-1 text-zinc-400">·</span>
              )}
              {(data.totals_by_type.debit_note || 0) > 0 && (
                <span className="text-blue-700 font-mono font-semibold" data-testid="ledger-adj-dn">
                  + {fmtCurrency(data.totals_by_type.debit_note)} (Debit Notes)
                </span>
              )}
            </div>
          )}

          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="text-left px-4 py-2">Date</th>
                <th className="text-left px-4 py-2">Ref</th>
                <th className="text-left px-4 py-2">Type</th>
                <th className="text-left px-4 py-2">Particulars</th>
                <th className="text-right px-4 py-2">Debit</th>
                <th className="text-right px-4 py-2">Credit</th>
                <th className="text-right px-4 py-2">Balance</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              <tr className="bg-zinc-50 border-t border-zinc-100">
                <td colSpan={6} className="px-4 py-2 text-xs font-bold">Opening Balance</td>
                <td className="px-4 py-2 text-right font-bold">{fmtCurrency(data.opening_balance)}</td>
              </tr>
              {data.entries.map((e, i) => {
                const typePill =
                  e.type === "invoice"     ? { cls: "bg-purple-100 text-purple-800 border-purple-300", label: "INV" } :
                  e.type === "payment"     ? { cls: "bg-emerald-100 text-emerald-800 border-emerald-300", label: "PMT" } :
                  e.type === "credit_note" ? { cls: "bg-red-100 text-red-800 border-red-300", label: "CN" } :
                  e.type === "debit_note"  ? { cls: "bg-blue-100 text-blue-800 border-blue-300", label: "DN" } :
                                             { cls: "bg-zinc-100 text-zinc-700 border-zinc-300", label: "—" };
                const rowTint =
                  e.type === "credit_note" ? "bg-red-50/40 hover:bg-red-50" :
                  e.type === "debit_note"  ? "bg-blue-50/40 hover:bg-blue-50" :
                                             "";
                return (
                  <tr key={i} className={`border-t border-zinc-100 ${rowTint}`} data-testid={`ledger-row-${e.type}-${i}`}>
                    <td className="px-4 py-1.5 text-xs">{fmtDate(e.date)}</td>
                    <td className="px-4 py-1.5 text-xs font-semibold">{e.reference}</td>
                    <td className="px-4 py-1.5"><span className={`inline-block text-[9px] font-bold px-1.5 py-0.5 border rounded-sm ${typePill.cls}`}>{typePill.label}</span></td>
                    <td className="px-4 py-1.5 text-xs">{e.particulars}</td>
                    <td className="px-4 py-1.5 text-right">{e.debit ? fmtCurrency(e.debit) : ""}</td>
                    <td className="px-4 py-1.5 text-right text-emerald-700">{e.credit ? fmtCurrency(e.credit) : ""}</td>
                    <td className="px-4 py-1.5 text-right font-semibold">{fmtCurrency(e.balance)}</td>
                  </tr>
                );
              })}
              <tr className="bg-amber-50 border-t border-zinc-300">
                <td colSpan={4} className="px-4 py-2 font-bold">TOTAL</td>
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

/* ------------------ Iter124 · LR Register ------------------ */
function LRRegisterReport() {
  const today = new Date();
  const _fmt = (d) => d.toISOString().slice(0, 10);
  const monthStart = _fmt(new Date(today.getFullYear(), today.getMonth(), 1));
  const monthEnd = _fmt(today);
  const [start, setStart] = useState(monthStart);
  const [end, setEnd] = useState(monthEnd);
  const [customerId, setCustomerId] = useState("");
  const [driver, setDriver] = useState("");
  const [invoiceStatus, setInvoiceStatus] = useState("all");
  const [q, setQ] = useState("");
  const [full, setFull] = useState(false);
  const [activeCol, setActiveCol] = useState(null);   // Iter124b · column highlight
  const [bulkZipOpen, setBulkZipOpen] = useState(false);
  const [bulkZipBusy, setBulkZipBusy] = useState(false);
  const [bulkZipReport, setBulkZipReport] = useState(null);
  const tableWrapRef = useRef(null);

  // Clear column highlight when the user clicks outside the table.
  useEffect(() => {
    if (activeCol == null) return;
    const onDocClick = (e) => {
      if (tableWrapRef.current && !tableWrapRef.current.contains(e.target)) {
        setActiveCol(null);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [activeCol]);

  const { data: customersResp } = useQuery({
    queryKey: ["customers-list-lr-reg"],
    queryFn: async () => (await api.get("/customers", { params: { limit: 500 } })).data,
  });
  const customers = Array.isArray(customersResp) ? customersResp : (customersResp?.items || []);

  const params = { start, end };
  if (customerId) params.customer_id = customerId;
  if (driver) params.driver = driver;
  if (invoiceStatus && invoiceStatus !== "all") params.invoice_status = invoiceStatus;
  if (q) params.q = q;

  const { data, isFetching, refetch } = useQuery({
    queryKey: ["lr-register", start, end, customerId, driver, invoiceStatus, q],
    queryFn: async () => (await api.get("/reports/lr-register", { params })).data,
    keepPreviousData: true,
  });

  const setThisMonth = () => {
    setStart(_fmt(new Date(today.getFullYear(), today.getMonth(), 1))); setEnd(_fmt(today));
  };
  const setLastMonth = () => {
    const y = today.getMonth() === 0 ? today.getFullYear() - 1 : today.getFullYear();
    const m = today.getMonth() === 0 ? 11 : today.getMonth() - 1;
    setStart(_fmt(new Date(y, m, 1))); setEnd(_fmt(new Date(y, m + 1, 0)));
  };

  const _download = async (ext) => {
    const resp = await api.get(`/reports/lr-register.${ext}`, {
      params, responseType: "blob", timeout: 90_000,
    });
    const mime = ext === "xlsx"
      ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      : "application/pdf";
    const url = URL.createObjectURL(new Blob([resp.data], { type: mime }));
    const a = document.createElement("a"); a.href = url;
    const dispo = resp.headers?.["content-disposition"] || "";
    const m = /filename="([^"]+)"/.exec(dispo);
    a.download = m ? m[1] : `LR_Register.${ext}`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
    const { toast } = await import("sonner");
    toast.success(`${ext.toUpperCase()} downloaded`);
  };

  const rows = data?.rows || [];
  const tot = data?.totals || {};
  const co = data?.company || {};

  return (
    <div className="space-y-4" data-testid="lr-register-tab">
      <div className="border border-zinc-200 bg-white rounded-sm p-4 grid grid-cols-1 md:grid-cols-6 gap-3">
        <FieldWrap label="Start">
          <input data-testid="lrreg-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className={ic} />
          <div className="mt-1 text-[10px] uppercase tracking-wider font-mono text-zinc-500" data-testid="lrreg-start-display">{fmtDate(start) || "—"}</div>
        </FieldWrap>
        <FieldWrap label="End">
          <input data-testid="lrreg-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className={ic} />
          <div className="mt-1 text-[10px] uppercase tracking-wider font-mono text-zinc-500" data-testid="lrreg-end-display">{fmtDate(end) || "—"}</div>
        </FieldWrap>
        <FieldWrap label="Customer">
          <select data-testid="lrreg-customer" value={customerId} onChange={(e) => setCustomerId(e.target.value)} className={ic}>
            <option value="">All</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </FieldWrap>
        <FieldWrap label="Driver contains">
          <input data-testid="lrreg-driver" type="text" value={driver} onChange={(e) => setDriver(e.target.value)} className={ic} placeholder="e.g. Ravi" />
        </FieldWrap>
        <FieldWrap label="Invoice Status">
          <select data-testid="lrreg-invstatus" value={invoiceStatus} onChange={(e) => setInvoiceStatus(e.target.value)} className={ic}>
            <option value="all">All</option>
            <option value="un_invoiced">Un-invoiced</option>
            <option value="unpaid">Unpaid</option>
            <option value="partially_paid">Partially paid</option>
            <option value="paid">Paid</option>
          </select>
        </FieldWrap>
        <FieldWrap label="Search">
          <input data-testid="lrreg-q" type="text" value={q} onChange={(e) => setQ(e.target.value)} className={ic} placeholder="LR / vehicle / driver / ref" />
        </FieldWrap>
        <div className="md:col-span-6 flex flex-wrap gap-2 pt-1">
          <button data-testid="lrreg-this-month" onClick={setThisMonth} className="px-3 py-1.5 text-[11px] uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-100">This month</button>
          <button data-testid="lrreg-last-month" onClick={setLastMonth} className="px-3 py-1.5 text-[11px] uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-100">Last month</button>
          <label className="inline-flex items-center gap-2 px-3 py-1.5 text-[11px] uppercase tracking-wider border border-zinc-300 rounded-sm">
            <input data-testid="lrreg-full-toggle" type="checkbox" checked={full} onChange={(e) => setFull(e.target.checked)} className="w-3 h-3" />
            Full view
          </label>
          <div className="grow" />
          <button data-testid="lrreg-refresh" onClick={() => refetch()} disabled={isFetching} className="px-3 py-1.5 text-[11px] uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
            {isFetching ? "Loading…" : "Refresh"}
          </button>
          <button data-testid="lr-register-xlsx" onClick={() => _download("xlsx")} className="inline-flex items-center gap-2 px-3 py-1.5 text-[11px] uppercase tracking-wider border border-emerald-600 text-emerald-700 rounded-sm hover:bg-emerald-600 hover:text-white">
            <Download size={12} /> Excel
          </button>
          <button data-testid="lr-register-pdf" onClick={() => _download("pdf")} className="inline-flex items-center gap-2 px-3 py-1.5 text-[11px] uppercase tracking-wider border border-rose-600 text-rose-700 rounded-sm hover:bg-rose-600 hover:text-white">
            <Printer size={12} /> PDF
          </button>
          <button data-testid="lrreg-all-copies-zip" onClick={() => setBulkZipOpen(true)} className="inline-flex items-center gap-2 px-3 py-1.5 text-[11px] uppercase tracking-wider border border-indigo-700 text-indigo-800 rounded-sm hover:bg-indigo-700 hover:text-white">
            <Archive size={12} /> All Copies ZIP
          </button>
        </div>
      </div>

      {/* Iter124b — Always-visible period + active-filter chip banner */}
      <div className="border border-zinc-200 bg-white rounded-sm px-4 py-3 flex flex-wrap items-center gap-3 text-xs">
        {co?.name ? (
          <div><span className="font-bold text-zinc-950">{co.name}</span> · GSTIN {co.gstin || "—"} · Code <span className="font-mono">{co.company_code}</span></div>
        ) : (
          <div className="text-zinc-500 italic">Loading company…</div>
        )}
        <div className="inline-flex items-center gap-1 px-2 py-0.5 bg-zinc-100 border border-zinc-200 rounded-sm">
          <span className="text-[10px] uppercase tracking-wider text-zinc-500">Period</span>
          <span className="font-mono text-zinc-900">{fmtDate(start)}</span>
          <span className="text-zinc-400">→</span>
          <span className="font-mono text-zinc-900">{fmtDate(end)}</span>
        </div>
        {customerId && (
          <div className="inline-flex items-center gap-1 px-2 py-0.5 bg-indigo-50 border border-indigo-200 rounded-sm">
            <span className="text-[10px] uppercase tracking-wider text-indigo-500">Customer</span>
            <span className="text-indigo-900">{customers.find(c => c.id === customerId)?.name || customerId}</span>
            <button data-testid="chip-clear-customer" onClick={() => setCustomerId("")} className="ml-1 text-indigo-400 hover:text-indigo-900">×</button>
          </div>
        )}
        {driver && (
          <div className="inline-flex items-center gap-1 px-2 py-0.5 bg-indigo-50 border border-indigo-200 rounded-sm">
            <span className="text-[10px] uppercase tracking-wider text-indigo-500">Driver</span>
            <span className="text-indigo-900">{driver}</span>
            <button data-testid="chip-clear-driver" onClick={() => setDriver("")} className="ml-1 text-indigo-400 hover:text-indigo-900">×</button>
          </div>
        )}
        {invoiceStatus !== "all" && (
          <div className="inline-flex items-center gap-1 px-2 py-0.5 bg-indigo-50 border border-indigo-200 rounded-sm">
            <span className="text-[10px] uppercase tracking-wider text-indigo-500">Invoice</span>
            <span className="text-indigo-900">{invoiceStatus.replace("_", " ")}</span>
            <button data-testid="chip-clear-invoice-status" onClick={() => setInvoiceStatus("all")} className="ml-1 text-indigo-400 hover:text-indigo-900">×</button>
          </div>
        )}
        {q && (
          <div className="inline-flex items-center gap-1 px-2 py-0.5 bg-indigo-50 border border-indigo-200 rounded-sm">
            <span className="text-[10px] uppercase tracking-wider text-indigo-500">Search</span>
            <span className="text-indigo-900">"{q}"</span>
            <button data-testid="chip-clear-q" onClick={() => setQ("")} className="ml-1 text-indigo-400 hover:text-indigo-900">×</button>
          </div>
        )}
        {(customerId || driver || invoiceStatus !== "all" || q) && (
          <button data-testid="lrreg-clear-filters" onClick={() => { setCustomerId(""); setDriver(""); setInvoiceStatus("all"); setQ(""); }} className="text-[10px] uppercase tracking-wider text-rose-600 hover:text-rose-800">
            Clear filters
          </button>
        )}
        <div className="grow" />
        <div className="text-zinc-500">
          {isFetching ? <span className="italic">Loading…</span> :
            <>Showing <span className="font-mono text-zinc-900">{tot.count || 0}</span> LR{tot.count === 1 ? "" : "s"}</>}
        </div>
      </div>

      <div ref={tableWrapRef} className="border border-zinc-200 bg-white rounded-sm overflow-auto max-h-[70vh]" data-testid="lr-register-table" onClick={(e) => {
        const cell = e.target.closest("[data-col]");
        if (cell) setActiveCol(cell.getAttribute("data-col"));
      }}>
        <table className="text-xs" style={{ borderCollapse: "separate", borderSpacing: 0, minWidth: "2100px" }}>
          <thead className="bg-zinc-950 text-white sticky top-0 z-10">
            <tr>
              {[
                { k: "lr_number",    label: "LR #",         align: "text-left",  w: 110, nowrap: true },
                { k: "lr_date",      label: "Date",         align: "text-left",  w: 108, nowrap: true },
                { k: "cust_ref",     label: "Cust Ref #",   align: "text-left",  w: 120, nowrap: true },
                { k: "from",         label: "From",         align: "text-left",  w: 130 },
                { k: "consignee",    label: "Consignee",    align: "text-left",  w: 200 },
                { k: "ship_to",      label: "Ship-To",      align: "text-left",  w: 170 },
                { k: "vehicle",      label: "Vehicle",      align: "text-left",  w: 120, nowrap: true },
                { k: "driver",       label: "Driver",       align: "text-left",  w: 140 },
                { k: "product",      label: "Product",      align: "text-left",  w: 170 },
                { k: "loaded",       label: "Load MT",      align: "text-right", w: 80,  nowrap: true },
                { k: "unloaded",     label: "Unload MT",    align: "text-right", w: 84,  nowrap: true },
                { k: "shortage",     label: "Shortage MT",  align: "text-right", w: 96,  nowrap: true },
                { k: "allowance",    label: "Allow MT",     align: "text-right", w: 80,  nowrap: true },
                { k: "net_shortage", label: "Net MT",       align: "text-right", w: 80,  nowrap: true },
                ...(full ? [{ k: "shortage_amount", label: "Shortage ₹", align: "text-right", w: 105, nowrap: true }] : []),
                { k: "freight",        label: "Freight ₹",    align: "text-right", w: 105, nowrap: true },
                { k: "invoice_number", label: "Invoice #",    align: "text-left",  w: 140, nowrap: true },
                { k: "invoice_status", label: "Inv Status",   align: "text-left",  w: 120, nowrap: true },
                { k: "lr_copies",      label: "LR Copies",    align: "text-left",  w: 118, nowrap: true },
              ].map((h) => (
                <th key={h.k}
                    data-col={h.k}
                    data-testid={`lrreg-th-${h.k}`}
                    style={{ minWidth: h.w, width: h.w }}
                    className={`px-2 py-2 cursor-pointer select-none ${h.align} ${activeCol === h.k ? "bg-indigo-600 ring-1 ring-indigo-300" : ""}`}>
                  {h.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono">
            {rows.length === 0 && !isFetching && (
              <tr><td colSpan={full ? 19 : 18} className="text-center italic text-zinc-500 py-8">
                No LRs issued in this period. Try widening the date range or clearing filters.
              </td></tr>
            )}
            {rows.length === 0 && isFetching && (
              <tr><td colSpan={full ? 19 : 18} className="text-center italic text-zinc-400 py-8">
                Loading LR Register…
              </td></tr>
            )}
            {rows.map((r, i) => {
              const zebra = i % 2 === 0 ? "bg-zinc-50" : "";
              const hl = (k) => activeCol === k ? "bg-indigo-50 ring-1 ring-indigo-200" : "";
              const NW = "whitespace-nowrap";
              return (
              <tr key={r.trip_id} className={zebra} data-testid={`lrreg-row-${r.trip_id}`}>
                <td data-col="lr_number" className={`px-2 py-1 font-bold text-indigo-800 ${NW} ${hl("lr_number")}`}>{r.lr_number}</td>
                <td data-col="lr_date" className={`px-2 py-1 ${NW} ${hl("lr_date")}`}>{fmtDate(r.lr_date)}</td>
                <td data-col="cust_ref" className={`px-2 py-1 ${NW} ${hl("cust_ref")}`}>{r.customer_reference_number || "—"}</td>
                <td data-col="from" className={`px-2 py-1 break-words ${hl("from")}`}>{r.from_location}</td>
                <td data-col="consignee" className={`px-2 py-1 break-words ${hl("consignee")}`}>{r.customer_name}</td>
                <td data-col="ship_to" className={`px-2 py-1 break-words ${hl("ship_to")}`}>{r.ship_to}</td>
                <td data-col="vehicle" className={`px-2 py-1 ${NW} ${hl("vehicle")}`}>{r.vehicle_number}</td>
                <td data-col="driver" className={`px-2 py-1 break-words ${hl("driver")}`}>{r.driver_name || "—"}</td>
                <td data-col="product" className={`px-2 py-1 break-words ${hl("product")}`}>{r.product || "—"}</td>
                <td data-col="loaded" className={`px-2 py-1 text-right ${NW} ${hl("loaded")}`}>{Number(r.loaded_qty).toFixed(2)}</td>
                <td data-col="unloaded" className={`px-2 py-1 text-right ${NW} ${hl("unloaded")}`}>{Number(r.unloaded_qty).toFixed(2)}</td>
                <td data-col="shortage" className={`px-2 py-1 text-right ${NW} ${hl("shortage")}`}>{Number(r.shortage_qty).toFixed(3)}</td>
                <td data-col="allowance" className={`px-2 py-1 text-right ${NW} ${hl("allowance")}`}>{Number(r.allowance_qty).toFixed(3)}</td>
                <td data-col="net_shortage" className={`px-2 py-1 text-right ${NW} ${hl("net_shortage")}`}>{Number(r.net_shortage_qty).toFixed(3)}</td>
                {full && <td data-col="shortage_amount" className={`px-2 py-1 text-right ${NW} ${hl("shortage_amount")}`}>{fmtCurrency(r.shortage_amount)}</td>}
                <td data-col="freight" className={`px-2 py-1 text-right ${NW} ${hl("freight")}`}>{fmtCurrency(r.freight_amount)}</td>
                <td data-col="invoice_number" className={`px-2 py-1 ${NW} ${hl("invoice_number")}`}>{r.invoice_number || "—"}</td>
                <td data-col="invoice_status" className={`px-2 py-1 ${NW} ${hl("invoice_status")}`}>
                  <span className={`px-1.5 py-0.5 rounded-sm text-[10px] uppercase tracking-wider ${
                    r.invoice_status === "paid" ? "bg-emerald-100 text-emerald-800"
                    : r.invoice_status === "partially_paid" ? "bg-amber-100 text-amber-800"
                    : r.invoice_status === "unpaid" ? "bg-rose-100 text-rose-800"
                    : "bg-zinc-100 text-zinc-600"
                  }`}>{r.invoice_status.replace("_", " ")}</span>
                </td>
                <td data-col="lr_copies" className={`px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-600 ${NW} ${hl("lr_copies")}`}>{r.lr_copies}</td>
              </tr>
            );})}
          </tbody>
          {rows.length > 0 && (
            <tfoot className="bg-amber-50 border-t-2 border-zinc-950 font-bold">
              <tr>
                <td className="px-2 py-2" colSpan={9}>TOTAL · {tot.count} LR{tot.count === 1 ? "" : "s"}</td>
                <td className="px-2 py-2 text-right">{Number(tot.loaded || 0).toFixed(2)}</td>
                <td className="px-2 py-2 text-right">{Number(tot.unloaded || 0).toFixed(2)}</td>
                <td className="px-2 py-2 text-right">{Number(tot.shortage || 0).toFixed(3)}</td>
                <td className="px-2 py-2 text-right">{Number(tot.allowance || 0).toFixed(3)}</td>
                <td className="px-2 py-2 text-right">{Number(tot.net_shortage || 0).toFixed(3)}</td>
                {full && <td className="px-2 py-2 text-right">{fmtCurrency(tot.shortage_amount || 0)}</td>}
                <td className="px-2 py-2 text-right">{fmtCurrency(tot.freight || 0)}</td>
                <td colSpan={3}></td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
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

/* ------------------ GSTR-1 §9B (CN/DN) — Iter132c C3.3 ------------------ */
// Pure projection of the LOCKED C3.1 canonical JSON (GET /api/reports/gstr1-9b).
// XLSX/PDF are pass-through downloads (C3.2 endpoints). Zero client calculation.
function GSTR19BReport() {
  const cdnEnabled = useCdnEnabled();
  const now = new Date();
  const defaultMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [month, setMonth] = useState(defaultMonth);
  const [section, setSection] = useState("cdnr");
  const [showJson, setShowJson] = useState(false);

  const { data, refetch, isFetching, isError, error } = useQuery({
    queryKey: ["gstr1-9b", month],
    queryFn: async () => (await api.get("/reports/gstr1-9b", { params: { month } })).data,
    enabled: Boolean(month) && cdnEnabled,
    staleTime: 60_000,
    retry: false,
  });

  if (!cdnEnabled) return <Navigate to="/reports/ledger" replace />;

  const reconMismatch =
    isError && error?.response?.status === 500 &&
    error?.response?.data?.detail?.error === "gstr1_9b_reconciliation_mismatch";
  const deltas = reconMismatch ? (error.response.data.detail.deltas || []) : [];
  const recon = data?.reconciliation;
  const reconciled = recon?.reconciled === true;
  const downloadsDisabled = isFetching || !data || !reconciled;

  const doDownload = async (kind) => {
    const t = toast.loading(`Preparing ${kind.toUpperCase()}…`);
    try {
      const resp = await api.get(`/reports/gstr1-9b.${kind}`, {
        params: { month }, responseType: "blob",
      });
      const cd = resp.headers?.["content-disposition"] || "";
      const m = cd.match(/filename="?([^"]+)"?/);
      const fname = m ? m[1] : `gstr1_9b_${month}.${kind}`;
      const url = URL.createObjectURL(resp.data);
      const a = document.createElement("a");
      a.href = url; a.download = fname; a.click();
      URL.revokeObjectURL(url);
      toast.success(`${kind.toUpperCase()} downloaded`, { id: t });
    } catch (e) {
      toast.error(`${kind.toUpperCase()} download failed`, { id: t });
    }
  };

  const doJsonDownload = () => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `gstr1_9b_${month}.json`; a.click();
    URL.revokeObjectURL(url);
  };

  const totals = data?.totals || {};
  const cdnrRows = (data?.cdnr || []).flatMap((g) =>
    (g.nt || []).map((nt) => ({ ...nt, _ctin: g.ctin, _customer_name: nt.customer_name || g.customer_name }))
  );
  const cdnurRows = data?.cdnur || [];
  const b2csRows = data?.b2cs_adjustments || [];
  const commercialRows = data?.commercial_notes || [];
  const cancelledRows = data?.cancelled_after_export || [];
  const warnings = data?.warnings || [];
  const isEmpty = data && (data.note_count || 0) === 0 && cancelledRows.length === 0;

  return (
    <div className="space-y-4" data-testid="gstr1-9b-tab">
      {/* Filter bar */}
      <div className="border border-zinc-200 bg-white rounded-sm p-4 grid grid-cols-1 md:grid-cols-4 gap-3">
        <FieldWrap label="Month">
          <input data-testid="g9b-month" type="month" value={month}
            onChange={(e) => setMonth(e.target.value)} className={ic} />
        </FieldWrap>
        <div className="flex items-end">
          <button data-testid="g9b-refresh-btn" onClick={() => refetch()} disabled={isFetching}
            className="w-full px-3 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
            {isFetching ? "Refreshing…" : "Refresh"}
          </button>
        </div>
        <div className="flex items-end gap-2 md:col-span-2 justify-end">
          <button data-testid="g9b-download-pdf-btn" onClick={() => doDownload("pdf")} disabled={downloadsDisabled}
            title="Download human-readable statutory PDF"
            className="px-3 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-40 inline-flex items-center gap-2">
            <Download size={14} /> Download PDF
          </button>
          <button data-testid="g9b-download-xlsx-btn" onClick={() => doDownload("xlsx")} disabled={downloadsDisabled}
            title="Download 6-sheet accountant workbook"
            className="px-3 py-2 text-xs uppercase tracking-wider bg-emerald-700 text-white rounded-sm hover:bg-emerald-800 disabled:opacity-40 inline-flex items-center gap-2">
            <Download size={14} /> Download XLSX
          </button>
          <button data-testid="g9b-view-json-btn" onClick={() => setShowJson((v) => !v)} disabled={!data}
            title="Technical JSON view"
            className="px-3 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-100 disabled:opacity-40 inline-flex items-center gap-1">
            View JSON <ChevronDown size={12} />
          </button>
        </div>
      </div>

      {/* Loading */}
      {isFetching && !data && (
        <div data-testid="g9b-loading" className="border border-zinc-200 bg-white rounded-sm p-6 text-sm text-zinc-500">
          Loading GSTR-1 §9B report…
        </div>
      )}

      {/* Recon mismatch */}
      {reconMismatch && (
        <div data-testid="g9b-recon-mismatch" className="border border-red-300 bg-red-50 rounded-sm p-4">
          <div className="flex items-center gap-2 text-red-700 font-bold text-sm">
            <AlertTriangle size={16} /> RECONCILIATION MISMATCH — downloads disabled
          </div>
          <div className="mt-2 text-xs text-red-800 space-y-1 font-mono">
            {deltas.map((d, i) => (
              <div key={i}>• {d.invariant}: endpoint={String(d.endpoint)} · ground_truth={String(d.ground_truth)} · delta={String(d.delta)}</div>
            ))}
          </div>
        </div>
      )}

      {/* Error (non-mismatch) */}
      {isError && !reconMismatch && (
        <div data-testid="g9b-error" className="border border-red-300 bg-red-50 rounded-sm p-4 text-sm text-red-700">
          Could not load GSTR-1 §9B report. {error?.response?.data?.detail || error?.message || ""}
          <button onClick={() => refetch()} className="ml-3 underline">Retry</button>
        </div>
      )}

      {data && (
        <>
          {/* Reconciliation banner */}
          <div data-testid="g9b-recon-status"
            className={`border rounded-sm px-4 py-2 flex items-center justify-between text-sm ${
              reconciled ? "border-emerald-300 bg-emerald-50 text-emerald-800"
                         : "border-red-300 bg-red-50 text-red-800"
            }`}>
            <div className="font-bold">
              {reconciled ? "● RECONCILED YES ✓" : "● RECONCILED NO ✗"}
            </div>
            <div className="text-xs font-mono">
              {data.note_count || 0} notes · CN {fmtCurrency(recon?.cn_total || 0)} · DN {fmtCurrency(recon?.dn_total || 0)}
            </div>
          </div>

          {/* KPI cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <G9bKpi testid="g9b-kpi-cdnr"       label="CDNR (B2B)"        count={totals.cdnr?.note_count}       val={totals.cdnr?.val} />
            <G9bKpi testid="g9b-kpi-cdnur"      label="CDNUR (B2CL)"      count={totals.cdnur?.note_count}      val={totals.cdnur?.val} />
            <G9bKpi testid="g9b-kpi-b2cs"       label="B2CS (Table 7)"    count={totals.b2cs_adjustments?.note_count} val={totals.b2cs_adjustments?.val} />
            <G9bKpi testid="g9b-kpi-commercial" label="Commercial (§34)"  count={totals.commercial_notes?.note_count} val={totals.commercial_notes?.val} />
            <G9bKpi testid="g9b-kpi-cancelled"  label="§9C due"           count={totals.cancelled_after_export?.note_count} val={null} />
          </div>

          {isEmpty && (
            <div data-testid="g9b-empty-state" className="border border-zinc-200 bg-white rounded-sm p-8 text-center text-sm text-zinc-500">
              No CN/DN issued in {month}. Change the month or refresh.
            </div>
          )}

          {/* Section tabs */}
          <div className="flex flex-wrap gap-2 border-b border-zinc-200">
            {[
              ["cdnr", "CDNR", cdnrRows.length, "g9b-section-cdnr"],
              ["cdnur", "CDNUR", cdnurRows.length, "g9b-section-cdnur"],
              ["b2cs", "B2CS", b2csRows.length, "g9b-section-b2cs"],
              ["commercial", "Commercial", commercialRows.length, "g9b-section-commercial"],
              ["cancelled", "§9C", cancelledRows.length, "g9b-section-cancelled"],
            ].map(([key, lbl, cnt, tid]) => (
              <button key={key} data-testid={tid} onClick={() => setSection(key)}
                className={`px-3 py-2 text-xs font-semibold border-b-2 -mb-px ${
                  section === key ? "border-zinc-950 text-zinc-950" : "border-transparent text-zinc-500 hover:text-zinc-950"
                }`}>
                {lbl} <span className="ml-1 text-zinc-400">({cnt})</span>
              </button>
            ))}
          </div>

          {/* Active section table */}
          {section === "cdnr"       && <G9bCdnTable testid="g9b-table-cdnr"       rows={cdnrRows}      showCtin />}
          {section === "cdnur"      && <G9bCdnTable testid="g9b-table-cdnur"      rows={cdnurRows}     banner="B2CL — Unregistered high-value inter-state" />}
          {section === "b2cs"       && <G9bCdnTable testid="g9b-table-b2cs"       rows={b2csRows}      banner="Report NET-OF in Table 7 · not part of §9B" bannerTone="warn" />}
          {section === "commercial" && <G9bCommercialTable testid="g9b-table-commercial" rows={commercialRows} />}
          {section === "cancelled"  && <G9bCancelledTable  testid="g9b-table-cancelled"  rows={cancelledRows} />}

          {/* Warnings */}
          {warnings.length > 0 && (
            <div data-testid="g9b-warnings" className="border border-amber-300 bg-amber-50 rounded-sm p-3 text-xs text-amber-800">
              <div className="font-bold uppercase tracking-wider mb-1 flex items-center gap-1"><Info size={12} /> Warnings</div>
              <ul className="list-disc list-inside space-y-0.5 font-mono">
                {warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}

          {/* JSON panel */}
          {showJson && (
            <div data-testid="g9b-json-panel" className="border border-zinc-300 bg-zinc-50 rounded-sm p-3">
              <div className="flex items-center justify-between mb-2">
                <div className="text-xs uppercase tracking-wider font-bold text-zinc-500">Canonical JSON (technical)</div>
                <button onClick={doJsonDownload} className="text-xs underline hover:text-zinc-950">Download JSON</button>
              </div>
              <pre className="text-[10px] leading-tight font-mono overflow-auto max-h-96 bg-white p-2 border border-zinc-200 rounded-sm">
{JSON.stringify(data, null, 2)}
              </pre>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function G9bKpi({ testid, label, count, val }) {
  return (
    <div data-testid={testid} className="border border-zinc-200 bg-white rounded-sm p-3">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">{label}</div>
      <div className="mt-1 text-lg font-black tracking-tight tabular-nums">{count ?? 0}</div>
      {val !== null && val !== undefined && (
        <div className="text-[11px] text-zinc-500 font-mono">{fmtCurrency(val || 0)}</div>
      )}
    </div>
  );
}

function G9bSectionBanner({ text, tone = "info" }) {
  const cls = tone === "warn"
    ? "border-amber-300 bg-amber-50 text-amber-800"
    : "border-zinc-300 bg-zinc-50 text-zinc-700";
  return <div className={`border rounded-sm px-3 py-2 text-xs italic ${cls}`}>{text}</div>;
}

function G9bCdnTable({ testid, rows, showCtin = false, banner, bannerTone }) {
  if (!rows.length) {
    return (
      <div data-testid={testid} className="border border-zinc-200 bg-white rounded-sm p-6 text-sm text-zinc-500 text-center">
        No records for this section.
      </div>
    );
  }
  return (
    <div className="space-y-2" data-testid={testid}>
      {banner && <G9bSectionBanner text={banner} tone={bannerTone} />}
      <div className="border border-zinc-200 bg-white rounded-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              {showCtin && <th className="text-left px-3 py-2">Ctin</th>}
              <th className="text-left px-3 py-2">Recipient</th>
              <th className="text-left px-3 py-2">Note #</th>
              <th className="text-left px-3 py-2">Date</th>
              <th className="text-center px-3 py-2">T</th>
              <th className="text-right px-3 py-2">Value ₹</th>
              <th className="text-left px-3 py-2">POS</th>
              <th className="text-center px-3 py-2">RCM</th>
              <th className="text-right px-3 py-2">Rate%</th>
              <th className="text-right px-3 py-2">Taxable ₹</th>
              <th className="text-right px-3 py-2">CGST</th>
              <th className="text-right px-3 py-2">SGST</th>
              <th className="text-right px-3 py-2">IGST</th>
              <th className="text-left px-3 py-2">Invoice #</th>
              <th className="text-left px-3 py-2">Reason</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {rows.map((nt) => {
              const itm = nt.itms?.[0]?.itm_det || {};
              const bg = nt.kind === "credit" ? "bg-red-50" : "bg-blue-50";
              return (
                <tr key={nt.note_id} className={`border-t border-zinc-100 ${bg}`}>
                  {showCtin && <td className="px-3 py-1.5 whitespace-nowrap">{nt._ctin || ""}</td>}
                  <td className="px-3 py-1.5">{nt._customer_name || nt.customer_name || ""}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap font-semibold">{nt.nt_num}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{nt.nt_dt}</td>
                  <td className="px-3 py-1.5 text-center font-bold">{nt.ntty}</td>
                  <td className="px-3 py-1.5 text-right">{fmtCurrency(nt.val || 0)}</td>
                  <td className="px-3 py-1.5">{nt.pos || ""}</td>
                  <td className="px-3 py-1.5 text-center">
                    {nt.rchrg === "Y" ? <span className="inline-block px-1.5 py-0.5 bg-zinc-900 text-white text-[9px] rounded-sm font-bold">Y</span> : ""}
                  </td>
                  <td className="px-3 py-1.5 text-right">{Number(itm.rt || 0).toFixed(2)}</td>
                  <td className="px-3 py-1.5 text-right">{fmtCurrency(itm.txval || 0)}</td>
                  <td className="px-3 py-1.5 text-right">{fmtCurrency(itm.camt || 0)}</td>
                  <td className="px-3 py-1.5 text-right">{fmtCurrency(itm.samt || 0)}</td>
                  <td className="px-3 py-1.5 text-right">{fmtCurrency(itm.iamt || 0)}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{nt.inum || ""}</td>
                  <td className="px-3 py-1.5">{nt.rsn} · {nt.reason_code_qorvena || ""}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function G9bCommercialTable({ testid, rows }) {
  return (
    <div className="space-y-2" data-testid={testid}>
      <G9bSectionBanner text="Financial/Commercial note — NOT reported in GSTR-1 per CGST §34/§15(3)(b)" tone="warn" />
      {rows.length === 0 ? (
        <div className="border border-zinc-200 bg-white rounded-sm p-6 text-sm text-zinc-500 text-center">
          No commercial notes for this period.
        </div>
      ) : (
        <div className="border border-zinc-200 bg-white rounded-sm overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="text-left px-3 py-2">Note #</th>
                <th className="text-left px-3 py-2">Date</th>
                <th className="text-center px-3 py-2">T</th>
                <th className="text-left px-3 py-2">Recipient</th>
                <th className="text-left px-3 py-2">GSTIN</th>
                <th className="text-left px-3 py-2">Invoice #</th>
                <th className="text-right px-3 py-2">Subtotal ₹</th>
                <th className="text-right px-3 py-2">Total ₹</th>
                <th className="text-left px-3 py-2">Reason</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {rows.map((nt) => (
                <tr key={nt.note_id} className={`border-t border-zinc-100 ${nt.kind === "credit" ? "bg-red-50" : "bg-blue-50"}`}>
                  <td className="px-3 py-1.5 whitespace-nowrap font-semibold">{nt.note_number}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{nt.note_date}</td>
                  <td className="px-3 py-1.5 text-center font-bold">{nt.ntty}</td>
                  <td className="px-3 py-1.5">{nt.customer_name}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{nt.customer_gstin || "—"}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{nt.invoice_number || ""}</td>
                  <td className="px-3 py-1.5 text-right">{fmtCurrency(nt.subtotal || 0)}</td>
                  <td className="px-3 py-1.5 text-right">{fmtCurrency(nt.total_amount || 0)}</td>
                  <td className="px-3 py-1.5">{nt.reason_code_qorvena} · {nt.reason_text || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function G9bCancelledTable({ testid, rows }) {
  return (
    <div className="space-y-2" data-testid={testid}>
      <G9bSectionBanner text="Requires GSTR-1 §9C (CDNRA/CDNURA) amendment in a subsequent filing period" tone="warn" />
      {rows.length === 0 ? (
        <div className="border border-zinc-200 bg-white rounded-sm p-6 text-sm text-zinc-500 text-center">
          No cancelled-after-export notes for this period.
        </div>
      ) : (
        <div className="border border-zinc-200 bg-white rounded-sm overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="text-left px-3 py-2">Note #</th>
                <th className="text-left px-3 py-2">Date</th>
                <th className="text-center px-3 py-2">T</th>
                <th className="text-left px-3 py-2">Recipient</th>
                <th className="text-left px-3 py-2">GSTIN</th>
                <th className="text-left px-3 py-2">Invoice #</th>
                <th className="text-right px-3 py-2">Total ₹</th>
                <th className="text-left px-3 py-2">Cancelled At</th>
                <th className="text-left px-3 py-2">Reason</th>
                <th className="text-left px-3 py-2">Advisory</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {rows.map((nt) => (
                <tr key={nt.note_id} className="border-t border-zinc-100 bg-red-50">
                  <td className="px-3 py-1.5 whitespace-nowrap font-semibold">{nt.note_number}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{nt.note_date}</td>
                  <td className="px-3 py-1.5 text-center font-bold">{nt.ntty}</td>
                  <td className="px-3 py-1.5">{nt.customer_name}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{nt.customer_gstin || "—"}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{nt.invoice_number || ""}</td>
                  <td className="px-3 py-1.5 text-right">{fmtCurrency(nt.total_amount || 0)}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{(nt.cancelled_at || "").slice(0, 10)}</td>
                  <td className="px-3 py-1.5">{nt.cancelled_reason || ""}</td>
                  <td className="px-3 py-1.5 text-[11px]">{nt._advisory || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

