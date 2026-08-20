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
    // Iter55 fix: dedicated GET (list is capped at 2000; newer trips were invisible)
    queryFn: async () => (await api.get(`/trips/${id}`)).data,
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
  const supDiesel = Number(trip.supplier_diesel || 0);
  const supShortage = Number(trip.supplier_shortage_deduction || 0);
  const supOther = Number(trip.supplier_other_recoveries || 0);
  const supIncome = Number(trip.supplier_other_income || 0);
  const customerDieselAdj = Number(trip.customer_diesel_received || 0);
  // Iter64 fix — prefer SERVER-computed values (single source of truth). Local
  // recompute is kept only as a graceful fallback for older trips where the
  // server may not have persisted these keys yet.  Formula matches
  // services.compute_totals exactly (includes customer_diesel_received).
  const netPayable = trip.supplier_net_payable != null
    ? Number(trip.supplier_net_payable)
    : (supFreight - supAdvance - supDiesel - customerDieselAdj - supShortage - supOther + supIncome);
  const supplierProfit = trip.profit != null && isSupplier
    ? Number(trip.profit)
    : (Number(trip.freight_amount || 0) - netPayable);
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

      {/* Iter64 · Priority 1 — Supplier Trip Summary Chip.
          All figures read straight from the server-computed trip (services.compute_totals) —
          no re-calculation happens here so it can never drift from the Supplier Statement. */}
      {isSupplier && (
        <section
          data-testid="supplier-trip-summary-chip"
          className="border border-amber-300 bg-amber-50/60 rounded-sm px-4 py-3"
        >
          <div className="flex items-center justify-between border-b border-amber-200 pb-2 mb-2">
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase tracking-[0.15em] font-bold text-amber-900">Supplier Settlement · Compact Summary</span>
              <span data-testid="stsc-supplier-name" className="text-xs font-bold text-zinc-950">{trip.supplier_name || "—"}</span>
            </div>
            <div className="text-[10px] text-amber-800">
              Same figures shown in Reports → Supplier Statement · <span className="font-semibold">no separate calculation</span>
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-x-4 gap-y-2 text-xs">
            <ChipRow tid="stsc-actual-freight" label="Actual Freight" value={trip.freight_amount} />
            <ChipRow tid="stsc-supplier-freight" label="Supplier Freight" value={supFreight} />
            <ChipRow tid="stsc-supplier-advance" label="Supplier Advance" value={-supAdvance} kind="debit" />
            <ChipRow tid="stsc-supplier-diesel" label="Supplier Diesel" value={-supDiesel} kind="debit" />
            <ChipRow tid="stsc-customer-diesel-adj" label="Customer Diesel Adj." value={-Number(trip.customer_diesel_received || 0)} kind="debit" />
            <ChipRow tid="stsc-other-deductions" label="Other Deductions" value={-(supShortage + supOther)} kind="debit" />
            <ChipRow tid="stsc-other-additions" label="Other Additions" value={supIncome} kind="credit" />
            <ChipRow tid="stsc-final-payable" label="Final Supplier Payable" value={netPayable} kind="total" />
            <ChipRow tid="stsc-supplier-profit" label="Supplier Profit (Ours)" value={supplierProfit} kind={supplierProfit >= 0 ? "profit" : "loss"} />
          </div>
        </section>
      )}

      {/* Customer */}
      <Section title="Customer · కస్టమర్">
        <Grid2>
          <Row k="Name" v={customer.name || "—"} />
          <Row k="Phone" v={customer.phone || "—"} />
          <Row k="GSTIN" v={customer.gstin || "—"} />
          <Row k="Address" v={customer.address || "—"} />
          <Row k="State / Pincode" v={`${customer.state || "—"} · ${customer.pincode || "—"}`} />
          <Row k="Customer Ref No." v={<span data-testid="tripview-customer-ref">{trip.customer_reference_number || "—"}</span>} strong />
        </Grid2>
      </Section>

      {/* Iter66 · Phase C — Ship-To Site */}
      {(() => {
        const site = (customer.ship_sites || []).find((s) => s.id === trip.ship_site_id);
        if (!site && !trip.ship_site_id) return null;   // no site selected — fallback = to_location shown in Load & Route
        return (
          <Section title="Ship-To · అన్‌లోడింగ్ సైట్">
            <Grid2>
              <Row k="Site Name" v={<span data-testid="tripview-ship-site-name">{site?.site_name || (trip.ship_site_id ? "(site removed)" : trip.to_location || "—")}</span>} strong />
              <Row k="Contact" v={site?.contact_person || "—"} />
              <Row k="Phone" v={site?.phone || "—"} />
              <Row k="GSTIN" v={site?.gstin || customer.gstin || "—"} />
              <Row k="Address" v={<span data-testid="tripview-ship-site-address">{site?.address || trip.to_location || "—"}</span>} />
              <Row k="State / Pincode" v={`${site?.state || "—"} · ${site?.pincode || "—"}`} />
            </Grid2>
          </Section>
        );
      })()}

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

      {/* Loading / Unloading — always render */}
      <Section title="Loading & Unloading · లోడ్/అన్‌లోడ్">
        <Grid2>
          <Row k="Loading Date" v={trip.loading_date ? fmtDate(trip.loading_date) : "—"} />
          <Row k="Unloading Date" v={trip.unloading_date ? fmtDate(trip.unloading_date) : "—"} />
          <Row k="Loaded Qty" v={`${Number(trip.loaded_qty || 0).toFixed(3)} MT`} mono />
          <Row k="Unloaded Qty" v={`${Number(trip.unloaded_qty || 0).toFixed(3)} MT`} mono />
          <Row k="Shortage Qty" v={`${Number(trip.shortage_qty || 0).toFixed(3)} MT`} mono />
          <Row k="Excess Qty" v={`${Number(trip.excess_qty || 0).toFixed(3)} MT`} mono />
          <Row k="Product Rate" v={trip.product_rate_per_mt ? `₹ ${Number(trip.product_rate_per_mt).toFixed(2)} / MT` : "—"} mono />
          <Row k="Shortage Amount" v={fmtCurrency(trip.shortage_amount)} mono strong />
          <Row k="Excess Amount" v={fmtCurrency(trip.excess_amount)} mono strong />
        </Grid2>
      </Section>

      {/* Halting Charges — always render */}
      <Section title="Halting / Waiting Charges · హాల్టింగ్">
        <Grid2>
          <Row k="Total Days" v={trip.total_halting_days || 0} mono />
          <Row k="Grace Days" v={trip.grace_days || 4} mono />
          <Row k="Chargeable Days" v={trip.chargeable_halting_days || 0} mono />
          <Row k="Halting Rate / Day" v={fmtCurrency(trip.halting_rate_per_day)} mono />
          <Row k="Halting Amount" v={fmtCurrency(trip.halting_amount)} mono strong />
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

      {/* Supplier detailed section — always render for supplier vehicles */}
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
            <Row k="Less: Diesel Funded" v={fmtCurrency(trip.supplier_diesel)} mono />
            <Row k="Less: Shortage Deduction" v={fmtCurrency(trip.supplier_shortage_deduction)} mono />
            <Row k="Less: Other Recoveries" v={fmtCurrency(supOther)} mono />
            <Row k="Add: Other Income / Bonus" v={fmtCurrency(trip.supplier_other_income)} mono />
          </Grid2>

          {/* Iter91 — Multi-row Diesel + Advance breakdown */}
          <SupplierEntriesReadOnly title="Diesel Entries" kind="diesel"
            entries={(trip.supplier_diesel_entries || []).filter((e) => !e.deleted)} />
          <SupplierEntriesReadOnly title="Advance Entries" kind="advance"
            entries={(trip.supplier_advance_entries || []).filter((e) => !e.deleted)} />
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="border border-rose-200 bg-rose-50 p-3 rounded-sm">
              <div className="text-[10px] uppercase tracking-wider text-zinc-600 font-bold">Net Amount Payable to Supplier</div>
              <div className="font-mono text-2xl font-bold text-rose-800">{fmtCurrency(netPayable)}</div>
              <div className="text-[10px] text-zinc-500 mt-1">Freight − Advance − Diesel − Shortage − Recoveries + Income</div>
            </div>
            <div className={`border p-3 rounded-sm ${supplierProfit >= 0 ? "border-emerald-300 bg-emerald-50" : "border-rose-300 bg-rose-50"}`}>
              <div className="text-[10px] uppercase tracking-wider text-zinc-600 font-bold">Trip Profit</div>
              <div className={`font-mono text-2xl font-bold ${supplierProfit >= 0 ? "text-emerald-800" : "text-rose-800"}`}>{fmtCurrency(supplierProfit)}</div>
              <div className="text-[10px] text-zinc-500 mt-1">Customer Freight − Net Payable</div>
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

      {/* LR / Weighbridge / Consignor — always render */}
      <Section title="LR / Weighbridge / Consignor">
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
          <Row k="Consignor" v={trip.consignor_name || "—"} />
          <Row k="Consignor Address" v={trip.consignor_address || "—"} />
          <Row k="Site Location" v={trip.consignee_site_location || "—"} />
          <Row k="Site Contact" v={trip.consignee_site_contact || "—"} />
        </Grid2>
      </Section>

      <Section title="Notes · గమనికలు">
        <div className="text-sm whitespace-pre-wrap">{trip.notes || <span className="text-zinc-400">—</span>}</div>
      </Section>

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

