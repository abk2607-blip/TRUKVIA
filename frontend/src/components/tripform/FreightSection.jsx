// Iter100 UI · Freight Calculation with visible frozen policy snapshot.
// Surfaces the Phase-2 Central Freight Engine so users can UAT which
// method + qty basis is being applied to THIS trip.
import React from "react";
import { fmtCurrency } from "@/api";
import { Section, Field } from "./FormPrimitives";
import { inputCls } from "./tripFormDefaults";

function Chip({ label, value, tone, testid, highlight }) {
  const toneMap = {
    default: "bg-white border-zinc-200 text-zinc-950",
    info: "bg-sky-50 border-sky-200 text-sky-900",
    warn: "bg-amber-50 border-amber-200 text-amber-900",
    good: "bg-emerald-50 border-emerald-200 text-emerald-900",
    muted: "bg-zinc-50 border-zinc-200 text-zinc-500",
  };
  return (
    <div
      className={`border rounded-sm p-2 ${toneMap[tone || "default"]} ${highlight ? "ring-2 ring-amber-400" : ""}`}
      data-testid={testid}
    >
      <div className="text-[9px] uppercase tracking-wider text-zinc-500 font-bold">{label}</div>
      <div className="font-mono text-sm font-bold mt-0.5">{value}</div>
    </div>
  );
}

