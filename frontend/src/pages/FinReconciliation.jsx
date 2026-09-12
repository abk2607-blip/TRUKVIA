import React, { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { RefreshCw, X } from "lucide-react";

const DOMAIN_META = [
  { code: "A", label: "Source ↔ FinTxn", tab: "source-fintxn" },
  { code: "B", label: "Expense Balance", tab: "balances" },
  { code: "C", label: "AR ↔ Balance Due", tab: "balances" },
  { code: "D", label: "CN / DN Totals", tab: "balances" },
  { code: "E", label: "Wallets", tab: "wallets" },
  { code: "F", label: "Payables Invariant", tab: "payables" },
  { code: "G", label: "Projection Health", tab: "projection-health" },
  { code: "H", label: "Day Closings", tab: "day-closings" },
];

const TABS = [
  { id: "source-fintxn", label: "Source ↔ FinTxn", domains: ["A"] },
  { id: "balances", label: "Balances", domains: ["B", "C", "D"] },
  { id: "wallets", label: "Wallets", domains: ["E"] },
  { id: "payables", label: "Payables", domains: ["F"] },
  { id: "projection-health", label: "Projection Health", domains: ["G"] },
  { id: "day-closings", label: "Day Closings", domains: ["H"] },
];

const STATUS_STYLE = {
  emerald: "bg-emerald-50 text-emerald-800 border-emerald-200",
  amber: "bg-amber-50 text-amber-800 border-amber-200",
  rose: "bg-rose-50 text-rose-800 border-rose-200",
};

function StatusChip({ status, children }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider border rounded-sm ${STATUS_STYLE[status] || "border-zinc-200"}`}>
      {children || status}
    </span>
  );
}

function KPITile({ code, label, kpi, active, onClick }) {
  const status = kpi?.status || "emerald";
  return (
    <button
      data-testid={`recon-kpi-${code.toLowerCase()}`}
      onClick={onClick}
      className={`text-left border rounded-sm p-3 transition-colors ${active ? "border-zinc-950 shadow-[0_0_0_2px_hsl(var(--brand))_inset]" : "border-zinc-200 hover:bg-zinc-50"}`}
    >
      <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">{code} · {label}</div>
      <div className="mt-2 flex items-center justify-between">
        <StatusChip status={status} />
        <span className="text-xs text-zinc-600">{kpi?.count ?? 0} row(s)</span>
      </div>
    </button>
  );
}

export default function FinReconciliation() {
  const today = new Date().toISOString().slice(0, 10);
  const monthAgo = new Date(Date.now() - 31 * 86400000).toISOString().slice(0, 10);
  const [from, setFrom] = useState(monthAgo);
  const [to, setTo] = useState(today);
  const [activeTab, setActiveTab] = useState("source-fintxn");
  const [selectedRow, setSelectedRow] = useState(null);
  const isOwner = true; // client hint only — server enforces on /fin/reproject

  const { data: sumData, refetch: refetchSummary, isFetching: sumLoading } = useQuery({
    queryKey: ["recon-summary", from, to],
    queryFn: async () => (await api.get(`/fin/reconciliation/summary?from=${from}&to=${to}`)).data,
  });
  const domainsInTab = useMemo(() => TABS.find(t => t.id === activeTab)?.domains || [], [activeTab]);
  const domainQueries = useQuery({
    queryKey: ["recon-domain", activeTab, from, to],
    queryFn: async () => {
      const results = {};
      for (const d of domainsInTab) {
        const r = await api.get(`/fin/reconciliation/domain/${d}?from=${from}&to=${to}&page=1&size=100`);
        results[d] = r.data;
      }
      return results;
    },
    enabled: domainsInTab.length > 0,
  });

  const allRows = useMemo(() => {
    const rows = [];
    for (const [d, res] of Object.entries(domainQueries.data || {})) {
      for (const r of (res.rows || [])) rows.push({ ...r, _domain: d });
    }
    return rows;
  }, [domainQueries.data]);

  const doRebuild = async (row) => {
    if (!row.source_type || !row.source_id) {
      toast.error("No source reference available for rebuild.");
      return;
    }
    try {
      await api.post("/fin/reproject", { source_type: row.source_type, source_id: row.source_id });
      toast.success("Rebuild queued · row will refresh.");
      await refetchSummary();
      await domainQueries.refetch();
      setSelectedRow(null);
    } catch (e) {
      const detail = e?.response?.data?.detail || "Rebuild failed";
      toast.error(String(detail));
    }
  };

  const isClean = allRows.length === 0 && !domainQueries.isFetching;

  return (
    <div className="space-y-6" data-testid="recon-page">
      <div>
        <div className="text-[11px] uppercase tracking-[0.28em] font-bold text-zinc-500">
          <span className="telugu">అకౌంట్ మ్యాచింగ్</span>
          <span className="mx-1 text-zinc-300">·</span>Reconciliation
        </div>
        <h1 className="mt-1 text-3xl font-black tracking-tight text-zinc-950">Reconciliation Center</h1>
        <div className="mt-1 text-xs text-zinc-500">
          computed_at · {sumData?.computed_at || "—"}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3 border-b border-zinc-200 pb-3">
        <label className="text-xs">
          <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">From</div>
          <input type="date" value={from} onChange={e => setFrom(e.target.value)} className="mt-1 border border-zinc-300 px-2 py-1 rounded-sm text-sm" />
        </label>
        <label className="text-xs">
          <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">To</div>
          <input type="date" value={to} onChange={e => setTo(e.target.value)} className="mt-1 border border-zinc-300 px-2 py-1 rounded-sm text-sm" />
        </label>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {DOMAIN_META.map(m => (
          <KPITile
            key={m.code}
            code={m.code}
            label={m.label}
            kpi={sumData?.kpis?.[m.code]}
            active={TABS.find(t => t.id === activeTab)?.domains?.includes(m.code)}
            onClick={() => setActiveTab(m.tab)}
          />
        ))}
      </div>

      <div className="flex flex-wrap gap-1 border-b border-zinc-200">
        {TABS.map(t => (
          <button
            key={t.id}
            data-testid={`recon-tab-${t.id}`}
            onClick={() => setActiveTab(t.id)}
            className={`text-xs uppercase tracking-wider font-bold px-3 py-2 border-b-2 ${activeTab === t.id ? "border-zinc-950 text-zinc-950" : "border-transparent text-zinc-500 hover:text-zinc-800"}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === "day-closings" && (
        <div className="border border-amber-200 bg-amber-50 text-amber-900 rounded-sm p-3 text-xs">
          Day Closing snapshots do not auto-refresh after late entries. Reopen the day to re-close if you want the snapshot updated.
        </div>
      )}

      {isClean ? (
        <div data-testid="recon-empty-state" className="border border-emerald-200 bg-emerald-50 text-emerald-900 rounded-sm p-6 text-center text-sm">
          Everything reconciles cleanly.
        </div>
      ) : (
        <table data-testid="recon-mismatch-table" className="w-full text-sm border border-zinc-200">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-widest text-zinc-500">
            <tr>
              <th className="text-left p-2">Domain</th>
              <th className="text-left p-2">Key</th>
              <th className="text-right p-2">Source</th>
              <th className="text-right p-2">Projected</th>
              <th className="text-right p-2">Δ</th>
              <th className="text-left p-2">Status</th>
              <th className="text-left p-2">Last checked</th>
            </tr>
          </thead>
          <tbody>
            {allRows.map((r, i) => (
              <tr
                key={`${r._domain}:${r.key}:${i}`}
                data-testid="recon-mismatch-row"
                onClick={() => setSelectedRow(r)}
                className="border-t border-zinc-100 hover:bg-zinc-50 cursor-pointer"
              >
                <td className="p-2 font-mono text-xs">{r._domain}</td>
                <td className="p-2 font-mono text-xs">{r.key}</td>
                <td className="p-2 text-right font-mono">{r.source ?? "—"}</td>
                <td className="p-2 text-right font-mono">{r.projected ?? "—"}</td>
                <td className="p-2 text-right font-mono">{r.delta ?? "—"}</td>
                <td className="p-2"><StatusChip status={r.status} /></td>
                <td className="p-2 text-[11px] text-zinc-500">{r.last_checked?.slice(0, 19) || "—"}</td>
              </tr>
            ))}
            {allRows.length === 0 && (
              <tr><td colSpan={7} className="p-6 text-center text-zinc-500">No rows in this tab · looks clean.</td></tr>
            )}
          </tbody>
        </table>
      )}

      {selectedRow && (
        <div className="fixed inset-0 z-50 bg-zinc-900/50" onClick={() => setSelectedRow(null)}>
          <div
            data-testid="recon-detail-drawer"
            className="absolute right-0 top-0 h-full w-full max-w-md bg-white shadow-2xl p-6 overflow-auto"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <div className="text-[11px] uppercase tracking-widest font-bold text-zinc-500">Mismatch Detail</div>
              <button onClick={() => setSelectedRow(null)} className="w-8 h-8 flex items-center justify-center hover:bg-zinc-100 rounded-sm"><X size={18} /></button>
            </div>
            <div className="mt-2 text-lg font-bold text-zinc-950">{selectedRow._domain} · {selectedRow.key}</div>
            <div className="mt-4 space-y-2 text-sm">
              <div><b>Source:</b> <span className="font-mono">{selectedRow.source ?? "—"}</span></div>
              <div><b>Projected:</b> <span className="font-mono">{selectedRow.projected ?? "—"}</span></div>
              <div><b>Δ:</b> <span className="font-mono">{selectedRow.delta ?? "—"}</span></div>
              <div><b>Status:</b> <StatusChip status={selectedRow.status} /></div>
              {selectedRow.note && <div className="text-xs text-zinc-600 mt-2">{selectedRow.note}</div>}
            </div>
            {selectedRow.source_type && selectedRow.source_id && (
              <div className="mt-4 space-y-1 text-xs text-zinc-600">
                <div>Source: <span className="font-mono">/api/fin/source/{selectedRow.source_type}/{selectedRow.source_id}</span></div>
                <div>Legs: <span className="font-mono">/api/fin/source-legs/{selectedRow.source_type}/{selectedRow.source_id}</span></div>
              </div>
            )}
            {isOwner && selectedRow.source_type && selectedRow.source_id && (
              <button
                data-testid="recon-rebuild-btn"
                onClick={() => doRebuild(selectedRow)}
                className="mt-6 w-full inline-flex items-center justify-center gap-2 px-4 py-3 bg-zinc-950 text-white text-sm font-semibold uppercase tracking-wider rounded-sm border border-zinc-950 hover:bg-white hover:text-zinc-950 transition-colors"
                style={{ outlineColor: "#FD7800" }}
              >
                <RefreshCw size={16} /> Rebuild this row
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
