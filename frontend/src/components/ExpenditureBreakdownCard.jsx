import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency } from "@/api";
import { Link } from "react-router-dom";
import { PieChart } from "lucide-react";

/**
 * ExpenditureBreakdownCard — visualises per-type Other-Expenditure spend
 * for the current month across every trip in the active company.
 * Zero-state hidden; renders a stacked bar-chart with % + amount + count.
 */
export default function ExpenditureBreakdownCard() {
  // Current month by default
  const today = new Date();
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1).toISOString().slice(0, 10);
  const monthEnd = today.toISOString().slice(0, 10);

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

      {/* Horizontal stacked bar */}
      <div
        data-testid="expenditure-bar"
        className="w-full h-4 flex overflow-hidden rounded-sm border border-zinc-200"
        title={`Total ${fmtCurrency(total)}`}
      >
        {rows.map((r, i) => (
          <div
            key={r.type}
            style={{ width: `${r.pct}%`, backgroundColor: palette[i % palette.length] }}
            title={`${r.type}: ${fmtCurrency(r.amount)} (${r.pct}%)`}
          />
        ))}
      </div>

      {/* Legend */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {rows.map((r, i) => (
          <div
            key={r.type}
            data-testid={`expenditure-row-${r.type.toLowerCase().replace(/\s+/g, "-")}`}
            className="flex items-center gap-2 text-sm"
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
          </div>
        ))}
      </div>
    </div>
  );
}
