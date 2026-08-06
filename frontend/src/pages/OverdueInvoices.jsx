import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, API, fmtCurrency, fmtDate } from "@/api";
import { MessageCircle, Mail, ExternalLink, AlertTriangle } from "lucide-react";

/**
 * Overdue Invoices dashboard for month-end reminders.
 * WhatsApp share via wa.me link · Email via mailto: with pre-filled subject/body.
 * Both open the user's own WhatsApp / Gmail — no API keys required.
 */
export default function OverdueInvoices() {
  const [days, setDays] = useState(30);

  const { data = [] } = useQuery({
    queryKey: ["overdue-invoices", days],
    queryFn: async () => (await api.get("/invoices/overdue", { params: { days } })).data,
  });
  const { data: company } = useQuery({
    queryKey: ["company"],
    queryFn: async () => (await api.get("/company")).data,
  });

  const totalOutstanding = data.reduce((s, i) => s + Number(i.balance_due || 0), 0);
  const oldest = data.length > 0 ? data[0] : null;

  const buildMessage = (inv) => {
    const co = company?.name || "our team";
    return `Dear ${inv.customer_name || "Customer"},\n\nThis is a friendly reminder from ${co} regarding Invoice ${inv.invoice_number} dated ${fmtDate(inv.invoice_date)} for ${fmtCurrency(inv.total_amount)}.\nOutstanding Balance: ${fmtCurrency(inv.balance_due)} (${inv.age_days} days overdue).\n\nInvoice PDF: ${API}/invoices/${inv.id}/pdf\n\nKindly arrange the payment at your earliest convenience. For any queries, please reach us on ${company?.phone || ""}.\n\nRegards,\n${co}`;
  };

  const whatsappUrl = (inv) => {
    const phone = (inv.customer_phone || "").replace(/[^0-9]/g, "");
    const num = phone.length === 10 ? `91${phone}` : phone; // assume India
    return `https://wa.me/${num}?text=${encodeURIComponent(buildMessage(inv))}`;
  };

  const gmailUrl = (inv) => {
    const subject = `Payment Reminder — Invoice ${inv.invoice_number} — ${company?.name || ""}`.trim();
    const body = buildMessage(inv);
    const to = inv.customer_email || "";
    // https://mail.google.com/mail/?view=cm&fs=1&to=&su=&body=
    return `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(to)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  };

  return (
    <div className="space-y-6" data-testid="overdue-invoices-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Payment Reminders</div>
          <h1 className="text-3xl font-black tracking-tighter">
            <span className="telugu">బకాయిలు</span>
            <span className="text-zinc-400"> · Overdue Invoices</span>
          </h1>
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-wider font-bold text-zinc-500">Overdue Beyond</label>
          <select data-testid="overdue-days-filter" value={days} onChange={(e) => setDays(Number(e.target.value))} className="mt-1 border border-zinc-300 px-3 py-1.5 rounded-sm text-sm bg-white">
            <option value={0}>Any pending</option>
            <option value={15}>15 days</option>
            <option value={30}>30 days</option>
            <option value={45}>45 days</option>
            <option value={60}>60 days</option>
            <option value={90}>90 days</option>
          </select>
        </div>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="border border-rose-300 bg-rose-50 p-3 rounded-sm">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Overdue Invoices</div>
          <div className="font-mono text-2xl font-black text-rose-800 mt-1">{data.length}</div>
        </div>
        <div className="border border-amber-300 bg-amber-50 p-3 rounded-sm">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Total Outstanding</div>
          <div className="font-mono text-2xl font-black text-amber-800 mt-1">{fmtCurrency(totalOutstanding)}</div>
        </div>
        <div className="border border-zinc-200 bg-white p-3 rounded-sm">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Oldest Invoice</div>
          <div className="font-mono text-lg font-bold mt-1">{oldest ? `${oldest.age_days}d` : "—"}</div>
          <div className="text-[10px] text-zinc-500">{oldest ? oldest.invoice_number : ""}</div>
        </div>
        <div className="border border-zinc-200 bg-white p-3 rounded-sm">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Customers</div>
          <div className="font-mono text-2xl font-black mt-1">{new Set(data.map((d) => d.customer_id)).size}</div>
        </div>
      </div>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-x-auto">
        <table className="w-full text-sm" data-testid="overdue-invoices-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-4 py-2">Invoice #</th>
              <th className="text-left px-4 py-2">Date</th>
              <th className="text-left px-4 py-2">Customer</th>
              <th className="text-right px-4 py-2">Total</th>
              <th className="text-right px-4 py-2">Balance Due</th>
              <th className="text-right px-4 py-2">Age</th>
              <th className="text-right px-4 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.map((inv) => (
              <tr key={inv.id} className="border-t border-zinc-100">
                <td className="px-4 py-3 font-mono font-semibold">
                  <Link to={`/invoices/${inv.id}`} className="hover:underline">{inv.invoice_number}</Link>
                </td>
                <td className="px-4 py-3 font-mono text-xs">{fmtDate(inv.invoice_date)}</td>
                <td className="px-4 py-3">
                  <div className="font-semibold">{inv.customer_name}</div>
                  <div className="text-[10px] text-zinc-500">{inv.customer_phone || "—"} · {inv.customer_email || "no email"}</div>
                </td>
                <td className="px-4 py-3 text-right font-mono">{fmtCurrency(inv.total_amount)}</td>
                <td className="px-4 py-3 text-right font-mono font-bold text-rose-700">{fmtCurrency(inv.balance_due)}</td>
                <td className="px-4 py-3 text-right">
                  <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-sm font-bold ${inv.age_days >= 60 ? "bg-rose-100 text-rose-800" : inv.age_days >= 30 ? "bg-amber-100 text-amber-800" : "bg-zinc-100 text-zinc-700"}`}>
                    {inv.age_days} days
                  </span>
                </td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  <a data-testid={`whatsapp-invoice-${inv.id}`} href={whatsappUrl(inv)} target="_blank" rel="noreferrer"
                     title={inv.customer_phone ? "Send WhatsApp reminder" : "Customer phone missing"}
                     className={`inline-flex items-center gap-1 px-2 py-1 text-xs border rounded-sm mr-1 ${inv.customer_phone ? "border-emerald-300 text-emerald-700 hover:bg-emerald-50" : "border-zinc-200 text-zinc-400 pointer-events-none"}`}>
                    <MessageCircle size={11} /> WhatsApp
                  </a>
                  <a data-testid={`gmail-invoice-${inv.id}`} href={gmailUrl(inv)} target="_blank" rel="noreferrer"
                     title={inv.customer_email ? "Compose reminder in Gmail" : "No email — Gmail will still open"}
                     className="inline-flex items-center gap-1 px-2 py-1 text-xs border border-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white mr-1">
                    <Mail size={11} /> Gmail
                  </a>
                  <a data-testid={`pdf-invoice-${inv.id}`} href={`${API}/invoices/${inv.id}/pdf`} target="_blank" rel="noreferrer"
                     className="inline-flex items-center gap-1 px-2 py-1 text-xs border border-zinc-200 rounded-sm hover:bg-zinc-100">
                    <ExternalLink size={11} /> PDF
                  </a>
                </td>
              </tr>
            ))}
            {data.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-14 text-center text-zinc-400 text-sm"><AlertTriangle size={22} className="inline mb-2 text-emerald-600" /><br/>All caught up — no invoices overdue by {days}+ days.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="text-[11px] text-zinc-500 bg-zinc-50 border border-zinc-200 rounded-sm p-3">
        <span className="font-bold">Tip:</span> WhatsApp opens your own WhatsApp Web / app with the reminder pre-typed for the customer's number.
        Gmail opens Compose in your Gmail account with a pre-filled subject and invoice download link — just review and hit Send. No credentials required.
      </div>
    </div>
  );
}
