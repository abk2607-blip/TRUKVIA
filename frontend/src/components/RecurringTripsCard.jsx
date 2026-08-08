import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, fmtCurrency } from "@/api";
import { toast } from "sonner";
import { Repeat, Loader2 } from "lucide-react";

export default function RecurringTripsCard() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { data: suggestions = [], isLoading } = useQuery({
    queryKey: ["recurring-suggestions"],
    queryFn: async () => (await api.get("/trips/recurring-suggestions")).data,
    staleTime: 60_000,
  });
  const repeat = useMutation({
    mutationFn: async (lastTripId) => (await api.post(`/trips/quick-repeat/${lastTripId}`)).data,
    onSuccess: (t) => {
      toast.success(`Repeated — ${t.vehicle_number} for today`);
      qc.invalidateQueries({ queryKey: ["trips"] });
      qc.invalidateQueries({ queryKey: ["recurring-suggestions"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      nav(`/trips/${t.id}/edit`);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Repeat failed"),
  });

  if (isLoading) {
    return (
      <div className="border border-zinc-200 bg-white p-5 rounded-sm text-sm text-zinc-500 flex items-center gap-2">
        <Loader2 size={14} className="animate-spin" /> Loading recurring trips…
      </div>
    );
  }
  if (!suggestions.length) return null;

  return (
    <div data-testid="recurring-trips-card" className="border border-emerald-300 bg-emerald-50 rounded-sm p-5">
      <div className="flex items-center gap-2 mb-3">
        <Repeat size={14} className="text-emerald-700" />
        <div className="text-[10px] uppercase tracking-[0.15em] font-bold text-emerald-900">One-Tap Trips · పునరావృత ట్రిప్స్</div>
        <div className="text-xs text-emerald-800 ml-2">Regular routes detected — tap to log today's run</div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {suggestions.map((s) => (
          <button
            key={s.last_trip_id}
            data-testid={`recurring-repeat-${s.last_trip_id}`}
            disabled={repeat.isPending}
            onClick={() => repeat.mutate(s.last_trip_id)}
            className="text-left border border-emerald-200 bg-white rounded-sm p-3 hover:border-emerald-600 hover:shadow-sm transition disabled:opacity-50"
          >
            <div className="text-xs font-bold text-zinc-900 truncate">{s.customer_name}</div>
            <div className="text-[11px] text-zinc-500 mt-0.5 truncate">
              {s.from_location} → {s.to_location}
            </div>
            <div className="flex items-center justify-between mt-2 text-[10px]">
              <span className="text-emerald-800">↻ {s.count_60d}× in 60d</span>
              <span className="font-mono text-zinc-600">{s.vehicle_number}</span>
            </div>
            <div className="text-[11px] text-zinc-700 mt-1 font-mono">Avg {fmtCurrency(s.avg_freight)}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
