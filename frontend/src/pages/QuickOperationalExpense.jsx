import React, { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/api";
import { SearchableSelect } from "@/components/ui/searchable-select";
import AsyncSearchableSelect from "@/components/AsyncSearchableSelect";
import { Plus, Trash2, Save, AlertTriangle, Pencil, X, Link2 } from "lucide-react";

/** Iter139 P0 · Quick Operational Expense — single-point daily entry.
 *  One Date + One Category + N (vehicle, amount) rows → N canonical Expense rows
 *  via POST /api/expenses/bulk-operational. Zero touch to Iter136 register.
 */
// Iter144 · Trip picker helpers.
function _tripToOption(t) {
  const trip_ref = (t.lr_number && t.lr_number.trim())
    ? t.lr_number.trim()
    : (t.id
        ? (t.id.length > 14 ? t.id.slice(0, 8) + "…" + t.id.slice(-4) : t.id)
        : "—");
  const vnum = t.vehicle_number || "—";
  const route = (t.from_location || t.to_location)
    ? `${t.from_location || "—"} → ${t.to_location || "—"}`
    : "—";
  const label = `${trip_ref} · ${vnum} · ${route}`;
  const isSup = (t.vehicle_type || "").toLowerCase() === "supplier";
  const meta = [
    isSup ? "SUPPLIER" : "OWN",
    t.driver_name || t.lr_driver_name || "",
    isSup && t.supplier_name ? `Supplier: ${t.supplier_name}` : "",
  ].filter(Boolean).join(" · ");
  return { value: t.id, label, meta, trip: t };
}

function TripHelperStrip({ date }) {
  // Small ping query — one row is enough to know the picker will have
  // something to show. Runs only when there's no active selection.
  const ping = useQuery({
    queryKey: ["trips-exist-for-date", date],
    queryFn: async () => (await api.get("/trips", { params: { date, limit: 1 } })).data,
    enabled: !!date,
    staleTime: 30_000,
  });
  const arr = ping.data || [];
  if (ping.isLoading) return null;
  if (arr.length === 0) {
    return (
      <div className="mt-1 text-[11px] text-amber-700"
           data-testid="quick-expense-trip-empty-hint">
        No active trips on this date. Save an expense without a Trip link or
        change the date.
      </div>
    );
  }
  return (
    <div className="mt-1 text-[11px] text-zinc-500"
         data-testid="quick-expense-trip-hint">
      Optional — link this batch to a trip on {date}. Vehicle auto-fills when
      a trip is selected.
    </div>
  );
}
const CATEGORIES = [
  "Toll", "Diesel", "Parking", "Batta", "Driver Batta",
  "Loading Charges", "Unloading Charges", "Weighment",
  "Detention", "Cleaning", "Driver Food", "AdBlue",
];
// Same alias table as services_quick_expense.py — must stay in sync.
const CATEGORY_ALIAS = { "Driver Batta": "Batta" };
const canon = (c) => CATEGORY_ALIAS[c] || c;
const SUPPLIER_MODES = [
  { value: "supplier_settlement_adjustment", label: "Supplier Adjustment (recovery)" },
  { value: "company_borne", label: "Company Borne (P&L)" },
];
const rid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
// Iter144 UAT-FIX · Robust numeric parse — handles trimmed strings, currency
// prefixes ("₹"), thousand separators (","), and locales that use "," as the
// decimal separator (e.g. some browser autofill / paste-from-Excel flows).
// Without this, `<input type="number">` .value can briefly be `""` while the
// DOM shows the typed text, producing amount = 0 while qty/rate look filled.
const _num = (v) => {
  if (v === null || v === undefined) return 0;
  if (typeof v === "number") return isFinite(v) ? v : 0;
  const s = String(v).replace(/[₹\s]/g, "").replace(/,/g, ".");
  // Strip everything after the first dot except digits (e.g. "34.20.5" → "34.20")
  const m = s.match(/^-?\d*(\.\d+)?/);
  const n = parseFloat(m ? m[0] : s);
  return isFinite(n) ? n : 0;
};
const eqAmount = (a, b) => Math.abs(_num(a) - _num(b)) < 0.005;
const fmt = (n) => `₹${_num(n).toFixed(2)}`;
const q2 = (n) => Math.round(_num(n) * 100) / 100;
// Iter139 UAT · Diesel rows derive amount from qty × rate; other categories keep typed amount.
const computedAmount = (row, cat) => cat === "Diesel"
  ? q2(_num(row.qty) * _num(row.rate))
  : _num(row.amount);
const dieselNarration = (row, filled_at) => {
  const qty = _num(row.qty), rate = _num(row.rate);
  const parts = [];
  if (qty > 0 && rate > 0) parts.push(`${qty}L @ ₹${rate.toFixed(2)}`);
  if (filled_at) parts.push(filled_at);
  if (row.vendor_name) parts.push(row.vendor_name);
  return parts.join(" · ");
};

export default function QuickOperationalExpense() {
  const today = new Date().toISOString().slice(0, 10);
  const qc = useQueryClient();
  const [date, setDate] = useState(today);
  const [category, setCategory] = useState("Toll");
  const [tripId, setTripId] = useState("");
  // Iter144 · Trip picker state. When a Trip is selected we lock every
  // row's Vehicle to the Trip's vehicle_id so the operator cannot pick a
  // vehicle that contradicts the Trip. Cleared automatically when the
  // Date changes (list stale) or when the user clears the picker.
  const [selectedTrip, setSelectedTrip] = useState(null); // { value, label, meta, trip }
  const tripLocked = !!selectedTrip;
  const [rows, setRows] = useState(() => [{ id: rid(), vehicle_id: "", amount: "", remarks: "", supplier_settlement_mode: "" }]);
  const idemKey = useRef(`qob-${today}-${rid()}`);
  // Iter140 · Edit / Cancel drawers for Recent Entries.
  const [editing, setEditing] = useState(null);   // { doc } — the canonical Expense being edited
  const [cancelling, setCancelling] = useState(null); // { doc, reason }

  const vehiclesQ = useQuery({
    queryKey: ["vehicles", "active"],
    queryFn: async () => (await api.get("/vehicles", { params: { active_only: true } })).data,
    staleTime: 60_000,
  });
  const vehicles = vehiclesQ.data || [];
  const vehById = useMemo(() => Object.fromEntries(vehicles.map((v) => [v.id, v])), [vehicles]);

  // Iter139 UAT #2 · Vendor master for Diesel selector (searchable).
  const vendorsQ = useQuery({
    queryKey: ["vendors", "active"],
    queryFn: async () => (await api.get("/vendors", { params: { active_only: true } })).data,
    staleTime: 60_000,
    enabled: category === "Diesel",
  });
  const vendors = vendorsQ.data || [];
  const vendorOptions = useMemo(() => vendors.map((v) => ({
    value: v.id,
    label: v.name || v.id,
    secondary: [v.city, v.mobile].filter(Boolean).join(" · "),
    keywords: [v.name, v.mobile, v.contact_person, v.city].filter(Boolean),
  })), [vendors]);

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
    mutationFn: async (rowsToSubmit) => {
      const isDiesel = category === "Diesel";
      const entries = rowsToSubmit.map((r) => {
        const amt = computedAmount(r, category);
        if (isDiesel) {
          // Iter139 UAT #2 · Send qty/rate/vendor_id — server is authoritative for amount + narration.
          // Iter144 UAT-FIX · Coerce qty/rate through _num() so locale/paste
          // edge cases can never send NaN, empty string, or comma-decimal
          // values to the server. Server-side AMOUNT_TAMPERED guard still
          // runs and stays authoritative.
          return {
            client_row_id: r.id, vehicle_id: r.vehicle_id,
            qty: _num(r.qty),
            rate: _num(r.rate),
            filled_at: r.filled_at || "",
            vendor_id: r.vendor_id || "",
            amount: amt, // sent for the server tamper-check only
            remarks: r.remarks || "",
            supplier_settlement_mode: r.supplier_settlement_mode || "",
          };
        }
        return {
          client_row_id: r.id, vehicle_id: r.vehicle_id,
          amount: amt, remarks: r.remarks || "",
          narration: "",
          supplier_settlement_mode: r.supplier_settlement_mode || "",
        };
      });
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
      // Iter140 · Refresh the Today's Entries strip so the just-saved rows show up.
      qc.invalidateQueries({ queryKey: ["quick-op-today", date] });
      // Iter145 P0 · Trip View reads canonical Expense live; invalidate so
      // the just-created/edited/cancelled row reflects immediately when the
      // user navigates back to /trips/{tripId}/view.
      if (tripId) {
        qc.invalidateQueries({ queryKey: ["trip-expenses-canonical", tripId] });
        qc.invalidateQueries({ queryKey: ["trip-view", tripId] });
      }
    },
    onError: (err) => toast.error(err?.response?.data?.detail || "Save failed"),
  });

  const totalRows = rows.length;
  const totalAmount = rows.reduce((s, r) => s + computedAmount(r, category), 0);
  const isDiesel = category === "Diesel";

  // Iter139 P0 · Exact-duplicate warning (UX only — no unique constraint).
  // Match keys: date + canonical(category) + vehicle_id + amount, active rows only.
  const [dupModal, setDupModal] = useState(null); // { rowsToSubmit, duplicates: [{row, existing?, inBatch?}] }
  const dupCheck = useMutation({
    mutationFn: async () => {
      const canonCat = canon(category);
      const readyRows = rows.filter(
        (r) => r.vehicle_id && computedAmount(r, category) > 0,
      );
      if (readyRows.length === 0) return { readyRows, duplicates: [] };
      // ── In-batch duplicates ────────────────────────────────────
      const seen = new Map();
      const inBatch = [];
      for (const r of readyRows) {
        const k = `${r.vehicle_id}|${computedAmount(r, category).toFixed(2)}`;
        if (seen.has(k)) inBatch.push({ row: r, firstRow: seen.get(k), source: "batch" });
        else seen.set(k, r);
      }
      // ── Existing-DB duplicates ─────────────────────────────────
      // One request per distinct vehicle_id for this date+canonical category
      // — batch-size ≤ 200, so ≤ 200 lightweight queries and typically far fewer.
      const distinctVids = [...new Set(readyRows.map((r) => r.vehicle_id))];
      const existingByVid = {};
      await Promise.all(distinctVids.map(async (vid) => {
        const { data } = await api.get("/expenses", { params: {
          vehicle_id: vid, category: canonCat, date_from: date, date_to: date,
        }});
        existingByVid[vid] = Array.isArray(data) ? data : [];
      }));
      const dupExisting = [];
      for (const r of readyRows) {
        const amt = computedAmount(r, category);
        const match = (existingByVid[r.vehicle_id] || []).find(
          (e) => eqAmount(e.amount, amt) && !e.is_reversed && !e.is_deleted,
        );
        if (match) dupExisting.push({ row: r, existing: match, source: "existing" });
      }
      return { readyRows, duplicates: [...dupExisting, ...inBatch] };
    },
    onSuccess: ({ readyRows, duplicates }) => {
      if (duplicates.length === 0) {
        save.mutate(readyRows);
        return;
      }
      setDupModal({ readyRows, duplicates });
    },
    onError: (err) => toast.error(err?.response?.data?.detail || "Duplicate check failed"),
  });

  const resolveDupModal = (choice) => {
    if (!dupModal) return;
    const { readyRows, duplicates } = dupModal;
    setDupModal(null);
    if (choice === "cancel_all") {
      // Skip every duplicated row; submit non-dup rows only.
      const dupIds = new Set(duplicates.map((d) => d.row.id));
      const keep = readyRows.filter((r) => !dupIds.has(r.id));
      if (keep.length === 0) { toast.info("All duplicate rows cancelled — nothing to save."); return; }
      save.mutate(keep);
    } else if (choice === "add_all") {
      save.mutate(readyRows);
    }
  };

  return (
    <div className="p-6 max-w-5xl" data-testid="quick-expense-page">
      <div className="flex items-baseline justify-between mb-6">
        <h1 className="text-2xl font-semibold">Quick Operational Expense</h1>
        <div className="text-xs text-zinc-500">Enter once → reflects in Vehicle Cost, Trip Cost, Expense Register automatically.</div>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-4">
        <label className="text-sm">
          <div className="text-zinc-600 mb-1">Date</div>
          <input type="date" value={date}
                 onChange={(e) => {
                   const newDate = e.target.value;
                   setDate(newDate);
                   // Iter144 · Trip list is date-scoped. Clear selection on
                   // date change so we never carry a stale trip across days.
                   if (selectedTrip) {
                     setSelectedTrip(null);
                     setTripId("");
                     toast.info("Trip cleared — different date selected.");
                   }
                 }}
                 className="w-full border rounded px-2 py-1" data-testid="quick-expense-date"/>
        </label>
        <label className="text-sm">
          <div className="text-zinc-600 mb-1">Category</div>
          <SearchableSelect testId="quick-expense-category" placeholder="Search category…"
            emptyText="No categories" allowClear={false}
            value={category} onChange={setCategory} options={categoryOptions}/>
        </label>
        <label className="text-sm" data-testid="quick-expense-trip-wrap">
          <div className="text-zinc-600 mb-1">Trip (Optional)</div>
          <AsyncSearchableSelect
            dataTestId="quick-expense-trip-picker"
            placeholder="Search Trip…"
            value={selectedTrip?.value || ""}
            selectedOption={selectedTrip}
            allowClear
            fetchOptions={async (q) => {
              if (!date) return [];
              const { data } = await api.get("/trips", {
                params: { date, ...(q ? { q } : {}), limit: 50 },
              });
              return (data || []).map(_tripToOption);
            }}
            onChange={(_val, opt) => {
              if (!opt) {
                // User cleared the picker — release the lock.
                setSelectedTrip(null);
                setTripId("");
                return;
              }
              const t = opt.trip || {};
              setSelectedTrip(opt);
              setTripId(t.id || "");
              // Auto-populate + lock Vehicle on every row (submission-level).
              if (t.vehicle_id) {
                setRows((rs) => rs.map((r) => ({ ...r, vehicle_id: t.vehicle_id })));
              }
            }}
          />
          {!selectedTrip && (
            <TripHelperStrip date={date}/>
          )}
        </label>
      </div>

      {selectedTrip && (
        <div className="mb-4 flex items-start gap-2 rounded border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs text-indigo-900"
             data-testid="quick-expense-trip-lock-notice">
          <Link2 size={14} className="mt-0.5 flex-shrink-0"/>
          <div className="flex-1">
            All rows below will be linked to <b>{selectedTrip.label}</b>.
            Vehicle is auto-selected from this trip and locked. Add rows to
            accumulate this trip's costs, or clear the trip to unlock.
          </div>
        </div>
      )}

      <div className="border rounded overflow-hidden mb-4">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 text-zinc-600 text-xs uppercase">
            <tr>
              <th className="px-3 py-2 text-left w-[42%]">Vehicle</th>
              <th className="px-3 py-2 text-right w-[22%]">{isDiesel ? "Qty × Rate → Amount ₹" : "Amount ₹"}</th>
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
                      emptyText="No vehicles" allowClear={!tripLocked}
                      disabled={tripLocked}
                      value={r.vehicle_id} onChange={(v) => patchRow(r.id, { vehicle_id: v })}
                      options={vehicleOptions}/>
                    {tripLocked && (
                      <div className="mt-1 text-[10px] text-indigo-700"
                           data-testid={`quick-expense-row-${i}-vehicle-locked`}>
                        Locked by Trip {selectedTrip.trip?.lr_number || selectedTrip.trip?.id || ""}
                      </div>
                    )}
                    {r.__error && <div className="text-xs text-red-600 mt-1">⚠ {r.__error}</div>}
                  </td>
                  <td className="px-3 py-2">
                    {isDiesel ? (
                      <div className="grid grid-cols-3 gap-1">
                        <input type="text" inputMode="decimal"
                               autoComplete="off"
                               value={r.qty ?? ""}
                               onChange={(e) => patchRow(r.id, { qty: e.target.value })}
                               placeholder="Qty L"
                               className="w-full border rounded px-2 py-1 text-right tabular-nums"
                               data-testid={`quick-expense-row-${i}-qty`}/>
                        <input type="text" inputMode="decimal"
                               autoComplete="off"
                               value={r.rate ?? ""}
                               onChange={(e) => patchRow(r.id, { rate: e.target.value })}
                               placeholder="₹/L"
                               className="w-full border rounded px-2 py-1 text-right tabular-nums"
                               data-testid={`quick-expense-row-${i}-rate`}/>
                        <input type="text" readOnly value={fmt(computedAmount(r, category))}
                               tabIndex={-1}
                               onKeyDown={(e) => e.preventDefault()}
                               onPaste={(e) => e.preventDefault()}
                               onCopy={(e) => e.preventDefault()}
                               className="w-full border rounded px-2 py-1 text-right tabular-nums bg-zinc-50 text-zinc-700 cursor-not-allowed select-none"
                               data-testid={`quick-expense-row-${i}-amount`}/>
                      </div>
                    ) : (
                      <input type="number" min="0" step="0.01" value={r.amount}
                             onChange={(e) => patchRow(r.id, { amount: e.target.value })}
                             className="w-full border rounded px-2 py-1 text-right tabular-nums"
                             data-testid={`quick-expense-row-${i}-amount`}/>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {isDiesel && (
                      <>
                        <input value={r.filled_at || ""}
                               onChange={(e) => patchRow(r.id, { filled_at: e.target.value })}
                               placeholder="Filled at (station / location) — optional"
                               className="w-full border rounded px-2 py-1 mb-1"
                               data-testid={`quick-expense-row-${i}-filled-at`}/>
                        <div className="mb-1">
                          <SearchableSelect
                            testId={`quick-expense-row-${i}-vendor`}
                            placeholder="Vendor (optional) — search master…"
                            emptyText="No vendors" allowClear
                            value={r.vendor_id || ""}
                            onChange={(v) => patchRow(r.id, { vendor_id: v })}
                            options={vendorOptions}/>
                        </div>
                      </>
                    )}
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
        <button onClick={() => dupCheck.mutate()} disabled={save.isPending || dupCheck.isPending}
                className="inline-flex items-center gap-1 bg-zinc-900 text-white px-4 py-2 rounded disabled:opacity-40"
                data-testid="quick-expense-save">
          <Save size={14}/> {save.isPending || dupCheck.isPending ? "Saving…" : `Save ${totalRows} ${totalRows === 1 ? "Entry" : "Entries"}`}
        </button>
      </div>

      {dupModal && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center pt-24" data-testid="duplicate-modal">
          <div className="bg-white rounded-lg shadow-xl w-[min(640px,92vw)] max-h-[80vh] overflow-auto">
            <div className="flex items-start gap-3 px-5 py-4 border-b bg-amber-50">
              <AlertTriangle className="text-amber-600 mt-0.5" size={20}/>
              <div>
                <div className="font-semibold text-amber-900">
                  {dupModal.duplicates.length === 1 ? "DUPLICATE RECORD FOUND"
                    : `${dupModal.duplicates.length} DUPLICATE RECORDS FOUND`}
                </div>
                <div className="text-xs text-amber-800 mt-1">
                  Same date, category, vehicle, and amount. You can cancel these rows or add them anyway.
                </div>
              </div>
            </div>
            <div className="px-5 py-3 space-y-3 text-sm">
              {dupModal.duplicates.map((d, i) => {
                const veh = vehById[d.row.vehicle_id];
                const vnum = veh?.vehicle_number || d.row.vehicle_id;
                const existing = d.existing;
                return (
                  <div key={i} className="border rounded p-3" data-testid={`duplicate-item-${i}`}>
                    <div className="text-xs uppercase tracking-wide text-zinc-500 mb-1">
                      {d.source === "batch" ? "Duplicate within this batch" : "Matches an existing record"}
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <div className="text-[11px] text-zinc-500 mb-0.5">Existing</div>
                        {existing ? (
                          <div>
                            <div className="font-medium">{fmt(existing.amount)}</div>
                            <div className="text-xs text-zinc-600">
                              {existing.date} · {existing.category} · {existing.vehicle_number}
                            </div>
                            {existing.narration && <div className="text-xs text-zinc-500 mt-0.5">{existing.narration}</div>}
                          </div>
                        ) : (
                          <div className="text-xs text-zinc-500">Another row above with same vehicle + amount.</div>
                        )}
                      </div>
                      <div>
                        <div className="text-[11px] text-zinc-500 mb-0.5">New Entry</div>
                        <div className="font-medium">{fmt(d.row.amount)}</div>
                        <div className="text-xs text-zinc-600">
                          {date} · {canon(category)} · {vnum}
                        </div>
                        {d.row.remarks && <div className="text-xs text-zinc-500 mt-0.5">{d.row.remarks}</div>}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="flex justify-end gap-2 px-5 py-3 border-t bg-zinc-50">
              <button onClick={() => resolveDupModal("cancel_all")}
                      className="px-3 py-1.5 border rounded text-sm"
                      data-testid="duplicate-modal-cancel">
                {dupModal.duplicates.length === 1 ? "Cancel" : "Cancel All Duplicates"}
              </button>
              <button onClick={() => resolveDupModal("add_all")}
                      className="px-3 py-1.5 bg-amber-600 text-white rounded text-sm"
                      data-testid="duplicate-modal-add-anyway">
                {dupModal.duplicates.length === 1 ? "Add Anyway" : "Add All Anyway"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Iter140 · Today's Entries strip · reads canonical Expense (source_type='quick_op'). */}
      <TodayEntries
        date={date}
        vendorsById={Object.fromEntries((vendors || []).map((v) => [v.id, v]))}
        onEdit={(doc) => setEditing({ doc })}
        onCancel={(doc) => setCancelling({ doc, reason: "" })}
      />

      {editing && (
        <EditExpenseModal
          doc={editing.doc}
          vendorOptions={vendorOptions}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            qc.invalidateQueries({ queryKey: ["quick-op-today"] });
            // Iter145 P0 · reflect edited amount on Trip View immediately.
            qc.invalidateQueries({ queryKey: ["trip-expenses-canonical"] });
            qc.invalidateQueries({ queryKey: ["trip-view"] });
            toast.success("Expense updated");
          }}
        />
      )}

      {cancelling && (
        <CancelExpenseModal
          doc={cancelling.doc}
          onClose={() => setCancelling(null)}
          onCancelled={() => {
            setCancelling(null);
            qc.invalidateQueries({ queryKey: ["quick-op-today"] });
            // Iter145 P0 · reflect cancelled row disappearance on Trip View.
            qc.invalidateQueries({ queryKey: ["trip-expenses-canonical"] });
            qc.invalidateQueries({ queryKey: ["trip-view"] });
            toast.success("Expense cancelled");
          }}
        />
      )}
    </div>
  );
}

// ── Iter140 · Today's Entries strip ────────────────────────────────────────
function TodayEntries({ date, vendorsById, onEdit, onCancel }) {
  const q = useQuery({
    queryKey: ["quick-op-today", date],
    queryFn: async () => (await api.get("/expenses", { params: {
      source_type: "quick_op", date_from: date, date_to: date,
    }})).data,
    staleTime: 5_000,
    enabled: !!date,
  });
  const rows = Array.isArray(q.data) ? q.data : [];
  const total = rows.reduce((s, r) => s + (Number(r.amount) || 0), 0);
  const rowsSorted = useMemo(
    () => [...rows].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")),
    [rows]
  );
  return (
    <div className="bg-white border rounded-lg p-4 mt-6" data-testid="today-entries">
      <div className="flex items-center gap-3 flex-wrap mb-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-700">
          Today's Entries
          <span className="ml-2 text-zinc-400 font-normal normal-case tracking-normal">
            (Quick Op · {date} · source-of-truth Expense)
          </span>
          <span className="ml-2 text-[10px] text-zinc-300 font-normal normal-case"
                data-testid="today-entries-version"
                title="Bundle marker — Ctrl/Cmd+Shift+R if this stamp is missing.">v140</span>
        </h2>
        <div className="ml-auto text-xs text-zinc-600 flex gap-4">
          <span data-testid="today-entries-count">Rows: {rows.length}</span>
          <span data-testid="today-entries-total">Total: {fmt(total)}</span>
        </div>
      </div>
      {q.isLoading ? (
        <div className="text-zinc-400 text-sm">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="text-zinc-400 text-sm" data-testid="today-entries-empty">
          No quick-op entries for {date}.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50">
              <tr className="text-left">
                <th className="py-2 px-2">Time</th>
                <th className="py-2 px-2">Category</th>
                <th className="py-2 px-2">Vehicle</th>
                <th className="py-2 px-2">Vendor</th>
                <th className="py-2 px-2">Description</th>
                <th className="py-2 px-2 text-right">Amount</th>
                <th className="py-2 px-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {rowsSorted.map((r, i) => (
                <tr key={r.id} className="border-t"
                    data-testid={`today-entry-row-${i}`}
                    data-eid={r.id}>
                  <td className="py-2 px-2 whitespace-nowrap text-xs text-zinc-500">
                    {(r.created_at || "").slice(11, 16)}
                  </td>
                  <td className="py-2 px-2">{r.category}</td>
                  <td className="py-2 px-2 font-mono text-xs">{r.vehicle_number || r.vehicle_id}</td>
                  <td className="py-2 px-2 text-xs">
                    {r.party_type === "vendor"
                      ? (vendorsById[r.party_id]?.name || r.party_name || r.party_id)
                      : <span className="text-zinc-400">—</span>}
                  </td>
                  <td className="py-2 px-2 text-zinc-600 text-xs">{r.narration || r.remarks || ""}</td>
                  <td className="py-2 px-2 text-right tabular-nums"
                      data-testid={`today-entry-amount-${i}`}>{fmt(r.amount)}</td>
                  <td className="py-2 px-2 text-right whitespace-nowrap">
                    <button
                      onClick={() => onEdit(r)}
                      className="text-xs text-indigo-700 hover:underline mr-3"
                      data-testid={`today-entry-edit-${i}`}>
                      <Pencil size={12} className="inline mr-1"/>Edit
                    </button>
                    <button
                      onClick={() => onCancel(r)}
                      className="text-xs text-rose-700 hover:underline"
                      data-testid={`today-entry-cancel-${i}`}>
                      <X size={12} className="inline mr-1"/>Cancel
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t bg-zinc-50">
                <td colSpan={5} className="py-2 px-2 text-right font-semibold">Total</td>
                <td className="py-2 px-2 text-right tabular-nums font-semibold"
                    data-testid="today-entries-total-cell">{fmt(total)}</td>
                <td/>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      <p className="mt-3 text-[11px] text-zinc-400">
        Reads canonical Expense with <code>source_type='quick_op'</code>. Edit
        and Cancel update the SAME Expense — Vehicle Cost, Expense Register
        and Vendor-linked view reflect the change immediately. Cancel is a
        soft-delete: accounting history is preserved.
      </p>
    </div>
  );
}

// ── Iter140 · Edit modal ───────────────────────────────────────────────────
function EditExpenseModal({ doc, vendorOptions, onClose, onSaved }) {
  const isDiesel = doc.category === "Diesel";
  // Best-effort parse of qty / rate from the server-composed narration
  //   "149.62L @ ₹104.25 · <filled_at> · <vendor>"
  const parsed = useMemo(() => {
    const m = /^(\d+(?:\.\d+)?)L\s*@\s*₹\s*(\d+(?:\.\d+)?)/.exec(doc.narration || "");
    if (m) return { qty: parseFloat(m[1]), rate: parseFloat(m[2]) };
    return { qty: "", rate: "" };
  }, [doc.narration]);
  const [qty, setQty] = useState(String(parsed.qty || ""));
  const [rate, setRate] = useState(String(parsed.rate || ""));
  const [filledAt, setFilledAt] = useState(() => {
    // "qty×rate · filled_at · vendor"
    const parts = (doc.narration || "").split(" · ");
    return parts.length >= 2 ? parts[1] : "";
  });
  const [vendorId, setVendorId] = useState(doc.party_type === "vendor" ? (doc.party_id || "") : "");
  const [amount, setAmount] = useState(String(doc.amount || ""));
  const [remarks, setRemarks] = useState(doc.remarks || "");
  const computedAmt = isDiesel
    ? q2((parseFloat(qty) || 0) * (parseFloat(rate) || 0))
    : (parseFloat(amount) || 0);

  const save = useMutation({
    mutationFn: async () => {
      if (isDiesel) {
        const { data } = await api.put(`/expenses/${doc.id}/quick-diesel`, {
          qty: parseFloat(qty) || 0,
          rate: parseFloat(rate) || 0,
          filled_at: filledAt || "",
          vendor_id: vendorId || "",
          remarks: remarks || "",
        });
        return data;
      }
      // Non-Diesel — canonical PUT /expenses/{id}
      const payload = { ...doc, amount: computedAmt, remarks };
      const { data } = await api.put(`/expenses/${doc.id}`, payload);
      return data;
    },
    onSuccess: onSaved,
    onError: (e) => toast.error(e?.response?.data?.detail || "Update failed"),
  });

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center pt-16"
         data-testid="edit-expense-modal">
      <div className="bg-white rounded-lg shadow-xl w-[min(640px,94vw)] max-h-[85vh] overflow-auto">
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b">
          <div>
            <div className="font-semibold">Edit {doc.category} Expense</div>
            <div className="text-xs text-zinc-500 mt-0.5">
              {doc.date} · {doc.vehicle_number || doc.vehicle_id} · {doc.id}
            </div>
          </div>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-700"
                  data-testid="edit-expense-close">×</button>
        </div>
        <div className="px-5 py-4 space-y-3 text-sm">
          {isDiesel ? (
            <>
              <div className="grid grid-cols-3 gap-3">
                <label className="text-xs">Qty (Ltrs)
                  <input type="number" step="0.01" value={qty}
                         onChange={(e) => setQty(e.target.value)}
                         className="w-full border rounded px-2 py-1 mt-0.5"
                         data-testid="edit-diesel-qty"/>
                </label>
                <label className="text-xs">Rate (₹)
                  <input type="number" step="0.01" value={rate}
                         onChange={(e) => setRate(e.target.value)}
                         className="w-full border rounded px-2 py-1 mt-0.5"
                         data-testid="edit-diesel-rate"/>
                </label>
                <label className="text-xs">Amount (server-authoritative)
                  <input type="text" readOnly value={fmt(computedAmt)}
                         tabIndex={-1}
                         onKeyDown={(e) => e.preventDefault()}
                         onPaste={(e) => e.preventDefault()}
                         className="w-full border rounded px-2 py-1 mt-0.5 bg-zinc-50 cursor-not-allowed text-right tabular-nums"
                         data-testid="edit-diesel-amount"/>
                </label>
              </div>
              <label className="text-xs block">Filled At
                <input type="text" value={filledAt}
                       onChange={(e) => setFilledAt(e.target.value)}
                       className="w-full border rounded px-2 py-1 mt-0.5"
                       data-testid="edit-diesel-filled-at"/>
              </label>
              <div className="text-xs">
                <div className="mb-0.5">Vendor</div>
                <SearchableSelect
                  testId="edit-diesel-vendor"
                  placeholder="Vendor (optional) — search master…"
                  emptyText="No vendors" allowClear
                  value={vendorId}
                  onChange={(v) => setVendorId(v)}
                  options={vendorOptions}/>
              </div>
            </>
          ) : (
            <label className="text-xs block">Amount
              <input type="number" step="0.01" value={amount}
                     onChange={(e) => setAmount(e.target.value)}
                     className="w-full border rounded px-2 py-1 mt-0.5"
                     data-testid="edit-nondiesel-amount"/>
            </label>
          )}
          <label className="text-xs block">Remarks
            <textarea rows={2} value={remarks}
                      onChange={(e) => setRemarks(e.target.value)}
                      className="w-full border rounded px-2 py-1 mt-0.5"
                      data-testid="edit-remarks"/>
          </label>
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t bg-zinc-50">
          <button onClick={onClose} className="px-3 py-1.5 border rounded text-sm"
                  data-testid="edit-expense-cancel-btn">Cancel</button>
          <button onClick={() => save.mutate()}
                  disabled={save.isPending}
                  className="px-3 py-1.5 bg-zinc-900 text-white rounded text-sm disabled:opacity-40"
                  data-testid="edit-expense-save-btn">
            {save.isPending ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Iter140 · Cancel modal ─────────────────────────────────────────────────
function CancelExpenseModal({ doc, onClose, onCancelled }) {
  const [reason, setReason] = useState("");
  const del = useMutation({
    mutationFn: async () => {
      const r = (reason || "").trim();
      if (r.length < 3) throw new Error("Please enter a cancellation reason (min 3 chars).");
      const { data } = await api.delete(`/expenses/${doc.id}`,
        { params: { reason: r } });
      return data;
    },
    onSuccess: onCancelled,
    onError: (e) => toast.error(e?.response?.data?.detail || e?.message || "Cancel failed"),
  });
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center pt-24"
         data-testid="cancel-expense-modal">
      <div className="bg-white rounded-lg shadow-xl w-[min(500px,92vw)]">
        <div className="flex items-start gap-3 px-5 py-4 border-b bg-rose-50">
          <AlertTriangle className="text-rose-600 mt-0.5" size={20}/>
          <div>
            <div className="font-semibold text-rose-900">Cancel this expense?</div>
            <div className="text-xs text-rose-800 mt-1">
              Soft-cancel (accounting history is preserved). Vehicle Cost,
              Expense Register and Vendor-linked view will hide it.
            </div>
          </div>
        </div>
        <div className="px-5 py-3 text-sm space-y-2">
          <div>
            <div className="text-[11px] uppercase text-zinc-500">Category</div>
            <div className="font-medium">{doc.category}</div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-[11px] uppercase text-zinc-500">Vehicle</div>
              <div>{doc.vehicle_number || doc.vehicle_id}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase text-zinc-500">Amount</div>
              <div>{fmt(doc.amount)}</div>
            </div>
          </div>
          {doc.party_type === "vendor" && (
            <div>
              <div className="text-[11px] uppercase text-zinc-500">Vendor</div>
              <div>{doc.party_name || doc.party_id}</div>
            </div>
          )}
          <label className="block text-xs pt-1">Reason (mandatory, min 3 chars)
            <input type="text" value={reason}
                   onChange={(e) => setReason(e.target.value)}
                   className="w-full border rounded px-2 py-1 mt-0.5"
                   data-testid="cancel-expense-reason"/>
          </label>
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t bg-zinc-50">
          <button onClick={onClose} className="px-3 py-1.5 border rounded text-sm"
                  data-testid="cancel-expense-close">Keep it</button>
          <button onClick={() => del.mutate()}
                  disabled={del.isPending || (reason || "").trim().length < 3}
                  className="px-3 py-1.5 bg-rose-600 text-white rounded text-sm disabled:opacity-40"
                  data-testid="cancel-expense-confirm">
            {del.isPending ? "Cancelling…" : "Cancel Expense"}
          </button>
        </div>
      </div>
    </div>
  );
}
