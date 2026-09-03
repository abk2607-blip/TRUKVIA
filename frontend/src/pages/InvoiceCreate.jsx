import React, { useState, useMemo, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, fmtCurrency, fmtDate, getActiveCompanyId } from "@/api";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import VoiceButton from "@/components/VoiceButton";
import AsyncSearchableSelect from "@/components/AsyncSearchableSelect";
// Iter126c — Form Preservation
import { useFormDraft } from "@/hooks/useFormDraft";
import DraftRestoreBanner from "@/components/DraftRestoreBanner";
import { useAuth } from "@/context/AuthContext";

export default function InvoiceCreate() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [customerId, setCustomerId] = useState("");
  const [selected, setSelected] = useState({});
  const [rcm, setRcm] = useState(true);
  const [hsnSac, setHsnSac] = useState("996791");
  const [invoiceDate, setInvoiceDate] = useState(new Date().toISOString().slice(0, 10));
  const [notes, setNotes] = useState("");
  // Iter134 · Invoice Number correction — separate visible field.
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [invoiceNumberEdited, setInvoiceNumberEdited] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const [suggestedFy, setSuggestedFy] = useState("");
  const [suggestedNumber, setSuggestedNumber] = useState("");

  // Iter126c — Draft preservation. InvoiceCreate is Phase 1 scope. The
  // sanitised buffer that is written includes ONLY the six controlled
  // fields below (customer_id, invoice_date, hsn_sac, rcm, notes, and the
  // selected trip-id map). Nothing sensitive touches sessionStorage.
  const invoiceForm = useMemo(
    () => ({ customerId, selected, rcm, hsnSac, invoiceDate, notes }),
    [customerId, selected, rcm, hsnSac, invoiceDate, notes],
  );
  const _setInvoiceForm = useCallback((updater) => {
    // The hook calls `setForm(prev => ({ ...prev, ...draft.form }))` on
    // Restore. Split the merged object back into the individual pieces of
    // React state that own each field.
    const next = typeof updater === "function" ? updater(invoiceForm) : updater;
    if (Object.prototype.hasOwnProperty.call(next, "customerId")) setCustomerId(next.customerId || "");
    if (Object.prototype.hasOwnProperty.call(next, "selected")) setSelected(next.selected || {});
    if (Object.prototype.hasOwnProperty.call(next, "rcm")) setRcm(Boolean(next.rcm));
    if (Object.prototype.hasOwnProperty.call(next, "hsnSac")) setHsnSac(next.hsnSac || "996791");
    if (Object.prototype.hasOwnProperty.call(next, "invoiceDate")) setInvoiceDate(next.invoiceDate || new Date().toISOString().slice(0, 10));
    if (Object.prototype.hasOwnProperty.call(next, "notes")) setNotes(next.notes || "");
  }, [invoiceForm]);
  const { user } = useAuth();
  // Iter134 · Role-based UX for Invoice Number override (LIVE UAT hardening).
  //
  // Canonical role source (Notes / PartyLedger / Vendors / Mechanics):
  //   user.effective_role   ── set by GET /auth/me after resolution
  //   user.role             ── legacy fallback
  //
  // A real Owner logging in via Google OAuth hits AuthCallback → setUser(data)
  // where `data` comes from POST /auth/session and DOES NOT include a role
  // field. The role only arrives on the next /auth/me tick. If we treat
  // "role unknown" as non-owner, the first render locks a real Owner out
  // of their own field until /auth/me completes.
  //
  // Fix: PERMISSIVE default. When no role information is available yet,
  // render as Owner (backend authorization remains the final gate). We only
  // treat the user as non-owner when a role IS present AND is explicitly not
  // "owner" (e.g. accountant, manager, viewer).
  const _rawRole = (user?.effective_role ?? user?.role ?? "").toString().trim().toLowerCase();
  const isOwner = _rawRole === "" ? true : _rawRole === "owner";
  const draft = useFormDraft({
    route: "/invoices/new",
    form: invoiceForm,
    setForm: _setInvoiceForm,
    userId: user && user.user_id,
    companyId: getActiveCompanyId(),
  });
  const idemKeyRef = useRef(null);

  const { data: customers = [] } = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get("/customers")).data });
  const { data: company } = useQuery({ queryKey: ["company"], queryFn: async () => (await api.get("/company")).data });
  const { data: trips = [], refetch } = useQuery({
    queryKey: ["invoiceable-trips", customerId],
    queryFn: async () => (await api.get("/trips", { params: { customer_id: customerId, status: "pending" } })).data,
    enabled: Boolean(customerId),
  });

  // Iter78 — Fetch the currently-selected customer via ids-lookup so the picker
  // button always shows its name (even if the customer is outside the paginated
  // search window). Same pattern as Trip Form.
  const { data: selCustResp } = useQuery({
    queryKey: ["customer-detail", customerId],
    queryFn: async () => (await api.get("/customers", { params: { ids: customerId } })).data,
    enabled: Boolean(customerId),
    staleTime: 60000,
  });
  const selectedCustomer =
    selCustResp?.items?.find?.((c) => c.id === customerId) ||
    customers.find((c) => c.id === customerId) ||
    null;
  const selectedCustomerOption = selectedCustomer
    ? {
        value: selectedCustomer.id,
        label: selectedCustomer.name,
        meta: [selectedCustomer.gstin, selectedCustomer.state, selectedCustomer.phone].filter(Boolean).join(" · "),
      }
    : null;

  // Iter78 — Server-side customer search for the Invoice picker (hides pytest
  // fixture customers by default; the same 300 ms-debounced picker used in Trip Form).
  const fetchCustomers = useCallback(async (q) => {
    const params = { limit: 50 };
    if (q) params.q = q;
    if (customerId) params.ids = customerId;
    const { data } = await api.get("/customers", { params });
    return (data?.items || []).map((c) => ({
      value: c.id,
      label: c.name,
      meta: [c.gstin, c.state, c.phone].filter(Boolean).join(" · "),
    }));
  }, [customerId]);
  // Auto GST determination: same state → CGST+SGST; different / missing → IGST
  const gstType = useMemo(() => {
    const home = (company?.state || "").trim().toLowerCase();
    const cust = (selectedCustomer?.state || "").trim().toLowerCase();
    if (!home || !cust) return "cgst_sgst"; // fallback for preview only
    return home === cust ? "cgst_sgst" : "igst";
  }, [company?.state, selectedCustomer?.state]);

  const selectedTrips = useMemo(() => trips.filter((t) => selected[t.id]), [trips, selected]);
  const freightTotal = selectedTrips.reduce((s, t) => s + Number(t.freight_amount || 0), 0);
  const haltingTotal = selectedTrips.reduce((s, t) => s + Number(t.halting_amount || 0), 0);
  const excessTotal = selectedTrips.reduce((s, t) => s + Number(t.excess_amount || 0), 0);
  const shortageTotal = selectedTrips.reduce((s, t) => s + Number(t.shortage_amount || 0) + Number((t.expenses || {}).shortage_amount || 0), 0);
  const dieselDedTotal = selectedTrips.reduce((s, t) => s + Number((t.expenses || {}).diesel_from_customer_amount || 0), 0);
  const advanceDedTotal = selectedTrips.reduce((s, t) => s + Number((t.expenses || {}).cash_advance_received || 0), 0);
  const subtotal = freightTotal + haltingTotal + excessTotal - shortageTotal - dieselDedTotal - advanceDedTotal;
  const cgst = gstType === "cgst_sgst" ? subtotal * 0.025 : 0;
  const sgst = gstType === "cgst_sgst" ? subtotal * 0.025 : 0;
  const igst = gstType === "igst" ? subtotal * 0.05 : 0;
  const totalTax = cgst + sgst + igst;
  const grossTotal = rcm ? subtotal : subtotal + totalTax;
  const finalTotal = Math.round(grossTotal);
  const roundOff = Number((finalTotal - grossTotal).toFixed(2));

  // Iter134 · Reason-binding fix.
  // The backend is the source of truth for whether an override is happening
  // (it re-computes preview atomically against the same $inc counter it
  // will consume). We therefore:
  //   1. Always send `invoice_number` + trimmed `invoice_number_reason`
  //      when the Owner has visibly touched the field. If the number the
  //      user typed happens to equal the backend's LIVE preview, the
  //      backend safely treats it as non-override and ignores the reason
  //      (per routers/invoices.py line 324).
  //   2. Trim the reason before sending — a whitespace-only reason
  //      collapses to "" and is rejected, which mirrors backend behaviour.
  //   3. Locally block the Create button when an override is happening
  //      but the trimmed reason is < 10 chars, with an inline hint —
  //      users can never hit the 400 for an already-typed valid reason.
  const trimmedNum = (invoiceNumber || "").trim();
  const trimmedReason = (overrideReason || "").trim();
  // Local heuristic — matches backend's `override_num != preview` gate.
  // Backend re-verifies against LIVE preview so we err on the safe side by
  // sending the fields whenever the user has actually edited.
  const localOverrideActive = Boolean(
    isOwner && invoiceNumberEdited && trimmedNum && trimmedNum !== (suggestedNumber || "")
  );
  const reasonInvalid = localOverrideActive && trimmedReason.length < 10;

  const create = useMutation({
    mutationFn: async () => (await api.post("/invoices", {
      customer_id: customerId,
      trip_ids: Object.keys(selected).filter((k) => selected[k]),
      invoice_date: invoiceDate,
      hsn_sac: hsnSac,
      gst_type: gstType,
      rcm,
      notes,
      // Owner + touched → send override fields (trimmed). Backend accepts,
      // rejects with a specific error, or silently treats as non-override
      // when the typed value equals the LIVE preview.
      ...(isOwner && invoiceNumberEdited && trimmedNum
        ? { invoice_number: trimmedNum, invoice_number_reason: trimmedReason }
        : {}),
    }, { headers: idemKeyRef.current ? { "Idempotency-Key": idemKeyRef.current } : {} })).data,
    onSuccess: (data) => {
      toast.success("Invoice created");
      qc.invalidateQueries();
      try { draft.clearOnSuccess(); } catch {}
      idemKeyRef.current = null;
      nav(`/invoices/${data.id}`);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const toggleAll = () => {
    if (Object.keys(selected).length === trips.length && trips.every((t) => selected[t.id])) {
      setSelected({});
    } else {
      setSelected(Object.fromEntries(trips.map((t) => [t.id, true])));
    }
  };

  const canSubmit = customerId && selectedTrips.length > 0 && !reasonInvalid;

  return (
    <div className="space-y-6" data-testid="invoice-create-page">
      <DraftRestoreBanner draft={draft} />
      <header className="flex items-center gap-3 border-b border-zinc-200 pb-4">
        <button onClick={() => nav(-1)} className="p-2 border border-zinc-200 rounded-sm"><ArrowLeft size={16} /></button>
        <div className="flex-1">
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">New</div>
          <h1 className="text-3xl font-black tracking-tighter">
            <span className="telugu">కొత్త ఇన్వాయిస్</span>
            <span className="text-zinc-400"> · Create Invoice</span>
          </h1>
        </div>
        <VoiceButton
          context="invoice"
          onParsed={(p) => {
            if (p.customer_id) setCustomerId(p.customer_id);
            if (p.invoice_date) setInvoiceDate(p.invoice_date);
            if (p.notes) setNotes(p.notes);
          }}
        />
      </header>

      <section className="border border-zinc-200 bg-white rounded-sm p-5 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Customer · కస్టమర్ *</label>
            <div className="mt-1">
              <AsyncSearchableSelect
                dataTestId="invoice-customer"
                value={customerId}
                selectedOption={selectedCustomerOption}
                fetchOptions={fetchCustomers}
                onChange={(v) => { setCustomerId(v); setSelected({}); }}
                placeholder="Search customer name, phone, GSTIN…"
              />
            </div>
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Invoice Date · తేదీ</label>
            <input data-testid="invoice-date" type="date" value={invoiceDate}
              max={new Date().toISOString().slice(0,10)}
              onChange={(e) => setInvoiceDate(e.target.value)} className={inputCls} />
            <NextNumberChip
              invoiceDate={invoiceDate}
              onPreview={(p) => {
                setSuggestedFy(p.fy || "");
                setSuggestedNumber(p.suggested_number || "");
                if (!invoiceNumberEdited) setInvoiceNumber(p.suggested_number || "");
              }}
            />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
              Invoice Number
              {invoiceNumberEdited && (
                <span className="ml-2 px-1.5 py-0.5 text-[9px] rounded-sm bg-amber-100 text-amber-900 border border-amber-300" data-testid="invoice-number-overridden">
                  Overridden
                </span>
              )}
            </label>
            <input
              data-testid="invoice-number-input"
              value={invoiceNumber}
              onChange={(e) => { setInvoiceNumber(e.target.value); setInvoiceNumberEdited(true); }}
              disabled={!isOwner}
              readOnly={!isOwner}
              aria-disabled={!isOwner}
              className={inputCls + " font-mono" + (!isOwner ? " bg-zinc-50 text-zinc-600 cursor-not-allowed" : "")}
              placeholder="Auto-generated from Invoice Date"
              title={isOwner ? "Owner can override the invoice number" : "Owner-only override"}
            />
            <div className="mt-1 text-[10px] text-zinc-500 flex items-center gap-2">
              <span data-testid="invoice-fy-label">
                {suggestedFy ? `FY 20${suggestedFy.split("-")[0]}-${suggestedFy.split("-")[1]}` : "—"}
              </span>
              {isOwner && invoiceNumberEdited && suggestedNumber && invoiceNumber !== suggestedNumber && (
                <>
                  <span>·</span>
                  <span>Suggested: <span className="font-mono">{suggestedNumber}</span></span>
                  <button
                    type="button"
                    data-testid="invoice-number-reset"
                    onClick={() => { setInvoiceNumber(suggestedNumber); setInvoiceNumberEdited(false); setOverrideReason(""); }}
                    className="text-indigo-700 hover:underline"
                  >
                    Reset
                  </button>
                </>
              )}
              <span data-testid="invoice-number-role-hint" className="text-zinc-400">
                · {isOwner ? "Owner can override the invoice number" : "Owner-only override"}
              </span>
            </div>
            {isOwner && invoiceNumberEdited && trimmedNum !== (suggestedNumber || "") && (
              <>
                <input
                  data-testid="invoice-number-reason"
                  value={overrideReason}
                  onChange={(e) => setOverrideReason(e.target.value)}
                  className={inputCls + " mt-2" + (reasonInvalid ? " border-rose-400 focus:border-rose-500 focus:ring-rose-500" : "")}
                  placeholder="Reason for overriding the invoice number (min 10 chars)"
                  aria-invalid={reasonInvalid || undefined}
                  aria-describedby="invoice-number-reason-hint"
                />
                <div
                  id="invoice-number-reason-hint"
                  data-testid="invoice-number-reason-hint"
                  className={"mt-1 text-[10px] " + (reasonInvalid ? "text-rose-700 font-semibold" : "text-zinc-500")}
                >
                  {reasonInvalid
                    ? `Reason must be at least 10 characters (currently ${trimmedReason.length}).`
                    : "Reason is required when overriding the invoice number."}
                </div>
              </>
            )}
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">GST Type <span className="text-emerald-700">(Auto)</span></label>
            <div data-testid="invoice-gst-type" className={`${inputCls} bg-zinc-50 flex items-center`}>
              {gstType === "cgst_sgst" ? "CGST + SGST (Intra-state)" : "IGST (Inter-state)"}
            </div>
            <div className="text-[10px] text-zinc-500 mt-1">
              {selectedCustomer?.state && company?.state
                ? `Company: ${company.state} · Customer: ${selectedCustomer.state} → ${gstType === "cgst_sgst" ? "Same state" : "Different states"}`
                : "Set Company & Customer states to auto-determine"}
            </div>
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">HSN / SAC Code</label>
            <select data-testid="invoice-hsn" value={hsnSac} onChange={(e) => setHsnSac(e.target.value)} className={inputCls + " bg-white"}>
              <option value="996791">996791 · Goods Transport Agency Services</option>
              <option value="996511">996511 · Road transport services of goods</option>
            </select>
            <div className="text-[10px] text-zinc-500 mt-1">Applies to all trips in this invoice. Trips may still override individually.</div>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">GST Treatment</label>
            <div className="mt-1 flex gap-2" data-testid="invoice-gst-treatment">
              <button type="button" onClick={() => setRcm(true)}
                data-testid="gst-rcm-btn"
                className={`flex-1 px-3 py-2 text-xs uppercase tracking-wider font-semibold rounded-sm border ${rcm ? "bg-amber-100 border-amber-400 text-amber-900" : "bg-white border-zinc-200 text-zinc-500 hover:border-zinc-950"}`}>
                RCM · Recipient pays tax
              </button>
              <button type="button" onClick={() => setRcm(false)}
                data-testid="gst-normal-btn"
                className={`flex-1 px-3 py-2 text-xs uppercase tracking-wider font-semibold rounded-sm border ${!rcm ? "bg-emerald-100 border-emerald-400 text-emerald-900" : "bg-white border-zinc-200 text-zinc-500 hover:border-zinc-950"}`}>
                Normal GST · Forward charge
              </button>
            </div>
            <div className="text-[10px] text-zinc-500 mt-1">
              {rcm
                ? "RCM selected: tax will be shown on invoice but NOT collected. Customer files it under RCM."
                : "Normal charge: 5% GST added to the taxable amount."}
            </div>
          </div>
        </div>
      </section>

      {customerId && (
        <section className="border border-zinc-200 bg-white rounded-sm">
          <div className="px-5 py-3 border-b border-zinc-200 flex items-center justify-between">
            <div className="text-sm font-bold uppercase tracking-wider">
              <span className="telugu">పెండింగ్ ట్రిప్స్</span> · Uninvoiced Trips ({trips.length})
            </div>
            {trips.length > 0 && (
              <button data-testid="toggle-all-trips" onClick={toggleAll} className="text-xs px-2 py-1 border border-zinc-200 rounded-sm hover:bg-zinc-950 hover:text-white">
                {trips.every((t) => selected[t.id]) ? "Clear All" : "Select All"}
              </button>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
                <tr>
                  <th className="px-3 py-2"></th>
                  <th className="text-left px-3 py-2 font-semibold">Date</th>
                  <th className="text-left px-3 py-2 font-semibold">Vehicle</th>
                  <th className="text-left px-3 py-2 font-semibold">Route</th>
                  <th className="text-right px-3 py-2 font-semibold">Tons</th>
                  <th className="text-left px-3 py-2 font-semibold">Mode</th>
                  <th className="text-right px-3 py-2 font-semibold">Freight</th>
                </tr>
              </thead>
              <tbody>
                {trips.map((t) => (
                  <tr key={t.id} data-testid={`select-trip-${t.id}`} className={`border-t border-zinc-100 cursor-pointer ${selected[t.id] ? "bg-amber-50" : ""}`} onClick={() => setSelected({ ...selected, [t.id]: !selected[t.id] })}>
                    <td className="px-3 py-2"><input type="checkbox" readOnly checked={!!selected[t.id]} className="w-4 h-4" /></td>
                    <td className="px-3 py-2 font-mono text-xs">{fmtDate(t.date)}</td>
                    <td className="px-3 py-2 font-mono text-xs">{t.vehicle_number}</td>
                    <td className="px-3 py-2 text-xs">{t.from_location} → {t.to_location}</td>
                    <td className="px-3 py-2 text-right font-mono">{Number(t.tons).toFixed(2)}</td>
                    <td className="px-3 py-2 text-xs">{t.freight_mode === "per_ton" ? `${Number(t.rate_per_ton).toFixed(0)}/ton` : "Fixed"}</td>
                    <td className="px-3 py-2 text-right font-mono font-semibold">{fmtCurrency(t.freight_amount)}</td>
                  </tr>
                ))}
                {trips.length === 0 && (
                  <tr><td colSpan={7} className="px-4 py-12 text-center text-zinc-400">No pending trips for this customer.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {selectedTrips.length > 0 && (
        <section className="border border-zinc-950 bg-white rounded-sm p-5" data-testid="invoice-preview-totals">
          <div className="text-sm font-bold uppercase tracking-wider mb-3">Preview Totals</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1 text-sm">
              <Row k="Trips Selected" v={selectedTrips.length} mono />
              <Row k="Freight Total" v={fmtCurrency(freightTotal)} mono />
              {haltingTotal > 0 && <Row k="Halting Charges" v={fmtCurrency(haltingTotal)} mono />}
              {excessTotal > 0 && <Row k="Excess Charges" v={fmtCurrency(excessTotal)} mono />}
              {shortageTotal > 0 && <Row k="Less: Shortage" v={`(${fmtCurrency(shortageTotal)})`} mono />}
              {dieselDedTotal > 0 && <Row k="Less: Diesel from Customer" v={`(${fmtCurrency(dieselDedTotal)})`} mono />}
              {advanceDedTotal > 0 && <Row k="Less: Customer Advance" v={`(${fmtCurrency(advanceDedTotal)})`} mono />}
              <Row k="Net Freight (Taxable)" v={fmtCurrency(subtotal)} mono />
              {gstType === "cgst_sgst" ? (
                <>
                  <Row k="CGST @ 2.5%" v={fmtCurrency(cgst)} mono />
                  <Row k="SGST @ 2.5%" v={fmtCurrency(sgst)} mono />
                </>
              ) : (
                <Row k="IGST @ 5%" v={fmtCurrency(igst)} mono />
              )}
              {rcm && <Row k="RCM (tax not collected)" v="—" muted />}
              <Row k="Total Amount" v={fmtCurrency(grossTotal)} mono />
              {Math.abs(roundOff) >= 0.005 && (
                <Row k="Round Off" v={`${roundOff > 0 ? "+" : "−"} ${fmtCurrency(Math.abs(roundOff))}`} mono muted />
              )}
            </div>
            <div className="bg-amber-50 border border-amber-200 p-4 rounded-sm text-right">
              <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Final Payable</div>
              <div className="font-mono text-3xl font-black text-amber-900 mt-2">{fmtCurrency(finalTotal)}</div>
            </div>
          </div>

          <div className="mt-4">
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Notes · గమనికలు</label>
            <textarea data-testid="invoice-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} className={inputCls} />
          </div>

          <div className="mt-4 flex justify-end">
            <button data-testid="create-invoice-btn" disabled={!canSubmit || create.isPending} onClick={() => { idemKeyRef.current = draft.getKeyForSave(); create.mutate(); }} className="px-6 py-3 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
              {create.isPending ? "Creating..." : "Create Invoice"}
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

function NextNumberChip({ invoiceDate, onPreview }) {
  const { data } = useQuery({
    queryKey: ["invoice-next-preview", invoiceDate],
    queryFn: async () => (await api.get("/invoices/next-preview", { params: { invoice_date: invoiceDate } })).data,
    enabled: !!invoiceDate,
    staleTime: 5000,
  });
  React.useEffect(() => { if (data && onPreview) onPreview(data); }, [data, onPreview]);
  const today = new Date().toISOString().slice(0, 10);
  const isFuture = invoiceDate > today;
  const daysOld = invoiceDate && !isFuture
    ? Math.floor((new Date(today) - new Date(invoiceDate)) / 86400000)
    : 0;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px]" data-testid="invoice-next-chip">
      {isFuture ? (
        <span className="px-2 py-0.5 rounded-sm bg-rose-100 text-rose-800 border border-rose-300 font-semibold" data-testid="invoice-future-warning">
          Future date not allowed
        </span>
      ) : data ? (
        <>
          {daysOld > 90 && (
            <span className="px-2 py-0.5 rounded-sm bg-amber-100 text-amber-900 border border-amber-300" data-testid="invoice-backdated-warning">
              Backdated {daysOld} days
            </span>
          )}
        </>
      ) : (
        <span className="text-zinc-500">Fetching next number…</span>
      )}
    </div>
  );
}


const inputCls = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";

function Row({ k, v, mono, muted }) {
  return (
    <div className="flex justify-between border-b border-zinc-100 py-1.5">
      <span className={muted ? "text-zinc-500" : ""}>{k}</span>
      <span className={`${mono ? "font-mono" : ""} ${muted ? "text-zinc-400" : "font-semibold"}`}>{v}</span>
    </div>
  );
}
