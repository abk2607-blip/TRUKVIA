// Iter55 — Extracted verbatim from TripForm.jsx.
// Iter91 — Multi-row Diesel / Advance transaction logs. Loading/Unloading/Material/Qty
// auto-fill from Trip Details (single source of truth) with a "🔗 auto" hint;
// override with a fresh value dirties the field and shows a "Reset to Trip" chip.
import React, { useMemo } from "react";
import { fmtCurrency } from "@/api";
import { toast } from "sonner";
import SearchableSelect from "@/components/SearchableSelect";
import { Section, Field } from "./FormPrimitives";
import { inputCls } from "./tripFormDefaults";
import SupplierEntriesTable from "./SupplierEntriesTable";

// Small badge that shows next to auto-filled fields.
function AutoHint({ auto, dirty, onReset, tripValue }) {
  if (dirty) {
    return (
      <div className="flex items-center justify-between mt-1">
        <span className="text-[10px] text-amber-700 font-bold uppercase tracking-wider">✎ Overridden</span>
        {onReset && (
          <button type="button" onClick={onReset} className="text-[10px] uppercase font-bold text-blue-700 hover:underline" title={`Reset to trip value: ${tripValue || "empty"}`}>
            Reset to Trip
          </button>
        )}
      </div>
    );
  }
  if (auto) {
    return <div className="text-[10px] text-blue-700 mt-1 font-bold uppercase tracking-wider">🔗 Auto from Trip Details</div>;
  }
  return null;
}

