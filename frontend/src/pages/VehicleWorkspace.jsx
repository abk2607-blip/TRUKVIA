/** Iter141 P0 · Vehicle Workspace — read/projection surface only.
 *  Reads:
 *    GET /api/vehicles                       — for vehicle identity
 *    GET /api/vehicles/{vid}/cost-summary    — canonical cost + rows[] + repair_total + trip_linked_total
 *    GET /api/vehicles/{vid}/repair-history  — repair events + derived totals
 *  Writes: NONE.
 *  No new schema, no new collection, no accounting change. Cost = canonical
 *  Expense.amount only. Repair Cost = Σ Expense.amount (never Bill+WO+Expense).
 *  Bundle stamp: v141-p0.
 */
import React, { useMemo, useState } from "react";
import { useParams, Link, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";

const fmt = (n) => {
  const x = Number(n) || 0;
  if (x === 0) return "—";
  return "₹" + x.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};
const fmtDate = (d) => d || "—";

export default function VehicleWorkspace() {
  const { vid } = useParams();
  const loc = useLocation();
  const navigate = useNavigate();
  const initTab = new URLSearchParams(loc.search).get("tab") || "overview";
  const [tab, setTab] = useState(initTab);
  const today = new Date().toISOString().slice(0, 10);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [cat, setCat] = useState("");

  const vehicleQ = useQuery({
    queryKey: ["vehicle", vid],
    queryFn: async () => (await api.get("/vehicles")).data.find((x) => x.id === vid) || null,
    enabled: !!vid,
    staleTime: 30_000,
  });
  const vehicle = vehicleQ.data;

  const params = useMemo(() => {
    const p = {};
    if (from) p.from = from;
    if (to) p.to = to;
    if (cat) p.category = cat;
    return p;
  }, [from, to, cat]);

  const costQ = useQuery({
    queryKey: ["vehicle-cost-summary", vid, params],
    queryFn: async () => (await api.get(`/vehicles/${vid}/cost-summary`, { params })).data,
    enabled: !!vid,
  });
  const cost = costQ.data;

  const repairsQ = useQuery({
    queryKey: ["vehicle-repair-history", vid, from, to],
    queryFn: async () => (await api.get(`/vehicles/${vid}/repair-history`, {
      params: { ...(from ? { from } : {}), ...(to ? { to } : {}) },
    })).data,
    enabled: !!vid && tab === "repairs",
  });
  const repairs = repairsQ.data;

  const categories = useMemo(() => {
    const s = new Set(["Toll", "Diesel", "Parking", "Batta"]);
    (cost?.by_category || []).forEach((c) => s.add(c.category));
    return Array.from(s);
  }, [cost]);

  const rows = cost?.rows || [];

  if (vehicleQ.isLoading) return <div className="p-6 text-zinc-500" data-testid="vw-loading">Loading vehicle…</div>;
  if (!vehicle) return <div className="p-6 text-rose-600" data-testid="vw-not-found">Vehicle not found.</div>;

  const isSupplier = (vehicle.vehicle_type || "").toLowerCase() === "supplier";

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6" data-testid="vehicle-workspace">
      {/* HEADER */}
      <div className="bg-white border rounded-lg p-4" data-testid="vw-header">
        <div className="flex items-start gap-4 flex-wrap">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-zinc-400">Vehicle</div>
            <h1 className="text-2xl font-semibold font-mono" data-testid="vw-vehicle-number">
              {vehicle.vehicle_number}
            </h1>
            <div className="text-xs text-zinc-500 mt-1 flex flex-wrap gap-3">
              <span className={"inline-flex items-center gap-1 text-[11px] uppercase font-semibold " +
                    (isSupplier ? "text-amber-700" : "text-emerald-700")}
                    data-testid="vw-vehicle-type">
                {isSupplier ? "Supplier-owned" : "Company-owned"}
              </span>
              <span className={"inline-flex items-center gap-1 text-[11px] uppercase font-semibold " +
                    (vehicle.is_active !== false ? "text-emerald-700" : "text-zinc-500")}
                    data-testid="vw-active-status">
                {vehicle.is_active !== false ? "Active" : "Inactive"}
              </span>
              {isSupplier ? (
                <span className="text-zinc-600" data-testid="vw-supplier-context">
                  Supplier: <b>{vehicle.supplier_name || vehicle.supplier_id || "—"}</b>
                  {vehicle.supplier_mobile ? ` · ${vehicle.supplier_mobile}` : ""}
                </span>
              ) : (
                <span className="text-zinc-600" data-testid="vw-owner-context">
                  Owner: <b>{vehicle.owner_name || "—"}</b>
                  {vehicle.owner_phone ? ` · ${vehicle.owner_phone}` : ""}
                </span>
              )}
              {vehicle.make_model && <span className="text-zinc-600">Make/Model: {vehicle.make_model}</span>}
              {vehicle.capacity_tons > 0 && <span className="text-zinc-600">Capacity: {vehicle.capacity_tons} T</span>}
            </div>
            {(vehicle.rc_expiry || vehicle.fc_expiry || vehicle.insurance_expiry || vehicle.permit_expiry || vehicle.puc_expiry) && (
              <div className="text-[11px] text-zinc-500 mt-2 flex flex-wrap gap-3" data-testid="vw-expiries">
                {vehicle.rc_expiry && <span>RC: {fmtDate(vehicle.rc_expiry)}</span>}
                {vehicle.fc_expiry && <span>FC: {fmtDate(vehicle.fc_expiry)}</span>}
                {vehicle.insurance_expiry && <span>Insurance: {fmtDate(vehicle.insurance_expiry)}</span>}
                {vehicle.permit_expiry && <span>Permit: {fmtDate(vehicle.permit_expiry)}</span>}
                {vehicle.puc_expiry && <span>PUC: {fmtDate(vehicle.puc_expiry)}</span>}
              </div>
            )}
          </div>
          <div className="ml-auto flex flex-col gap-2 items-end">
            <span className="text-[10px] text-zinc-300 uppercase" data-testid="vw-version">v141-p0</span>
            <Link to={`/vehicles/${vid}/cost`}
                  className="text-xs text-indigo-700 hover:underline"
                  data-testid="vw-cost-deep-link">
              Open classic Vehicle Cost report →
            </Link>
            <Link to={`/vehicles/${vid}/repairs/new`}
                  className="text-xs text-indigo-700 hover:underline"
                  data-testid="vw-new-repair">
              + New Repair
            </Link>
          </div>
        </div>
      </div>

      {/* FILTERS · shared across Expenses / Overview / Repairs (existing server semantics) */}
      <div className="bg-white border rounded-lg p-3 flex flex-wrap items-end gap-3" data-testid="vw-filters">
        <label className="text-xs">From
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)}
                 className="block border rounded px-2 py-1 mt-0.5"
                 data-testid="vw-filter-from"/>
        </label>
        <label className="text-xs">To
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)}
                 className="block border rounded px-2 py-1 mt-0.5"
                 data-testid="vw-filter-to"/>
        </label>
        <label className="text-xs">Category
          <select value={cat} onChange={(e) => setCat(e.target.value)}
                  className="block border rounded px-2 py-1 mt-0.5"
                  data-testid="vw-filter-category">
            <option value="">All categories</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <button onClick={() => { setFrom(""); setTo(""); setCat(""); }}
                className="text-xs px-3 py-1.5 border rounded"
                data-testid="vw-filter-clear">Clear</button>
        <span className="ml-auto text-xs text-zinc-500">
          {cost ? `${cost.expense_count} rows · ${cost.from || "all"} → ${cost.to || "all"}` : ""}
        </span>
      </div>

      {/* KPI TILES · derived from existing cost-summary response */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="vw-kpis">
        <Kpi label="Total Vehicle Cost" value={fmt(cost?.total_cost)}
             testId="vw-kpi-total"/>
        <Kpi label="Repair Cost" value={fmt(cost?.repair_total)}
             testId="vw-kpi-repair"/>
        <Kpi label="Operational Expense" value={fmt(cost?.non_trip_total)}
             testId="vw-kpi-operational"
             hint="Non-trip canonical Expense (Quick Op + Non-Trip)"/>
        <Kpi label="Trip-linked Cost" value={fmt(cost?.trip_linked_total)}
             testId="vw-kpi-trip"/>
      </div>

      {/* TAB BAR */}
      <div className="flex border-b" data-testid="vw-tabs">
        {[
          { id: "overview", label: "Overview" },
          { id: "expenses", label: "Expenses" },
          { id: "repairs",  label: "Repairs" },
          { id: "reports",  label: "Reports" },
        ].map((t) => (
          <button key={t.id}
                  onClick={() => { setTab(t.id); navigate(`/vehicles/${vid}?tab=${t.id}`, { replace: true }); }}
                  className={"px-4 py-2 text-sm border-b-2 -mb-px " +
                             (tab === t.id ? "border-zinc-900 text-zinc-900 font-semibold"
                                            : "border-transparent text-zinc-500 hover:text-zinc-800")}
                  data-testid={`vw-tab-${t.id}`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* TAB CONTENT */}
      {tab === "overview" && (
        <OverviewTab cost={cost} loading={costQ.isLoading} vid={vid}/>
      )}
      {tab === "expenses" && (
        <ExpensesTab cost={cost} loading={costQ.isLoading}/>
      )}
      {tab === "repairs" && (
        <RepairsTab data={repairs} loading={repairsQ.isLoading} vid={vid}/>
      )}
      {tab === "reports" && (
        <div className="bg-white border rounded-lg p-8 text-center text-zinc-500"
             data-testid="vw-reports-placeholder">
          <div className="text-sm font-semibold uppercase tracking-wider text-zinc-700 mb-2">
            Vehicle Reports
          </div>
          <div className="text-xs">Coming in the next release.</div>
        </div>
      )}
    </div>
  );
}

function Kpi({ label, value, testId, hint }) {
  return (
    <div className="bg-white border rounded-lg p-4" data-testid={testId}>
      <div className="text-[11px] uppercase tracking-wider text-zinc-400">{label}</div>
      <div className="text-lg font-semibold tabular-nums mt-0.5">{value}</div>
      {hint && <div className="text-[10px] text-zinc-400 mt-0.5">{hint}</div>}
    </div>
  );
}

function OverviewTab({ cost, loading, vid }) {
  if (loading) return <div className="text-zinc-400 text-sm">Loading…</div>;
  const byCat = cost?.by_category || [];
  const byMon = cost?.by_month || [];
  return (
    <div className="grid md:grid-cols-2 gap-4" data-testid="vw-overview">
      <div className="bg-white border rounded-lg p-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-zinc-600 mb-3">
          Category breakdown
        </div>
        {byCat.length === 0 ? (
          <div className="text-zinc-400 text-sm">No expenses in this range.</div>
        ) : (
          <ul className="space-y-1.5">
            {byCat.slice(0, 8).map((c) => (
              <li key={c.category} className="flex justify-between text-sm"
                  data-testid={`vw-cat-${c.category}`}>
                <span>{c.category}</span>
                <span className="tabular-nums">{fmt(c.amount)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="bg-white border rounded-lg p-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-zinc-600 mb-3">
          Month-wise cost
        </div>
        {byMon.length === 0 ? (
          <div className="text-zinc-400 text-sm">No expenses in this range.</div>
        ) : (
          <ul className="space-y-1.5">
            {byMon.slice(-8).map((m) => (
              <li key={m.month} className="flex justify-between text-sm">
                <span>{m.month}</span>
                <span className="tabular-nums">{fmt(m.amount)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function ExpensesTab({ cost, loading }) {
  if (loading) return <div className="text-zinc-400 text-sm" data-testid="vw-expenses-loading">Loading…</div>;
  const rows = cost?.rows || [];
  return (
    <div className="bg-white border rounded-lg p-4" data-testid="vw-expenses">
      <div className="flex items-center gap-3 mb-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-zinc-600">
          Expenses ({cost?.expense_count || 0})
        </div>
        <div className="ml-auto text-xs text-zinc-500" data-testid="vw-expenses-total">
          Filtered total: <b className="tabular-nums text-zinc-900">{fmt(cost?.total_cost)}</b>
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="text-zinc-400 text-sm" data-testid="vw-expenses-empty">
          No expenses in this range.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50">
              <tr className="text-left">
                <th className="py-2 px-2">Date</th>
                <th className="py-2 px-2">Category</th>
                <th className="py-2 px-2">Description</th>
                <th className="py-2 px-2">Vendor</th>
                <th className="py-2 px-2">Trip / Repair</th>
                <th className="py-2 px-2 text-right">Amount</th>
                <th className="py-2 px-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.id || i} className="border-t" data-testid={`vw-expense-row-${i}`}>
                  <td className="py-2 px-2 whitespace-nowrap">{r.date}</td>
                  <td className="py-2 px-2">{r.category}</td>
                  <td className="py-2 px-2 text-zinc-700 text-xs">
                    {r.narration || r.remarks || "—"}
                  </td>
                  <td className="py-2 px-2 text-xs">
                    {r.party_type === "vendor"
                      ? <span data-testid={`vw-expense-vendor-${i}`}>{r.party_name || "—"}</span>
                      : <span className="text-zinc-400">—</span>}
                  </td>
                  <td className="py-2 px-2 text-xs text-zinc-500">
                    {r.repair_event_id ? "repair" : (r.trip_id ? "trip" : (r.source_type || ""))}
                  </td>
                  <td className="py-2 px-2 text-right tabular-nums"
                      data-testid={`vw-expense-amount-${i}`}>{fmt(r.amount)}</td>
                  <td className="py-2 px-2 text-right text-xs">
                    {r.source_type === "quick_op" ? (
                      <Link to="/expenses/quick"
                            className="text-indigo-700 hover:underline"
                            data-testid={`vw-expense-edit-${i}`}
                            title="Edit / Cancel via Today's Entries (Iter140)">
                        Edit in Quick Op →
                      </Link>
                    ) : (
                      <span className="text-zinc-400">read-only</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t bg-zinc-50">
                <td colSpan={5} className="py-2 px-2 text-right font-semibold">Total</td>
                <td className="py-2 px-2 text-right tabular-nums font-semibold"
                    data-testid="vw-expenses-total-cell">{fmt(cost?.total_cost)}</td>
                <td/>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      <p className="mt-3 text-[11px] text-zinc-400">
        Source: canonical <code>Expense</code> via
        <code className="mx-1">GET /api/vehicles/{"{vid}"}/cost-summary</code>.
        Repair-linked and Trip-linked canonical Expenses are counted exactly once.
        Cancelled or reversed rows are automatically excluded.
      </p>
    </div>
  );
}

function RepairsTab({ data, loading, vid }) {
  if (loading) return <div className="text-zinc-400 text-sm" data-testid="vw-repairs-loading">Loading…</div>;
  const events = data?.events || [];
  return (
    <div className="bg-white border rounded-lg p-4" data-testid="vw-repairs">
      <div className="flex items-center gap-3 mb-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-zinc-600">
          Repair History ({data?.count || 0})
        </div>
        <div className="ml-auto text-xs text-zinc-500" data-testid="vw-repairs-total">
          Total Repair Cost: <b className="tabular-nums text-zinc-900">{fmt(data?.total_repair_cost)}</b>
        </div>
      </div>
      {events.length === 0 ? (
        <div className="text-zinc-400 text-sm" data-testid="vw-repairs-empty">
          No repairs in this range.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50">
              <tr className="text-left">
                <th className="py-2 px-2">Date</th>
                <th className="py-2 px-2">Description</th>
                <th className="py-2 px-2">Workshop</th>
                <th className="py-2 px-2">Vendor Payable</th>
                <th className="py-2 px-2">Mechanic Payable</th>
                <th className="py-2 px-2 text-right">Repair Cost</th>
                <th className="py-2 px-2">Status</th>
                <th className="py-2 px-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev, i) => (
                <tr key={ev.id} className="border-t" data-testid={`vw-repair-row-${i}`}>
                  <td className="py-2 px-2 whitespace-nowrap">{ev.event_date}</td>
                  <td className="py-2 px-2 text-xs">{ev.description || "—"}</td>
                  <td className="py-2 px-2 text-xs">{ev.workshop_name || "—"}</td>
                  <td className="py-2 px-2 text-xs tabular-nums">{fmt(ev.vendor_payable)}</td>
                  <td className="py-2 px-2 text-xs tabular-nums">{fmt(ev.mechanic_payable)}</td>
                  <td className="py-2 px-2 text-right tabular-nums font-medium"
                      data-testid={`vw-repair-cost-${i}`}>{fmt(ev.total_repair_cost)}</td>
                  <td className="py-2 px-2 text-xs uppercase">{ev.status}</td>
                  <td className="py-2 px-2 text-right">
                    <Link to={`/vehicles/${vid}/repairs/new?rid=${ev.id}`}
                          className="text-xs text-indigo-700 hover:underline"
                          data-testid={`vw-repair-open-${i}`}>
                      Open →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t bg-zinc-50">
                <td colSpan={5} className="py-2 px-2 text-right font-semibold">Total</td>
                <td className="py-2 px-2 text-right tabular-nums font-semibold"
                    data-testid="vw-repairs-total-cell">{fmt(data?.total_repair_cost)}</td>
                <td colSpan={2}/>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      <p className="mt-3 text-[11px] text-zinc-400">
        Repair Cost = Σ canonical <code>Expense.amount</code> for that repair
        (never Bill+WO+Expense). Vendor / Mechanic payable columns come from
        the same <code>/repair-history</code> response for context only — they
        are the payable side and do <b>not</b> add to Vehicle Cost.
      </p>
    </div>
  );
}
