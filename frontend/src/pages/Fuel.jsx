import React, { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate } from "@/api";
import { Fuel as FuelIcon, Upload, Plus, TrendingUp } from "lucide-react";
import FuelImportWizard from "@/components/fuel/FuelImportWizard";
import ManualFuelDialog from "@/components/fuel/ManualFuelDialog";

/* Iter147 P0 · Unified Fuel Log.
 * ------------------------------------------------------------------
 * Operator-facing single view over every Diesel projection:
 *   IOCL Import · BPCL Import · Quick Op · Manual · Trip Legacy · Legacy Fuel
 * Never a new accounting truth — pure projection. Buttons for IOCL /
 * BPCL fleet-card imports and canonical manual entry. */

const SOURCE_OPTIONS = [
  "IOCL Import", "BPCL Import", "Quick Op", "Manual",
  "Trip Legacy", "Legacy Fuel",
];

const SOURCE_COLORS = {
  "IOCL Import": "bg-orange-100 text-orange-800 border-orange-200",
  "BPCL Import": "bg-amber-100 text-amber-800 border-amber-200",
  "Quick Op": "bg-emerald-100 text-emerald-800 border-emerald-200",
  "Manual": "bg-sky-100 text-sky-800 border-sky-200",
  "Trip Legacy": "bg-zinc-100 text-zinc-700 border-zinc-200",
  "Legacy Fuel": "bg-zinc-100 text-zinc-500 border-zinc-200",
  "Fleet Card Import": "bg-orange-100 text-orange-800 border-orange-200",
};

