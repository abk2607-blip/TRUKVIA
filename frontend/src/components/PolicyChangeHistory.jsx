import React, { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { X, Loader2, Undo2, ShieldAlert, CheckCircle2, AlertTriangle } from "lucide-react";

const fmt = (n) =>
  Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const _FM = {
  per_ton_loading: "Per Ton · Loading Qty",
  per_ton_unloading: "Per Ton · Unloading Qty",
  per_ton_higher_of: "Per Ton · Higher of Loading / Unloading",
  fixed: "Fixed / Round Trip",
};
const _SM = {
  net_shortage: "Net Shortage above limit",
  full_after_limit: "Full Shortage After Limit Exceeded",
};

function _summarise(p) {
  const sc = p?.shortage_config || {};
  return {
    freight: _FM[p?.default_freight_method] || p?.default_freight_method || "—",
    method: _SM[sc.method] || sc.method || "—",
    allowance: Number(sc.limit || 0) > 0
      ? `${sc.limit}${sc.limit_type === "kg" ? " KG" : " %"}`
      : "Uses Product Master allowance",
    effective_from: sc.effective_from || "—",
  };
}

function StatusBadge({ status }) {
  if (status === "reverted") {
    return (
      <span className="text-[10px] uppercase tracking-widest font-bold px-2 py-0.5 border border-rose-300 bg-rose-50 text-rose-800">
        Reverted
      </span>
    );
  }
  return (
    <span className="text-[10px] uppercase tracking-widest font-bold px-2 py-0.5 border border-emerald-300 bg-emerald-50 text-emerald-800">
      Applied
    </span>
  );
}

/**
 * Iter105 · Phase B — Policy Change History modal for one customer.
 *
 * Shows every policy-change event with old vs new summary, effective date,
 * reason, actor, affected-trip count. A `Revert` button on `applied` rows
 * opens a confirmation dialog that requires a mandatory reason and surfaces
 * the invoice-safety blocker if the backend refuses the revert (409).
 */
export default function PolicyChangeHistory({ customerId, customerName, onClose }) {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(null); // event row
  const [reason, setReason] = useState("");
  const [blockedInfo, setBlockedInfo] = useState(null);

  const { data, isLoading } = useQuery({
    queryKey: ["policy-changes", customerId],
    queryFn: async () =>
      (await api.get("/policy-changes", { params: { customer_id: customerId } })).data,
    enabled: !!customerId,
  });

  const items = data?.items || [];

  const revertMut = useMutation({
    mutationFn: async ({ eventId, reason }) =>
      (await api.post(`/policy-changes/${eventId}/revert`, { reason })).data,
    onSuccess: (resp) => {
      toast.success(`Reverted · ${resp.reverted_trip_count} trip(s) restored`);
      setConfirming(null);
      setReason("");
      setBlockedInfo(null);
      qc.invalidateQueries({ queryKey: ["policy-changes", customerId] });
      qc.invalidateQueries({ queryKey: ["customers"] });
      qc.invalidateQueries({ queryKey: ["customers-paginated"] });
      qc.invalidateQueries({ queryKey: ["trips"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err) => {
      const detail = err?.response?.data?.detail;
      if (err?.response?.status === 409 && detail?.code === "REVERT_BLOCKED_INVOICED") {
        setBlockedInfo(detail);
        return; // keep modal open, show blocking message inline
      }
      const msg = typeof detail === "string" ? detail : detail?.message || "Revert failed";
      toast.error(msg);
    },
  });

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
         data-testid="policy-history-modal">
      <div className="bg-white w-full max-w-5xl max-h-[92vh] flex flex-col shadow-2xl border border-zinc-200">
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-200">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-amber-600 font-bold">
              Iter105 · Policy Changes
            </div>
            <h2 className="text-lg font-black text-zinc-950 tracking-tight">
              {customerName}
            </h2>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-zinc-100 rounded"
                  data-testid="policy-history-close">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {isLoading && (
            <div className="p-6 flex items-center justify-center text-zinc-600">
              <Loader2 className="animate-spin mr-2" size={16} /> Loading policy history...
            </div>
          )}
          {!isLoading && items.length === 0 && (
            <div className="p-8 text-center text-sm text-zinc-500 border border-dashed border-zinc-300">
              No policy changes recorded for this customer yet.
            </div>
          )}
          {items.map((ev) => (
            <PolicyEventRow
              key={ev.id}
              event={ev}
              onRevert={() => { setConfirming(ev); setReason(""); setBlockedInfo(null); }}
            />
          ))}
        </div>
      </div>

      {/* Revert confirmation sub-modal */}
      {confirming && (
        <div className="fixed inset-0 z-[60] bg-black/50 flex items-center justify-center p-4"
             data-testid="policy-revert-confirm">
          <div className="bg-white w-full max-w-lg shadow-2xl border border-zinc-950">
            <div className="px-5 py-4 border-b border-zinc-200 flex items-center gap-2">
              <ShieldAlert size={18} className="text-rose-600" />
              <div className="text-sm font-bold text-zinc-950 uppercase tracking-wider">
                Confirm Revert
              </div>
            </div>
            <div className="p-5 space-y-4 text-sm">
              <p className="text-zinc-700">
                This will restore the customer master and{" "}
                <span className="font-bold">{confirming.applied_trip_ids?.length || 0}</span>{" "}
                previously-applied trip{(confirming.applied_trip_ids?.length || 0) === 1 ? "" : "s"}{" "}
                to the policy in effect before <span className="font-mono">{confirming.created_at?.slice(0, 10)}</span>.
              </p>

              {blockedInfo && (
                <div className="border border-rose-300 bg-rose-50 p-3 space-y-1"
                     data-testid="policy-revert-blocked">
                  <div className="flex items-center gap-1 text-rose-800 font-bold text-xs uppercase tracking-wider">
                    <AlertTriangle size={14} /> Revert blocked
                  </div>
                  <div className="text-xs text-rose-800">{blockedInfo.message}</div>
                  {blockedInfo.invoiced_lr_numbers?.length > 0 && (
                    <div className="text-[11px] font-mono text-rose-900 mt-1">
                      LRs: {blockedInfo.invoiced_lr_numbers.filter(Boolean).join(", ") || blockedInfo.invoiced_trip_ids.join(", ")}
                    </div>
                  )}
                </div>
              )}

              <div>
                <label className="block text-[10px] uppercase tracking-widest text-zinc-500 font-bold mb-1">
                  Reason for revert (required) <span className="text-rose-600">*</span>
                </label>
                <textarea
                  rows={3}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="e.g. Contract renegotiated · reverting to previous shortage terms"
                  className="w-full border border-zinc-300 px-3 py-2 text-sm"
                  data-testid="policy-revert-reason"
                />
              </div>
            </div>
            <div className="px-5 py-4 border-t border-zinc-200 flex items-center justify-end gap-2">
              <button
                onClick={() => { setConfirming(null); setBlockedInfo(null); setReason(""); }}
                className="px-4 py-2 text-sm border border-zinc-300 hover:bg-zinc-100"
                data-testid="policy-revert-cancel">
                Cancel
              </button>
              <button
                onClick={() => revertMut.mutate({ eventId: confirming.id, reason: reason.trim() })}
                disabled={!reason.trim() || revertMut.isPending}
                className="px-4 py-2 text-sm bg-rose-700 text-white font-semibold uppercase tracking-wider hover:bg-rose-800 disabled:opacity-40 inline-flex items-center gap-2"
                data-testid="policy-revert-confirm-btn">
                {revertMut.isPending && <Loader2 className="animate-spin" size={14} />}
                <Undo2 size={14} /> Confirm revert
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function PolicyEventRow({ event, onRevert }) {
  const [expanded, setExpanded] = useState(false);
  const old_ = useMemo(() => _summarise(event.old_policy), [event.old_policy]);
  const new_ = useMemo(() => _summarise(event.new_policy), [event.new_policy]);
  const deltas = event.per_trip_deltas || [];
  const isApplied = event.status === "applied";

  return (
    <div className="border border-zinc-200" data-testid={`policy-event-${event.id}`}>
      <div className="flex items-center gap-3 p-3">
        <StatusBadge status={event.status} />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-bold text-zinc-950">
            {event.created_at?.slice(0, 10)} · effective {event.effective_from}
          </div>
          <div className="text-[11px] text-zinc-500">
            by {event.actor_email || event.actor_name || "—"} ·{" "}
            {event.applied_trip_ids?.length || 0} trip(s) affected
            {event.reason ? ` · "${event.reason}"` : ""}
          </div>
          {event.status === "reverted" && (
            <div className="text-[11px] text-rose-700 mt-0.5">
              Reverted {event.reverted_at?.slice(0, 10)} by {event.reverted_by || "—"} · "{event.revert_reason}"
            </div>
          )}
        </div>
        {isApplied && (
          <button
            onClick={onRevert}
            className="px-3 py-1.5 text-[11px] uppercase tracking-widest font-bold border border-rose-300 text-rose-700 hover:bg-rose-50 inline-flex items-center gap-1"
            data-testid={`policy-revert-btn-${event.id}`}>
            <Undo2 size={12} /> Revert
          </button>
        )}
        <button onClick={() => setExpanded(!expanded)}
                className="text-[11px] uppercase tracking-wider text-zinc-500 hover:text-zinc-950"
                data-testid={`policy-expand-${event.id}`}>
          {expanded ? "Hide" : "Details"}
        </button>
      </div>

      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-zinc-100 bg-zinc-50/40">
          <div className="grid grid-cols-2 gap-3 pt-3">
            <PolicyMini title="Old" data={old_} />
            <PolicyMini title="New" data={new_} highlight />
          </div>
          {deltas.length > 0 && (
            <div className="border border-zinc-200 bg-white">
              <div className="px-3 py-1.5 border-b border-zinc-200 text-[10px] uppercase tracking-widest text-zinc-500 font-bold">
                Per-trip changes
              </div>
              <table className="w-full text-xs">
                <thead className="bg-zinc-50 text-zinc-500 uppercase text-[10px]">
                  <tr>
                    <th className="p-2 text-left">Date</th>
                    <th className="p-2 text-left">Vehicle · LR</th>
                    <th className="p-2 text-right">Old shortage ₹</th>
                    <th className="p-2 text-right">New shortage ₹</th>
                    <th className="p-2 text-right">Old freight ₹</th>
                    <th className="p-2 text-right">New freight ₹</th>
                    <th className="p-2 text-right">Δ Net ₹</th>
                  </tr>
                </thead>
                <tbody>
                  {deltas.map((d) => (
                    <tr key={d.trip_id} className="border-t border-zinc-100">
                      <td className="p-2 font-mono">{d.date}</td>
                      <td className="p-2">
                        <div className="font-semibold">{d.vehicle_number}</div>
                        <div className="text-[10px] text-zinc-500">{d.lr_number || "—"}</div>
                      </td>
                      <td className="p-2 text-right font-mono">₹ {fmt(d.old?.shortage_amount)}</td>
                      <td className="p-2 text-right font-mono">₹ {fmt(d.new?.shortage_amount)}</td>
                      <td className="p-2 text-right font-mono">₹ {fmt(d.old?.freight_amount)}</td>
                      <td className="p-2 text-right font-mono">₹ {fmt(d.new?.freight_amount)}</td>
                      <td className="p-2 text-right font-mono font-bold">
                        {d.delta_net_settlement > 0 ? "+" : ""}₹ {fmt(d.delta_net_settlement)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function PolicyMini({ title, data, highlight }) {
  const bg = highlight ? "bg-emerald-50 border-emerald-200" : "bg-white border-zinc-200";
  return (
    <div className={`border ${bg} p-3 text-xs space-y-1`}>
      <div className={`text-[10px] uppercase tracking-widest font-bold ${
        highlight ? "text-emerald-700" : "text-zinc-500"
      }`}>{title} policy</div>
      <div><span className="text-zinc-500">Freight:</span> <span className="font-bold">{data.freight}</span></div>
      <div><span className="text-zinc-500">Deduction:</span> <span className="font-bold">{data.method}</span></div>
      <div><span className="text-zinc-500">Allowance:</span> <span className="font-bold">{data.allowance}</span></div>
      <div><span className="text-zinc-500">Effective:</span> <span className="font-mono">{data.effective_from}</span></div>
    </div>
  );
}
