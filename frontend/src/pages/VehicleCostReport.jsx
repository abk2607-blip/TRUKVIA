import React, { useState, useMemo } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";
import { ArrowLeft, Truck, FileText, Wrench, Calendar, Plus } from "lucide-react";

/**
 * Iter133 · Turn 2B — Vehicle Cost + Repair History (read-only).
 * Reads canonical Expense collection (with legacy XOR fallback) via
 *   GET /api/vehicles/:vid/cost-summary
 *   GET /api/vehicles/:vid/repair-history
 * NO client-side re-aggregation. Server is the single source of truth.
 */
export default function VehicleCostReport() {
  const { vid } = useParams();
  const navigate = useNavigate();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [category, setCategory] = useState("");
  const [tripLinked, setTripLinked] = useState(""); // "", "yes", "no"

  const params = useMemo(() => {
    const p = {};
    if (from) p.from = from;
    if (to) p.to = to;
    if (category) p.category = category;
    if (tripLinked) p.trip_linked = tripLinked;
    return p;
  }, [from, to, category, tripLinked]);

  const { data: vehicle } = useQuery({
    queryKey: ["vehicle", vid],
    queryFn: async () => (await api.get(`/vehicles`)).data.find((x) => x.id === vid) || null,
  });
  const cost = useQuery({
    queryKey: ["vehicle-cost", vid, params],
    queryFn: async () =>
      (await api.get(`/vehicles/${vid}/cost-summary`, { params })).data,
  });
  const history = useQuery({
    queryKey: ["vehicle-repair-history", vid, from, to],
    queryFn: async () =>
      (await api.get(`/vehicles/${vid}/repair-history`, {
        params: { ...(from ? { from } : {}), ...(to ? { to } : {}) },
      })).data,
  });

  const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;

  return (
    <div className="p-6 space-y-6" data-testid="vehicle-cost-report">
      <div className="flex items-center gap-3">
        <button
          data-testid="back-btn"
          onClick={() => navigate("/vehicles")}
          className="flex items-center gap-1 text-sm text-zinc-600 hover:text-zinc-900"
        >
          <ArrowLeft size={16} /> Back to Vehicles
        </button>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <Truck size={22} /> {vehicle?.vehicle_number || vid}
        </h1>
        <Link
          data-testid="new-repair-btn"
          to={`/vehicles/${vid}/repairs/new`}
          className="ml-auto inline-flex items-center gap-1 text-xs px-3 py-2 bg-zinc-950 text-white rounded-sm hover:bg-zinc-800"
        >
          <Plus size={14} /> New Repair
        </Link>
      </div>

      {/* Filters */}
      <div className="bg-white border rounded-lg p-4 flex flex-wrap gap-3 items-end" data-testid="filters">
        <label className="text-sm">From
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)}
            className="ml-2 border rounded px-2 py-1" data-testid="filter-from" />
        </label>
        <label className="text-sm">To
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)}
            className="ml-2 border rounded px-2 py-1" data-testid="filter-to" />
        </label>
        <label className="text-sm">Category
          <input type="text" value={category} onChange={(e) => setCategory(e.target.value)}
            placeholder="Toll / Repair-Parts …"
            className="ml-2 border rounded px-2 py-1" data-testid="filter-category" />
        </label>
        <label className="text-sm">Trip-linked
          <select value={tripLinked} onChange={(e) => setTripLinked(e.target.value)}
            className="ml-2 border rounded px-2 py-1" data-testid="filter-trip-linked">
            <option value="">Any</option>
            <option value="yes">Trip-linked only</option>
            <option value="no">Non-trip only</option>
          </select>
        </label>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4" data-testid="kpis">
        <Kpi label="Total Cost" value={fmt(cost.data?.total_cost)} testid="kpi-total" />
        <Kpi label="Transactions" value={cost.data?.expense_count ?? 0} testid="kpi-count" />
        <Kpi label="Trip-linked" value={fmt(cost.data?.trip_linked_total)} testid="kpi-trip" />
        <Kpi label="Non-trip" value={fmt(cost.data?.non_trip_total)} testid="kpi-nontrip" />
        <Kpi label="Repair Cost" value={fmt(cost.data?.repair_total)} testid="kpi-repair" />
      </div>

      {/* Category breakdown */}
      <div className="bg-white border rounded-lg p-4" data-testid="category-breakdown">
        <h2 className="text-lg font-semibold flex items-center gap-2 mb-3">
          <FileText size={18} /> Category-wise Cost
        </h2>
        {cost.isLoading ? <div className="text-zinc-500">Loading…</div> :
         (cost.data?.by_category || []).length === 0 ? <div className="text-zinc-400">No expenses in this range.</div> :
         <table className="w-full text-sm">
           <thead><tr className="text-left border-b"><th className="py-2">Category</th><th className="text-right">Amount</th></tr></thead>
           <tbody>
             {cost.data.by_category.map((r) => (
               <tr key={r.category} className="border-b" data-testid={`cat-row-${r.category}`}>
                 <td className="py-2">{r.category}</td>
                 <td className="text-right font-medium">{fmt(r.amount)}</td>
               </tr>
             ))}
           </tbody>
         </table>}
      </div>

      {/* Monthly */}
      <div className="bg-white border rounded-lg p-4" data-testid="monthly-breakdown">
        <h2 className="text-lg font-semibold flex items-center gap-2 mb-3">
          <Calendar size={18} /> Monthly Cost
        </h2>
        {(cost.data?.by_month || []).length === 0 ? <div className="text-zinc-400">Nothing to show.</div> :
         <table className="w-full text-sm">
           <thead><tr className="text-left border-b"><th className="py-2">Month</th><th className="text-right">Amount</th></tr></thead>
           <tbody>
             {cost.data.by_month.map((r) => (
               <tr key={r.month} className="border-b">
                 <td className="py-2">{r.month}</td>
                 <td className="text-right">{fmt(r.amount)}</td>
               </tr>
             ))}
           </tbody>
         </table>}
      </div>

      {/* Repair History */}
      <div className="bg-white border rounded-lg p-4" data-testid="repair-history">
        <h2 className="text-lg font-semibold flex items-center gap-2 mb-3">
          <Wrench size={18} /> Repair History
          <span className="text-sm font-normal text-zinc-500">
            (Total repair cost: <span data-testid="history-total">{fmt(history.data?.total_repair_cost)}</span>)
          </span>
        </h2>
        {history.isLoading ? <div className="text-zinc-500">Loading…</div> :
         (history.data?.events || []).length === 0 ? <div className="text-zinc-400">No repair events for this vehicle.</div> :
         <div className="space-y-3">
           {history.data.events.map((ev) => (
             <details key={ev.id} className="border rounded" data-testid={`repair-event-${ev.id}`}>
               <summary className="cursor-pointer px-3 py-2 flex flex-wrap gap-x-6 gap-y-1 text-sm items-center">
                 <span className="font-medium">{ev.event_date}</span>
                 <span>{ev.workshop_name || <em className="text-zinc-400">no workshop</em>}</span>
                 <span>Total: <span className="font-semibold">{fmt(ev.total_repair_cost)}</span></span>
                 <span className="text-zinc-500">Parts: {fmt(ev.parts_cost)} · Labour: {fmt(ev.labour_cost)}</span>
                 <span className="text-zinc-500">Vendor payable: {fmt(ev.vendor_outstanding)}/{fmt(ev.vendor_payable)}</span>
                 <span className="text-zinc-500">Mechanic payable: {fmt(ev.mechanic_outstanding)}/{fmt(ev.mechanic_payable)}</span>
                 <Link to={`/repairs/${ev.id}`} data-testid={`open-repair-${ev.id}`}
                   onClick={(e) => e.stopPropagation()}
                   className="ml-auto text-xs px-2 py-1 border rounded-sm hover:bg-zinc-950 hover:text-white">
                   Open
                 </Link>
               </summary>
               <div className="px-3 py-2 border-t bg-zinc-50 text-sm space-y-2">
                 {ev.description && <div><strong>Description:</strong> {ev.description}</div>}
                 <DrillTable title="Vendor Bills" rows={ev.vendor_bills} cols={[
                   ["bill_number", "Bill #"], ["vendor_name", "Vendor"],
                   ["bill_date", "Date"], ["bill_amount", "Amount", true],
                 ]} />
                 <DrillTable title="Mechanic Work Orders" rows={ev.mechanic_work_orders} cols={[
                   ["mechanic_name", "Mechanic"], ["work_date", "Date"],
                   ["amount", "Amount", true],
                 ]} />
                 <DrillTable title="Canonical Expenses (source of truth)" rows={ev.expenses} cols={[
                   ["category", "Category"], ["date", "Date"],
                   ["amount", "Amount", true], ["source_type", "Src"],
                 ]} />
               </div>
             </details>
           ))}
         </div>}
      </div>

      <p className="text-xs text-zinc-400" data-testid="source-note">
        Vehicle Cost reads canonical Expense (with legacy Trip fallback where a trip
        has no canonical materialisation). Repair total is DERIVED from Expenses only —
        Vendor Bill and Mechanic WO amounts are shown separately as payables and are
        never summed into cost.
      </p>
    </div>
  );
}

function Kpi({ label, value, testid }) {
  return (
    <div className="bg-white border rounded-lg p-4" data-testid={testid}>
      <div className="text-xs text-zinc-500 uppercase tracking-wide">{label}</div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
    </div>
  );
}

function DrillTable({ title, rows = [], cols }) {
  if (!rows || rows.length === 0) return null;
  return (
    <div>
      <div className="font-semibold text-xs uppercase tracking-wide text-zinc-500 mb-1">{title}</div>
      <table className="w-full text-xs border">
        <thead className="bg-zinc-100">
          <tr>{cols.map(([, label]) => <th key={label} className="text-left px-2 py-1">{label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.id || i} className="border-t">
              {cols.map(([k, , money]) =>
                <td key={k} className={"px-2 py-1 " + (money ? "text-right" : "")}>
                  {money ? `₹${Number(r[k] || 0).toLocaleString("en-IN")}` : (r[k] ?? "—")}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
