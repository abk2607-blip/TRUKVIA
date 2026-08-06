import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, API, fmtCurrency } from "@/api";
import { toast } from "sonner";
import { ArrowLeft, FileText } from "lucide-react";
import FileAttachments from "@/components/FileAttachments";

const EMPTY = {
  customer_id: "",
  date: new Date().toISOString().slice(0, 10),
  vehicle_number: "",
  vehicle_id: "",
  vehicle_type: "own",
  supplier_name: "",
  supplier_freight: 0,
  supplier_freight_mode: "per_ton",
  supplier_rate_per_ton: 0,
  supplier_fixed_amount: 0,
  supplier_round_trip_kms: 0,
  supplier_rate_per_km_per_ton: 0,
  supplier_loading_point: "",
  supplier_unloading_point: "",
  supplier_material: "",
  supplier_quantity: 0,
  supplier_advance: 0,
  supplier_other_recoveries: 0,
  supplier_net_payable: 0,
  driver_id: "",
  driver_name: "",
  driver_mobile: "",
  product_id: "",
  load_details: "Bitumen VG 40",
  hsn_sac: "",
  tons: 0,
  from_location: "",
  to_location: "",
  from_pincode: "",
  to_pincode: "",
  freight_mode: "per_ton",
  rate_per_ton: 0,
  fixed_amount: 0,
  round_trip_kms: 0,
  rate_per_km_per_ton: 0,
  // Loading / Unloading tracking
  loading_date: "",
  unloading_date: "",
  loaded_qty: 0,
  unloaded_qty: 0,
  shortage_qty: 0,
  excess_qty: 0,
  product_rate_per_mt: 0,
  shortage_amount: 0,
  excess_amount: 0,
  shortage_amount_override: false,
  excess_amount_override: false,
  // Halting / Waiting charges
  total_halting_days: 0,
  grace_days: 4,
  chargeable_halting_days: 0,
  halting_rate_per_day: 0,
  halting_amount: 0,
  halting_amount_override: false,
  expenses: {
    diesel: 0, toll: 0, batta: 0, repair: 0, other: 0,
    firewood: 0, other_desc: "",
    diesel_from_customer_qty: 0, diesel_from_customer_rate: 0, diesel_from_customer_amount: 0,
    shortage_qty: 0, shortage_amount: 0, cash_advance_received: 0,
  },
  notes: "",
  lr_number: "",
  lr_time: "",
  consignor_name: "",
  consignor_address: "",
  consignee_site_location: "",
  consignee_site_contact: "",
  external_invoice_no: "",
  customer_invoice_no: "",
  customer_purchased_at: "",
  invoice_value: 0,
  waybill_no: "",
  gross_weight: 0,
  tare_weight: 0,
  seal_numbers: "",
};

