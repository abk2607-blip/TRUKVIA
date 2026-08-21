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
  QuickAddShipSite,
} from "@/components/QuickAddModals";

import { EMPTY, inputCls } from "@/components/tripform/tripFormDefaults";
import { Section } from "@/components/tripform/FormPrimitives";
import OverrideReasonDialog from "@/components/OverrideReasonDialog";
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

  // Iter68 — customers are now server-searched inside TripDetailsSection;
  // no need to load the full list upfront.
  const customers = [];
  const { data: drivers = [] } = useQuery({ queryKey: ["drivers"], queryFn: async () => (await api.get("/drivers")).data });
  const { data: products = [] } = useQuery({ queryKey: ["products"], queryFn: async () => (await api.get("/products")).data });
  const { data: vehicles = [] } = useQuery({ queryKey: ["vehicles"], queryFn: async () => (await api.get("/vehicles")).data });
  const { data: templates = [] } = useQuery({ queryKey: ["templates"], queryFn: async () => (await api.get("/templates")).data });
  const { data: expenditureTypes = [] } = useQuery({ queryKey: ["expenditure-types"], queryFn: async () => (await api.get("/expenditure-types")).data });
  const { data: suppliers = [] } = useQuery({ queryKey: ["suppliers"], queryFn: async () => (await api.get("/suppliers")).data });
  const [selectedTemplate, setSelectedTemplate] = useState("");
  const [qaOpen, setQaOpen] = useState(null); // 'customer' | 'vehicle' | 'driver' | 'product' | null
  // Iter100 — Override Reason Dialog state. `capturedReasons` persists reasons
  // across dialog re-opens so users don't have to retype if they cancel & retry.
  const [overrideDialog, setOverrideDialog] = useState({ open: false, list: [] });
  const [capturedReasons, setCapturedReasons] = useState({}); // { field: reason }

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

  // Iter102 · Fetch selected customer's full record so we can cascade its
  // frozen commercial defaults (default_freight_method, shortage_config)
  // into the trip snapshot the moment the user picks a customer — instead
  // of waiting for the backend to snapshot on save. Without this, the
  // Freight Section shows "Loading Qty" for every customer, regardless of
  // their configured Unloading / Higher-of default.
  const { data: selCustResp } = useQuery({
    queryKey: ["trip-form-selected-cust", form.customer_id],
    queryFn: async () =>
      (await api.get("/customers", { params: { ids: form.customer_id, limit: 1 } })).data,
    enabled: !!form.customer_id && !isEdit, // edit mode already has the frozen snapshot
    staleTime: 60000,
  });
  const selCustFull = selCustResp?.items?.find?.((c) => c.id === form.customer_id);
  useEffect(() => {
    if (isEdit) return;                       // never overwrite an existing snapshot
    if (!selCustFull) return;
    const custMethod = (selCustFull.default_freight_method || "per_ton_loading").toLowerCase();
    setForm((f) => {
      if ((f.applied_freight_method || "").toLowerCase() === custMethod) return f;
      return { ...f, applied_freight_method: custMethod };
    });
  }, [selCustFull, isEdit]);

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
        // Iter92 — Supplier Halting (independent, manual)
        supplier_halting_days: Number(form.supplier_halting_days || 0),
        supplier_halting_rate_per_day: Number(form.supplier_halting_rate_per_day || 0),
        supplier_halting_amount: Number(form.supplier_halting_amount || 0),
        supplier_halting_remarks: form.supplier_halting_remarks || "",
        // Iter91 — Multi-row Diesel / Advance transaction logs. Server totals
        // are recomputed from these entries; the flat fields above are only
        // fallbacks when the entries list is empty.
        supplier_diesel_entries: (form.supplier_diesel_entries || []).map((e) => ({
          ...e,
          quantity: Number(e.quantity || 0),
          rate: Number(e.rate || 0),
          amount: Number(e.amount || 0),
        })),
        supplier_advance_entries: (form.supplier_advance_entries || []).map((e) => ({
          ...e,
          amount: Number(e.amount || 0),
        })),
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
      const saved = isEdit
        ? (await api.put(`/trips/${id}`, payload)).data
        : (await api.post("/trips", payload)).data;
      // Iter100 — After the trip persists, log each captured override reason
      // to the audit trail. Failures here are non-blocking (trip save is the
      // primary contract) but surfaced via toast.
      const tid = saved?.id || id;
      const pending = overrideDialog.list || [];
      if (tid && pending.length) {
        for (const o of pending) {
          const reason = (capturedReasons[o.field] || "").trim();
          if (!reason) continue;
          try {
            await api.post(`/trips/${tid}/field-override`, {
              field: o.field,
              system_value: o.system_value,
              final_value: o.final_value,
              reason,
            });
          } catch (err) {
            toast.error(`Override log failed for ${o.label}: ${err?.response?.data?.detail || err.message}`);
          }
        }
      }
      return saved;
    },
    onSuccess: () => {
      toast.success(isEdit ? "Trip updated" : "Trip created");
      qc.invalidateQueries({ queryKey: ["trips"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setCapturedReasons({});
      setOverrideDialog({ open: false, list: [] });
      nav("/trips");
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  // Live computed — Iter102: Round Trip KM freight now respects
  // applied_freight_method (Loading / Unloading / Higher-of) just like
  // per-ton mode does, matching services._compute_trip parity.
  const _ldQ = Number(form.tons || 0);
  const _unQ = Number(form.unloaded_qty || 0);
  const _fmForFreight = (form.applied_freight_method || "per_ton_loading").toLowerCase();
  const _rtQty =
    _fmForFreight === "per_ton_unloading" ? _unQ
    : _fmForFreight === "per_ton_higher_of" ? Math.max(_ldQ, _unQ)
    : _ldQ;
  const freight = form.freight_mode === "per_ton"
    ? (
        _fmForFreight === "per_ton_unloading" ? _unQ * Number(form.rate_per_ton || 0)
        : _fmForFreight === "per_ton_higher_of" ? Math.max(_ldQ, _unQ) * Number(form.rate_per_ton || 0)
        : _ldQ * Number(form.rate_per_ton || 0)
      )
    : (Number(form.round_trip_kms || 0) > 0 && Number(form.rate_per_km_per_ton || 0) > 0)
      ? _rtQty * Number(form.round_trip_kms || 0) * Number(form.rate_per_km_per_ton || 0)
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
  // Iter91 — Prefer per-entry totals over the legacy flat fields.
  const _activeDiesel = (form.supplier_diesel_entries || []).filter((e) => !e.deleted);
  const _activeAdvance = (form.supplier_advance_entries || []).filter((e) => !e.deleted);
  const supplierDieselLive = _activeDiesel.length
    ? _activeDiesel.reduce((s, e) => s + Number(e.amount || 0), 0)
    : Number(form.supplier_diesel || 0);
  const supplierAdvanceLive = _activeAdvance.length
    ? _activeAdvance.reduce((s, e) => s + Number(e.amount || 0), 0)
    : Number(form.supplier_advance || 0);
  const supplierNetPayable =
    supplierFreightLive
    + Number(form.supplier_halting_amount || 0)   // Iter92 — Supplier Halting adds to payable
    - supplierAdvanceLive
    - supplierDieselLive
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

  // ═══════════════════════════════════════════════════════════════════
  // Iter100 UI · Shortage Policy Snapshot (visible for UAT).
  // Must be computed BEFORE shortageAmountSystem so the auto Shortage
  // Amount respects the frozen limit / method just like the backend.
  // Iter102 — Product-allowance fallback: when the Customer has no
  // shortage rule, use the Product Master's `applied_product_shortage_pct`
  // as the effective limit (pct-of-loading). Mirrors services._compute_trip.
  // ═══════════════════════════════════════════════════════════════════
  const _rawCustLimit = Number(form.applied_customer_shortage_limit || 0);
  const _rawCustType = (form.applied_customer_shortage_limit_type || "").toLowerCase();
  const _prodPct = Number(form.applied_product_shortage_pct || 0);
  const _fallbackToProduct = _rawCustLimit <= 0 && _prodPct > 0;
  const custShortageLimit = _fallbackToProduct ? _prodPct : _rawCustLimit;
  const custShortageLimitType = _fallbackToProduct ? "pct" : _rawCustType;
  const custShortageMethod = (form.applied_customer_shortage_method || (_fallbackToProduct ? "net_shortage" : "")).toLowerCase();
  const _limitSource = _fallbackToProduct ? "Product Master" : "Customer Master";
  const hasCustShortagePolicy = custShortageLimitType === "kg" || custShortageLimitType === "pct";
  const custShortageLimitDisplay =
    !hasCustShortagePolicy || custShortageLimit === 0
      ? "—"
      : custShortageLimitType === "kg"
      ? `${custShortageLimit} KG (fixed) · from ${_limitSource}`
      : `${custShortageLimit} % of Loading Qty · from ${_limitSource}`;
  const custShortageMethodLabel =
    custShortageMethod === "full_after_limit"
      ? "Full Shortage After Limit Exceeded"
      : custShortageMethod === "net_shortage"
      ? "Net Shortage (only above limit)"
      : "—";
  const custAllowedMT =
    custShortageLimitType === "kg"
      ? custShortageLimit / 1000
      : custShortageLimitType === "pct"
      ? (loadedQ * custShortageLimit) / 100
      : 0;
  const actualShortageMT = shortageQtyLive;
  const limitExceeded = custAllowedMT > 0 && actualShortageMT > custAllowedMT;
  // Deductible MT depends on the applied deduction method (mirrors services._compute_trip).
  const custDeductibleMT = !hasCustShortagePolicy
    ? actualShortageMT                                       // no policy: legacy full × rate
    : custShortageMethod === "full_after_limit"
      ? (limitExceeded ? actualShortageMT : 0)                // full only when limit exceeded
      : Math.max(actualShortageMT - custAllowedMT, 0);        // net (default)
  const netShortageMT = custDeductibleMT;                    // alias for chain display

  // Supplier shortage (independent · fixed KG only)
  const supplierShortageLimitKg = Number(form.applied_supplier_shortage_limit_kg || 0);
  const supplierShortageAllowedMT = supplierShortageLimitKg / 1000;
  const supplierActualKg = actualShortageMT * 1000;
  const supplierLimitExceeded = supplierShortageLimitKg > 0 && supplierActualKg > supplierShortageLimitKg;
  const supplierNetShortageMT = supplierLimitExceeded ? actualShortageMT : 0;

  // Iter100 — Pure system-computed values (INDEPENDENT of override flags).
  // Shortage amount respects the frozen policy so the auto value matches
  // the backend and the Net Shortage chain on-screen (₹ = rate × net MT).
  const shortageAmountSystem = Number((productRate * custDeductibleMT).toFixed(2));
  const excessAmountSystem = Number((productRate * excessQtyLive).toFixed(2));
  const shortageAmountLive = form.shortage_amount_override
    ? Number(form.shortage_amount || 0)
    : shortageAmountSystem;
  const excessAmountLive = form.excess_amount_override
    ? Number(form.excess_amount || 0)
    : excessAmountSystem;

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

  // ═══════════════════════════════════════════════════════════════════
  // Iter100 UI · Freight Policy Snapshot (Phase 2 UAT surfacing).
  // Shortage policy snapshot lives earlier (feeds shortageAmountSystem).
  // ═══════════════════════════════════════════════════════════════════
  const _FM_LABELS = {
    per_ton_loading: "Per Ton (Loading Qty)",
    per_ton_unloading: "Per Ton (Unloading Qty)",
    per_ton_higher_of: "Per Ton (Higher of Loading/Unloading)",
    fixed: "Fixed / Round Trip",
  };
  const freightMethodSnap = (form.applied_freight_method || (form.freight_mode === "fixed" ? "fixed" : "per_ton_loading")).toLowerCase();
  const freightMethodLabel = _FM_LABELS[freightMethodSnap] || freightMethodSnap;
  // Iter102 UI · Round-Trip KM mode ALSO honours the frozen freight method
  // (Loading / Unloading / Higher-of). A pure Lump-Sum trip (round_trip_kms
  // or rate_per_km_per_ton is 0) is the only case where qty_used is truly 0.
  const _rtKmLive = Number(form.round_trip_kms || 0);
  const _rtRateLive = Number(form.rate_per_km_per_ton || 0);
  const _isPureLumpSum = form.freight_mode === "fixed" && !(_rtKmLive > 0 && _rtRateLive > 0);
  const _methodBasisQty =
    freightMethodSnap === "per_ton_unloading"
      ? unloadedQ
      : freightMethodSnap === "per_ton_higher_of"
      ? Math.max(loadedQ, unloadedQ)
      : loadedQ; // per_ton_loading OR fixed-round-trip fallback → Loading Qty
  const freightQtyUsedLive = _isPureLumpSum ? 0 : _methodBasisQty;
  const _methodBasisLabel =
    freightMethodSnap === "per_ton_unloading"
      ? "Unloading Qty"
      : freightMethodSnap === "per_ton_higher_of"
      ? "Higher of Loading / Unloading"
      : "Loading Qty";
  const freightQtyBasisLabel = _isPureLumpSum ? "N/A · Lump Sum" : _methodBasisLabel;

  const chargeableDaysLive = form.halting_amount_override
    ? Number(form.chargeable_halting_days || 0)
    : autoChargeableDays;
  const haltingRateLive = Number(form.halting_rate_per_day || 0);
  // Iter100 — Pure system-computed halting (INDEPENDENT of override flag).
  const haltingAmountSystem = Number((autoChargeableDays * haltingRateLive).toFixed(2));
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

  // Iter73 — Supplier Freight auto-sync. When user is on `per_ton` or `fixed`  // freight mode AND has entered the rate/tonnage inputs, mirror the live
  // computed value into `form.supplier_freight` so the field isn't left blank
  // in the UI and the value that hits the backend matches what the user sees
  // in the "Supplier Freight (Live)" tile. User manual edits are still
  // respected — the effect only writes when the live value differs from the
  // current form value AND the inputs are non-zero.
  useEffect(() => {
    if (form.vehicle_type !== "supplier") return;
    const mode = form.supplier_freight_mode;
    const shouldAuto =
      (mode === "per_ton" && Number(form.supplier_rate_per_ton || 0) > 0) ||
      (mode === "fixed" &&
        ((Number(form.supplier_round_trip_kms || 0) > 0 && Number(form.supplier_rate_per_km_per_ton || 0) > 0) ||
         Number(form.supplier_fixed_amount || 0) > 0));
    if (!shouldAuto) return;
    const target = Number(supplierFreightLive.toFixed(2));
    const current = Number(Number(form.supplier_freight || 0).toFixed(2));
    if (target !== current) {
      setForm((f) => ({ ...f, supplier_freight: target }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    form.vehicle_type,
    form.supplier_freight_mode,
    form.supplier_rate_per_ton,
    form.supplier_rate_per_km_per_ton,
    form.supplier_round_trip_kms,
    form.supplier_fixed_amount,
    form.supplier_quantity,
    form.tons,
  ]);

  // Iter74 — Auto-mirror trip.shortage_amount → supplier_shortage_deduction
  // for supplier vehicles UNLESS user has explicitly overridden. Matches the
  // backend `_compute_trip` mirror so the live "Net Payable" tile stays
  // consistent with what the server will compute on save.
  useEffect(() => {
    if (form.vehicle_type !== "supplier") return;
    if (form.supplier_shortage_deduction_override) return;
    const target = Number(Number(form.shortage_amount || 0).toFixed(2));
    const current = Number(Number(form.supplier_shortage_deduction || 0).toFixed(2));
    if (target !== current) {
      setForm((f) => ({ ...f, supplier_shortage_deduction: target }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.vehicle_type, form.shortage_amount, form.supplier_shortage_deduction_override]);

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

  // Iter100 — Detect every financial field whose final value differs from
  // the system-computed value. Each entry becomes a row in the mandatory
  // Override Reason Dialog. Rounded to 2dp to ignore floating-point noise.
  const _eq2 = (a, b) => Math.abs(Number(a || 0) - Number(b || 0)) < 0.005;
  const detectOverrides = () => {
    const list = [];
    // Customer-side (compare against PURE system value, not override-aware Live)
    if (form.shortage_amount_override && !_eq2(form.shortage_amount, shortageAmountSystem)) {
      list.push({ field: "shortage_amount", label: "Customer Shortage Amount",
        system_value: shortageAmountSystem,
        final_value: Number(Number(form.shortage_amount || 0).toFixed(2)) });
    }
    if (form.excess_amount_override && !_eq2(form.excess_amount, excessAmountSystem)) {
      list.push({ field: "excess_amount", label: "Customer Excess Amount",
        system_value: excessAmountSystem,
        final_value: Number(Number(form.excess_amount || 0).toFixed(2)) });
    }
    if (form.halting_amount_override && !_eq2(form.halting_amount, haltingAmountSystem)) {
      list.push({ field: "halting_amount", label: "Customer Halting Amount",
        system_value: haltingAmountSystem,
        final_value: Number(Number(form.halting_amount || 0).toFixed(2)) });
    }
    // Supplier-side (only for supplier vehicles)
    if (form.vehicle_type === "supplier") {
      if (!_eq2(form.supplier_freight, supplierFreightLive)) {
        list.push({ field: "supplier_freight", label: "Supplier Freight",
          system_value: Number(supplierFreightLive.toFixed(2)),
          final_value: Number(Number(form.supplier_freight || 0).toFixed(2)) });
      }
      if (form.supplier_shortage_deduction_override) {
        const sysShort = Number(Number(form.shortage_amount || 0).toFixed(2));
        if (!_eq2(form.supplier_shortage_deduction, sysShort)) {
          list.push({ field: "supplier_shortage_deduction", label: "Supplier Shortage Deduction",
            system_value: sysShort,
            final_value: Number(Number(form.supplier_shortage_deduction || 0).toFixed(2)) });
        }
      }
      // Supplier Halting is always manual — any non-zero value is an override.
      if (Number(form.supplier_halting_amount || 0) > 0) {
        const autoHalting = Number(form.supplier_halting_days || 0) * Number(form.supplier_halting_rate_per_day || 0);
        if (!_eq2(form.supplier_halting_amount, autoHalting)) {
          list.push({ field: "supplier_halting_amount", label: "Supplier Halting Amount",
            system_value: Number(autoHalting.toFixed(2)),
            final_value: Number(Number(form.supplier_halting_amount || 0).toFixed(2)) });
        }
      }
      // Advance / Diesel — if flat field differs from sum of entries (when entries exist)
      const _dieselSum = _activeDiesel.reduce((s, e) => s + Number(e.amount || 0), 0);
      if (_activeDiesel.length && !_eq2(form.supplier_diesel, _dieselSum)) {
        list.push({ field: "supplier_diesel", label: "Supplier Diesel (Total)",
          system_value: Number(_dieselSum.toFixed(2)),
          final_value: Number(Number(form.supplier_diesel || 0).toFixed(2)) });
      }
      const _advSum = _activeAdvance.reduce((s, e) => s + Number(e.amount || 0), 0);
      if (_activeAdvance.length && !_eq2(form.supplier_advance, _advSum)) {
        list.push({ field: "supplier_advance", label: "Supplier Advance (Total)",
          system_value: Number(_advSum.toFixed(2)),
          final_value: Number(Number(form.supplier_advance || 0).toFixed(2)) });
      }
    }
    // Attach any previously captured reason so the dialog pre-fills on re-open.
    return list.map((o) => ({ ...o, reason: capturedReasons[o.field] || "" }));
  };

  const handleFormSubmit = (e) => {
    e.preventDefault();
    // Iter47 Phase 3: Strict supplier enforcement on supplier vehicles
    if (form.vehicle_type === "supplier" && !form.supplier_id) {
      toast.error("Please select a Supplier for this supplier vehicle (mandatory)");
      return;
    }
    const overrides = detectOverrides();
    // Every override needs a reason captured before save proceeds.
    const missing = overrides.filter((o) => !(capturedReasons[o.field] || "").trim());
    if (missing.length > 0) {
      setOverrideDialog({ open: true, list: overrides });
      return;
    }
    setOverrideDialog({ open: false, list: overrides });
    save.mutate();
  };

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

      <form onSubmit={handleFormSubmit} className="space-y-6">
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
            tripId={isEdit ? id : null}
            supplierFreightLive={supplierFreightLive}
            supplierNetPayable={supplierNetPayable}
            supplierProfit={supplierProfit}
            onQuickAddSupplier={() => setQaOpen("supplier")}
          />
        )}

        <FreightSection
          form={form}
          setForm={setForm}
          freight={freight}
          freightMethodLabel={freightMethodLabel}
          freightQtyBasisLabel={freightQtyBasisLabel}
          freightQtyUsedLive={freightQtyUsedLive}
          loadedQ={loadedQ}
          unloadedQ={unloadedQ}
        />

        <UnloadingSection
          form={form} setForm={setForm}
          shortageQtyLive={shortageQtyLive} excessQtyLive={excessQtyLive}
          shortageAmountLive={shortageAmountLive} excessAmountLive={excessAmountLive}
          custShortageLimitDisplay={custShortageLimitDisplay}
          custShortageLimitType={custShortageLimitType}
          custShortageMethod={custShortageMethod}
          custShortageMethodLabel={custShortageMethodLabel}
          custAllowedMT={custAllowedMT}
          netShortageMT={netShortageMT}
          limitExceeded={limitExceeded}
          supplierShortageLimitKg={supplierShortageLimitKg}
          supplierShortageAllowedMT={supplierShortageAllowedMT}
          supplierNetShortageMT={supplierNetShortageMT}
          supplierLimitExceeded={supplierLimitExceeded}
          loadedQ={loadedQ}
          unloadedQ={unloadedQ}
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
        <div className="sticky bottom-[64px] md:bottom-0 -mx-4 md:mx-0 z-40 bg-white/95 backdrop-blur border-t border-zinc-200 px-4 py-3 flex items-center justify-between gap-3 shadow-[0_-6px_16px_-8px_rgba(15,23,42,0.15)]" data-testid="trip-form-sticky-bar">
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
      {qaOpen === "ship-site" && form.customer_id && (
        <QuickAddShipSite
          customerId={form.customer_id}
          onCreated={(s) => setForm((f) => ({ ...f, ship_site_id: s.id }))}
          onClose={() => setQaOpen(null)}
        />
      )}

      <OverrideReasonDialog
        open={overrideDialog.open}
        overrides={overrideDialog.list}
        onCancel={() => setOverrideDialog({ open: false, list: [] })}
        onConfirm={(reasons) => {
          setCapturedReasons((prev) => ({ ...prev, ...reasons }));
          // Re-arm dialog list with the freshly captured reasons so the save
          // mutation can pick them up when POSTing to /field-override.
          const withReasons = overrideDialog.list.map((o) => ({
            ...o, reason: (reasons[o.field] || "").trim(),
          }));
          setOverrideDialog({ open: false, list: withReasons });
          // Kick off save now that every override has a justification.
          save.mutate();
        }}
      />
    </div>
  );
}
