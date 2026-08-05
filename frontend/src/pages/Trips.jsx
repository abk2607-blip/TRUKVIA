import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate } from "@/api";
import { Link } from "react-router-dom";
import { Plus, CheckCircle2, Clock, Download } from "lucide-react";

const downloadEwayBill = async (tripId) => {
  const { api: ax } = await import("@/api");
  try {
    const { data } = await ax.get(`/trips/${tripId}/ewaybill`);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `ewaybill_${tripId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    console.error(e);
  }
};

export default function Trips() {
  const { data: trips = [] } = useQuery({ queryKey: ["trips"], queryFn: async () => (await api.get("/trips")).data });
  const { data: customers = [] } = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get("/customers")).data });
  const custMap = Object.fromEntries(customers.map((c) => [c.id, c.name]));

  return (
    <div className="space-y-6" data-testid="trips-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Log</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">ట్రిప్స్</span>
            <span className="text-zinc-400"> · Trips</span>
          </h1>
        </div>
        <div className="flex gap-2">
          <Link to="/trips/import" data-testid="import-trips-btn" className="px-3 py-2 text-xs uppercase tracking-wider font-semibold border border-zinc-950 text-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white inline-flex items-center gap-2">
            <Plus size={14} /> Import Excel
          </Link>
          <Link to="/trips/new" data-testid="new-trip-btn" className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2">
            <Plus size={14} /> New Trip
          </Link>
        </div>
      </header>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="trips-table">
            <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="text-left px-3 py-2 font-semibold">Date</th>
                <th className="text-left px-3 py-2 font-semibold">Customer</th>
                <th className="text-left px-3 py-2 font-semibold">Vehicle</th>
                <th className="text-left px-3 py-2 font-semibold">Route</th>
                <th className="text-right px-3 py-2 font-semibold">Tons</th>
                <th className="text-left px-3 py-2 font-semibold">Mode</th>
                <th className="text-right px-3 py-2 font-semibold">Freight</th>
                <th className="text-right px-3 py-2 font-semibold">Expense</th>
                <th className="text-right px-3 py-2 font-semibold">Profit</th>
                <th className="text-left px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {trips.map((t) => (
                <tr key={t.id} data-testid={`trip-row-${t.id}`} className="border-t border-zinc-100">
                  <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">{fmtDate(t.date)}</td>
                  <td className="px-3 py-2">{custMap[t.customer_id] || "—"}</td>
                  <td className="px-3 py-2 font-mono text-xs">{t.vehicle_number}</td>
                  <td className="px-3 py-2 text-xs">{t.from_location} → {t.to_location}</td>
                  <td className="px-3 py-2 text-right font-mono">{Number(t.tons).toFixed(2)}</td>
                  <td className="px-3 py-2 text-xs">
                    {t.freight_mode === "per_ton" ? (
                      <span className="telugu">టన్ను ({Number(t.rate_per_ton).toFixed(0)})</span>
                    ) : (t.round_trip_kms > 0 && t.rate_per_km_per_ton > 0) ? (
                      <span className="telugu">RT {Number(t.round_trip_kms).toFixed(0)}km × ₹{Number(t.rate_per_km_per_ton).toFixed(2)}</span>
                    ) : (
                      <span className="telugu">Lump</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right font-mono">{fmtCurrency(t.freight_amount)}</td>
                  <td className="px-3 py-2 text-right font-mono text-rose-700">{fmtCurrency(t.total_expense)}</td>
                  <td className={`px-3 py-2 text-right font-mono font-semibold ${t.profit >= 0 ? "text-emerald-700" : "text-rose-700"}`}>{fmtCurrency(t.profit)}</td>
                  <td className="px-3 py-2">
                    {t.status === "invoiced" ? (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded-sm border border-emerald-200"><CheckCircle2 size={10} /> Invoiced</span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider bg-amber-50 text-amber-700 px-2 py-0.5 rounded-sm border border-amber-200"><Clock size={10} /> Pending</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <button
                      data-testid={`ewaybill-${t.id}`}
                      onClick={() => downloadEwayBill(t.id)}
                      className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-zinc-200 rounded-sm hover:bg-zinc-950 hover:text-white mr-1"
                      title="Download E-Way Bill JSON"
                    >
                      <Download size={11} /> E-Way
                    </button>
                    {t.status === "pending" && (
                      <Link data-testid={`edit-trip-${t.id}`} to={`/trips/${t.id}/edit`} className="text-xs px-2 py-1 border border-zinc-200 rounded-sm hover:bg-zinc-950 hover:text-white">Edit</Link>
                    )}
                  </td>
                </tr>
              ))}
              {trips.length === 0 && (
                <tr><td colSpan={11} className="px-4 py-12 text-center text-zinc-400">No trips logged. Click "New Trip" to start.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
