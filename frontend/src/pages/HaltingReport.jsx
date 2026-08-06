import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency } from "@/api";
import { Clock } from "lucide-react";

export default function HaltingReport() {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const { data } = useQuery({
    queryKey: ["report-halting", start, end],
    queryFn: async () => (await api.get("/reports/halting", { params: { start: start || undefined, end: end || undefined } })).data,
  });

  return (
    <div className="space-y-6" data-testid="halting-report-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Report</div>
          <h1 className="text-3xl font-black tracking-tighter">
            <span className="telugu">హాల్టింగ్ నివేదిక</span>
            <span className="text-zinc-400"> · Halting Charges Report</span>
          </h1>
        </div>
        <div className="flex items-end gap-2">
          <div>
            <label className="text-[10px] uppercase tracking-wider font-bold text-zinc-500">Start</label>
            <input data-testid="halting-start-date" type="date" value={start} onChange={(e) => setStart(e.target.value)} className="mt-1 border border-zinc-300 px-3 py-1.5 rounded-sm text-sm" />
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider font-bold text-zinc-500">End</label>
            <input data-testid="halting-end-date" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="mt-1 border border-zinc-300 px-3 py-1.5 rounded-sm text-sm" />
          </div>
        </div>
      </header>

      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="Trips with Halting" value={data.totals.trips_with_halting} />
            <Stat label="Total Days" value={data.totals.total_days} />
            <Stat label="Chargeable Days" value={data.totals.chargeable_days} accent="amber" />
            <Stat label="Halting Revenue" value={fmtCurrency(data.totals.halting_revenue)} accent="emerald" />
          </div>

          <div className="border border-zinc-200 bg-white rounded-sm overflow-x-auto">
            <table className="w-full text-sm" data-testid="halting-report-table">
              <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
                <tr>
                  <th className="text-left px-4 py-2">Customer</th>
                  <th className="text-right px-4 py-2">Trips</th>
                  <th className="text-right px-4 py-2">Total Days</th>
                  <th className="text-right px-4 py-2">Chargeable Days</th>
                  <th className="text-right px-4 py-2">Avg Rate / Day</th>
                  <th className="text-right px-4 py-2">Halting Revenue</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {(data.customers || []).map((c) => (
                  <tr key={c.customer_id} className="border-t border-zinc-100">
                    <td className="px-4 py-2 font-semibold">{c.customer_name}</td>
                    <td className="px-4 py-2 text-right">{c.trips_with_halting}</td>
                    <td className="px-4 py-2 text-right">{c.total_days}</td>
                    <td className="px-4 py-2 text-right text-amber-700 font-bold">{c.chargeable_days}</td>
                    <td className="px-4 py-2 text-right">{fmtCurrency(c.avg_rate)}</td>
                    <td className="px-4 py-2 text-right font-bold text-emerald-800">{fmtCurrency(c.halting_revenue)}</td>
                  </tr>
                ))}
                {(data.customers || []).length === 0 && (
                  <tr><td colSpan={6} className="px-4 py-14 text-center text-zinc-400 text-sm"><Clock size={22} className="inline mb-2" /><br/>No halting charges in this period.</td></tr>
                )}
              </tbody>
              {data.customers.length > 0 && (
                <tfoot>
                  <tr className="bg-amber-50 border-t-2 border-zinc-950">
                    <td className="px-4 py-2 font-bold">TOTAL</td>
                    <td className="px-4 py-2 text-right font-bold">{data.totals.trips_with_halting}</td>
                    <td className="px-4 py-2 text-right font-bold">{data.totals.total_days}</td>
                    <td className="px-4 py-2 text-right font-bold">{data.totals.chargeable_days}</td>
                    <td></td>
                    <td className="px-4 py-2 text-right font-bold text-emerald-800">{fmtCurrency(data.totals.halting_revenue)}</td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, accent }) {
  const cls = accent === "emerald" ? "border-emerald-300 bg-emerald-50"
    : accent === "amber" ? "border-amber-300 bg-amber-50"
    : "border-zinc-200 bg-white";
  return (
    <div className={`border p-3 rounded-sm ${cls}`}>
      <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">{label}</div>
      <div className="font-mono text-xl font-black mt-1">{value}</div>
    </div>
  );
}
