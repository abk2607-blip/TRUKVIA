import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, API, fmtCurrency, fmtDate } from "@/api";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Plus, CheckCircle2, Clock, Download, FileText, Trash2, Eye, Pencil, Copy, Share2 } from "lucide-react";

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
  const qc = useQueryClient();
  const { data: trips = [] } = useQuery({ queryKey: ["trips"], queryFn: async () => (await api.get("/trips")).data });
  const { data: customers = [] } = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get("/customers")).data });
  const custMap = Object.fromEntries(customers.map((c) => [c.id, c.name]));

  // Iter51 — Halting filter + halting-column sort
  const [showHaltingOnly, setShowHaltingOnly] = React.useState(false);
  const [sortHalting, setSortHalting] = React.useState(null); // null | "desc" | "asc"

  const displayedTrips = React.useMemo(() => {
    let list = trips;
    if (showHaltingOnly) list = list.filter((t) => (t.halting_amount || 0) > 0);
    if (sortHalting) {
      const dir = sortHalting === "desc" ? -1 : 1;
      // Iter52 — When sorting halting, consider age as a tiebreaker so older
      // pending charges bubble up when amounts are equal.
      const _age = (t) => {
        const anchor = t.unloading_date || t.date;
        if (!anchor) return 0;
        const then = new Date(anchor).getTime();
        return isNaN(then) ? 0 : (Date.now() - then) / 86400000;
      };
      list = [...list].sort((a, b) => {
        const primary = ((a.halting_amount || 0) - (b.halting_amount || 0)) * dir;
        if (primary !== 0) return primary;
        return (_age(b) - _age(a));   // older first for both directions
      });
    }
    return list;
  }, [trips, showHaltingOnly, sortHalting]);

  const cycleHaltingSort = () => {
    setSortHalting((s) => (s === null ? "desc" : s === "desc" ? "asc" : null));
  };

  const totalHalting = React.useMemo(
    () => trips.reduce((s, t) => s + (Number(t.halting_amount) || 0), 0),
    [trips]
  );
  const haltingTripCount = React.useMemo(
    () => trips.filter((t) => (t.halting_amount || 0) > 0).length,
    [trips]
  );

  const del = useMutation({
    mutationFn: async ({ id, reason }) => (await api.delete(`/trips/${id}`, { params: { reason } })).data,
    onSuccess: () => { toast.success("Trip deleted"); qc.invalidateQueries(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const askDelete = (t) => {
    const linked = t.invoice_id ? "\n⚠ This trip is linked to an invoice. The invoice totals will be recomputed." : "";
    const reason = window.prompt(`Delete trip on ${t.date} (${t.vehicle_number})?${linked}\n\nReason for deletion (mandatory):`);
    if (!reason || !reason.trim()) { toast.error("Reason required"); return; }
    del.mutate({ id: t.id, reason });
  };

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
          <button
            data-testid="halting-only-toggle"
            onClick={() => setShowHaltingOnly((v) => !v)}
            className={`px-3 py-2 text-xs uppercase tracking-wider font-semibold rounded-sm inline-flex items-center gap-2 border transition-colors
              ${showHaltingOnly
                ? "bg-amber-500 text-white border-amber-600 hover:bg-amber-600"
                : "bg-white text-amber-800 border-amber-400 hover:bg-amber-50"}`}
            title={showHaltingOnly ? "Show all trips" : "Show only trips with halting charges"}
          >
            <Clock size={14} /> {showHaltingOnly ? "Halting Only ·" : "Halting Only ·"}
            <span className="font-mono font-bold">{haltingTripCount}</span>
          </button>
          <Link to="/trips/import" data-testid="import-trips-btn" className="px-3 py-2 text-xs uppercase tracking-wider font-semibold border border-zinc-950 text-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white inline-flex items-center gap-2">
            <Plus size={14} /> Import Excel
          </Link>
          <Link to="/trips/new" data-testid="new-trip-btn" className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2">
            <Plus size={14} /> New Trip
          </Link>
        </div>
      </header>

      {/* Iter51 — Halting summary strip: total across all trips + filtered count */}
      {trips.length > 0 && (
        <div className="flex flex-wrap items-center gap-4 -mt-2 text-xs" data-testid="halting-summary">
          <span className="text-zinc-500">
            Showing <span className="font-bold text-zinc-900" data-testid="trip-count-shown">{displayedTrips.length}</span> of {trips.length} trips
            {showHaltingOnly && <span className="ml-2 text-amber-700 font-bold">· Halting only</span>}
            {sortHalting && <span className="ml-2 text-zinc-700 font-bold">· Sorted by Halting ({sortHalting === "desc" ? "high→low" : "low→high"})</span>}
          </span>
          <span className="text-zinc-500">
            Total halting across all trips:
            <span className="ml-1 font-mono font-bold text-amber-700" data-testid="total-halting-sum">{fmtCurrency(totalHalting)}</span>
          </span>
        </div>
      )}

      <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="trips-table">
            <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-[0.12em] sticky top-0 z-10">
              <tr>
                <th className="text-left px-4 py-3 font-bold">Date · Time</th>
                <th className="text-left px-4 py-3 font-bold">LR Number</th>
                <th className="text-left px-4 py-3 font-bold">Customer</th>
                <th className="text-left px-4 py-3 font-bold">Vehicle</th>
                <th className="text-left px-4 py-3 font-bold">Route · Load</th>
                <th className="text-right px-4 py-3 font-bold">Tons</th>
                <th className="text-right px-4 py-3 font-bold">Freight</th>
                <th
                  data-testid="halting-column-header"
                  onClick={cycleHaltingSort}
                  role="button"
                  className="text-right px-4 py-3 font-bold cursor-pointer select-none hover:bg-white/10"
                  title="Click to sort by Halting Amount (desc → asc → off)"
                >
                  Halting {sortHalting === "desc" ? "▼" : sortHalting === "asc" ? "▲" : "⇅"}
                </th>
                <th className="text-right px-4 py-3 font-bold">Expense</th>
                <th className="text-right px-4 py-3 font-bold">Profit</th>
                <th className="text-center px-4 py-3 font-bold">Status</th>
                <th className="px-4 py-3 font-bold text-center">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {displayedTrips.map((t, idx) => {
                const created = t.created_at ? new Date(t.created_at) : null;
                const timeStr = created ? created.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false }) : "";
                return (
                <tr
                  key={t.id}
                  data-testid={`trip-row-${t.id}`}
                  onClick={() => window.location.href = `/trips/${t.id}/view`}
                  className={`${idx % 2 === 0 ? "bg-white" : "bg-zinc-50/60"} hover:bg-amber-50/40 transition-colors cursor-pointer`}
                >
                  {/* Date · Time */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="text-sm font-semibold text-zinc-900 font-mono">{fmtDate(t.date)}</div>
                    {timeStr && <div className="text-[10px] text-zinc-400 font-mono mt-0.5">🕒 {timeStr}</div>}
                  </td>
                  {/* LR Number — highlighted badge */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    {t.lr_number ? (
                      <span className="inline-block font-mono text-[11px] font-bold px-2 py-1 bg-indigo-50 text-indigo-800 border border-indigo-200 rounded-sm">
                        {t.lr_number}
                      </span>
                    ) : (
                      <span className="text-zinc-300 text-xs">—</span>
                    )}
                  </td>
                  {/* Customer — highlighted */}
                  <td className="px-4 py-3 max-w-[220px]">
                    <div className="font-bold text-zinc-900 truncate leading-tight" title={custMap[t.customer_id] || ""}>
                      {custMap[t.customer_id] || "—"}
                    </div>
                  </td>
                  {/* Vehicle — chip */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span className="inline-block font-mono text-[11px] font-bold px-2 py-1 bg-zinc-950 text-white rounded-sm tracking-wider">
                      {t.vehicle_number}
                    </span>
                    {t.vehicle_type === "supplier" && (
                      <div className="text-[9px] uppercase tracking-wider text-orange-600 font-bold mt-1">Supplier</div>
                    )}
                  </td>
                  {/* Route + Load */}
                  <td className="px-4 py-3 max-w-[220px]">
                    <div className="text-xs text-zinc-800 font-medium truncate leading-tight" title={`${t.from_location || "?"} → ${t.to_location || "?"}`}>
                      {t.from_location || "—"} <span className="text-zinc-400">→</span> {t.to_location || "—"}
                    </div>
                    {t.load_details && (
                      <div className="text-[10px] text-zinc-500 truncate mt-0.5" title={t.load_details}>📦 {t.load_details}</div>
                    )}
                  </td>
                  {/* Tons */}
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <div className="font-mono font-semibold text-sm">{Number(t.tons).toFixed(2)}</div>
                    <div className="text-[9px] uppercase text-zinc-400 tracking-wider">
                      {t.freight_mode === "per_ton" ? `₹${Number(t.rate_per_ton).toFixed(0)}/T` : "Fixed"}
                    </div>
                  </td>
                  {/* Freight */}
                  <td className="px-4 py-3 text-right whitespace-nowrap font-mono text-sm font-semibold text-zinc-900">
                    {fmtCurrency(t.freight_amount)}
                  </td>
                  {/* Halting — dedicated column so drivers see waiting charges at-a-glance */}
                  <td
                    className={`px-4 py-3 text-right whitespace-nowrap font-mono text-sm ${t.halting_amount > 0 ? "text-amber-700 font-bold" : "text-zinc-300"}`}
                    title={t.halting_amount > 0 ? `${t.chargeable_halting_days || 0} chargeable day(s) × ₹${t.halting_rate_per_day || 0}/day` : "No halting charges"}
                    data-testid={`trip-halting-${t.id}`}
                  >
                    {t.halting_amount > 0 ? (
                      <div className="flex flex-col items-end gap-0.5">
                        <span>{fmtCurrency(t.halting_amount)}</span>
                        <HaltingAgeChip trip={t} />
                      </div>
                    ) : (
                      "—"
                    )}
                  </td>
                  {/* Expense */}
                  <td className="px-4 py-3 text-right whitespace-nowrap font-mono text-sm text-rose-700">
                    {fmtCurrency(t.total_expense)}
                  </td>
                  {/* Profit — emphasized */}
                  <td className={`px-4 py-3 text-right whitespace-nowrap font-mono text-sm font-bold ${t.profit >= 0 ? "text-emerald-700" : "text-rose-700"}`}>
                    {fmtCurrency(t.profit)}
                  </td>
                  {/* Status — pill */}
                  <td className="px-4 py-3 text-center whitespace-nowrap">
                    {t.status === "invoiced" ? (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider bg-emerald-100 text-emerald-800 px-2.5 py-1 rounded-full border border-emerald-300 font-bold">
                        <CheckCircle2 size={10} /> Invoiced
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider bg-amber-100 text-amber-800 px-2.5 py-1 rounded-full border border-amber-300 font-bold">
                        <Clock size={10} /> Pending
                      </span>
                    )}
                  </td>
                  {/* Actions — icon-only compact cluster */}
                  <td className="px-2 py-3 whitespace-nowrap w-[220px]" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-0.5">
                      <Link
                        data-testid={`view-trip-${t.id}`}
                        to={`/trips/${t.id}/view`}
                        className="p-1.5 border border-zinc-200 rounded-sm text-zinc-600 hover:bg-zinc-950 hover:text-white transition"
                        title="View details"
                      ><Eye size={12} /></Link>
                      <Link
                        data-testid={`edit-trip-${t.id}`}
                        to={`/trips/${t.id}/edit`}
                        className={`p-1.5 border rounded-sm hover:bg-zinc-950 hover:text-white transition ${t.status === "invoiced" ? "border-amber-300 text-amber-700" : "border-zinc-200 text-zinc-600"}`}
                        title={t.status === "invoiced" ? "Edit (invoice will recalc)" : "Edit"}
                      ><Pencil size={12} /></Link>
                      <a
                        data-testid={`lr-${t.id}`}
                        href={`${API}/trips/${t.id}/lr`}
                        target="_blank"
                        rel="noreferrer"
                        className="p-1.5 border border-indigo-200 rounded-sm text-indigo-700 hover:bg-indigo-600 hover:text-white transition"
                        title="LR PDF"
                      ><FileText size={12} /></a>
                      <button
                        data-testid={`share-lr-${t.id}`}
                        onClick={async () => {
                          try {
                            const { data } = await api.post(`/trips/${t.id}/share-lr`);
                            window.open(data.whatsapp_url, "_blank");
                            toast.success(`LR ${data.lr_number} ready to share`);
                          } catch (e) { toast.error(e.response?.data?.detail || "Share failed"); }
                        }}
                        className="p-1.5 border border-emerald-300 rounded-sm text-emerald-700 hover:bg-emerald-600 hover:text-white transition"
                        title="Share LR via WhatsApp"
                      ><Share2 size={12} /></button>
                      <button
                        data-testid={`ewaybill-${t.id}`}
                        onClick={() => downloadEwayBill(t.id)}
                        className="p-1.5 border border-zinc-200 rounded-sm text-zinc-600 hover:bg-zinc-950 hover:text-white transition"
                        title="E-Way Bill JSON"
                      ><Download size={12} /></button>
                      <button
                        data-testid={`duplicate-trip-${t.id}`}
                        onClick={async () => {
                          try {
                            const { data } = await api.post(`/trips/${t.id}/duplicate`);
                            toast.success("Trip duplicated");
                            qc.invalidateQueries({ queryKey: ["trips"] });
                            window.location.href = `/trips/${data.id}/edit`;
                          } catch (e) { toast.error(e.response?.data?.detail || "Duplicate failed"); }
                        }}
                        className="p-1.5 border border-emerald-200 rounded-sm text-emerald-700 hover:bg-emerald-50 transition"
                        title="Duplicate"
                      ><Copy size={12} /></button>
                      <button
                        data-testid={`delete-trip-${t.id}`}
                        onClick={() => askDelete(t)}
                        className="p-1.5 border border-rose-200 rounded-sm text-rose-700 hover:bg-rose-600 hover:text-white transition"
                        title="Delete"
                      ><Trash2 size={12} /></button>
                    </div>
                  </td>
                </tr>
                );
              })}
              {trips.length === 0 && (
                <tr><td colSpan={12} className="px-4 py-16 text-center text-zinc-400">No trips logged. Click "New Trip" to start.</td></tr>
              )}
              {trips.length > 0 && displayedTrips.length === 0 && (
                <tr><td colSpan={12} className="px-4 py-16 text-center text-zinc-400" data-testid="halting-empty-state">
                  No trips match the current filter. Turn off "Halting Only" to see all trips.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}


// Iter52 — Halting Aging chip. Shows how many days a halting charge has been
// pending so ops teams can chase the oldest ones first.
// Age is calculated from `unloading_date` (or `date` as fallback) — that's
// when the vehicle stopped waiting and the halting became "owed".
// Tone:
//   grey  (< 7 days)  — fresh
//   amber (7-30 days) — chase soon
//   rose  (> 30 days) — overdue, chase now
function HaltingAgeChip({ trip }) {
  const ageDays = React.useMemo(() => {
    const anchor = trip.unloading_date || trip.date;
    if (!anchor) return null;
    const then = new Date(anchor);
    if (isNaN(then.getTime())) return null;
    const now = new Date();
    return Math.floor((now - then) / (1000 * 60 * 60 * 24));
  }, [trip.unloading_date, trip.date]);
  if (ageDays == null || ageDays < 0) return null;
  const tone = ageDays >= 30 ? "bg-rose-100 text-rose-700 border-rose-300"
    : ageDays >= 7 ? "bg-amber-100 text-amber-700 border-amber-300"
    : "bg-zinc-100 text-zinc-600 border-zinc-300";
  return (
    <span
      data-testid={`trip-halting-age-${trip.id}`}
      title={`Halting pending for ${ageDays} day(s) since ${trip.unloading_date || trip.date}`}
      className={`inline-block text-[9px] font-mono font-bold px-1.5 py-0.5 rounded border ${tone}`}
    >
      {ageDays}d
    </span>
  );
}