export default function SupplierSection({
  form, setForm, suppliers, tripId,
  supplierFreightLive, supplierNetPayable, supplierProfit,
  onQuickAddSupplier,
}) {
  // Trip Details are the source of truth. Supplier fields override on non-empty.
  const effLoading = (form.supplier_loading_point || form.from_location || "");
  const effUnloading = (form.supplier_unloading_point || form.to_location || "");
  const effMaterial = (form.supplier_material || form.load_details || "");
  const effQty = Number(form.supplier_quantity || 0) > 0 ? Number(form.supplier_quantity) : Number(form.tons || 0);

  const isDirtyLoading = !!form.supplier_loading_point && form.supplier_loading_point !== (form.from_location || "");
  const isDirtyUnloading = !!form.supplier_unloading_point && form.supplier_unloading_point !== (form.to_location || "");
  const isDirtyMaterial = !!form.supplier_material && form.supplier_material !== (form.load_details || "");
  const isDirtyQty = Number(form.supplier_quantity || 0) > 0 && Number(form.supplier_quantity) !== Number(form.tons || 0);

  const isAutoLoading = !form.supplier_loading_point && !!form.from_location;
  const isAutoUnloading = !form.supplier_unloading_point && !!form.to_location;
  const isAutoMaterial = !form.supplier_material && !!form.load_details;
  const isAutoQty = !(Number(form.supplier_quantity || 0) > 0) && Number(form.tons || 0) > 0;

  // When the server returns an updated trip after entries CRUD, merge into form.
  const onServerRefresh = (updated) => {
    if (!updated) return;
    setForm({
      ...form,
      ...updated,
      // preserve nested containers we own
      expenses: { ...(form.expenses || {}), ...(updated.expenses || {}) },
    });
  };

  return (
    <Section title="Supplier Vehicle · సప్లయర్ వాహనం">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Field label="Supplier · సప్లయర్" required>
          <div className="flex items-center gap-2">
            <div className="flex-1">
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
                  value: s.id, label: s.name,
                  meta: [s.mobile, s.gst_in].filter(Boolean).join(" · "),
                }))}
              />
            </div>
            {onQuickAddSupplier && (
              <button type="button" data-testid="trip-quickadd-supplier-btn" onClick={onQuickAddSupplier}
                className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 whitespace-nowrap">+ New</button>
            )}
          </div>
          {!form.supplier_id && (
            <div className="text-[10px] text-rose-700 mt-1 font-bold">⚠ Supplier selection is mandatory for supplier vehicles.</div>
          )}
        </Field>

        <Field label="Loading Point">
          <input
            data-testid="trip-supplier-loading"
            value={effLoading}
            onChange={(e) => setForm({ ...form, supplier_loading_point: e.target.value })}
            className={inputCls}
            placeholder={form.from_location ? `Auto from Trip: ${form.from_location}` : "e.g. IOCL Chennai"}
          />
          <AutoHint auto={isAutoLoading} dirty={isDirtyLoading}
            tripValue={form.from_location}
            onReset={() => setForm({ ...form, supplier_loading_point: "" })} />
        </Field>
        <Field label="Unloading Point">
          <input
            data-testid="trip-supplier-unloading"
            value={effUnloading}
            onChange={(e) => setForm({ ...form, supplier_unloading_point: e.target.value })}
            className={inputCls}
            placeholder={form.to_location ? `Auto from Trip: ${form.to_location}` : "e.g. Vijayawada Site"}
          />
          <AutoHint auto={isAutoUnloading} dirty={isDirtyUnloading}
            tripValue={form.to_location}
            onReset={() => setForm({ ...form, supplier_unloading_point: "" })} />
        </Field>
        <Field label="Material">
          <input
            data-testid="trip-supplier-material"
            value={effMaterial}
            onChange={(e) => setForm({ ...form, supplier_material: e.target.value })}
            className={inputCls}
            placeholder={form.load_details ? `Auto from Trip: ${form.load_details}` : "Bitumen VG 40"}
          />
          <AutoHint auto={isAutoMaterial} dirty={isDirtyMaterial}
            tripValue={form.load_details}
            onReset={() => setForm({ ...form, supplier_material: "" })} />
        </Field>
        <Field label="Quantity (MT)">
          <input
            data-testid="trip-supplier-qty"
            type="number" step="0.001" min="0"
            value={form.supplier_quantity || ""}
            onChange={(e) => setForm({ ...form, supplier_quantity: e.target.value })}
            className={inputCls}
            placeholder={form.tons ? `Auto from Trip: ${form.tons}` : "Quantity in MT"}
          />
          <AutoHint auto={isAutoQty} dirty={isDirtyQty}
            tripValue={form.tons}
            onReset={() => setForm({ ...form, supplier_quantity: 0 })} />
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
        <Field label={`Shortage Deduction (₹)${form.supplier_shortage_deduction_override ? "  · MANUAL OVERRIDE" : "  · AUTO"}`}>
          <div className="flex items-center gap-2">
            <input
              data-testid="trip-supplier-shortage"
              type="number" step="0.01" min="0"
              value={form.supplier_shortage_deduction}
              onChange={(e) => {
                const newVal = Number(e.target.value);
                const sys = Number(form.supplier_shortage_original_amount || 0);
                // Match backend Iter111 restore-to-auto contract (delta < 0.005)
                const isSystemVal = Math.abs(newVal - sys) < 0.005;
                if (isSystemVal) {
                  setForm({ ...form, supplier_shortage_deduction: newVal,
                            supplier_shortage_deduction_override: false,
                            supplier_shortage_override_reason: "" });
                  return;
                }
                // Ask reason inline — mandatory per Iter111 rule #6
                const existing = (form.supplier_shortage_override_reason || "").trim();
                let reason = existing;
                if (!existing) {
                  reason = (window.prompt(
                    "Reason for manual Supplier Shortage override (required):",
                    ""
                  ) || "").trim();
                }
                if (!reason) {
                  toast?.error?.("Override reason is required. Value not changed.");
                  return;
                }
                setForm({ ...form, supplier_shortage_deduction: newVal,
                          supplier_shortage_deduction_override: true,
                          supplier_shortage_override_reason: reason });
              }}
              className={inputCls}
              placeholder="System-calculated"
            />
            {form.supplier_shortage_deduction_override && (
              <button type="button" data-testid="trip-supplier-shortage-reset"
                onClick={() => setForm({ ...form,
                  supplier_shortage_deduction: Number(form.supplier_shortage_original_amount || 0),
                  supplier_shortage_deduction_override: false,
                  supplier_shortage_override_reason: "" })}
                className="text-[10px] uppercase font-bold text-blue-700 hover:underline whitespace-nowrap"
                title="Restore system-calculated value">Restore&nbsp;AUTO</button>
            )}
          </div>
          {form.supplier_shortage_deduction_override && (
            <div className="text-[10px] text-amber-800 mt-1">
              Override · system value = ₹{Number(form.supplier_shortage_original_amount || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })} · reason: {form.supplier_shortage_override_reason || "—"}
            </div>
          )}
        </Field>
        <Field label="Other Recoveries (₹)">
          <input data-testid="trip-supplier-recovery" type="number" step="0.01" min="0" value={form.supplier_other_recoveries} onChange={(e) => setForm({ ...form, supplier_other_recoveries: e.target.value })} className={inputCls} placeholder="Damages, penalties etc." />
        </Field>
        <Field label="Other Income / Bonus (₹)">
          <input data-testid="trip-supplier-income" type="number" step="0.01" min="0" value={form.supplier_other_income} onChange={(e) => setForm({ ...form, supplier_other_income: e.target.value })} className={inputCls} placeholder="Excess bonus paid to supplier" />
        </Field>
      </div>

      {/* Iter92 — Supplier Halting (independent of customer halting; manual only) */}
      <div className="mt-5 border border-zinc-200 bg-zinc-50 rounded-sm p-3" data-testid="sup-halting-block">
        <div className="flex items-center justify-between mb-2">
          <div className="text-[11px] uppercase tracking-wider font-bold text-zinc-700">
            Supplier Halting Charges <span className="ml-1 text-[10px] font-normal text-zinc-500 normal-case">(independent from Customer Halting; manual only)</span>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <Field label="Halting Days">
            <input data-testid="sup-halting-days" type="number" step="0.5" min="0"
              value={form.supplier_halting_days || ""}
              onChange={(e) => {
                const days = e.target.value;
                const rate = Number(form.supplier_halting_rate_per_day || 0);
                const nextAmt = (Number(days || 0) > 0 && rate > 0) ? Number(days) * rate : form.supplier_halting_amount;
                setForm({ ...form, supplier_halting_days: days, supplier_halting_amount: nextAmt });
              }}
              className={inputCls} placeholder="e.g. 2" />
          </Field>
          <Field label="Rate / Day (₹)">
            <input data-testid="sup-halting-rate" type="number" step="0.01" min="0"
              value={form.supplier_halting_rate_per_day || ""}
              onChange={(e) => {
                const rate = e.target.value;
                const days = Number(form.supplier_halting_days || 0);
                const nextAmt = (days > 0 && Number(rate || 0) > 0) ? days * Number(rate) : form.supplier_halting_amount;
                setForm({ ...form, supplier_halting_rate_per_day: rate, supplier_halting_amount: nextAmt });
              }}
              className={inputCls} placeholder="e.g. 1500" />
          </Field>
          <Field label="Halting Amount (₹)">
            <input data-testid="sup-halting-amount" type="number" step="0.01" min="0"
              value={form.supplier_halting_amount || ""}
              onChange={(e) => setForm({ ...form, supplier_halting_amount: e.target.value })}
              className={`${inputCls} font-bold`} placeholder="Auto = Days × Rate (editable)" />
          </Field>
          <Field label="Remarks">
            <input data-testid="sup-halting-remarks"
              value={form.supplier_halting_remarks || ""}
              onChange={(e) => setForm({ ...form, supplier_halting_remarks: e.target.value })}
              className={inputCls} placeholder="Detention reason (optional)" />
          </Field>
        </div>
        <div className="text-[10px] text-zinc-500 mt-2">
          Leave blank / 0 if the supplier is NOT receiving halting. Values here are <b>never auto-copied</b> from customer halting charges.
        </div>
      </div>

      {/* Iter91 — Multi-row Diesel + Advance entries */}
      <div className="mt-5 space-y-4">
        <SupplierEntriesTable
          kind="diesel"
          entries={form.supplier_diesel_entries || []}
          tripId={tripId}
          onLocalChange={(next) => setForm({ ...form, supplier_diesel_entries: next })}
          onServerRefresh={onServerRefresh}
        />
        <SupplierEntriesTable
          kind="advance"
          entries={form.supplier_advance_entries || []}
          tripId={tripId}
          onLocalChange={(next) => setForm({ ...form, supplier_advance_entries: next })}
          onServerRefresh={onServerRefresh}
        />
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

      {/* Iter111 · Requirement #7 — Transparent Supplier Calculation Summary.
          Reads engine-computed fields directly from `form` — introduces NO
          second calculation. Purely a display for UAT verification. */}
      <SupplierCalcSummary
        form={form}
        supplierFreightLive={supplierFreightLive}
        supplierNetPayable={supplierNetPayable}
      />
    </Section>
  );
}

