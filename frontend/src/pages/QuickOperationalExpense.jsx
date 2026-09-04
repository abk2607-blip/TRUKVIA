import React, { useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/api";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Plus, Trash2, Save } from "lucide-react";

/** Iter139 P0 · Quick Operational Expense — single-point daily entry.
 *  One Date + One Category + N (vehicle, amount) rows → N canonical Expense rows
 *  via POST /api/expenses/bulk-operational. Zero touch to Iter136 register.
 */
const CATEGORIES = [
  "Toll", "Diesel", "Parking", "Batta", "Driver Batta",
  "Loading Charges", "Unloading Charges", "Weighment",
  "Detention", "Cleaning", "Driver Food", "AdBlue",
];
const SUPPLIER_MODES = [
  { value: "supplier_settlement_adjustment", label: "Supplier Adjustment (recovery)" },
  { value: "company_borne", label: "Company Borne (P&L)" },
];
const rid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36);

export default function QuickOperationalExpense() {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [category, setCategory] = useState("Toll");
  const [tripId, setTripId] = useState("");
  const [rows, setRows] = useState(() => [{ id: rid(), vehicle_id: "", amount: "", remarks: "", supplier_settlement_mode: "" }]);
  const idemKey = useRef(`qob-${today}-${rid()}`);

  const vehiclesQ = useQuery({
    queryKey: ["vehicles", "active"],
    queryFn: async () => (await api.get("/vehicles", { params: { active_only: true } })).data,
    staleTime: 60_000,
  });
  const vehicles = vehiclesQ.data || [];
  const vehById = useMemo(() => Object.fromEntries(vehicles.map((v) => [v.id, v])), [vehicles]);

  const vehicleOptions = useMemo(() => vehicles.map((v) => ({
    value: v.id, label: v.vehicle_number || v.id,
    secondary: (v.vehicle_type || "").toLowerCase() === "supplier"
      ? `Supplier · ${v.supplier_name || v.owner_name || ""}` : (v.owner_name || ""),
    keywords: [v.vehicle_number, v.owner_name, v.supplier_name, v.make_model].filter(Boolean),
  })), [vehicles]);
  const categoryOptions = CATEGORIES.map((c) => ({ value: c, label: c }));

  const addRow = () => setRows((r) => [...r, { id: rid(), vehicle_id: "", amount: "", remarks: "", supplier_settlement_mode: "" }]);
  const removeRow = (id) => setRows((r) => (r.length <= 1 ? r : r.filter((x) => x.id !== id)));
  const patchRow = (id, patch) => setRows((r) => r.map((x) => (x.id === id ? { ...x, ...patch } : x)));

  const save = useMutation({
    mutationFn: async () => {
      const entries = rows.map((r) => ({
        client_row_id: r.id, vehicle_id: r.vehicle_id,
        amount: parseFloat(r.amount) || 0, remarks: r.remarks || "",
        supplier_settlement_mode: r.supplier_settlement_mode || "",
      }));
      const body = { date, category, trip_id: tripId || "", entries };
      const { data } = await api.post("/expenses/bulk-operational", body, {
        headers: { "Idempotency-Key": idemKey.current },
      });
      return data;
    },
    onSuccess: (res) => {
      const c = res.created || 0, d = res.duplicate || 0, f = res.failed || 0;
      toast.success(`${c} created · ${d} duplicate · ${f} failed`);
      // Clear only created rows; keep failed rows with an error hint.
      const errorByRow = {};
      for (const r of res.results || []) if (r.status === "failed") errorByRow[r.client_row_id] = r.error?.detail || "Failed";
      const failedRows = rows.filter((r) => errorByRow[r.id]).map((r) => ({ ...r, __error: errorByRow[r.id] }));
      if (failedRows.length === 0) {
        setRows([{ id: rid(), vehicle_id: "", amount: "", remarks: "", supplier_settlement_mode: "" }]);
      } else {
        setRows(failedRows);
      }
      // Fresh idem key for the next submission (retry uses same key).
      idemKey.current = `qob-${date}-${rid()}`;
    },
    onError: (err) => toast.error(err?.response?.data?.detail || "Save failed"),
  });

  const totalRows = rows.length;
  const totalAmount = rows.reduce((s, r) => s + (parseFloat(r.amount) || 0), 0);

  return (
    <div className="p-6 max-w-5xl" data-testid="quick-expense-page">
      <div className="flex items-baseline justify-between mb-6">
        <h1 className="text-2xl font-semibold">Quick Operational Expense</h1>
        <div className="text-xs text-zinc-500">Enter once → reflects in Vehicle Cost, Trip Cost, Expense Register automatically.</div>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-4">
        <label className="text-sm">
          <div className="text-zinc-600 mb-1">Date</div>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
                 className="w-full border rounded px-2 py-1" data-testid="quick-expense-date"/>
        </label>
        <label className="text-sm">
          <div className="text-zinc-600 mb-1">Category</div>
          <SearchableSelect testId="quick-expense-category" placeholder="Search category…"
            emptyText="No categories" allowClear={false}
            value={category} onChange={setCategory} options={categoryOptions}/>
        </label>
        <label className="text-sm">
          <div className="text-zinc-600 mb-1">Trip ID (optional)</div>
          <input value={tripId} onChange={(e) => setTripId(e.target.value)} placeholder="trip_..."
                 className="w-full border rounded px-2 py-1 font-mono text-xs" data-testid="quick-expense-trip"/>
        </label>
      </div>

      <div className="border rounded overflow-hidden mb-4">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 text-zinc-600 text-xs uppercase">
            <tr>
              <th className="px-3 py-2 text-left w-[42%]">Vehicle</th>
              <th className="px-3 py-2 text-right w-[15%]">Amount ₹</th>
              <th className="px-3 py-2 text-left">Remarks / Supplier Mode</th>
              <th className="px-3 py-2 w-[40px]"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const veh = vehById[r.vehicle_id];
              const isSupplier = veh && (veh.vehicle_type || "").toLowerCase() === "supplier";
              return (
                <tr key={r.id} className="border-t align-top" data-testid={`quick-expense-row-${i}`}>
                  <td className="px-3 py-2">
                    <SearchableSelect testId={`quick-expense-row-${i}-vehicle`} placeholder="Search vehicle…"
                      emptyText="No vehicles" allowClear
                      value={r.vehicle_id} onChange={(v) => patchRow(r.id, { vehicle_id: v })}
                      options={vehicleOptions}/>
                    {r.__error && <div className="text-xs text-red-600 mt-1">⚠ {r.__error}</div>}
                  </td>
                  <td className="px-3 py-2">
                    <input type="number" min="0" step="0.01" value={r.amount}
                           onChange={(e) => patchRow(r.id, { amount: e.target.value })}
                           className="w-full border rounded px-2 py-1 text-right tabular-nums"
                           data-testid={`quick-expense-row-${i}-amount`}/>
                  </td>
                  <td className="px-3 py-2">
                    <input value={r.remarks} onChange={(e) => patchRow(r.id, { remarks: e.target.value })}
                           placeholder="optional remarks"
                           className="w-full border rounded px-2 py-1 mb-1"
                           data-testid={`quick-expense-row-${i}-remarks`}/>
                    {isSupplier && (
                      <select value={r.supplier_settlement_mode}
                              onChange={(e) => patchRow(r.id, { supplier_settlement_mode: e.target.value })}
                              className="w-full border rounded px-2 py-1 text-xs"
                              data-testid={`quick-expense-row-${i}-supplier-mode`}>
                        <option value="">— Settlement Mode (required) —</option>
                        {SUPPLIER_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                      </select>
                    )}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <button onClick={() => removeRow(r.id)} disabled={rows.length <= 1}
                            className="text-zinc-400 hover:text-red-600 disabled:opacity-30"
                            data-testid={`quick-expense-row-${i}-remove`}
                            title="Remove row">
                      <Trash2 size={14}/>
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between mb-6">
        <button onClick={addRow} className="text-sm text-zinc-700 hover:text-zinc-900 inline-flex items-center gap-1"
                data-testid="quick-expense-add-row">
          <Plus size={14}/> Add Row
        </button>
        <div className="text-xs text-zinc-500">
          {totalRows} row{totalRows !== 1 ? "s" : ""} · Total: ₹ <span className="tabular-nums">{totalAmount.toFixed(2)}</span>
        </div>
      </div>

      <div className="flex justify-end gap-2">
        <button onClick={() => save.mutate()} disabled={save.isPending}
                className="inline-flex items-center gap-1 bg-zinc-900 text-white px-4 py-2 rounded disabled:opacity-40"
                data-testid="quick-expense-save">
          <Save size={14}/> {save.isPending ? "Saving…" : `Save ${totalRows} ${totalRows === 1 ? "Entry" : "Entries"}`}
        </button>
      </div>
    </div>
  );
}
