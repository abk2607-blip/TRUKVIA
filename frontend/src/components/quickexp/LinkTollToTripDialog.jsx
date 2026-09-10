import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency } from "@/api";
import { toast } from "sonner";
import { X, Link2, AlertTriangle, Truck, CheckCircle2 } from "lucide-react";

/* Iter149 P0 · Link FASTag Toll → Trip.
 * ------------------------------------------------------------------
 * Narrow modal. Fetches candidate Trips for the Expense's vehicle
 * within ±2 days, sorted by date-proximity. NEVER auto-picks — the
 * operator must click one and confirm. Also supports Unlink (clear
 * trip_id) when the row is already linked.
 *
 * Contract: writes ONLY via `PATCH /api/expenses/{eid}/toll-trip`.
 * Success invalidates every canonical projection queryKey so Trip Cost
 * / Trip View / Vehicle Cost / Today's Expenses update instantly.
 *
 * L.1 REVISED (2026-09-10) · A trip is considered legacy-conflicting
 * (i.e. blocked in the picker) ONLY when it carries a real legacy
 * Toll amount that vehicle-cost XOR fallback would still count:
 *   • Trip.expenses.toll > 0, OR
 *   • any Trip.other_expenditures[] row of type "Toll" with amount>0
 * Modern/fresh trips with zero legacy Toll surface are eligible even
 * when has_canonical_expenses=false. This exactly mirrors the backend
 * `is_legacy_conflicting_toll_trip` predicate.
 */
