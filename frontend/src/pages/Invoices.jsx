import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate } from "@/api";
import { Link } from "react-router-dom";
import { Plus, FileText } from "lucide-react";

export default function Invoices() {
  const { data: invoices = [] } = useQuery({ queryKey: ["invoices"], queryFn: async () => (await api.get("/invoices")).data });
  const { data: customers = [] } = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get("/customers")).data });
  const custMap = Object.fromEntries(customers.map((c) => [c.id, c.name]));

  return (
    <div className="space-y-6" data-testid="invoices-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Billing</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">ఇన్వాయిస్‌లు</span>
            <span className="text-zinc-400"> · Invoices</span>
          </h1>
        </div>
        <Link to="/invoices/new" data-testid="new-invoice-btn" className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2">
          <Plus size={14} /> New Invoice
        </Link>
      </header>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
        <table className="w-full text-sm" data-testid="invoices-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-4 py-2 font-semibold">Invoice #</th>
              <th className="text-left px-4 py-2 font-semibold">Date</th>
              <th className="text-left px-4 py-2 font-semibold">Customer</th>
              <th className="text-right px-4 py-2 font-semibold">Trips</th>
              <th className="text-right px-4 py-2 font-semibold">Total</th>
              <th className="text-right px-4 py-2 font-semibold">Paid</th>
              <th className="text-right px-4 py-2 font-semibold">Balance</th>
              <th className="text-left px-4 py-2 font-semibold">GST</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((inv) => (
              <tr key={inv.id} data-testid={`invoice-row-${inv.id}`} className="border-t border-zinc-100">
                <td className="px-4 py-3 font-mono text-xs font-semibold">{inv.invoice_number}</td>
                <td className="px-4 py-3 font-mono text-xs">{fmtDate(inv.invoice_date)}</td>
                <td className="px-4 py-3">{custMap[inv.customer_id] || "—"}</td>
                <td className="px-4 py-3 text-right font-mono">{inv.trip_ids.length}</td>
                <td className="px-4 py-3 text-right font-mono font-semibold">{fmtCurrency(inv.total_amount)}</td>
                <td className="px-4 py-3 text-right font-mono text-emerald-700">{fmtCurrency(inv.amount_paid)}</td>
                <td className={`px-4 py-3 text-right font-mono font-bold ${inv.balance_due > 0 ? "text-amber-700" : "text-zinc-400"}`}>{fmtCurrency(inv.balance_due)}</td>
                <td className="px-4 py-3 text-[10px] uppercase tracking-wider">
                  {inv.rcm ? <span className="border border-zinc-300 px-2 py-0.5 rounded-sm">RCM</span> : <span className="border border-zinc-300 px-2 py-0.5 rounded-sm">FWD</span>}
                  <span className="ml-1 text-zinc-500">{inv.gst_type === "cgst_sgst" ? "C+S" : "IGST"}</span>
                </td>
                <td className="px-4 py-3 text-right">
                  <Link data-testid={`view-invoice-${inv.id}`} to={`/invoices/${inv.id}`} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-zinc-200 rounded-sm hover:bg-zinc-950 hover:text-white">
                    <FileText size={12} /> View
                  </Link>
                </td>
              </tr>
            ))}
            {invoices.length === 0 && (
              <tr><td colSpan={9} className="px-4 py-12 text-center text-zinc-400">No invoices yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
