// Iter55/101 — LR Section with Preview + Download always available.
// Preview works during Trip Creation via POST /api/trips/lr/preview (no persist).
// After Save (isEdit), the Download button hits the persistent GET
// /api/trips/{tid}/lr endpoint that auto-assigns a real LR series number.
import React, { useState } from "react";
import { FileText, Eye, Loader2 } from "lucide-react";
import { Section, Field } from "./FormPrimitives";
import { inputCls } from "./tripFormDefaults";
import { openTripLrPdf, previewLrFromDraft } from "@/utils/pdfDownload";

export default function LRSection({ form, setForm, isEdit, id }) {
  const [busy, setBusy] = useState(""); // "" | "preview" | "download"
  const [lrCopy, setLrCopy] = useState("original"); // Iter115 · which copy stamp

  const runPreview = async () => {
    setBusy("preview");
    try {
      await previewLrFromDraft(form);
    } finally {
      setBusy("");
    }
  };

  const runDownload = async ({ copy = "original" } = {}) => {
    setBusy("download");
    try {
      const suffix = copy !== "original" ? `_${copy.toUpperCase()}` : "";
      await openTripLrPdf(id, `LR_${form.lr_number || id}${suffix}.pdf`, { copy });
    } finally {
      setBusy("");
    }
  };

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

      <div className="mt-5 border-t border-zinc-200 pt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          data-testid="preview-lr-btn"
          disabled={!!busy}
          onClick={runPreview}
          className="inline-flex items-center gap-2 px-4 py-2 text-xs uppercase tracking-wider font-semibold border-2 border-amber-700 text-amber-800 bg-amber-50 rounded-sm hover:bg-amber-100 disabled:opacity-50"
        >
          {busy === "preview" ? <Loader2 size={14} className="animate-spin" /> : <Eye size={14} />}
          Preview LR (before Save)
        </button>
        {isEdit && (
          <>
            <select
              data-testid="lr-copy-select"
              value={lrCopy}
              onChange={(e) => setLrCopy(e.target.value)}
              disabled={!!busy}
              className="px-3 py-2 text-xs uppercase tracking-wider font-semibold border border-zinc-950 bg-white text-zinc-950 rounded-sm disabled:opacity-50"
              title="Choose which copy of the LR to download"
            >
              <option value="original">Original · Consignee</option>
              <option value="duplicate">Duplicate · Transporter</option>
              <option value="triplicate">Triplicate · Consignor</option>
            </select>
            <button
              type="button"
              data-testid="download-lr-btn"
              disabled={!!busy}
              onClick={() => runDownload({ copy: lrCopy })}
              className="inline-flex items-center gap-2 px-4 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50"
            >
              {busy === "download" ? <Loader2 size={14} className="animate-spin" /> : <FileText size={14} />}
              Download LR PDF
            </button>
          </>
        )}
        <span className="text-[11px] text-zinc-500">
          Preview renders the LR without saving — use it to verify all fields before finalising the trip.
          {isEdit ? "" : " Download activates after Save (auto-assigns the LR series number)."}
        </span>
      </div>
    </Section>
  );
}
