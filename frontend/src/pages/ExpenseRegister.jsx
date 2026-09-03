import React, { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { Plus } from "lucide-react";
import ExpenseForm from "@/pages/ExpenseForm";

/** Iter136 P0 · Expense Register — operator-facing view.
 * Reads GET /api/expenses (canonical). Vehicle Cost / Vendor / Mechanic
 * ledgers are unaffected — this page is a projection of Expense only.
 */
const PARTY_LABELS = {
  none: "—",
  cash: "Cash",
  vendor: "Vendor",
  mechanic: "Mechanic",
  supplier: "Supplier",
  driver: "Driver",
};

export default function ExpenseRegister() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = ["owner", "admin"].includes((user?.effective_role || "").toLowerCase());
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [category, setCategory] = useState("");
  const [vehicleId, setVehicleId] = useState("");
  const [partyType, setPartyType] = useState("");
  const [includeReversed, setIncludeReversed] = useState(false);
  const [drawer, setDrawer] = useState({ open: false, mode: "create", row: null });

  const params = useMemo(() => {
    const p = {};
    if (from) p.date_from = from;
    if (to) p.date_to = to;
    if (category) p.category = category;
    if (vehicleId) p.vehicle_id = vehicleId;
    if (partyType) p.party_type = partyType;
    if (includeReversed) p.include_reversed = true;
    return p;
  }, [from, to, category, vehicleId, partyType, includeReversed]);

  const list = useQuery({
    queryKey: ["expenses", "register", params],
    queryFn: async () => (await api.get("/expenses", { params })).data,
  });
  const vehicles = useQuery({
    queryKey: ["vehicles-lite"],
    queryFn: async () => (await api.get("/vehicles")).data,
    staleTime: 60_000,
  });

  const cancel = useMutation({
    mutationFn: async ({ id, reason }) =>
      (await api.delete(`/expenses/${id}`, { params: { reason } })).data,
    onSuccess: () => { toast.success("Expense cancelled"); qc.invalidateQueries({ queryKey: ["expenses"] }); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Cancel failed"),
  });

  const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const rows = list.data || [];
  const totalAmount = rows.reduce((s, r) => s + Number(r.amount || 0), 0);
  const reversedCount = rows.filter((r) => r.is_reversed).length;

  const doCancel = (row) => {
    const reason = window.prompt("Reason for cancellation (min 3 chars):");
    if (!reason || reason.trim().length < 3) { toast.error("Reason must be at least 3 characters"); return; }
    cancel.mutate({ id: row.id, reason: reason.trim() });
  };

  return (
    <div className="p-6 space-y-4" data-testid="expense-register">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-semibold">Expenses</h1>
        <div className="ml-auto">
          <button data-testid="new-expense-btn"
                  onClick={() => setDrawer({ open: true, mode: "create", row: null })}
                  className="inline-flex items-center gap-1 text-xs px-3 py-2 bg-zinc-950 text-white rounded-sm hover:bg-zinc-800">
            <Plus size={14} /> New Expense
          </button>
        </div>
      </div>

      <div className="bg-white border rounded-lg p-4 flex flex-wrap gap-3 items-end">
        <label className="text-sm">From <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="ml-2 border rounded px-2 py-1" data-testid="filter-from"/></label>
        <label className="text-sm">To   <input type="date" value={to}   onChange={(e) => setTo(e.target.value)}   className="ml-2 border rounded px-2 py-1" data-testid="filter-to"  /></label>
        <label className="text-sm">Category
          <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Any" className="ml-2 border rounded px-2 py-1 w-40" data-testid="filter-category"/>
        </label>
        <label className="text-sm">Vehicle
          <select value={vehicleId} onChange={(e) => setVehicleId(e.target.value)} className="ml-2 border rounded px-2 py-1" data-testid="filter-vehicle">
            <option value="">All</option>
            {(vehicles.data || []).map((v) => <option key={v.id} value={v.id}>{v.vehicle_number}</option>)}
          </select>
        </label>
        <label className="text-sm">Party
          <select value={partyType} onChange={(e) => setPartyType(e.target.value)} className="ml-2 border rounded px-2 py-1" data-testid="filter-party-type">
            <option value="">All</option>
            <option value="vendor">Vendor</option>
            <option value="mechanic">Mechanic</option>
            <option value="supplier">Supplier</option>
            <option value="driver">Driver</option>
            <option value="cash">Cash</option>
            <option value="none">None</option>
          </select>
        </label>
        <label className="text-sm flex items-center gap-1">
          <input type="checkbox" checked={includeReversed} onChange={(e) => setIncludeReversed(e.target.checked)} data-testid="filter-reversed"/> Show reversed
        </label>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <Kpi label="Rows" value={rows.length} testid="kpi-count"/>
        <Kpi label="Total Amount" value={fmt(totalAmount)} testid="kpi-total"/>
        <Kpi label="Reversed" value={reversedCount} testid="kpi-reversed"/>
      </div>

      <div className="bg-white border rounded-lg p-4 overflow-x-auto" data-testid="expense-table">
        {list.isLoading ? <div>Loading…</div> :
         rows.length === 0 ? <div className="text-zinc-400">No expenses.</div> :
         <table className="w-full text-sm">
           <thead className="bg-zinc-50 text-left">
             <tr>
               <th className="py-2 px-2">Date</th>
               <th className="py-2 px-2">Category</th>
               <th className="py-2 px-2">Description</th>
               <th className="py-2 px-2">Vehicle</th>
               <th className="py-2 px-2">Trip</th>
               <th className="py-2 px-2">Party</th>
               <th className="py-2 px-2">Ref</th>
               <th className="py-2 px-2 text-right">Amount</th>
               <th className="py-2 px-2">Status</th>
               <th className="py-2 px-2 text-right">Actions</th>
             </tr>
           </thead>
           <tbody>
             {rows.map((r, i) => (
               <tr key={r.id} className={"border-t " + (r.is_reversed ? "opacity-50 line-through" : "")} data-testid={`expense-row-${i}`}>
                 <td className="py-2 px-2 whitespace-nowrap">{r.date}</td>
                 <td className="py-2 px-2">{r.category}</td>
                 <td className="py-2 px-2">{r.narration || r.remarks || "—"}</td>
                 <td className="py-2 px-2 whitespace-nowrap" data-testid={`row-vehicle-${i}`}>
                   {r.vehicle_id && r.vehicle_number ? (
                     <Link to={`/vehicles/${r.vehicle_id}/cost`} className="text-indigo-700 hover:underline font-mono text-xs" data-testid={`row-vehicle-link-${r.vehicle_id}`}>
                       {r.vehicle_number}
                     </Link>
                   ) : <span className="text-zinc-400 text-xs">—</span>}
                 </td>
                 <td className="py-2 px-2 font-mono text-xs">{r.trip_id ? <Link to={`/trips/${r.trip_id}/view`} className="text-indigo-700 hover:underline">{r.trip_id.slice(-6)}</Link> : "—"}</td>
                 <td className="py-2 px-2">{r.party_name ? r.party_name : PARTY_LABELS[r.party_type] || "—"}</td>
                 <td className="py-2 px-2 font-mono text-xs">{r.vendor_bill_id || r.mechanic_work_order_id || r.repair_event_id || "—"}</td>
                 <td className="py-2 px-2 text-right tabular-nums">{fmt(r.amount)}</td>
                 <td className="py-2 px-2 text-xs">
                   {r.is_reversed ? <span className="text-rose-700">Reversed</span> :
                    r.reversal_of ? <span className="text-amber-700">Correction</span> :
                    <span className="text-emerald-700">Active</span>}
                 </td>
                 <td className="py-2 px-2 text-right space-x-1">
                   {!r.is_reversed && (
                     <button className="text-xs px-2 py-1 border rounded hover:bg-zinc-950 hover:text-white"
                             onClick={() => setDrawer({ open: true, mode: "edit", row: r })}
                             data-testid={`edit-btn-${r.id}`}>Edit</button>
                   )}
                   {isAdmin && !r.is_reversed && (
                     <button className="text-xs px-2 py-1 border rounded hover:bg-rose-700 hover:text-white"
                             onClick={() => doCancel(r)}
                             data-testid={`cancel-btn-${r.id}`}>Cancel</button>
                   )}
                 </td>
               </tr>
             ))}
           </tbody>
         </table>}
      </div>

      <p className="text-xs text-zinc-400">
        Expense is the canonical cost source. Vendor and Mechanic ledgers derive from Bills / Work Orders + Payments only — they are NOT affected by standalone expenses recorded here.
      </p>

      {drawer.open && (
        <ExpenseForm
          mode={drawer.mode}
          row={drawer.row}
          vehicles={vehicles.data || []}
          onClose={() => setDrawer({ open: false, mode: "create", row: null })}
          onSaved={() => { qc.invalidateQueries({ queryKey: ["expenses"] }); setDrawer({ open: false, mode: "create", row: null }); }}
        />
      )}
    </div>
  );
}

function Kpi({ label, value, testid }) {
  return (
    <div className="bg-white border rounded-lg p-4" data-testid={testid}>
      <div className="text-xs text-zinc-500 uppercase">{label}</div>
      <div className="text-2xl font-semibold mt-1 tabular-nums">{value}</div>
    </div>
  );
}
