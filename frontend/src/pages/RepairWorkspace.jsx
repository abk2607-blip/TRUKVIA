import React, { useState, useMemo, useEffect } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errMsg } from "@/api";
import { toast } from "sonner";
import { ArrowLeft, Plus, Wrench, HardHat, CheckCircle2, AlertTriangle, RefreshCw, Wallet } from "lucide-react";
import PaymentDrawer from "@/components/PaymentDrawer";

/**
 * Iter133 · Turn 3 · Slice A — Repair Workspace.
 *
 * Routes:
 *   /vehicles/:vid/repairs/new   → RepairEvent header create form
 *   /repairs/:rid                → RepairEvent detail: Parts + Labour + derived totals
 *
 * BINDING PRINCIPLE — ENTER ONCE → CALCULATE ONCE:
 *   Save Parts   → POST /vendor-bills          (payable) THEN POST /expenses (twin cost)
 *   Save Labour  → POST /mechanic-work-orders  (payable) THEN POST /expenses (twin cost)
 *   Save Other   → POST /expenses only (no payable, no party linkage)
 *
 * TWIN-WRITE SAFETY:
 *   Each row keeps two stable Idempotency-Keys generated on row-open.
 *   If Bill/WO succeeds but Expense fails → row is marked "Cost failed" with
 *   a Retry Cost button that re-issues ONLY the Expense POST using the SAME
 *   Idempotency-Key. Backend replays a successful Bill; the Expense POST
 *   either finally succeeds or replays a successful earlier attempt.
 *   Never creates duplicate Bill/WO/Expense on any retry.
 *
 * DERIVED TOTALS come from GET /api/vehicles/{vid}/repair-history — the same
 * single source that Vehicle Cost Report reads. Zero client re-aggregation.
 */

