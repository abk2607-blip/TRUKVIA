import React, { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, API, fmtCurrency, fmtDate } from "@/api";
import { toast } from "sonner";
import { ArrowLeft, Download, Printer, Trash2, Plus, MessageCircle, Mail } from "lucide-react";
import VoiceButton from "@/components/VoiceButton";

export default function InvoiceView() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();

  const { data: invoice, isLoading } = useQuery({
    queryKey: ["invoice", id],
    queryFn: async () => (await api.get(`/invoices/${id}`)).data,
  });
  const { data: customers = [] } = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get("/customers")).data });
  const { data: company = {} } = useQuery({ queryKey: ["company"], queryFn: async () => (await api.get("/company")).data });
  const { data: allTrips = [] } = useQuery({
    queryKey: ["invoice-trips", id],
    queryFn: async () => {
      const ids = (invoice?.trip_ids || []).join(",");
      if (!ids) return [];
      return (await api.get("/trips", { params: { ids } })).data;
    },
    enabled: Boolean(invoice?.trip_ids?.length),
  });

  const [showPay, setShowPay] = useState(false);
  const [pay, setPay] = useState({ amount: "", date: new Date().toISOString().slice(0, 10), mode: "Cash", note: "" });

  const addPay = useMutation({
    mutationFn: async () => (await api.post(`/invoices/${id}/payments`, { ...pay, amount: Number(pay.amount) })).data,
    onSuccess: () => { toast.success("Payment recorded"); qc.invalidateQueries(); setShowPay(false); setPay({ amount: "", date: new Date().toISOString().slice(0, 10), mode: "Cash", note: "" }); },
  });

  const del = useMutation({
    mutationFn: async () => {
      const reason = window.prompt("Reason for deleting this invoice? (mandatory)");
      if (!reason || !reason.trim()) throw new Error("Reason required");
      return (await api.delete(`/invoices/${id}`, { params: { reason } })).data;
    },
    onSuccess: () => { toast.success("Invoice deleted"); qc.invalidateQueries(); nav("/invoices"); },
    onError: (e) => toast.error(e?.response?.data?.detail || e.message || "Failed"),
  });

  const sendWhatsApp = async () => {
    if (!customer.phone) { toast.error("Customer phone not set"); return; }
    let token = invoice.share_token;
    if (!token) {
      try {
        const { data } = await api.post(`/invoices/${id}/share`);
        token = data.share_token;
        qc.invalidateQueries({ queryKey: ["invoice", id] });
      } catch {
        toast.error("Could not create share link");
        return;
      }
    }
    const shareUrl = `${window.location.origin.replace("localhost:3000", window.location.host).replace(/\/$/, "")}`;
    // Use REACT_APP_BACKEND_URL API for public PDF
    const pdfUrl = `${API}/public/invoice/${token}/pdf`;
    const phone = customer.phone.replace(/[^\d]/g, "");
    const digits = phone.length === 10 ? "91" + phone : phone;
    const amount = Number(invoice.balance_due || invoice.total_amount).toLocaleString("en-IN");
    const msg =
      `Namaste ${customer.name},\n\n` +
      `Invoice ${invoice.invoice_number} pampistunnamu.\n` +
      `Total: ₹${Number(invoice.total_amount).toLocaleString("en-IN")}\n` +
      `Balance Due: ₹${amount}\n\n` +
      `PDF: ${pdfUrl}\n\n` +
      `Dayachesi payment cheyandi. Thank you!\n` +
      `— ${company.name || "Bitumen Transport"}`;
    window.open(`https://wa.me/${digits}?text=${encodeURIComponent(msg)}`, "_blank");
  };

  if (isLoading || !invoice) return <div className="text-zinc-500">Loading...</div>;
  const customer = customers.find((c) => c.id === invoice.customer_id) || {};
  const trips = allTrips.filter((t) => invoice.trip_ids.includes(t.id))
    .sort((a, b) => (a.date || "").localeCompare(b.date || ""));

  const pdfUrl = `${API}/invoices/${id}/pdf`;

  return (
    <div className="space-y-6" data-testid="invoice-view-page">
      <header className="flex items-center justify-between border-b border-zinc-200 pb-4 no-print">
        <div className="flex items-center gap-3">
          <button onClick={() => nav(-1)} className="p-2 border border-zinc-200 rounded-sm"><ArrowLeft size={16} /></button>
          <div>
            <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Invoice</div>
            <h1 className="text-3xl font-black tracking-tighter font-mono">{invoice.invoice_number}</h1>
          </div>
        </div>
        <div className="flex gap-2 flex-wrap">
          <a data-testid="download-pdf-btn" href={pdfUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800">
            <Download size={14} /> PDF
          </a>
          <button
            data-testid="whatsapp-invoice-btn"
            onClick={sendWhatsApp}
            className="inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-emerald-600 text-white rounded-sm hover:bg-emerald-700"
          >
            <MessageCircle size={14} /> WhatsApp
          </button>
          <a
            data-testid="gmail-invoice-btn"
            href={(() => {
              const subject = `Invoice ${invoice.invoice_number} — ${company?.name || ""}`.trim();
              const body = `Dear ${customer?.name || "Customer"},\n\nPlease find attached / linked Invoice ${invoice.invoice_number} dated ${(invoice.invoice_date || "")} for ${Number(invoice.total_amount || 0).toLocaleString("en-IN")}.\nBalance Due: ${Number(invoice.balance_due || 0).toLocaleString("en-IN")}\n\nPDF: ${pdfUrl}\n\nRegards,\n${company?.name || ""}`;
              const to = customer?.email || "";
              return `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(to)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
            })()}
            target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-rose-600 text-white rounded-sm hover:bg-rose-700"
            title={customer?.email ? `Compose Gmail to ${customer.email}` : "Compose Gmail (no customer email set)"}
          >
            <Mail size={14} /> Gmail
          </a>
          <button data-testid="print-btn" onClick={() => window.print()} className="inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider font-semibold border border-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white">
            <Printer size={14} /> Print
          </button>
            <button data-testid="delete-invoice-btn" onClick={() => { if (window.confirm("Delete invoice? Trips will be released.")) del.mutate(); }} className="inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-50">
            <Trash2 size={14} /> Delete
          </button>
        </div>
      </header>

      {/* Invoice Paper */}
      <div className="bg-white border border-zinc-950 rounded-sm p-8 print:border-0 print:p-4" data-testid="invoice-paper">
        {/* Company + Title */}
        <div className="grid grid-cols-2 gap-6 border-b-2 border-zinc-950 pb-4">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">From</div>
            <div className="flex items-start gap-3 mt-1">
              {company.logo && (
                <img data-testid="invoice-logo" src={company.logo} alt="Logo" className="w-16 h-16 object-contain border border-zinc-200 rounded-sm bg-white" />
              )}
              <div>
                <div className="text-lg font-black">{company.name || "Your Company Name"}</div>
                <div className="text-xs whitespace-pre-line mt-1 text-zinc-700">{company.address}</div>
                <div className="text-xs mt-1 text-zinc-700">
                  {company.phone && <>Ph: {company.phone} · </>}
                  {company.email}
                </div>
                <div className="text-xs mt-1 font-mono">
                  <span className="font-bold">GSTIN:</span> {company.gstin || "—"} · <span className="font-bold">PAN:</span> {company.pan || "—"}
                </div>
                <div className="text-xs font-mono">State: {company.state || "—"}</div>
              </div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-3xl font-black tracking-tight">TAX INVOICE</div>
            <div className="mt-1 text-xs font-bold uppercase tracking-wider">
              Reverse Charge: {invoice.rcm ? "YES" : "NO"}
            </div>
            <div className="mt-3 inline-block border border-zinc-300 text-left text-xs">
              <div className="grid grid-cols-2 divide-x divide-zinc-300">
                <div className="px-3 py-1.5 font-bold bg-zinc-50">Invoice No</div>
                <div className="px-3 py-1.5 font-mono">{invoice.invoice_number}</div>
              </div>
              <div className="grid grid-cols-2 divide-x divide-zinc-300 border-t border-zinc-300">
                <div className="px-3 py-1.5 font-bold bg-zinc-50">Date</div>
                <div className="px-3 py-1.5 font-mono">{fmtDate(invoice.invoice_date)}</div>
              </div>
              <div className="grid grid-cols-2 divide-x divide-zinc-300 border-t border-zinc-300">
                <div className="px-3 py-1.5 font-bold bg-zinc-50">HSN/SAC</div>
                <div className="px-3 py-1.5 font-mono">{invoice.hsn_sac || company.hsn_sac || "996791"}</div>
              </div>
            </div>
          </div>
        </div>

        {/* Bill To  |  Ship To  |  Bank Details — Iter79 restore SHIP TO opposite BILL TO */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-6 border-b border-zinc-300 py-4">
          <div data-testid="invoice-bill-to">
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">Bill To</div>
            <div className="mt-1 text-base sm:text-lg font-bold">{customer.name}</div>
            <div className="text-xs whitespace-pre-line mt-1 text-zinc-700">{customer.address}</div>
            <div className="text-xs font-mono mt-1"><span className="font-bold">GSTIN:</span> {customer.gstin || "—"}</div>
            <div className="text-xs font-mono">PAN: {customer.pan || "—"} · State: {customer.state || "—"}</div>
          </div>
          <div data-testid="invoice-ship-to">
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">Ship To</div>
            {(() => {
              // Iter79 — Resolve consignee from the invoice's trips.
              //   1) If ALL trips share the same ship_site_id → show that site
              //   2) Else if all trips share the same to_location → show that
              //   3) Else "Mixed — see trip rows below"
              const sites = (customer.ship_sites || []);
              const ids = Array.from(new Set(trips.map((t) => t.ship_site_id).filter(Boolean)));
              const tos = Array.from(new Set(trips.map((t) => t.to_location).filter(Boolean)));
              if (ids.length === 1) {
                const s = sites.find((x) => x.id === ids[0]);
                if (s) {
                  return (
                    <>
                      <div className="mt-1 text-base sm:text-lg font-bold">{s.site_name || customer.name}</div>
                      <div className="text-xs whitespace-pre-line mt-1 text-zinc-700">{s.address || "—"}</div>
                      {s.gstin && <div className="text-xs font-mono mt-1"><span className="font-bold">GSTIN:</span> {s.gstin}</div>}
                      <div className="text-xs font-mono">State: {s.state || customer.state || "—"} {s.pincode ? `· ${s.pincode}` : ""}</div>
                      {(s.contact_person || s.phone) && (
                        <div className="text-xs text-zinc-600 mt-1">
                          {s.contact_person || ""}{s.contact_person && s.phone ? " · " : ""}{s.phone || ""}
                        </div>
                      )}
                    </>
                  );
                }
              }
              if (tos.length === 1) {
                return (
                  <>
                    <div className="mt-1 text-base sm:text-lg font-bold">{customer.name}</div>
                    <div className="text-xs mt-1 text-zinc-700">{tos[0]}</div>
                    <div className="text-xs font-mono">State: {customer.state || "—"}</div>
                  </>
                );
              }
              return (
                <div className="mt-1 text-xs text-zinc-600 italic">Mixed destinations — see trip rows below</div>
              );
            })()}
          </div>
          <div className="md:text-right" data-testid="invoice-bank">
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">Bank Details</div>
            <div className="mt-1 text-xs font-mono">
              <div>{company.bank_name || "—"}</div>
              <div>A/c: {company.account_number || "—"}</div>
              <div>IFSC: {company.ifsc || "—"}</div>
              <div>Branch: {company.branch || "—"}</div>
            </div>
          </div>
        </div>

        {/* Trips Table */}
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-xs border border-zinc-300" data-testid="invoice-trips-table">
            <thead className="bg-zinc-100 text-zinc-700">
              <tr>
                <th className="border border-zinc-300 px-2 py-2 text-left">#</th>
                <th className="border border-zinc-300 px-2 py-2 text-left">Date</th>
                <th className="border border-zinc-300 px-2 py-2 text-left">Vehicle</th>
                <th className="border border-zinc-300 px-2 py-2 text-left" data-testid="invoice-th-cust-ref">Cust Ref</th>
                <th className="border border-zinc-300 px-2 py-2 text-left">Load</th>
                <th className="border border-zinc-300 px-2 py-2 text-left">Route</th>
                <th className="border border-zinc-300 px-2 py-2 text-right">Tons</th>
                <th className="border border-zinc-300 px-2 py-2 text-left">Rate Mode</th>
                <th className="border border-zinc-300 px-2 py-2 text-right">Rate</th>
                <th className="border border-zinc-300 px-2 py-2 text-right">Freight (₹)</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {trips.map((t, idx) => {
                const shortAmt = Number(t.shortage_amount || 0) + Number((t.expenses || {}).shortage_amount || 0);
                const haltAmt = Number(t.halting_amount || 0);
                const excessAmt = Number(t.excess_amount || 0);
                return (
                  <React.Fragment key={t.id}>
                    <tr>
                      <td className="border border-zinc-300 px-2 py-1.5">{idx + 1}</td>
                      <td className="border border-zinc-300 px-2 py-1.5">{fmtDate(t.date)}</td>
                      <td className="border border-zinc-300 px-2 py-1.5">{t.vehicle_number}</td>
                      <td
                        className="border border-zinc-300 px-2 py-1.5"
                        data-testid={`invoice-trip-cust-ref-${t.id}`}
                      >
                        {/* Iter82 — Customer Ref shown per-trip, NEVER inherited. Blank stays blank. */}
                        {t.customer_reference_number || t.customer_invoice_no || t.waybill_no || "—"}
                      </td>
                      <td className="border border-zinc-300 px-2 py-1.5">{t.load_details}</td>
                      <td className="border border-zinc-300 px-2 py-1.5">{t.from_location} → {t.to_location}</td>
                      <td className="border border-zinc-300 px-2 py-1.5 text-right">{Number(t.tons).toFixed(2)}</td>
                      <td className="border border-zinc-300 px-2 py-1.5">{t.freight_mode === "per_ton" ? "Per Ton" : "Round Trip"}</td>
                      <td className="border border-zinc-300 px-2 py-1.5 text-right">
                        {t.freight_mode === "per_ton"
                          ? Number(t.rate_per_ton).toFixed(2)
                          : (t.round_trip_kms > 0 && t.rate_per_km_per_ton > 0)
                            ? `${Number(t.round_trip_kms).toFixed(0)}km×₹${Number(t.rate_per_km_per_ton).toFixed(2)}`
                            : Number(t.fixed_amount).toFixed(2)}
                      </td>
                      <td className="border border-zinc-300 px-2 py-1.5 text-right font-bold">{fmtCurrency(t.freight_amount)}</td>
                    </tr>
                    {haltAmt > 0 && (
                      <tr className="bg-zinc-50 text-zinc-600">
                        <td className="border border-zinc-300 px-2 py-1"></td>
                        <td className="border border-zinc-300 px-2 py-1" colSpan={8}>↳ Halting Charges — {t.chargeable_halting_days || 0} day(s) × ₹ {Number(t.halting_rate_per_day || 0).toFixed(2)} / day</td>
                        <td className="border border-zinc-300 px-2 py-1 text-right">{fmtCurrency(haltAmt)}</td>
                      </tr>
                    )}
                    {(() => {
                      const d = Number((t.expenses || {}).diesel_from_customer_amount || 0);
                      if (d <= 0) return null;
                      const dq = Number((t.expenses || {}).diesel_from_customer_qty || 0);
                      const dr = Number((t.expenses || {}).diesel_from_customer_rate || 0);
                      return (
                        <tr className="bg-zinc-50 text-rose-700">
                          <td className="border border-zinc-300 px-2 py-1"></td>
                          <td className="border border-zinc-300 px-2 py-1" colSpan={8}>↳ Less: Diesel from Customer{dq > 0 && dr > 0 ? ` — ${dq.toFixed(2)} L × ₹ ${dr.toFixed(2)} / L` : ""}</td>
                          <td className="border border-zinc-300 px-2 py-1 text-right">({fmtCurrency(d)})</td>
                        </tr>
                      );
                    })()}
                    {(() => {
                      const a = Number((t.expenses || {}).cash_advance_received || 0);
                      if (a <= 0) return null;
                      return (
                        <tr className="bg-zinc-50 text-rose-700">
                          <td className="border border-zinc-300 px-2 py-1"></td>
                          <td className="border border-zinc-300 px-2 py-1" colSpan={8}>↳ Less: Customer Advance Received</td>
                          <td className="border border-zinc-300 px-2 py-1 text-right">({fmtCurrency(a)})</td>
                        </tr>
                      );
                    })()}
                    {shortAmt > 0 && (
                      <tr className="bg-zinc-50 text-rose-700">
                        <td className="border border-zinc-300 px-2 py-1"></td>
                        <td className="border border-zinc-300 px-2 py-1" colSpan={8}>
                          ↳ Less: Shortage
                          {t.shortage_qty > 0 && ` — ${Number(t.shortage_qty).toFixed(3)} MT`}
                          {t.product_rate_per_mt > 0 && ` × ₹ ${Number(t.product_rate_per_mt).toFixed(2)} / MT`}
                        </td>
                        <td className="border border-zinc-300 px-2 py-1 text-right">({fmtCurrency(shortAmt)})</td>
                      </tr>
                    )}
                    {excessAmt > 0 && (
                      <tr className="bg-zinc-50 text-emerald-700">
                        <td className="border border-zinc-300 px-2 py-1"></td>
                        <td className="border border-zinc-300 px-2 py-1" colSpan={8}>
                          ↳ Add: Excess Qty
                          {t.excess_qty > 0 && ` — ${Number(t.excess_qty).toFixed(3)} MT`}
                          {t.product_rate_per_mt > 0 && ` × ₹ ${Number(t.product_rate_per_mt).toFixed(2)} / MT`}
                        </td>
                        <td className="border border-zinc-300 px-2 py-1 text-right">{fmtCurrency(excessAmt)}</td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Totals */}
        <div className="mt-4 grid grid-cols-2 gap-6">
          <div className="text-xs">
            <div className="font-bold uppercase tracking-wider text-zinc-500 text-[10px]">Terms & Notes</div>
            <ol className="mt-2 list-decimal list-inside space-y-1 text-zinc-700">
              <li>{invoice.rcm ? "GST is payable by service recipient under RCM per Notification No. 08/2017." : "GST charged under forward charge; included in total."}</li>
              <li>Bitumen shortage/excess accounted only beyond 1% variation.</li>
              <li>Halting Charges applicable after 48 hours from arrival at the site.</li>
              {invoice.notes && <li>Notes: {invoice.notes}</li>}
            </ol>
          </div>
          <div>
            <table className="w-full text-sm border border-zinc-300">
              <tbody className="font-mono">
                <tr><td className="border-b border-zinc-300 px-3 py-1.5 font-bold">Freight Amount</td><td className="border-b border-zinc-300 px-3 py-1.5 text-right">{fmtCurrency(invoice.freight_total || invoice.subtotal)}</td></tr>
                {invoice.halting_total > 0 && (
                  <tr><td className="border-b border-zinc-300 px-3 py-1.5">Halting Charges</td><td className="border-b border-zinc-300 px-3 py-1.5 text-right">{fmtCurrency(invoice.halting_total)}</td></tr>
                )}
                {invoice.excess_total > 0 && (
                  <tr><td className="border-b border-zinc-300 px-3 py-1.5">Excess Qty Charges</td><td className="border-b border-zinc-300 px-3 py-1.5 text-right">{fmtCurrency(invoice.excess_total)}</td></tr>
                )}
                {invoice.shortage_total > 0 && (
                  <tr><td className="border-b border-zinc-300 px-3 py-1.5 text-rose-700">Less: Shortage Deduction</td><td className="border-b border-zinc-300 px-3 py-1.5 text-right text-rose-700">({fmtCurrency(invoice.shortage_total)})</td></tr>
                )}
                {invoice.diesel_deduction_total > 0 && (
                  <tr><td className="border-b border-zinc-300 px-3 py-1.5 text-rose-700">Less: Diesel from Customer</td><td className="border-b border-zinc-300 px-3 py-1.5 text-right text-rose-700">({fmtCurrency(invoice.diesel_deduction_total)})</td></tr>
                )}
                {invoice.advance_deduction_total > 0 && (
                  <tr><td className="border-b border-zinc-300 px-3 py-1.5 text-rose-700">Less: Customer Advance Received</td><td className="border-b border-zinc-300 px-3 py-1.5 text-right text-rose-700">({fmtCurrency(invoice.advance_deduction_total)})</td></tr>
                )}
                <tr className="bg-zinc-50"><td className="border-b border-zinc-300 px-3 py-1.5 font-bold">Net Freight (Taxable)</td><td className="border-b border-zinc-300 px-3 py-1.5 text-right font-bold">{fmtCurrency(invoice.subtotal)}</td></tr>
                {invoice.gst_type === "cgst_sgst" ? (
                  <>
                    <tr><td className="border-b border-zinc-300 px-3 py-1.5">CGST @ 2.5%</td><td className="border-b border-zinc-300 px-3 py-1.5 text-right">{fmtCurrency(invoice.cgst_amount)}</td></tr>
                    <tr><td className="border-b border-zinc-300 px-3 py-1.5">SGST @ 2.5%</td><td className="border-b border-zinc-300 px-3 py-1.5 text-right">{fmtCurrency(invoice.sgst_amount)}</td></tr>
                  </>
                ) : (
                  <tr><td className="border-b border-zinc-300 px-3 py-1.5">IGST @ 5%</td><td className="border-b border-zinc-300 px-3 py-1.5 text-right">{fmtCurrency(invoice.igst_amount)}</td></tr>
                )}
                {invoice.rcm && <tr><td className="border-b border-zinc-300 px-3 py-1.5 text-zinc-500">Under RCM</td><td className="border-b border-zinc-300 px-3 py-1.5 text-right text-zinc-400">—</td></tr>}
                <tr><td className="border-b border-zinc-300 px-3 py-1.5 font-semibold">Total Amount</td><td className="border-b border-zinc-300 px-3 py-1.5 text-right font-semibold">{fmtCurrency(invoice.gross_total || invoice.total_amount)}</td></tr>
                {typeof invoice.round_off === "number" && Math.abs(invoice.round_off) >= 0.005 && (
                  <tr><td className="border-b border-zinc-300 px-3 py-1.5 text-zinc-500">Round Off</td><td className="border-b border-zinc-300 px-3 py-1.5 text-right text-zinc-500">{invoice.round_off > 0 ? "+" : "−"} {fmtCurrency(Math.abs(invoice.round_off))}</td></tr>
                )}
                <tr className="bg-amber-50"><td className="border-b border-zinc-300 px-3 py-2 font-black text-base">FINAL PAYABLE</td><td className="border-b border-zinc-300 px-3 py-2 text-right font-black text-base">{fmtCurrency(invoice.total_amount)}</td></tr>
                <tr><td className="border-b border-zinc-300 px-3 py-1.5 text-emerald-700 font-semibold">Amount Received</td><td className="border-b border-zinc-300 px-3 py-1.5 text-right text-emerald-700 font-semibold">{fmtCurrency(invoice.amount_paid)}</td></tr>
                <tr><td className="px-3 py-1.5 text-amber-800 font-bold">Balance Due</td><td className="px-3 py-1.5 text-right text-amber-800 font-bold">{fmtCurrency(invoice.balance_due)}</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="mt-8 grid grid-cols-2 text-xs">
          <div></div>
          <div className="text-right">
            <div className="mt-8 border-t border-zinc-950 pt-2 inline-block px-8 font-bold">
              For {company.name || "Your Company"}<br />
              <span className="font-normal text-[10px] uppercase tracking-wider text-zinc-500">Authorised Signatory</span>
            </div>
          </div>
        </div>
      </div>

      {/* Payments Section */}
      <section className="border border-zinc-200 bg-white rounded-sm no-print">
        <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
          <h3 className="text-sm font-bold uppercase tracking-wider">
            <span className="telugu">చెల్లింపులు</span> · Payments
          </h3>
          <button data-testid="add-payment-btn" onClick={() => setShowPay(true)} disabled={invoice.balance_due <= 0} className="inline-flex items-center gap-1 px-3 py-1.5 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-40">
            <Plus size={12} /> Add Payment
          </button>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-4 py-2 font-semibold">Date</th>
              <th className="text-left px-4 py-2 font-semibold">Mode</th>
              <th className="text-right px-4 py-2 font-semibold">Amount</th>
              <th className="text-left px-4 py-2 font-semibold">Note</th>
            </tr>
          </thead>
          <tbody>
            {(invoice.payments || []).map((p) => (
              <tr key={p.id} className="border-t border-zinc-100">
                <td className="px-4 py-2 font-mono text-xs">{fmtDate(p.date)}</td>
                <td className="px-4 py-2">{p.mode}</td>
                <td className="px-4 py-2 text-right font-mono font-semibold text-emerald-700">{fmtCurrency(p.amount)}</td>
                <td className="px-4 py-2 text-xs text-zinc-500">{p.note}</td>
              </tr>
            ))}
            {(invoice.payments || []).length === 0 && (
              <tr><td colSpan={4} className="px-4 py-6 text-center text-zinc-400 text-sm">No payments yet.</td></tr>
            )}
          </tbody>
        </table>
      </section>

      {showPay && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4 no-print" data-testid="payment-modal">
          <div className="bg-white w-full max-w-md border border-zinc-950 rounded-sm p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-bold">Record Payment</h3>
              <VoiceButton
                context="payment"
                size="sm"
                onParsed={(p) => {
                  setPay((prev) => ({
                    ...prev,
                    amount: p.amount ? String(p.amount) : prev.amount,
                    date: p.date || prev.date,
                    mode: p.mode || prev.mode,
                    note: p.note || prev.note,
                  }));
                }}
              />
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Amount *</label>
                <input data-testid="pay-amount" type="number" step="0.01" value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} className="w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm" />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Date</label>
                <input data-testid="pay-date" type="date" value={pay.date} onChange={(e) => setPay({ ...pay, date: e.target.value })} className="w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm" />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Mode</label>
                <select data-testid="pay-mode" value={pay.mode} onChange={(e) => setPay({ ...pay, mode: e.target.value })} className="w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm">
                  <option>Cash</option><option>Bank Transfer</option><option>UPI</option><option>Cheque</option><option>Other</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Note</label>
                <input data-testid="pay-note" value={pay.note} onChange={(e) => setPay({ ...pay, note: e.target.value })} className="w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm" />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setShowPay(false)} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
              <button data-testid="save-payment-btn" onClick={() => addPay.mutate()} disabled={!pay.amount || addPay.isPending} className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
