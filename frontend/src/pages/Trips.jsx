import React from "react";
import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { api, API, fmtCurrency, fmtDate } from "@/api";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Plus, CheckCircle2, Clock, Download, FileText, Trash2, Eye, Pencil, Copy, Share2, Search, X, ChevronLeft, ChevronRight } from "lucide-react";
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
    return n;
  }, [filters, showHaltingOnly]);

  // Lookup master data for the searchable selects (small, cache-friendly).
  const { data: customers = [] } = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get("/customers")).data });
  const { data: vehicles = [] } = useQuery({ queryKey: ["vehicles"], queryFn: async () => (await api.get("/vehicles")).data });
  const { data: suppliers = [] } = useQuery({ queryKey: ["suppliers"], queryFn: async () => (await api.get("/suppliers")).data });
  const custMap = React.useMemo(() => Object.fromEntries(customers.map((c) => [c.id, c.name])), [customers]);

  // Server-side trips query — key includes every filter + page so results are cached per combo.
  const tripsQ = useQuery({
    queryKey: ["trips", "search", filters, showHaltingOnly, page],
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
            <button
              type="button"
              data-testid="trips-clear-filters"
              onClick={clearFilters}
              disabled={activeFilterCount === 0}
              className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold border rounded-sm inline-flex items-center justify-center gap-1 disabled:opacity-40 disabled:cursor-not-allowed
                bg-rose-50 text-rose-800 border-rose-300 hover:bg-rose-100"
            >
              <X size={12} /> Clear Filters {activeFilterCount > 0 && <span className="font-mono">({activeFilterCount})</span>}
            </button>
          </div>
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

      <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="trips-table">
            <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-[0.12em] sticky top-0 z-10">
              <tr>
                <th className="text-left px-4 py-3 font-bold">Date · Time</th>
                <th className="text-left px-4 py-3 font-bold">LR Number</th>
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
                  className={`${idx % 2 === 0 ? "bg-white" : "bg-zinc-50/60"} hover:bg-amber-50/40 transition-colors cursor-pointer`}
                >
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
                  <td colSpan={12} className="px-4 py-16 text-center text-zinc-400" data-testid="trips-empty-state">
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
