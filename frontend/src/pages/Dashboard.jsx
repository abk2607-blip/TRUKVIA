import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate } from "@/api";
import { Link } from "react-router-dom";
import { TrendingUp, TrendingDown, Truck, FileText, Users, Wallet, ArrowUpRight, MessageCircle, AlertTriangle, Share2, Loader2, CheckCircle2 } from "lucide-react";
import InsightsCard from "@/components/InsightsCard";
import RecurringTripsCard from "@/components/RecurringTripsCard";
import ExpenditureBreakdownCard from "@/components/ExpenditureBreakdownCard";

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

      {/* Expenditure Breakdown — per-type spend chart */}
      <ExpenditureBreakdownCard />

      {/* Iter50/51 — Ops Observability Row: Deploy Guard + Save-Health */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <DeployGuardTile />
        <SaveHealthTile />
      </div>

      {/* Iter51 — Active Save-Health Alerts (banners) */}
      <SaveHealthAlertsBanner />

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


// Iter50/51 — Save-Health Ops tile with threshold-config editor.
function SaveHealthTile() {
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [showCfg, setShowCfg] = React.useState(false);
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["save-health"],
    queryFn: async () => (await api.get("/admin/save-health", { params: { hours: 24 } })).data,
    refetchInterval: 60 * 1000, // 1-min live refresh
  });
  const { data: cfg } = useQuery({
    queryKey: ["save-health-alert-config"],
    queryFn: async () => (await api.get("/admin/save-health/alert-config")).data,
  });
  const [formCfg, setFormCfg] = React.useState(null);
  React.useEffect(() => { if (cfg) setFormCfg(cfg); }, [cfg]);
  const saveCfg = useMutation({
    mutationFn: async (payload) => (await api.put("/admin/save-health/alert-config", payload)).data,
    onSuccess: () => { qc.invalidateQueries(["save-health-alert-config"]); setShowCfg(false); },
  });
  const total = data?.total_failures ?? 0;
  const tone = total === 0 ? "border-emerald-300 bg-emerald-50 text-emerald-900"
    : total <= 5 ? "border-amber-300 bg-amber-50 text-amber-900"
    : "border-rose-300 bg-rose-50 text-rose-900";
  const badge = total === 0 ? "🟢 Healthy" : total <= 5 ? "🟡 Watch" : "🔴 Alert";
  return (
    <div data-testid="save-health-tile" className={`border p-4 rounded-sm ${tone}`}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-[0.15em] font-bold flex items-center gap-2">
            <AlertTriangle size={12} /> Save Health · Last 24h
          </div>
          <div className="mt-2 flex items-baseline gap-3">
            <span data-testid="save-health-total" className="font-mono text-3xl font-black">{isLoading ? "…" : total}</span>
            <span className="text-xs font-semibold">{badge}</span>
          </div>
          <div className="text-[10px] mt-1 opacity-70">
            Write requests (POST/PUT/PATCH/DELETE) returning HTTP ≥ 400 across all collections.
            {cfg && (
              <span className="ml-1">
                Alert threshold: <b>{cfg.threshold}</b> / {cfg.window_hours}h
                {!cfg.enabled && <span className="ml-1 text-zinc-500">(disabled)</span>}
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <button
            data-testid="save-health-toggle"
            onClick={() => { setOpen((o) => !o); if (!open) refetch(); }}
            className="text-[10px] uppercase tracking-wider font-bold px-3 py-1.5 border border-current rounded-sm hover:bg-white/40"
          >
            {open ? "Hide" : "View details"}
          </button>
          <button
            data-testid="save-health-configure"
            onClick={() => setShowCfg((s) => !s)}
            className="text-[10px] uppercase tracking-wider font-bold px-3 py-1.5 border border-current rounded-sm hover:bg-white/40"
          >
            Configure
          </button>
        </div>
      </div>

      {showCfg && formCfg && (
        <div className="mt-4 pt-4 border-t border-current/20 space-y-3" data-testid="save-health-config-panel">
          <div className="text-[10px] uppercase tracking-wider font-bold opacity-70">Alert Threshold Configuration</div>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs">
            <label className="flex flex-col">
              <span className="text-[10px] uppercase tracking-wider opacity-70 mb-1">Threshold (failures)</span>
              <input data-testid="cfg-threshold" type="number" min="1" value={formCfg.threshold}
                onChange={(e) => setFormCfg({ ...formCfg, threshold: Number(e.target.value) })}
                className="border border-current/40 bg-white px-2 py-1 rounded-sm font-mono text-zinc-900" />
            </label>
            <label className="flex flex-col">
              <span className="text-[10px] uppercase tracking-wider opacity-70 mb-1">Window (hours)</span>
              <input data-testid="cfg-window" type="number" min="1" value={formCfg.window_hours}
                onChange={(e) => setFormCfg({ ...formCfg, window_hours: Number(e.target.value) })}
                className="border border-current/40 bg-white px-2 py-1 rounded-sm font-mono text-zinc-900" />
            </label>
            <label className="flex flex-col">
              <span className="text-[10px] uppercase tracking-wider opacity-70 mb-1">Cooldown (min)</span>
              <input data-testid="cfg-cooldown" type="number" min="5" value={formCfg.cooldown_min}
                onChange={(e) => setFormCfg({ ...formCfg, cooldown_min: Number(e.target.value) })}
                className="border border-current/40 bg-white px-2 py-1 rounded-sm font-mono text-zinc-900" />
            </label>
            <label className="flex items-center gap-2 text-xs mt-4">
              <input data-testid="cfg-enabled" type="checkbox" checked={formCfg.enabled}
                onChange={(e) => setFormCfg({ ...formCfg, enabled: e.target.checked })} />
              <span>Alerts enabled</span>
            </label>
          </div>
          <div className="text-[10px] uppercase tracking-wider font-bold opacity-70 pt-2">Delivery Channels & Recipients</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
            <label className="flex flex-col md:col-span-2">
              <span className="text-[10px] uppercase tracking-wider opacity-70 mb-1">Email recipients (comma-separated)</span>
              <input data-testid="cfg-email-recipients" type="text"
                value={(formCfg.email_recipients || []).join(", ")}
                onChange={(e) => setFormCfg({ ...formCfg, email_recipients: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                className="border border-current/40 bg-white px-2 py-1 rounded-sm text-zinc-900"
                placeholder="owner@example.com, ops@example.com" />
            </label>
            <label className="flex flex-col">
              <span className="text-[10px] uppercase tracking-wider opacity-70 mb-1">Channels</span>
              <div className="flex gap-3">
                <label className="flex items-center gap-1 text-xs">
                  <input data-testid="cfg-channel-email" type="checkbox"
                    checked={(formCfg.channels || []).includes("email")}
                    onChange={(e) => {
                      const cur = new Set(formCfg.channels || []);
                      e.target.checked ? cur.add("email") : cur.delete("email");
                      setFormCfg({ ...formCfg, channels: Array.from(cur) });
                    }} />
                  <span>Email</span>
                </label>
                <label className="flex items-center gap-1 text-xs">
                  <input data-testid="cfg-channel-whatsapp" type="checkbox"
                    checked={(formCfg.channels || []).includes("whatsapp")}
                    onChange={(e) => {
                      const cur = new Set(formCfg.channels || []);
                      e.target.checked ? cur.add("whatsapp") : cur.delete("whatsapp");
                      setFormCfg({ ...formCfg, channels: Array.from(cur) });
                    }} />
                  <span>WhatsApp (manual share)</span>
                </label>
              </div>
            </label>
            <label className="flex flex-col">
              <span className="text-[10px] uppercase tracking-wider opacity-70 mb-1">WhatsApp phone (optional, E.164 digits only)</span>
              <input data-testid="cfg-wa-phone" type="text"
                value={formCfg.wa_phone || ""}
                onChange={(e) => setFormCfg({ ...formCfg, wa_phone: e.target.value.replace(/\D/g, "") })}
                placeholder="919999999999"
                className="border border-current/40 bg-white px-2 py-1 rounded-sm font-mono text-zinc-900" />
            </label>
          </div>
          <div className="flex gap-2 flex-wrap">
            <button data-testid="cfg-save" onClick={() => saveCfg.mutate(formCfg)}
              className="px-3 py-1.5 bg-zinc-950 text-white text-[10px] uppercase tracking-wider font-bold rounded-sm">
              Save Configuration
            </button>
            <button data-testid="cfg-test-alert" onClick={async () => {
              try {
                const { data: r } = await api.post("/admin/save-health/alerts/test");
                const sent = r?.email?.sent?.length || 0;
                if (sent > 0) {
                  alert(`Test email sent to ${sent} recipient(s). Also generated WhatsApp deeplink — check the recent alerts panel.`);
                } else {
                  alert(`Test complete. Result: ${JSON.stringify(r).slice(0, 200)}`);
                }
              } catch (e) {
                alert(`Test failed: ${e?.response?.data?.detail || e?.message || "unknown error"}`);
              }
            }}
              className="px-3 py-1.5 border border-current text-[10px] uppercase tracking-wider font-bold rounded-sm hover:bg-white/40">
              Send Test Alert
            </button>
            <button onClick={() => setShowCfg(false)}
              className="px-3 py-1.5 border border-current text-[10px] uppercase tracking-wider font-bold rounded-sm">
              Cancel
            </button>
          </div>
        </div>
      )}

      {open && data && (
        <div className="mt-4 pt-4 border-t border-current/20 grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="save-health-details">
          <div>
            <div className="text-[10px] uppercase tracking-wider font-bold opacity-70 mb-2">By Collection</div>
            {data.per_collection?.length ? (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left opacity-70 border-b border-current/20">
                    <th className="py-1">Collection</th><th>Status</th><th className="text-right">Count</th>
                  </tr>
                </thead>
                <tbody>
                  {data.per_collection.map((r, i) => (
                    <tr key={i} className="border-b border-current/10 last:border-0">
                      <td className="py-1 font-mono">{r.collection}</td>
                      <td className="font-mono">{r.status}</td>
                      <td className="text-right font-mono font-bold">{r.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <div className="text-xs italic opacity-60">No save failures in the last 24 hours.</div>}
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider font-bold opacity-70 mb-2">Recent Failures</div>
            {data.recent?.length ? (
              <ul className="space-y-1 text-[10px] font-mono">
                {data.recent.slice(0, 10).map((r, i) => (
                  <li key={i} className="flex justify-between gap-2 py-1 border-b border-current/10 last:border-0">
                    <span className="opacity-70">{(r.ts || "").slice(11, 19)}</span>
                    <span className="flex-1 truncate">{r.method} {r.path?.slice(0, 40)}</span>
                    <span className="font-bold">{r.status}</span>
                  </li>
                ))}
              </ul>
            ) : <div className="text-xs italic opacity-60">Nothing recent.</div>}
          </div>
        </div>
      )}
    </div>
  );
}


// Iter51/52 — Deploy Guard status tile with history bar (P4).
function DeployGuardTile() {
  const [running, setRunning] = React.useState(false);
  const [showHistory, setShowHistory] = React.useState(false);
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["deploy-readiness"],
    queryFn: async () => (await api.get("/admin/deploy-readiness")).data,
    refetchInterval: 60 * 1000,
  });
  const { data: hist } = useQuery({
    queryKey: ["deploy-history"],
    queryFn: async () => (await api.get("/admin/deploy-history", { params: { limit: 30 } })).data,
    refetchInterval: 60 * 1000,
  });
  const status = data?.status || "unknown";
  const tone = status === "pass" ? "border-emerald-300 bg-emerald-50 text-emerald-900"
    : status === "fail" ? "border-rose-300 bg-rose-50 text-rose-900"
    : "border-zinc-200 bg-zinc-50 text-zinc-700";
  const badge = status === "pass" ? "🟢 Guard PASS · Safe to Deploy"
    : status === "fail" ? "🔴 Guard FAIL · Deploy BLOCKED"
    : "🟡 Not yet checked";
  const runNow = async () => {
    setRunning(true);
    try {
      await api.post("/admin/deploy-readiness/run-now");
      setTimeout(() => { refetch(); setRunning(false); }, 20000);
    } catch { setRunning(false); }
  };
  return (
    <div data-testid="deploy-guard-tile" className={`border p-4 rounded-sm ${tone}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-[0.15em] font-bold flex items-center gap-2">
            <CheckCircle2 size={12} /> Deploy Regression Guard
          </div>
          <div className="mt-2 text-xs font-bold" data-testid="deploy-guard-badge">{isLoading ? "…" : badge}</div>
          {data?.checked_at && (
            <div className="text-[10px] mt-1 opacity-70">
              Last check: {new Date(data.checked_at).toLocaleTimeString()}
              {data.elapsed_s != null && <span> · {data.elapsed_s}s</span>}
              {data.exit_code != null && <span> · exit={data.exit_code}</span>}
            </div>
          )}
          <div className="text-[10px] mt-1 opacity-70">
            Runs iter42-51 (73 tests). Enforced by <code className="font-mono">REGRESSION_GUARD_STRICT=1</code>.
          </div>
          {/* Iter52 — Guard History mini bar */}
          {hist?.history?.length > 0 && (
            <div className="mt-3">
              <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider opacity-70 mb-1">
                <span>History · last {hist.count} runs</span>
                <span className="font-bold">{hist.pass_rate}% pass · {hist.passes}✓ / {hist.fails}✗</span>
              </div>
              <div className="flex items-end gap-[2px] h-6" data-testid="deploy-guard-history-bars">
                {hist.history.map((h, i) => (
                  <div
                    key={i}
                    title={`${new Date(h.checked_at).toLocaleString()} — ${h.status.toUpperCase()}${h.failed_tests?.length ? " · " + h.failed_tests.join(", ") : ""}`}
                    className={`flex-1 rounded-sm min-w-[3px] ${h.status === "pass" ? "bg-emerald-500" : "bg-rose-500"}`}
                    style={{ height: `${h.status === "pass" ? 100 : 80}%` }}
                  />
                ))}
              </div>
              <button
                data-testid="deploy-guard-history-toggle"
                onClick={() => setShowHistory((s) => !s)}
                className="mt-2 text-[10px] uppercase tracking-wider font-bold underline opacity-70 hover:opacity-100"
              >
                {showHistory ? "Hide" : "See"} failed runs
              </button>
              {showHistory && (
                <div className="mt-2 text-[10px] font-mono space-y-1" data-testid="deploy-guard-history-list">
                  {hist.history.filter((h) => h.status === "fail").slice(-10).map((h, i) => (
                    <div key={i} className="flex gap-2 border-b border-current/10 py-1">
                      <span className="opacity-70">{new Date(h.checked_at).toLocaleString()}</span>
                      <span className="text-rose-700 font-bold">FAIL</span>
                      <span className="truncate">{(h.failed_tests || []).join(", ") || "(no test list captured)"}</span>
                    </div>
                  ))}
                  {hist.history.filter((h) => h.status === "fail").length === 0 && (
                    <div className="italic opacity-60">No failed runs recorded yet 🎉</div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
        <button
          data-testid="deploy-guard-run-now"
          onClick={runNow}
          disabled={running}
          className="text-[10px] uppercase tracking-wider font-bold px-3 py-1.5 border border-current rounded-sm hover:bg-white/40 disabled:opacity-60"
        >
          {running ? "Running…" : "Re-run"}
        </button>
      </div>
    </div>
  );
}

// Iter51 — Save-Health Alerts banner. Shows only when an unacknowledged
// alert exists (i.e. the failure count crossed the configured threshold).
function SaveHealthAlertsBanner() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["save-health-alerts"],
    queryFn: async () => (await api.get("/admin/save-health/alerts", { params: { unacknowledged_only: true, limit: 3 } })).data,
    refetchInterval: 60 * 1000,
  });
  const ack = useMutation({
    mutationFn: async (fired_at) => (await api.post(`/admin/save-health/alerts/${encodeURIComponent(fired_at)}/ack`)).data,
    onSuccess: () => qc.invalidateQueries(["save-health-alerts"]),
  });
  const alerts = data?.alerts || [];
  if (!alerts.length) return null;
  return (
    <div className="space-y-2" data-testid="save-health-alerts-banner">
      {alerts.map((a) => (
        <div key={a.fired_at} className="border-2 border-rose-500 bg-rose-50 text-rose-900 rounded-sm p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-[0.15em] font-black text-rose-700 flex items-center gap-2">
                <AlertTriangle size={14} /> Save-Health Alert
              </div>
              <div className="mt-1 font-bold text-sm">
                {a.total_failures} save failures in the last {a.window_hours}h — threshold was {a.threshold}.
              </div>
              <div className="text-[10px] mt-1 opacity-80">Fired at {new Date(a.fired_at).toLocaleString()}</div>
              {a.top_offenders?.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
                  {a.top_offenders.map((o, i) => (
                    <span key={i} className="px-2 py-1 bg-white border border-rose-300 rounded-sm font-mono">
                      {o.collection} · {o.status} · {o.count}
                    </span>
                  ))}
                </div>
              )}
              {a.recent_errors?.length > 0 && (
                <details className="mt-2 text-[10px] font-mono">
                  <summary className="cursor-pointer">Recent errors ({a.recent_errors.length})</summary>
                  <ul className="mt-1 space-y-1">
                    {a.recent_errors.slice(0, 5).map((r, i) => (
                      <li key={i} className="flex gap-2">
                        <span className="opacity-70">{(r.ts || "").slice(11, 19)}</span>
                        <span>{r.method} {r.path?.slice(0, 60)}</span>
                        <span className="font-bold">{r.status}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
            <div className="flex flex-col gap-2 items-end shrink-0">
              {a.whatsapp_url && (
                <a
                  data-testid={`share-wa-${a.fired_at}`}
                  href={a.whatsapp_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[10px] uppercase tracking-wider font-bold px-3 py-2 border border-emerald-600 bg-emerald-50 text-emerald-900 rounded-sm hover:bg-emerald-100 inline-flex items-center gap-1"
                >
                  📱 Share on WhatsApp
                </a>
              )}
              <button
                data-testid={`ack-alert-${a.fired_at}`}
                onClick={() => ack.mutate(a.fired_at)}
                className="text-[10px] uppercase tracking-wider font-bold px-3 py-2 border border-rose-500 rounded-sm hover:bg-rose-100"
              >
                Acknowledge
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

