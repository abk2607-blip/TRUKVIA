/**
 * Iter53 — Deploy Guard Trend page.
 * 30-day pass/fail trend chart driven by /api/admin/deploy-history.
 * Shows a daily bucket line chart + rolling pass-rate + failed-test heatmap.
 */
import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { Link } from "react-router-dom";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine } from "recharts";
import { CheckCircle2, XCircle, RefreshCw, ArrowLeft } from "lucide-react";

export default function DeployHistoryPage() {
  const qc = useQueryClient();
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["deploy-history-full"],
    queryFn: async () => (await api.get("/admin/deploy-history", { params: { limit: 100 } })).data,
    refetchInterval: 60 * 1000,
  });
  const [running, setRunning] = React.useState(false);
  const runNow = useMutation({
    mutationFn: async () => (await api.post("/admin/deploy-readiness/run-now")).data,
    onSuccess: () => {
      setRunning(true);
      setTimeout(() => {
        setRunning(false);
        qc.invalidateQueries({ queryKey: ["deploy-history-full"] });
      }, 30000);
    },
  });

  // Aggregate history into per-day buckets covering the last 30 days
  const buckets = React.useMemo(() => {
    if (!data?.history) return [];
    const days = 30;
    const now = new Date();
    const bucketMap = {};
    for (let i = 0; i < days; i++) {
      const d = new Date(now);
      d.setDate(now.getDate() - (days - 1 - i));
      const key = d.toISOString().slice(0, 10);
      bucketMap[key] = { date: key, day: d.toLocaleDateString(undefined, { month: "short", day: "numeric" }), pass: 0, fail: 0, total: 0 };
    }
    for (const row of data.history) {
      const key = (row.checked_at || "").slice(0, 10);
      if (bucketMap[key]) {
        bucketMap[key][row.status === "pass" ? "pass" : "fail"] += 1;
        bucketMap[key].total += 1;
      }
    }
    return Object.values(bucketMap).map((b) => ({
      ...b,
      pass_rate: b.total ? Math.round((b.pass / b.total) * 100) : null,
    }));
  }, [data]);

  const failedByTest = React.useMemo(() => {
    if (!data?.history) return {};
    const map = {};
    for (const r of data.history) {
      if (r.status !== "fail") continue;
      for (const t of r.failed_tests || []) {
        map[t] = (map[t] || 0) + 1;
      }
    }
    return map;
  }, [data]);
  const topFailedTests = Object.entries(failedByTest).sort((a, b) => b[1] - a[1]).slice(0, 10);

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/dashboard" className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 hover:text-zinc-900 inline-flex items-center gap-1"><ArrowLeft size={12} /> Dashboard</Link>
          <h1 className="mt-1 text-3xl font-black tracking-tight">Deploy Guard · 30-day Trend</h1>
          <p className="text-xs text-zinc-500 mt-1">Regression suite pass/fail history for the last 30 days · Auto-refreshes every 60s</p>
        </div>
        <button
          data-testid="trend-refresh"
          onClick={() => { runNow.mutate(); }}
          disabled={running || isFetching}
          className="text-xs uppercase tracking-wider font-bold px-4 py-2 border border-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white inline-flex items-center gap-2 disabled:opacity-60"
        >
          <RefreshCw size={14} className={running || isFetching ? "animate-spin" : ""} />
          {running ? "Running…" : "Trigger New Run"}
        </button>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KPI label="Total Runs" value={data?.count ?? "—"} testid="kpi-total-runs" />
        <KPI label="Passes" value={data?.passes ?? "—"} tone="emerald" testid="kpi-passes" />
        <KPI label="Failures" value={data?.fails ?? "—"} tone="rose" testid="kpi-fails" />
        <KPI label="Pass Rate" value={data ? `${data.pass_rate}%` : "—"} tone={data?.pass_rate === 100 ? "emerald" : data?.pass_rate >= 90 ? "amber" : "rose"} testid="kpi-pass-rate" />
      </div>

      {/* Line chart — pass rate over 30 days */}
      <div className="border-2 border-zinc-950 rounded-sm p-4 bg-white" data-testid="trend-chart">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-bold">Pass-rate Trend · Daily buckets</h2>
          <span className="text-[10px] uppercase tracking-wider text-zinc-500">{buckets.length} days</span>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={buckets} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="day" stroke="#6b7280" style={{ fontSize: 10 }} />
            <YAxis domain={[0, 100]} stroke="#6b7280" style={{ fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
            <ReferenceLine y={100} stroke="#10b981" strokeDasharray="4 4" />
            <ReferenceLine y={90} stroke="#f59e0b" strokeDasharray="4 4" />
            <Tooltip formatter={(v, name) => [name === "pass_rate" ? `${v ?? "—"}%` : v, name === "pass_rate" ? "Pass rate" : name === "pass" ? "Passes" : "Failures"]} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line type="monotone" dataKey="pass_rate" stroke="#059669" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} name="Pass rate %" />
            <Line type="monotone" dataKey="fail" stroke="#e11d48" strokeWidth={1.5} dot={{ r: 2 }} name="Failures (count)" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Recent runs table + top failing tests */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-2 border border-zinc-300 rounded-sm bg-white">
          <div className="px-4 py-2 border-b border-zinc-200 text-[10px] uppercase tracking-wider font-bold text-zinc-500">
            Recent 20 Runs
          </div>
          <div className="max-h-[400px] overflow-y-auto">
            <table className="w-full text-xs" data-testid="recent-runs-table">
              <thead className="bg-zinc-50 sticky top-0">
                <tr>
                  <th className="text-left px-3 py-2 font-bold">Time</th>
                  <th className="text-left px-3 py-2 font-bold">Status</th>
                  <th className="text-right px-3 py-2 font-bold">Elapsed</th>
                  <th className="text-left px-3 py-2 font-bold">Failed Tests</th>
                </tr>
              </thead>
              <tbody>
                {(data?.history || []).slice().reverse().slice(0, 20).map((r, i) => (
                  <tr key={i} className="border-t border-zinc-100">
                    <td className="px-3 py-2 font-mono text-[10px]">{new Date(r.checked_at).toLocaleString()}</td>
                    <td className="px-3 py-2">
                      {r.status === "pass" ? (
                        <span className="inline-flex items-center gap-1 text-emerald-700 font-bold"><CheckCircle2 size={12} /> PASS</span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-rose-700 font-bold"><XCircle size={12} /> FAIL</span>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono text-right">{r.elapsed_s?.toFixed?.(1) ?? "—"}s</td>
                    <td className="px-3 py-2 font-mono text-[10px] text-rose-700">
                      {r.failed_tests?.length ? r.failed_tests.map((t) => t.replace(/^tests\//, "")).join(", ") : "—"}
                    </td>
                  </tr>
                ))}
                {!data?.history?.length && (
                  <tr><td colSpan={4} className="px-3 py-8 text-center text-zinc-400 italic">No runs recorded yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="border border-zinc-300 rounded-sm bg-white">
          <div className="px-4 py-2 border-b border-zinc-200 text-[10px] uppercase tracking-wider font-bold text-zinc-500">
            Top Failing Tests
          </div>
          <div className="p-3 space-y-2">
            {topFailedTests.length > 0 ? (
              topFailedTests.map(([test, count], i) => (
                <div key={i} className="flex items-center justify-between text-xs font-mono">
                  <span className="truncate" title={test}>{test.replace(/^tests\//, "")}</span>
                  <span className="inline-flex items-center justify-center min-w-[24px] px-1.5 py-0.5 bg-rose-100 text-rose-700 font-bold rounded-sm ml-2">{count}</span>
                </div>
              ))
            ) : (
              <div className="text-xs italic text-zinc-400 text-center py-6">No failing tests in the last {data?.count ?? 0} runs 🎉</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function KPI({ label, value, tone = "zinc", testid }) {
  const cls = tone === "emerald" ? "border-emerald-300 bg-emerald-50 text-emerald-900"
    : tone === "rose" ? "border-rose-300 bg-rose-50 text-rose-900"
    : tone === "amber" ? "border-amber-300 bg-amber-50 text-amber-900"
    : "border-zinc-300 bg-white text-zinc-900";
  return (
    <div data-testid={testid} className={`border rounded-sm p-4 ${cls}`}>
      <div className="text-[10px] uppercase tracking-[0.15em] font-bold opacity-70">{label}</div>
      <div className="mt-1 font-mono text-3xl font-black">{value}</div>
    </div>
  );
}
