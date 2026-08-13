import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { Sparkles, RefreshCw, Loader2 } from "lucide-react";

export default function InsightsCard() {
  const qc = useQueryClient();
  const { data, isFetching, isLoading } = useQuery({
    queryKey: ["ai-insights"],
    queryFn: async () => (await api.get("/ai/insights", { timeout: 60000 })).data,
    staleTime: 6 * 60 * 60 * 1000,
    retry: false,
  });
  const refresh = useMutation({
    mutationFn: async () => (await api.post("/ai/insights/refresh", null, { timeout: 60000 })).data,
    onSuccess: (d) => { qc.setQueryData(["ai-insights"], d); toast.success("Insights refreshed"); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Refresh failed"),
  });

  const bullets = data?.insights || [];

  return (
    <div data-testid="dashboard-insights-card" className="border border-zinc-950 bg-gradient-to-br from-zinc-950 to-zinc-800 text-white rounded-sm p-5">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.15em] font-bold text-emerald-300">
            <Sparkles size={12} /> AI Insights · స్మార్ట్ సూచనలు
          </div>
          <div className="text-xs text-zinc-400 mt-1">
            {data?.generated_at ? `Updated ${new Date(data.generated_at).toLocaleString()}` : "Live business signals"}
            {data?.cached ? " · cached (6h)" : ""}
          </div>
        </div>
        <button
          data-testid="insights-refresh-btn"
          disabled={refresh.isPending}
          onClick={() => refresh.mutate()}
          className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider border border-zinc-600 text-zinc-300 px-2 py-1 rounded-sm hover:bg-zinc-800"
        >
          {refresh.isPending ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
          Refresh
        </button>
      </div>

      {isLoading || (isFetching && bullets.length === 0) ? (
        <div className="text-sm text-zinc-400 flex items-center gap-2 py-4"><Loader2 size={14} className="animate-spin" /> Generating insights…</div>
      ) : bullets.length === 0 ? (
        <div className="text-sm text-zinc-400 py-4">No insights yet. Log a few trips and click Refresh.</div>
      ) : (
        <ul className="space-y-2" data-testid="insights-list">
          {bullets.map((b, i) => (
            <li key={i} data-testid={`insight-${i}`} className="text-sm leading-relaxed border-l-2 border-emerald-500 pl-3">
              {b}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
