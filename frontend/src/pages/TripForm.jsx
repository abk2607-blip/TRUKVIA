// Iter55 — TripForm refactor. Pure component extraction; state, mutations,
// computations, useEffects, and API calls preserved EXACTLY as before.
import React, { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import FileAttachments from "@/components/FileAttachments";
import VoiceTripButton from "@/components/VoiceTripButton";
import {
  QuickAddCustomer,
  QuickAddDriver,
  QuickAddVehicle,
  QuickAddProduct,
  QuickAddSupplier,
} from "@/components/QuickAddModals";

import { EMPTY, inputCls } from "@/components/tripform/tripFormDefaults";
import { Section } from "@/components/tripform/FormPrimitives";
import TripDetailsSection from "@/components/tripform/TripDetailsSection";
import FreightSection from "@/components/tripform/FreightSection";
import UnloadingSection from "@/components/tripform/UnloadingSection";
import HaltingSection from "@/components/tripform/HaltingSection";
import ReceivedFromCustomerSection from "@/components/tripform/ReceivedFromCustomerSection";
import ExpensesSection from "@/components/tripform/ExpensesSection";
import SupplierSection from "@/components/tripform/SupplierSection";
import OtherExpenditureSection from "@/components/tripform/OtherExpenditureSection";
import LRSection from "@/components/tripform/LRSection";

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
    // Iter55 fix: use dedicated GET /trips/{id} instead of list-and-filter
    // (list is capped at 2000; newer trips were invisible to edit form).
    queryFn: async () => (await api.get(`/trips/${id}`)).data,
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
        // Iter49 — expenses has TWO string fields (`other_desc` + `other_remarks`).
        // Number()-casting `other_remarks` produced NaN → JSON null → backend 422.
        expenses: Object.fromEntries(Object.entries(form.expenses).map(([k, v]) =>
          [k, (k === "other_desc" || k === "other_remarks") ? (v || "") : Number(v || 0)]
        )),
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

        <TripDetailsSection
          form={form} setForm={setForm}
          customers={customers} vehicles={vehicles} drivers={drivers} products={products}
          setQaOpen={setQaOpen}
        />

        {/* Iter63 · Priority D — Supplier Section moved to render immediately after Trip Details */}
        {form.vehicle_type === "supplier" && (
          <SupplierSection
            form={form} setForm={setForm} suppliers={suppliers}
            supplierFreightLive={supplierFreightLive}
            supplierNetPayable={supplierNetPayable}
            supplierProfit={supplierProfit}
            onQuickAddSupplier={() => setQaOpen("supplier")}
          />
        )}

        <FreightSection form={form} setForm={setForm} freight={freight} />

        <UnloadingSection
          form={form} setForm={setForm}
          shortageQtyLive={shortageQtyLive} excessQtyLive={excessQtyLive}
          shortageAmountLive={shortageAmountLive} excessAmountLive={excessAmountLive}
        />

        <HaltingSection
          form={form} setForm={setForm}
          datesPresent={_datesPresent}
          totalHaltingDaysLive={totalHaltingDaysLive}
          autoChargeableDays={autoChargeableDays}
          haltingAmountLive={haltingAmountLive}
        />

        <ReceivedFromCustomerSection form={form} setForm={setForm} />

        <ExpensesSection
          form={form} setForm={setForm} setExp={setExp}
          totalExpense={totalExpense} freight={freight} profit={profit}
        />

        <OtherExpenditureSection
          form={form} setForm={setForm}
          expenditureTypes={expenditureTypes}
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

        <LRSection form={form} setForm={setForm} isEdit={isEdit} id={id} />

        {isEdit && (
          <Section title="Attachments · LR proof / Weighbridge slip">
            <FileAttachments linkedType="trip" linkedId={id} category="trip_attachment" title="Trip Files" />
          </Section>
        )}

        <Section title="గమనికలు · Notes">
          <textarea data-testid="trip-notes" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={inputCls} />
        </Section>

        {/* Iter63 · Priority Q3 — Sticky Save/Cancel bar (visible on every scroll position) */}
        <div className="sticky bottom-0 -mx-4 md:mx-0 z-40 bg-white/95 backdrop-blur border-t border-zinc-200 px-4 py-3 flex items-center justify-between gap-3 shadow-[0_-6px_16px_-8px_rgba(15,23,42,0.15)]" data-testid="trip-form-sticky-bar">
          <div className="text-xs text-zinc-600 tabular-nums hidden md:block">
            <span className="font-semibold">Freight:</span> ₹{Number(freight || 0).toLocaleString("en-IN")}
            <span className="mx-3 text-zinc-300">·</span>
            <span className="font-semibold">Profit:</span> <span className={Number(profit || 0) >= 0 ? "text-emerald-700" : "text-rose-700"}>₹{Number(profit || 0).toLocaleString("en-IN")}</span>
            {form.vehicle_type === "supplier" && (
              <>
                <span className="mx-3 text-zinc-300">·</span>
                <span className="font-semibold">Net Payable to Supplier:</span> <span className="text-rose-700">₹{Number(supplierNetPayable || 0).toLocaleString("en-IN")}</span>
              </>
            )}
          </div>
          <div className="flex items-center gap-2 ml-auto">
            <button
              type="button"
              onClick={() => nav(-1)}
              data-testid="trip-cancel-sticky"
              className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-50"
            >Cancel</button>
            <button
              data-testid="save-trip-btn"
              type="submit"
              disabled={save.isPending || (form.vehicle_type === "supplier" && !form.supplier_id)}
              className="px-6 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50"
            >
              {save.isPending ? "Saving..." : (isEdit ? "Update Trip" : "Save Trip")}
            </button>
          </div>
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
      {qaOpen === "supplier" && (
        <QuickAddSupplier
          onCreated={(s) => setForm((f) => ({ ...f, supplier_id: s.id, supplier_name: s.name }))}
          onClose={() => setQaOpen(null)}
        />
      )}
    </div>
  );
}
