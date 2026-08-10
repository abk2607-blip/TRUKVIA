// Iter55 — Extracted verbatim from TripForm.jsx. Pure JSX.
import React from "react";
import { FileText } from "lucide-react";
import { API } from "@/api";
import { Section, Field } from "./FormPrimitives";
import { inputCls } from "./tripFormDefaults";

export default function LRSection({ form, setForm, isEdit, id }) {
  return (
    <Section title="LR / Lorry Receipt (Optional)">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Field label="LR Number (auto)">
          <input data-testid="trip-lr-number" value={form.lr_number} onChange={(e) => setForm({ ...form, lr_number: e.target.value })} className={inputCls} placeholder="Leave blank for auto-generation" />
        </Field>
        <Field label="LR Time">
          <input data-testid="trip-lr-time" type="time" value={form.lr_time} onChange={(e) => setForm({ ...form, lr_time: e.target.value })} className={inputCls} />
        </Field>
        <Field label="External Invoice # (BPCL/HPCL)">
          <input data-testid="trip-ext-invoice" value={form.external_invoice_no} onChange={(e) => setForm({ ...form, external_invoice_no: e.target.value })} className={inputCls} placeholder="MUM-26-27-00220" />
        </Field>
        <Field label="Customer Invoice #">
          <input data-testid="trip-cust-invoice" value={form.customer_invoice_no} onChange={(e) => setForm({ ...form, customer_invoice_no: e.target.value })} className={inputCls} />
        </Field>
        <Field label="Customer Purchased At">
          <input data-testid="trip-purchased-at" value={form.customer_purchased_at} onChange={(e) => setForm({ ...form, customer_purchased_at: e.target.value })} className={inputCls} placeholder="e.g. HPCL Kondapalli" />
        </Field>
        <Field label="Invoice Value (₹)">
          <input data-testid="trip-invoice-value" type="number" step="0.01" min="0" value={form.invoice_value} onChange={(e) => setForm({ ...form, invoice_value: e.target.value })} className={inputCls} />
        </Field>
        <Field label="Waybill No.">
          <input data-testid="trip-waybill" value={form.waybill_no} onChange={(e) => setForm({ ...form, waybill_no: e.target.value })} className={inputCls} />
        </Field>
        <Field label="Consignor Name">
          <input data-testid="trip-consignor" value={form.consignor_name} onChange={(e) => setForm({ ...form, consignor_name: e.target.value })} className={inputCls} placeholder="BPCL - Mumbai" />
        </Field>
        <Field label="Consignee Site Location">
          <input data-testid="trip-site-loc" value={form.consignee_site_location} onChange={(e) => setForm({ ...form, consignee_site_location: e.target.value })} className={inputCls} />
        </Field>
        <Field label="Site Contact Person">
          <input data-testid="trip-site-contact" value={form.consignee_site_contact} onChange={(e) => setForm({ ...form, consignee_site_contact: e.target.value })} className={inputCls} placeholder="Name & phone" />
        </Field>
        <Field label="Gross Wt (MT)">
          <input data-testid="trip-gross-wt" type="number" step="0.001" min="0" value={form.gross_weight} onChange={(e) => setForm({ ...form, gross_weight: e.target.value })} className={inputCls} />
        </Field>
        <Field label="Tare Wt (MT)">
          <input data-testid="trip-tare-wt" type="number" step="0.001" min="0" value={form.tare_weight} onChange={(e) => setForm({ ...form, tare_weight: e.target.value })} className={inputCls} />
        </Field>
        <Field label="Seal Numbers">
          <input data-testid="trip-seal" value={form.seal_numbers} onChange={(e) => setForm({ ...form, seal_numbers: e.target.value })} className={inputCls} placeholder="SL-001, SL-002" />
        </Field>
        <Field label={<span>Driver Name (LR) <span className="text-[9px] text-zinc-400">auto from Trip · editable</span></span>}>
          <input data-testid="trip-lr-driver-name" value={form.lr_driver_name} onChange={(e) => setForm({ ...form, lr_driver_name: e.target.value })} className={inputCls} placeholder={form.driver_name || "Enter driver name"} />
        </Field>
        <Field label={<span>Driver Mobile (LR) <span className="text-[9px] text-zinc-400">auto from Trip · editable</span></span>}>
          <input data-testid="trip-driver-mobile" value={form.lr_driver_mobile} onChange={(e) => setForm({ ...form, lr_driver_mobile: e.target.value })} className={inputCls} placeholder={form.driver_mobile || "98xxxxxxxx"} />
        </Field>
        <Field label="From Pincode">
          <input data-testid="trip-from-pin" value={form.from_pincode} onChange={(e) => setForm({ ...form, from_pincode: e.target.value })} className={inputCls} />
        </Field>
        <Field label="To Pincode">
          <input data-testid="trip-to-pin" value={form.to_pincode} onChange={(e) => setForm({ ...form, to_pincode: e.target.value })} className={inputCls} />
        </Field>
      </div>
      {isEdit && (
        <div className="mt-4">
          <a data-testid="download-lr-btn" href={`${API}/trips/${id}/lr`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800">
            <FileText size={14} /> Download LR PDF
          </a>
          <span className="ml-2 text-xs text-zinc-500">Auto-assigns an LR number on first download.</span>
        </div>
      )}
    </Section>
  );
}
