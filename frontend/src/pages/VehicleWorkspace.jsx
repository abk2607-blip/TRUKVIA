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

  // Iter143 P1 · Trip metadata join for Trip Cost tab.
  //
  // Large-data safety: the /api/trips endpoint caps at limit=2000. Rather
  // than fetching every trip on the vehicle (which would truncate for very
  // long histories), we derive the exact set of trip_ids that actually
  // appear in cost.rows[] and fetch metadata for ONLY those via the
  // endpoint's `ids=` parameter (see routers/trips.py:283-297 — bypasses
  // the 2000 cap because it fetches a specific list). This means the
  // request set is bounded by the number of trip-linked cost rows, not by
  // trip history depth. ONE request per tab open — no N+1.
  const tripIdsForCost = useMemo(() => {
    if (!cost || !Array.isArray(cost.rows)) return [];
    const s = new Set();
    for (const r of cost.rows) {
      if (r && r.trip_id && !r.repair_event_id) s.add(r.trip_id);
    }
    return Array.from(s);
  }, [cost]);

  const tripsQ = useQuery({
    queryKey: ["trips-by-ids", vid, tripIdsForCost.join(",")],
    queryFn: async () => {
      if (tripIdsForCost.length === 0) return [];
      // Chunk if the URL would get very long (very defensive — 500/chunk).
      const CHUNK = 500;
      const results = [];
      for (let i = 0; i < tripIdsForCost.length; i += CHUNK) {
        const slice = tripIdsForCost.slice(i, i + CHUNK);
        const { data } = await api.get("/trips", { params: { ids: slice.join(",") } });
        results.push(...(data || []));
      }
      return results;
    },
    enabled: !!vid && tab === "trip-cost" && tripIdsForCost.length >= 0,
    staleTime: 15_000,
  });
  const tripsMeta = tripsQ.data;

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
          { id: "overview",  label: "Overview" },
          { id: "expenses",  label: "Expenses" },
          { id: "trip-cost", label: "Trip Cost" },
          { id: "repairs",   label: "Repairs" },
          { id: "reports",   label: "Reports" },
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
      {tab === "trip-cost" && (
        <TripCostTab cost={cost}
                     costLoading={costQ.isLoading}
                     costError={costQ.isError}
                     tripsMeta={tripsMeta}
                     tripsLoading={tripsQ.isLoading}/>
      )}
      {tab === "repairs" && (
        <RepairsTab data={repairs} loading={repairsQ.isLoading} vid={vid}/>
      )}
      {tab === "reports" && (
        <div className="bg-white border rounded-lg p-8 text-center text-zinc-500"
             data-testid="vw-reports">
          <div className="text-sm font-semibold uppercase tracking-wider text-zinc-700 mb-1">
            Vehicle Reports
          </div>
          <div className="text-[11px] text-zinc-500 mb-4">
            Uses current workspace filters — From: <b>{from || "All"}</b> · To: <b>{to || "All"}</b> · Category: <b>{cat || "All"}</b>
          </div>
          <div className="flex justify-center gap-3">
            <a href={`${process.env.REACT_APP_BACKEND_URL}/api/vehicles/${vid}/cost-summary.pdf?${new URLSearchParams({...(from?{from}:{}),...(to?{to}:{}),...(cat?{category:cat}:{})}).toString()}`}
               target="_blank" rel="noreferrer"
               className="px-4 py-2 bg-zinc-900 text-white rounded text-sm hover:bg-zinc-800"
               data-testid="vw-download-pdf">Download PDF</a>
            <a href={`${process.env.REACT_APP_BACKEND_URL}/api/vehicles/${vid}/cost-summary.xlsx?${new URLSearchParams({...(from?{from}:{}),...(to?{to}:{}),...(cat?{category:cat}:{})}).toString()}`}
               target="_blank" rel="noreferrer"
               className="px-4 py-2 border border-zinc-900 text-zinc-900 rounded text-sm hover:bg-zinc-100"
               data-testid="vw-download-xlsx">Download Excel</a>
          </div>
          <div className="text-[10px] text-zinc-400 mt-4">v142-p0 · pure projection of cost-summary + repair-history</div>
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

/**
 * Iter143 P1 · Trip Cost tab.
 * Pure projection — reuses parent's cost-summary payload (authoritative cost
 * source) + a single /api/trips?vehicle_id=vid metadata query. NEVER re-sums
 * from Trip.total_expense / Trip.expenses / VendorBill / MechanicWO / supplier
 * payable. Zero backend change. Zero new endpoint. XOR safety inherited from
 * cost-summary rows[] (canonical XOR legacy_trip_fallback — never both).
 */
function TripCostTab({ cost, costLoading, costError, tripsMeta, tripsLoading }) {
  const trips = React.useMemo(() => {
    if (!cost) return [];
    const rows = (cost.rows || []).filter(
      (r) => r.trip_id && !r.repair_event_id
    );
    // Group by trip_id — O(n) single pass.
    const groups = new Map();
    for (const r of rows) {
      const tid = r.trip_id;
      let g = groups.get(tid);
      if (!g) {
        g = { trip_id: tid, total: 0, by_category: new Map(), rows: [], sources: new Set() };
        groups.set(tid, g);
      }
      const amt = Number(r.amount) || 0;
      g.total += amt;
      g.by_category.set(r.category, (g.by_category.get(r.category) || 0) + amt);
      g.rows.push(r);
      g.sources.add(r.source_type || "manual");
    }
    // Trip metadata map — O(m). Iter143 rule: never one request per trip.
    const metaMap = new Map();
    for (const t of tripsMeta || []) metaMap.set(t.id, t);
    // Materialise + hide zero-cost + attach meta.
    const list = [];
    for (const g of groups.values()) {
      const total = Math.round(g.total * 100) / 100;
      if (total <= 0) continue;                      // decision 3: hide zero-cost trips
      const meta = metaMap.get(g.trip_id) || null;
      list.push({
        trip_id: g.trip_id,
        meta,
        metaMissing: !meta,
        total,
        by_category: Array.from(g.by_category.entries())
          .map(([category, amount]) => ({
            category,
            amount: Math.round(amount * 100) / 100,
          }))
          .sort((a, b) => (b.amount - a.amount) || a.category.localeCompare(b.category)),
        source_kind: g.sources.has("legacy_trip_fallback") ? "legacy_fallback" : "canonical",
      });
    }
    // Sort: newest trip.date first (fallback = trip_id).
    list.sort((a, b) => {
      const da = a.meta?.date || "";
      const db = b.meta?.date || "";
      if (da !== db) return db.localeCompare(da);
      return a.trip_id.localeCompare(b.trip_id);
    });
    return list;
  }, [cost, tripsMeta]);

  if (costError) {
    return (
      <div className="bg-white border rounded-lg p-4 text-rose-600 text-sm"
           data-testid="vw-trip-cost-error">
        Unable to load Vehicle Cost — Trip Cost cannot be computed. Please retry.
      </div>
    );
  }
  if (costLoading) {
    return (
      <div className="text-zinc-400 text-sm" data-testid="vw-trip-cost-loading">
        Loading…
      </div>
    );
  }

  const displayedTotal = Math.round(
    trips.reduce((s, t) => s + t.total, 0) * 100
  ) / 100;
  const tripLinked = Math.round((Number(cost?.trip_linked_total) || 0) * 100) / 100;
  const nonTrip = Math.round((Number(cost?.non_trip_total) || 0) * 100) / 100;
  const vehicleTotal = Math.round((Number(cost?.total_cost) || 0) * 100) / 100;
  const reconciled = Math.abs(displayedTotal - tripLinked) < 0.01;

  return (
    <div className="bg-white border rounded-lg p-4" data-testid="vw-trip-cost">
      <div className="flex items-center gap-3 mb-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-zinc-600">
          Trip Cost ({trips.length})
        </div>
        {tripsLoading && (
          <span className="text-[11px] text-zinc-400" data-testid="vw-trip-cost-meta-loading">
            Loading trip metadata…
          </span>
        )}
        <div className="ml-auto text-xs text-zinc-500" data-testid="vw-trip-cost-total">
          Displayed trip total:{" "}
          <b className="tabular-nums text-zinc-900">{fmt(displayedTotal)}</b>
        </div>
      </div>

      {trips.length === 0 ? (
        <div className="text-zinc-400 text-sm" data-testid="vw-trip-cost-empty">
          No trip-linked costs for this vehicle in the selected period.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50">
              <tr className="text-left">
                <th className="py-2 px-2">Trip Date</th>
                <th className="py-2 px-2">Trip Ref</th>
                <th className="py-2 px-2">Customer</th>
                <th className="py-2 px-2">Route</th>
                <th className="py-2 px-2">Driver</th>
                <th className="py-2 px-2">Type</th>
                <th className="py-2 px-2">Categories</th>
                <th className="py-2 px-2 text-right">Trip Total</th>
                <th className="py-2 px-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {trips.map((t, i) => (
                <TripCostRow key={t.trip_id} row={t} idx={i}/>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t bg-zinc-50">
                <td colSpan={7} className="py-2 px-2 text-right font-semibold">
                  Σ Displayed Trip Costs
                </td>
                <td className="py-2 px-2 text-right tabular-nums font-semibold"
                    data-testid="vw-trip-cost-total-cell">
                  {fmt(displayedTotal)}
                </td>
                <td/>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {/* Reconciliation trust strip — never silently hides a mismatch */}
      <div
        className={
          "mt-3 rounded px-3 py-2 text-xs border " +
          (reconciled
            ? "bg-emerald-50 border-emerald-200 text-emerald-900"
            : "bg-rose-50 border-rose-300 text-rose-900 font-semibold")
        }
        data-testid="vw-trip-cost-reconciled"
        data-reconciled={reconciled ? "true" : "false"}
      >
        {reconciled ? (
          <>
            Trip-linked Costs (<span className="tabular-nums">{fmt(tripLinked)}</span>) +{" "}
            Non-trip Costs (<span className="tabular-nums">{fmt(nonTrip)}</span>) ={" "}
            Vehicle Total (<span className="tabular-nums">{fmt(vehicleTotal)}</span>) ✓
          </>
        ) : (
          <>
            ⚠ Reconciliation mismatch — displayed trip total{" "}
            <span className="tabular-nums">{fmt(displayedTotal)}</span> ≠
            trip-linked total{" "}
            <span className="tabular-nums">{fmt(tripLinked)}</span>. Please refresh
            or report this to support (never treat this as final).
          </>
        )}
      </div>

      <p className="mt-3 text-[11px] text-zinc-400">
        Source: <code>GET /api/vehicles/{"{vid}"}/cost-summary → rows[]</code>,
        grouped client-side by <code>trip_id</code>. Trip metadata joined once via{" "}
        <code>GET /api/trips?vehicle_id={"{vid}"}</code> — never per-trip.
        Supplier payable, VendorBill, MechanicWO amounts are never included here
        (they are the payable side, not cost).
      </p>
    </div>
  );
}

function TripCostRow({ row, idx }) {
  const m = row.meta || {};
  const isSupplier = (m.vehicle_type || "").toLowerCase() === "supplier";
  const trip_id_short = row.trip_id.length > 12
    ? row.trip_id.slice(0, 8) + "…" + row.trip_id.slice(-4)
    : row.trip_id;
  return (
    <tr className="border-t align-top"
        data-testid={`vw-trip-cost-row-${idx}`}
        data-trip-id={row.trip_id}
        data-source={row.source_kind}>
      <td className="py-2 px-2 whitespace-nowrap text-xs">
        {m.date || <span className="text-zinc-400" data-testid={`vw-trip-cost-row-${idx}-meta-missing`}>meta missing</span>}
      </td>
      <td className="py-2 px-2 text-xs font-mono">
        {row.metaMissing ? (
          <span title="Cost row references a trip not returned by /api/trips (out of date-range join, or trip since deleted). Cost is still counted; no silent drop.">
            {trip_id_short}
          </span>
        ) : (
          <Link to={`/trips/${row.trip_id}/view`}
                className="text-indigo-700 hover:underline"
                data-testid={`vw-trip-cost-row-${idx}-ref`}>
            {m.lr_number || trip_id_short}
          </Link>
        )}
      </td>
      <td className="py-2 px-2 text-xs">
        {isSupplier ? (m.supplier_name || "—") : (m.consignor_name || m.customer_id || "—")}
      </td>
      <td className="py-2 px-2 text-xs whitespace-nowrap">
        {(m.from_location || "—")}<span className="text-zinc-400 mx-1">→</span>{(m.to_location || "—")}
      </td>
      <td className="py-2 px-2 text-xs">{m.driver_name || m.lr_driver_name || "—"}</td>
      <td className="py-2 px-2">
        <span
          className={
            "text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded " +
            (isSupplier
              ? "bg-amber-100 text-amber-800"
              : "bg-emerald-100 text-emerald-800")
          }
          data-testid={`vw-trip-cost-row-${idx}-badge`}
        >
          {isSupplier ? "SUPPLIER" : "OWN"}
        </span>
        {isSupplier && m.supplier_name && (
          <div className="text-[10px] text-zinc-500 mt-0.5" title="Supplier">
            {m.supplier_name}
          </div>
        )}
      </td>
      <td className="py-2 px-2 text-xs">
        <div className="flex flex-wrap gap-1">
          {row.by_category.map((c) => (
            <span key={c.category}
                  className="inline-flex items-center gap-1 bg-zinc-100 border border-zinc-200 rounded px-1.5 py-0.5"
                  data-testid={`vw-trip-cost-row-${idx}-cat-${c.category}`}>
              <span className="text-zinc-700">{c.category}</span>
              <span className="tabular-nums text-zinc-900">{fmt(c.amount)}</span>
            </span>
          ))}
        </div>
        {row.source_kind === "legacy_fallback" && (
          <div className="text-[10px] text-amber-700 mt-1">
            legacy fallback (pre-canonical)
          </div>
        )}
      </td>
      <td className="py-2 px-2 text-right tabular-nums font-medium"
          data-testid={`vw-trip-cost-row-${idx}-total`}>
        {fmt(row.total)}
      </td>
      <td className="py-2 px-2 text-right whitespace-nowrap">
        <Link to={`/trips/${row.trip_id}/view`}
              className="text-xs text-indigo-700 hover:underline"
              data-testid={`vw-trip-cost-row-${idx}-open`}>
          Open Trip →
        </Link>
      </td>
    </tr>
  );
}