export default function Fuel() {
  const qc = useQueryClient();
  const [wizardSource, setWizardSource] = useState(null); // "iocl" | "bpcl" | null
  const [manualOpen, setManualOpen] = useState(false);
  const [filters, setFilters] = useState({
    date_from: "", date_to: "", vehicle_id: "", source_label: "",
  });

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ["fuel-log", filters],
    queryFn: async () => {
      const p = new URLSearchParams();
      if (filters.date_from) p.set("date_from", filters.date_from);
      if (filters.date_to) p.set("date_to", filters.date_to);
      if (filters.vehicle_id) p.set("vehicle_id", filters.vehicle_id);
      if (filters.source_label) p.set("source_label", filters.source_label);
      const { data } = await api.get(`/fuel-log?${p.toString()}`);
      return data;
    },
  });

  const { data: vehicles = [] } = useQuery({
    queryKey: ["vehicles"],
    queryFn: async () => (await api.get("/vehicles")).data,
  });

  const totals = useMemo(() => {
    const t = { count: 0, litres: 0, amount: 0 };
    rows.forEach((r) => {
      t.count += 1;
      t.litres += Number(r.litres || 0);
      t.amount += Number(r.amount || 0);
    });
    return t;
  }, [rows]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["fuel-log"] });
  };

  return (
    <div className="space-y-6" data-testid="fuel-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4 gap-3 flex-wrap">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Diesel · Unified Log</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">డీజిల్ లాగ్</span>
            <span className="text-zinc-400"> · Fuel Log</span>
          </h1>
          <div className="mt-1 text-xs text-zinc-500">
            Every Diesel transaction — IOCL, BPCL, Quick Op, Manual, Trip Legacy — in one place.
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            data-testid="import-iocl-btn"
            onClick={() => setWizardSource("iocl")}
            className="px-3 py-2 text-xs uppercase tracking-wider font-semibold border border-orange-500 text-orange-700 rounded-sm hover:bg-orange-50 inline-flex items-center gap-2"
          >
            <Upload size={14} /> Import IOCL
          </button>
          <button
            data-testid="import-bpcl-btn"
            onClick={() => setWizardSource("bpcl")}
            className="px-3 py-2 text-xs uppercase tracking-wider font-semibold border border-amber-500 text-amber-700 rounded-sm hover:bg-amber-50 inline-flex items-center gap-2"
          >
            <Upload size={14} /> Import BPCL
          </button>
          <button
            data-testid="manual-fuel-btn"
            onClick={() => setManualOpen(true)}
            className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2"
          >
            <Plus size={14} /> Manual Fuel
          </button>
        </div>
      </header>

      {/* Filters */}
      <section className="grid grid-cols-2 md:grid-cols-5 gap-3" data-testid="fuel-filters">
        <F label="From">
          <input type="date" value={filters.date_from} data-testid="filter-date-from"
            onChange={(e) => setFilters({ ...filters, date_from: e.target.value })} className={ic} />
        </F>
        <F label="To">
          <input type="date" value={filters.date_to} data-testid="filter-date-to"
            onChange={(e) => setFilters({ ...filters, date_to: e.target.value })} className={ic} />
        </F>
        <F label="Vehicle">
          <select value={filters.vehicle_id} data-testid="filter-vehicle"
            onChange={(e) => setFilters({ ...filters, vehicle_id: e.target.value })} className={ic}>
            <option value="">All Vehicles</option>
            {vehicles.map((v) => <option key={v.id} value={v.id}>{v.vehicle_number}</option>)}
          </select>
        </F>
        <F label="Source">
          <select value={filters.source_label} data-testid="filter-source"
            onChange={(e) => setFilters({ ...filters, source_label: e.target.value })} className={ic}>
            <option value="">All Sources</option>
            {SOURCE_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </F>
        <F label=" ">
          <button
            data-testid="clear-filters-btn"
            onClick={() => setFilters({ date_from: "", date_to: "", vehicle_id: "", source_label: "" })}
            className={`${ic} text-left hover:bg-zinc-100`}
          >
            Clear filters
          </button>
        </F>
      </section>

      {/* Totals strip */}
      <section className="grid grid-cols-3 gap-3" data-testid="fuel-totals">
        <Kpi label="Entries" value={totals.count} />
        <Kpi label="Litres" value={totals.litres.toFixed(2)} />
        <Kpi label="Amount" value={fmtCurrency(totals.amount)} icon={<TrendingUp size={14} />} />
      </section>

      {/* Table */}
      <section className="border border-zinc-200 bg-white rounded-sm">
        <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider flex items-center gap-2">
          <FuelIcon size={14} /> Unified Fuel Log
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="fuel-log-table">
            <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="text-left px-4 py-2">Date</th>
                <th className="text-left px-4 py-2">Vehicle</th>
                <th className="text-right px-4 py-2">Litres</th>
                <th className="text-right px-4 py-2">Rate</th>
                <th className="text-right px-4 py-2">Amount</th>
                <th className="text-left px-4 py-2">Station</th>
                <th className="text-right px-4 py-2">ODO</th>
                <th className="text-left px-4 py-2">Source</th>
                <th className="text-left px-4 py-2">Reference</th>
                <th className="text-left px-4 py-2">Status</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {isLoading && (
                <tr><td colSpan={10} className="px-4 py-12 text-center text-zinc-400">Loading…</td></tr>
              )}
              {!isLoading && rows.length === 0 && (
                <tr><td colSpan={10} className="px-4 py-12 text-center text-zinc-400" data-testid="fuel-log-empty">
                  No Diesel entries yet. Import a fleet-card file or add a manual entry.
                </td></tr>
              )}
              {rows.map((r) => (
                <tr key={`${r.kind}:${r.id}`} data-testid={`fuel-row-${r.id}`} className="border-t border-zinc-100">
                  <td className="px-4 py-2 text-xs">{fmtDate(r.date)}</td>
                  <td className="px-4 py-2 font-semibold">{r.vehicle_number || "—"}</td>
                  <td className="px-4 py-2 text-right">{Number(r.litres || 0) > 0 ? Number(r.litres).toFixed(2) : "—"}</td>
                  <td className="px-4 py-2 text-right">{Number(r.rate || 0) > 0 ? fmtCurrency(r.rate) : "—"}</td>
                  <td className="px-4 py-2 text-right font-semibold">{fmtCurrency(r.amount)}</td>
                  <td className="px-4 py-2 text-xs text-zinc-600 max-w-[240px] truncate" title={r.station_name}>
                    {r.station_name || "—"}
                  </td>
                  <td className="px-4 py-2 text-right text-xs">
                    {r.odometer > 0 ? Number(r.odometer).toFixed(0) : "—"}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      data-testid={`source-chip-${r.id}`}
                      className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold border ${SOURCE_COLORS[r.source_label] || "bg-zinc-100 text-zinc-700 border-zinc-200"}`}
                    >
                      {r.source_label}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-zinc-500 max-w-[160px] truncate" title={r.source_txn_ref}>
                    {r.source_txn_ref || "—"}
                  </td>
                  <td className="px-4 py-2 text-xs text-emerald-700">{r.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {wizardSource && (
        <FuelImportWizard
          source={wizardSource}
          vehicles={vehicles}
          onClose={() => setWizardSource(null)}
          onSuccess={() => { setWizardSource(null); invalidate(); }}
        />
      )}
      {manualOpen && (
        <ManualFuelDialog
          vehicles={vehicles}
          onClose={() => setManualOpen(false)}
          onSuccess={() => { setManualOpen(false); invalidate(); }}
        />
      )}
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

function Kpi({ label, value, icon }) {
  return (
    <div className="border border-zinc-200 bg-white rounded-sm p-4">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold flex items-center gap-1">
        {icon} {label}
      </div>
      <div className="mt-1 text-2xl font-black tracking-tight font-mono">{value}</div>
    </div>
  );
}
