import React, { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate } from "@/api";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";

export default function InvoiceCreate() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [customerId, setCustomerId] = useState("");
  const [selected, setSelected] = useState({});
  const [rcm, setRcm] = useState(true);
  const [invoiceDate, setInvoiceDate] = useState(new Date().toISOString().slice(0, 10));
  const [notes, setNotes] = useState("");

  const { data: customers = [] } = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get("/customers")).data });
  const { data: company } = useQuery({ queryKey: ["company"], queryFn: async () => (await api.get("/company")).data });
  const { data: trips = [], refetch } = useQuery({
    queryKey: ["invoiceable-trips", customerId],
    queryFn: async () => (await api.get("/trips", { params: { customer_id: customerId, status: "pending" } })).data,
    enabled: Boolean(customerId),
  });

  const selectedCustomer = customers.find((c) => c.id === customerId);
  // Auto GST determination: same state → CGST+SGST; different / missing → IGST
  const gstType = useMemo(() => {
    const home = (company?.state || "").trim().toLowerCase();
    const cust = (selectedCustomer?.state || "").trim().toLowerCase();
    if (!home || !cust) return "cgst_sgst"; // fallback for preview only
    return home === cust ? "cgst_sgst" : "igst";
  }, [company?.state, selectedCustomer?.state]);

  const selectedTrips = useMemo(() => trips.filter((t) => selected[t.id]), [trips, selected]);
  const freightTotal = selectedTrips.reduce((s, t) => s + Number(t.freight_amount || 0), 0);
  const haltingTotal = selectedTrips.reduce((s, t) => s + Number(t.halting_amount || 0), 0);
  const excessTotal = selectedTrips.reduce((s, t) => s + Number(t.excess_amount || 0), 0);
  const shortageTotal = selectedTrips.reduce((s, t) => s + Number(t.shortage_amount || 0) + Number((t.expenses || {}).shortage_amount || 0), 0);
  const subtotal = freightTotal + haltingTotal + excessTotal - shortageTotal;
  const cgst = gstType === "cgst_sgst" ? subtotal * 0.025 : 0;
  const sgst = gstType === "cgst_sgst" ? subtotal * 0.025 : 0;
  const igst = gstType === "igst" ? subtotal * 0.05 : 0;
  const totalTax = cgst + sgst + igst;
  const grossTotal = rcm ? subtotal : subtotal + totalTax;
  const finalTotal = Math.round(grossTotal);
  const roundOff = Number((finalTotal - grossTotal).toFixed(2));

  const create = useMutation({
    mutationFn: async () => (await api.post("/invoices", {
      customer_id: customerId,
      trip_ids: Object.keys(selected).filter((k) => selected[k]),
      invoice_date: invoiceDate,
      gst_type: gstType,
      rcm,
      notes,
    })).data,
    onSuccess: (data) => {
      toast.success("Invoice created");
      qc.invalidateQueries();
      nav(`/invoices/${data.id}`);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const toggleAll = () => {
    if (Object.keys(selected).length === trips.length && trips.every((t) => selected[t.id])) {
      setSelected({});
    } else {
      setSelected(Object.fromEntries(trips.map((t) => [t.id, true])));
    }
  };

  const canSubmit = customerId && selectedTrips.length > 0;

  return (
    <div className="space-y-6" data-testid="invoice-create-page">
      <header className="flex items-center gap-3 border-b border-zinc-200 pb-4">
        <button onClick={() => nav(-1)} className="p-2 border border-zinc-200 rounded-sm"><ArrowLeft size={16} /></button>
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">New</div>
          <h1 className="text-3xl font-black tracking-tighter">
            <span className="telugu">కొత్త ఇన్వాయిస్</span>
            <span className="text-zinc-400"> · Create Invoice</span>
          </h1>
        </div>
      </header>

      <section className="border border-zinc-200 bg-white rounded-sm p-5 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Customer · కస్టమర్ *</label>
            <select data-testid="invoice-customer" value={customerId} onChange={(e) => { setCustomerId(e.target.value); setSelected({}); }} className={inputCls}>
              <option value="">-- Select Customer --</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Invoice Date · తేదీ</label>
            <input data-testid="invoice-date" type="date" value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} className={inputCls} />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">GST Type <span className="text-emerald-700">(Auto)</span></label>
            <div data-testid="invoice-gst-type" className={`${inputCls} bg-zinc-50 flex items-center`}>
              {gstType === "cgst_sgst" ? "CGST + SGST (Intra-state)" : "IGST (Inter-state)"}
            </div>
            <div className="text-[10px] text-zinc-500 mt-1">
              {selectedCustomer?.state && company?.state
                ? `Company: ${company.state} · Customer: ${selectedCustomer.state} → ${gstType === "cgst_sgst" ? "Same state" : "Different states"}`
                : "Set Company & Customer states to auto-determine"}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <input id="rcm" data-testid="invoice-rcm" type="checkbox" checked={rcm} onChange={(e) => setRcm(e.target.checked)} className="w-4 h-4" />
          <label htmlFor="rcm" className="text-sm">
            <span className="font-semibold">Reverse Charge (RCM)</span>
            <span className="ml-2 text-xs text-zinc-500">
              <span className="telugu">తక్కువ చార్జ్ — పన్ను రిసీవర్ చెల్లిస్తారు</span>
            </span>
          </label>
        </div>
      </section>

      {customerId && (
        <section className="border border-zinc-200 bg-white rounded-sm">
          <div className="px-5 py-3 border-b border-zinc-200 flex items-center justify-between">
            <div className="text-sm font-bold uppercase tracking-wider">
              <span className="telugu">పెండింగ్ ట్రిప్స్</span> · Uninvoiced Trips ({trips.length})
            </div>
            {trips.length > 0 && (
              <button data-testid="toggle-all-trips" onClick={toggleAll} className="text-xs px-2 py-1 border border-zinc-200 rounded-sm hover:bg-zinc-950 hover:text-white">
                {trips.every((t) => selected[t.id]) ? "Clear All" : "Select All"}
              </button>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
                <tr>
                  <th className="px-3 py-2"></th>
                  <th className="text-left px-3 py-2 font-semibold">Date</th>
                  <th className="text-left px-3 py-2 font-semibold">Vehicle</th>
                  <th className="text-left px-3 py-2 font-semibold">Route</th>
                  <th className="text-right px-3 py-2 font-semibold">Tons</th>
                  <th className="text-left px-3 py-2 font-semibold">Mode</th>
                  <th className="text-right px-3 py-2 font-semibold">Freight</th>
                </tr>
              </thead>
              <tbody>
                {trips.map((t) => (
                  <tr key={t.id} data-testid={`select-trip-${t.id}`} className={`border-t border-zinc-100 cursor-pointer ${selected[t.id] ? "bg-amber-50" : ""}`} onClick={() => setSelected({ ...selected, [t.id]: !selected[t.id] })}>
                    <td className="px-3 py-2"><input type="checkbox" readOnly checked={!!selected[t.id]} className="w-4 h-4" /></td>
                    <td className="px-3 py-2 font-mono text-xs">{fmtDate(t.date)}</td>
                    <td className="px-3 py-2 font-mono text-xs">{t.vehicle_number}</td>
                    <td className="px-3 py-2 text-xs">{t.from_location} → {t.to_location}</td>
                    <td className="px-3 py-2 text-right font-mono">{Number(t.tons).toFixed(2)}</td>
                    <td className="px-3 py-2 text-xs">{t.freight_mode === "per_ton" ? `${Number(t.rate_per_ton).toFixed(0)}/ton` : "Fixed"}</td>
                    <td className="px-3 py-2 text-right font-mono font-semibold">{fmtCurrency(t.freight_amount)}</td>
                  </tr>
                ))}
                {trips.length === 0 && (
                  <tr><td colSpan={7} className="px-4 py-12 text-center text-zinc-400">No pending trips for this customer.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {selectedTrips.length > 0 && (
        <section className="border border-zinc-950 bg-white rounded-sm p-5" data-testid="invoice-preview-totals">
          <div className="text-sm font-bold uppercase tracking-wider mb-3">Preview Totals</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1 text-sm">
              <Row k="Trips Selected" v={selectedTrips.length} mono />
              <Row k="Freight Total" v={fmtCurrency(freightTotal)} mono />
              {haltingTotal > 0 && <Row k="Halting Charges" v={fmtCurrency(haltingTotal)} mono />}
              {excessTotal > 0 && <Row k="Excess Charges" v={fmtCurrency(excessTotal)} mono />}
              {shortageTotal > 0 && <Row k="Less: Shortage" v={`(${fmtCurrency(shortageTotal)})`} mono />}
              <Row k="Taxable Amount" v={fmtCurrency(subtotal)} mono />
              {gstType === "cgst_sgst" ? (
                <>
                  <Row k="CGST @ 2.5%" v={fmtCurrency(cgst)} mono />
                  <Row k="SGST @ 2.5%" v={fmtCurrency(sgst)} mono />
                </>
              ) : (
                <Row k="IGST @ 5%" v={fmtCurrency(igst)} mono />
              )}
              {rcm && <Row k="RCM (tax not collected)" v="—" muted />}
              <Row k="Total Amount" v={fmtCurrency(grossTotal)} mono />
              {Math.abs(roundOff) >= 0.005 && (
                <Row k="Round Off" v={`${roundOff > 0 ? "+" : "−"} ${fmtCurrency(Math.abs(roundOff))}`} mono muted />
              )}
            </div>
            <div className="bg-amber-50 border border-amber-200 p-4 rounded-sm text-right">
              <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Final Payable</div>
              <div className="font-mono text-3xl font-black text-amber-900 mt-2">{fmtCurrency(finalTotal)}</div>
            </div>
          </div>

          <div className="mt-4">
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Notes · గమనికలు</label>
            <textarea data-testid="invoice-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} className={inputCls} />
          </div>

          <div className="mt-4 flex justify-end">
            <button data-testid="create-invoice-btn" disabled={!canSubmit || create.isPending} onClick={() => create.mutate()} className="px-6 py-3 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
              {create.isPending ? "Creating..." : "Create Invoice"}
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

const inputCls = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";

function Row({ k, v, mono, muted }) {
  return (
    <div className="flex justify-between border-b border-zinc-100 py-1.5">
      <span className={muted ? "text-zinc-500" : ""}>{k}</span>
      <span className={`${mono ? "font-mono" : ""} ${muted ? "text-zinc-400" : "font-semibold"}`}>{v}</span>
    </div>
  );
}
