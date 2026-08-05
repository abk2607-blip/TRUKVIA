import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate } from "@/api";
import { Link } from "react-router-dom";
import { TrendingUp, TrendingDown, Truck, FileText, Users, Wallet, ArrowUpRight } from "lucide-react";

export default function Dashboard() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard"],
    queryFn: async () => (await api.get("/dashboard")).data,
  });

  if (isLoading) return <div className="text-zinc-500">Loading...</div>;
  const d = data || {};

  const stats = [
    { label_te: "మొత్తం ఆదాయం", label_en: "Total Revenue", value: fmtCurrency(d.total_revenue), icon: TrendingUp, color: "text-emerald-600", testid: "stat-revenue" },
    { label_te: "మొత్తం ఖర్చులు", label_en: "Total Expenses", value: fmtCurrency(d.total_expense), icon: TrendingDown, color: "text-rose-600", testid: "stat-expense" },
    { label_te: "నికర లాభం", label_en: "Net Profit", value: fmtCurrency(d.total_profit), icon: Wallet, color: "text-zinc-950", testid: "stat-profit", highlight: true },
    { label_te: "బాకీ మొత్తం", label_en: "Receivables", value: fmtCurrency(d.total_receivable), icon: FileText, color: "text-amber-600", testid: "stat-receivable" },
  ];

  return (
    <div className="space-y-8" data-testid="dashboard-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Overview</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter text-zinc-950">
            <span className="telugu">డ్యాష్‌బోర్డ్</span>
            <span className="text-zinc-400"> · Dashboard</span>
          </h1>
        </div>
        <div className="flex gap-2">
          <Link to="/trips/new" data-testid="quick-new-trip" className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 transition-colors">
            + New Trip
          </Link>
          <Link to="/invoices/new" data-testid="quick-new-invoice" className="px-3 py-2 text-xs uppercase tracking-wider font-semibold border border-zinc-950 text-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white transition-colors">
            + New Invoice
          </Link>
        </div>
      </header>

      {/* KPI Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((s) => (
          <div key={s.label_en} data-testid={s.testid} className={`border p-5 rounded-sm bg-white ${s.highlight ? "border-zinc-950" : "border-zinc-200"}`}>
            <div className="flex items-center justify-between">
              <div className="text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-500">
                <span className="telugu">{s.label_te}</span> · {s.label_en}
              </div>
              <s.icon size={16} className={s.color} />
            </div>
            <div className="mt-4 font-mono text-2xl font-bold text-zinc-950">{s.value}</div>
          </div>
        ))}
      </div>

      {/* Counters row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MiniStat testid="mini-trips" icon={Truck} label="Trips" value={d.trip_count || 0} sub={`${d.pending_trips || 0} pending`} />
        <MiniStat testid="mini-invoices" icon={FileText} label="Invoices" value={d.invoice_count || 0} sub={`${fmtCurrency(d.total_billed)} billed`} />
        <MiniStat testid="mini-customers" icon={Users} label="Customers" value={d.customer_count || 0} />
        <MiniStat testid="mini-received" icon={Wallet} label="Received" value={fmtCurrency(d.total_received)} />
      </div>

      {/* Two-column: recent trips + receivables */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 border border-zinc-200 bg-white rounded-sm">
          <div className="px-5 py-3 border-b border-zinc-200 flex items-center justify-between">
            <h3 className="text-sm font-bold uppercase tracking-wider">Recent Trips</h3>
            <Link to="/trips" className="text-xs text-zinc-500 hover:text-zinc-950 inline-flex items-center gap-1">View all <ArrowUpRight size={12} /></Link>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="recent-trips-table">
              <thead className="bg-zinc-50">
                <tr className="text-[10px] uppercase tracking-wider text-zinc-500">
                  <th className="text-left px-4 py-2 font-semibold">Date</th>
                  <th className="text-left px-4 py-2 font-semibold">Customer</th>
                  <th className="text-left px-4 py-2 font-semibold">Vehicle</th>
                  <th className="text-right px-4 py-2 font-semibold">Tons</th>
                  <th className="text-right px-4 py-2 font-semibold">Freight</th>
                  <th className="text-right px-4 py-2 font-semibold">Profit</th>
                </tr>
              </thead>
              <tbody>
                {(d.recent_trips || []).map((t) => (
                  <tr key={t.id} className="border-t border-zinc-100">
                    <td className="px-4 py-2 font-mono text-xs">{fmtDate(t.date)}</td>
                    <td className="px-4 py-2">{t.customer_name || "—"}</td>
                    <td className="px-4 py-2 font-mono text-xs">{t.vehicle_number}</td>
                    <td className="px-4 py-2 text-right font-mono">{Number(t.tons).toFixed(2)}</td>
                    <td className="px-4 py-2 text-right font-mono">{fmtCurrency(t.freight_amount)}</td>
                    <td className={`px-4 py-2 text-right font-mono ${t.profit >= 0 ? "text-emerald-700" : "text-rose-700"}`}>{fmtCurrency(t.profit)}</td>
                  </tr>
                ))}
                {(d.recent_trips || []).length === 0 && (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-zinc-400 text-sm">No trips yet. Create your first trip.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="border border-zinc-200 bg-white rounded-sm">
          <div className="px-5 py-3 border-b border-zinc-200 flex items-center justify-between">
            <h3 className="text-sm font-bold uppercase tracking-wider">
              <span className="telugu">బాకీలు</span> · Receivables
            </h3>
          </div>
          <div className="divide-y divide-zinc-100 max-h-[380px] overflow-y-auto" data-testid="receivables-list">
            {(d.receivables || []).map((r) => (
              <div key={r.customer_id} className="px-5 py-3 flex items-center justify-between">
                <div>
                  <div className="text-sm font-semibold">{r.customer_name}</div>
                  <div className="text-[10px] text-zinc-500 uppercase tracking-wider">{r.invoices} invoice(s)</div>
                </div>
                <div className="font-mono text-sm font-bold text-amber-700">{fmtCurrency(r.balance)}</div>
              </div>
            ))}
            {(d.receivables || []).length === 0 && (
              <div className="px-5 py-8 text-center text-zinc-400 text-sm">No pending balances.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function MiniStat({ testid, icon: Icon, label, value, sub }) {
  return (
    <div data-testid={testid} className="border border-zinc-200 bg-white p-4 rounded-sm">
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-zinc-500 font-bold">
        <Icon size={12} /> {label}
      </div>
      <div className="mt-2 font-mono text-lg font-bold">{value}</div>
      {sub && <div className="text-[10px] text-zinc-500 mt-1">{sub}</div>}
    </div>
  );
}
