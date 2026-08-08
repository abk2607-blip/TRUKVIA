import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate } from "@/api";
import { Link } from "react-router-dom";
import { TrendingUp, TrendingDown, Truck, FileText, Users, Wallet, ArrowUpRight, MessageCircle, AlertTriangle, Share2, Loader2 } from "lucide-react";
import InsightsCard from "@/components/InsightsCard";
import RecurringTripsCard from "@/components/RecurringTripsCard";

export default function Dashboard() {
  const [digestLoading, setDigestLoading] = React.useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard"],
    queryFn: async () => (await api.get("/dashboard")).data,
  });
  const { data: gst } = useQuery({
    queryKey: ["gst-summary"],
    queryFn: async () => (await api.get("/reports/gst-summary")).data,
  });
  const { data: overdue = [] } = useQuery({
    queryKey: ["overdue-invoices-widget"],
    queryFn: async () => (await api.get("/invoices/overdue", { params: { days: 30 } })).data,
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
          <button
            data-testid="daily-digest-btn"
            disabled={digestLoading}
            onClick={async () => {
              setDigestLoading(true);
              try {
                const { data: d } = await api.get("/ai/daily-digest");
                window.open(d.whatsapp_url, "_blank");
              } catch (e) {
                console.error(e);
              } finally {
                setDigestLoading(false);
              }
            }}
            className="px-3 py-2 text-xs uppercase tracking-wider font-semibold border border-emerald-500 text-emerald-800 bg-emerald-50 rounded-sm hover:bg-emerald-100 inline-flex items-center gap-2 disabled:opacity-50"
            title="Send today's business digest via WhatsApp"
          >
            {digestLoading ? <Loader2 size={12} className="animate-spin" /> : <Share2 size={12} />}
            Daily Digest
          </button>
          <Link to="/trips/new" data-testid="quick-new-trip" className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 transition-colors">
            + New Trip
          </Link>
          <Link to="/invoices/new" data-testid="quick-new-invoice" className="px-3 py-2 text-xs uppercase tracking-wider font-semibold border border-zinc-950 text-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white transition-colors">
            + New Invoice
          </Link>
        </div>
      </header>

      {/* AI Smart Insights */}
      <InsightsCard />

      {/* Recurring / One-Tap Trips */}
      <RecurringTripsCard />

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

      {/* GST Summary + Overdue widgets */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4" data-testid="gst-summary-widget">
        {gst && (
          <>
            <div className="border border-zinc-950 bg-white rounded-sm p-4 lg:col-span-2">
              <div className="flex items-center justify-between mb-2">
                <div className="text-[11px] uppercase tracking-wider font-bold text-zinc-500">GST Summary — Current Month · {gst.current_month.start?.slice(0,7)}</div>
                <Link to="/reports/gstr1" className="text-[10px] text-zinc-500 hover:text-zinc-950 inline-flex items-center gap-1">GSTR-1 <ArrowUpRight size={11} /></Link>
              </div>
              <div className="grid grid-cols-3 gap-3 text-sm">
                <GstCell label="CGST" value={fmtCurrency(gst.current_month.cgst)} />
                <GstCell label="SGST" value={fmtCurrency(gst.current_month.sgst)} />
                <GstCell label="IGST" value={fmtCurrency(gst.current_month.igst)} />
                <GstCell label="Taxable" value={fmtCurrency(gst.current_month.taxable)} muted />
                <GstCell label="Total Tax" value={fmtCurrency(gst.current_month.total_tax)} accent="amber" />
                <GstCell label="Invoices" value={gst.current_month.invoices} />
              </div>
              <div className="mt-3 pt-3 border-t border-zinc-100 flex flex-wrap gap-4 text-[11px]">
                <div><span className="text-zinc-500 uppercase tracking-wider font-bold">FY {gst.current_fy.start?.slice(2,4)}-{gst.current_fy.end?.slice(2,4)} Taxable:</span> <span className="font-mono font-bold ml-1">{fmtCurrency(gst.current_fy.taxable)}</span></div>
                <div><span className="text-zinc-500 uppercase tracking-wider font-bold">FY Tax:</span> <span className="font-mono font-bold ml-1">{fmtCurrency(gst.current_fy.total_tax)}</span></div>
                <div><span className="text-zinc-500 uppercase tracking-wider font-bold">Next GSTR-1:</span> <span className="font-mono ml-1">{gst.next_gstr1_due}</span></div>
                <div><span className="text-zinc-500 uppercase tracking-wider font-bold">Next GSTR-3B:</span> <span className="font-mono ml-1">{gst.next_gstr3b_due}</span></div>
              </div>
            </div>
            <Link to="/invoices/overdue" className={`border rounded-sm p-4 block hover:shadow-md transition-shadow ${overdue.length > 0 ? "border-rose-300 bg-rose-50" : "border-emerald-300 bg-emerald-50"}`} data-testid="overdue-widget">
              <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider font-bold text-zinc-500">
                <AlertTriangle size={12} className={overdue.length > 0 ? "text-rose-600" : "text-emerald-600"} /> Overdue Invoices (30+ days)
              </div>
              <div className={`font-mono text-4xl font-black mt-2 ${overdue.length > 0 ? "text-rose-800" : "text-emerald-800"}`}>{overdue.length}</div>
              <div className="font-mono text-sm mt-1">
                {fmtCurrency(overdue.reduce((s, i) => s + Number(i.balance_due || 0), 0))} outstanding
              </div>
              <div className="mt-3 text-[11px] text-zinc-600 inline-flex items-center gap-1">
                Send reminders <ArrowUpRight size={11} />
              </div>
            </Link>
          </>
        )}
      </div>

      {/* Expiry alerts */}
      {(d.expiry_alerts || []).length > 0 && (
        <div className="border border-amber-300 bg-amber-50 rounded-sm p-4" data-testid="expiry-alerts">
          <div className="flex items-center gap-2 mb-2 text-sm font-bold uppercase tracking-wider text-amber-900">
            <AlertTriangle size={14} /> Vehicle Document Alerts
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {(d.expiry_alerts || []).slice(0, 9).map((a, i) => (
              <div key={i} className={`border rounded-sm px-3 py-2 text-xs flex justify-between items-center ${a.status === "expired" ? "border-rose-300 bg-white" : "border-amber-300 bg-white"}`}>
                <div>
                  <span className="font-bold font-mono">{a.vehicle_number}</span>
                  <span className="ml-2 text-zinc-600">{a.document}</span>
                </div>
                <div className={`font-mono ${a.status === "expired" ? "text-rose-700" : "text-amber-800"}`}>
                  {a.status === "expired" ? `Expired ${Math.abs(a.days)}d ago` : `${a.days}d left`}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

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
            {(d.receivables || []).map((r) => {
              const overdue = r.oldest_days >= 15;
              const phone = (r.customer_phone || "").replace(/[^\d]/g, "");
              const msg = `Namaste ${r.customer_name}, mee paiki ₹${Number(r.balance).toLocaleString("en-IN")} balance undi. Dayachesi payment cheyandi. Thank you. — ${window.location.host}`;
              const waLink = phone ? `https://wa.me/${phone.length === 10 ? "91" + phone : phone}?text=${encodeURIComponent(msg)}` : null;
              const smsLink = phone ? `sms:${phone}?body=${encodeURIComponent(msg)}` : null;
              return (
                <div key={r.customer_id} className="px-5 py-3 flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold truncate">{r.customer_name}</div>
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider flex items-center gap-1">
                      {r.invoices} invoice{r.invoices > 1 ? "s" : ""}
                      {r.oldest_days > 0 && (
                        <span className={`ml-1 px-1.5 py-0.5 rounded-sm border ${overdue ? "border-rose-300 bg-rose-50 text-rose-700" : "border-zinc-200 text-zinc-600"}`}>
                          {r.oldest_days}d
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="font-mono text-sm font-bold text-amber-700 whitespace-nowrap">{fmtCurrency(r.balance)}</div>
                    {waLink && (
                      <a
                        data-testid={`whatsapp-remind-${r.customer_id}`}
                        href={waLink}
                        target="_blank"
                        rel="noreferrer"
                        title="WhatsApp reminder"
                        className="p-1.5 border border-emerald-300 text-emerald-700 hover:bg-emerald-50 rounded-sm"
                      >
                        <MessageCircle size={14} />
                      </a>
                    )}
                    {!phone && (
                      <span className="text-[10px] text-zinc-400 italic">No phone</span>
                    )}
                  </div>
                </div>
              );
            })}
            {(d.receivables || []).length === 0 && (
              <div className="px-5 py-8 text-center text-zinc-400 text-sm">No pending balances.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function GstCell({ label, value, accent, muted }) {
  const cls = accent === "amber" ? "text-amber-800 bg-amber-50 border-amber-200"
    : muted ? "text-zinc-500 bg-zinc-50 border-zinc-100"
    : "border-zinc-100 bg-white";
  return (
    <div className={`border rounded-sm p-2 ${cls}`}>
      <div className="text-[9px] uppercase tracking-wider font-bold text-zinc-500">{label}</div>
      <div className="font-mono font-bold text-sm mt-0.5">{value}</div>
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
