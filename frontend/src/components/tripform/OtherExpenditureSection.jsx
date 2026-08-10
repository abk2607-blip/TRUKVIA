// Iter55 — Extracted verbatim from TripForm.jsx. Pure JSX.
import React from "react";
import { Section, Field } from "./FormPrimitives";
import { inputCls } from "./tripFormDefaults";
import OtherExpenditures from "./OtherExpenditures";

export default function OtherExpenditureSection({
  form, setForm, expenditureTypes, onCreateType,
}) {
  return (
    <Section title="Other Expenditure · ఇతర ఖర్చులు">
      <div className="text-[11px] text-zinc-500 mb-3 bg-amber-50 border border-amber-200 rounded-sm p-2">
        <span className="font-bold">Note:</span> Customer Diesel &amp; Advance are managed in <em>"Received From Customer"</em> above. This section is for miscellaneous trip expenditures (Driver Food, Parking, Toll, Loading Charges, Unloading Charges, Weighment, Labour, etc.).
      </div>
      <OtherExpenditures
        rows={form.other_expenditures || []}
        types={expenditureTypes}
        onChange={(list) => setForm({ ...form, other_expenditures: list })}
        onCreateType={onCreateType}
      />

      {/* Other Income (₹) with remarks */}
      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3 border-t border-zinc-200 pt-4">
        <Field label="Other Income (₹) — Miscellaneous">
          <input data-testid="trip-other-income" type="number" step="0.01" min="0" value={form.other_income} onChange={(e) => setForm({ ...form, other_income: e.target.value })} className={inputCls} placeholder="Detention income, misc bonus, etc." />
        </Field>
        <Field label="Other Income — Remarks">
          <input data-testid="trip-other-income-remarks" value={form.other_income_remarks} onChange={(e) => setForm({ ...form, other_income_remarks: e.target.value })} className={inputCls} placeholder="Reason / context (optional)" />
        </Field>
      </div>
    </Section>
  );
}
