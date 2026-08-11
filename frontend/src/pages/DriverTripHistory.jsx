// Iter60 · Phase B — Driver Trip History (Trip = single source of truth).
import React from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate } from "@/api";
import { ArrowLeft, Eye, AlertTriangle } from "lucide-react";

export default function DriverTripHistory() {
  const { id } = useParams();
  const [dateFrom, setDateFrom] = React.useState("");
  const [dateTo, setDateTo] = React.useState("");
  const [page, setPage] = React.useState(0);
  const PAGE_SIZE = 50;

  const { data, isLoading } = useQuery({
    queryKey: ["driver-trips", id, dateFrom, dateTo, page],
    queryFn: async () => (await api.get(`/drivers/${id}/trips`, {
      params: { date_from: dateFrom, date_to: dateTo, limit: PAGE_SIZE, offset: page * PAGE_SIZE },
    })).data,
    keepPreviousData: true,
  });

  const trips = data?.trips || [];
  const totals = data?.totals || { shortage_kg: 0, excess_kg: 0, recovery_amount: 0, trip_count: 0 };
  const driver = data?.driver;
  const total = data?.total || 0;
  const ic = "border border-zinc-300 px-3 py-1.5 rounded-sm text-xs focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";

  return (
    <div className="space-y-6" data-testid="driver-trip-history-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div className="flex items-start gap-3">
          <Link to="/drivers" className="p-2 border border-zinc-200 rounded-sm mt-1"><ArrowLeft size={16} /></Link>
          <div>
            <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Driver · Trip History</div>
            <h1 className="mt-1 text-3xl font-black tracking-tighter">
              {driver?.name || "Loading…"}
              {driver?.phone && <span className="ml-3 text-sm font-mono text-zinc-500">📞 {driver.phone}</span>}
            </h1>
            <p className="text-[11px] text-zinc-500 mt-1">
              Trip is the source of truth. All driver-assigned Trips flow here automatically. Historical shortage policy is preserved per Trip.
            </p>
          </div>
        </div>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="driver-history-summary">
        <StatTile label="Total Trips" value={totals.trip_count} tone="zinc" testid="stat-trips" />
        <StatTile label="Total Shortage" value={`${totals.shortage_kg.toFixed(1)} KG`} tone="rose" testid="stat-shortage" />
        <StatTile label="Total Excess" value={`${totals.excess_kg.toFixed(1)} KG`} tone="emerald" testid="stat-excess" />
        <StatTile label="Driver Recovery" value={fmtCurrency(totals.recovery_amount)} tone="amber" testid="stat-recovery" />
      </div>

      <div className="flex flex-wrap items-end gap-3 border border-zinc-200 bg-white rounded-sm p-3">
        <div>
          <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">From</label>
          <input data-testid="history-date-from" type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(0); }} className={`${ic} block mt-1`} />
        </div>
        <div>
          <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">To</label>
          <input data-testid="history-date-to" type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(0); }} className={`${ic} block mt-1`} />
        </div>
        {(dateFrom || dateTo) && (
          <button data-testid="history-clear-dates" onClick={() => { setDateFrom(""); setDateTo(""); setPage(0); }} className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold border border-rose-300 text-rose-800 rounded-sm hover:bg-rose-50">Clear dates</button>
        )}
        <div className="flex-1" />
        <div className="text-xs text-zinc-500">{isLoading ? "Loading…" : `Showing ${trips.length} of ${total.toLocaleString()}`}</div>
      </div>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="driver-trip-history-table">
            <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-wider">
              <tr>
                <th className="text-left px-3 py-2">Date</th>
                <th className="text-left px-3 py-2">LR</th>
                <th className="text-left px-3 py-2">Vehicle</th>
                <th className="text-left px-3 py-2">Customer</th>
                <th className="text-left px-3 py-2">Loading → Unloading</th>
                <th className="text-left px-3 py-2">Product</th>
                <th className="text-right px-3 py-2">Load / Unload MT</th>
                <th className="text-right px-3 py-2">Shortage KG</th>
                <th className="text-right px-3 py-2">Excess KG</th>
                <th className="text-right px-3 py-2">Rate</th>
                <th className="text-right px-3 py-2">Freight</th>
                <th className="text-right px-3 py-2">Recovery</th>
                <th className="w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {isLoading ? (
                <tr><td colSpan={13} className="px-3 py-10 text-center text-zinc-400 italic">Loading…</td></tr>
              ) : trips.length === 0 ? (
                <tr><td colSpan={13} className="px-3 py-10 text-center text-zinc-400 italic" data-testid="driver-history-empty">No trips for this driver{dateFrom || dateTo ? " in the selected date range" : ""}.</td></tr>
              ) : trips.map((t) => {
                const dr = t.driver_recovery || {};
                const overridden = !!dr.override;
                return (
                  <tr key={t.trip_id} data-testid={`history-row-${t.trip_id}`} className="hover:bg-amber-50/40">
                    <td className="px-3 py-2 font-mono">{fmtDate(t.date)}</td>
                    <td className="px-3 py-2 font-mono">{t.lr_number || "—"}</td>
                    <td className="px-3 py-2"><span className="font-mono text-[10px] font-bold px-1.5 py-0.5 bg-zinc-950 text-white rounded-sm">{t.vehicle_number}</span></td>
                    <td className="px-3 py-2 truncate max-w-[160px]" title={t.customer_name}>{t.customer_name || "—"}</td>
                    <td className="px-3 py-2 truncate max-w-[220px]" title={`${t.loading_point} → ${t.unloading_point}`}>{t.loading_point || "—"} <span className="text-zinc-400">→</span> {t.unloading_point || "—"}</td>
                    <td className="px-3 py-2 truncate max-w-[140px]" title={t.product}>{t.product || "—"}</td>
                    <td className="px-3 py-2 text-right font-mono">{Number(t.loaded_qty_mt).toFixed(3)} / {Number(t.unloaded_qty_mt).toFixed(3)}</td>
                    <td className={`px-3 py-2 text-right font-mono ${t.shortage_qty_kg > 0 ? "text-rose-700 font-bold" : "text-zinc-300"}`} data-testid={`history-shortage-${t.trip_id}`}>{t.shortage_qty_kg > 0 ? t.shortage_qty_kg.toFixed(1) : "—"}</td>
                    <td className={`px-3 py-2 text-right font-mono ${t.excess_qty_kg > 0 ? "text-emerald-700 font-bold" : "text-zinc-300"}`} data-testid={`history-excess-${t.trip_id}`}>{t.excess_qty_kg > 0 ? t.excess_qty_kg.toFixed(1) : "—"}</td>
                    <td className="px-3 py-2 text-right font-mono">{Number(t.product_rate_per_mt || 0).toFixed(2)}</td>
                    <td className="px-3 py-2 text-right font-mono">{fmtCurrency(t.freight_amount)}</td>
                    <td className={`px-3 py-2 text-right font-mono ${dr.final_recovery_amount > 0 ? "text-amber-800 font-bold" : "text-zinc-300"}`} data-testid={`history-recovery-${t.trip_id}`}>
                      {dr.final_recovery_amount > 0 ? fmtCurrency(dr.final_recovery_amount) : "—"}
                      {overridden && <div className="text-[9px] font-normal text-amber-600 mt-0.5 inline-flex items-center gap-0.5"><AlertTriangle size={9} /> Overridden</div>}
                      {dr.policy_missing && <div className="text-[9px] font-normal text-rose-600 mt-0.5">No policy</div>}
                      {dr.policy_name && !dr.policy_missing && (
                        <div className="text-[9px] font-normal text-zinc-500 mt-0.5" title={`v${dr.policy_version || 1} · limit ${dr.allowed_limit_kg}KG`}>
                          {dr.policy_name} v{dr.policy_version}
                        </div>
                      )}
                    </td>
                    <td className="px-2 py-2 text-center">
                      <Link data-testid={`view-${t.trip_id}`} to={`/trips/${t.trip_id}/view`} className="p-1 border border-zinc-200 rounded-sm text-zinc-600 hover:bg-zinc-950 hover:text-white"><Eye size={12} /></Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {total > PAGE_SIZE && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-zinc-200 bg-zinc-50 text-xs" data-testid="history-pagination">
            <span>Page {page + 1} of {Math.ceil(total / PAGE_SIZE)}</span>
            <div className="flex gap-2">
              <button data-testid="history-prev" disabled={page === 0} onClick={() => setPage(p => Math.max(0, p - 1))} className="px-3 py-1 text-[11px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm disabled:opacity-40 hover:bg-white">Prev</button>
              <button data-testid="history-next" disabled={(page + 1) * PAGE_SIZE >= total} onClick={() => setPage(p => p + 1)} className="px-3 py-1 text-[11px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm disabled:opacity-40 hover:bg-white">Next</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


function StatTile({ label, value, tone, testid }) {
  const toneMap = {
    zinc: "border-zinc-200 bg-white",
    rose: "border-rose-200 bg-rose-50",
    emerald: "border-emerald-200 bg-emerald-50",
    amber: "border-amber-200 bg-amber-50",
  };
  return (
    <div className={`border ${toneMap[tone] || toneMap.zinc} p-3 rounded-sm`} data-testid={testid}>
      <div className="text-[10px] uppercase font-bold tracking-wider text-zinc-500">{label}</div>
      <div className="text-lg font-black font-mono mt-1">{value}</div>
    </div>
  );
}
