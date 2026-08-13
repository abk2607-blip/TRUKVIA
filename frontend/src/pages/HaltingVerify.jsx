// Iter65 · Priority 1 — Halting Live Verification Checklist page.
// Purpose: show operators every Trip with halting activity + a per-stage
// audit so we can verify the same Halting Days and Halting Charges flow
// consistently Trip Entry → Auto Calc → Trip View → Invoice → Supplier
// Settlement.  Backend recomputes with the same formula so a MISMATCH
// row exposes a real data-integrity issue.
import React from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency } from "@/api";
import { CheckCircle2, AlertTriangle, ExternalLink, ArrowLeft, Info } from "lucide-react";

const ic = "border border-zinc-300 px-3 py-1.5 rounded-sm text-xs focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";

export default function HaltingVerify() {
  const [dateFrom, setDateFrom] = React.useState("");
  const [dateTo, setDateTo] = React.useState("");
  const [onlyMismatches, setOnlyMismatches] = React.useState(false);
  const [expandTrip, setExpandTrip] = React.useState(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["halting-verify", dateFrom, dateTo, onlyMismatches],
    queryFn: async () => (await api.get("/reports/halting-verify", {
      params: { date_from: dateFrom, date_to: dateTo, only_mismatches: onlyMismatches, limit: 500 },
    })).data,
  });

  const rows = data?.rows || [];
  // Iter65 fix — derive okCount from server-authoritative totals so the tile
  // stays truthful even when only_mismatches=true strips OK rows from the response.
  const mismatchCount = data?.mismatch_count || 0;
  const okCount = data ? Math.max(0, (data.total || 0) - mismatchCount) : 0;

  return (
    <div className="space-y-6" data-testid="halting-verify-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <Link to="/reports" className="text-xs text-zinc-500 hover:text-zinc-950 inline-flex items-center gap-1 mb-2">
            <ArrowLeft size={12} /> Back to Reports
          </Link>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Live Audit</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">Halting Verification Checklist</h1>
          <div className="text-xs text-zinc-500 mt-1 max-w-2xl">
            One-page audit — verifies the same Halting Days and Halting Charges are consistent across
            <span className="font-semibold"> Trip Entry → Auto Calc → Trip View → Invoice → Supplier Settlement</span>.
            The server recomputes each stage using the exact same formula stored in <code>services.compute_totals</code>
            so a MISMATCH row exposes a real data-integrity issue — not a display bug.
          </div>
        </div>
      </header>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3 border border-zinc-200 bg-white rounded-sm p-3">
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 block">Date From</label>
          <input data-testid="halting-verify-date-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className={ic} />
        </div>
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 block">Date To</label>
          <input data-testid="halting-verify-date-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className={ic} />
        </div>
        <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
          <input data-testid="halting-verify-only-mismatches" type="checkbox" checked={onlyMismatches} onChange={(e) => setOnlyMismatches(e.target.checked)} className="h-4 w-4 accent-rose-600" />
          <span className={onlyMismatches ? "text-rose-800 font-semibold" : "text-zinc-600"}>Only Mismatches</span>
        </label>
        <button onClick={() => refetch()} data-testid="halting-verify-refresh" className="px-3 py-1.5 text-xs uppercase tracking-wider border border-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white">Refresh</button>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-4 gap-3">
        <div className="border border-zinc-200 bg-white rounded-sm px-4 py-3" data-testid="stat-total">
          <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500">Trips with Halting</div>
          <div className="mt-1 text-2xl font-black tabular-nums">{data?.total ?? "…"}</div>
        </div>
        <div className="border border-emerald-200 bg-emerald-50 rounded-sm px-4 py-3" data-testid="stat-ok">
          <div className="text-[10px] uppercase tracking-wider font-bold text-emerald-700">Consistent (OK)</div>
          <div className="mt-1 text-2xl font-black tabular-nums text-emerald-800">{okCount}</div>
        </div>
        <div className={`border rounded-sm px-4 py-3 ${mismatchCount > 0 ? "border-rose-300 bg-rose-50" : "border-zinc-200 bg-white"}`} data-testid="stat-mismatch">
          <div className={`text-[10px] uppercase tracking-wider font-bold ${mismatchCount > 0 ? "text-rose-800" : "text-zinc-500"}`}>Mismatches</div>
          <div className={`mt-1 text-2xl font-black tabular-nums ${mismatchCount > 0 ? "text-rose-800" : "text-zinc-800"}`}>{mismatchCount}</div>
        </div>
        <div className="border border-zinc-200 bg-white rounded-sm px-4 py-3">
          <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500">Overall Health</div>
          <div className="mt-1 text-lg font-bold">
            {mismatchCount === 0 && (data?.total ?? 0) > 0 ? (
              <span className="text-emerald-700 inline-flex items-center gap-1" data-testid="halting-verify-verdict"><CheckCircle2 size={16} /> ALL GREEN — safe to enable SMS Digest</span>
            ) : mismatchCount > 0 ? (
              <span className="text-rose-700 inline-flex items-center gap-1" data-testid="halting-verify-verdict"><AlertTriangle size={16} /> FIX MISMATCHES FIRST</span>
            ) : (
              <span className="text-zinc-500" data-testid="halting-verify-verdict">No halting trips yet.</span>
            )}
          </div>
        </div>
      </div>

      {/* Formula reference card */}
      <div className="border border-indigo-200 bg-indigo-50 rounded-sm p-3 text-xs text-indigo-900 flex gap-3">
        <Info size={16} className="shrink-0 mt-0.5" />
        <div className="space-y-1">
          <div><b>Total Halting Days</b> = (Unloading Date − Loading Date) if both dates present, else the manually-typed value.</div>
          <div><b>Chargeable Days</b> = max(Total − Grace Days, 0). Default grace is 4 days per your policy.</div>
          <div><b>Halting Amount</b> = Chargeable × Rate (unless the user manually overrode the amount — override flag preserved on the trip).</div>
          <div><b>Invoice</b> line copies <code>halting_amount</code> straight from the Trip.</div>
          <div><b>Supplier Settlement</b> does NOT include halting — halting is customer-side revenue only.</div>
        </div>
      </div>

      {/* Table */}
      <div className="border border-zinc-200 bg-white rounded-sm overflow-x-auto">
        <table className="w-full text-sm" data-testid="halting-verify-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-3 py-2 font-semibold">Status</th>
              <th className="text-left px-3 py-2 font-semibold">Trip</th>
              <th className="text-left px-3 py-2 font-semibold">Vehicle</th>
              <th className="text-left px-3 py-2 font-semibold">Customer</th>
              <th className="text-right px-3 py-2 font-semibold">Total Days</th>
              <th className="text-right px-3 py-2 font-semibold">Grace</th>
              <th className="text-right px-3 py-2 font-semibold">Chargeable</th>
              <th className="text-right px-3 py-2 font-semibold">Rate</th>
              <th className="text-right px-3 py-2 font-semibold">Amount</th>
              <th className="text-left px-3 py-2 font-semibold">Invoice</th>
              <th className="text-center px-3 py-2 font-semibold">Type</th>
              <th className="text-center px-3 py-2 font-semibold"></th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={12} className="text-center py-12 text-zinc-400">Loading…</td></tr>
            )}
            {!isLoading && rows.length === 0 && (
              <tr><td colSpan={12} className="text-center py-12 text-zinc-400" data-testid="halting-verify-empty">
                {onlyMismatches ? "No mismatches found in this window — halting flow is consistent." : "No halting trips in this window."}
              </td></tr>
            )}
            {rows.map((r) => (
              <React.Fragment key={r.trip_id}>
                <tr className={`border-b border-zinc-100 ${r.status === "MISMATCH" ? "bg-rose-50" : ""}`} data-testid={`hv-row-${r.trip_id}`}>
                  <td className="px-3 py-2">
                    {r.status === "OK" ? (
                      <span className="inline-flex items-center gap-1 text-emerald-700 text-[10px] uppercase tracking-wider font-bold">
                        <CheckCircle2 size={12} /> OK
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-rose-800 text-[10px] uppercase tracking-wider font-bold" data-testid={`hv-mismatch-${r.trip_id}`}>
                        <AlertTriangle size={12} /> MISMATCH
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">
                    <div>{r.trip_number || "—"}</div>
                    <div className="text-[10px] text-zinc-500">{r.date}</div>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{r.vehicle_number || "—"}</td>
                  <td className="px-3 py-2 text-xs text-zinc-700 max-w-[200px] truncate">{r.customer_name || "—"}</td>
                  <td className="px-3 py-2 text-right font-mono">{r.halting_calc.total_halting_days_stored}</td>
                  <td className="px-3 py-2 text-right font-mono text-zinc-500">{r.trip_entry.grace_days}</td>
                  <td className="px-3 py-2 text-right font-mono">{r.halting_calc.chargeable_halting_days_stored}</td>
                  <td className="px-3 py-2 text-right font-mono">{fmtCurrency(r.trip_entry.halting_rate_per_day)}</td>
                  <td className="px-3 py-2 text-right font-mono font-bold">
                    {fmtCurrency(r.halting_calc.halting_amount_stored)}
                    {r.trip_entry.halting_amount_override && <div className="text-[9px] text-amber-700 font-semibold">OVERRIDE</div>}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {r.invoice_stage ? (
                      <Link to={`/invoices/${r.invoice_stage.invoice_id}/view`} className="text-indigo-700 hover:text-indigo-950 inline-flex items-center gap-1">
                        {r.invoice_stage.invoice_number} <ExternalLink size={10} />
                      </Link>
                    ) : (
                      <span className="text-zinc-400 text-[10px] uppercase tracking-wider">Pending</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span className={`inline-block px-2 py-0.5 rounded-full border text-[10px] uppercase tracking-wider font-bold ${
                      r.vehicle_type === "supplier" ? "bg-amber-50 text-amber-800 border-amber-200" : "bg-sky-50 text-sky-800 border-sky-200"
                    }`}>{r.vehicle_type}</span>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <button
                      data-testid={`hv-expand-${r.trip_id}`}
                      onClick={() => setExpandTrip(expandTrip === r.trip_id ? null : r.trip_id)}
                      className="text-xs px-2 py-1 border border-zinc-300 rounded-sm hover:bg-zinc-50"
                    >{expandTrip === r.trip_id ? "Hide" : "Details"}</button>
                  </td>
                </tr>
                {expandTrip === r.trip_id && (
                  <tr className="bg-zinc-50" data-testid={`hv-expanded-${r.trip_id}`}>
                    <td colSpan={12} className="px-6 py-4">
                      <div className="grid grid-cols-4 gap-4 text-xs">
                        <Stage title="1 · Trip Entry (as saved)">
                          <KV k="Loading Date" v={r.trip_entry.loading_date || "—"} />
                          <KV k="Unloading Date" v={r.trip_entry.unloading_date || "—"} />
                          <KV k="Dates Present" v={r.trip_entry.dates_present ? "Yes" : "No"} />
                          <KV k="Grace Days" v={r.trip_entry.grace_days} />
                          <KV k="Rate/Day" v={fmtCurrency(r.trip_entry.halting_rate_per_day)} />
                          <KV k="Manual Override" v={r.trip_entry.halting_amount_override ? "Yes" : "No"} />
                        </Stage>
                        <Stage title="2 · Auto Calc (server recomputed)">
                          <KV k="Total Days" v={`stored ${r.halting_calc.total_halting_days_stored} · expected ${r.halting_calc.total_halting_days_expected}`} />
                          <KV k="Chargeable" v={`stored ${r.halting_calc.chargeable_halting_days_stored} · expected ${r.halting_calc.chargeable_halting_days_expected}`} />
                          <KV k="Amount" v={`stored ${fmtCurrency(r.halting_calc.halting_amount_stored)} · expected ${fmtCurrency(r.halting_calc.halting_amount_expected)}`} />
                        </Stage>
                        <Stage title="3 · Invoice Mirror">
                          {r.invoice_stage ? (
                            <>
                              <KV k="Invoice #" v={r.invoice_stage.invoice_number} />
                              <KV k="Status" v={r.invoice_stage.invoice_status} />
                              <KV k="Line Halting" v={fmtCurrency(r.invoice_stage.invoice_line_halting)} />
                              <KV k="Invoice Halting Total" v={fmtCurrency(r.invoice_stage.invoice_total_halting)} />
                            </>
                          ) : (
                            <div className="text-zinc-400 italic">Trip not yet invoiced.</div>
                          )}
                        </Stage>
                        <Stage title="4 · Supplier Settlement">
                          {r.supplier_stage ? (
                            <>
                              <KV k="Supplier" v={r.supplier_stage.supplier_name || "—"} />
                              <KV k="Supplier Freight" v={fmtCurrency(r.supplier_stage.supplier_freight)} />
                              <div className="text-[10px] text-zinc-500 mt-1 italic">{r.supplier_stage.note}</div>
                            </>
                          ) : (
                            <div className="text-zinc-400 italic">Own vehicle — no supplier settlement.</div>
                          )}
                        </Stage>
                      </div>
                      {r.flags?.length > 0 && (
                        <div className="mt-3 border border-rose-300 bg-rose-100 text-rose-900 rounded-sm p-3 text-xs" data-testid={`hv-flags-${r.trip_id}`}>
                          <div className="font-bold mb-1 flex items-center gap-1"><AlertTriangle size={12} /> Data Integrity Flags</div>
                          <ul className="list-disc pl-5 space-y-0.5">
                            {r.flags.map((f, i) => <li key={i}>{f}</li>)}
                          </ul>
                        </div>
                      )}
                      <div className="mt-3 flex items-center gap-2">
                        <Link to={`/trips/${r.trip_id}/view`} className="text-xs px-3 py-1 border border-zinc-300 rounded-sm hover:bg-white inline-flex items-center gap-1" data-testid={`hv-view-${r.trip_id}`}>Open Trip View <ExternalLink size={10} /></Link>
                        <Link to={`/trips/${r.trip_id}/edit`} className="text-xs px-3 py-1 border border-indigo-200 text-indigo-800 rounded-sm hover:bg-indigo-50 inline-flex items-center gap-1" data-testid={`hv-edit-${r.trip_id}`}>Edit Trip <ExternalLink size={10} /></Link>
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stage({ title, children }) {
  return (
    <div className="border border-zinc-200 bg-white rounded-sm p-3">
      <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-2">{title}</div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function KV({ k, v }) {
  return (
    <div className="flex justify-between gap-2 text-xs">
      <span className="text-zinc-500 uppercase tracking-wider text-[10px]">{k}</span>
      <span className="font-mono font-semibold text-right">{String(v)}</span>
    </div>
  );
}
