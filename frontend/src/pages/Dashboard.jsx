import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate } from "@/api";
import { Link } from "react-router-dom";
import { TrendingUp, TrendingDown, Truck, FileText, Users, Wallet, ArrowUpRight, MessageCircle, AlertTriangle, Share2, Loader2, CheckCircle2, X } from "lucide-react";
import InsightsCard from "@/components/InsightsCard";
import RecurringTripsCard from "@/components/RecurringTripsCard";
import ExpenditureBreakdownCard from "@/components/ExpenditureBreakdownCard";

export default function Dashboard() {
  const [digestLoading, setDigestLoading] = React.useState(false);
  const { data, isLoading, isError, error, refetch } = useQuery({
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

  // Iter69 — Never block the whole Dashboard on any single API. Render the
  // shell + skeletons immediately so the user sees the app open in <1s and
  // widgets fill in as their data arrives. A hard failure surfaces inline
  // with a retry button instead of a permanent "Loading…" screen.
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
                const { data: d } = await api.get("/ai/daily-digest", { timeout: 60000 });
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

      {/* Iter69 — Non-blocking status banner. Only appears when the primary
          `/dashboard` call is still loading OR failed; the rest of the page
          remains interactive so the user can navigate elsewhere via the sidebar. */}
      {isLoading && (
        <div data-testid="dashboard-loading-banner" className="border border-zinc-200 bg-zinc-50 rounded-sm px-4 py-2 text-xs text-zinc-600 flex items-center gap-2">
          <Loader2 size={12} className="animate-spin" />
          Loading your dashboard data…
        </div>
      )}
      {isError && !isLoading && (() => {
        // Iter100 · Silent-restart routing.
        // Backend-restart-class errors (404 / 5xx / network) never surface as a
        // red banner — they flow through the top-right "Refreshing…" pill and
        // the TanStack Query retry policy (10 retries · ~65s). Only genuine
        // client / server errors show the red banner so users can retry.
        const s = error?.response?.status;
        const isNetwork = !s || error?.code === "ERR_NETWORK" || error?.message === "Network Error";
        const isRestart = isNetwork || [404, 502, 503, 504].includes(s);
        if (isRestart) {
          return (
            <div data-testid="dashboard-loading-banner" className="border border-zinc-200 bg-zinc-50 rounded-sm px-4 py-2 text-xs text-zinc-600 flex items-center gap-2">
              <Loader2 size={12} className="animate-spin" />
              Waiting for backend… retrying automatically.
            </div>
          );
        }
        return (
          <div data-testid="dashboard-error-banner" className="border border-rose-300 bg-rose-50 rounded-sm px-4 py-3 text-xs text-rose-800 flex items-center justify-between gap-3">
            <div>
              <div className="font-bold uppercase tracking-wider mb-0.5">Dashboard data couldn't load</div>
              <div>{error?.response?.data?.detail || error?.message || "Please retry — the rest of the app is available in the sidebar."}</div>
            </div>
            <button
              data-testid="dashboard-retry-btn"
              onClick={() => refetch()}
              className="px-3 py-1.5 text-[11px] uppercase tracking-wider font-semibold bg-rose-600 text-white rounded-sm hover:bg-rose-700"
            >Retry</button>
          </div>
        );
      })()}

      {/* AI Smart Insights */}
      <InsightsCard />

      {/* Recurring / One-Tap Trips */}
      <RecurringTripsCard />

      {/* Expenditure Breakdown — per-type spend chart */}
      <ExpenditureBreakdownCard />

      {/* Iter50/51 — Ops Observability Row: Save-Health */}
      <div className="grid grid-cols-1 gap-4">
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
  const [showAuthDrill, setShowAuthDrill] = React.useState(false);
  const [authDrillRange, setAuthDrillRange] = React.useState(null); // Iter58 P3 — {since, until} narrow window
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["save-health"],
    queryFn: async () => (await api.get("/admin/save-health", { params: { hours: 24 } })).data,
    refetchInterval: 60 * 1000, // 1-min live refresh
  });
  // Iter57 P3 — Sparkline (24 buckets over 24h)
  const { data: spark } = useQuery({
    queryKey: ["save-health-sparkline"],
    queryFn: async () => (await api.get("/admin/save-health/sparkline", { params: { hours: 24, buckets: 24 } })).data,
    refetchInterval: 60 * 1000,
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
  const authFailures = data?.auth_failures ?? 0;
  const saveFailures = data?.save_failures ?? 0;
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
          <div className="mt-1 flex items-center gap-3 text-[10px] font-mono">
            <span data-testid="save-health-save-failures" className="flex items-center gap-1">
              <span className="opacity-70 uppercase tracking-wider">Save</span>
              <span className="font-bold">{saveFailures}</span>
            </span>
            <span className="opacity-40">·</span>
            <button
              type="button"
              data-testid="save-health-auth-failures"
              onClick={() => { setAuthDrillRange(null); setShowAuthDrill(true); }}
              className="flex items-center gap-1 hover:underline focus:outline-none focus:underline"
              title="Click to see recent 401/403 failures"
            >
              <span className="opacity-70 uppercase tracking-wider">Auth</span>
              <span className="font-bold">{authFailures}</span>
              <span className="text-[9px] opacity-60">›</span>
            </button>
          </div>
          {/* Iter57 P3 — 24h sparkline (Iter58 P3: clickable buckets) */}
          {spark && (
            <div className="mt-2" data-testid="save-health-sparkline">
              <SaveHealthSparkline
                auth={spark.auth || []}
                save={spark.save || []}
                bucketMinutes={spark.bucket_minutes || 60}
                cutoff={spark.cutoff}
                onBucketClick={(idx) => {
                  const start = new Date(spark.cutoff);
                  const bucketMs = (spark.bucket_minutes || 60) * 60 * 1000;
                  const since = new Date(start.getTime() + idx * bucketMs).toISOString();
                  const until = new Date(start.getTime() + (idx + 1) * bucketMs).toISOString();
                  setAuthDrillRange({ since, until });
                  setShowAuthDrill(true);
                }}
              />
            </div>
          )}
          <div className="text-[10px] mt-1 opacity-70">
            Write requests (POST/PUT/PATCH/DELETE) returning HTTP ≥ 400 across all collections, plus 401/403 on <code className="font-mono">/api/auth/*</code>.
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
            <label className="flex flex-col md:col-span-2" data-testid="cfg-email-recipients-editor">
              <span className="text-[10px] uppercase tracking-wider opacity-70 mb-1 flex items-center gap-2">
                Email recipients
                <span className="font-mono normal-case tracking-normal opacity-70">
                  ({(formCfg.email_recipients || []).length} configured — all receive every alert)
                </span>
              </span>
              <div className="flex flex-wrap gap-2 border border-current/40 bg-white p-2 rounded-sm min-h-[40px]">
                {(formCfg.email_recipients || []).map((r, i) => (
                  <span key={i} data-testid={`recipient-chip-${i}`} className="inline-flex items-center gap-1 bg-emerald-100 text-emerald-900 border border-emerald-300 px-2 py-1 rounded-sm text-xs font-mono">
                    {r}
                    <button
                      data-testid={`recipient-remove-${i}`}
                      onClick={() => setFormCfg({ ...formCfg, email_recipients: (formCfg.email_recipients || []).filter((_, idx) => idx !== i) })}
                      className="text-emerald-700 hover:text-rose-700 font-bold ml-1"
                      title="Remove this recipient"
                    >×</button>
                  </span>
                ))}
                <input
                  data-testid="cfg-email-recipients-input"
                  type="email"
                  placeholder={(formCfg.email_recipients || []).length ? "+ add another…" : "owner@example.com"}
                  className="flex-1 min-w-[180px] outline-none text-zinc-900 text-xs bg-transparent"
                  onKeyDown={(e) => {
                    if ((e.key === "Enter" || e.key === "," || e.key === " ") && e.currentTarget.value.trim()) {
                      e.preventDefault();
                      const v = e.currentTarget.value.trim().replace(/,$/, "");
                      if (v.includes("@") && !((formCfg.email_recipients || []).includes(v))) {
                        setFormCfg({ ...formCfg, email_recipients: [...(formCfg.email_recipients || []), v] });
                      }
                      e.currentTarget.value = "";
                    }
                  }}
                  onBlur={(e) => {
                    const v = e.currentTarget.value.trim();
                    if (v && v.includes("@") && !((formCfg.email_recipients || []).includes(v))) {
                      setFormCfg({ ...formCfg, email_recipients: [...(formCfg.email_recipients || []), v] });
                      e.currentTarget.value = "";
                    }
                  }}
                />
              </div>
              <span className="text-[10px] mt-1 opacity-60">Press Enter, comma or space to add each address. Click ✕ to remove. Every alert is dispatched to ALL configured addresses.</span>
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
          <div className="text-[10px] uppercase tracking-wider font-bold opacity-70 pt-3">Alert Categories — enable/disable independently</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs" data-testid="cfg-alert-types-panel">
            {[
              ["save_failure", "Save failures", "Any POST/PUT/PATCH/DELETE returning ≥ 400"],
              ["trip_save_failure", "Trip save failures", "Trip create/update errors"],
              ["invoice_save_failure", "Invoice save failures", "Invoice create/update errors"],
              ["login_failure", "Login/auth failures", "401/403 on /api/auth/*"],
              ["deployment_failure", "Deployment failures", "Regression guard flips to fail"],
            ].map(([key, label, hint]) => (
              <label key={key} className="flex items-start gap-2 border border-current/20 rounded-sm px-3 py-2 bg-white hover:bg-current/5">
                <input
                  data-testid={`cfg-alert-type-${key}`}
                  type="checkbox"
                  checked={(formCfg.alert_types || {})[key] !== false}
                  onChange={(e) => setFormCfg({
                    ...formCfg,
                    alert_types: { ...(formCfg.alert_types || {}), [key]: e.target.checked },
                  })}
                  className="mt-0.5"
                />
                <span className="flex flex-col">
                  <span className="font-bold text-zinc-900">{label}</span>
                  <span className="text-[10px] text-zinc-500">{hint}</span>
                </span>
              </label>
            ))}
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
                  <li key={i} className="flex justify-between gap-2 py-1 border-b border-current/10 last:border-0" data-testid={`save-health-recent-${i}`}>
                    <span className="opacity-70">{(r.ts || "").slice(11, 19)}</span>
                    <span
                      className={`px-1 rounded-sm text-[9px] font-bold uppercase tracking-wider ${r.kind === "auth_failure" ? "bg-rose-200 text-rose-900" : "bg-amber-200 text-amber-900"}`}
                      data-testid={`save-health-recent-kind-${i}`}
                    >
                      {r.kind === "auth_failure" ? "AUTH" : "SAVE"}
                    </span>
                    <span className="flex-1 truncate">{r.method} {r.path?.slice(0, 40)}</span>
                    <span className="font-bold">{r.status}</span>
                  </li>
                ))}
              </ul>
            ) : <div className="text-xs italic opacity-60">Nothing recent.</div>}
          </div>
        </div>
      )}

      {/* Iter57 P2 — Auth-failure drill-down modal (Iter58 P3: accepts optional slice) */}
      {showAuthDrill && (
        <AuthFailureDrillModal
          range={authDrillRange}
          onClose={() => { setShowAuthDrill(false); setAuthDrillRange(null); }}
        />
      )}
    </div>
  );
}


