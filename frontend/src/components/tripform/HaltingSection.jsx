// Iter55 — Extracted verbatim from TripForm.jsx. Pure JSX.
import React from "react";
import { Section, Field } from "./FormPrimitives";
import { inputCls } from "./tripFormDefaults";

export default function HaltingSection({
  form, setForm,
  datesPresent, totalHaltingDaysLive, autoChargeableDays, haltingAmountLive,
}) {
  return (
    <Section title="Halting / Waiting Charges · హాల్టింగ్">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {datesPresent ? (
          <div className="border border-zinc-200 p-2 rounded-sm text-center">
            <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Total Days</div>
            <div className="font-mono text-lg font-bold" data-testid="trip-total-halting-days-auto">{totalHaltingDaysLive}</div>
            <div className="text-[9px] text-zinc-400 mt-0.5">Auto from Loading/Unloading dates</div>
          </div>
        ) : (
          <Field label={<span>Total Halting Days <span className="text-[9px] text-amber-700 uppercase">manual</span></span>}>
            <input data-testid="trip-total-halting-days" type="number" min="0" step="1"
              value={form.total_halting_days || 0}
              onChange={(e) => setForm({ ...form, total_halting_days: e.target.value, halting_amount_override: false })}
              className={inputCls}
              placeholder="Or enter Loading + Unloading dates"
            />
          </Field>
        )}
        <Field label="Grace Days">
          <input data-testid="trip-grace-days" type="number" min="0" step="1" value={form.grace_days} onChange={(e) => setForm({ ...form, grace_days: e.target.value, halting_amount_override: false })} className={inputCls} />
        </Field>
        <Field label={
          <span>Chargeable Days <button type="button" onClick={() => setForm({ ...form, halting_amount_override: !form.halting_amount_override })} className={`ml-1 text-[9px] uppercase tracking-wider ${form.halting_amount_override ? "text-amber-700" : "text-zinc-400"}`}>{form.halting_amount_override ? "manual" : "auto"}</button></span>
        }>
          <input data-testid="trip-chargeable-days" type="number" min="0" step="1" value={form.halting_amount_override ? form.chargeable_halting_days : autoChargeableDays} disabled={!form.halting_amount_override} onChange={(e) => setForm({ ...form, chargeable_halting_days: e.target.value })} className={`${inputCls} disabled:bg-zinc-50 disabled:text-zinc-600`} />
        </Field>
        <Field label="Halting Rate (₹ / Day)">
          <input data-testid="trip-halting-rate" type="number" step="0.01" min="0" value={form.halting_rate_per_day} onChange={(e) => setForm({ ...form, halting_rate_per_day: e.target.value, halting_amount_override: false })} className={inputCls} />
        </Field>
        <Field label={
          <span>Halting Amount (₹) <span className={`ml-1 text-[9px] uppercase tracking-wider ${form.halting_amount_override ? "text-amber-700" : "text-zinc-400"}`}>{form.halting_amount_override ? "manual" : "auto"}</span></span>
        }>
          <input data-testid="trip-halting-amount" type="number" step="0.01" min="0" value={form.halting_amount_override ? form.halting_amount : haltingAmountLive} disabled={!form.halting_amount_override} onChange={(e) => setForm({ ...form, halting_amount: e.target.value })} className={`${inputCls} disabled:bg-zinc-50 disabled:text-zinc-600 font-bold`} />
        </Field>
      </div>
      <div className="mt-3 text-[11px] text-zinc-500 bg-amber-50 border border-amber-200 rounded-sm p-2">
        <span className="font-bold">Formula:</span> Halting = Chargeable Days × Rate.
        {" "}Provide <b>Loading Date + Unloading Date</b> in Trip Details for automatic Total Days —
        {" "}or type Total Days directly above when dates are unknown. Grace of {form.grace_days || 4} days is deducted.
      </div>
      <div className="mt-3">
        <Field label="Halting — Remarks">
          <input data-testid="trip-halting-remarks" value={form.halting_remarks} onChange={(e) => setForm({ ...form, halting_remarks: e.target.value })} className={inputCls} placeholder="Detention reason / site details (optional)" />
        </Field>
      </div>
    </Section>
  );
}