// ─── Iter111 · Requirement #7 · Supplier Calculation Summary card ─────────
function _fmtQty(n, dp = 3) {
  return Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
function _fmtMoney(n) {
  return "₹ " + Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function SupplierCalcSummary({ form, supplierFreightLive, supplierNetPayable }) {
  const method = (form.applied_freight_method || "per_ton_loading").toLowerCase();
  const methodLabel = {
    per_ton_loading: "Per Ton · Loading Quantity",
    per_ton_unloading: "Per Ton · Unloading Quantity",
    per_ton_higher_of: "Per Ton · Higher of Loading / Unloading",
    fixed: "Fixed / Round-trip",
  }[method] || method;
  const loaded = Number(form.tons || form.loaded_qty || 0);
  const unloaded = Number(form.unloaded_qty || 0);
  let basisQty;
  if (method === "per_ton_unloading") basisQty = unloaded;
  else if (method === "per_ton_higher_of") basisQty = Math.max(loaded, unloaded);
  else basisQty = loaded;
  const supQty = Number(form.supplier_quantity || 0) > 0 ? Number(form.supplier_quantity) : basisQty;
  const supRate = form.supplier_freight_mode === "per_ton"
    ? `${_fmtMoney(form.supplier_rate_per_ton)} / MT`
    : (Number(form.supplier_fixed_amount) > 0
        ? `Fixed ${_fmtMoney(form.supplier_fixed_amount)}`
        : `${_fmtMoney(form.supplier_rate_per_km_per_ton)} / ton / km × ${form.supplier_round_trip_kms || 0} km`);
  const allowedLimitKg = Number(form.applied_supplier_shortage_limit_kg || 0);
  const actualShortageMt = Number(form.shortage_qty || 0);
  const actualShortageKg = Math.round(actualShortageMt * 1000);
  const withinLimit = allowedLimitKg > 0 && actualShortageKg <= allowedLimitKg;
  const deductibleMt = withinLimit ? 0 : actualShortageMt;
  const productRate = Number(form.product_rate_per_mt || 0);
  const sysShortageDeduction = Number(form.supplier_shortage_original_amount || 0);
  const finalShortageDeduction = Number(form.supplier_shortage_deduction || 0);
  const isOverride = !!form.supplier_shortage_deduction_override;

  return (
    <div className="mt-6 border-2 border-zinc-950 bg-white" data-testid="supplier-calc-summary">
      <div className="px-4 py-2 bg-zinc-950 text-white flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-widest font-bold">
          Iter111 · Supplier Calculation Summary
        </div>
        <span className={`text-[10px] uppercase tracking-widest font-bold px-2 py-0.5 border ${
          isOverride
            ? "border-amber-300 bg-amber-100 text-amber-900"
            : "border-emerald-300 bg-emerald-100 text-emerald-900"
        }`}>
          {isOverride ? "Manual Override" : "AUTO"}
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1 p-4 text-xs">
        <_Row k="Loading Quantity" v={`${_fmtQty(loaded)} MT`} testid="sc-loading" />
        <_Row k="Unloading Quantity" v={`${_fmtQty(unloaded)} MT`} testid="sc-unloading" />
        <_Row k="Applied Freight Basis" v={methodLabel} testid="sc-basis" bold />
        <_Row k="Supplier Freight Qty Used" v={`${_fmtQty(supQty)} MT`} testid="sc-supqty" mono />
        <_Row k="Supplier Freight Rate" v={supRate} testid="sc-rate" />
        <_Row k="Supplier Freight Amount" v={_fmtMoney(supplierFreightLive)} testid="sc-freight-amt" bold />
        <div className="col-span-full my-2 border-t border-dashed border-zinc-300" />
        <_Row k="Allowed Shortage Limit" v={allowedLimitKg > 0 ? `${allowedLimitKg} KG` : "— (no limit → FULL deduction)"} testid="sc-limit" />
        <_Row k="Actual Shortage" v={`${actualShortageKg} KG  (${_fmtQty(actualShortageMt)} MT)`} testid="sc-actual" />
        <_Row k="Deductible Shortage" v={
          withinLimit
            ? "0 KG  (within limit → ₹0)"
            : `${Math.round(deductibleMt * 1000)} KG  (${_fmtQty(deductibleMt)} MT)`
        } testid="sc-deductible" bold tone={withinLimit ? "emerald" : "rose"} />
        <_Row k="Shortage Rate" v={`${_fmtMoney(productRate)} / MT  (product_rate_per_mt)`} testid="sc-shortage-rate" />
        <_Row k="System-Calculated Deduction" v={_fmtMoney(sysShortageDeduction)} testid="sc-sys-deduction" mono />
        <_Row
          k={isOverride ? "Final Deduction (Manual)" : "Final Deduction"}
          v={_fmtMoney(finalShortageDeduction)}
          testid="sc-final-deduction" bold
          tone={isOverride ? "amber" : "zinc"}
        />
        {isOverride && form.supplier_shortage_override_reason && (
          <div className="col-span-full text-[10px] text-amber-800 border-l-2 border-amber-500 pl-2 mt-1" data-testid="sc-override-reason">
            Override reason: {form.supplier_shortage_override_reason}
            {form.supplier_shortage_override_by ? ` · by ${form.supplier_shortage_override_by}` : ""}
            {form.supplier_shortage_override_at ? ` · ${form.supplier_shortage_override_at.slice(0, 16).replace("T", " ")}` : ""}
          </div>
        )}
        <div className="col-span-full my-2 border-t-2 border-zinc-950" />
        <_Row k="Final Supplier Settlement · Net Payable" v={_fmtMoney(supplierNetPayable)} testid="sc-net-payable" bold big tone="rose" />
      </div>
    </div>
  );
}
function _Row({ k, v, testid, bold, mono, big, tone }) {
  const toneCls = {
    emerald: "text-emerald-800",
    rose: "text-rose-800",
    amber: "text-amber-800",
    zinc: "text-zinc-950",
  }[tone] || "text-zinc-950";
  return (
    <div className="flex items-baseline gap-3 py-0.5" data-testid={testid}>
      <div className="text-[10px] uppercase tracking-widest text-zinc-500 flex-shrink-0" style={{ minWidth: 220 }}>{k}</div>
      <div className={`${bold ? "font-bold" : ""} ${mono ? "font-mono" : ""} ${big ? "text-base" : ""} ${toneCls}`}>{v}</div>
    </div>
  );
}
