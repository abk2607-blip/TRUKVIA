import React from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, API, fmtCurrency, fmtDate } from "@/api";
import { ArrowLeft, Pencil, FileText, ExternalLink } from "lucide-react";
import FileAttachments from "@/components/FileAttachments";

export default function TripView() {
  const { id } = useParams();
  const nav = useNavigate();

  const { data: trip } = useQuery({
    queryKey: ["trip-view", id],
    queryFn: async () => (await api.get("/trips")).data.find((t) => t.id === id),
  });
  const { data: customers = [] } = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get("/customers")).data });
  const { data: vehicles = [] } = useQuery({ queryKey: ["vehicles"], queryFn: async () => (await api.get("/vehicles")).data });
  const { data: invoices = [] } = useQuery({ queryKey: ["invoices"], queryFn: async () => (await api.get("/invoices")).data });

  if (!trip) {
    return <div className="text-center text-zinc-500 py-16" data-testid="trip-view-loading">Loading trip…</div>;
  }

  const customer = customers.find((c) => c.id === trip.customer_id) || {};
  const vehicle = vehicles.find((v) => v.id === trip.vehicle_id) || vehicles.find((v) => v.vehicle_number === trip.vehicle_number) || {};
  const invoice = invoices.find((i) => i.id === trip.invoice_id);
  const isSupplier = trip.vehicle_type === "supplier";
  const supFreight = Number(trip.supplier_freight || 0);
  const supAdvance = Number(trip.supplier_advance || 0);
  const supOther = Number(trip.supplier_other_recoveries || 0);
  const netPayable = supFreight - supAdvance - supOther;
  const supplierProfit = Number(trip.freight_amount || 0) - (supFreight - supAdvance);
  const e = trip.expenses || {};

  return (
    <div className="space-y-6" data-testid="trip-view-page">
      <header className="flex items-center gap-3 border-b border-zinc-200 pb-4">
        <button onClick={() => nav(-1)} className="p-2 border border-zinc-200 rounded-sm" data-testid="trip-view-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Trip Details</div>
          <h1 className="text-3xl font-black tracking-tighter">
            <span className="telugu">ట్రిప్ వివరాలు</span>
            <span className="text-zinc-400"> · Trip View</span>
          </h1>
        </div>
        <div className="flex gap-2">
          <a data-testid="trip-view-lr" href={`${API}/trips/${trip.id}/lr`} target="_blank" rel="noreferrer"
             className="inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider border border-zinc-200 rounded-sm hover:bg-zinc-950 hover:text-white">
            <FileText size={14} /> LR PDF
          </a>
          <Link data-testid="trip-view-edit" to={`/trips/${trip.id}/edit`}
                className="inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800">
            <Pencil size={14} /> Edit Trip
          </Link>
        </div>
      </header>

      {/* Summary strip */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Stat label="Date" value={fmtDate(trip.date)} />
        <Stat label="Status" value={trip.status === "invoiced" ? "Invoiced" : "Pending"} accent={trip.status === "invoiced" ? "emerald" : "amber"} />
        <Stat label="Freight" value={fmtCurrency(trip.freight_amount)} />
        <Stat label={isSupplier ? "Net Payable" : "Total Expense"} value={fmtCurrency(trip.total_expense)} accent="rose" />
        <Stat label="Profit" value={fmtCurrency(trip.profit)} accent={trip.profit >= 0 ? "emerald" : "rose"} />
      </div>

      {/* Customer */}
      <Section title="Customer · కస్టమర్">
        <Grid2>
          <Row k="Name" v={customer.name || "—"} />
          <Row k="Phone" v={customer.phone || "—"} />
          <Row k="GSTIN" v={customer.gstin || "—"} />
          <Row k="Address" v={customer.address || "—"} />
          <Row k="State / Pincode" v={`${customer.state || "—"} · ${customer.pincode || "—"}`} />
        </Grid2>
      </Section>

      {/* Vehicle */}
      <Section title="Vehicle · వాహనం">
        <Grid2>
          <Row k="Vehicle Number" v={trip.vehicle_number} mono />
          <Row k="Vehicle Type" v={isSupplier ? "Supplier (Hired)" : "Own"} />
          <Row k="Owner / Supplier" v={vehicle.owner_name || vehicle.supplier_name || trip.supplier_name || "—"} />
          <Row k="Capacity" v={vehicle.capacity_tons ? `${vehicle.capacity_tons} MT` : "—"} />
          <Row k="Make / Model" v={vehicle.make_model || "—"} />
        </Grid2>
      </Section>

      {/* Driver */}
      <Section title="Driver · డ్రైవర్">
        <Grid2>
          <Row k="Driver Name" v={trip.driver_name || "—"} />
          <Row k="Driver Mobile" v={trip.driver_mobile || "—"} />
        </Grid2>
      </Section>

      {/* Load / Route */}
      <Section title="Load & Route · లోడ్">
        <Grid2>
          <Row k="Product" v={trip.load_details || "—"} />
          <Row k="HSN / SAC" v={trip.hsn_sac || "—"} />
          <Row k="Tons" v={`${Number(trip.tons || 0).toFixed(2)} MT`} mono />
          <Row k="From" v={`${trip.from_location || "—"}${trip.from_pincode ? ` (${trip.from_pincode})` : ""}`} />
          <Row k="To" v={`${trip.to_location || "—"}${trip.to_pincode ? ` (${trip.to_pincode})` : ""}`} />
        </Grid2>
      </Section>

      {/* Freight (Customer Billing) */}
      <Section title="Customer Freight · బిల్లింగ్">
        <Grid2>
          <Row k="Freight Mode" v={trip.freight_mode === "per_ton" ? "Per Ton" : "Round Trip / Fixed"} />
          {trip.freight_mode === "per_ton" ? (
            <Row k="Rate per Ton" v={`₹ ${Number(trip.rate_per_ton || 0).toFixed(2)}`} mono />
          ) : (
            <>
              <Row k="Round Trip KMs" v={Number(trip.round_trip_kms || 0).toFixed(2)} mono />
              <Row k="Rate ₹/ton/km" v={Number(trip.rate_per_km_per_ton || 0).toFixed(2)} mono />
              <Row k="Fixed Amount" v={`₹ ${Number(trip.fixed_amount || 0).toFixed(2)}`} mono />
            </>
          )}
          <Row k="Freight Amount" v={fmtCurrency(trip.freight_amount)} mono strong />
        </Grid2>
      </Section>

      {/* Supplier detailed section */}
      {isSupplier && (
        <Section title="Supplier Freight & Settlement · సప్లయర్ వివరాలు">
          <Grid2>
            <Row k="Supplier Name" v={trip.supplier_name || "—"} />
            <Row k="Loading Point" v={trip.supplier_loading_point || trip.from_location || "—"} />
            <Row k="Unloading Point" v={trip.supplier_unloading_point || trip.to_location || "—"} />
            <Row k="Material" v={trip.supplier_material || trip.load_details || "—"} />
            <Row k="Quantity (MT)" v={Number(trip.supplier_quantity || trip.tons || 0).toFixed(2)} mono />
            <Row k="Freight Mode" v={trip.supplier_freight_mode === "per_ton" ? "Per Ton" : "Round Trip / Fixed"} />
            {trip.supplier_freight_mode === "per_ton" ? (
              <Row k="Supplier Rate / MT" v={`₹ ${Number(trip.supplier_rate_per_ton || 0).toFixed(2)}`} mono />
            ) : (
              <>
                <Row k="Distance (KMs)" v={Number(trip.supplier_round_trip_kms || 0).toFixed(2)} mono />
                <Row k="Rate ₹/ton/km" v={Number(trip.supplier_rate_per_km_per_ton || 0).toFixed(2)} mono />
                <Row k="Fixed Amount" v={`₹ ${Number(trip.supplier_fixed_amount || 0).toFixed(2)}`} mono />
              </>
            )}
            <Row k="Supplier Freight" v={fmtCurrency(supFreight)} mono strong />
            <Row k="Less: Advance Paid" v={fmtCurrency(supAdvance)} mono />
            <Row k="Less: Other Recoveries" v={fmtCurrency(supOther)} mono />
          </Grid2>
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="border border-rose-200 bg-rose-50 p-3 rounded-sm">
              <div className="text-[10px] uppercase tracking-wider text-zinc-600 font-bold">Net Amount Payable to Supplier</div>
              <div className="font-mono text-2xl font-bold text-rose-800">{fmtCurrency(netPayable)}</div>
              <div className="text-[10px] text-zinc-500 mt-1">Freight − Advance − Other Recoveries</div>
            </div>
            <div className={`border p-3 rounded-sm ${supplierProfit >= 0 ? "border-emerald-300 bg-emerald-50" : "border-rose-300 bg-rose-50"}`}>
              <div className="text-[10px] uppercase tracking-wider text-zinc-600 font-bold">Trip Profit</div>
              <div className={`font-mono text-2xl font-bold ${supplierProfit >= 0 ? "text-emerald-800" : "text-rose-800"}`}>{fmtCurrency(supplierProfit)}</div>
              <div className="text-[10px] text-zinc-500 mt-1">Customer Freight − (Supplier Freight − Advance)</div>
            </div>
          </div>
        </Section>
      )}

      {/* Expenses (own trips) */}
      {!isSupplier && (
        <Section title="Expenses · ఖర్చులు">
          <Grid2>
            <Row k="Diesel" v={fmtCurrency(e.diesel)} mono />
            <Row k="Toll" v={fmtCurrency(e.toll)} mono />
            <Row k="Driver Batta" v={fmtCurrency(e.batta)} mono />
            <Row k="Repair" v={fmtCurrency(e.repair)} mono />
            <Row k="Firewood" v={fmtCurrency(e.firewood)} mono />
            <Row k={`Other (${e.other_desc || "—"})`} v={fmtCurrency(e.other)} mono />
            <Row k="Diesel from Customer" v={fmtCurrency(e.diesel_from_customer_amount)} mono />
            <Row k="Shortage Qty / Amt" v={`${Number(e.shortage_qty || 0)} · ${fmtCurrency(e.shortage_amount)}`} mono />
            <Row k="Cash Advance Received" v={fmtCurrency(e.cash_advance_received)} mono />
            <Row k="Total Expense" v={fmtCurrency(trip.total_expense)} mono strong />
          </Grid2>
        </Section>
      )}

      {/* Invoice */}
      <Section title="Invoice Details · ఇన్వాయిస్">
        {invoice ? (
          <div className="space-y-3">
            <Grid2>
              <Row k="Invoice Number" v={invoice.invoice_number} mono />
              <Row k="Invoice Date" v={fmtDate(invoice.invoice_date)} />
              <Row k="Total Amount" v={fmtCurrency(invoice.total_amount)} mono strong />
              <Row k="Received" v={fmtCurrency(invoice.amount_paid)} mono />
              <Row k="Balance Due" v={fmtCurrency(invoice.balance_due)} mono strong />
              <Row k="GST" v={invoice.rcm ? "RCM (Reverse Charge)" : (invoice.gst_type === "igst" ? "IGST 5%" : "CGST+SGST 5%")} />
            </Grid2>
            <Link to={`/invoices/${invoice.id}`} data-testid="trip-view-open-invoice"
                  className="inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider border border-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white">
              <ExternalLink size={14} /> Open Invoice
            </Link>
          </div>
        ) : (
          <div className="text-sm text-zinc-500">This trip is not yet invoiced.</div>
        )}
      </Section>

      {/* LR Fields */}
      {(trip.lr_number || trip.external_invoice_no || trip.waybill_no || trip.gross_weight) && (
        <Section title="LR / Weighbridge">
          <Grid2>
            <Row k="LR Number" v={trip.lr_number || "—"} mono />
            <Row k="LR Time" v={trip.lr_time || "—"} />
            <Row k="External Invoice #" v={trip.external_invoice_no || "—"} />
            <Row k="Customer Invoice #" v={trip.customer_invoice_no || "—"} />
            <Row k="Purchased At" v={trip.customer_purchased_at || "—"} />
            <Row k="Invoice Value" v={fmtCurrency(trip.invoice_value)} mono />
            <Row k="Waybill No" v={trip.waybill_no || "—"} />
            <Row k="Gross Wt" v={`${Number(trip.gross_weight || 0).toFixed(3)} MT`} mono />
            <Row k="Tare Wt" v={`${Number(trip.tare_weight || 0).toFixed(3)} MT`} mono />
            <Row k="Seal Numbers" v={trip.seal_numbers || "—"} />
          </Grid2>
        </Section>
      )}

      {trip.notes && (
        <Section title="Notes · గమనికలు">
          <div className="text-sm whitespace-pre-wrap">{trip.notes}</div>
        </Section>
      )}

      <Section title="Attachments">
        <FileAttachments linkedType="trip" linkedId={trip.id} category="trip_attachment" title="Trip Files" />
      </Section>
    </div>
  );
}

function Stat({ label, value, accent }) {
  const cls = accent === "emerald" ? "border-emerald-300 bg-emerald-50 text-emerald-800"
    : accent === "rose" ? "border-rose-300 bg-rose-50 text-rose-800"
    : accent === "amber" ? "border-amber-300 bg-amber-50 text-amber-800"
    : "border-zinc-200 bg-white";
  return (
    <div className={`border p-3 rounded-sm ${cls}`}>
      <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">{label}</div>
      <div className="font-mono text-lg font-bold mt-1">{value}</div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <section className="border border-zinc-200 bg-white rounded-sm">
      <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">{title}</div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function Grid2({ children }) {
  return <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 text-sm">{children}</div>;
}

function Row({ k, v, mono, strong }) {
  return (
    <div className="flex justify-between border-b border-zinc-100 py-1.5">
      <span className="text-zinc-500 text-[11px] uppercase tracking-wider font-semibold">{k}</span>
      <span className={`${mono ? "font-mono" : ""} ${strong ? "font-bold" : ""}`}>{v}</span>
    </div>
  );
}
