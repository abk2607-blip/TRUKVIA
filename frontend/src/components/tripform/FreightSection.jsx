// Iter55 — Extracted verbatim from TripForm.jsx. Pure JSX.
import React from "react";
import { fmtCurrency } from "@/api";
import { Section, Field } from "./FormPrimitives";
import { inputCls } from "./tripFormDefaults";

export default function FreightSection({ form, setForm, freight }) {
  return (
    <Section title="ఫ్రైట్ · Freight Calculation">
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
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Freight · ఫ్రైట్</div>
              <div className="font-mono text-2xl font-bold text-amber-900">{fmtCurrency(freight)}</div>
              <div className="text-[10px] text-zinc-500 mt-1 font-mono">{Number(form.tons || 0).toFixed(2)} × ₹{Number(form.rate_per_ton || 0).toFixed(2)}</div>
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
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Freight · ఫ్రైట్</div>
              <div className="font-mono text-2xl font-bold text-amber-900">{fmtCurrency(freight)}</div>
              <div className="text-[10px] text-zinc-500 mt-1 font-mono">
                {Number(form.round_trip_kms || 0) > 0 && Number(form.rate_per_km_per_ton || 0) > 0
                  ? `${Number(form.tons || 0).toFixed(2)} × ${Number(form.round_trip_kms || 0).toFixed(2)}km × ₹${Number(form.rate_per_km_per_ton || 0).toFixed(2)}`
                  : `Lump sum ₹${Number(form.fixed_amount || 0).toFixed(2)}`}
              </div>
            </div>
          </div>
        </>
      )}
    </Section>
  );
}
