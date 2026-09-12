import React, { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X, FileText, MapPin, Search, Loader2 } from "lucide-react";
import { StateSelect } from "@/lib/states";
import ShipSitesModal from "@/components/ShipSitesModal";
import PolicyChangeDialog from "@/components/PolicyChangeDialog";
import DuplicateMasterModal, { parseDuplicateError } from "@/components/DuplicateMasterModal";
import BankAccountsSection from "@/components/BankAccountsSection";

const EMPTY = {
  name: "", address: "", phone: "", gstin: "", pan: "", state: "",
  // Iter89 Phase 1.5 — Freight + Shortage master defaults
  default_freight_method: "per_ton_loading",
  shortage_config: { limit: 0, limit_type: "pct", method: "net_shortage",
                     effective_from: "", active: true, remarks: "" },
};
const PAGE_SIZE = 50;

export default function Customers() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [shipCust, setShipCust] = useState(null);
  // Iter127a UAT — user-facing duplicate modal state.
  const [dup, setDup] = useState(null); // { existing, matchedField } | null
  // Iter105 — Policy Change Workflow. When editing a customer and the
  // freight method / shortage config differ from the DB, hold the pending
  // save in this state and let PolicyChangeDialog decide whether the master
  // is saved as-is (OFF) or applied to selected historical trips (ON).
  const [policyDlg, setPolicyDlg] = useState(null);

  // Iter68 — debounced server-side search
  const [rawQuery, setRawQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [page, setPage] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQuery(rawQuery.trim());
      setPage(0);
    }, 300);
    return () => clearTimeout(t);
  }, [rawQuery]);

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["customers-paginated", debouncedQuery, page],
    queryFn: async () => {
      const params = { limit: PAGE_SIZE, skip: page * PAGE_SIZE };
      if (debouncedQuery) params.q = debouncedQuery;
      return (await api.get("/customers", { params })).data;
    },
    placeholderData: keepPreviousData,
  });

  const customers = data?.items || [];
  const total = data?.total ?? 0;
  const hasMore = data?.has_more ?? false;

  const save = useMutation({
    mutationFn: async (opts = {}) => {
      const headers = opts.confirmName ? { "X-Confirm-Name-Match": "allow" } : {};
      if (editing) {
        return (await api.put(`/customers/${editing.id}`, { ...editing, ...form }, { headers })).data;
      }
      return (await api.post("/customers", form, { headers })).data;
    },
    onSuccess: () => {
      toast.success(editing ? "Customer updated" : "Customer created");
      qc.invalidateQueries({ queryKey: ["customers-paginated"] });
      qc.invalidateQueries({ queryKey: ["customers"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setOpen(false); setEditing(null); setForm(EMPTY);
    },
    onError: (e) => {
      const d = parseDuplicateError(e);
      if (d) { setDup(d); return; }
      toast.error(typeof e?.response?.data?.detail === "string" ? e.response.data.detail : "Failed to save");
    },
  });

  // Iter105 — Detect a policy change on submit. If the customer's freight
  // method or shortage_config differs from the DB row we intercept the save
  // and open PolicyChangeDialog. If nothing changed we fall through to the
  // normal mutation (unchanged legacy behaviour for new customers / trivial
  // edits like name / GSTIN).
  const _policyChanged = (dbRow, next) => {
    if (!dbRow) return false;
    if ((dbRow.default_freight_method || "") !== (next.default_freight_method || "")) return true;
    const a = dbRow.shortage_config || {};
    const b = next.shortage_config || {};
    return (
      Number(a.limit || 0) !== Number(b.limit || 0) ||
      (a.limit_type || "pct") !== (b.limit_type || "pct") ||
      (a.method || "net_shortage") !== (b.method || "net_shortage") ||
      (a.effective_from || "") !== (b.effective_from || "") ||
      Boolean(a.active !== false) !== Boolean(b.active !== false)
    );
  };
  // Iter105 fix (UAT-1) — A policy-bearing customer must always route Save
  // through the Policy Change Dialog, even when the form values match the
  // DB exactly. This is the "re-apply the current policy to old trips
  // that have empty/stale snapshots" case, which is the exact scenario the
  // user hit on MEGHA (policy already in the master, but the 12-May-2026
  // trip was created before the policy existed).
  const _hasEffectivePolicy = (f) => Boolean((f?.shortage_config?.effective_from || "").trim());
  const _shouldOpenPolicyDialog = () => {
    if (!editing) return false;                  // new-customer flow: no dialog
    if (_policyChanged(editing, form)) return true;
    return _hasEffectivePolicy(form);            // policy is set → always review
  };
  const openPolicyDialog = () => {
    setPolicyDlg({
      customerId: editing.id,
      customerName: form.name || editing.name,
      oldPolicy: {
        default_freight_method: editing.default_freight_method || "per_ton_loading",
        shortage_config: editing.shortage_config || {},
      },
      newPolicy: {
        default_freight_method: form.default_freight_method || "per_ton_loading",
        shortage_config: form.shortage_config || {},
      },
    });
  };
  const handleSubmit = (e) => {
    e.preventDefault();
    if (_shouldOpenPolicyDialog()) {
      openPolicyDialog();
      return;
    }
    saveWithReturn.mutate();
  };

  const del = useMutation({
    mutationFn: async (id) => (await api.delete(`/customers/${id}`)).data,
    onSuccess: () => {
      toast.success("Deleted");
      qc.invalidateQueries({ queryKey: ["customers-paginated"] });
      qc.invalidateQueries({ queryKey: ["customers"] });
    },
  });

  const openEdit = (c) => { setEditing(c); setForm({ ...EMPTY, ...c }); setOpen(true); };
  const openNew = () => { setEditing(null); setForm(EMPTY); setOpen(true); };

  // Iter104b — Deep-link edit support. `/customers?edit={id}&returnTo=history`
  // opens the Edit modal for that customer on mount. On save, if returnTo is
  // "history", navigate back to the Customer View. Existing UX unaffected.
  const [searchParams, setSearchParams] = useSearchParams();
  const navRR = useNavigate();
  const editIdFromUrl = searchParams.get("edit");
  const returnTo = searchParams.get("returnTo");
  useEffect(() => {
    if (!editIdFromUrl || open) return;
    (async () => {
      try {
        const { data } = await api.get("/customers", { params: { ids: editIdFromUrl, limit: 1 } });
        const found = (data?.items || []).find((c) => c.id === editIdFromUrl);
        if (found) openEdit(found);
      } catch {}
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editIdFromUrl]);
  // Wrap the mutation success to honour `returnTo`.
  const _origSave = save;
  const saveWithReturn = {
    ..._origSave,
    mutate: (...args) => {
      _origSave.mutate(...args, {
        onSuccess: (data) => {
          if (returnTo === "history" && editIdFromUrl) {
            setOpen(false); setEditing(null); setForm(EMPTY);
            setSearchParams({}, { replace: true });
            navRR(`/customers/history/${editIdFromUrl}`, { replace: true });
          }
        },
      });
    },
  };

  const start = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const end = Math.min((page + 1) * PAGE_SIZE, total);

  return (
    <div className="space-y-6" data-testid="customers-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Master</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">కస్టమర్లు</span>
            <span className="text-zinc-400"> · Customers</span>
          </h1>
        </div>
        <button data-testid="add-customer-btn" onClick={openNew} className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2">
          <Plus size={14} /> Add Customer
        </button>
      </header>

      {/* Iter68 — server-side search bar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            data-testid="customer-search-input"
            value={rawQuery}
            onChange={(e) => setRawQuery(e.target.value)}
            placeholder="Search name, phone, GSTIN, or code…"
            className="w-full border border-zinc-300 pl-9 pr-9 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white"
          />
          {rawQuery && (
            <button
              type="button"
              data-testid="customer-search-clear"
              onClick={() => setRawQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-rose-600"
            >
              <X size={14} />
            </button>
          )}
        </div>
        <div className="text-xs text-zinc-500" data-testid="customer-search-count">
          {isFetching && <Loader2 size={12} className="inline animate-spin mr-1" />}
          {debouncedQuery ? `${total} match${total === 1 ? "" : "es"} for “${debouncedQuery}”` : `${total} customers`}
        </div>
      </div>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
        <table className="w-full text-sm" data-testid="customers-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-4 py-2 font-semibold">Name</th>
              <th className="text-left px-4 py-2 font-semibold">GSTIN</th>
              <th className="text-left px-4 py-2 font-semibold">Phone</th>
              <th className="text-left px-4 py-2 font-semibold">State</th>
              <th className="text-right px-4 py-2 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {customers.map((c) => (
              <tr key={c.id} data-testid={`customer-row-${c.id}`} className="border-t border-zinc-100 hover:bg-zinc-50">
                <td className="px-4 py-3 font-semibold">
                  {/* Iter104 · Option A — clicking the Name opens the existing
                      Customer History details page (trip history + balances). */}
                  <Link
                    to={`/customers/history/${c.id}`}
                    data-testid={`view-customer-${c.id}`}
                    className="hover:text-indigo-700 hover:underline"
                    title="View customer details"
                  >
                    {c.name}
                  </Link>
                </td>
                <td className="px-4 py-3 font-mono text-xs">{c.gstin || "—"}</td>
                <td className="px-4 py-3">{c.phone || "—"}</td>
                <td className="px-4 py-3">{c.state || "—"}</td>
                <td className="px-4 py-3 text-right">
                  <Link data-testid={`history-customer-${c.id}`} to={`/customers/history/${c.id}`} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-indigo-300 text-indigo-700 rounded-sm mr-2 hover:bg-indigo-600 hover:text-white transition">
                    <FileText size={12} /> History
                  </Link>
                  <button data-testid={`ship-sites-customer-${c.id}`} onClick={() => setShipCust(c)} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-amber-300 text-amber-800 rounded-sm mr-2 hover:bg-amber-600 hover:text-white transition">
                    <MapPin size={12} /> Ship-To ({(c.ship_sites || []).filter((s) => s.is_active !== false).length})
                  </button>
                  <button data-testid={`edit-customer-${c.id}`} onClick={() => openEdit(c)} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-zinc-200 rounded-sm mr-2 hover:bg-zinc-950 hover:text-white">
                    <Pencil size={12} /> Edit
                  </button>
                  <button data-testid={`delete-customer-${c.id}`} onClick={() => { if (window.confirm("Delete this customer?")) del.mutate(c.id); }} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-50">
                    <Trash2 size={12} /> Delete
                  </button>
                </td>
              </tr>
            ))}
            {!isLoading && customers.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-12 text-center text-zinc-400" data-testid="customers-empty">
                {debouncedQuery ? `No customers match “${debouncedQuery}”.` : "No customers yet."}
              </td></tr>
            )}
          </tbody>
        </table>

        {/* Iter68 — pagination controls */}
        {total > 0 && (
          <div className="flex items-center justify-between border-t border-zinc-100 px-4 py-2 text-xs text-zinc-600 bg-zinc-50" data-testid="customer-pagination">
            <div>Showing <b>{start}</b>–<b>{end}</b> of <b>{total}</b></div>
            <div className="flex items-center gap-2">
              <button
                data-testid="customer-page-prev"
                disabled={page === 0 || isFetching}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="px-3 py-1 border border-zinc-300 rounded-sm hover:bg-white disabled:opacity-40"
              >Prev</button>
              <span>Page {page + 1}</span>
              <button
                data-testid="customer-page-next"
                disabled={!hasMore || isFetching}
                onClick={() => setPage((p) => p + 1)}
                className="px-3 py-1 border border-zinc-300 rounded-sm hover:bg-white disabled:opacity-40"
              >Next</button>
            </div>
          </div>
        )}
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4" data-testid="customer-modal">
          <div className="bg-white w-full max-w-lg border border-zinc-950 rounded-sm flex flex-col max-h-[90vh]">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200 shrink-0">
              <h3 className="font-bold">{editing ? "Edit Customer" : "New Customer"}</h3>
              <button onClick={() => setOpen(false)} data-testid="close-customer-modal"><X size={18} /></button>
            </div>
            <form onSubmit={handleSubmit} className="p-5 space-y-3 overflow-y-auto flex-1">
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Name / పేరు *</label>
                <input data-testid="customer-input-name" required value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none" />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
                  GSTIN <span className="text-emerald-700 normal-case">(auto-fills State &amp; PAN)</span>
                </label>
                <input data-testid="customer-input-gstin" value={form.gstin || ""}
                  onChange={async (e) => {
                    const v = e.target.value.toUpperCase();
                    const next = { ...form, gstin: v };
                    if (v.length === 15) {
                      try {
                        const { data } = await api.get("/gstin/lookup", { params: { gstin: v } });
                        if (data.valid_format) {
                          if (data.state) next.state = data.state;
                          if (data.pan) next.pan = data.pan;
                          if (data.checksum_ok) toast.success(`GSTIN valid · ${data.state}`);
                          else toast.warning("GSTIN format ok but checksum failed");
                        } else {
                          toast.error("Invalid GSTIN format");
                        }
                      } catch {}
                    }
                    setForm(next);
                  }}
                  placeholder="e.g. 37AAECR5210P2Z2"
                  maxLength={15}
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm font-mono uppercase focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none" />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">PAN</label>
                <input data-testid="customer-input-pan" value={form.pan || ""} onChange={(e) => setForm({ ...form, pan: e.target.value.toUpperCase() })}
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm font-mono uppercase focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none" />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Phone / ఫోన్</label>
                <input data-testid="customer-input-phone" value={form.phone || ""} onChange={(e) => setForm({ ...form, phone: e.target.value })}
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none" />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">State / రాష్ట్రం</label>
                <StateSelect
                  value={form.state}
                  onChange={(v) => setForm({ ...form, state: v })}
                  dataTestId="customer-input-state"
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white"
                />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Address / చిరునామా</label>
                <textarea
                  data-testid="customer-input-address"
                  rows={2}
                  value={form.address || ""}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none"
                />
              </div>

              {/* Iter89 Phase 1.5 — Freight Configuration */}
              <div className="border-t border-zinc-200 pt-3 mt-3">
                <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-2">Freight Configuration</div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Default Freight Calculation Method</label>
                <select
                  data-testid="customer-input-freight-method"
                  value={form.default_freight_method || "per_ton_loading"}
                  onChange={(e) => setForm({ ...form, default_freight_method: e.target.value })}
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white"
                >
                  <option value="per_ton_loading">Loading Qty Basis</option>
                  <option value="per_ton_unloading">Unloading Qty Basis</option>
                  <option value="per_ton_higher_of">Higher of Loading / Unloading Qty</option>
                  <option value="fixed">Fixed Freight</option>
                </select>
                <div className="text-[10px] text-zinc-500 mt-1">Default only. Editable at Trip level.</div>
              </div>

              {/* Iter103 · Phase 1.6 — Shortage Configuration (simplified).
                  Product Master owns the allowance; Customer owns the deduction
                  METHOD. The Custom Allowance section is now OPTIONAL and hidden
                  behind a toggle — normal customers just pick their method. */}
              <div className="border-t border-zinc-200 pt-3 mt-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500">Customer Shortage Rule</div>
                  {/* Iter105 fix (UAT-1) — Explicit entry point into the Policy
                      Change Dialog. Available on the edit form for any
                      existing customer, so a user can review and apply the
                      CURRENT policy to previous pending trips even when no
                      field on the form has been changed. */}
                  {editing && (
                    <button
                      type="button"
                      data-testid="review-policy-pending-trips-btn"
                      onClick={openPolicyDialog}
                      className="text-[10px] uppercase tracking-wider font-bold px-2 py-1 border border-amber-500 text-amber-700 hover:bg-amber-50"
                    >
                      Review policy · pending trips…
                    </button>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Deduction Method</label>
                    <select
                      data-testid="customer-input-shortage-method"
                      value={form.shortage_config?.method || "net_shortage"}
                      onChange={(e) => setForm({ ...form, shortage_config: { ...(form.shortage_config || {}), method: e.target.value } })}
                      className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm bg-white outline-none focus:border-zinc-950"
                    >
                      <option value="net_shortage">Net Shortage (deduct excess above limit)</option>
                      <option value="full_after_limit">Full Shortage After Limit Exceeded</option>
                    </select>
                    <div className="text-[10px] text-zinc-500 mt-1">
                      Applies once the Product Master's allowance is exceeded. Product allowance is the default limit.
                    </div>
                  </div>
                  {/* Custom Allowance override — collapsed by default */}
                  <div className="col-span-2 border border-dashed border-zinc-300 rounded-sm bg-zinc-50 p-3">
                    <label className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-zinc-700 cursor-pointer">
                      <input
                        type="checkbox"
                        data-testid="customer-input-shortage-custom-toggle"
                        checked={Number(form.shortage_config?.limit || 0) > 0}
                        onChange={(e) => {
                          if (e.target.checked) {
                            // enable custom override with a sensible default (0.5 pct)
                            setForm({ ...form, shortage_config: {
                              ...(form.shortage_config || {}),
                              limit: Number(form.shortage_config?.limit || 0.5),
                              limit_type: form.shortage_config?.limit_type || "pct",
                            }});
                          } else {
                            // disable custom override → fall back to Product Master
                            setForm({ ...form, shortage_config: {
                              ...(form.shortage_config || {}),
                              limit: 0, limit_type: "pct",
                            }});
                          }
                        }}
                        className="accent-zinc-950"
                      />
                      Custom Allowance — overrides Product Master
                    </label>
                    <div className="text-[10px] text-zinc-500 mt-1 mb-2">
                      Leave OFF for standard customers (Product's allowance is used). Turn ON only for contract exceptions.
                    </div>
                    {Number(form.shortage_config?.limit || 0) > 0 && (
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Shortage Limit</label>
                          <input
                            data-testid="customer-input-shortage-limit"
                            type="number" step="0.01" min="0"
                            value={form.shortage_config?.limit ?? 0}
                            onChange={(e) => setForm({ ...form, shortage_config: { ...(form.shortage_config || {}), limit: Number(e.target.value) } })}
                            className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white"
                          />
                        </div>
                        <div>
                          <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Limit Type</label>
                          <select
                            data-testid="customer-input-shortage-limit-type"
                            value={form.shortage_config?.limit_type || "pct"}
                            onChange={(e) => setForm({ ...form, shortage_config: { ...(form.shortage_config || {}), limit_type: e.target.value } })}
                            className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm bg-white outline-none focus:border-zinc-950"
                          >
                            <option value="pct">% of Loaded Qty</option>
                            <option value="kg">Fixed KG</option>
                          </select>
                        </div>
                      </div>
                    )}
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Effective From</label>
                    <input
                      data-testid="customer-input-shortage-effective-from"
                      type="date"
                      value={form.shortage_config?.effective_from || ""}
                      onChange={(e) => setForm({ ...form, shortage_config: { ...(form.shortage_config || {}), effective_from: e.target.value } })}
                      className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm outline-none focus:border-zinc-950"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Status</label>
                    <select
                      data-testid="customer-input-shortage-active"
                      value={form.shortage_config?.active === false ? "0" : "1"}
                      onChange={(e) => setForm({ ...form, shortage_config: { ...(form.shortage_config || {}), active: e.target.value === "1" } })}
                      className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm bg-white outline-none focus:border-zinc-950"
                    >
                      <option value="1">Active</option>
                      <option value="0">Inactive</option>
                    </select>
                  </div>
                  <div className="col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Remarks</label>
                    <input
                      data-testid="customer-input-shortage-remarks"
                      value={form.shortage_config?.remarks || ""}
                      onChange={(e) => setForm({ ...form, shortage_config: { ...(form.shortage_config || {}), remarks: e.target.value } })}
                      className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm outline-none focus:border-zinc-950"
                    />
                  </div>
                </div>
                <div className="text-[10px] text-zinc-500 mt-2">Historical protection: existing Trips retain their original snapshot. This rule applies only to future Trips.</div>
              </div>
              <BankAccountsSection kind="party" partyType="customer" partyId={editing?.id || ""} />
              <div className="flex gap-2 justify-end pt-2">
                <button type="button" onClick={() => setOpen(false)} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
                <button data-testid="save-customer-btn" type="submit" disabled={save.isPending} className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
                  {save.isPending ? "Saving..." : "Save"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {shipCust && (
        <ShipSitesModal customer={shipCust} onClose={() => setShipCust(null)} />
      )}

      {policyDlg && (
        <PolicyChangeDialog
          customerId={policyDlg.customerId}
          customerName={policyDlg.customerName}
          oldPolicy={policyDlg.oldPolicy}
          newPolicy={policyDlg.newPolicy}
          onClose={() => setPolicyDlg(null)}
          onSaveMaster={async () => {
            // OFF path — parent still runs the standard PUT /customers.
            await api.put(`/customers/${policyDlg.customerId}`, { ...editing, ...form });
          }}
          onDone={() => {
            setPolicyDlg(null);
            qc.invalidateQueries({ queryKey: ["customers-paginated"] });
            qc.invalidateQueries({ queryKey: ["customers"] });
            qc.invalidateQueries({ queryKey: ["trips"] });
            qc.invalidateQueries({ queryKey: ["dashboard"] });
            setOpen(false); setEditing(null); setForm(EMPTY);
            if (returnTo === "history" && editIdFromUrl) {
              setSearchParams({}, { replace: true });
              navRR(`/customers/history/${editIdFromUrl}`, { replace: true });
            }
          }}
        />
      )}
      {dup && (
        <DuplicateMasterModal
          open entity="customer"
          existing={dup.existing} matchedField={dup.matchedField}
          onCancel={() => setDup(null)}
          onOpenExisting={(ex) => { setDup(null); setOpen(false); setEditing(null); setForm(EMPTY); openEdit({ ...EMPTY, ...ex }); }}
          onContinueCreate={dup.matchedField === "name" ? () => { setDup(null); save.mutate({ confirmName: true }); } : undefined}
        />
      )}
    </div>
  );
}
