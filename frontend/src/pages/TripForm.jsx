import React, { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, API, fmtCurrency } from "@/api";
import { toast } from "sonner";
import { ArrowLeft, FileText } from "lucide-react";
import FileAttachments from "@/components/FileAttachments";
import SearchableSelect from "@/components/SearchableSelect";
import VoiceTripButton from "@/components/VoiceTripButton";
import VoiceButton from "@/components/VoiceButton";
import {
  QuickAddCustomer,
  QuickAddDriver,
  QuickAddVehicle,
  QuickAddProduct,
} from "@/components/QuickAddModals";

const EMPTY = {
  customer_id: "",
  date: new Date().toISOString().slice(0, 10),
  vehicle_number: "",
  vehicle_id: "",
  vehicle_type: "own",
  supplier_id: "",
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
  supplier_diesel: 0,
  supplier_shortage_deduction: 0,
  supplier_other_recoveries: 0,
  supplier_other_income: 0,
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
  other_expenditures: [],
  halting_remarks: "",
  shortage_remarks: "",
  excess_remarks: "",
  other_income: 0,
  other_income_remarks: "",
  supplier_settlement_remarks: "",
  lr_driver_name: "",
  lr_driver_mobile: "",
  customer_diesel_received: 0,
  customer_advance_received: 0,
  customer_receipts: [],
};

