import React from "react";
import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { api, API, fmtCurrency, fmtDate } from "@/api";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Plus, CheckCircle2, Clock, Download, FileText, Trash2, Eye, Pencil, Copy, Share2, Search, X, ChevronLeft, ChevronRight, Bookmark, BookmarkPlus, FileWarning } from "lucide-react";
import SearchableSelect from "@/components/SearchableSelect";

const downloadEwayBill = async (tripId) => {
  const { api: ax } = await import("@/api");
  try {
    const { data } = await ax.get(`/trips/${tripId}/ewaybill`);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `ewaybill_${tripId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    console.error(e);
  }
};

const PAGE_SIZE = 100;
const EMPTY_FILTERS = {
  customer_id: "", vehicle_id: "", supplier_id: "",
  date_from: "", date_to: "", q: "",
};

export default function Trips() {
  const qc = useQueryClient();

  // Iter56 — Server-side filter / search / pagination state
  const [filters, setFilters] = React.useState(EMPTY_FILTERS);
  const [qDraft, setQDraft] = React.useState(""); // uncommitted free-text
  const [showHaltingOnly, setShowHaltingOnly] = React.useState(false);
  const [showMissingCustRef, setShowMissingCustRef] = React.useState(false); // Iter84
  const [sortHalting, setSortHalting] = React.useState(null); // null | "desc" | "asc"
  const [page, setPage] = React.useState(0);

  // Debounce the free-text search so we don't hit the backend on every keystroke.
  React.useEffect(() => {
    const t = setTimeout(() => {
      setFilters((f) => (f.q === qDraft ? f : { ...f, q: qDraft }));
      setPage(0);
    }, 300);
    return () => clearTimeout(t);
  }, [qDraft]);

  const activeFilterCount = React.useMemo(() => {
    let n = 0;
    if (filters.customer_id) n++;
    if (filters.vehicle_id) n++;
    if (filters.supplier_id) n++;
    if (filters.date_from) n++;
    if (filters.date_to) n++;
    if (filters.q?.trim()) n++;
    if (showHaltingOnly) n++;
    if (showMissingCustRef) n++;
    return n;
  }, [filters, showHaltingOnly, showMissingCustRef]);

  // Lookup master data for the searchable selects (small, cache-friendly).
  const { data: customers = [] } = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get("/customers")).data });
  const { data: vehicles = [] } = useQuery({ queryKey: ["vehicles"], queryFn: async () => (await api.get("/vehicles")).data });
  const { data: suppliers = [] } = useQuery({ queryKey: ["suppliers"], queryFn: async () => (await api.get("/suppliers")).data });
  const custMap = React.useMemo(() => Object.fromEntries(customers.map((c) => [c.id, c.name])), [customers]);

  // Iter57 P1 — Saved filter views (company-scoped by backend).
  const { data: savedViews = [] } = useQuery({ queryKey: ["saved-trip-filters"], queryFn: async () => (await api.get("/saved-trip-filters")).data });
  const saveView = useMutation({
    mutationFn: async ({ name, filter_state }) => (await api.post("/saved-trip-filters", { name, filter_state })).data,
    onSuccess: () => { toast.success("Filter view saved"); qc.invalidateQueries({ queryKey: ["saved-trip-filters"] }); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed to save"),
  });
  const deleteView = useMutation({
    mutationFn: async (fid) => (await api.delete(`/saved-trip-filters/${fid}`)).data,
    onSuccess: () => { toast.success("Filter view removed"); qc.invalidateQueries({ queryKey: ["saved-trip-filters"] }); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const applySavedView = (view) => {
    const s = view?.filter_state || {};
    setFilters({
      customer_id: s.customer_id || "",
      vehicle_id: s.vehicle_id || "",
      supplier_id: s.supplier_id || "",
      date_from: s.date_from || "",
      date_to: s.date_to || "",
      q: s.q || "",
    });
    setQDraft(s.q || "");
    setShowHaltingOnly(!!s.halting_only);
    setShowMissingCustRef(!!s.missing_cust_ref);
    setPage(0);
  };

  const handleSaveCurrentView = () => {
    if (activeFilterCount === 0) {
      toast.error("Apply at least one filter first");
      return;
    }
    const name = window.prompt("Name this view (e.g. 'Last 30d · ABC · unbilled')");
    if (!name || !name.trim()) return;
    saveView.mutate({
      name: name.trim(),
      filter_state: { ...filters, halting_only: showHaltingOnly, missing_cust_ref: showMissingCustRef },
    });
  };

  // Server-side trips query — key includes every filter + page so results are cached per combo.
  const tripsQ = useQuery({
    queryKey: ["trips", "search", filters, showHaltingOnly, showMissingCustRef, page],
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const params = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
      if (filters.customer_id) params.customer_id = filters.customer_id;
      if (filters.vehicle_id) params.vehicle_id = filters.vehicle_id;
      if (filters.supplier_id) params.supplier_id = filters.supplier_id;
      if (filters.date_from) params.date_from = filters.date_from;
      if (filters.date_to) params.date_to = filters.date_to;
      if (filters.q?.trim()) params.q = filters.q.trim();
      if (showHaltingOnly) params.halting_only = true;
      if (showMissingCustRef) params.missing_cust_ref = true;
      const res = await api.get("/trips", { params });
      const total = Number(res.headers?.["x-total-count"] ?? res.data?.length ?? 0);
      const hasMore = (res.headers?.["x-has-more"] ?? "").toString() === "true";
      return { items: res.data || [], total, hasMore };
    },
    keepPreviousData: true,
  });
  const trips = tripsQ.data?.items || [];
  const total = tripsQ.data?.total ?? 0;
  const hasMore = tripsQ.data?.hasMore || false;
  const isLoading = tripsQ.isFetching && !tripsQ.data;

  // Iter51 — Halting sort applied client-side over the current page (server-side sort is by date).
  const displayedTrips = React.useMemo(() => {
    let list = trips;
    if (sortHalting) {
      const dir = sortHalting === "desc" ? -1 : 1;
      const _age = (t) => {
        const anchor = t.unloading_date || t.date;
        if (!anchor) return 0;
        const then = new Date(anchor).getTime();
        return isNaN(then) ? 0 : (Date.now() - then) / 86400000;
      };
      list = [...list].sort((a, b) => {
        const primary = ((a.halting_amount || 0) - (b.halting_amount || 0)) * dir;
        if (primary !== 0) return primary;
        return (_age(b) - _age(a));
      });
    }
    return list;
  }, [trips, sortHalting]);

  const cycleHaltingSort = () => {
    setSortHalting((s) => (s === null ? "desc" : s === "desc" ? "asc" : null));
  };

  // Iter51 — Halting summary (across current page only when filtered; else across page)
  const pageHaltingSum = React.useMemo(
    () => trips.reduce((s, t) => s + (Number(t.halting_amount) || 0), 0),
    [trips]
  );
  const pageHaltingCount = React.useMemo(
    () => trips.filter((t) => (t.halting_amount || 0) > 0).length,
    [trips]
  );

  const del = useMutation({
    mutationFn: async ({ id, reason }) => (await api.delete(`/trips/${id}`, { params: { reason } })).data,
    onSuccess: () => { toast.success("Trip deleted"); qc.invalidateQueries({ queryKey: ["trips"] }); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  // ─── Iter58 P1 — Multi-select bulk actions ──────────────────────────────
  const [selected, setSelected] = React.useState(() => new Set());
  const nav = useNavigate();
  React.useEffect(() => { setSelected(new Set()); }, [filters, page, showHaltingOnly, showMissingCustRef]);
  const pageIds = React.useMemo(() => displayedTrips.map((t) => t.id), [displayedTrips]);
  const allOnPageSelected = pageIds.length > 0 && pageIds.every((id) => selected.has(id));
  const toggleAllOnPage = () => {
    setSelected((prev) => {
      const s = new Set(prev);
      if (allOnPageSelected) pageIds.forEach((id) => s.delete(id));
      else pageIds.forEach((id) => s.add(id));
      return s;
    });
  };
  const toggleOne = (id) => {
    setSelected((prev) => {
      const s = new Set(prev);
      if (s.has(id)) s.delete(id); else s.add(id);
      return s;
    });
  };
  const clearSelection = () => setSelected(new Set());
  const selectedTrips = React.useMemo(
    () => displayedTrips.filter((t) => selected.has(t.id)),
    [displayedTrips, selected]
  );
  const selectedInvoicedCount = selectedTrips.filter((t) => t.status === "invoiced").length;

  const bulkDelete = useMutation({
    mutationFn: async ({ trip_ids, reason, force_invoiced }) =>
      (await api.post("/trips/bulk-delete", { trip_ids, reason, force_invoiced })).data,
    onSuccess: (res) => {
      if (res?.requires_force) {
        toast.error(res.detail);
        return;
      }
      toast.success(`Deleted ${res.deleted_count} trip${res.deleted_count === 1 ? "" : "s"}${res.recomputed_invoices?.length ? ` · ${res.recomputed_invoices.length} invoice(s) recomputed` : ""}`);
      clearSelection();
      qc.invalidateQueries({ queryKey: ["trips"] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Bulk delete failed"),
  });
  const runBulkDelete = async () => {
    if (selected.size === 0) return;
    const trip_ids = Array.from(selected);
    const invoiced = selectedInvoicedCount;
    let confirmMsg = `Delete ${trip_ids.length} selected trip${trip_ids.length === 1 ? "" : "s"}?`;
    if (invoiced > 0) confirmMsg += `\n\n⚠ ${invoiced} of these trip(s) are linked to an invoice. Their invoice totals will be recomputed.`;
    if (!window.confirm(confirmMsg)) return;
    const reason = window.prompt("Reason for deletion (mandatory):");
    if (!reason || !reason.trim()) { toast.error("Reason required"); return; }
    let forceInvoiced = false;
    if (invoiced > 0) {
      forceInvoiced = window.confirm(
        `Type OK to confirm: ${invoiced} selected trip(s) are already INVOICED. Delete them anyway and recompute the linked invoices?`
      );
      if (!forceInvoiced) { toast.info("Bulk delete cancelled"); return; }
    }
    bulkDelete.mutate({ trip_ids, reason: reason.trim(), force_invoiced: forceInvoiced });
  };

  const bulkInvoice = useMutation({
    mutationFn: async (trip_ids) => {
      // Preflight: same customer + all unbilled
      const pf = (await api.post("/trips/bulk-invoice-preflight", { trip_ids })).data;
      if (!pf.ok) {
        const err = new Error(pf.detail || "Preflight failed");
        err._preflight = pf;
        throw err;
      }
      // Create the invoice via the existing endpoint — same GST/CGST/SGST/IGST logic.
      const { data } = await api.post("/invoices", {
        customer_id: pf.customer_id,
        trip_ids,
        gst_type: "cgst_sgst",   // Backend auto-corrects based on state match anyway
        rcm: false,
      });
      return data;
    },
    onSuccess: (inv) => {
      toast.success(`Invoice ${inv.invoice_number} created (₹${(inv.total_amount || 0).toLocaleString("en-IN")})`);
      clearSelection();
      qc.invalidateQueries({ queryKey: ["trips"] });
      qc.invalidateQueries({ queryKey: ["invoices"] });
      // Navigate straight to the new invoice so the operator can review/print
      nav(`/invoices/${inv.id}`);
    },
    onError: (e) => {
      const detail = e?._preflight?.detail || e?.response?.data?.detail || e.message || "Bulk invoice failed";
      toast.error(detail);
    },
  });
  const runBulkInvoice = () => {
    if (selected.size === 0) return;
    const trip_ids = Array.from(selected);
    if (!window.confirm(`Create ONE invoice covering the ${trip_ids.length} selected trip${trip_ids.length === 1 ? "" : "s"}? All must belong to the same customer and be unbilled.`)) return;
    bulkInvoice.mutate(trip_ids);
  };

  const askDelete = (t) => {
    const linked = t.invoice_id ? "\n⚠ This trip is linked to an invoice. The invoice totals will be recomputed." : "";
    const reason = window.prompt(`Delete trip on ${t.date} (${t.vehicle_number})?${linked}\n\nReason for deletion (mandatory):`);
    if (!reason || !reason.trim()) { toast.error("Reason required"); return; }
    del.mutate({ id: t.id, reason });
  };

  const clearFilters = () => {
    setFilters(EMPTY_FILTERS);
    setQDraft("");
    setShowHaltingOnly(false);
    setSortHalting(null);
    setPage(0);
  };

  const setFilter = (k, v) => {
    setFilters((f) => ({ ...f, [k]: v }));
    setPage(0);
  };

  // Quick-preset date ranges
  const setLastNDays = (n) => {
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - (n - 1));
    setFilters((f) => ({ ...f, date_from: from.toISOString().slice(0, 10), date_to: to.toISOString().slice(0, 10) }));
    setPage(0);
  };

  const pageEnd = Math.min((page + 1) * PAGE_SIZE, total);
  const pageStart = total === 0 ? 0 : page * PAGE_SIZE + 1;

  return (
    <div className="space-y-6" data-testid="trips-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Log</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">ట్రిప్స్</span>
            <span className="text-zinc-400"> · Trips</span>
          </h1>
        </div>
        <div className="flex gap-2">
          <button
            data-testid="halting-only-toggle"
            onClick={() => { setShowHaltingOnly((v) => !v); setPage(0); }}
            className={`px-3 py-2 text-xs uppercase tracking-wider font-semibold rounded-sm inline-flex items-center gap-2 border transition-colors
              ${showHaltingOnly ? "bg-amber-500 text-white border-amber-600 hover:bg-amber-600" : "bg-white text-amber-800 border-amber-400 hover:bg-amber-50"}`}
            title={showHaltingOnly ? "Show all trips" : "Show only trips with halting charges"}
          >
            <Clock size={14} /> Halting Only · <span className="font-mono font-bold">{pageHaltingCount}</span>
          </button>
          <button
            data-testid="missing-cust-ref-toggle"
            onClick={() => { setShowMissingCustRef((v) => !v); setPage(0); }}
            className={`px-3 py-2 text-xs uppercase tracking-wider font-semibold rounded-sm inline-flex items-center gap-2 border transition-colors
              ${showMissingCustRef ? "bg-rose-600 text-white border-rose-700 hover:bg-rose-700" : "bg-white text-rose-800 border-rose-400 hover:bg-rose-50"}`}
            title={showMissingCustRef ? "Show all trips" : "Show only trips missing a Customer Ref / Invoice No."}
          >
            <FileWarning size={14} /> Missing Cust Ref
          </button>
          <Link to="/trips/import" data-testid="import-trips-btn" className="px-3 py-2 text-xs uppercase tracking-wider font-semibold border border-zinc-950 text-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white inline-flex items-center gap-2">
            <Plus size={14} /> Import Excel
          </Link>
          <Link to="/trips/new" data-testid="new-trip-btn" className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2">
            <Plus size={14} /> New Trip
          </Link>
        </div>
      </header>

      {/* Iter56 — Search & Filter bar */}
      <div className="border border-zinc-200 bg-white rounded-sm p-4 space-y-3" data-testid="trips-filter-bar">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          {/* Free-text search */}
          <div className="md:col-span-2">
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Search · Trip / LR / Vehicle / Customer</label>
            <div className="relative mt-1">
              <Search size={14} className="absolute left-3 top-2.5 text-zinc-400 pointer-events-none" />
              <input
                data-testid="trips-search-input"
                value={qDraft}
                onChange={(e) => setQDraft(e.target.value)}
                placeholder="Type to search LR number, vehicle, customer name, route…"
                className="w-full pl-9 pr-9 py-2 border border-zinc-300 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none"
              />
              {qDraft && (
                <button type="button" data-testid="trips-search-clear" onClick={() => setQDraft("")} className="absolute right-2 top-2 p-0.5 text-zinc-400 hover:text-zinc-950" title="Clear search">
                  <X size={14} />
                </button>
              )}
            </div>
          </div>
          {/* Date range */}
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">From Date</label>
            <input
              data-testid="trips-filter-date-from"
              type="date"
              value={filters.date_from}
              onChange={(e) => setFilter("date_from", e.target.value)}
              className="w-full mt-1 border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none"
            />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">To Date</label>
            <input
              data-testid="trips-filter-date-to"
              type="date"
              value={filters.date_to}
              onChange={(e) => setFilter("date_to", e.target.value)}
              className="w-full mt-1 border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          {/* Customer picker */}
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Customer</label>
            <div className="mt-1">
              <SearchableSelect
                dataTestId="trips-filter-customer"
                value={filters.customer_id}
                onChange={(v) => setFilter("customer_id", v || "")}
                placeholder="All customers · type to search"
                options={customers.map((c) => ({
                  value: c.id, label: c.name,
                  meta: [c.gstin, c.state, c.phone].filter(Boolean).join(" · "),
                }))}
              />
            </div>
          </div>
          {/* Vehicle picker */}
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Vehicle Number</label>
            <div className="mt-1">
              <SearchableSelect
                dataTestId="trips-filter-vehicle"
                value={filters.vehicle_id}
                onChange={(v) => setFilter("vehicle_id", v || "")}
                placeholder="All vehicles · type to search"
                options={vehicles.map((v) => ({
                  value: v.id, label: v.vehicle_number,
                  meta: [v.vehicle_type === "supplier" ? "Supplier" : "Own", v.owner_name || v.supplier_name].filter(Boolean).join(" · "),
                }))}
              />
            </div>
          </div>
          {/* Supplier picker */}
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Supplier</label>
            <div className="mt-1">
              <SearchableSelect
                dataTestId="trips-filter-supplier"
                value={filters.supplier_id}
                onChange={(v) => setFilter("supplier_id", v || "")}
                placeholder="All suppliers · type to search"
                options={suppliers.map((s) => ({
                  value: s.id, label: s.name,
                  meta: [s.mobile, s.gst_in].filter(Boolean).join(" · "),
                }))}
              />
            </div>
          </div>
          {/* Preset buttons + clear */}
          <div className="flex flex-col justify-end gap-2">
            <div className="flex flex-wrap gap-1" data-testid="trips-filter-presets">
              <button type="button" onClick={() => setLastNDays(7)} className="px-2 py-1 text-[10px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100" data-testid="preset-7d">Last 7d</button>
              <button type="button" onClick={() => setLastNDays(30)} className="px-2 py-1 text-[10px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100" data-testid="preset-30d">Last 30d</button>
              <button type="button" onClick={() => setLastNDays(90)} className="px-2 py-1 text-[10px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100" data-testid="preset-90d">Last 90d</button>
            </div>
            <div className="grid grid-cols-2 gap-1">
              <button
                type="button"
                data-testid="trips-clear-filters"
                onClick={clearFilters}
                disabled={activeFilterCount === 0}
                className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold border rounded-sm inline-flex items-center justify-center gap-1 disabled:opacity-40 disabled:cursor-not-allowed
                  bg-rose-50 text-rose-800 border-rose-300 hover:bg-rose-100"
              >
                <X size={12} /> Clear {activeFilterCount > 0 && <span className="font-mono">({activeFilterCount})</span>}
              </button>
              <ExportMenu
                filters={filters}
                showHaltingOnly={showHaltingOnly}
                showMissingCustRef={showMissingCustRef}
                total={total}
              />
            </div>
          </div>
        </div>

        {/* Iter57 P1 — Saved views strip */}
        <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-zinc-100" data-testid="trips-saved-views">
          <span className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 flex items-center gap-1">
            <Bookmark size={11} /> Saved Views
          </span>
          {savedViews.length === 0 ? (
            <span className="text-[11px] text-zinc-400 italic">No saved views yet — build a filter and click "+ Save Current".</span>
          ) : (
            savedViews.map((v) => (
              <span key={v.id} data-testid={`saved-view-${v.id}`} className="inline-flex items-center gap-1 border border-indigo-200 bg-indigo-50 rounded-full pl-2 pr-1 py-0.5 text-[11px] group">
                <button
                  type="button"
                  data-testid={`apply-view-${v.id}`}
                  onClick={() => applySavedView(v)}
                  className="font-semibold text-indigo-800 hover:underline"
                  title={JSON.stringify(v.filter_state)}
                >
                  {v.name}
                </button>
                <button
                  type="button"
                  data-testid={`delete-view-${v.id}`}
                  onClick={() => { if (window.confirm(`Delete saved view "${v.name}"?`)) deleteView.mutate(v.id); }}
                  className="text-indigo-400 hover:text-rose-600 p-0.5 opacity-60 group-hover:opacity-100"
                  title="Delete this view"
                >
                  <X size={10} />
                </button>
              </span>
            ))
          )}
          <button
            type="button"
            data-testid="save-current-view-btn"
            onClick={handleSaveCurrentView}
            disabled={activeFilterCount === 0 || saveView.isPending}
            className="ml-auto inline-flex items-center gap-1 px-2 py-1 text-[10px] uppercase tracking-wider font-bold border border-indigo-300 text-indigo-700 rounded-sm hover:bg-indigo-50 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <BookmarkPlus size={11} /> Save Current
          </button>
        </div>
      </div>

      {/* Results summary strip */}
      <div className="flex flex-wrap items-center gap-4 -mt-2 text-xs" data-testid="trips-summary">
        <span className="text-zinc-500">
          {isLoading ? (
            "Loading…"
          ) : total === 0 ? (
            <>No trips match{activeFilterCount > 0 ? " your filters" : ""}</>
          ) : (
            <>Showing <span className="font-bold text-zinc-900" data-testid="trip-count-shown">{pageStart}–{pageEnd}</span> of <span className="font-bold text-zinc-900" data-testid="trip-count-total">{total.toLocaleString()}</span> trips</>
          )}
          {showHaltingOnly && <span className="ml-2 text-amber-700 font-bold">· Halting only</span>}
          {sortHalting && <span className="ml-2 text-zinc-700 font-bold">· Sorted by Halting ({sortHalting === "desc" ? "high→low" : "low→high"})</span>}
        </span>
        {pageHaltingSum > 0 && (
          <span className="text-zinc-500">
            Halting this page:
            <span className="ml-1 font-mono font-bold text-amber-700" data-testid="page-halting-sum">{fmtCurrency(pageHaltingSum)}</span>
          </span>
        )}
      </div>

      {/* Iter58 P1 — Sticky bulk action bar (appears only when rows are selected) */}
      {selected.size > 0 && (
        <div
          data-testid="bulk-action-bar"
          className="sticky top-2 z-30 bg-zinc-950 text-white border border-zinc-800 rounded-sm p-3 flex flex-wrap items-center gap-3 shadow-lg"
        >
          <span className="text-xs uppercase tracking-wider font-bold">
            <span data-testid="bulk-selected-count" className="font-mono text-base">{selected.size}</span> trip{selected.size === 1 ? "" : "s"} selected
            {selectedInvoicedCount > 0 && (
              <span className="ml-2 text-amber-300 text-[10px]" data-testid="bulk-invoiced-warning">
                ⚠ {selectedInvoicedCount} already invoiced
              </span>
            )}
          </span>
          <div className="flex-1" />
          <button
            type="button"
            data-testid="bulk-invoice-btn"
            onClick={runBulkInvoice}
            disabled={bulkInvoice.isPending || selectedInvoicedCount > 0}
            title={selectedInvoicedCount > 0 ? "Some selected trips are already invoiced" : "Create ONE invoice for all selected trips (must be same customer)"}
            className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold bg-emerald-600 text-white rounded-sm hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-1"
          >
            <FileText size={12} /> {bulkInvoice.isPending ? "Creating…" : `Bulk Invoice`}
          </button>
          <button
            type="button"
            data-testid="bulk-export-btn"
            onClick={async () => {
              try {
                const trip_ids = Array.from(selected).join(",");
                const res = await api.get(`/trips/export?format=csv&trip_ids=${encodeURIComponent(trip_ids)}`, { responseType: "blob" });
                const cd = res.headers?.["content-disposition"] || "";
                const m = /filename="([^"]+)"/.exec(cd);
                const url = URL.createObjectURL(res.data);
                const a = document.createElement("a"); a.href = url; a.download = m ? m[1] : "trips_selected.csv"; a.click();
                URL.revokeObjectURL(url);
                toast.success(`Exported ${selected.size} selected trip${selected.size === 1 ? "" : "s"}`);
              } catch (e) { toast.error(e?.response?.data?.detail || "Export failed"); }
            }}
            className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold bg-indigo-600 text-white rounded-sm hover:bg-indigo-700 inline-flex items-center gap-1"
          >
            <Download size={12} /> Export Selected
          </button>
          <button
            type="button"
            data-testid="bulk-delete-btn"
            onClick={runBulkDelete}
            disabled={bulkDelete.isPending}
            className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold bg-rose-600 text-white rounded-sm hover:bg-rose-700 inline-flex items-center gap-1 disabled:opacity-40"
          >
            <Trash2 size={12} /> {bulkDelete.isPending ? "Deleting…" : "Bulk Delete"}
          </button>
          <button
            type="button"
            data-testid="bulk-clear-selection"
            onClick={clearSelection}
            className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold border border-zinc-700 text-zinc-300 rounded-sm hover:bg-zinc-800"
          >
            <X size={12} /> Clear
          </button>
        </div>
      )}

      <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="trips-table">
            <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-[0.12em] sticky top-0 z-10">
              <tr>
                <th className="px-3 py-3 w-8">
                  <input
                    type="checkbox"
                    data-testid="bulk-select-all"
                    checked={allOnPageSelected}
                    onChange={toggleAllOnPage}
                    className="accent-emerald-500 cursor-pointer"
                    title={allOnPageSelected ? "Deselect all on this page" : "Select all on this page"}
                  />
                </th>
                <th className="text-left px-4 py-3 font-bold">Date · Time</th>
                <th className="text-left px-4 py-3 font-bold">LR Number</th>
                <th className="text-left px-4 py-3 font-bold" data-testid="trips-th-cust-ref">Cust Ref</th>
                <th className="text-left px-4 py-3 font-bold">Customer</th>
                <th className="text-left px-4 py-3 font-bold">Vehicle</th>
                <th className="text-left px-4 py-3 font-bold">Route · Load</th>
                <th className="text-right px-4 py-3 font-bold">Tons</th>
                <th className="text-right px-4 py-3 font-bold">Freight</th>
                <th
                  data-testid="halting-column-header"
                  onClick={cycleHaltingSort}
                  role="button"
                  className="text-right px-4 py-3 font-bold cursor-pointer select-none hover:bg-white/10"
                  title="Click to sort by Halting Amount (desc → asc → off)"
                >
                  Halting {sortHalting === "desc" ? "▼" : sortHalting === "asc" ? "▲" : "⇅"}
                </th>
                <th className="text-right px-4 py-3 font-bold">Expense</th>
                <th className="text-right px-4 py-3 font-bold">Profit</th>
                <th className="text-center px-4 py-3 font-bold">Status</th>
                <th className="px-4 py-3 font-bold text-center">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {displayedTrips.map((t, idx) => {
                const created = t.created_at ? new Date(t.created_at) : null;
                const timeStr = created ? created.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false }) : "";
                return (
                <tr
                  key={t.id}
                  data-testid={`trip-row-${t.id}`}
                  onClick={() => window.location.href = `/trips/${t.id}/view`}
                  className={`${idx % 2 === 0 ? "bg-white" : "bg-zinc-50/60"} ${selected.has(t.id) ? "!bg-emerald-50" : ""} hover:bg-amber-50/40 transition-colors cursor-pointer`}
                >
                  <td className="px-3 py-3 w-8" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      data-testid={`bulk-select-${t.id}`}
                      checked={selected.has(t.id)}
                      onChange={() => toggleOne(t.id)}
                      className="accent-emerald-500 cursor-pointer"
                    />
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="text-sm font-semibold text-zinc-900 font-mono">{fmtDate(t.date)}</div>
                    {timeStr && <div className="text-[10px] text-zinc-400 font-mono mt-0.5">🕒 {timeStr}</div>}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {t.lr_number ? (
                      <span className="inline-block font-mono text-[11px] font-bold px-2 py-1 bg-indigo-50 text-indigo-800 border border-indigo-200 rounded-sm">
                        {t.lr_number}
                      </span>
                    ) : (
                      <span className="text-zinc-300 text-xs">—</span>
                    )}
                  </td>
                  <td
                    className="px-4 py-3 whitespace-nowrap"
                    data-testid={`trip-cust-ref-${t.id}`}
                    onClick={(e) => { if (showMissingCustRef) e.stopPropagation(); }}
                  >
                    {/* Iter83 — Reuse existing per-trip customer_reference_number (never inherited).
                        Iter85 — In the Missing Cust Ref view, render an inline editor. */}
                    {showMissingCustRef ? (
                      <InlineCustRefEditor
                        trip={t}
                        onSaved={() => {
                          qc.invalidateQueries({ queryKey: ["trips"] });
                        }}
                      />
                    ) : (t.customer_reference_number || t.customer_invoice_no || t.waybill_no) ? (
                      <span className="inline-block font-mono text-[11px] font-bold px-2 py-1 bg-amber-50 text-amber-800 border border-amber-200 rounded-sm">
                        {t.customer_reference_number || t.customer_invoice_no || t.waybill_no}
                      </span>
                    ) : (
                      <span className="text-zinc-300 text-xs">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 max-w-[220px]">
                    <div className="font-bold text-zinc-900 truncate leading-tight" title={custMap[t.customer_id] || ""}>
                      {custMap[t.customer_id] || "—"}
                    </div>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span className="inline-block font-mono text-[11px] font-bold px-2 py-1 bg-zinc-950 text-white rounded-sm tracking-wider">
                      {t.vehicle_number}
                    </span>
                    {t.vehicle_type === "supplier" && (
                      <div className="text-[9px] uppercase tracking-wider text-orange-600 font-bold mt-1">Supplier</div>
                    )}
                  </td>
                  <td className="px-4 py-3 max-w-[220px]">
                    <div className="text-xs text-zinc-800 font-medium truncate leading-tight" title={`${t.from_location || "?"} → ${t.to_location || "?"}`}>
                      {t.from_location || "—"} <span className="text-zinc-400">→</span> {t.to_location || "—"}
                    </div>
                    {t.load_details && (
                      <div className="text-[10px] text-zinc-500 truncate mt-0.5" title={t.load_details}>📦 {t.load_details}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <div className="font-mono font-semibold text-sm">{Number(t.tons).toFixed(2)}</div>
                    <div className="text-[9px] uppercase text-zinc-400 tracking-wider">
                      {t.freight_mode === "per_ton" ? `₹${Number(t.rate_per_ton).toFixed(0)}/T` : "Fixed"}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap font-mono text-sm font-semibold text-zinc-900">
                    {fmtCurrency(t.freight_amount)}
                  </td>
                  <td
                    className={`px-4 py-3 text-right whitespace-nowrap font-mono text-sm ${t.halting_amount > 0 ? "text-amber-700 font-bold" : "text-zinc-300"}`}
                    title={t.halting_amount > 0 ? `${t.chargeable_halting_days || 0} chargeable day(s) × ₹${t.halting_rate_per_day || 0}/day` : "No halting charges"}
                    data-testid={`trip-halting-${t.id}`}
                  >
                    {t.halting_amount > 0 ? (
                      <div className="flex flex-col items-end gap-0.5">
                        <span>{fmtCurrency(t.halting_amount)}</span>
                        <HaltingAgeChip trip={t} />
                      </div>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap font-mono text-sm text-rose-700">
                    {fmtCurrency(t.total_expense)}
                  </td>
                  <td className={`px-4 py-3 text-right whitespace-nowrap font-mono text-sm font-bold ${t.profit >= 0 ? "text-emerald-700" : "text-rose-700"}`}>
                    {fmtCurrency(t.profit)}
                  </td>
                  <td className="px-4 py-3 text-center whitespace-nowrap">
                    {t.status === "invoiced" ? (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider bg-emerald-100 text-emerald-800 px-2.5 py-1 rounded-full border border-emerald-300 font-bold">
                        <CheckCircle2 size={10} /> Invoiced
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider bg-amber-100 text-amber-800 px-2.5 py-1 rounded-full border border-amber-300 font-bold">
                        <Clock size={10} /> Pending
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-3 whitespace-nowrap w-[220px]" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-0.5">
                      <Link data-testid={`view-trip-${t.id}`} to={`/trips/${t.id}/view`} className="p-1.5 border border-zinc-200 rounded-sm text-zinc-600 hover:bg-zinc-950 hover:text-white transition" title="View details"><Eye size={12} /></Link>
                      <Link data-testid={`edit-trip-${t.id}`} to={`/trips/${t.id}/edit`} className={`p-1.5 border rounded-sm hover:bg-zinc-950 hover:text-white transition ${t.status === "invoiced" ? "border-amber-300 text-amber-700" : "border-zinc-200 text-zinc-600"}`} title={t.status === "invoiced" ? "Edit (invoice will recalc)" : "Edit"}><Pencil size={12} /></Link>
                      <a data-testid={`lr-${t.id}`} href={`${API}/trips/${t.id}/lr`} target="_blank" rel="noreferrer" className="p-1.5 border border-indigo-200 rounded-sm text-indigo-700 hover:bg-indigo-600 hover:text-white transition" title="LR PDF"><FileText size={12} /></a>
                      <button data-testid={`share-lr-${t.id}`}
                        onClick={async () => {
                          try {
                            const { data } = await api.post(`/trips/${t.id}/share-lr`);
                            window.open(data.whatsapp_url, "_blank");
                            toast.success(`LR ${data.lr_number} ready to share`);
                          } catch (e) { toast.error(e.response?.data?.detail || "Share failed"); }
                        }}
                        className="p-1.5 border border-emerald-300 rounded-sm text-emerald-700 hover:bg-emerald-600 hover:text-white transition"
                        title="Share LR via WhatsApp"
                      ><Share2 size={12} /></button>
                      <button data-testid={`ewaybill-${t.id}`} onClick={() => downloadEwayBill(t.id)} className="p-1.5 border border-zinc-200 rounded-sm text-zinc-600 hover:bg-zinc-950 hover:text-white transition" title="E-Way Bill JSON"><Download size={12} /></button>
                      <button data-testid={`duplicate-trip-${t.id}`}
                        onClick={async () => {
                          try {
                            const { data } = await api.post(`/trips/${t.id}/duplicate`);
                            toast.success("Trip duplicated");
                            qc.invalidateQueries({ queryKey: ["trips"] });
                            window.location.href = `/trips/${data.id}/edit`;
                          } catch (e) { toast.error(e.response?.data?.detail || "Duplicate failed"); }
                        }}
                        className="p-1.5 border border-emerald-200 rounded-sm text-emerald-700 hover:bg-emerald-50 transition"
                        title="Duplicate"
                      ><Copy size={12} /></button>
                      <button data-testid={`delete-trip-${t.id}`} onClick={() => askDelete(t)} className="p-1.5 border border-rose-200 rounded-sm text-rose-700 hover:bg-rose-600 hover:text-white transition" title="Delete"><Trash2 size={12} /></button>
                    </div>
                  </td>
                </tr>
                );
              })}
              {!isLoading && total === 0 && (
                <tr>
                  <td colSpan={14} className="px-4 py-16 text-center text-zinc-400" data-testid="trips-empty-state">
                    {activeFilterCount > 0 ? (
                      <>
                        No trips match your filters.
                        <button onClick={clearFilters} className="ml-2 underline font-bold text-zinc-700 hover:text-zinc-950" data-testid="empty-clear-btn">Clear filters</button>
                      </>
                    ) : (
                      <>No trips logged. Click "New Trip" to start.</>
                    )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination controls */}
        {total > PAGE_SIZE && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-zinc-200 bg-zinc-50 text-xs" data-testid="trips-pagination">
            <div className="text-zinc-600">
              Page <span className="font-bold" data-testid="pagination-current">{page + 1}</span> of <span className="font-bold">{Math.ceil(total / PAGE_SIZE)}</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                data-testid="pagination-prev"
                disabled={page === 0 || tripsQ.isFetching}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="px-3 py-1.5 text-[11px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm inline-flex items-center gap-1 hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <ChevronLeft size={12} /> Prev
              </button>
              <button
                data-testid="pagination-next"
                disabled={!hasMore || tripsQ.isFetching}
                onClick={() => setPage((p) => p + 1)}
                className="px-3 py-1.5 text-[11px] uppercase tracking-wider font-bold border border-zinc-300 rounded-sm inline-flex items-center gap-1 hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Next <ChevronRight size={12} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


// Iter52 — Halting Aging chip (unchanged; retained from prior iteration).
function HaltingAgeChip({ trip }) {
  const ageDays = React.useMemo(() => {
    const anchor = trip.unloading_date || trip.date;
    if (!anchor) return null;
    const then = new Date(anchor);
    if (isNaN(then.getTime())) return null;
    const now = new Date();
    return Math.floor((now - then) / (1000 * 60 * 60 * 24));
  }, [trip.unloading_date, trip.date]);
  if (ageDays == null || ageDays < 0) return null;
  const tone = ageDays >= 30 ? "bg-rose-100 text-rose-700 border-rose-300"
    : ageDays >= 7 ? "bg-amber-100 text-amber-700 border-amber-300"
    : "bg-zinc-100 text-zinc-600 border-zinc-300";
  return (
    <span
      data-testid={`trip-halting-age-${trip.id}`}
      title={`Halting pending for ${ageDays} day(s) since ${trip.unloading_date || trip.date}`}
      className={`inline-block text-[9px] font-mono font-bold px-1.5 py-0.5 rounded border ${tone}`}
    >
      {ageDays}d
    </span>
  );
}



// Iter57 P1 — Export Filtered Trips (CSV / XLSX)
function ExportMenu({ filters, showHaltingOnly, showMissingCustRef, total }) {
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const rootRef = React.useRef(null);
  React.useEffect(() => {
    const onDoc = (e) => { if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  const doExport = async (fmt) => {
    if (busy) return;
    setBusy(true);
    setOpen(false);
    try {
      const params = new URLSearchParams({ format: fmt });
      if (filters.customer_id) params.set("customer_id", filters.customer_id);
      if (filters.vehicle_id) params.set("vehicle_id", filters.vehicle_id);
      if (filters.supplier_id) params.set("supplier_id", filters.supplier_id);
      if (filters.date_from) params.set("date_from", filters.date_from);
      if (filters.date_to) params.set("date_to", filters.date_to);
      if (filters.q?.trim()) params.set("q", filters.q.trim());
      if (showHaltingOnly) params.set("halting_only", "true");
      if (showMissingCustRef) params.set("missing_cust_ref", "true");
      const res = await api.get(`/trips/export?${params.toString()}`, { responseType: "blob" });
      const cd = res.headers?.["content-disposition"] || "";
      const m = /filename="([^"]+)"/.exec(cd);
      const filename = m ? m[1] : `trips_export.${fmt}`;
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`Exported ${total.toLocaleString()} trip${total === 1 ? "" : "s"} → ${filename}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Export failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        data-testid="trips-export-btn"
        onClick={() => setOpen((v) => !v)}
        disabled={busy || total === 0}
        className="w-full px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold border rounded-sm inline-flex items-center justify-center gap-1 disabled:opacity-40 disabled:cursor-not-allowed bg-emerald-50 text-emerald-800 border-emerald-300 hover:bg-emerald-100"
      >
        <Download size={12} /> {busy ? "…" : "Export"}
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-20 bg-white border border-zinc-200 rounded-sm shadow-lg min-w-[160px]" data-testid="trips-export-menu">
          <button
            type="button"
            data-testid="trips-export-csv"
            onClick={() => doExport("csv")}
            className="w-full text-left px-3 py-2 text-xs hover:bg-zinc-100 border-b border-zinc-100"
          >
            <span className="font-bold">CSV</span>
            <span className="text-zinc-500 ml-2 text-[10px]">Excel-compatible</span>
          </button>
          <button
            type="button"
            data-testid="trips-export-xlsx"
            onClick={() => doExport("xlsx")}
            className="w-full text-left px-3 py-2 text-xs hover:bg-zinc-100"
          >
            <span className="font-bold">XLSX</span>
            <span className="text-zinc-500 ml-2 text-[10px]">Native Excel</span>
          </button>
        </div>
      )}
    </div>
  );
}