// Iter64 · Priority 1 — Compact row for the Supplier Trip Summary Chip.
function ChipRow({ tid, label, value, kind }) {
  const cls = {
    debit: "text-rose-700",
    credit: "text-emerald-700",
    total: "text-zinc-950 font-bold",
    profit: "text-emerald-800 font-bold",
    loss: "text-rose-800 font-bold",
  }[kind] || "text-zinc-800";
  return (
    <div className="flex justify-between items-baseline gap-2" data-testid={tid}>
      <span className="text-[10px] uppercase tracking-wider text-zinc-600 truncate">{label}</span>
      <span className={`font-mono tabular-nums ${cls}`}>{fmtCurrency(value)}</span>
    </div>
  );
}


// Iter91 — Read-only Diesel / Advance entries table for the Supplier section.
function SupplierEntriesReadOnly({ title, kind, entries }) {
  if (!entries || entries.length === 0) return null;
  const isDiesel = kind === "diesel";
  const total = entries.reduce((s, e) => s + Number(e.amount || 0), 0);
  return (
    <div className="mt-4 border border-zinc-200 rounded-sm" data-testid={`tv-sup-${kind}-block`}>
      <div className="px-3 py-2 border-b border-zinc-200 text-[10px] uppercase tracking-wider font-bold text-zinc-600 bg-zinc-50">
        {title} · {entries.length} row{entries.length > 1 ? "s" : ""}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-[10px] uppercase text-zinc-500">
            <tr className="border-b border-zinc-200">
              <th className="text-left py-1.5 px-3">Date</th>
              {isDiesel && <th className="text-right py-1.5 px-3">Qty (L)</th>}
              {isDiesel && <th className="text-right py-1.5 px-3">Rate</th>}
              <th className="text-right py-1.5 px-3">Amount</th>
              <th className="text-left py-1.5 px-3">Mode</th>
              <th className="text-left py-1.5 px-3">Reference</th>
              <th className="text-left py-1.5 px-3">Remarks</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id} className="border-b border-zinc-100">
                <td className="py-1.5 px-3 font-mono">{e.date || "—"}</td>
                {isDiesel && <td className="py-1.5 px-3 text-right font-mono">{Number(e.quantity || 0) || "—"}</td>}
                {isDiesel && <td className="py-1.5 px-3 text-right font-mono">{Number(e.rate || 0) || "—"}</td>}
                <td className="py-1.5 px-3 text-right font-mono font-bold">{`₹ ${Number(e.amount || 0).toFixed(2)}`}</td>
                <td className="py-1.5 px-3">{e.mode || "—"}</td>
                <td className="py-1.5 px-3">{e.reference || "—"}</td>
                <td className="py-1.5 px-3">{e.remarks || "—"}</td>
              </tr>
            ))}
            <tr className="bg-zinc-50 font-bold">
              <td colSpan={isDiesel ? 3 : 1} className="py-2 px-3 text-right uppercase text-[10px] tracking-wider">Total</td>
              <td className="py-2 px-3 text-right font-mono">{`₹ ${total.toFixed(2)}`}</td>
              <td colSpan={3}></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