export default function FreightSection({
  form, setForm, freight,
  freightMethodLabel,
  freightQtyBasisLabel,
  freightQtyUsedLive,
  loadedQ, unloadedQ,
}) {
  const rate = Number(form.rate_per_ton || 0);
  const fixedLump = Number(form.fixed_amount || 0);
  const roundKm = Number(form.round_trip_kms || 0);
  const rateKm = Number(form.rate_per_km_per_ton || 0);
  const perTon = form.freight_mode === "per_ton";
  // Iter102 · Displayed formula MUST reflect the frozen applied_freight_method
  // and the actual `freight_qty_used` — not the raw Loading Qty. This keeps
  // the three columns of the UAT invariant in lock-step:
  //   Applied Method → Freight Qty Used → Displayed Formula → Final Amount
  const qtyUsed = Number(freightQtyUsedLive || 0);
  const isFixedLump = !perTon && !(roundKm > 0 && rateKm > 0);
  const calcExpr = perTon
    ? `${qtyUsed.toFixed(3)} MT × ₹${rate.toFixed(2)}`
    : isFixedLump
      ? `Fixed Freight (Lump Sum) · ₹${fixedLump.toFixed(2)}`
      : `${qtyUsed.toFixed(3)} MT × ${roundKm.toFixed(2)} KM × ₹${rateKm.toFixed(2)}`;
  const basisLine = isFixedLump
    ? "Freight Basis: Fixed / Lump Sum"
    : `Freight Basis: ${freightQtyBasisLabel || "—"}`;
  const calculatedFreight = Number(freight || 0);

  return (
    <Section title="ఫ్రైట్ · Freight Calculation">
      {/* ═════════ Freight Policy Snapshot (frozen at trip creation) ═════════ */}
      <div
        className="mb-4 border border-zinc-950 rounded-sm bg-gradient-to-br from-slate-50 to-white p-3"
        data-testid="freight-policy-panel"
      >
        <div className="flex items-baseline justify-between mb-2">
          <div className="text-[10px] uppercase tracking-[0.15em] font-black text-zinc-950">
            📋 Freight Calculation Policy · Applied for THIS Trip
          </div>
          <div className="text-[9px] uppercase tracking-wider text-zinc-500 font-mono">frozen snapshot</div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <Chip testid="freight-policy-method" label="Method" value={freightMethodLabel || "—"} tone="info" />
          <Chip testid="freight-policy-basis" label="Qty Basis" value={freightQtyBasisLabel || "—"} tone="info" />
          <Chip testid="freight-policy-loading" label="Loading Qty" value={`${loadedQ.toFixed(3)} MT`} />
          <Chip testid="freight-policy-unloading" label="Unloading Qty" value={`${unloadedQ.toFixed(3)} MT`} />
        </div>
      </div>

      <div className="flex gap-3 mb-4">
        <label data-testid="freight-mode-per-ton" className={`flex-1 border p-3 rounded-sm cursor-pointer ${form.freight_mode === "per_ton" ? "border-zinc-950 bg-zinc-50" : "border-zinc-200"}`}>
          <input type="radio" name="mode" checked={form.freight_mode === "per_ton"} onChange={() => setForm({ ...form, freight_mode: "per_ton" })} className="mr-2" />
          <span className="font-semibold text-sm"><span className="telugu">టన్ను ప్రకారం</span> · Per Ton</span>
          <div className="text-[11px] text-zinc-500 mt-1">Tons × Rate</div>
        </label>
        <label data-testid="freight-mode-fixed" className={`flex-1 border p-3 rounded-sm cursor-pointer ${form.freight_mode === "fixed" ? "border-zinc-950 bg-zinc-50" : "border-zinc-200"}`}>
          <input type="radio" name="mode" checked={form.freight_mode === "fixed"} onChange={() => setForm({ ...form, freight_mode: "fixed" })} className="mr-2" />
          <span className="font-semibold text-sm"><span className="telugu">రౌండ్ ట్రిప్</span> · Round Trip</span>
          <div className="text-[11px] text-zinc-500 mt-1">Tons × Round Trip KMs × Rate</div>
        </label>
      </div>

      {form.freight_mode === "per_ton" ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Field label="Rate per Ton (₹) · రేటు">
            <input data-testid="trip-rate-per-ton" type="number" step="0.01" min="0" value={form.rate_per_ton} onChange={(e) => setForm({ ...form, rate_per_ton: e.target.value })} className={inputCls} />
          </Field>
          <div className="md:col-span-2 flex items-end justify-end">
            <div className="bg-amber-50 border border-amber-200 px-4 py-3 rounded-sm text-right" data-testid="freight-preview">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Calculated Freight · ఫ్రైట్</div>
              <div className="font-mono text-2xl font-bold text-amber-900" data-testid="freight-preview-amount">{fmtCurrency(calculatedFreight)}</div>
              <div className="text-[10px] font-semibold text-amber-900 mt-1" data-testid="freight-preview-basis">{basisLine}</div>
              <div className="text-[10px] text-zinc-600 mt-0.5 font-mono" data-testid="freight-preview-formula">{calcExpr}</div>
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Field label="Round Trip KMs · రౌండ్ ట్రిప్ KM">
              <input data-testid="trip-round-trip-kms" type="number" step="0.01" min="0" value={form.round_trip_kms} onChange={(e) => setForm({ ...form, round_trip_kms: e.target.value })} className={inputCls} placeholder="e.g. 450" />
            </Field>
            <Field label="Rate (₹/ton/km) · రేటు">
              <input data-testid="trip-rate-per-km-per-ton" type="number" step="0.01" min="0" value={form.rate_per_km_per_ton} onChange={(e) => setForm({ ...form, rate_per_km_per_ton: e.target.value })} className={inputCls} placeholder="e.g. 3.5" />
            </Field>
            <Field label="Or Fixed Lump Sum (₹)">
              <input data-testid="trip-fixed-amount" type="number" step="0.01" min="0" value={form.fixed_amount} onChange={(e) => setForm({ ...form, fixed_amount: e.target.value })} className={inputCls} placeholder="Used only if KMs/Rate = 0" />
            </Field>
          </div>
          <div className="mt-4 flex justify-end">
            <div className="bg-amber-50 border border-amber-200 px-4 py-3 rounded-sm text-right" data-testid="freight-preview">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Calculated Freight · ఫ్రైట్</div>
              <div className="font-mono text-2xl font-bold text-amber-900" data-testid="freight-preview-amount">{fmtCurrency(calculatedFreight)}</div>
              <div className="text-[10px] font-semibold text-amber-900 mt-1" data-testid="freight-preview-basis">{basisLine}</div>
              <div className="text-[10px] text-zinc-600 mt-0.5 font-mono" data-testid="freight-preview-formula">{calcExpr}</div>
            </div>
          </div>
        </>
      )}

      {/* ═════════ Freight Breakdown Chain — shows for both per-ton AND round-trip ═════════ */}
      {!isFixedLump && (
        <div className="mt-4 border border-zinc-200 rounded-sm bg-white p-3" data-testid="freight-breakdown-chain">
          <div className="text-[10px] uppercase tracking-[0.15em] font-black text-zinc-950 mb-2">
            🧮 Freight Breakdown · Verification
          </div>
          <div className={`grid grid-cols-2 gap-2 ${perTon ? "md:grid-cols-5" : "md:grid-cols-6"}`}>
            <Chip testid="fb-loading" label="Loading Qty" value={`${loadedQ.toFixed(3)} MT`} tone={freightQtyBasisLabel === "Loading Qty" || freightQtyBasisLabel === "Higher of Loading / Unloading" ? "info" : "muted"} />
            <Chip testid="fb-unloading" label="Unloading Qty" value={`${unloadedQ.toFixed(3)} MT`} tone={freightQtyBasisLabel === "Unloading Qty" || freightQtyBasisLabel === "Higher of Loading / Unloading" ? "info" : "muted"} />
            <Chip testid="fb-qty-used" label="Qty Used (this trip)" value={`${qtyUsed.toFixed(3)} MT`} tone="warn" highlight />
            {perTon ? (
              <Chip testid="fb-rate" label="Rate" value={`₹${rate.toFixed(2)} / MT`} />
            ) : (
              <>
                <Chip testid="fb-round-km" label="Round Trip KM" value={`${roundKm.toFixed(2)} KM`} />
                <Chip testid="fb-rate" label="Rate" value={`₹${rateKm.toFixed(2)} / MT / KM`} />
              </>
            )}
            <Chip testid="fb-calculated" label="Calculated Freight" value={fmtCurrency(calculatedFreight)} tone="good" />
          </div>
        </div>
      )}
    </Section>
  );
}
