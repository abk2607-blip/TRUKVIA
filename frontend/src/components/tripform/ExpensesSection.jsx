// Iter55 — Extracted verbatim from TripForm.jsx. Pure JSX.
import React from "react";
import { fmtCurrency } from "@/api";
import VoiceButton from "@/components/VoiceButton";
import { Section, Field } from "./FormPrimitives";
import { inputCls } from "./tripFormDefaults";

export default function ExpensesSection({
  form, setForm, setExp,
  totalExpense, freight, profit,
}) {
  return (
    <Section title="ఖర్చులు · Expenses">
      <div className="flex justify-end mb-2">
        <VoiceButton
          context="expense"
          size="sm"
          onParsed={(p) => {
            const num = (v) => (v === "" || v === null || v === undefined ? null : Number(v));
            setForm((f) => ({
              ...f,
              expenses: {
                ...f.expenses,
                diesel: num(p.diesel) ?? f.expenses.diesel,
                toll: num(p.toll) ?? f.expenses.toll,
                batta: num(p.batta) ?? f.expenses.batta,
                repair: num(p.repair) ?? f.expenses.repair,
                other: num(p.other) ?? f.expenses.other,
                other_desc: p.other_desc || f.expenses.other_desc,
              },
            }));
          }}
        />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[
          ["diesel", "Diesel · డీజిల్"],
          ["toll", "Toll · టోల్"],
          ["batta", "Driver Batta · బాటా"],
          ["repair", "Repair · రిపేర్"],
          ["other", "Other · ఇతర"],
        ].map(([k, lbl]) => (
          <Field key={k} label={lbl}>
            <input data-testid={`exp-${k}`} type="number" step="0.01" min="0" value={form.expenses[k]} onChange={(e) => setExp(k, e.target.value)} className={inputCls} />
          </Field>
        ))}
      </div>
      <div className="mt-4 grid grid-cols-3 gap-4">
        <div className="border border-zinc-200 p-3 rounded-sm text-center">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Total Expense</div>
          <div className="font-mono text-lg font-bold text-rose-700">{fmtCurrency(totalExpense)}</div>
        </div>
        <div className="border border-zinc-200 p-3 rounded-sm text-center">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Freight</div>
          <div className="font-mono text-lg font-bold">{fmtCurrency(freight)}</div>
        </div>
        <div className={`border p-3 rounded-sm text-center ${profit >= 0 ? "border-emerald-300 bg-emerald-50" : "border-rose-300 bg-rose-50"}`} data-testid="trip-profit-preview">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Profit · లాభం</div>
          <div className={`font-mono text-lg font-bold ${profit >= 0 ? "text-emerald-800" : "text-rose-800"}`}>{fmtCurrency(profit)}</div>
        </div>
      </div>
    </Section>
  );
}
