// Iter100 UI · Unloading Details with visible frozen policy snapshot.
// Surfaces the Phase-3 Shortage engine so users can UAT the applicable rule
// (Customer + Supplier) and the Net Shortage chain directly on the Trip UI:
//     Loading → Unloading → Actual Shortage → Allowed → Net → Amount.
import React from "react";
import { Section, Field } from "./FormPrimitives";
import { inputCls } from "./tripFormDefaults";
import { fmtCurrency } from "@/api";

function Tile({ label, value, muted, testid, tone }) {
  const toneMap = {
    default: "bg-white border-zinc-200 text-zinc-950",
    good: "bg-emerald-50 border-emerald-200 text-emerald-900",
    bad: "bg-rose-50 border-rose-200 text-rose-900",
    warn: "bg-amber-50 border-amber-200 text-amber-900",
    info: "bg-sky-50 border-sky-200 text-sky-900",
  };
  return (
    <div className={`border p-2 rounded-sm ${toneMap[tone || "default"]}`} data-testid={testid}>
      <div className="text-[9px] uppercase tracking-wider text-zinc-500 font-bold">{label}</div>
      <div className={`font-mono text-sm font-bold mt-0.5 ${muted ? "text-zinc-400" : ""}`}>{value}</div>
    </div>
  );
}

