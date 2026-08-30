import React, { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate } from "@/api";
import { X, Search } from "lucide-react";
import NoteCreateDialog from "@/components/NoteCreateDialog";

/**
 * Iter132c C2 refinement · Customer-based CN/DN entry.
 * Reuses GET /customers/{cid}/transactions (already C1-enriched with
 * effective_balance_due, credits_total, debits_total). No new backend.
 */
export default function NoteCreateFromCustomerDialog({ kind, customerId, onClose }) {
  const [search, setSearch] = useState("");
  const [dateFilter, setDateFilter] = useState("");
  const [chosen, setChosen] = useState(null);

  const { data, isLoading } = useQuery({
    queryKey: ["customer-transactions", customerId],
    queryFn: async () => (await api.get(`/customers/${customerId}/transactions`)).data,
    enabled: Boolean(customerId),
  });

  const invoices = useMemo(() => {
    const txns = (data?.transactions || []).filter((t) => t.type === "invoice");
    const s = search.trim().toLowerCase();
    return txns.filter((t) => {
      if (s && !(t.ref || "").toLowerCase().includes(s)) return false;
      if (dateFilter && t.date !== dateFilter) return false;
      return true;
    });
  }, [data, search, dateFilter]);

  // Adapt txn shape to Invoice shape NoteCreateDialog expects.
  const chosenInvoice = chosen && {
    id: chosen.id,
    invoice_number: chosen.ref,
    invoice_date: chosen.date,
    total_amount: chosen.effective_total_amount || chosen.amount || 0,
    balance_due: chosen.balance_due || 0,
    effective_balance_due: chosen.effective_balance_due ?? chosen.balance_due ?? 0,
    credits_total: chosen.credits_total || 0,
    debits_total: chosen.debits_total || 0,
  };

  if (chosen) {
    return <NoteCreateDialog kind={kind} invoice={chosenInvoice} onClose={onClose} />;
  }

  const kindLabel = kind === "credit" ? "Credit Note" : "Debit Note";
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start sm:items-center justify-center p-2 overflow-y-auto"
         data-testid="customer-note-invoice-selector"
         onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="bg-white rounded-md w-full max-w-2xl my-4 shadow-xl">
        <div className={`flex items-center justify-between px-4 py-3 border-b ${kind === "credit" ? "bg-emerald-50 border-emerald-300" : "bg-orange-50 border-orange-300"}`}>
          <div className="font-bold">Select reference invoice · {kindLabel}</div>
          <button onClick={onClose} className="p-1 hover:bg-white/50 rounded-sm"><X size={16} /></button>
        </div>
        <div className="p-4 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div className="relative">
              <Search size={14} className="absolute top-2.5 left-2 text-zinc-400" />
              <input
                data-testid="cust-note-invoice-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Invoice number contains…"
                className="w-full border border-zinc-300 pl-7 pr-2 py-1.5 text-sm rounded-sm"
              />
            </div>
            <input
              type="date"
              data-testid="cust-note-invoice-date"
              value={dateFilter}
              onChange={(e) => setDateFilter(e.target.value)}
              className="w-full border border-zinc-300 px-2 py-1.5 text-sm rounded-sm"
            />
          </div>
          <div className="text-xs text-zinc-500">{invoices.length} invoice(s) for this customer</div>
          {isLoading ? (
            <div className="text-sm text-zinc-500 italic">Loading…</div>
          ) : (
            <div className="max-h-96 overflow-y-auto space-y-1 border border-zinc-200 rounded-sm">
              {invoices.length === 0 ? (
                <div className="p-4 text-center text-zinc-500 italic text-sm">No matching invoices.</div>
              ) : invoices.map((t) => (
                <button
                  key={t.id}
                  data-testid={`customer-note-invoice-option-${t.id}`}
                  onClick={() => setChosen(t)}
                  className="w-full text-left border-b border-zinc-100 last:border-b-0 px-3 py-2 hover:bg-zinc-50 flex items-center justify-between gap-2">
                  <div>
                    <div className="text-sm font-semibold">{t.ref}</div>
                    <div className="text-xs text-zinc-600">{fmtDate(t.date)}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-semibold">{fmtCurrency(t.amount)}</div>
                    <div className="text-xs text-zinc-600">Balance {fmtCurrency(t.effective_balance_due ?? t.balance_due ?? 0)}</div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