// Iter57 P3 — Save Health Sparkline (tiny inline SVG, no external chart lib)
// Iter58 P3 — buckets are now clickable — clicking opens the drill-down modal
// scoped to that exact 1-hour slice.
function SaveHealthSparkline({ auth, save, bucketMinutes, cutoff, onBucketClick }) {
  const width = 220, height = 32, pad = 2;
  const buckets = Math.max(auth.length, save.length, 1);
  const maxVal = Math.max(1, ...auth, ...save);
  const stepX = (width - pad * 2) / Math.max(buckets - 1, 1);
  const yFor = (v) => height - pad - (v / maxVal) * (height - pad * 2);
  const pathFor = (arr) => arr.map((v, i) => `${i === 0 ? "M" : "L"}${(pad + i * stepX).toFixed(1)},${yFor(v).toFixed(1)}`).join(" ");
  const start = cutoff ? new Date(cutoff) : null;
  const bucketMs = (bucketMinutes || 60) * 60 * 1000;
  return (
    <div className="inline-flex items-center gap-2" title={`Last ${(buckets * bucketMinutes / 60).toFixed(0)}h · ${bucketMinutes.toFixed(0)}-min buckets · Click a bucket to drill down`}>
      <svg width={width} height={height} className="border border-current/20 rounded-sm bg-white/40" data-testid="save-health-sparkline-svg">
        <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="currentColor" strokeOpacity="0.15" strokeWidth="0.5" />
        <path d={pathFor(save)} fill="none" stroke="#d97706" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        <path d={pathFor(auth)} fill="none" stroke="#e11d48" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        {/* Iter58 P3 — Invisible hit targets per bucket for click-to-drill */}
        {onBucketClick && start && auth.map((_, i) => {
          const cx = pad + i * stepX;
          const bucketStart = new Date(start.getTime() + i * bucketMs);
          const label = bucketStart.toISOString().slice(11, 16) + " UTC";
          const authCount = auth[i] || 0;
          const saveCount = save[i] || 0;
          return (
            <rect
              key={i}
              data-testid={`sparkline-bucket-${i}`}
              x={cx - stepX / 2}
              y={0}
              width={stepX}
              height={height}
              fill="transparent"
              style={{ cursor: (authCount + saveCount) > 0 ? "pointer" : "default" }}
              onClick={() => { if ((authCount + saveCount) > 0) onBucketClick(i); }}
            >
              <title>{`${label} · Auth: ${authCount} · Save: ${saveCount}${authCount+saveCount>0 ? " (click to drill)" : ""}`}</title>
            </rect>
          );
        })}
      </svg>
      <div className="text-[9px] font-mono opacity-70 leading-tight flex flex-col">
        <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-[#d97706] inline-block" /> Save</span>
        <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-[#e11d48] inline-block" /> Auth</span>
      </div>
    </div>
  );
}


// Iter57 P2 — Auth Failure Drill-Down Modal (PII-safe: shows only ts/method/path/status/ip)
// Iter58 P3 — Accepts optional `range={since, until}` to narrow the window.
function AuthFailureDrillModal({ onClose, range }) {
  const params = { hours: 24, limit: 100 };
  if (range?.since) params.since = range.since;
  if (range?.until) params.until = range.until;
  const { data, isLoading } = useQuery({
    queryKey: ["auth-failures-drill", range?.since, range?.until],
    queryFn: async () => (await api.get("/admin/save-health/auth-failures", { params })).data,
    refetchInterval: 30 * 1000,
  });
  const label = range?.since
    ? `Slice: ${range.since.slice(11, 16)} → ${range.until.slice(11, 16)} UTC`
    : "Last 24h";
  return (
    <div
      data-testid="auth-drill-modal"
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="bg-white rounded-sm border border-zinc-300 w-full max-w-3xl max-h-[85vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200 bg-zinc-950 text-white">
          <div>
            <div className="text-[10px] uppercase tracking-[0.15em] font-bold opacity-70">Iter57 · Auth Failure Drill-Down</div>
            <div className="text-lg font-bold" data-testid="auth-drill-title">Recent 401/403 Failures · <span data-testid="auth-drill-scope">{label}</span></div>
          </div>
          <button
            type="button"
            data-testid="auth-drill-close"
            onClick={onClose}
            className="text-white/70 hover:text-white p-2 rounded-sm hover:bg-white/10"
          >
            <X size={16} />
          </button>
        </div>
        <div className="p-4 overflow-auto text-zinc-900">
          {isLoading ? (
            <div className="text-sm text-zinc-500 italic">Loading…</div>
          ) : !data ? (
            <div className="text-sm text-zinc-500 italic">No data.</div>
          ) : data.count === 0 ? (
            <div data-testid="auth-drill-empty" className="text-sm text-emerald-700 py-6 text-center">
              🟢 Zero authentication failures in the last 24 hours. Nice.
            </div>
          ) : (
            <>
              <div className="mb-3 flex flex-wrap gap-2 text-[11px] uppercase tracking-wider font-bold">
                <span className="bg-rose-50 text-rose-800 border border-rose-200 px-2 py-1 rounded-sm">Total: {data.count}</span>
                {data.top_ips.slice(0, 5).map((ip, i) => (
                  <span key={i} className="bg-zinc-100 text-zinc-800 border border-zinc-300 px-2 py-1 rounded-sm font-mono" data-testid={`auth-drill-top-ip-${i}`}>
                    {ip.ip} · {ip.count}
                  </span>
                ))}
              </div>
              <div className="mb-2 text-[11px] text-zinc-500 italic">
                Timestamps in UTC. IP source is <span className="font-mono">X-Forwarded-For</span> when present, else direct client host.
                No passwords, tokens or headers are captured or displayed.
              </div>
              <div className="overflow-x-auto border border-zinc-200 rounded-sm">
                <table className="w-full text-xs" data-testid="auth-drill-table">
                  <thead className="bg-zinc-100 text-zinc-700 text-[10px] uppercase tracking-wider">
                    <tr>
                      <th className="text-left px-3 py-2">Timestamp (UTC)</th>
                      <th className="text-left px-3 py-2">Method</th>
                      <th className="text-left px-3 py-2">Path</th>
                      <th className="text-right px-3 py-2">Status</th>
                      <th className="text-left px-3 py-2">Source IP</th>
                      <th className="text-right px-3 py-2">Latency</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100">
                    {data.items.map((r, i) => (
                      <tr key={i} data-testid={`auth-drill-row-${i}`} className={i % 2 === 0 ? "bg-white" : "bg-zinc-50/50"}>
                        <td className="px-3 py-2 font-mono text-zinc-600">{(r.ts_iso || "").replace("T", " ").slice(0, 19)}</td>
                        <td className="px-3 py-2 font-mono">{r.method}</td>
                        <td className="px-3 py-2 font-mono">{r.path}</td>
                        <td className="px-3 py-2 text-right font-mono font-bold text-rose-700">{r.status}</td>
                        <td className="px-3 py-2 font-mono">{r.ip || "—"}</td>
                        <td className="px-3 py-2 text-right font-mono text-zinc-500">{r.latency_ms ? `${r.latency_ms}ms` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
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