export default function UnloadingSection({
  form, setForm,
  shortageQtyLive, excessQtyLive,
  shortageAmountLive, excessAmountLive,
  // Iter100 UI · frozen shortage policy snapshot
  custShortageLimitDisplay, custShortageLimitType, custShortageMethod, custShortageMethodLabel,
  custAllowedMT, netShortageMT, limitExceeded,
  supplierShortageLimitKg, supplierShortageAllowedMT, supplierNetShortageMT, supplierLimitExceeded,
  loadedQ, unloadedQ,
}) {
  const hasCustPolicy = custShortageLimitType === "kg" || custShortageLimitType === "pct";
  const hasSupPolicy = supplierShortageLimitKg > 0;
  const netAmt = Number((Number(form.product_rate_per_mt || 0) * (netShortageMT || 0)).toFixed(2));

  return (
    <Section title="Unloading Details · అన్‌లోడ్">
      {/* ═════════════ Shortage Eligibility (frozen snapshot) ═════════════ */}
      <div
        className="mb-4 border border-zinc-950 rounded-sm bg-gradient-to-br from-slate-50 to-white p-3"
        data-testid="shortage-eligibility-panel"
      >
        <div className="flex items-baseline justify-between mb-2">
          <div className="text-[10px] uppercase tracking-[0.15em] font-black text-zinc-950">
            📋 Shortage Eligibility · Applied Policy Snapshot
          </div>
          <div className="text-[9px] uppercase tracking-wider text-zinc-500 font-mono">frozen at trip creation</div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <Tile
            testid="policy-cust-limit"
            label="Customer · Applied Limit"
            value={custShortageLimitDisplay || "—"}
            muted={!hasCustPolicy}
            tone={hasCustPolicy ? "info" : "default"}
          />
          <Tile
            testid="policy-cust-method"
            label="Customer · Deduction Method"
            value={custShortageMethodLabel || "—"}
            muted={!hasCustPolicy}
            tone={hasCustPolicy ? "info" : "default"}
          />
          <Tile
            testid="policy-cust-allowed"
            label="Customer · Allowed"
            value={hasCustPolicy ? `${custAllowedMT.toFixed(3)} MT` : "—"}
            muted={!hasCustPolicy}
            tone={hasCustPolicy ? "info" : "default"}
          />
          <Tile
            testid="policy-supplier-limit"
            label="Supplier · Fixed KG Limit"
            value={hasSupPolicy ? `${supplierShortageLimitKg} KG · ${supplierShortageAllowedMT.toFixed(3)} MT` : "—"}
            muted={!hasSupPolicy}
            tone={hasSupPolicy ? "warn" : "default"}
          />
        </div>
        {!hasCustPolicy && !hasSupPolicy && (
          <div className="mt-2 text-[10px] text-zinc-500 italic">
            No shortage policy snapshot on this trip — set the Customer / Supplier shortage rules in Masters and recreate the trip.
          </div>
        )}
      </div>

      {/* ═════════════ Base fields ═════════════ */}
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
      </div>

      {/* ═════════════ Net Shortage Chain ═════════════ */}
      {(shortageQtyLive > 0 || excessQtyLive > 0 || hasCustPolicy) && (
        <div className="mt-4 border border-zinc-200 rounded-sm bg-white p-3" data-testid="net-shortage-chain">
          <div className="text-[10px] uppercase tracking-[0.15em] font-black text-zinc-950 mb-2">
            🧮 Net Shortage Calculation · Customer
          </div>
          <div className="grid grid-cols-2 md:grid-cols-6 gap-2 items-stretch">
            <Tile testid="chain-loading"  label="Loading Qty"    value={`${loadedQ.toFixed(3)} MT`} />
            <Tile testid="chain-unloading" label="Unloading Qty" value={`${unloadedQ.toFixed(3)} MT`} />
            <Tile
              testid="chain-actual-shortage"
              label="Actual Shortage"
              value={`${shortageQtyLive.toFixed(3)} MT`}
              tone={shortageQtyLive > 0 ? "bad" : "default"}
            />
            <Tile
              testid="chain-allowed"
              label="Allowed"
              value={hasCustPolicy ? `${custAllowedMT.toFixed(3)} MT` : "—"}
              tone="info"
              muted={!hasCustPolicy}
            />
            <Tile
              testid="chain-net-shortage"
              label={custShortageMethod === "full_after_limit" && limitExceeded ? "Net (Full ×)" : "Net Shortage"}
              value={`${(netShortageMT || 0).toFixed(3)} MT`}
              tone={netShortageMT > 0 ? "bad" : "good"}
            />
            <Tile
              testid="chain-shortage-amount"
              label="Shortage Amount"
              value={fmtCurrency(netAmt)}
              tone={netAmt > 0 ? "bad" : "default"}
            />
          </div>
          {custShortageMethod === "full_after_limit" && limitExceeded && (
            <div className="mt-2 text-[10px] text-rose-800 bg-rose-50 border border-rose-200 rounded-sm px-2 py-1" data-testid="chain-full-notice">
              ⚠ Limit exceeded — <b>Full Actual Shortage</b> is deductible per the customer rule.
            </div>
          )}
          {custShortageMethod === "net_shortage" && limitExceeded && (
            <div className="mt-2 text-[10px] text-amber-800 bg-amber-50 border border-amber-200 rounded-sm px-2 py-1" data-testid="chain-net-notice">
              ⚠ Limit exceeded — only the <b>quantity above the allowance</b> is deductible.
            </div>
          )}
          {hasCustPolicy && !limitExceeded && shortageQtyLive > 0 && (
            <div className="mt-2 text-[10px] text-emerald-800 bg-emerald-50 border border-emerald-200 rounded-sm px-2 py-1" data-testid="chain-within-notice">
              ✓ Within allowed limit — no customer deduction applies.
            </div>
          )}

          {/* Supplier chain — only when supplier policy set on trip */}
          {hasSupPolicy && (
            <>
              <div className="mt-3 text-[10px] uppercase tracking-[0.15em] font-black text-zinc-950 mb-2">
                🧮 Net Shortage Calculation · Supplier (independent · KG basis)
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                <Tile testid="supplier-chain-actual" label="Actual Shortage" value={`${(shortageQtyLive * 1000).toFixed(0)} KG`} tone={shortageQtyLive > 0 ? "bad" : "default"} />
                <Tile testid="supplier-chain-allowed" label="Supplier Allowed" value={`${supplierShortageLimitKg} KG`} tone="warn" />
                <Tile testid="supplier-chain-net" label="Supplier Net" value={`${(supplierNetShortageMT * 1000).toFixed(0)} KG`} tone={supplierNetShortageMT > 0 ? "bad" : "good"} />
                <Tile testid="supplier-chain-deduction" label="Rule Applied" value={supplierLimitExceeded ? "Full Actual (exceeded)" : "No deduction"} tone={supplierLimitExceeded ? "bad" : "good"} />
              </div>
            </>
          )}
        </div>
      )}

      {/* ═════════════ Editable amounts (auto/manual toggle) ═════════════ */}
      <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="border border-zinc-200 p-2 rounded-sm text-center">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Shortage Qty</div>
          <div className="font-mono text-sm font-bold text-rose-700">{shortageQtyLive.toFixed(3)} MT</div>
        </div>
        <div className="border border-zinc-200 p-2 rounded-sm text-center">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Excess Qty</div>
          <div className="font-mono text-sm font-bold text-emerald-700">{excessQtyLive.toFixed(3)} MT</div>
        </div>
        <Field label={
          <span>Shortage Amount (₹) <button type="button" data-testid="trip-shortage-amount-toggle" onClick={() => setForm({ ...form, shortage_amount_override: !form.shortage_amount_override })} className={`ml-1 text-[9px] uppercase tracking-wider ${form.shortage_amount_override ? "text-amber-700" : "text-zinc-400"}`}>{form.shortage_amount_override ? "manual" : "auto"}</button></span>
        }>
          <input data-testid="trip-shortage-amount" type="number" step="0.01" min="0" value={form.shortage_amount_override ? form.shortage_amount : shortageAmountLive} disabled={!form.shortage_amount_override} onChange={(e) => setForm({ ...form, shortage_amount: e.target.value })} className={`${inputCls} disabled:bg-zinc-50 disabled:text-zinc-600`} />
        </Field>
        <Field label={
          <span>Excess Amount (₹) <button type="button" data-testid="trip-excess-amount-toggle" onClick={() => setForm({ ...form, excess_amount_override: !form.excess_amount_override })} className={`ml-1 text-[9px] uppercase tracking-wider ${form.excess_amount_override ? "text-amber-700" : "text-zinc-400"}`}>{form.excess_amount_override ? "manual" : "auto"}</button></span>
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
