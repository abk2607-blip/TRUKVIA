// Iter55 — Extracted verbatim from TripForm.jsx. Pure JSX.
import React from "react";
import { fmtCurrency } from "@/api";
import { Section } from "./FormPrimitives";
import CustomerReceipts from "./CustomerReceipts";

export default function ReceivedFromCustomerSection({ form, setForm }) {
  return (
    <Section title="కస్టమర్ నుండి · Received From Customer">
      <CustomerReceipts
        receipts={form.customer_receipts || []}
        onChange={(list) => setForm({ ...form, customer_receipts: list })}
      />
      {(() => {
        const diesel = (form.customer_receipts || []).filter((r) => r.type === "diesel").reduce((s, r) => s + (Number(r.amount) || (Number(r.litres || 0) * Number(r.rate || 0))), 0);
        const advance = (form.customer_receipts || []).filter((r) => r.type === "advance").reduce((s, r) => s + Number(r.amount || 0), 0);
        const total = diesel + advance;
        return (
          <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-2">
            <div className="border border-zinc-200 bg-white rounded-sm p-2.5"><div className="text-[9px] uppercase tracking-wider font-bold text-zinc-500">Total Diesel Received</div><div className="font-mono text-base font-bold" data-testid="cr-total-diesel">{fmtCurrency(diesel)}</div></div>
            <div className="border border-zinc-200 bg-white rounded-sm p-2.5"><div className="text-[9px] uppercase tracking-wider font-bold text-zinc-500">Total Advance Received</div><div className="font-mono text-base font-bold" data-testid="cr-total-advance">{fmtCurrency(advance)}</div></div>
            <div className="border border-rose-300 bg-rose-50 rounded-sm p-2.5"><div className="text-[9px] uppercase tracking-wider font-bold text-rose-700">Total Deductions from Freight</div><div className="font-mono text-lg font-bold text-rose-800" data-testid="cr-total-deduction">{fmtCurrency(total)}</div></div>
          </div>
        );
      })()}
      <div className="mt-2 text-[11px] text-zinc-500">Each receipt is trip-linked. These reduce the customer's Net Payable Freight. For supplier vehicle trips, Customer Diesel is also deducted from Supplier Net Payable.</div>
    </Section>
  );
}