export default function TripForm() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { id } = useParams();
  const isEdit = Boolean(id);
  const [form, setForm] = useState(EMPTY);

  const { data: customers = [] } = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get("/customers")).data });
  const { data: drivers = [] } = useQuery({ queryKey: ["drivers"], queryFn: async () => (await api.get("/drivers")).data });
  const { data: products = [] } = useQuery({ queryKey: ["products"], queryFn: async () => (await api.get("/products")).data });
  const { data: vehicles = [] } = useQuery({ queryKey: ["vehicles"], queryFn: async () => (await api.get("/vehicles")).data });

  const { data: trip } = useQuery({
    queryKey: ["trip", id],
    queryFn: async () => (await api.get("/trips")).data.find((t) => t.id === id),
    enabled: isEdit,
  });

  useEffect(() => {
    if (trip) setForm({ ...EMPTY, ...trip, expenses: { ...EMPTY.expenses, ...(trip.expenses || {}) } });
  }, [trip]);

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        ...form,
        tons: Number(form.tons),
        rate_per_ton: Number(form.rate_per_ton),
        fixed_amount: Number(form.fixed_amount),
        round_trip_kms: Number(form.round_trip_kms),
        rate_per_km_per_ton: Number(form.rate_per_km_per_ton),
        supplier_freight: Number(form.supplier_freight || 0),
        supplier_rate_per_ton: Number(form.supplier_rate_per_ton || 0),
        supplier_fixed_amount: Number(form.supplier_fixed_amount || 0),
        supplier_round_trip_kms: Number(form.supplier_round_trip_kms || 0),
        supplier_rate_per_km_per_ton: Number(form.supplier_rate_per_km_per_ton || 0),
        supplier_quantity: Number(form.supplier_quantity || 0),
        supplier_advance: Number(form.supplier_advance || 0),
        supplier_other_recoveries: Number(form.supplier_other_recoveries || 0),
        loaded_qty: Number(form.loaded_qty || 0),
        unloaded_qty: Number(form.unloaded_qty || 0),
        excess_qty: Number(form.excess_qty || 0),
        shortage_qty: Number(form.shortage_qty || 0),
        product_rate_per_mt: Number(form.product_rate_per_mt || 0),
        shortage_amount: Number(form.shortage_amount || 0),
        excess_amount: Number(form.excess_amount || 0),
        shortage_amount_override: !!form.shortage_amount_override,
        excess_amount_override: !!form.excess_amount_override,
        total_halting_days: Number(form.total_halting_days || 0),
        grace_days: Number(form.grace_days || 0),
        chargeable_halting_days: Number(form.chargeable_halting_days || 0),
        halting_rate_per_day: Number(form.halting_rate_per_day || 0),
        halting_amount: Number(form.halting_amount || 0),
        halting_amount_override: !!form.halting_amount_override,
        invoice_value: Number(form.invoice_value || 0),
        gross_weight: Number(form.gross_weight || 0),
        tare_weight: Number(form.tare_weight || 0),
        expenses: Object.fromEntries(Object.entries(form.expenses).map(([k, v]) => [k, k === "other_desc" ? v : Number(v || 0)])),
      };
      if (isEdit) return (await api.put(`/trips/${id}`, payload)).data;
      return (await api.post("/trips", payload)).data;
    },
    onSuccess: () => {
      toast.success(isEdit ? "Trip updated" : "Trip created");
      qc.invalidateQueries({ queryKey: ["trips"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      nav("/trips");
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  // Live computed
  const freight = form.freight_mode === "per_ton"
    ? Number(form.tons || 0) * Number(form.rate_per_ton || 0)
    : (Number(form.round_trip_kms || 0) > 0 && Number(form.rate_per_km_per_ton || 0) > 0)
      ? Number(form.tons || 0) * Number(form.round_trip_kms || 0) * Number(form.rate_per_km_per_ton || 0)
      : Number(form.fixed_amount || 0);
  const totalExpense = Object.entries(form.expenses).reduce((s, [k, v]) => s + (k === "other_desc" ? 0 : Number(v || 0)), 0);
  const profit = freight - totalExpense;

  // Supplier live compute
  const supQty = Number(form.supplier_quantity || 0) > 0 ? Number(form.supplier_quantity) : Number(form.tons || 0);
  let supplierFreightLive = Number(form.supplier_freight || 0);
  if (form.supplier_freight_mode === "per_ton" && Number(form.supplier_rate_per_ton || 0) > 0) {
    supplierFreightLive = supQty * Number(form.supplier_rate_per_ton);
  } else if (form.supplier_freight_mode === "fixed") {
    if (Number(form.supplier_round_trip_kms || 0) > 0 && Number(form.supplier_rate_per_km_per_ton || 0) > 0) {
      supplierFreightLive = supQty * Number(form.supplier_round_trip_kms) * Number(form.supplier_rate_per_km_per_ton);
    } else if (Number(form.supplier_fixed_amount || 0) > 0) {
      supplierFreightLive = Number(form.supplier_fixed_amount);
    }
  }
  const supplierNetPayable = supplierFreightLive - Number(form.supplier_advance || 0) - Number(form.supplier_other_recoveries || 0);
  const supplierProfit = freight - (supplierFreightLive - Number(form.supplier_advance || 0));

  // Loading/Unloading auto-diff
  const loadedQ = Number(form.loaded_qty || 0);
  const unloadedQ = Number(form.unloaded_qty || 0);
  const qtyDiff = Number((loadedQ - unloadedQ).toFixed(3));
  const shortageQtyLive = (loadedQ > 0 || unloadedQ > 0) && qtyDiff > 0 ? qtyDiff : 0;
  const excessQtyLive = (loadedQ > 0 || unloadedQ > 0) && qtyDiff < 0 ? Math.abs(qtyDiff) : 0;
  const productRate = Number(form.product_rate_per_mt || 0);
  const shortageAmountLive = form.shortage_amount_override
    ? Number(form.shortage_amount || 0)
    : Number((productRate * shortageQtyLive).toFixed(2));
  const excessAmountLive = form.excess_amount_override
    ? Number(form.excess_amount || 0)
    : Number((productRate * excessQtyLive).toFixed(2));

  // Halting auto-calc
  let totalHaltingDaysLive = 0;
  if (form.loading_date && form.unloading_date) {
    const ld = new Date(form.loading_date);
    const ud = new Date(form.unloading_date);
    const diffMs = ud - ld;
    totalHaltingDaysLive = Math.max(Math.floor(diffMs / 86400000), 0);
  }
  const graceDaysLive = Math.max(Number(form.grace_days || 0), 0);
  const autoChargeableDays = Math.max(totalHaltingDaysLive - graceDaysLive, 0);
  const chargeableDaysLive = form.halting_amount_override
    ? Number(form.chargeable_halting_days || 0)
    : autoChargeableDays;
  const haltingRateLive = Number(form.halting_rate_per_day || 0);
  const haltingAmountLive = form.halting_amount_override
    ? Number(form.halting_amount || 0)
    : Number((chargeableDaysLive * haltingRateLive).toFixed(2));

  // Keep auto-derived fields in sync when user hasn't overridden
  useEffect(() => {
    if (!form.shortage_amount_override) {
      setForm((f) => ({ ...f, shortage_qty: shortageQtyLive, excess_qty: excessQtyLive, shortage_amount: shortageAmountLive, excess_amount: excessAmountLive }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadedQ, unloadedQ, productRate, form.shortage_amount_override, form.excess_amount_override]);

  useEffect(() => {
    if (!form.halting_amount_override) {
      setForm((f) => ({ ...f, total_halting_days: totalHaltingDaysLive, chargeable_halting_days: autoChargeableDays, halting_amount: haltingAmountLive }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.loading_date, form.unloading_date, form.grace_days, form.halting_rate_per_day, form.halting_amount_override]);

  const setExp = (k, v) => setForm({ ...form, expenses: { ...form.expenses, [k]: v } });

  return (
    <div className="space-y-6" data-testid="trip-form-page">
      <header className="flex items-center gap-3 border-b border-zinc-200 pb-4">
        <button onClick={() => nav(-1)} className="p-2 border border-zinc-200 rounded-sm"><ArrowLeft size={16} /></button>
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Trip Entry</div>
          <h1 className="text-3xl font-black tracking-tighter">
            <span className="telugu">{isEdit ? "ట్రిప్ ఎడిట్" : "కొత్త ట్రిప్"}</span>
            <span className="text-zinc-400"> · {isEdit ? "Edit Trip" : "New Trip"}</span>
          </h1>
        </div>
      </header>

      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-6">
        {isEdit && form.status === "invoiced" && (
          <div data-testid="invoiced-edit-warning" className="border border-amber-300 bg-amber-50 rounded-sm p-4 text-sm">
            <div className="font-bold text-amber-900 uppercase tracking-wider text-xs mb-1">⚠ Invoiced Trip</div>
            <div className="text-amber-800">
              This trip is linked to <span className="font-mono font-semibold">invoice #{trip?.invoice_id?.slice(-8) || "—"}</span>. Any changes here will automatically recalculate the linked invoice totals.
            </div>
          </div>
        )}
        {/* Basic Details */}
        <Section title="వివరాలు · Trip Details">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Field label="Date · తేదీ" required>
              <input type="date" data-testid="trip-date" required value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Customer · కస్టమర్" required>
              <select data-testid="trip-customer" required value={form.customer_id} onChange={(e) => setForm({ ...form, customer_id: e.target.value })} className={inputCls}>
                <option value="">-- Select Customer --</option>
                {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
            <Field label="Vehicle No · వాహనం" required>
              {vehicles.length > 0 ? (
                <>
                  <select
                    data-testid="trip-vehicle-select"
                    value={vehicles.find((v) => v.vehicle_number === form.vehicle_number)?.id || ""}
                    onChange={(e) => {
                      const v = vehicles.find((x) => x.id === e.target.value);
                      if (v) {
                        setForm({
                          ...form,
                          vehicle_id: v.id,
                          vehicle_number: v.vehicle_number,
                          vehicle_type: v.vehicle_type || "own",
                          supplier_name: v.vehicle_type === "supplier" ? (v.supplier_name || "") : "",
                        });
                      } else {
                        setForm({ ...form, vehicle_id: "", vehicle_number: "" });
                      }
                    }}
                    className={inputCls}
                  >
                    <option value="">-- Select from Master --</option>
                    {vehicles.map((v) => <option key={v.id} value={v.id}>{v.vehicle_number}{v.vehicle_type === "supplier" ? " · Supplier" : ""}{v.owner_name ? ` · ${v.owner_name}` : ""}</option>)}
                  </select>
                  <input data-testid="trip-vehicle" required value={form.vehicle_number} onChange={(e) => setForm({ ...form, vehicle_number: e.target.value.toUpperCase() })} className={`${inputCls} mt-1`} placeholder="Or type: AP16TA1234" />
                </>
              ) : (
                <input data-testid="trip-vehicle" required value={form.vehicle_number} onChange={(e) => setForm({ ...form, vehicle_number: e.target.value.toUpperCase() })} className={inputCls} placeholder="AP16TA1234" />
              )}
            </Field>
            <Field label="Driver · డ్రైవర్">
              <select
                data-testid="trip-driver"
                value={form.driver_id || ""}
                onChange={(e) => {
                  const id = e.target.value;
                  const d = drivers.find((x) => x.id === id);
                  setForm({ ...form, driver_id: id, driver_name: d?.name || "" });
                }}
                className={inputCls}
              >
                <option value="">-- Select Driver --</option>
                {drivers.map((d) => <option key={d.id} value={d.id}>{d.name}{d.phone ? ` · ${d.phone}` : ""}</option>)}
              </select>
            </Field>
            <Field label="Product / Load · లోడ్">
              <select
                data-testid="trip-product"
                value={form.product_id || ""}
                onChange={(e) => {
                  const pid = e.target.value;
                  const p = products.find((x) => x.id === pid);
                  if (p) {
                    setForm({
                      ...form,
                      product_id: pid,
                      load_details: p.name,
                      hsn_sac: p.hsn_sac,
                      rate_per_ton: form.freight_mode === "per_ton" && p.default_rate ? p.default_rate : form.rate_per_ton,
                    });
                  } else {
                    setForm({ ...form, product_id: "" });
                  }
                }}
                className={inputCls}
              >
                <option value="">-- Custom / Type Below --</option>
                {products.map((p) => <option key={p.id} value={p.id}>{p.name} (HSN {p.hsn_sac})</option>)}
              </select>
              <input data-testid="trip-load" value={form.load_details} onChange={(e) => setForm({ ...form, load_details: e.target.value, product_id: "" })} className={`${inputCls} mt-1`} placeholder="Load details" />
            </Field>
            <Field label="Tons · టన్నులు" required>
              <input data-testid="trip-tons" required type="number" step="0.01" min="0" value={form.tons} onChange={(e) => setForm({ ...form, tons: e.target.value })} className={inputCls} />
            </Field>
            <Field label="From · నుండి">
              <input data-testid="trip-from" value={form.from_location} onChange={(e) => setForm({ ...form, from_location: e.target.value })} className={inputCls} />
            </Field>
            <Field label="To · వరకు">
              <input data-testid="trip-to" value={form.to_location} onChange={(e) => setForm({ ...form, to_location: e.target.value })} className={inputCls} />
            </Field>
          </div>
        </Section>

        {/* Freight */}
        <Section title="ఫ్రైట్ · Freight Calculation">
          <div className="flex gap-3 mb-4">
            <label data-testid="freight-mode-per-ton" className={`flex-1 border p-3 rounded-sm cursor-pointer ${form.freight_mode === "per_ton" ? "border-zinc-950 bg-zinc-50" : "border-zinc-200"}`}>
              <input type="radio" name="mode" checked={form.freight_mode === "per_ton"} onChange={() => setForm({ ...form, freight_mode: "per_ton" })} className="mr-2" />
              <span className="font-semibold text-sm"><span className="telugu">టన్ను ప్రకారం</span> · Per Ton</span>
              <div className="text-[11px] text-zinc-500 mt-1">Tons × Rate</div>
            </label>
            <label data-testid="freight-mode-fixed" className={`flex-1 border p-3 rounded-sm cursor-pointer ${form.freight_mode === "fixed" ? "border-zinc-950 bg-zinc-50" : "border-zinc-200"}`}>
              <input type="radio" name="mode" checked={form.freight_mode === "fixed"} onChange={() => setForm({ ...form, freight_mode: "fixed" })} className="mr-2" />
              <span className="font-semibold text-sm"><span className="telugu">రౌండ్ ట్రిప్</span> · Round Trip</span>
              <div className="text-[11px] text-zinc-500 mt-1">Tons × Round Trip KMs × Rate</div>
            </label>
          </div>

          {form.freight_mode === "per_ton" ? (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Field label="Rate per Ton (₹) · రేటు">
                <input data-testid="trip-rate-per-ton" type="number" step="0.01" min="0" value={form.rate_per_ton} onChange={(e) => setForm({ ...form, rate_per_ton: e.target.value })} className={inputCls} />
              </Field>
              <div className="md:col-span-2 flex items-end justify-end">
                <div className="bg-amber-50 border border-amber-200 px-4 py-3 rounded-sm text-right" data-testid="freight-preview">
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Freight · ఫ్రైట్</div>
                  <div className="font-mono text-2xl font-bold text-amber-900">{fmtCurrency(freight)}</div>
                  <div className="text-[10px] text-zinc-500 mt-1 font-mono">{Number(form.tons || 0).toFixed(2)} × ₹{Number(form.rate_per_ton || 0).toFixed(2)}</div>
                </div>
              </div>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Field label="Round Trip KMs · రౌండ్ ట్రిప్ KM">
                  <input data-testid="trip-round-trip-kms" type="number" step="0.01" min="0" value={form.round_trip_kms} onChange={(e) => setForm({ ...form, round_trip_kms: e.target.value })} className={inputCls} placeholder="e.g. 450" />
                </Field>
                <Field label="Rate (₹/ton/km) · రేటు">
                  <input data-testid="trip-rate-per-km-per-ton" type="number" step="0.01" min="0" value={form.rate_per_km_per_ton} onChange={(e) => setForm({ ...form, rate_per_km_per_ton: e.target.value })} className={inputCls} placeholder="e.g. 3.5" />
                </Field>
                <Field label="Or Fixed Lump Sum (₹)">
                  <input data-testid="trip-fixed-amount" type="number" step="0.01" min="0" value={form.fixed_amount} onChange={(e) => setForm({ ...form, fixed_amount: e.target.value })} className={inputCls} placeholder="Used only if KMs/Rate = 0" />
                </Field>
              </div>
              <div className="mt-4 flex justify-end">
                <div className="bg-amber-50 border border-amber-200 px-4 py-3 rounded-sm text-right" data-testid="freight-preview">
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Freight · ఫ్రైట్</div>
                  <div className="font-mono text-2xl font-bold text-amber-900">{fmtCurrency(freight)}</div>
                  <div className="text-[10px] text-zinc-500 mt-1 font-mono">
                    {Number(form.round_trip_kms || 0) > 0 && Number(form.rate_per_km_per_ton || 0) > 0
                      ? `${Number(form.tons || 0).toFixed(2)} × ${Number(form.round_trip_kms || 0).toFixed(2)}km × ₹${Number(form.rate_per_km_per_ton || 0).toFixed(2)}`
                      : `Lump sum ₹${Number(form.fixed_amount || 0).toFixed(2)}`}
                  </div>
                </div>
              </div>
            </>
          )}
        </Section>

        {/* Loading / Unloading Details */}
        <Section title="Loading &amp; Unloading Details · లోడ్/అన్‌లోడ్">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Field label="Loading Date">
              <input data-testid="trip-loading-date" type="date" value={form.loading_date} onChange={(e) => setForm({ ...form, loading_date: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Unloading Date">
              <input data-testid="trip-unloading-date" type="date" value={form.unloading_date} onChange={(e) => setForm({ ...form, unloading_date: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Loaded Qty (MT)">
              <input data-testid="trip-loaded-qty" type="number" step="0.001" min="0" value={form.loaded_qty} onChange={(e) => setForm({ ...form, loaded_qty: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Unloaded Qty (MT)">
              <input data-testid="trip-unloaded-qty" type="number" step="0.001" min="0" value={form.unloaded_qty} onChange={(e) => setForm({ ...form, unloaded_qty: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Product Rate (₹ / MT)">
              <input data-testid="trip-product-rate" type="number" step="0.01" min="0" value={form.product_rate_per_mt} onChange={(e) => setForm({ ...form, product_rate_per_mt: e.target.value, shortage_amount_override: false, excess_amount_override: false })} className={inputCls} placeholder="Optional" />
            </Field>
            <div className="border border-zinc-200 p-2 rounded-sm text-center">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Shortage Qty</div>
              <div className="font-mono text-sm font-bold text-rose-700">{shortageQtyLive.toFixed(3)} MT</div>
            </div>
            <div className="border border-zinc-200 p-2 rounded-sm text-center">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Excess Qty</div>
              <div className="font-mono text-sm font-bold text-emerald-700">{excessQtyLive.toFixed(3)} MT</div>
            </div>
            <Field label={
              <span>Shortage Amount (₹) <button type="button" onClick={() => setForm({ ...form, shortage_amount_override: !form.shortage_amount_override })} className={`ml-1 text-[9px] uppercase tracking-wider ${form.shortage_amount_override ? "text-amber-700" : "text-zinc-400"}`}>{form.shortage_amount_override ? "manual" : "auto"}</button></span>
            }>
              <input data-testid="trip-shortage-amount" type="number" step="0.01" min="0" value={form.shortage_amount_override ? form.shortage_amount : shortageAmountLive} disabled={!form.shortage_amount_override} onChange={(e) => setForm({ ...form, shortage_amount: e.target.value })} className={`${inputCls} disabled:bg-zinc-50 disabled:text-zinc-600`} />
            </Field>
            <Field label={
              <span>Excess Amount (₹) <button type="button" onClick={() => setForm({ ...form, excess_amount_override: !form.excess_amount_override })} className={`ml-1 text-[9px] uppercase tracking-wider ${form.excess_amount_override ? "text-amber-700" : "text-zinc-400"}`}>{form.excess_amount_override ? "manual" : "auto"}</button></span>
            }>
              <input data-testid="trip-excess-amount" type="number" step="0.01" min="0" value={form.excess_amount_override ? form.excess_amount : excessAmountLive} disabled={!form.excess_amount_override} onChange={(e) => setForm({ ...form, excess_amount: e.target.value })} className={`${inputCls} disabled:bg-zinc-50 disabled:text-zinc-600`} />
            </Field>
          </div>
        </Section>

        {/* Halting / Waiting Charges */}
        <Section title="Halting / Waiting Charges · హాల్టింగ్">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="border border-zinc-200 p-2 rounded-sm text-center">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Total Days</div>
              <div className="font-mono text-lg font-bold" data-testid="trip-total-halting-days">{totalHaltingDaysLive}</div>
              <div className="text-[9px] text-zinc-400 mt-0.5">Auto from dates</div>
            </div>
            <Field label="Grace Days">
              <input data-testid="trip-grace-days" type="number" min="0" step="1" value={form.grace_days} onChange={(e) => setForm({ ...form, grace_days: e.target.value, halting_amount_override: false })} className={inputCls} />
            </Field>
            <Field label={
              <span>Chargeable Days <button type="button" onClick={() => setForm({ ...form, halting_amount_override: !form.halting_amount_override })} className={`ml-1 text-[9px] uppercase tracking-wider ${form.halting_amount_override ? "text-amber-700" : "text-zinc-400"}`}>{form.halting_amount_override ? "manual" : "auto"}</button></span>
            }>
              <input data-testid="trip-chargeable-days" type="number" min="0" step="1" value={form.halting_amount_override ? form.chargeable_halting_days : autoChargeableDays} disabled={!form.halting_amount_override} onChange={(e) => setForm({ ...form, chargeable_halting_days: e.target.value })} className={`${inputCls} disabled:bg-zinc-50 disabled:text-zinc-600`} />
            </Field>
            <Field label="Halting Rate (₹ / Day)">
              <input data-testid="trip-halting-rate" type="number" step="0.01" min="0" value={form.halting_rate_per_day} onChange={(e) => setForm({ ...form, halting_rate_per_day: e.target.value, halting_amount_override: false })} className={inputCls} />
            </Field>
            <Field label={
              <span>Halting Amount (₹) <span className={`ml-1 text-[9px] uppercase tracking-wider ${form.halting_amount_override ? "text-amber-700" : "text-zinc-400"}`}>{form.halting_amount_override ? "manual" : "auto"}</span></span>
            }>
              <input data-testid="trip-halting-amount" type="number" step="0.01" min="0" value={form.halting_amount_override ? form.halting_amount : haltingAmountLive} disabled={!form.halting_amount_override} onChange={(e) => setForm({ ...form, halting_amount: e.target.value })} className={`${inputCls} disabled:bg-zinc-50 disabled:text-zinc-600 font-bold`} />
            </Field>
          </div>
          <div className="mt-3 text-[11px] text-zinc-500 bg-zinc-50 border border-zinc-200 rounded-sm p-2">
            <span className="font-bold">Rule:</span> First {form.grace_days || 4} days = grace period (free). From day {(Number(form.grace_days) || 4) + 1} onwards, halting is charged at ₹{Number(form.halting_rate_per_day || 0).toLocaleString("en-IN")} / day. All fields editable if customer contract differs.
          </div>
        </Section>

        {/* Expenses */}
        <Section title="ఖర్చులు · Expenses">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {[
              ["diesel", "Diesel · డీజిల్"],
              ["toll", "Toll · టోల్"],
              ["batta", "Driver Batta · బాటా"],
              ["repair", "Repair · రిపేర్"],
              ["other", "Other · ఇతర"],
            ].map(([k, lbl]) => (
              <Field key={k} label={lbl}>
                <input data-testid={`exp-${k}`} type="number" step="0.01" min="0" value={form.expenses[k]} onChange={(e) => setExp(k, e.target.value)} className={inputCls} />
              </Field>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-3 gap-4">
            <div className="border border-zinc-200 p-3 rounded-sm text-center">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Total Expense</div>
              <div className="font-mono text-lg font-bold text-rose-700">{fmtCurrency(totalExpense)}</div>
            </div>
            <div className="border border-zinc-200 p-3 rounded-sm text-center">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Freight</div>
              <div className="font-mono text-lg font-bold">{fmtCurrency(freight)}</div>
            </div>
            <div className={`border p-3 rounded-sm text-center ${profit >= 0 ? "border-emerald-300 bg-emerald-50" : "border-rose-300 bg-rose-50"}`} data-testid="trip-profit-preview">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Profit · లాభం</div>
              <div className={`font-mono text-lg font-bold ${profit >= 0 ? "text-emerald-800" : "text-rose-800"}`}>{fmtCurrency(profit)}</div>
            </div>
          </div>
        </Section>

        {form.vehicle_type === "supplier" && (
          <Section title="Supplier Vehicle · సప్లయర్ వాహనం">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Field label="Supplier Name">
                <input data-testid="trip-supplier-name" value={form.supplier_name} onChange={(e) => setForm({ ...form, supplier_name: e.target.value })} className={inputCls} />
              </Field>
              <Field label="Loading Point">
                <input data-testid="trip-supplier-loading" value={form.supplier_loading_point} onChange={(e) => setForm({ ...form, supplier_loading_point: e.target.value })} className={inputCls} placeholder="e.g. HPCL Kondapalli" />
              </Field>
              <Field label="Unloading Point">
                <input data-testid="trip-supplier-unloading" value={form.supplier_unloading_point} onChange={(e) => setForm({ ...form, supplier_unloading_point: e.target.value })} className={inputCls} placeholder="e.g. Vijayawada Site" />
              </Field>
              <Field label="Material">
                <input data-testid="trip-supplier-material" value={form.supplier_material} onChange={(e) => setForm({ ...form, supplier_material: e.target.value })} className={inputCls} placeholder="Bitumen VG 40" />
              </Field>
              <Field label="Quantity (MT)">
                <input data-testid="trip-supplier-qty" type="number" step="0.01" min="0" value={form.supplier_quantity} onChange={(e) => setForm({ ...form, supplier_quantity: e.target.value })} className={inputCls} placeholder="If empty, trip Tons used" />
              </Field>
              <Field label="Freight Mode">
                <select data-testid="trip-supplier-mode" value={form.supplier_freight_mode} onChange={(e) => setForm({ ...form, supplier_freight_mode: e.target.value })} className={inputCls}>
                  <option value="per_ton">Per Ton</option>
                  <option value="fixed">Fixed / Round Trip</option>
                </select>
              </Field>
              {form.supplier_freight_mode === "per_ton" ? (
                <Field label="Supplier Rate / MT (₹)">
                  <input data-testid="trip-supplier-rate" type="number" step="0.01" min="0" value={form.supplier_rate_per_ton} onChange={(e) => setForm({ ...form, supplier_rate_per_ton: e.target.value })} className={inputCls} />
                </Field>
              ) : (
                <>
                  <Field label="Distance (Round Trip KMs)">
                    <input data-testid="trip-supplier-kms" type="number" step="0.01" min="0" value={form.supplier_round_trip_kms} onChange={(e) => setForm({ ...form, supplier_round_trip_kms: e.target.value })} className={inputCls} />
                  </Field>
                  <Field label="Rate (₹ / ton / km)">
                    <input data-testid="trip-supplier-rate-km" type="number" step="0.01" min="0" value={form.supplier_rate_per_km_per_ton} onChange={(e) => setForm({ ...form, supplier_rate_per_km_per_ton: e.target.value })} className={inputCls} />
                  </Field>
                  <Field label="Fixed Amount (₹)">
                    <input data-testid="trip-supplier-fixed" type="number" step="0.01" min="0" value={form.supplier_fixed_amount} onChange={(e) => setForm({ ...form, supplier_fixed_amount: e.target.value })} className={inputCls} placeholder="Used only if KMs/Rate = 0" />
                  </Field>
                </>
              )}
              <Field label="Supplier Freight (₹)">
                <input data-testid="trip-supplier-freight" type="number" step="0.01" min="0" value={form.supplier_freight} onChange={(e) => setForm({ ...form, supplier_freight: e.target.value })} className={inputCls} placeholder="Auto-computed" />
              </Field>
              <Field label="Supplier Advance (₹)">
                <input data-testid="trip-supplier-advance" type="number" step="0.01" min="0" value={form.supplier_advance} onChange={(e) => setForm({ ...form, supplier_advance: e.target.value })} className={inputCls} />
              </Field>
              <Field label="Other Recoveries (₹)">
                <input data-testid="trip-supplier-recovery" type="number" step="0.01" min="0" value={form.supplier_other_recoveries} onChange={(e) => setForm({ ...form, supplier_other_recoveries: e.target.value })} className={inputCls} placeholder="Damages, shortage etc." />
              </Field>
            </div>
            <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="border border-zinc-200 p-3 rounded-sm text-center">
                <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Supplier Freight (Live)</div>
                <div className="font-mono text-lg font-bold">{fmtCurrency(supplierFreightLive)}</div>
              </div>
              <div className="border border-zinc-200 p-3 rounded-sm text-center">
                <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Net Payable to Supplier</div>
                <div className="font-mono text-lg font-bold text-rose-700">{fmtCurrency(supplierNetPayable)}</div>
                <div className="text-[10px] text-zinc-500 mt-1">Freight − Advance − Recoveries</div>
              </div>
              <div className={`border p-3 rounded-sm text-center ${supplierProfit >= 0 ? "border-emerald-300 bg-emerald-50" : "border-rose-300 bg-rose-50"}`}>
                <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Trip Profit</div>
                <div className={`font-mono text-lg font-bold ${supplierProfit >= 0 ? "text-emerald-800" : "text-rose-800"}`}>{fmtCurrency(supplierProfit)}</div>
                <div className="text-[10px] text-zinc-500 mt-1">Customer − (Supplier Freight − Advance)</div>
              </div>
            </div>
          </Section>
        )}

        <Section title="Extra Recovery & Expenses (Optional)">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Field label="Diesel from Customer — Qty (L)">
              <input data-testid="trip-diesel-cust-qty" type="number" step="0.01" min="0" value={form.expenses.diesel_from_customer_qty} onChange={(e) => setExp("diesel_from_customer_qty", e.target.value)} className={inputCls} />
            </Field>
            <Field label="Diesel from Customer — Rate">
              <input data-testid="trip-diesel-cust-rate" type="number" step="0.01" min="0" value={form.expenses.diesel_from_customer_rate} onChange={(e) => setExp("diesel_from_customer_rate", e.target.value)} className={inputCls} />
            </Field>
            <Field label="Diesel from Customer — Amount">
              <input data-testid="trip-diesel-cust-amt" type="number" step="0.01" min="0" value={form.expenses.diesel_from_customer_amount || (Number(form.expenses.diesel_from_customer_qty) * Number(form.expenses.diesel_from_customer_rate)).toFixed(2)} onChange={(e) => setExp("diesel_from_customer_amount", e.target.value)} className={inputCls} />
            </Field>
            <Field label="Shortage Qty (MT/L)">
              <input data-testid="trip-shortage-qty" type="number" step="0.01" min="0" value={form.expenses.shortage_qty} onChange={(e) => setExp("shortage_qty", e.target.value)} className={inputCls} />
            </Field>
            <Field label="Shortage Amount (₹)">
              <input data-testid="trip-shortage-amt" type="number" step="0.01" min="0" value={form.expenses.shortage_amount} onChange={(e) => setExp("shortage_amount", e.target.value)} className={inputCls} />
            </Field>
            <Field label="Cash Advance Received">
              <input data-testid="trip-cash-advance" type="number" step="0.01" min="0" value={form.expenses.cash_advance_received} onChange={(e) => setExp("cash_advance_received", e.target.value)} className={inputCls} />
            </Field>
            <Field label="Firewood Expense">
              <input data-testid="trip-firewood" type="number" step="0.01" min="0" value={form.expenses.firewood} onChange={(e) => setExp("firewood", e.target.value)} className={inputCls} />
            </Field>
            <Field label="Other Expense Description">
              <input data-testid="trip-other-desc" value={form.expenses.other_desc} onChange={(e) => setExp("other_desc", e.target.value)} className={inputCls} />
            </Field>
            <Field label="Other Expense Amount">
              <input data-testid="trip-other-amt" type="number" step="0.01" min="0" value={form.expenses.other} onChange={(e) => setExp("other", e.target.value)} className={inputCls} />
            </Field>
          </div>
        </Section>

        <Section title="LR / Lorry Receipt (Optional)">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Field label="LR Number (auto)">
              <input data-testid="trip-lr-number" value={form.lr_number} onChange={(e) => setForm({ ...form, lr_number: e.target.value })} className={inputCls} placeholder="Auto-generated on download" />
            </Field>
            <Field label="LR Time">
              <input data-testid="trip-lr-time" type="time" value={form.lr_time} onChange={(e) => setForm({ ...form, lr_time: e.target.value })} className={inputCls} />
            </Field>
            <Field label="External Invoice # (BPCL/HPCL)">
              <input data-testid="trip-ext-invoice" value={form.external_invoice_no} onChange={(e) => setForm({ ...form, external_invoice_no: e.target.value })} className={inputCls} placeholder="MUM-26-27-00220" />
            </Field>
            <Field label="Customer Invoice #">
              <input data-testid="trip-cust-invoice" value={form.customer_invoice_no} onChange={(e) => setForm({ ...form, customer_invoice_no: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Customer Purchased At">
              <input data-testid="trip-purchased-at" value={form.customer_purchased_at} onChange={(e) => setForm({ ...form, customer_purchased_at: e.target.value })} className={inputCls} placeholder="e.g. HPCL Kondapalli" />
            </Field>
            <Field label="Invoice Value (₹)">
              <input data-testid="trip-invoice-value" type="number" step="0.01" min="0" value={form.invoice_value} onChange={(e) => setForm({ ...form, invoice_value: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Waybill No.">
              <input data-testid="trip-waybill" value={form.waybill_no} onChange={(e) => setForm({ ...form, waybill_no: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Consignor Name">
              <input data-testid="trip-consignor" value={form.consignor_name} onChange={(e) => setForm({ ...form, consignor_name: e.target.value })} className={inputCls} placeholder="BPCL - Mumbai" />
            </Field>
            <Field label="Consignee Site Location">
              <input data-testid="trip-site-loc" value={form.consignee_site_location} onChange={(e) => setForm({ ...form, consignee_site_location: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Site Contact Person">
              <input data-testid="trip-site-contact" value={form.consignee_site_contact} onChange={(e) => setForm({ ...form, consignee_site_contact: e.target.value })} className={inputCls} placeholder="Name & phone" />
            </Field>
            <Field label="Gross Wt (MT)">
              <input data-testid="trip-gross-wt" type="number" step="0.001" min="0" value={form.gross_weight} onChange={(e) => setForm({ ...form, gross_weight: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Tare Wt (MT)">
              <input data-testid="trip-tare-wt" type="number" step="0.001" min="0" value={form.tare_weight} onChange={(e) => setForm({ ...form, tare_weight: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Seal Numbers">
              <input data-testid="trip-seal" value={form.seal_numbers} onChange={(e) => setForm({ ...form, seal_numbers: e.target.value })} className={inputCls} placeholder="SL-001, SL-002" />
            </Field>
            <Field label="Driver Mobile">
              <input data-testid="trip-driver-mobile" value={form.driver_mobile} onChange={(e) => setForm({ ...form, driver_mobile: e.target.value })} className={inputCls} placeholder="98xxxxxxxx" />
            </Field>
            <Field label="From Pincode">
              <input data-testid="trip-from-pin" value={form.from_pincode} onChange={(e) => setForm({ ...form, from_pincode: e.target.value })} className={inputCls} />
            </Field>
            <Field label="To Pincode">
              <input data-testid="trip-to-pin" value={form.to_pincode} onChange={(e) => setForm({ ...form, to_pincode: e.target.value })} className={inputCls} />
            </Field>
          </div>
          {isEdit && (
            <div className="mt-4">
              <a data-testid="download-lr-btn" href={`${API}/trips/${id}/lr`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800">
                <FileText size={14} /> Download LR PDF
              </a>
              <span className="ml-2 text-xs text-zinc-500">Auto-assigns an LR number on first download.</span>
            </div>
          )}
        </Section>

        {isEdit && (
          <Section title="Attachments · LR proof / Weighbridge slip">
            <FileAttachments linkedType="trip" linkedId={id} category="trip_attachment" title="Trip Files" />
          </Section>
        )}

        <Section title="గమనికలు · Notes">
          <textarea data-testid="trip-notes" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={inputCls} />
        </Section>

        <div className="flex justify-end gap-2">
          <button type="button" onClick={() => nav(-1)} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
          <button data-testid="save-trip-btn" type="submit" disabled={save.isPending} className="px-6 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
            {save.isPending ? "Saving..." : (isEdit ? "Update Trip" : "Save Trip")}
          </button>
        </div>
      </form>
    </div>
  );
}

const inputCls = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";

function Section({ title, children }) {
  return (
    <section className="border border-zinc-200 bg-white rounded-sm">
      <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">
        {title}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function Field({ label, required, children }) {
  return (
    <div>
      <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
        {label}{required && " *"}
      </label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
