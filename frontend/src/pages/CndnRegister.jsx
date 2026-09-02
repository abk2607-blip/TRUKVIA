// Iter132c C4 · Credit Note / Debit Note Register
// Pure projection of the LOCKED C4 canonical JSON (GET /api/reports/cndn-register).
// XLSX/PDF are pass-through downloads. Zero client calculation.
import React, { useMemo, useState } from "react";
import { Navigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, fmtCurrency } from "@/api";
import { Download, AlertTriangle, Info, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { useCdnEnabledState } from "@/hooks/useCdnEnabled";

const ic = "w-full text-sm border border-zinc-300 rounded-sm px-3 py-2 bg-white";

function FieldWrap({ label, children }) {
  return (
    <label className="block">
      <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-1">{label}</div>
      {children}
    </label>
  );
}

function Kpi({ testid, label, value, sub, tone }) {
  const bg = tone === "credit" ? "bg-red-50 border-red-200"
           : tone === "debit"  ? "bg-blue-50 border-blue-200"
           : tone === "net"    ? "bg-emerald-50 border-emerald-200"
           :                     "border-zinc-200 bg-white";
  return (
    <div data-testid={testid} className={`border rounded-sm p-3 ${bg}`}>
      <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">{label}</div>
      <div className="mt-1 text-lg font-black tracking-tight tabular-nums font-mono">{value}</div>
      {sub != null && <div className="text-[11px] text-zinc-500 font-mono">{sub}</div>}
    </div>
  );
}

function _firstOfMonthISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}
function _todayISO() { return new Date().toISOString().slice(0, 10); }