export default function TripForm() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const prefillCustomer = searchParams.get("customer_id");
  const isEdit = Boolean(id);
  const [form, setForm] = useState(EMPTY);

  const { data: customers = [] } = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get("/customers")).data });
  const { data: drivers = [] } = useQuery({ queryKey: ["drivers"], queryFn: async () => (await api.get("/drivers")).data });
  const { data: products = [] } = useQuery({ queryKey: ["products"], queryFn: async () => (await api.get("/products")).data });
  const { data: vehicles = [] } = useQuery({ queryKey: ["vehicles"], queryFn: async () => (await api.get("/vehicles")).data });
  const { data: templates = [] } = useQuery({ queryKey: ["templates"], queryFn: async () => (await api.get("/templates")).data });
  const { data: expenditureTypes = [] } = useQuery({ queryKey: ["expenditure-types"], queryFn: async () => (await api.get("/expenditure-types")).data });
  const { data: suppliers = [] } = useQuery({ queryKey: ["suppliers"], queryFn: async () => (await api.get("/suppliers")).data });
  const [selectedTemplate, setSelectedTemplate] = useState("");
  const [qaOpen, setQaOpen] = useState(null); // 'customer' | 'vehicle' | 'driver' | 'product' | null

  const { data: trip } = useQuery({
    queryKey: ["trip", id],
    queryFn: async () => (await api.get("/trips")).data.find((t) => t.id === id),
    enabled: isEdit,
  });

  useEffect(() => {
    if (trip) setForm({ ...EMPTY, ...trip, expenses: { ...EMPTY.expenses, ...(trip.expenses || {}) } });
  }, [trip]);

  useEffect(() => {
    if (!isEdit && prefillCustomer) {
      setForm((f) => ({ ...f, customer_id: prefillCustomer }));
    }
  }, [prefillCustomer, isEdit]);

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
        supplier_diesel: Number(form.supplier_diesel || 0),
        supplier_shortage_deduction: Number(form.supplier_shortage_deduction || 0),
        supplier_other_recoveries: Number(form.supplier_other_recoveries || 0),
        supplier_other_income: Number(form.supplier_other_income || 0),
        loaded_qty: Number(form.tons || 0),
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
        customer_diesel_received: Number(form.customer_diesel_received || 0),
        customer_advance_received: Number(form.customer_advance_received || 0),
        customer_receipts: (form.customer_receipts || []).map((r) => ({
          id: r.id, date: r.date, type: r.type,
          amount: Number(r.amount || (Number(r.litres || 0) * Number(r.rate || 0)) || 0),
          litres: r.litres ? Number(r.litres) : undefined,
          rate: r.rate ? Number(r.rate) : undefined,
          mode: r.mode || undefined,
          ref_no: r.ref_no || undefined,
          remarks: r.remarks || undefined,
        })),
        other_expenditures: (form.other_expenditures || []).map((e2) => ({
          id: e2.id, date: e2.date, type: e2.type,
          amount: Number(e2.amount || 0),
          remarks: e2.remarks || "",
        })),
        other_income: Number(form.other_income || 0),
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
  const totalExpense = Object.entries(form.expenses).reduce((s, [k, v]) => s + (k === "other_desc" || k === "other_remarks" ? 0 : Number(v || 0)), 0)
    + (form.other_expenditures || []).reduce((s, e2) => s + Number(e2.amount || 0), 0);
  const profit = freight - totalExpense + Number(form.other_income || 0);

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
  const supplierNetPayable =
    supplierFreightLive
    - Number(form.supplier_advance || 0)
    - Number(form.supplier_diesel || 0)
    - Number(form.supplier_shortage_deduction || 0)
    - Number(form.supplier_other_recoveries || 0)
    + Number(form.supplier_other_income || 0);
  const supplierProfit = freight - supplierNetPayable;

  // Loading/Unloading auto-diff — Iter42: `tons` (Loading Qty in Tons) is the source of truth
  const loadedQ = Number(form.tons || 0);
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

  // Halting auto-calc — Iter46: honour manually-typed Total Days when no dates provided.
  let totalHaltingDaysLive = 0;
  const effectiveLoadingDate = form.loading_date || form.date || "";
  const _datesPresent = !!(effectiveLoadingDate && form.unloading_date);
  if (_datesPresent) {
    const ld = new Date(effectiveLoadingDate);
    const ud = new Date(form.unloading_date);
    const diffMs = ud - ld;
    totalHaltingDaysLive = Math.max(Math.floor(diffMs / 86400000), 0);
  } else {
    // Fall back to user-typed value stored in form.total_halting_days
    totalHaltingDaysLive = Math.max(Number(form.total_halting_days || 0), 0);
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
      setForm((f) => ({ ...f, loaded_qty: Number(f.tons || 0), shortage_qty: shortageQtyLive, excess_qty: excessQtyLive, shortage_amount: shortageAmountLive, excess_amount: excessAmountLive }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.tons, unloadedQ, productRate, form.shortage_amount_override, form.excess_amount_override]);

  useEffect(() => {
    if (!form.halting_amount_override) {
      setForm((f) => ({ ...f, total_halting_days: totalHaltingDaysLive, chargeable_halting_days: autoChargeableDays, halting_amount: haltingAmountLive }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.loading_date, form.unloading_date, form.grace_days, form.halting_rate_per_day, form.halting_amount_override, form.total_halting_days]);

  useEffect(() => {
    // Iter40 (Image 11): Auto-sync driver_name/mobile from Trip Details section
    // into the LR section, but ONLY when the LR fields are empty (never overwrite
    // a manual LR-side edit). Editing lr_driver_* does NOT touch Driver Master.
    setForm((f) => {
      if (!f.driver_name && !f.driver_mobile) return f;
      const patch = {};
      if (!f.lr_driver_name && f.driver_name) patch.lr_driver_name = f.driver_name;
      if (!f.lr_driver_mobile && f.driver_mobile) patch.lr_driver_mobile = f.driver_mobile;
      return Object.keys(patch).length ? { ...f, ...patch } : f;
    });
  }, [form.driver_name, form.driver_mobile]);

  const setExp = (k, v) => setForm({ ...form, expenses: { ...form.expenses, [k]: v } });

  return (
    <div className="space-y-6" data-testid="trip-form-page">
      <header className="flex items-center gap-3 border-b border-zinc-200 pb-4">
        <button onClick={() => nav(-1)} className="p-2 border border-zinc-200 rounded-sm"><ArrowLeft size={16} /></button>
        <div className="flex-1">
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Trip Entry</div>
          <h1 className="text-3xl font-black tracking-tighter">
            <span className="telugu">{isEdit ? "ట్రిప్ ఎడిట్" : "కొత్త ట్రిప్"}</span>
            <span className="text-zinc-400"> · {isEdit ? "Edit Trip" : "New Trip"}</span>
          </h1>
        </div>
        {!isEdit && (
          <VoiceTripButton
            onParsed={(p) => {
              setForm((f) => ({
                ...f,
                ...Object.fromEntries(Object.entries(p).filter(([, v]) => v !== "" && v !== null && v !== undefined)),
                expenses: f.expenses,
              }));
            }}
          />
        )}
      </header>

      <form onSubmit={(e) => {
        e.preventDefault();
        // Iter47 Phase 3: Strict supplier enforcement on supplier vehicles
        if (form.vehicle_type === "supplier" && !form.supplier_id) {
          toast.error("Please select a Supplier for this supplier vehicle (mandatory)");
          return;
        }
        save.mutate();
      }} className="space-y-6">
        {!isEdit && templates.length > 0 && (
          <div data-testid="template-picker" className="border border-emerald-300 bg-emerald-50 rounded-sm p-4 flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="text-sm text-emerald-900 flex-1">
              <div className="font-bold uppercase tracking-wider text-xs mb-1">⚡ Quick Start from Template</div>
              <div className="text-xs">Select a saved route/customer template to pre-fill this trip.</div>
            </div>
            <select
              data-testid="template-picker-select"
              value={selectedTemplate}
              onChange={async (e) => {
                const tid = e.target.value;
                setSelectedTemplate(tid);
                if (!tid) return;
                try {
                  const { data } = await api.post(`/trips/from-template/${tid}`);
                  setForm(prev => ({
                    ...prev,
                    ...data,
                    expenses: { ...(prev.expenses || {}) },
                  }));
                  toast.success("Template applied — fill in vehicle, driver, tons");
                } catch (err) { toast.error(err.response?.data?.detail || "Template apply failed"); }
              }}
              className={inputCls + " sm:w-72"}
            >
              <option value="">— Choose a template —</option>
              {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </div>
        )}
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
              <SearchableSelect
                dataTestId="trip-customer"
                value={form.customer_id}
                onChange={(v) => setForm({ ...form, customer_id: v })}
                onCreateNew={() => setQaOpen("customer")}
                createLabel="+ Add New Customer"
                placeholder="Search customer…"
                options={customers.map((c) => ({
                  value: c.id,
                  label: c.name,
                  meta: [c.gstin, c.state, c.phone].filter(Boolean).join(" · "),
                }))}
              />
            </Field>
            <Field label="Vehicle No · వాహనం" required>
              <SearchableSelect
                dataTestId="trip-vehicle-select"
                value={vehicles.find((v) => v.vehicle_number === form.vehicle_number)?.id || ""}
                onChange={(vid, opt) => {
                  const v = vehicles.find((x) => x.id === vid);
                  if (v) {
                    setForm({
                      ...form,
                      vehicle_id: v.id,
                      vehicle_number: v.vehicle_number,
                      vehicle_type: v.vehicle_type || "own",
                      supplier_id: v.vehicle_type === "supplier" ? (v.supplier_id || "") : "",
                      supplier_name: v.vehicle_type === "supplier" ? (v.supplier_name || "") : "",
                    });
                  } else {
                    setForm({ ...form, vehicle_id: "", vehicle_number: "" });
                  }
                }}
                onCreateNew={() => setQaOpen("vehicle")}
                createLabel="+ Add New Vehicle"
                placeholder="Search vehicle…"
                options={vehicles.map((v) => ({
                  value: v.id,
                  label: v.vehicle_number,
                  meta: [v.vehicle_type === "supplier" ? "Supplier" : "Own", v.owner_name || v.supplier_name].filter(Boolean).join(" · "),
                }))}
              />
              <input
                data-testid="trip-vehicle"
                required
                value={form.vehicle_number}
                onChange={(e) => setForm({ ...form, vehicle_number: e.target.value.toUpperCase() })}
                className={`${inputCls} mt-1`}
                placeholder="Or type new: AP16TA1234"
              />
            </Field>
            <Field label="Driver · డ్రైవర్">
              <SearchableSelect
                dataTestId="trip-driver"
                value={form.driver_id || ""}
                onChange={(did) => {
                  const d = drivers.find((x) => x.id === did);
                  setForm({ ...form, driver_id: did, driver_name: d?.name || "", driver_mobile: d?.phone || form.driver_mobile });
                }}
                onCreateNew={() => setQaOpen("driver")}
                createLabel="+ Add New Driver"
                placeholder="Search driver…"
                options={drivers.map((d) => ({
                  value: d.id,
                  label: d.name,
                  meta: d.phone || "",
                }))}
              />
            </Field>
            <Field label="Product / Load · లోడ్">
              <SearchableSelect
                dataTestId="trip-product"
                value={form.product_id || ""}
                onChange={(pid) => {
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
                onCreateNew={() => setQaOpen("product")}
                createLabel="+ Add New Product"
                placeholder="Search product…"
                options={products.map((p) => ({
                  value: p.id,
                  label: p.name,
                  meta: `HSN ${p.hsn_sac}${p.default_rate ? ` · ₹${p.default_rate}/MT` : ""}`,
                }))}
              />
              <input data-testid="trip-load" value={form.load_details} onChange={(e) => setForm({ ...form, load_details: e.target.value, product_id: "" })} className={`${inputCls} mt-1`} placeholder="Or type free-text load details" />
            </Field>
            <Field label="Loading Qty (in Tons) · లోడింగ్" required>
              <input data-testid="trip-tons" required type="number" step="0.001" min="0" value={form.tons} onChange={(e) => setForm({ ...form, tons: e.target.value })} className={inputCls} />
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
        <Section title="Unloading Details · అన్‌లోడ్">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Field label="Unloading Date">
              <input data-testid="trip-unloading-date" type="date" value={form.unloading_date} onChange={(e) => setForm({ ...form, unloading_date: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Loading Qty (MT) · from Trip Details">
              <input
                data-testid="trip-loaded-qty"
                type="number"
                step="0.001"
                min="0"
                value={Number(form.tons || 0)}
                readOnly
                className={`${inputCls} bg-zinc-100 cursor-not-allowed text-zinc-700 font-mono`}
                title="Auto-synced from 'Loading Qty (in Tons)' in Trip Details. Edit that field to change."
              />
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
          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label="Shortage — Remarks">
              <input data-testid="trip-shortage-remarks" value={form.shortage_remarks} onChange={(e) => setForm({ ...form, shortage_remarks: e.target.value })} className={inputCls} placeholder="Cause / reference (optional)" />
            </Field>
            <Field label="Excess — Remarks">
              <input data-testid="trip-excess-remarks" value={form.excess_remarks} onChange={(e) => setForm({ ...form, excess_remarks: e.target.value })} className={inputCls} placeholder="Cause / reference (optional)" />
            </Field>
          </div>
        </Section>

        {/* Halting / Waiting Charges */}
        <Section title="Halting / Waiting Charges · హాల్టింగ్">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {_datesPresent ? (
              <div className="border border-zinc-200 p-2 rounded-sm text-center">
                <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Total Days</div>
                <div className="font-mono text-lg font-bold" data-testid="trip-total-halting-days">{totalHaltingDaysLive}</div>
                <div className="text-[9px] text-zinc-400 mt-0.5">Auto from Loading/Unloading dates</div>
              </div>
            ) : (
              <Field label={<span>Total Halting Days <span className="text-[9px] text-amber-700 uppercase">manual</span></span>}>
                <input data-testid="trip-total-halting-days" type="number" min="0" step="1"
                  value={form.total_halting_days || 0}
                  onChange={(e) => setForm({ ...form, total_halting_days: e.target.value, halting_amount_override: false })}
                  className={inputCls}
                  placeholder="Or enter Loading + Unloading dates"
                />
              </Field>
            )}
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
          <div className="mt-3 text-[11px] text-zinc-500 bg-amber-50 border border-amber-200 rounded-sm p-2">
            <span className="font-bold">Formula:</span> Halting = Chargeable Days × Rate.
            {" "}Provide <b>Loading Date + Unloading Date</b> in Trip Details for automatic Total Days —
            {" "}or type Total Days directly above when dates are unknown. Grace of {form.grace_days || 4} days is deducted.
          </div>
          <div className="mt-3">
            <Field label="Halting — Remarks">
              <input data-testid="trip-halting-remarks" value={form.halting_remarks} onChange={(e) => setForm({ ...form, halting_remarks: e.target.value })} className={inputCls} placeholder="Detention reason / site details (optional)" />
            </Field>
          </div>
        </Section>

        {/* Customer-Provided (Diesel/Advance) — Iter39 repeatable receipts */}
        <Section title="కస్టమర్ నుండి · Received From Customer">
          <CustomerReceipts
            receipts={form.customer_receipts || []}
            onChange={(list) => setForm({ ...form, customer_receipts: list })}
          />
          {(() => {
            const diesel = (form.customer_receipts || []).filter((r) => r.type === "diesel").reduce((s, r) => s + (Number(r.amount) || (Number(r.litres || 0) * Number(r.rate || 0))), 0);
            const advance = (form.customer_receipts || []).filter((r) => r.type === "advance").reduce((s, r) => s + Number(r.amount || 0), 0);
            const total = diesel + advance;
            return (
              <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-2">
                <div className="border border-zinc-200 bg-white rounded-sm p-2.5"><div className="text-[9px] uppercase tracking-wider font-bold text-zinc-500">Total Diesel Received</div><div className="font-mono text-base font-bold" data-testid="cr-total-diesel">{fmtCurrency(diesel)}</div></div>
                <div className="border border-zinc-200 bg-white rounded-sm p-2.5"><div className="text-[9px] uppercase tracking-wider font-bold text-zinc-500">Total Advance Received</div><div className="font-mono text-base font-bold" data-testid="cr-total-advance">{fmtCurrency(advance)}</div></div>
                <div className="border border-rose-300 bg-rose-50 rounded-sm p-2.5"><div className="text-[9px] uppercase tracking-wider font-bold text-rose-700">Total Deductions from Freight</div><div className="font-mono text-lg font-bold text-rose-800" data-testid="cr-total-deduction">{fmtCurrency(total)}</div></div>
              </div>
            );
          })()}
          <div className="mt-2 text-[11px] text-zinc-500">Each receipt is trip-linked. These reduce the customer's Net Payable Freight. For supplier vehicle trips, Customer Diesel is also deducted from Supplier Net Payable.</div>
        </Section>

        {/* Expenses */}
        <Section title="ఖర్చులు · Expenses">
          <div className="flex justify-end mb-2">
            <VoiceButton
              context="expense"
              size="sm"
              onParsed={(p) => {
                const num = (v) => (v === "" || v === null || v === undefined ? null : Number(v));
                setForm((f) => ({
                  ...f,
                  expenses: {
                    ...f.expenses,
                    diesel: num(p.diesel) ?? f.expenses.diesel,
                    toll: num(p.toll) ?? f.expenses.toll,
                    batta: num(p.batta) ?? f.expenses.batta,
                    repair: num(p.repair) ?? f.expenses.repair,
                    other: num(p.other) ?? f.expenses.other,
                    other_desc: p.other_desc || f.expenses.other_desc,
                  },
                }));
              }}
            />
          </div>
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
              <Field label="Supplier · సప్లయర్" required>
                <SearchableSelect
                  dataTestId="trip-supplier-picker"
                  value={form.supplier_id || ""}
                  onChange={(sid) => {
                    const s = suppliers.find((x) => x.id === sid);
                    setForm({
                      ...form,
                      supplier_id: sid || "",
                      supplier_name: s ? s.name : form.supplier_name,
                    });
                  }}
                  placeholder="Select supplier…"
                  options={suppliers.map((s) => ({
                    value: s.id,
                    label: s.name,
                    meta: [s.mobile, s.gst_in].filter(Boolean).join(" · "),
                  }))}
                />
                {!form.supplier_id && (
                  <div className="text-[10px] text-rose-700 mt-1 font-bold">
                    ⚠ Supplier selection is mandatory for supplier vehicles. <a href="/suppliers/add" target="_blank" rel="noopener" className="underline">+ Add new</a>
                  </div>
                )}
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
              <Field label="Supplier Diesel (₹)">
                <input data-testid="trip-supplier-diesel" type="number" step="0.01" min="0" value={form.supplier_diesel} onChange={(e) => setForm({ ...form, supplier_diesel: e.target.value })} className={inputCls} placeholder="Diesel we paid on behalf" />
              </Field>
              <Field label="Shortage Deduction (₹)">
                <input data-testid="trip-supplier-shortage" type="number" step="0.01" min="0" value={form.supplier_shortage_deduction} onChange={(e) => setForm({ ...form, supplier_shortage_deduction: e.target.value })} className={inputCls} placeholder="Deducted from supplier" />
              </Field>
              <Field label="Other Recoveries (₹)">
                <input data-testid="trip-supplier-recovery" type="number" step="0.01" min="0" value={form.supplier_other_recoveries} onChange={(e) => setForm({ ...form, supplier_other_recoveries: e.target.value })} className={inputCls} placeholder="Damages, penalties etc." />
              </Field>
              <Field label="Other Income / Bonus (₹)">
                <input data-testid="trip-supplier-income" type="number" step="0.01" min="0" value={form.supplier_other_income} onChange={(e) => setForm({ ...form, supplier_other_income: e.target.value })} className={inputCls} placeholder="Excess bonus paid to supplier" />
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
                <div className="text-[10px] text-zinc-500 mt-1">Freight − Advance − Diesel − Shortage − Recoveries + Income</div>
              </div>
              <div className={`border p-3 rounded-sm text-center ${supplierProfit >= 0 ? "border-emerald-300 bg-emerald-50" : "border-rose-300 bg-rose-50"}`}>
                <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Trip Profit</div>
                <div className={`font-mono text-lg font-bold ${supplierProfit >= 0 ? "text-emerald-800" : "text-rose-800"}`}>{fmtCurrency(supplierProfit)}</div>
                <div className="text-[10px] text-zinc-500 mt-1">Customer Freight − Net Payable</div>
              </div>
            </div>
            <div className="mt-3">
              <Field label="Supplier Settlement — Remarks">
                <input data-testid="trip-supplier-settlement-remarks" value={form.supplier_settlement_remarks} onChange={(e) => setForm({ ...form, supplier_settlement_remarks: e.target.value })} className={inputCls} placeholder="Payment / TDS / adjustments notes (optional)" />
              </Field>
            </div>
          </Section>
        )}

        <Section title="Other Expenditure · ఇతర ఖర్చులు">
          <div className="text-[11px] text-zinc-500 mb-3 bg-amber-50 border border-amber-200 rounded-sm p-2">
            <span className="font-bold">Note:</span> Customer Diesel &amp; Advance are managed in <em>"Received From Customer"</em> above. This section is for miscellaneous trip expenditures (Driver Food, Parking, Toll, Loading Charges, Unloading Charges, Weighment, Labour, etc.).
          </div>
          <OtherExpenditures
            rows={form.other_expenditures || []}
            types={expenditureTypes}
            onChange={(list) => setForm({ ...form, other_expenditures: list })}
            onCreateType={async (name) => {
              try {
                const { data } = await api.post("/expenditure-types", { name });
                qc.invalidateQueries({ queryKey: ["expenditure-types"] });
                return data;
              } catch (err) {
                toast.error(err?.response?.data?.detail || "Could not add type");
                return null;
              }
            }}
          />

          {/* Other Income (₹) with remarks */}
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3 border-t border-zinc-200 pt-4">
            <Field label="Other Income (₹) — Miscellaneous">
              <input data-testid="trip-other-income" type="number" step="0.01" min="0" value={form.other_income} onChange={(e) => setForm({ ...form, other_income: e.target.value })} className={inputCls} placeholder="Detention income, misc bonus, etc." />
            </Field>
            <Field label="Other Income — Remarks">
              <input data-testid="trip-other-income-remarks" value={form.other_income_remarks} onChange={(e) => setForm({ ...form, other_income_remarks: e.target.value })} className={inputCls} placeholder="Reason / context (optional)" />
            </Field>
          </div>
        </Section>

        <Section title="LR / Lorry Receipt (Optional)">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Field label="LR Number (auto)">
              <input data-testid="trip-lr-number" value={form.lr_number} onChange={(e) => setForm({ ...form, lr_number: e.target.value })} className={inputCls} placeholder="Leave blank for auto-generation" />
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
            <Field label={<span>Driver Name (LR) <span className="text-[9px] text-zinc-400">auto from Trip · editable</span></span>}>
              <input data-testid="trip-lr-driver-name" value={form.lr_driver_name} onChange={(e) => setForm({ ...form, lr_driver_name: e.target.value })} className={inputCls} placeholder={form.driver_name || "Enter driver name"} />
            </Field>
            <Field label={<span>Driver Mobile (LR) <span className="text-[9px] text-zinc-400">auto from Trip · editable</span></span>}>
              <input data-testid="trip-driver-mobile" value={form.lr_driver_mobile} onChange={(e) => setForm({ ...form, lr_driver_mobile: e.target.value })} className={inputCls} placeholder={form.driver_mobile || "98xxxxxxxx"} />
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

      {qaOpen === "customer" && (
        <QuickAddCustomer
          onCreated={(c) => setForm((f) => ({ ...f, customer_id: c.id }))}
          onClose={() => setQaOpen(null)}
        />
      )}
      {qaOpen === "vehicle" && (
        <QuickAddVehicle
          prefillNumber={form.vehicle_number}
          onCreated={(v) => setForm((f) => ({
            ...f,
            vehicle_id: v.id,
            vehicle_number: v.vehicle_number,
            vehicle_type: v.vehicle_type || "own",
            supplier_id: v.vehicle_type === "supplier" ? (v.supplier_id || "") : "",
            supplier_name: v.vehicle_type === "supplier" ? (v.supplier_name || "") : "",
          }))}
          onClose={() => setQaOpen(null)}
        />
      )}
      {qaOpen === "driver" && (
        <QuickAddDriver
          onCreated={(d) => setForm((f) => ({ ...f, driver_id: d.id, driver_name: d.name, driver_mobile: d.phone || f.driver_mobile }))}
          onClose={() => setQaOpen(null)}
        />
      )}
      {qaOpen === "product" && (
        <QuickAddProduct
          onCreated={(p) => setForm((f) => ({
            ...f,
            product_id: p.id,
            load_details: p.name,
            hsn_sac: p.hsn_sac,
            rate_per_ton: f.freight_mode === "per_ton" && p.default_rate ? p.default_rate : f.rate_per_ton,
          }))}
          onClose={() => setQaOpen(null)}
        />
      )}
    </div>
  );
}

const inputCls = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";


// ---------- Iter39: Repeatable Customer Receipts (Diesel + Advance) ----------
function CustomerReceipts({ receipts, onChange }) {
  const [draft, setDraft] = React.useState({
    date: new Date().toISOString().slice(0, 10),
    type: "diesel",
    litres: "", rate: "", amount: "",
    mode: "Cash", ref_no: "", remarks: "",
  });
  const add = () => {
    const t = draft.type;
    const amt = t === "diesel"
      ? Number(draft.litres || 0) * Number(draft.rate || 0)
      : Number(draft.amount || 0);
    if (amt <= 0) return;
    const row = {
      id: `rcpt_${Date.now()}`,
      date: draft.date,
      type: t,
      amount: Number(amt.toFixed(2)),
      remarks: draft.remarks || "",
      ...(t === "diesel" ? { litres: Number(draft.litres), rate: Number(draft.rate) } : {}),
      ...(t === "advance" ? { mode: draft.mode, ref_no: draft.ref_no } : {}),
    };
    onChange([...(receipts || []), row]);
    setDraft({ ...draft, litres: "", rate: "", amount: "", ref_no: "", remarks: "" });
  };
  const del = (id) => onChange((receipts || []).filter((r) => r.id !== id));
  const ic = "w-full border border-zinc-300 px-2 py-1.5 rounded-sm text-xs focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";
  return (
    <div className="space-y-3" data-testid="customer-receipts">
      {/* Add row */}
      <div className="border border-zinc-200 rounded-sm p-3 bg-zinc-50">
        <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-2">Add Receipt</div>
        <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
          <div>
            <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Date</label>
            <input data-testid="cr-date" type="date" value={draft.date} onChange={(e) => setDraft({ ...draft, date: e.target.value })} className={ic} />
          </div>
          <div>
            <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Type</label>
            <select data-testid="cr-type" value={draft.type} onChange={(e) => setDraft({ ...draft, type: e.target.value })} className={ic}>
              <option value="diesel">Diesel</option>
              <option value="advance">Advance</option>
            </select>
          </div>
          {draft.type === "diesel" ? (
            <>
              <div>
                <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Litres</label>
                <input data-testid="cr-litres" type="number" step="0.01" min="0" value={draft.litres} onChange={(e) => setDraft({ ...draft, litres: e.target.value })} className={ic} placeholder="280" />
              </div>
              <div>
                <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Rate (₹/L)</label>
                <input data-testid="cr-rate" type="number" step="0.01" min="0" value={draft.rate} onChange={(e) => setDraft({ ...draft, rate: e.target.value })} className={ic} placeholder="104.24" />
              </div>
              <div>
                <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Total (auto)</label>
                <input value={draft.litres && draft.rate ? `₹ ${(Number(draft.litres) * Number(draft.rate)).toFixed(2)}` : ""} readOnly className={`${ic} bg-zinc-100 font-mono font-bold`} />
              </div>
            </>
          ) : (
            <>
              <div>
                <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Amount (₹)</label>
                <input data-testid="cr-amount" type="number" step="0.01" min="0" value={draft.amount} onChange={(e) => setDraft({ ...draft, amount: e.target.value })} className={ic} placeholder="20000" />
              </div>
              <div>
                <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Mode</label>
                <select data-testid="cr-mode" value={draft.mode} onChange={(e) => setDraft({ ...draft, mode: e.target.value })} className={ic}>
                  {["Cash", "Bank", "UPI", "IMPS", "NEFT", "Cash to Driver", "Other"].map((m) => <option key={m}>{m}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Ref / Txn No</label>
                <input data-testid="cr-refno" value={draft.ref_no} onChange={(e) => setDraft({ ...draft, ref_no: e.target.value })} className={ic} placeholder="Optional" />
              </div>
            </>
          )}
          <div className="flex items-end">
            <button type="button" data-testid="cr-add-btn" onClick={add} className="w-full px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold bg-emerald-600 text-white rounded-sm hover:bg-emerald-700">+ Add</button>
          </div>
          <div className="md:col-span-6">
            <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Remarks</label>
            <input data-testid="cr-remarks" value={draft.remarks} onChange={(e) => setDraft({ ...draft, remarks: e.target.value })} className={ic} placeholder="Optional notes (e.g. paid at HPCL Kondapalli / txn ref / receipt no)" />
          </div>
        </div>
      </div>

      {/* Existing receipts table */}
      {(receipts || []).length === 0 ? (
        <div className="text-xs text-zinc-500 italic px-2">No receipts added yet.</div>
      ) : (
        <div className="border border-zinc-200 rounded-sm overflow-hidden">
          <table className="w-full text-xs" data-testid="cr-list">
            <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-wider">
              <tr>
                <th className="text-left px-3 py-2">Date</th>
                <th className="text-left px-3 py-2">Type</th>
                <th className="text-left px-3 py-2">Details</th>
                <th className="text-right px-3 py-2">Amount</th>
                <th className="text-left px-3 py-2">Mode / Ref</th>
                <th className="w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {(receipts || []).map((r) => (
                <tr key={r.id} data-testid={`cr-row-${r.id}`} className="hover:bg-amber-50/50">
                  <td className="px-3 py-2 font-mono">{r.date}</td>
                  <td className="px-3 py-2 uppercase font-bold text-[10px]">
                    <span className={`px-2 py-0.5 rounded-sm border ${r.type === "diesel" ? "bg-orange-50 text-orange-800 border-orange-200" : "bg-blue-50 text-blue-800 border-blue-200"}`}>{r.type}</span>
                  </td>
                  <td className="px-3 py-2 text-zinc-600">
                    <div>
                      {r.type === "diesel"
                        ? `${r.litres} L × ₹${Number(r.rate).toFixed(2)}`
                        : (r.mode || "—")}
                    </div>
                    {r.remarks && <div className="text-[10px] text-zinc-500 italic mt-0.5">{r.remarks}</div>}
                  </td>
                  <td className="px-3 py-2 text-right font-mono font-bold">{fmtCurrency(r.amount)}</td>
                  <td className="px-3 py-2 text-zinc-600 text-[11px]">
                    {r.type === "advance" ? `${r.mode || "—"}${r.ref_no ? ` · ${r.ref_no}` : ""}` : "Customer Diesel"}
                  </td>
                  <td className="px-2 py-2 text-center">
                    <button type="button" data-testid={`cr-del-${r.id}`} onClick={() => del(r.id)} className="text-rose-600 hover:bg-rose-50 rounded p-1">×</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


// ---------- Iter40: Dynamic Other Expenditure list backed by Expenditure Master ----------
function OtherExpenditures({ rows, types, onChange, onCreateType }) {
  const [draft, setDraft] = React.useState({
    date: new Date().toISOString().slice(0, 10),
    type: "",
    amount: "",
    remarks: "",
  });
  const [newType, setNewType] = React.useState("");
  const ic = "w-full border border-zinc-300 px-2 py-1.5 rounded-sm text-xs focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";

  const add = () => {
    const amt = Number(draft.amount || 0);
    const type = (draft.type || "").trim();
    if (!type || amt <= 0) {
      toast.error("Choose a type and enter an amount");
      return;
    }
    onChange([
      ...(rows || []),
      { id: `oe_${Date.now()}`, date: draft.date, type, amount: Number(amt.toFixed(2)), remarks: draft.remarks || "" },
    ]);
    setDraft({ ...draft, amount: "", remarks: "" });
  };
  const del = (id) => onChange((rows || []).filter((r) => r.id !== id));
  const addNewType = async () => {
    const n = (newType || "").trim();
    if (!n) return;
    const created = await onCreateType(n);
    if (created) {
      setDraft({ ...draft, type: created.name });
      setNewType("");
      toast.success(`Added "${created.name}" to Expenditure Master`);
    }
  };

  const total = (rows || []).reduce((s, r) => s + Number(r.amount || 0), 0);

  return (
    <div className="space-y-3" data-testid="other-expenditures">
      <div className="border border-zinc-200 rounded-sm p-3 bg-zinc-50">
        <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-2">Add Expenditure</div>
        <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
          <div>
            <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Date</label>
            <input data-testid="oe-date" type="date" value={draft.date} onChange={(e) => setDraft({ ...draft, date: e.target.value })} className={ic} />
          </div>
          <div className="md:col-span-2">
            <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Type · రకం</label>
            <select data-testid="oe-type" value={draft.type} onChange={(e) => setDraft({ ...draft, type: e.target.value })} className={ic}>
              <option value="">— Select type —</option>
              {(types || []).map((t) => (
                <option key={t.id} value={t.name}>{t.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Amount (₹)</label>
            <input data-testid="oe-amount" type="number" step="0.01" min="0" value={draft.amount} onChange={(e) => setDraft({ ...draft, amount: e.target.value })} className={ic} placeholder="0" />
          </div>
          <div className="md:col-span-2">
            <label className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">Remarks</label>
            <input data-testid="oe-remarks" value={draft.remarks} onChange={(e) => setDraft({ ...draft, remarks: e.target.value })} className={ic} placeholder="Optional context" />
          </div>
          <div className="md:col-span-6 flex flex-col md:flex-row md:items-end gap-2 mt-1">
            <button type="button" data-testid="oe-add-btn" onClick={add} className="px-4 py-1.5 text-[10px] uppercase tracking-wider font-bold bg-emerald-600 text-white rounded-sm hover:bg-emerald-700">
              + Add Expenditure
            </button>
            <div className="flex items-center gap-2 flex-1 md:justify-end">
              <input
                data-testid="oe-new-type-input"
                value={newType}
                onChange={(e) => setNewType(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addNewType(); } }}
                className={`${ic} max-w-[220px]`}
                placeholder="Add new type to master…"
              />
              <button type="button" data-testid="oe-add-type-btn" onClick={addNewType} className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100">
                + Type
              </button>
            </div>
          </div>
        </div>
      </div>

      {(rows || []).length === 0 ? (
        <div className="text-xs text-zinc-500 italic px-2">No expenditures added yet.</div>
      ) : (
        <div className="border border-zinc-200 rounded-sm overflow-hidden">
          <table className="w-full text-xs" data-testid="oe-list">
            <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-wider">
              <tr>
                <th className="text-left px-3 py-2">Date</th>
                <th className="text-left px-3 py-2">Type</th>
                <th className="text-left px-3 py-2">Remarks</th>
                <th className="text-right px-3 py-2">Amount</th>
                <th className="w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {(rows || []).map((r) => (
                <tr key={r.id} data-testid={`oe-row-${r.id}`} className="hover:bg-amber-50/50">
                  <td className="px-3 py-2 font-mono">{r.date}</td>
                  <td className="px-3 py-2 font-bold">{r.type}</td>
                  <td className="px-3 py-2 text-zinc-600 italic">{r.remarks || "—"}</td>
                  <td className="px-3 py-2 text-right font-mono font-bold">{fmtCurrency(r.amount)}</td>
                  <td className="px-2 py-2 text-center">
                    <button type="button" data-testid={`oe-del-${r.id}`} onClick={() => del(r.id)} className="text-rose-600 hover:bg-rose-50 rounded p-1">×</button>
                  </td>
                </tr>
              ))}
              <tr className="bg-zinc-50 font-bold">
                <td colSpan={3} className="px-3 py-2 text-right uppercase tracking-wider text-[10px]">Total</td>
                <td className="px-3 py-2 text-right font-mono" data-testid="oe-total">{fmtCurrency(total)}</td>
                <td></td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


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
