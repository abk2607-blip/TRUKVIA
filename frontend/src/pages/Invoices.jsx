import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate } from "@/api";
import { Link, useNavigate } from "react-router-dom";
import { Plus, FileText, ChevronRight } from "lucide-react";

export default function Invoices() {
  const navigate = useNavigate();
  const { data: invoices = [] } = useQuery({ queryKey: ["invoices"], queryFn: async () => (await api.get("/invoices")).data });
  const { data: customers = [] } = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get("/customers")).data });
  const custMap = Object.fromEntries(customers.map((c) => [c.id, c.name]));

  const open = (id) => navigate(`/invoices/${id}`);

  return (
    <div className="space-y-6" data-testid="invoices-page">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Billing</div>
          <h1 className="mt-1 text-3xl sm:text-4xl font-black tracking-tighter">
            <span className="telugu">ఇన్వాయిస్‌లు</span>
            <span className="text-zinc-400"> · Invoices</span>
          </h1>
        </div>
        <Link
          to="/invoices/new"
          data-testid="new-invoice-btn"
          className="px-4 py-2.5 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2 min-h-[44px]"
        >
          <Plus size={16} /> New Invoice
        </Link>
      </header>

      {/* Mobile — card list. Iter76: whole card tappable. */}
      <div className="md:hidden space-y-2">
        {invoices.map((inv) => (
          <button
            key={inv.id}
            type="button"
            data-testid={`invoice-row-${inv.id}`}
            onClick={() => open(inv.id)}
            className="w-full text-left bg-white border border-zinc-200 rounded-sm p-4 active:bg-zinc-50 hover:border-zinc-400 transition-colors flex items-start gap-3"
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <div className="font-mono text-sm font-bold text-zinc-950 truncate">{inv.invoice_number}</div>
                <div className="text-[10px] font-mono text-zinc-500 whitespace-nowrap">{fmtDate(inv.invoice_date)}</div>
              </div>
              <div className="mt-1 text-sm font-semibold text-zinc-900 truncate">{custMap[inv.customer_id] || "—"}</div>
              <div className="mt-2 flex items-center gap-3 text-xs">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500">Total</div>
                  <div className="font-mono font-semibold">{fmtCurrency(inv.total_amount)}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500">Paid</div>
                  <div className="font-mono text-emerald-700">{fmtCurrency(inv.amount_paid)}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500">Balance</div>
                  <div className={`font-mono font-bold ${inv.balance_due > 0 ? "text-amber-700" : "text-zinc-400"}`}>{fmtCurrency(inv.balance_due)}</div>
                </div>
              </div>
              <div className="mt-2 flex items-center gap-1 text-[9px] uppercase tracking-wider">
                <span className="border border-zinc-300 px-1.5 py-0.5 rounded-sm">{inv.rcm ? "RCM" : "FWD"}</span>
                <span className="border border-zinc-300 px-1.5 py-0.5 rounded-sm">{inv.gst_type === "cgst_sgst" ? "C+S" : "IGST"}</span>
                <span className="ml-auto text-zinc-500 font-mono">{inv.trip_ids.length} trip{inv.trip_ids.length === 1 ? "" : "s"}</span>
              </div>
            </div>
            <ChevronRight size={18} className="text-zinc-300 shrink-0 mt-0.5" />
          </button>
        ))}
        {invoices.length === 0 && (
          <div className="bg-white border border-zinc-200 rounded-sm px-4 py-12 text-center text-zinc-400" data-testid="invoices-empty">
            No invoices yet.
          </div>
        )}
      </div>

      {/* Desktop — table. Iter76: whole row clickable. */}
      <div className="hidden md:block border border-zinc-200 bg-white rounded-sm overflow-hidden">
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
              <tr
                key={inv.id}
                data-testid={`invoice-row-desktop-${inv.id}`}
                onClick={() => open(inv.id)}
                className="border-t border-zinc-100 cursor-pointer hover:bg-zinc-50 transition-colors"
              >
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
                  <Link
                    data-testid={`view-invoice-${inv.id}`}
                    to={`/invoices/${inv.id}`}
                    onClick={(e) => e.stopPropagation()}
                    className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-zinc-200 rounded-sm hover:bg-zinc-950 hover:text-white"
                  >
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