function newUuid() {
  try {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
    if (typeof crypto !== "undefined" && crypto.getRandomValues) {
      const b = new Uint8Array(16); crypto.getRandomValues(b);
      b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
      const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
      return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    }
  } catch {}
  return `ts-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;
const today = () => new Date().toISOString().slice(0, 10);
const ic = "w-full border border-zinc-300 px-2 py-1.5 rounded-sm text-sm outline-none focus:border-zinc-950 bg-white";

export default function RepairWorkspace() {
  const { vid, rid } = useParams();
  if (rid) return <RepairDetail rid={rid} />;
  return <NewRepair vid={vid} />;
}

/* ------------------- New Repair (header only) ------------------- */
function NewRepair({ vid }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { data: vehicle } = useQuery({
    queryKey: ["vehicle", vid],
    queryFn: async () => (await api.get(`/vehicles`)).data.find((x) => x.id === vid) || null,
    enabled: !!vid,
  });
  const [form, setForm] = useState({
    event_date: today(),
    workshop_name: "",
    description: "",
    odometer: 0,
    trip_id: "",
    status: "open",
    remarks: "",
  });

  const create = useMutation({
    mutationFn: async () => {
      const body = {
        ...form,
        odometer: Number(form.odometer || 0),
        vehicle_id: vid,
        vehicle_number: vehicle?.vehicle_number || "",
      };
      return (await api.post("/repair-events", body)).data;
    },
    onSuccess: (data) => {
      toast.success("Repair created");
      qc.invalidateQueries({ queryKey: ["vehicle-repair-history", vid] });
      nav(`/repairs/${data.id}`);
    },
    onError: (e) => toast.error(errMsg(e, "Create failed")),
  });

  return (
    <div className="p-6 space-y-6 max-w-3xl" data-testid="repair-new-page">
      <div className="flex items-center gap-3">
        <button onClick={() => nav(`/vehicles/${vid}/cost`)}
          className="flex items-center gap-1 text-sm text-zinc-600 hover:text-zinc-900" data-testid="back-to-cost">
          <ArrowLeft size={16} /> Back
        </button>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <Wrench size={22} /> New Repair · {vehicle?.vehicle_number || vid}
        </h1>
      </div>

      <div className="bg-white border rounded-sm p-5 space-y-3">
        <div className="text-xs text-zinc-500">
          Repair envelope has <b>no total cost field</b>. Parts and Labour rows you add next will
          create the cost automatically.
        </div>
        <div className="grid grid-cols-2 gap-3">
          <L label="Event Date *">
            <input required data-testid="repair-event-date" type="date" value={form.event_date}
              onChange={(e) => setForm({ ...form, event_date: e.target.value })} className={ic} />
          </L>
          <L label="Status">
            <select data-testid="repair-status" value={form.status}
              onChange={(e) => setForm({ ...form, status: e.target.value })} className={ic}>
              <option value="open">Open</option>
              <option value="closed">Closed</option>
            </select>
          </L>
          <L label="Workshop / Garage">
            <input data-testid="repair-workshop" value={form.workshop_name}
              onChange={(e) => setForm({ ...form, workshop_name: e.target.value })} className={ic} />
          </L>
          <L label="Odometer">
            <input data-testid="repair-odometer" type="number" step="0.1" min="0" value={form.odometer}
              onChange={(e) => setForm({ ...form, odometer: e.target.value })} className={ic} />
          </L>
          <L label="Trip Reference (optional)">
            <input data-testid="repair-trip-id" value={form.trip_id}
              onChange={(e) => setForm({ ...form, trip_id: e.target.value })} className={ic}
              placeholder="Trip id if this repair is tied to a specific trip" />
          </L>
          <L label="Description">
            <input data-testid="repair-description" value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })} className={ic}
              placeholder="e.g. Gearbox overhaul + clutch plate" />
          </L>
          <div className="col-span-2">
            <L label="Remarks">
              <input data-testid="repair-remarks" value={form.remarks}
                onChange={(e) => setForm({ ...form, remarks: e.target.value })} className={ic} />
            </L>
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2 border-t">
          <button onClick={() => nav(`/vehicles/${vid}/cost`)}
            className="px-4 py-2 text-xs uppercase tracking-wider border rounded-sm">Cancel</button>
          <button data-testid="create-repair-btn"
            disabled={create.isPending || !form.event_date}
            onClick={() => create.mutate()}
            className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
            {create.isPending ? "Creating…" : "Create Repair & Add Rows"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------- Repair Detail: Parts + Labour + Totals ------------------- */
function RepairDetail({ rid }) {
  const nav = useNavigate();
  const qc = useQueryClient();

  const repair = useQuery({
    queryKey: ["repair-event", rid],
    queryFn: async () => (await api.get(`/repair-events/${rid}`)).data,
  });

  const vid = repair.data?.vehicle_id || "";
  const vehicle = useQuery({
    queryKey: ["vehicle", vid],
    queryFn: async () => (await api.get(`/vehicles`)).data.find((x) => x.id === vid) || null,
    enabled: !!vid,
  });

  const bills = useQuery({
    queryKey: ["vendor-bills", "repair", rid],
    queryFn: async () => (await api.get(`/vendor-bills?repair_event_id=${rid}`)).data,
  });
  const wos = useQuery({
    queryKey: ["mechanic-work-orders", "repair", rid],
    queryFn: async () => (await api.get(`/mechanic-work-orders?repair_event_id=${rid}`)).data,
  });
  const expenses = useQuery({
    queryKey: ["expenses", "repair", rid],
    queryFn: async () => (await api.get(`/expenses?repair_event_id=${rid}`)).data,
  });
  const history = useQuery({
    queryKey: ["vehicle-repair-history", vid, rid],
    queryFn: async () => (await api.get(`/vehicles/${vid}/repair-history`)).data,
    enabled: !!vid,
  });

  // Supplier settlement mode — mandatory if this vehicle is supplier-owned
  const isSupplierOwned = (vehicle.data?.vehicle_type === "supplier");
  const [settlementMode, setSettlementMode] = useState("supplier_settlement_adjustment");

  // Payment drawer state (reused for Vendor and Mechanic pay-actions)
  const [payDrawer, setPayDrawer] = useState(null); // {partyType, partyId, partyName, prefill}

  // Derived totals for THIS repair only (from repair-history)
  const thisEvent = useMemo(() => {
    return (history.data?.events || []).find((e) => e.id === rid) || null;
  }, [history.data, rid]);

  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ["vendor-bills", "repair", rid] });
    qc.invalidateQueries({ queryKey: ["mechanic-work-orders", "repair", rid] });
    qc.invalidateQueries({ queryKey: ["expenses", "repair", rid] });
    qc.invalidateQueries({ queryKey: ["vehicle-repair-history", vid, rid] });
  };

  if (repair.isLoading) return <div className="p-6">Loading…</div>;
  if (repair.isError) return <div className="p-6 text-rose-700">Repair not found.</div>;

  const r = repair.data;

  return (
    <div className="p-6 space-y-6" data-testid="repair-detail-page">
      <div className="flex items-center gap-3">
        <button onClick={() => nav(`/vehicles/${vid}/cost`)}
          className="flex items-center gap-1 text-sm text-zinc-600 hover:text-zinc-900" data-testid="back-to-cost">
          <ArrowLeft size={16} /> Back to Vehicle Cost
        </button>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <Wrench size={22} /> Repair · {vehicle.data?.vehicle_number || vid}
        </h1>
        <button onClick={refreshAll} className="ml-auto flex items-center gap-1 text-xs px-2 py-1 border rounded-sm hover:bg-zinc-100" data-testid="refresh-totals">
          <RefreshCw size={12} /> Refresh Totals
        </button>
      </div>

      {/* Header summary */}
      <div className="bg-white border rounded-sm p-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm" data-testid="repair-header">
        <Info label="Event Date" value={r.event_date} testid="rh-date" />
        <Info label="Workshop" value={r.workshop_name || "—"} testid="rh-workshop" />
        <Info label="Status" value={r.status} testid="rh-status" />
        <Info label="Description" value={r.description || "—"} testid="rh-desc" />
      </div>

      {/* Supplier settlement mode (only for supplier-owned vehicles) */}
      {isSupplierOwned && (
        <div className="bg-amber-50 border border-amber-300 rounded-sm p-4 space-y-2" data-testid="settlement-band">
          <div className="text-xs font-bold text-amber-900 uppercase tracking-wider">
            Supplier-owned vehicle · settlement mode required
          </div>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input type="radio" name="settlement" checked={settlementMode === "supplier_settlement_adjustment"}
                onChange={() => setSettlementMode("supplier_settlement_adjustment")}
                data-testid="settle-adjustment" />
              Recover from supplier freight <span className="text-zinc-500">(adjustment · Supplier CREDIT, no P&L hit)</span>
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="settlement" checked={settlementMode === "company_borne"}
                onChange={() => setSettlementMode("company_borne")}
                data-testid="settle-company-borne" />
              Company bears cost <span className="text-zinc-500">(P&L hit, no supplier credit)</span>
            </label>
          </div>
          <div className="text-[11px] text-amber-800">
            This selection applies to every Parts / Labour / Other row you save on this repair.
          </div>
        </div>
      )}

      {/* Derived totals — single source of truth from /repair-history */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3" data-testid="repair-totals">
        <Kpi label="Total Repair Cost" value={fmt(thisEvent?.total_repair_cost)} testid="kpi-total-repair-cost" hi />
        <Kpi label="Parts Cost" value={fmt(thisEvent?.parts_cost)} testid="kpi-parts-cost" />
        <Kpi label="Labour Cost" value={fmt(thisEvent?.labour_cost)} testid="kpi-labour-cost" />
        <Kpi label="Other Cost" value={fmt(thisEvent?.other_cost)} testid="kpi-other-cost" />
        <Kpi label="Vendor Payable" value={fmt(thisEvent?.vendor_outstanding) + " / " + fmt(thisEvent?.vendor_payable)} testid="kpi-vendor-payable" />
        <Kpi label="Mechanic Payable" value={fmt(thisEvent?.mechanic_outstanding) + " / " + fmt(thisEvent?.mechanic_payable)} testid="kpi-mechanic-payable" />
      </div>
      <p className="text-[11px] text-zinc-500" data-testid="totals-source-note">
        Totals derived server-side from canonical Expense rows (Repair Cost) and Bill/WO/Payment rows
        (payables). Bill amount + twin Expense amount is never double-counted.
      </p>

      {/* PARTS section */}
      <PartsSection
        rid={rid}
        vid={vid}
        vehicleNumber={vehicle.data?.vehicle_number || ""}
        isSupplierOwned={isSupplierOwned}
        settlementMode={settlementMode}
        existingBills={bills.data || []}
        existingExpenses={expenses.data || []}
        eventDate={r.event_date}
        onSaved={refreshAll}
        onOpenPay={(bill) => setPayDrawer({
          partyType: "vendor",
          partyId: bill.vendor_id,
          partyName: bill.vendor_name,
          prefill: {
            billOrWo: {
              id: bill.id, number: bill.bill_number, amount: bill.bill_amount,
              outstanding: (() => {
                const t = thisEvent;
                if (!t) return undefined;
                // best-effort: full event outstanding — user will enter actual amount
                return t.vendor_outstanding;
              })(),
            },
          },
        })}
      />

      {/* LABOUR section */}
      <LabourSection
        rid={rid}
        vid={vid}
        vehicleNumber={vehicle.data?.vehicle_number || ""}
        isSupplierOwned={isSupplierOwned}
        settlementMode={settlementMode}
        existingWos={wos.data || []}
        existingExpenses={expenses.data || []}
        eventDate={r.event_date}
        onSaved={refreshAll}
        onOpenPay={(wo) => setPayDrawer({
          partyType: "mechanic",
          partyId: wo.mechanic_id,
          partyName: wo.mechanic_name,
          prefill: {
            billOrWo: {
              id: wo.id, number: wo.id, amount: wo.amount,
              outstanding: thisEvent?.mechanic_outstanding,
            },
          },
        })}
      />

      {payDrawer && (
        <PaymentDrawer
          open
          partyType={payDrawer.partyType}
          partyId={payDrawer.partyId}
          partyName={payDrawer.partyName}
          prefill={payDrawer.prefill}
          onClose={() => setPayDrawer(null)}
          onSaved={refreshAll}
        />
      )}
    </div>
  );
}

/* ------------------- Parts section (VendorBill + twin Expense) ------------------- */
function PartsSection({ rid, vid, vehicleNumber, isSupplierOwned, settlementMode,
                       existingBills, existingExpenses, eventDate, onSaved, onOpenPay }) {
  const vendors = useQuery({
    queryKey: ["vendors"],
    queryFn: async () => (await api.get("/vendors")).data,
  });
  const [rows, setRows] = useState([]); // draft rows only; existingBills is the persisted set

  const addRow = () => setRows((r) => [...r, {
    key: newUuid(),
    idem_bill: newUuid(),
    idem_expense: newUuid(),
    vendor_id: "",
    bill_number: "",
    bill_date: eventDate || today(),
    bill_amount: "",
    category: "Repair-Parts",
    narration: "",
    saved_bill_id: "",
    saved_expense_id: "",
    error: "",
    busy: false,
  }]);

  const upd = (k, patch) => setRows((rs) => rs.map((r) => r.key === k ? { ...r, ...patch } : r));
  const rm = (k) => setRows((rs) => rs.filter((r) => r.key !== k));

  const saveRow = async (r) => {
    upd(r.key, { busy: true, error: "" });
    let billId = r.saved_bill_id;
    try {
      // Step 1 — Bill (payable)
      if (!billId) {
        const billBody = {
          vendor_id: r.vendor_id,
          bill_number: r.bill_number,
          bill_date: r.bill_date,
          bill_amount: Number(r.bill_amount),
          vehicle_id: vid,
          vehicle_number: vehicleNumber,
          repair_event_id: rid,
          narration: r.narration,
        };
        const bill = (await api.post("/vendor-bills", billBody, {
          headers: { "Idempotency-Key": r.idem_bill },
        })).data;
        billId = bill.id;
        upd(r.key, { saved_bill_id: billId });
      }
      // Step 2 — Twin canonical Expense (cost)
      const expBody = {
        date: r.bill_date,
        category: r.category || "Repair-Parts",
        amount: Number(r.bill_amount),
        vehicle_id: vid,
        vehicle_number: vehicleNumber,
        repair_event_id: rid,
        party_type: "vendor",
        vendor_bill_id: billId,
        narration: r.narration,
        supplier_owned_vehicle: !!isSupplierOwned,
        supplier_settlement_mode: isSupplierOwned ? settlementMode : "n/a",
      };
      const exp = (await api.post("/expenses", expBody, {
        headers: { "Idempotency-Key": r.idem_expense },
      })).data;
      upd(r.key, { saved_expense_id: exp.id, busy: false });
      toast.success("Parts row twinned (Bill + Cost)");
      onSaved();
    } catch (e) {
      const msg = errMsg(e, "Save failed");
      upd(r.key, {
        error: billId ? `Bill saved (id: ${billId}) — Cost posting failed: ${msg}`
                      : `Bill create failed: ${msg}`,
        busy: false,
      });
      toast.error(msg);
    }
  };

  const retryCost = (r) => saveRow(r); // idempotency keys are stable → replays cleanly

  return (
    <div className="bg-white border rounded-sm p-4 space-y-3" data-testid="parts-section">
      <div className="flex items-center gap-2">
        <Wrench size={16} className="text-zinc-600" />
        <h2 className="font-semibold text-base">Parts (Vendor Bills)</h2>
        <button data-testid="add-parts-row" onClick={addRow}
          className="ml-auto text-xs px-2 py-1 border rounded-sm hover:bg-zinc-950 hover:text-white inline-flex items-center gap-1">
          <Plus size={12} /> Add Parts Row
        </button>
      </div>

      {/* Persisted bills (with derived twin/paid state) */}
      {existingBills.length > 0 && (
        <table className="w-full text-sm border-t" data-testid="parts-existing-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-2 py-1.5">Vendor</th>
              <th className="text-left px-2 py-1.5">Bill #</th>
              <th className="text-left px-2 py-1.5">Date</th>
              <th className="text-right px-2 py-1.5">Amount</th>
              <th className="text-center px-2 py-1.5">Cost Twinned</th>
              <th className="text-right px-2 py-1.5">Actions</th>
            </tr>
          </thead>
          <tbody>
            {existingBills.map((b) => {
              const twin = existingExpenses.find((x) => x.vendor_bill_id === b.id && !x.is_reversed);
              return (
                <tr key={b.id} className="border-t" data-testid={`parts-existing-row-${b.id}`}>
                  <td className="px-2 py-1.5">{b.vendor_name}</td>
                  <td className="px-2 py-1.5 font-mono text-xs">{b.bill_number || b.id}</td>
                  <td className="px-2 py-1.5 text-xs">{b.bill_date}</td>
                  <td className="px-2 py-1.5 text-right font-medium">{fmt(b.bill_amount)}</td>
                  <td className="px-2 py-1.5 text-center">
                    {twin
                      ? <span className="text-emerald-700 inline-flex items-center gap-1 text-xs"><CheckCircle2 size={12}/> Cost ₹{Number(twin.amount).toLocaleString("en-IN")}</span>
                      : <span className="text-rose-700 inline-flex items-center gap-1 text-xs"><AlertTriangle size={12}/> No Cost</span>}
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <button data-testid={`pay-vendor-btn-${b.id}`}
                      onClick={() => onOpenPay(b)}
                      className="text-xs px-2 py-1 border rounded-sm inline-flex items-center gap-1 hover:bg-zinc-950 hover:text-white">
                      <Wallet size={12} /> Pay
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {/* Draft rows */}
      {rows.length > 0 && (
        <div className="border-t pt-3 space-y-2" data-testid="parts-draft-rows">
          {rows.map((r) => (
            <div key={r.key} className="grid grid-cols-12 gap-2 items-end border rounded-sm p-2 bg-zinc-50"
                 data-testid={`parts-draft-row-${r.key}`}>
              <div className="col-span-3">
                <div className="text-[9px] uppercase tracking-wider text-zinc-500">Vendor *</div>
                <select value={r.vendor_id} onChange={(e) => upd(r.key, { vendor_id: e.target.value })}
                  className={ic} disabled={!!r.saved_bill_id} data-testid="parts-vendor-select">
                  <option value="">— Select vendor —</option>
                  {(vendors.data || []).filter((v) => v.is_active !== false).map((v) =>
                    <option key={v.id} value={v.id}>{v.name}</option>)}
                </select>
              </div>
              <div className="col-span-2">
                <div className="text-[9px] uppercase tracking-wider text-zinc-500">Bill #</div>
                <input value={r.bill_number} onChange={(e) => upd(r.key, { bill_number: e.target.value })}
                  className={ic} disabled={!!r.saved_bill_id} data-testid="parts-bill-number" />
              </div>
              <div className="col-span-2">
                <div className="text-[9px] uppercase tracking-wider text-zinc-500">Date *</div>
                <input type="date" value={r.bill_date}
                  onChange={(e) => upd(r.key, { bill_date: e.target.value })}
                  className={ic} disabled={!!r.saved_bill_id} data-testid="parts-bill-date" />
              </div>
              <div className="col-span-2">
                <div className="text-[9px] uppercase tracking-wider text-zinc-500">Amount * (₹)</div>
                <input type="number" step="0.01" min="0.01" value={r.bill_amount}
                  onChange={(e) => upd(r.key, { bill_amount: e.target.value })}
                  className={ic} disabled={!!r.saved_bill_id} data-testid="parts-amount" />
              </div>
              <div className="col-span-2">
                <div className="text-[9px] uppercase tracking-wider text-zinc-500">Category</div>
                <input value={r.category} onChange={(e) => upd(r.key, { category: e.target.value })}
                  className={ic} data-testid="parts-category" />
              </div>
              <div className="col-span-1 flex flex-col gap-1">
                {!r.saved_expense_id && !r.error && (
                  <button data-testid="save-parts-btn"
                    disabled={r.busy || !r.vendor_id || !(Number(r.bill_amount) > 0)}
                    onClick={() => saveRow(r)}
                    className="text-xs px-2 py-1 bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
                    {r.busy ? "Saving…" : "Save Parts"}
                  </button>
                )}
                {r.error && r.saved_bill_id && !r.saved_expense_id && (
                  <button data-testid="retry-parts-cost-btn"
                    disabled={r.busy}
                    onClick={() => retryCost(r)}
                    className="text-xs px-2 py-1 bg-rose-600 text-white rounded-sm hover:bg-rose-700 disabled:opacity-50">
                    {r.busy ? "Retrying…" : "Retry Cost"}
                  </button>
                )}
                {r.saved_expense_id && (
                  <span className="text-[10px] text-emerald-700 inline-flex items-center gap-1"
                        data-testid="parts-twinned-badge">
                    <CheckCircle2 size={12}/> Twinned
                  </span>
                )}
                {!r.saved_bill_id && !r.saved_expense_id && (
                  <button onClick={() => rm(r.key)} className="text-[10px] text-zinc-500 hover:text-rose-700">Remove</button>
                )}
              </div>
              <div className="col-span-12">
                <div className="text-[9px] uppercase tracking-wider text-zinc-500">Narration</div>
                <input value={r.narration} onChange={(e) => upd(r.key, { narration: e.target.value })}
                  className={ic} data-testid="parts-narration" />
              </div>
              {r.error && (
                <div className="col-span-12 text-[11px] text-rose-700 border-t pt-1" data-testid="parts-error">
                  <AlertTriangle size={12} className="inline mr-1" /> {r.error}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {rows.length === 0 && existingBills.length === 0 && (
        <div className="text-xs text-zinc-500 border-t pt-3" data-testid="parts-empty">
          No parts recorded yet. Click <b>Add Parts Row</b> to enter a vendor bill — the cost is booked automatically.
        </div>
      )}
    </div>
  );
}

/* ------------------- Labour section (MechanicWorkOrder + twin Expense) ------------------- */
function LabourSection({ rid, vid, vehicleNumber, isSupplierOwned, settlementMode,
                        existingWos, existingExpenses, eventDate, onSaved, onOpenPay }) {
  const mechanics = useQuery({
    queryKey: ["mechanics"],
    queryFn: async () => (await api.get("/mechanics")).data,
  });
  const [rows, setRows] = useState([]);

  const addRow = () => setRows((r) => [...r, {
    key: newUuid(),
    idem_wo: newUuid(),
    idem_expense: newUuid(),
    mechanic_id: "",
    work_date: eventDate || today(),
    amount: "",
    hours_worked: 0,
    category: "Repair-Labour",
    narration: "",
    saved_wo_id: "",
    saved_expense_id: "",
    error: "",
    busy: false,
  }]);
  const upd = (k, patch) => setRows((rs) => rs.map((r) => r.key === k ? { ...r, ...patch } : r));
  const rm = (k) => setRows((rs) => rs.filter((r) => r.key !== k));

  const saveRow = async (r) => {
    upd(r.key, { busy: true, error: "" });
    let woId = r.saved_wo_id;
    try {
      if (!woId) {
        const woBody = {
          mechanic_id: r.mechanic_id,
          work_date: r.work_date,
          amount: Number(r.amount),
          hours_worked: Number(r.hours_worked || 0),
          vehicle_id: vid,
          vehicle_number: vehicleNumber,
          repair_event_id: rid,
          narration: r.narration,
        };
        const wo = (await api.post("/mechanic-work-orders", woBody, {
          headers: { "Idempotency-Key": r.idem_wo },
        })).data;
        woId = wo.id;
        upd(r.key, { saved_wo_id: woId });
      }
      const expBody = {
        date: r.work_date,
        category: r.category || "Repair-Labour",
        amount: Number(r.amount),
        vehicle_id: vid,
        vehicle_number: vehicleNumber,
        repair_event_id: rid,
        party_type: "mechanic",
        mechanic_work_order_id: woId,
        narration: r.narration,
        supplier_owned_vehicle: !!isSupplierOwned,
        supplier_settlement_mode: isSupplierOwned ? settlementMode : "n/a",
      };
      const exp = (await api.post("/expenses", expBody, {
        headers: { "Idempotency-Key": r.idem_expense },
      })).data;
      upd(r.key, { saved_expense_id: exp.id, busy: false });
      toast.success("Labour row twinned (WO + Cost)");
      onSaved();
    } catch (e) {
      const msg = errMsg(e, "Save failed");
      upd(r.key, {
        error: woId ? `Work Order saved (id: ${woId}) — Cost posting failed: ${msg}`
                    : `Work Order create failed: ${msg}`,
        busy: false,
      });
      toast.error(msg);
    }
  };
  const retryCost = (r) => saveRow(r);

  return (
    <div className="bg-white border rounded-sm p-4 space-y-3" data-testid="labour-section">
      <div className="flex items-center gap-2">
        <HardHat size={16} className="text-zinc-600" />
        <h2 className="font-semibold text-base">Labour (Mechanic Work Orders)</h2>
        <button data-testid="add-labour-row" onClick={addRow}
          className="ml-auto text-xs px-2 py-1 border rounded-sm hover:bg-zinc-950 hover:text-white inline-flex items-center gap-1">
          <Plus size={12} /> Add Labour Row
        </button>
      </div>

      {existingWos.length > 0 && (
        <table className="w-full text-sm border-t" data-testid="labour-existing-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-2 py-1.5">Mechanic</th>
              <th className="text-left px-2 py-1.5">Work Date</th>
              <th className="text-right px-2 py-1.5">Hours</th>
              <th className="text-right px-2 py-1.5">Amount</th>
              <th className="text-center px-2 py-1.5">Cost Twinned</th>
              <th className="text-right px-2 py-1.5">Actions</th>
            </tr>
          </thead>
          <tbody>
            {existingWos.map((w) => {
              const twin = existingExpenses.find((x) => x.mechanic_work_order_id === w.id && !x.is_reversed);
              return (
                <tr key={w.id} className="border-t" data-testid={`labour-existing-row-${w.id}`}>
                  <td className="px-2 py-1.5">{w.mechanic_name}</td>
                  <td className="px-2 py-1.5 text-xs">{w.work_date}</td>
                  <td className="px-2 py-1.5 text-right text-xs">{Number(w.hours_worked || 0)}</td>
                  <td className="px-2 py-1.5 text-right font-medium">{fmt(w.amount)}</td>
                  <td className="px-2 py-1.5 text-center">
                    {twin
                      ? <span className="text-emerald-700 inline-flex items-center gap-1 text-xs"><CheckCircle2 size={12}/> Cost ₹{Number(twin.amount).toLocaleString("en-IN")}</span>
                      : <span className="text-rose-700 inline-flex items-center gap-1 text-xs"><AlertTriangle size={12}/> No Cost</span>}
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <button data-testid={`pay-mechanic-btn-${w.id}`}
                      onClick={() => onOpenPay(w)}
                      className="text-xs px-2 py-1 border rounded-sm inline-flex items-center gap-1 hover:bg-zinc-950 hover:text-white">
                      <Wallet size={12} /> Pay
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {rows.length > 0 && (
        <div className="border-t pt-3 space-y-2" data-testid="labour-draft-rows">
          {rows.map((r) => (
            <div key={r.key} className="grid grid-cols-12 gap-2 items-end border rounded-sm p-2 bg-zinc-50"
                 data-testid={`labour-draft-row-${r.key}`}>
              <div className="col-span-3">
                <div className="text-[9px] uppercase tracking-wider text-zinc-500">Mechanic *</div>
                <select value={r.mechanic_id} onChange={(e) => upd(r.key, { mechanic_id: e.target.value })}
                  className={ic} disabled={!!r.saved_wo_id} data-testid="labour-mechanic-select">
                  <option value="">— Select mechanic —</option>
                  {(mechanics.data || []).filter((m) => m.is_active !== false).map((m) =>
                    <option key={m.id} value={m.id}>{m.name}</option>)}
                </select>
              </div>
              <div className="col-span-2">
                <div className="text-[9px] uppercase tracking-wider text-zinc-500">Work Date *</div>
                <input type="date" value={r.work_date}
                  onChange={(e) => upd(r.key, { work_date: e.target.value })}
                  className={ic} disabled={!!r.saved_wo_id} data-testid="labour-work-date" />
              </div>
              <div className="col-span-2">
                <div className="text-[9px] uppercase tracking-wider text-zinc-500">Amount * (₹)</div>
                <input type="number" step="0.01" min="0.01" value={r.amount}
                  onChange={(e) => upd(r.key, { amount: e.target.value })}
                  className={ic} disabled={!!r.saved_wo_id} data-testid="labour-amount" />
              </div>
              <div className="col-span-2">
                <div className="text-[9px] uppercase tracking-wider text-zinc-500">Hours</div>
                <input type="number" step="0.1" min="0" value={r.hours_worked}
                  onChange={(e) => upd(r.key, { hours_worked: e.target.value })}
                  className={ic} data-testid="labour-hours" />
              </div>
              <div className="col-span-2">
                <div className="text-[9px] uppercase tracking-wider text-zinc-500">Category</div>
                <input value={r.category} onChange={(e) => upd(r.key, { category: e.target.value })}
                  className={ic} data-testid="labour-category" />
              </div>
              <div className="col-span-1 flex flex-col gap-1">
                {!r.saved_expense_id && !r.error && (
                  <button data-testid="save-labour-btn"
                    disabled={r.busy || !r.mechanic_id || !(Number(r.amount) > 0)}
                    onClick={() => saveRow(r)}
                    className="text-xs px-2 py-1 bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
                    {r.busy ? "Saving…" : "Save Labour"}
                  </button>
                )}
                {r.error && r.saved_wo_id && !r.saved_expense_id && (
                  <button data-testid="retry-labour-cost-btn"
                    disabled={r.busy}
                    onClick={() => retryCost(r)}
                    className="text-xs px-2 py-1 bg-rose-600 text-white rounded-sm hover:bg-rose-700 disabled:opacity-50">
                    {r.busy ? "Retrying…" : "Retry Cost"}
                  </button>
                )}
                {r.saved_expense_id && (
                  <span className="text-[10px] text-emerald-700 inline-flex items-center gap-1"
                        data-testid="labour-twinned-badge">
                    <CheckCircle2 size={12}/> Twinned
                  </span>
                )}
                {!r.saved_wo_id && !r.saved_expense_id && (
                  <button onClick={() => rm(r.key)} className="text-[10px] text-zinc-500 hover:text-rose-700">Remove</button>
                )}
              </div>
              <div className="col-span-12">
                <div className="text-[9px] uppercase tracking-wider text-zinc-500">Narration</div>
                <input value={r.narration} onChange={(e) => upd(r.key, { narration: e.target.value })}
                  className={ic} data-testid="labour-narration" />
              </div>
              {r.error && (
                <div className="col-span-12 text-[11px] text-rose-700 border-t pt-1" data-testid="labour-error">
                  <AlertTriangle size={12} className="inline mr-1" /> {r.error}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {rows.length === 0 && existingWos.length === 0 && (
        <div className="text-xs text-zinc-500 border-t pt-3" data-testid="labour-empty">
          No labour recorded yet. Click <b>Add Labour Row</b> to enter a mechanic work-order — the cost is booked automatically.
        </div>
      )}
    </div>
  );
}

/* ------------------- Small helpers ------------------- */
function Kpi({ label, value, testid, hi }) {
  return (
    <div className={"border rounded-sm p-3 " + (hi ? "border-zinc-950 bg-white" : "bg-white")} data-testid={testid}>
      <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">{label}</div>
      <div className={"mt-1 font-semibold " + (hi ? "text-xl" : "text-base")}>{value}</div>
    </div>
  );
}
function Info({ label, value, testid }) {
  return (
    <div data-testid={testid}>
      <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">{label}</div>
      <div className="mt-0.5 text-sm">{value}</div>
    </div>
  );
}
function L({ label, children }) {
  return (
    <label>
      <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 mb-1">{label}</div>
      {children}
    </label>
  );
}
