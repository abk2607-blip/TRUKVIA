import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency } from "@/api";
import { Link, useNavigate } from "react-router-dom";
import { PieChart, X, ExternalLink } from "lucide-react";

/**
 * ExpenditureBreakdownCard — visualises per-type Other-Expenditure spend
 * for the current month across every trip in the active company.
 * Zero-state hidden; renders a stacked bar-chart with % + amount + count.
 * Clicking a legend row opens a drill-down modal listing trips for that type.
 */
export default function ExpenditureBreakdownCard() {
  const today = new Date();
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1).toISOString().slice(0, 10);
  const monthEnd = today.toISOString().slice(0, 10);
  const [drillType, setDrillType] = useState(null);

  const { data, isLoading } = useQuery({
    queryKey: ["expenditure-breakdown", monthStart, monthEnd],
    queryFn: async () =>
      (await api.get(`/dashboard/expenditure-breakdown?start=${monthStart}&end=${monthEnd}`)).data,
    staleTime: 60_000,
  });

  if (isLoading || !data || !data.by_type || data.by_type.length === 0) return null;

  const rows = data.by_type;
  const total = data.total;
  const palette = [
    "#f59e0b", "#0ea5e9", "#8b5cf6", "#10b981", "#ef4444",
    "#f97316", "#14b8a6", "#6366f1", "#ec4899", "#84cc16",
  ];

  return (
    <>
      <div
        data-testid="expenditure-breakdown-card"
        className="border border-zinc-200 bg-white rounded-sm p-5 space-y-4"
      >
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[10px] uppercase tracking-[0.15em] font-bold text-zinc-500 flex items-center gap-2">
              <PieChart size={12} className="text-amber-600" />
              Other Expenditure — Where the Cash Leaks
            </div>
            <h2 className="text-lg font-black mt-1 tracking-tight">
              <span className="telugu">ఇతర ఖర్చులు</span>
              <span className="text-zinc-400"> · Cost Breakdown</span>
            </h2>
            <div className="text-[11px] text-zinc-500">
              This month · {data.trip_count} trip(s) · total {fmtCurrency(total)}
            </div>
          </div>
          <Link to="/trips" className="text-[11px] uppercase tracking-wider font-bold text-zinc-500 hover:text-zinc-950">
            View Trips →
          </Link>
        </div>

        <div
          data-testid="expenditure-bar"
          className="w-full h-4 flex overflow-hidden rounded-sm border border-zinc-200"
          title={`Total ${fmtCurrency(total)}`}
        >
          {rows.map((r, i) => (
            <button
              key={r.type}
              onClick={() => setDrillType(r.type)}
              style={{ width: `${r.pct}%`, backgroundColor: palette[i % palette.length] }}
              title={`${r.type}: ${fmtCurrency(r.amount)} (${r.pct}%) — click for details`}
              className="cursor-pointer hover:opacity-70 transition-opacity"
            />
          ))}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {rows.map((r, i) => (
            <button
              key={r.type}
              type="button"
              data-testid={`expenditure-row-${r.type.toLowerCase().replace(/\s+/g, "-")}`}
              onClick={() => setDrillType(r.type)}
              className="flex items-center gap-2 text-sm text-left px-2 py-1 rounded-sm hover:bg-zinc-50 cursor-pointer"
              title="Click to see every trip that spent under this type"
            >
              <span
                className="w-2.5 h-2.5 rounded-sm shrink-0"
                style={{ backgroundColor: palette[i % palette.length] }}
              />
              <span className="flex-1 truncate">{r.type}</span>
              <span className="font-mono text-xs text-zinc-500">×{r.count}</span>
              <span className="font-mono font-bold text-zinc-900 text-right w-20">
                {fmtCurrency(r.amount)}
              </span>
              <span className="text-[10px] font-bold text-zinc-500 w-12 text-right">{r.pct}%</span>
            </button>
          ))}
        </div>
      </div>

      {drillType && (
        <ExpenditureDrillModal
          type={drillType}
          start={monthStart}
          end={monthEnd}
          onClose={() => setDrillType(null)}
        />
      )}
    </>
  );
}

function ExpenditureDrillModal({ type, start, end, onClose }) {
  const nav = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ["expenditure-detail", type, start, end],
    queryFn: async () =>
      (await api.get(`/dashboard/expenditure-detail`, { params: { type, start, end } })).data,
  });
  return (
    <div
      data-testid="expenditure-drill-modal"
      className="fixed inset-0 z-50 bg-zinc-950/50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-sm border border-zinc-200 w-full max-w-3xl max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b border-zinc-200 flex items-center justify-between">
          <div>
            <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500">Expenditure Drill-Down</div>
            <div className="text-lg font-bold">{type}</div>
            {data && (
              <div className="text-[11px] text-zinc-500">
                {data.count} entry(ies) · total <span className="font-mono font-bold">{fmtCurrency(data.total)}</span>
              </div>
            )}
          </div>
          <button data-testid="drill-close" onClick={onClose} className="p-2 hover:bg-zinc-100 rounded-sm">
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="p-8 text-center text-sm text-zinc-500">Loading…</div>
          ) : !data || data.trips.length === 0 ? (
            <div className="p-8 text-center text-sm text-zinc-500">No trips found.</div>
          ) : (
            <table className="w-full text-xs">
              <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-wider sticky top-0">
                <tr>
                  <th className="text-left px-3 py-2">Date</th>
                  <th className="text-left px-3 py-2">LR No.</th>
                  <th className="text-left px-3 py-2">Vehicle</th>
                  <th className="text-left px-3 py-2">Route</th>
                  <th className="text-right px-3 py-2">Amount</th>
                  <th className="text-left px-3 py-2">Remarks</th>
                  <th className="w-8"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {data.trips.map((r) => (
                  <tr
                    key={r.trip_id + r.date + r.amount}
                    data-testid={`drill-row-${r.trip_id}`}
                    className="hover:bg-amber-50 cursor-pointer"
                    onClick={() => {
                      nav(`/trips/${r.trip_id}/view`);
                      onClose();
                    }}
                  >
                    <td className="px-3 py-2 font-mono">{r.date}</td>
                    <td className="px-3 py-2 font-mono">{r.lr_number || "—"}</td>
                    <td className="px-3 py-2 font-mono font-bold">{r.vehicle_number}</td>
                    <td className="px-3 py-2 text-zinc-600">
                      {r.from_location || "?"} → {r.to_location || "?"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono font-bold">
                      {fmtCurrency(r.amount)}
                    </td>
                    <td className="px-3 py-2 text-zinc-500 italic">{r.remarks || "—"}</td>
                    <td className="px-2 py-2 text-zinc-400">
                      <ExternalLink size={12} />
                    </td>
                  </tr>
                ))}
              </tbody>
              {data.trips.length > 0 && (
                <tfoot>
                  <tr className="bg-amber-50 font-bold">
                    <td colSpan={4} className="px-3 py-2 text-right uppercase tracking-wider text-[10px]">
                      Total
                    </td>
                    <td className="px-3 py-2 text-right font-mono" data-testid="drill-total">
                      {fmtCurrency(data.total)}
                    </td>
                    <td colSpan={2}></td>
                  </tr>
                </tfoot>
              )}
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
