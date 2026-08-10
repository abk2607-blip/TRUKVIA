// Iter55 — Extracted verbatim from TripForm.jsx. Pure JSX.
import React from "react";
import { fmtCurrency } from "@/api";
import SearchableSelect from "@/components/SearchableSelect";
import { Section, Field } from "./FormPrimitives";
import { inputCls } from "./tripFormDefaults";

export default function SupplierSection({
  form, setForm, suppliers,
  supplierFreightLive, supplierNetPayable, supplierProfit,
}) {
  return (
    <Section title="Supplier Vehicle · సప్లయర్ వాహనం">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Field label="Supplier · సప్లయర్" required>
          <SearchableSelect
            dataTestId="trip-supplier-picker"
            value={form.supplier_id || ""}
            onChange={(sid) => {
              const s = suppliers.find((x) => x.id === sid);
              setForm({
                ...form,
                supplier_id: sid || "",
                supplier_name: s ? s.name : form.supplier_name,
              });
            }}
            placeholder="Select supplier…"
            options={suppliers.map((s) => ({
              value: s.id,
              label: s.name,
              meta: [s.mobile, s.gst_in].filter(Boolean).join(" · "),
            }))}
          />
          {!form.supplier_id && (
            <div className="text-[10px] text-rose-700 mt-1 font-bold">
              ⚠ Supplier selection is mandatory for supplier vehicles. <a href="/suppliers/add" target="_blank" rel="noopener" className="underline">+ Add new</a>
            </div>
          )}
        </Field>
        <Field label="Loading Point">
          <input data-testid="trip-supplier-loading" value={form.supplier_loading_point} onChange={(e) => setForm({ ...form, supplier_loading_point: e.target.value })} className={inputCls} placeholder="e.g. HPCL Kondapalli" />
        </Field>
        <Field label="Unloading Point">
          <input data-testid="trip-supplier-unloading" value={form.supplier_unloading_point} onChange={(e) => setForm({ ...form, supplier_unloading_point: e.target.value })} className={inputCls} placeholder="e.g. Vijayawada Site" />
        </Field>
        <Field label="Material">
          <input data-testid="trip-supplier-material" value={form.supplier_material} onChange={(e) => setForm({ ...form, supplier_material: e.target.value })} className={inputCls} placeholder="Bitumen VG 40" />
        </Field>
        <Field label="Quantity (MT)">
          <input data-testid="trip-supplier-qty" type="number" step="0.01" min="0" value={form.supplier_quantity} onChange={(e) => setForm({ ...form, supplier_quantity: e.target.value })} className={inputCls} placeholder="If empty, trip Tons used" />
        </Field>
        <Field label="Freight Mode">
          <select data-testid="trip-supplier-mode" value={form.supplier_freight_mode} onChange={(e) => setForm({ ...form, supplier_freight_mode: e.target.value })} className={inputCls}>
            <option value="per_ton">Per Ton</option>
            <option value="fixed">Fixed / Round Trip</option>
          </select>
        </Field>
        {form.supplier_freight_mode === "per_ton" ? (
          <Field label="Supplier Rate / MT (₹)">
            <input data-testid="trip-supplier-rate" type="number" step="0.01" min="0" value={form.supplier_rate_per_ton} onChange={(e) => setForm({ ...form, supplier_rate_per_ton: e.target.value })} className={inputCls} />
          </Field>
        ) : (
          <>
            <Field label="Distance (Round Trip KMs)">
              <input data-testid="trip-supplier-kms" type="number" step="0.01" min="0" value={form.supplier_round_trip_kms} onChange={(e) => setForm({ ...form, supplier_round_trip_kms: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Rate (₹ / ton / km)">
              <input data-testid="trip-supplier-rate-km" type="number" step="0.01" min="0" value={form.supplier_rate_per_km_per_ton} onChange={(e) => setForm({ ...form, supplier_rate_per_km_per_ton: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Fixed Amount (₹)">
              <input data-testid="trip-supplier-fixed" type="number" step="0.01" min="0" value={form.supplier_fixed_amount} onChange={(e) => setForm({ ...form, supplier_fixed_amount: e.target.value })} className={inputCls} placeholder="Used only if KMs/Rate = 0" />
            </Field>
          </>
        )}
        <Field label="Supplier Freight (₹)">
          <input data-testid="trip-supplier-freight" type="number" step="0.01" min="0" value={form.supplier_freight} onChange={(e) => setForm({ ...form, supplier_freight: e.target.value })} className={inputCls} placeholder="Auto-computed" />
        </Field>
        <Field label="Supplier Advance (₹)">
          <input data-testid="trip-supplier-advance" type="number" step="0.01" min="0" value={form.supplier_advance} onChange={(e) => setForm({ ...form, supplier_advance: e.target.value })} className={inputCls} />
        </Field>
        <Field label="Supplier Diesel (₹)">
          <input data-testid="trip-supplier-diesel" type="number" step="0.01" min="0" value={form.supplier_diesel} onChange={(e) => setForm({ ...form, supplier_diesel: e.target.value })} className={inputCls} placeholder="Diesel we paid on behalf" />
        </Field>
        <Field label="Shortage Deduction (₹)">
          <input data-testid="trip-supplier-shortage" type="number" step="0.01" min="0" value={form.supplier_shortage_deduction} onChange={(e) => setForm({ ...form, supplier_shortage_deduction: e.target.value })} className={inputCls} placeholder="Deducted from supplier" />
        </Field>
        <Field label="Other Recoveries (₹)">
          <input data-testid="trip-supplier-recovery" type="number" step="0.01" min="0" value={form.supplier_other_recoveries} onChange={(e) => setForm({ ...form, supplier_other_recoveries: e.target.value })} className={inputCls} placeholder="Damages, penalties etc." />
        </Field>
        <Field label="Other Income / Bonus (₹)">
          <input data-testid="trip-supplier-income" type="number" step="0.01" min="0" value={form.supplier_other_income} onChange={(e) => setForm({ ...form, supplier_other_income: e.target.value })} className={inputCls} placeholder="Excess bonus paid to supplier" />
        </Field>
      </div>
      <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="border border-zinc-200 p-3 rounded-sm text-center">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Supplier Freight (Live)</div>
          <div className="font-mono text-lg font-bold">{fmtCurrency(supplierFreightLive)}</div>
        </div>
        <div className="border border-zinc-200 p-3 rounded-sm text-center">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Net Payable to Supplier</div>
          <div className="font-mono text-lg font-bold text-rose-700">{fmtCurrency(supplierNetPayable)}</div>
          <div className="text-[10px] text-zinc-500 mt-1">Freight − Advance − Diesel − Shortage − Recoveries + Income</div>
        </div>
        <div className={`border p-3 rounded-sm text-center ${supplierProfit >= 0 ? "border-emerald-300 bg-emerald-50" : "border-rose-300 bg-rose-50"}`}>
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Trip Profit</div>
          <div className={`font-mono text-lg font-bold ${supplierProfit >= 0 ? "text-emerald-800" : "text-rose-800"}`}>{fmtCurrency(supplierProfit)}</div>
          <div className="text-[10px] text-zinc-500 mt-1">Customer Freight − Net Payable</div>
        </div>
      </div>
      <div className="mt-3">
        <Field label="Supplier Settlement — Remarks">
          <input data-testid="trip-supplier-settlement-remarks" value={form.supplier_settlement_remarks} onChange={(e) => setForm({ ...form, supplier_settlement_remarks: e.target.value })} className={inputCls} placeholder="Payment / TDS / adjustments notes (optional)" />
        </Field>
      </div>
    </Section>
  );
}