function isLegacyConflictingTollTrip(trip) {
  if (trip?.has_canonical_expenses === true) return false;
  const exp = trip?.expenses || {};
  if (Number(exp.toll || 0) > 0) return true;
  for (const oe of trip?.other_expenditures || []) {
    const amt = Number(oe?.amount || 0);
    if (amt <= 0) continue;
    if (String(oe?.type || "").trim().toLowerCase() === "toll") return true;
  }
  return false;
}
export default function LinkTollToTripDialog({ expense, onClose, onSuccess }) {
  const [selectedTripId, setSelectedTripId] = useState(expense?.trip_id || "");
  const [force, setForce] = useState(false);
  const [saving, setSaving] = useState(false);

  const eid = expense?.id || "";
  const vehId = expense?.vehicle_id || "";
  const eDate = expense?.date || "";
  const currentTripId = expense?.trip_id || "";

  const { dateFrom, dateTo } = useMemo(() => {
    if (!eDate) return { dateFrom: "", dateTo: "" };
    try {
      const d = new Date(eDate + "T00:00:00Z");
      const from = new Date(d); from.setUTCDate(from.getUTCDate() - 2);
      const to = new Date(d); to.setUTCDate(to.getUTCDate() + 2);
      const iso = (dt) => dt.toISOString().slice(0, 10);
      return { dateFrom: iso(from), dateTo: iso(to) };
    } catch { return { dateFrom: "", dateTo: "" }; }
  }, [eDate]);

  const tripsQ = useQuery({
    queryKey: ["toll-trip-candidates", vehId, dateFrom, dateTo],
    enabled: !!vehId && !!dateFrom && !!dateTo,
    queryFn: async () => (await api.get("/trips", {
      params: { vehicle_id: vehId, date_from: dateFrom, date_to: dateTo, limit: 50 },
    })).data,
    staleTime: 30_000,
  });
  const candidates = useMemo(() => {
    const rows = Array.isArray(tripsQ.data) ? tripsQ.data : [];
    return [...rows].sort((a, b) => {
      const da = Math.abs(new Date((a.date || eDate) + "T00:00:00Z") - new Date(eDate + "T00:00:00Z"));
      const dbb = Math.abs(new Date((b.date || eDate) + "T00:00:00Z") - new Date(eDate + "T00:00:00Z"));
      return da - dbb;
    });
  }, [tripsQ.data, eDate]);

  const outsideWindow = useMemo(() => {
    const t = candidates.find((c) => c.id === selectedTripId);
    if (!t || !t.date || !eDate) return false;
    try {
      const diff = Math.abs(
        new Date(t.date + "T00:00:00Z") - new Date(eDate + "T00:00:00Z"),
      ) / (1000 * 60 * 60 * 24);
      return diff > 2;
    } catch { return false; }
  }, [candidates, selectedTripId, eDate]);

  const canLink = !!selectedTripId && (!outsideWindow || force);
  const isSameAsCurrent = selectedTripId === currentTripId;

  const doLink = async () => {
    if (!eid || !canLink) return;
    setSaving(true);
    try {
      const { data } = await api.patch(`/expenses/${eid}/toll-trip`, {
        trip_id: selectedTripId,
        ...(outsideWindow && force ? { force: true } : {}),
      });
      if (data?.unchanged) {
        toast.info("Already linked to that trip.");
      } else {
        const chosen = candidates.find((c) => c.id === selectedTripId);
        toast.success(`Linked → ${chosen?.lr_number || selectedTripId}`);
      }
      onSuccess?.(data?.expense);
      onClose?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Link failed");
    } finally { setSaving(false); }
  };

  const doUnlink = async () => {
    if (!eid || !currentTripId) return;
    setSaving(true);
    try {
      const { data } = await api.patch(`/expenses/${eid}/toll-trip`, { trip_id: "" });
      toast.success("Trip unlinked.");
      onSuccess?.(data?.expense);
      onClose?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Unlink failed");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-3 md:p-6"
         data-testid="link-toll-to-trip-dialog">
      <div className="bg-white w-[95vw] max-w-[720px] max-h-[85vh] border border-zinc-950 rounded-sm flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
          <div>
            <div className="text-[10px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Iter149 P0 · Toll Trip Linkage</div>
            <h3 className="font-bold text-lg">Link FASTag Toll → Trip</h3>
          </div>
          <button data-testid="close-link-toll-dialog" onClick={onClose}><X size={18}/></button>
        </div>

        <div className="p-5 space-y-4 overflow-y-auto">
          <div className="border border-zinc-200 bg-zinc-50 rounded-sm p-3 text-xs space-y-1"
               data-testid="link-toll-expense-summary">
            <div className="flex items-center gap-2">
              <Truck size={14} className="text-zinc-500"/>
              <span className="font-bold font-mono">{expense?.vehicle_number || expense?.vehicle_id || "—"}</span>
              <span className="text-zinc-400">·</span>
              <span>{expense?.date || "—"}</span>
              <span className="text-zinc-400">·</span>
              <span className="font-semibold text-emerald-700 tabular-nums">{fmtCurrency(expense?.amount || 0)}</span>
            </div>
            <div className="text-zinc-600">{expense?.narration || expense?.remarks || "—"}</div>
            <div className="text-zinc-400 text-[10px]">Txn ID: <span className="font-mono">{expense?.source_txn_ref || "—"}</span></div>
          </div>

          {currentTripId && (
            <div className="border border-emerald-200 bg-emerald-50 rounded-sm p-3 flex items-center justify-between"
                 data-testid="link-toll-current-link">
              <div className="text-xs">
                <span className="font-bold text-emerald-800">Currently linked to trip:</span>
                <span className="ml-2 font-mono">{currentTripId}</span>
              </div>
              <button data-testid="toll-unlink-confirm-btn"
                onClick={doUnlink} disabled={saving}
                className="px-3 py-1.5 text-[11px] uppercase tracking-wider border border-rose-300 text-rose-800 rounded-sm hover:bg-rose-50 disabled:opacity-50">
                Unlink
              </button>
            </div>
          )}

          <div>
            <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold mb-2">
              Candidate trips · vehicle {expense?.vehicle_number} · {dateFrom} → {dateTo}
            </div>
            {tripsQ.isLoading ? (
              <div className="text-zinc-400 text-sm" data-testid="link-toll-loading">Loading candidate trips…</div>
            ) : candidates.length === 0 ? (
              <div className="border border-dashed border-zinc-300 rounded-sm p-4 text-xs text-zinc-500"
                   data-testid="link-toll-no-candidates">
                No trips found for this vehicle within ±2 days. Create the trip first, then link.
              </div>
            ) : (
              <div className="space-y-2" data-testid="candidate-trip-picker">
                {candidates.map((t) => {
                  const active = t.id === selectedTripId;
                  const legacyBlocked = isLegacyConflictingTollTrip(t);
                  const daysDelta = (() => {
                    try {
                      return Math.round((new Date(t.date + "T00:00:00Z") - new Date(eDate + "T00:00:00Z")) / (1000*60*60*24));
                    } catch { return null; }
                  })();
                  return (
                    <label key={t.id}
                      data-testid={`candidate-trip-${t.id}`}
                      className={`flex items-start gap-3 border rounded-sm p-3 cursor-pointer transition
                        ${active ? "border-emerald-500 bg-emerald-50" : "border-zinc-200 hover:border-zinc-400 bg-white"}
                        ${legacyBlocked ? "opacity-60" : ""}`}>
                      <input type="radio" name="candidate-trip"
                        data-testid={`candidate-trip-radio-${t.id}`}
                        checked={active} disabled={legacyBlocked}
                        onChange={() => setSelectedTripId(t.id)}/>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-mono font-bold text-sm">{t.lr_number || t.id}</span>
                          <span className={`text-[10px] uppercase font-bold px-1.5 py-0.5 rounded-sm
                            ${t.vehicle_type === "supplier" ? "bg-orange-100 text-orange-800" : "bg-zinc-100 text-zinc-700"}`}>
                            {(t.vehicle_type || "own").toUpperCase()}
                          </span>
                          <span className="text-xs text-zinc-500">{t.date}</span>
                          {daysDelta !== null && (
                            <span className={`text-[10px] font-bold uppercase tracking-wider
                              ${daysDelta === 0 ? "text-emerald-700" : (Math.abs(daysDelta) > 2 ? "text-rose-700" : "text-amber-700")}`}>
                              {daysDelta === 0 ? "SAME DAY" : `${daysDelta > 0 ? "+" : ""}${daysDelta}d`}
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-zinc-700 mt-1">
                          {(t.from_location || "—")} → {(t.to_location || "—")}
                        </div>
                        <div className="text-[11px] text-zinc-500 mt-0.5">
                          {t.customer_name || "—"}
                          {t.driver_name ? <> · Driver: <span className="font-mono">{t.driver_name}</span></> : null}
                        </div>
                        {legacyBlocked && (
                          <div className="mt-1 text-[10px] text-rose-700 font-bold uppercase"
                               data-testid={`candidate-legacy-blocked-${t.id}`}>
                            <AlertTriangle size={11} className="inline mr-1"/>
                            Legacy-conflicting trip — cannot link (Toll already recorded in legacy Trip.expenses)
                          </div>
                        )}
                      </div>
                    </label>
                  );
                })}
              </div>
            )}
          </div>

          {outsideWindow && !!selectedTripId && (
            <div className="border-2 border-amber-400 bg-amber-50 rounded-sm p-3 flex items-start gap-2"
                 data-testid="link-toll-force-warning">
              <AlertTriangle size={16} className="text-amber-700 shrink-0 mt-0.5"/>
              <div className="flex-1 text-xs text-amber-900">
                <div className="font-bold uppercase tracking-wider">Trip date outside ±2 days</div>
                <label className="flex items-center gap-2 mt-1">
                  <input type="checkbox" data-testid="link-toll-force-checkbox"
                    checked={force} onChange={(e) => setForce(e.target.checked)}/>
                  <span>Override and link anyway (recorded in audit log)</span>
                </label>
              </div>
            </div>
          )}
        </div>

        <div className="border-t border-zinc-200 px-5 py-3 flex items-center justify-between">
          <div className="text-[11px] text-zinc-500">
            {isSameAsCurrent && !!selectedTripId ? "Same as current linkage · nothing to save." : "Explicit operator confirmation required."}
          </div>
          <div className="flex gap-2">
            <button data-testid="link-toll-cancel-btn" onClick={onClose}
              className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">
              Cancel
            </button>
            <button data-testid="link-toll-confirm-btn"
              disabled={!canLink || saving || isSameAsCurrent}
              onClick={doLink}
              className="inline-flex items-center gap-1 px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
              <Link2 size={13}/>
              {saving ? "Linking…" : (currentTripId && !isSameAsCurrent ? "Change link" : "Link trip")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