export default function CndnRegisterReport() {
  const { enabled: cdnEnabled, settled: cdnSettled } = useCdnEnabledState();
  const [from, setFrom] = useState(_firstOfMonthISO());
  const [to, setTo] = useState(_todayISO());
  const [kind, setKind] = useState("all");
  const [status, setStatus] = useState("issued");
  const [customerId, setCustomerId] = useState("");
  const [reasonCode, setReasonCode] = useState("");
  const [showJson, setShowJson] = useState(false);

  const { data: customers = [] } = useQuery({
    queryKey: ["cndn-register-customers"],
    queryFn: async () => {
      const r = await api.get("/customers", { params: { limit: 5000 } });
      // Endpoint returns {items, total, ...} — flatten to a list here.
      return Array.isArray(r.data) ? r.data : (r.data?.items || []);
    },
    enabled: cdnEnabled,
    staleTime: 300_000,
  });

  const params = useMemo(() => {
    const p = { from, to, kind, status };
    if (customerId) p.customer_id = customerId;
    if (reasonCode) p.reason_code = reasonCode;
    return p;
  }, [from, to, kind, status, customerId, reasonCode]);

  const { data, refetch, isFetching, isError, error } = useQuery({
    queryKey: ["cndn-register", params],
    queryFn: async () => (await api.get("/reports/cndn-register", { params })).data,
    enabled: cdnEnabled && Boolean(from) && Boolean(to),
    staleTime: 30_000,
    retry: false,
  });

  // Only redirect once the flag probe has settled — otherwise a direct-URL
  // hit races the query and always redirects on first render (q.data is
  // undefined before resolution).
  if (cdnSettled && !cdnEnabled) return <Navigate to="/reports/ledger" replace />;

  const doDownload = async (kindFmt) => {
    const t = toast.loading(`Preparing ${kindFmt.toUpperCase()}…`);
    try {
      const resp = await api.get(`/reports/cndn-register.${kindFmt}`, {
        params, responseType: "blob",
      });
      const cd = resp.headers?.["content-disposition"] || "";
      const m = cd.match(/filename="?([^"]+)"?/);
      const fname = m ? m[1] : `cndn_register_${from}_${to}.${kindFmt}`;
      const url = URL.createObjectURL(resp.data);
      const a = document.createElement("a");
      a.href = url; a.download = fname; a.click();
      URL.revokeObjectURL(url);
      toast.success(`${kindFmt.toUpperCase()} downloaded`, { id: t });
    } catch (e) {
      toast.error(`${kindFmt.toUpperCase()} download failed`, { id: t });
    }
  };
  const doJsonDownload = () => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `cndn_register_${from}_${to}.json`; a.click();
    URL.revokeObjectURL(url);
  };

  const kpis = data?.kpis || {};
  const tax = data?.tax_summary || {};
  const recon = data?.reconciliation || {};
  const reconciled = recon?.reconciled === true;
  const rows = data?.rows || [];
  const byReason = data?.by_reason || [];
  const warnings = data?.warnings || [];
  const dlDisabled = isFetching || !data;
  const isEmpty = data && (data.note_count || 0) === 0;

  return (
    <div className="space-y-4" data-testid="cndn-register-tab">
      {/* Filter bar */}
      <div className="border border-zinc-200 bg-white rounded-sm p-4 grid grid-cols-1 md:grid-cols-6 gap-3">
        <FieldWrap label="From">
          <input data-testid="cndn-from" type="date" value={from}
            onChange={(e) => setFrom(e.target.value)} className={ic} />
        </FieldWrap>
        <FieldWrap label="To">
          <input data-testid="cndn-to" type="date" value={to}
            onChange={(e) => setTo(e.target.value)} className={ic} />
        </FieldWrap>
        <FieldWrap label="Kind">
          <select data-testid="cndn-kind" value={kind}
            onChange={(e) => setKind(e.target.value)} className={ic}>
            <option value="all">All</option>
            <option value="credit">Credit only</option>
            <option value="debit">Debit only</option>
          </select>
        </FieldWrap>
        <FieldWrap label="Status">
          <select data-testid="cndn-status" value={status}
            onChange={(e) => setStatus(e.target.value)} className={ic}>
            <option value="issued">Issued</option>
            <option value="draft">Draft</option>
            <option value="cancelled">Cancelled</option>
            <option value="all">All</option>
          </select>
        </FieldWrap>
        <FieldWrap label="Customer">
          <select data-testid="cndn-customer" value={customerId}
            onChange={(e) => setCustomerId(e.target.value)} className={ic}>
            <option value="">All customers</option>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </FieldWrap>
        <FieldWrap label="Reason">
          <select data-testid="cndn-reason" value={reasonCode}
            onChange={(e) => setReasonCode(e.target.value)} className={ic}>
            <option value="">All reasons</option>
            <option value="sales_return">sales_return</option>
            <option value="post_invoice_discount">post_invoice_discount</option>
            <option value="short_delivery">short_delivery</option>
            <option value="quality_claim">quality_claim</option>
            <option value="rate_correction">rate_correction</option>
            <option value="under_charge">under_charge</option>
            <option value="missed_halting">missed_halting</option>
            <option value="freight_escalation">freight_escalation</option>
            <option value="other">other</option>
          </select>
        </FieldWrap>
      </div>

      {/* Action row (4-button pattern + View JSON) */}
      <div className="flex flex-wrap items-center gap-2 justify-end">
        <button data-testid="cndn-view-btn" onClick={() => refetch()} disabled={isFetching}
          className="px-3 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
          {isFetching ? "Loading…" : "View Register"}
        </button>
        <button data-testid="cndn-json-btn" onClick={doJsonDownload} disabled={dlDisabled}
          title="Download canonical JSON (technical)"
          className="px-3 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-100 disabled:opacity-40 inline-flex items-center gap-2">
          <Download size={14} /> Download JSON
        </button>
        <button data-testid="cndn-xlsx-btn" onClick={() => doDownload("xlsx")} disabled={dlDisabled}
          title="Download 4-sheet accountant workbook"
          className="px-3 py-2 text-xs uppercase tracking-wider bg-emerald-700 text-white rounded-sm hover:bg-emerald-800 disabled:opacity-40 inline-flex items-center gap-2">
          <Download size={14} /> Download XLSX
        </button>
        <button data-testid="cndn-pdf-btn" onClick={() => doDownload("pdf")} disabled={dlDisabled}
          title="Download human-readable working PDF"
          className="px-3 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-40 inline-flex items-center gap-2">
          <Download size={14} /> Download PDF
        </button>
        <button data-testid="cndn-view-json-toggle" onClick={() => setShowJson((v) => !v)} disabled={!data}
          title="Toggle technical JSON view"
          className="px-3 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-100 disabled:opacity-40 inline-flex items-center gap-1">
          View JSON <ChevronDown size={12} />
        </button>
      </div>

      {/* Loading */}
      {isFetching && !data && (
        <div data-testid="cndn-loading" className="border border-zinc-200 bg-white rounded-sm p-6 text-sm text-zinc-500">
          Loading Credit / Debit Note Register…
        </div>
      )}

      {/* Error */}
      {isError && (
        <div data-testid="cndn-error" className="border border-red-300 bg-red-50 rounded-sm p-4 text-sm text-red-700">
          Could not load register. {error?.response?.data?.detail || error?.message || ""}
          <button onClick={() => refetch()} className="ml-3 underline">Retry</button>
        </div>
      )}

      {data && (
        <>
          {/* Reconciliation banner */}
          <div data-testid="cndn-recon-status"
            className={`border rounded-sm px-4 py-2 flex items-center justify-between text-sm ${
              reconciled ? "border-emerald-300 bg-emerald-50 text-emerald-800"
                         : "border-red-300 bg-red-50 text-red-800"
            }`}>
            <div className="font-bold">
              {reconciled ? "● RECONCILED YES ✓" : "● RECONCILED NO ✗"}
            </div>
            <div className="text-xs font-mono">
              {data.note_count || 0} notes · rows {recon.endpoint_row_count}/{recon.ground_truth_row_count} · total {fmtCurrency(recon.endpoint_total || 0)}
            </div>
          </div>

          {/* KPI cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <Kpi testid="cndn-kpi-total"    label="Total Notes"     value={kpis.total_count ?? 0} />
            <Kpi testid="cndn-kpi-credit"   label="Credit Notes"    value={kpis.credit_count ?? 0} sub={fmtCurrency(kpis.credit_total || 0)} tone="credit" />
            <Kpi testid="cndn-kpi-debit"    label="Debit Notes"     value={kpis.debit_count ?? 0}  sub={fmtCurrency(kpis.debit_total || 0)}  tone="debit" />
            <Kpi testid="cndn-kpi-net"      label="Net Receivable Δ" value={fmtCurrency(kpis.net_amount || 0)} tone="net" />
            <Kpi testid="cndn-kpi-cancelled" label="Cancelled"      value={kpis.cancelled_count ?? 0} sub={`Issued ${kpis.issued_count ?? 0} · Draft ${kpis.draft_count ?? 0}`} />
          </div>

          {/* Tax summary band */}
          <div className="border border-zinc-200 bg-white rounded-sm p-3" data-testid="cndn-tax-summary">
            <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold mb-2">Tax Summary</div>
            <div className="grid grid-cols-2 md:grid-cols-6 gap-4 text-sm font-mono">
              <div><span className="text-zinc-500">Taxable</span> <div className="font-bold">{fmtCurrency(tax.taxable || 0)}</div></div>
              <div><span className="text-zinc-500">CGST</span> <div className="font-bold">{fmtCurrency(tax.cgst || 0)}</div></div>
              <div><span className="text-zinc-500">SGST</span> <div className="font-bold">{fmtCurrency(tax.sgst || 0)}</div></div>
              <div><span className="text-zinc-500">IGST</span> <div className="font-bold">{fmtCurrency(tax.igst || 0)}</div></div>
              <div><span className="text-zinc-500">Total Tax</span> <div className="font-bold">{fmtCurrency(tax.total_tax || 0)}</div></div>
              <div><span className="text-zinc-500">Grand Total</span> <div className="font-bold">{fmtCurrency(tax.total_amount || 0)}</div></div>
            </div>
          </div>

          {isEmpty && (
            <div data-testid="cndn-empty-state" className="border border-zinc-200 bg-white rounded-sm p-8 text-center text-sm text-zinc-500">
              No CN/DN records for the selected filters.
            </div>
          )}

          {/* By-Reason breakdown */}
          {byReason.length > 0 && (
            <div className="border border-zinc-200 bg-white rounded-sm overflow-x-auto" data-testid="cndn-by-reason">
              <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">By Reason</div>
              <table className="w-full text-sm">
                <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
                  <tr>
                    <th className="text-left px-3 py-2">QORVENA Reason</th>
                    <th className="text-left px-3 py-2">§9B Code</th>
                    <th className="text-right px-3 py-2">Count</th>
                    <th className="text-right px-3 py-2">CN</th>
                    <th className="text-right px-3 py-2">DN</th>
                    <th className="text-right px-3 py-2">Total ₹</th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {byReason.map((br) => (
                    <tr key={br.reason_code} className="border-t border-zinc-100">
                      <td className="px-3 py-1.5">{br.reason_code}</td>
                      <td className="px-3 py-1.5">{br.gstr1_9b_reason_code}</td>
                      <td className="px-3 py-1.5 text-right">{br.count}</td>
                      <td className="px-3 py-1.5 text-right">{br.credit_count}</td>
                      <td className="px-3 py-1.5 text-right">{br.debit_count}</td>
                      <td className="px-3 py-1.5 text-right font-bold">{fmtCurrency(br.total_amount || 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Register table */}
          {rows.length > 0 && (
            <div className="border border-zinc-200 bg-white rounded-sm overflow-x-auto" data-testid="cndn-register-table">
              <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">
                Register ({rows.length})
              </div>
              <table className="w-full text-sm">
                <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
                  <tr>
                    <th className="text-left px-3 py-2">Note #</th>
                    <th className="text-left px-3 py-2">Date</th>
                    <th className="text-center px-3 py-2">T</th>
                    <th className="text-center px-3 py-2">Status</th>
                    <th className="text-left px-3 py-2">Customer</th>
                    <th className="text-left px-3 py-2">GSTIN</th>
                    <th className="text-left px-3 py-2">Invoice #</th>
                    <th className="text-right px-3 py-2">Taxable ₹</th>
                    <th className="text-right px-3 py-2">CGST</th>
                    <th className="text-right px-3 py-2">SGST</th>
                    <th className="text-right px-3 py-2">IGST</th>
                    <th className="text-right px-3 py-2">Total ₹</th>
                    <th className="text-right px-3 py-2">Signed ₹</th>
                    <th className="text-left px-3 py-2">Reason</th>
                    <th className="text-center px-3 py-2">GST</th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {rows.map((r) => {
                    const bg = r.kind === "credit" ? "bg-red-50" : "bg-blue-50";
                    const invHref = r.invoice_id ? `/invoices/${r.invoice_id}` : null;
                    return (
                      <tr key={r.note_id} data-testid={`cndn-row-${r.note_id}`} className={`border-t border-zinc-100 ${bg}`}>
                        <td className="px-3 py-1.5 whitespace-nowrap font-semibold">
                          <a href={`/notes?nid=${r.note_id}`} className="hover:underline" data-testid={`cndn-drill-${r.note_id}`}>
                            {r.note_number || <span className="text-zinc-400 italic">draft</span>}
                          </a>
                        </td>
                        <td className="px-3 py-1.5 whitespace-nowrap">{r.note_date}</td>
                        <td className="px-3 py-1.5 text-center font-bold">{r.ntty}</td>
                        <td className="px-3 py-1.5 text-center">
                          <span className={`inline-block px-1.5 py-0.5 text-[9px] rounded-sm font-bold ${
                            r.status === "issued" ? "bg-emerald-700 text-white" :
                            r.status === "draft" ? "bg-zinc-400 text-white" :
                            "bg-red-700 text-white"
                          }`}>{r.status?.toUpperCase()}</span>
                        </td>
                        <td className="px-3 py-1.5">{r.customer_name}</td>
                        <td className="px-3 py-1.5 whitespace-nowrap">{r.customer_gstin || "—"}</td>
                        <td className="px-3 py-1.5 whitespace-nowrap">
                          {invHref ? <a href={invHref} className="hover:underline">{r.invoice_number}</a> : r.invoice_number}
                        </td>
                        <td className="px-3 py-1.5 text-right">{fmtCurrency(r.subtotal || 0)}</td>
                        <td className="px-3 py-1.5 text-right">{fmtCurrency(r.cgst_amount || 0)}</td>
                        <td className="px-3 py-1.5 text-right">{fmtCurrency(r.sgst_amount || 0)}</td>
                        <td className="px-3 py-1.5 text-right">{fmtCurrency(r.igst_amount || 0)}</td>
                        <td className="px-3 py-1.5 text-right font-bold">{fmtCurrency(r.total_amount || 0)}</td>
                        <td className={`px-3 py-1.5 text-right font-bold ${r.signed_amount < 0 ? "text-red-700" : "text-blue-700"}`}>
                          {fmtCurrency(r.signed_amount || 0)}
                        </td>
                        <td className="px-3 py-1.5 text-[11px]">
                          {r.reason_code} · §9B {r.reason_code_gstr1_9b}
                        </td>
                        <td className="px-3 py-1.5 text-center">
                          {r.apply_gst ? "Y" : <span className="text-amber-700 font-bold">N</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Warnings */}
          {warnings.length > 0 && (
            <div data-testid="cndn-warnings" className="border border-amber-300 bg-amber-50 rounded-sm p-3 text-xs text-amber-800">
              <div className="font-bold uppercase tracking-wider mb-1 flex items-center gap-1"><Info size={12} /> Warnings</div>
              <ul className="list-disc list-inside space-y-0.5 font-mono">
                {warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}

          {/* JSON panel */}
          {showJson && (
            <div data-testid="cndn-json-panel" className="border border-zinc-300 bg-zinc-50 rounded-sm p-3">
              <div className="flex items-center justify-between mb-2">
                <div className="text-xs uppercase tracking-wider font-bold text-zinc-500">Canonical JSON (technical)</div>
                <button onClick={doJsonDownload} className="text-xs underline hover:text-zinc-950">Download JSON</button>
              </div>
              <pre className="text-[10px] leading-tight font-mono overflow-auto max-h-96 bg-white p-2 border border-zinc-200 rounded-sm">
{JSON.stringify(data, null, 2)}
              </pre>
            </div>
          )}
        </>
      )}
    </div>
  );
}
