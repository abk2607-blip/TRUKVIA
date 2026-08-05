import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";
import { History } from "lucide-react";

const MODULES = ["", "trip", "invoice", "customer", "vehicle", "driver", "product", "payment"];
const ACTIONS = ["", "create", "update", "delete"];

export default function AuditLog() {
  const [module, setModule] = useState("");
  const [action, setAction] = useState("");
  const [entityId, setEntityId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const { data = [], isFetching, refetch } = useQuery({
    queryKey: ["audit-logs", module, action, entityId, start, end],
    queryFn: async () => (await api.get("/audit-logs", {
      params: {
        module: module || undefined,
        action: action || undefined,
        entity_id: entityId || undefined,
        start: start || undefined,
        end: end || undefined,
        limit: 300,
      },
    })).data,
  });

  return (
    <div className="space-y-6" data-testid="audit-page">
      <header className="border-b border-zinc-200 pb-4 flex items-end justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Compliance</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">ఆడిట్ లాగ్</span>
            <span className="text-zinc-400"> · Audit Log</span>
          </h1>
        </div>
      </header>

      <div className="border border-zinc-200 bg-white rounded-sm p-4 grid grid-cols-1 md:grid-cols-6 gap-3">
        <F label="Module">
          <select data-testid="audit-module" value={module} onChange={(e) => setModule(e.target.value)} className={ic}>
            {MODULES.map((m) => <option key={m} value={m}>{m || "All"}</option>)}
          </select>
        </F>
        <F label="Action">
          <select data-testid="audit-action" value={action} onChange={(e) => setAction(e.target.value)} className={ic}>
            {ACTIONS.map((a) => <option key={a} value={a}>{a || "All"}</option>)}
          </select>
        </F>
        <F label="Entity ID">
          <input data-testid="audit-entity" value={entityId} onChange={(e) => setEntityId(e.target.value)} className={ic} placeholder="trip_/inv_/..." />
        </F>
        <F label="From">
          <input data-testid="audit-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className={ic} />
        </F>
        <F label="To">
          <input data-testid="audit-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className={ic} />
        </F>
        <div className="flex items-end">
          <button data-testid="audit-refresh" onClick={() => refetch()} className="w-full px-3 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800">
            {isFetching ? "..." : "Refresh"}
          </button>
        </div>
      </div>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
        <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider flex items-center gap-2">
          <History size={14} /> {data.length} entries
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="audit-table">
            <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="text-left px-3 py-2">Time</th>
                <th className="text-left px-3 py-2">User</th>
                <th className="text-left px-3 py-2">Module</th>
                <th className="text-left px-3 py-2">Action</th>
                <th className="text-left px-3 py-2">Ref</th>
                <th className="text-left px-3 py-2">Reason</th>
                <th className="text-left px-3 py-2">Changes</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {data.map((log) => (
                <tr key={log.id} data-testid={`audit-row-${log.id}`} className="border-t border-zinc-100 align-top">
                  <td className="px-3 py-2 text-xs whitespace-nowrap">{new Date(log.timestamp).toLocaleString("en-IN")}</td>
                  <td className="px-3 py-2 text-xs">{log.user_name || log.user_email || "—"}</td>
                  <td className="px-3 py-2 text-xs uppercase">{log.module}</td>
                  <td className="px-3 py-2 text-xs">
                    <span className={`px-1.5 py-0.5 rounded-sm border text-[10px] uppercase ${
                      log.action === "create" ? "border-emerald-300 text-emerald-800 bg-emerald-50" :
                      log.action === "update" ? "border-amber-300 text-amber-800 bg-amber-50" :
                      "border-rose-300 text-rose-800 bg-rose-50"
                    }`}>{log.action}</span>
                  </td>
                  <td className="px-3 py-2 text-xs">{log.entity_ref || log.entity_id}</td>
                  <td className="px-3 py-2 text-xs text-zinc-600 max-w-[200px] truncate" title={log.reason}>{log.reason || "—"}</td>
                  <td className="px-3 py-2 text-[10px] text-zinc-500 max-w-[300px]">
                    {log.changes && Object.keys(log.changes).length > 0 ? (
                      <details>
                        <summary className="cursor-pointer">{Object.keys(log.changes).length} field(s)</summary>
                        <pre className="mt-1 text-[9px] whitespace-pre-wrap">{JSON.stringify(log.changes, null, 2)}</pre>
                      </details>
                    ) : "—"}
                  </td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-12 text-center text-zinc-400 text-sm">No matching entries.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

const ic = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";
function F({ label, children }) {
  return (
    <div>
      <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">{label}</label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
