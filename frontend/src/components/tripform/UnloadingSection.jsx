// Iter55 — Extracted verbatim from TripForm.jsx. Pure JSX.
import React from "react";
import { Section, Field } from "./FormPrimitives";
import { inputCls } from "./tripFormDefaults";

export default function UnloadingSection({
  form, setForm,
  shortageQtyLive, excessQtyLive,
  shortageAmountLive, excessAmountLive,
}) {
  return (
    <Section title="Unloading Details · అన్‌లోడ్">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Field label="Unloading Date">
          <input data-testid="trip-unloading-date" type="date" value={form.unloading_date} onChange={(e) => setForm({ ...form, unloading_date: e.target.value })} className={inputCls} />
        </Field>
        <Field label="Loading Qty (MT) · from Trip Details">
          <input
            data-testid="trip-loaded-qty"
            type="number"
            step="0.001"
            min="0"
            value={Number(form.tons || 0)}
            readOnly
            className={`${inputCls} bg-zinc-100 cursor-not-allowed text-zinc-700 font-mono`}
            title="Auto-synced from 'Loading Qty (in Tons)' in Trip Details. Edit that field to change."
          />
        </Field>
        <Field label="Unloaded Qty (MT)">
          <input data-testid="trip-unloaded-qty" type="number" step="0.001" min="0" value={form.unloaded_qty} onChange={(e) => setForm({ ...form, unloaded_qty: e.target.value })} className={inputCls} />
        </Field>
        <Field label="Product Rate (₹ / MT)">
          <input data-testid="trip-product-rate" type="number" step="0.01" min="0" value={form.product_rate_per_mt} onChange={(e) => setForm({ ...form, product_rate_per_mt: e.target.value, shortage_amount_override: false, excess_amount_override: false })} className={inputCls} placeholder="Optional" />
        </Field>
        <div className="border border-zinc-200 p-2 rounded-sm text-center">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Shortage Qty</div>
          <div className="font-mono text-sm font-bold text-rose-700">{shortageQtyLive.toFixed(3)} MT</div>
        </div>
        <div className="border border-zinc-200 p-2 rounded-sm text-center">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Excess Qty</div>
          <div className="font-mono text-sm font-bold text-emerald-700">{excessQtyLive.toFixed(3)} MT</div>
        </div>
        <Field label={
          <span>Shortage Amount (₹) <button type="button" onClick={() => setForm({ ...form, shortage_amount_override: !form.shortage_amount_override })} className={`ml-1 text-[9px] uppercase tracking-wider ${form.shortage_amount_override ? "text-amber-700" : "text-zinc-400"}`}>{form.shortage_amount_override ? "manual" : "auto"}</button></span>
        }>
          <input data-testid="trip-shortage-amount" type="number" step="0.01" min="0" value={form.shortage_amount_override ? form.shortage_amount : shortageAmountLive} disabled={!form.shortage_amount_override} onChange={(e) => setForm({ ...form, shortage_amount: e.target.value })} className={`${inputCls} disabled:bg-zinc-50 disabled:text-zinc-600`} />
        </Field>
        <Field label={
          <span>Excess Amount (₹) <button type="button" onClick={() => setForm({ ...form, excess_amount_override: !form.excess_amount_override })} className={`ml-1 text-[9px] uppercase tracking-wider ${form.excess_amount_override ? "text-amber-700" : "text-zinc-400"}`}>{form.excess_amount_override ? "manual" : "auto"}</button></span>
        }>
          <input data-testid="trip-excess-amount" type="number" step="0.01" min="0" value={form.excess_amount_override ? form.excess_amount : excessAmountLive} disabled={!form.excess_amount_override} onChange={(e) => setForm({ ...form, excess_amount: e.target.value })} className={`${inputCls} disabled:bg-zinc-50 disabled:text-zinc-600`} />
        </Field>
      </div>
      <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
        <Field label="Shortage — Remarks">
          <input data-testid="trip-shortage-remarks" value={form.shortage_remarks} onChange={(e) => setForm({ ...form, shortage_remarks: e.target.value })} className={inputCls} placeholder="Cause / reference (optional)" />
        </Field>
        <Field label="Excess — Remarks">
          <input data-testid="trip-excess-remarks" value={form.excess_remarks} onChange={(e) => setForm({ ...form, excess_remarks: e.target.value })} className={inputCls} placeholder="Cause / reference (optional)" />
        </Field>
      </div>
    </Section>
  );
}