/* ================= Iter85 — Inline Customer Ref editor ================= */
function InlineCustRefEditor({ trip, onSaved }) {
  const initial = trip.customer_reference_number || trip.customer_invoice_no || trip.waybill_no || "";
  const [value, setValue] = React.useState(initial);
  const [saving, setSaving] = React.useState(false);
  const [savedFlash, setSavedFlash] = React.useState(false);
  const inputRef = React.useRef(null);

  React.useEffect(() => { setValue(initial); }, [initial]);

  const commit = async () => {
    const next = value.trim();
    if (next === initial.trim()) return;                 // no-op
    setSaving(true);
    try {
      await api.patch(`/trips/${trip.id}/customer-ref`, { customer_reference_number: next });
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 1200);
      onSaved?.();
      if (next) toast.success(`Cust Ref saved for ${trip.vehicle_number}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to save Cust Ref");
      setValue(initial);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="relative">
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); inputRef.current?.blur(); }
          if (e.key === "Escape") { setValue(initial); inputRef.current?.blur(); }
        }}
        placeholder="Type Cust Ref…"
        data-testid={`trip-cust-ref-input-${trip.id}`}
        disabled={saving}
        className={`w-32 font-mono text-[11px] font-bold px-2 py-1 rounded-sm border outline-none focus:ring-2 focus:ring-emerald-400 focus:border-emerald-500 disabled:opacity-60
          ${savedFlash ? "bg-emerald-50 border-emerald-400 text-emerald-800" : "bg-white border-rose-300 text-rose-900 placeholder-rose-300"}`}
      />
      {saving && (
        <span className="absolute right-1 top-1/2 -translate-y-1/2 text-[9px] text-zinc-400">…</span>
      )}
    </div>
  );
}

