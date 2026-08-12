// Iter61 · Phase C — Driver Salary & Payment Ledger.
// Single source of truth: server computes opening balance, running
// balance and closing balance. This page never does arithmetic on the
// client — it only renders + posts.
import React from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, fmtCurrency } from "@/api";
import { toast } from "sonner";
import {
  ArrowLeft, Plus, Trash2, Download, FileText, Wallet,
  IndianRupee, TrendingDown, TrendingUp, ChevronRight,
} from "lucide-react";

const ic = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";
const icSm = "border border-zinc-300 px-3 py-1.5 rounded-sm text-xs focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";
const btnPrimary = "inline-flex items-center gap-1 text-xs px-3 py-1.5 border border-zinc-950 bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 uppercase tracking-wider font-semibold";
const btnGhost = "inline-flex items-center gap-1 text-xs px-3 py-1.5 border border-zinc-300 rounded-sm hover:bg-zinc-50 uppercase tracking-wider";

const ENTRY_TYPE_LABEL = {
  salary: "Salary",
  advance: "Advance",
  other_payment: "Other Payment",
  trip_recovery: "Trip Recovery",
  other_deduction: "Other Deduction",
  settlement: "Settlement",
};

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function monthISO() {
  return new Date().toISOString().slice(0, 7);
}

function StatTile({ label, value, subtitle, tone = "default", testid }) {
  const toneCls = {
    default: "border-zinc-200 bg-white",
    credit: "border-emerald-200 bg-emerald-50",
    debit: "border-rose-200 bg-rose-50",
    accent: "border-sky-200 bg-sky-50",
  }[tone] || "border-zinc-200 bg-white";
  return (
    <div className={`border ${toneCls} rounded-sm px-5 py-4`} data-testid={testid}>
      <div className="text-[10px] uppercase tracking-[0.15em] font-bold text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-black tracking-tight text-zinc-950 tabular-nums">{value}</div>
      {subtitle && <div className="text-xs text-zinc-500 mt-0.5">{subtitle}</div>}
    </div>
  );
}

export default function DriverLedger() {
  const { id } = useParams();
  const qc = useQueryClient();
  const [dateFrom, setDateFrom] = React.useState("");
  const [dateTo, setDateTo] = React.useState("");
  // Modal state
  const [showEntryModal, setShowEntryModal] = React.useState(false);
  const [showSalaryModal, setShowSalaryModal] = React.useState(false);
  const [showSettleModal, setShowSettleModal] = React.useState(false);
  const [showPostModal, setShowPostModal] = React.useState(false);
  const [entryForm, setEntryForm] = React.useState({
    entry_date: todayISO(), entry_type: "advance", amount: "", remarks: "",
  });
  const [salaryForm, setSalaryForm] = React.useState({
    monthly_salary: "", effective_from: monthISO() + "-01", remarks: "",
  });
  const [settleForm, setSettleForm] = React.useState({
    month: monthISO(), paid_amount: "", remarks: "",
  });
  const [postForm, setPostForm] = React.useState({ month: monthISO() });

  const params = { date_from: dateFrom, date_to: dateTo };
  const { data: ledger, isLoading: loadingLedger } = useQuery({
    queryKey: ["driver-ledger", id, dateFrom, dateTo],
    queryFn: async () => (await api.get(`/drivers/${id}/ledger`, { params })).data,
  });
  const { data: salaryMasters } = useQuery({
    queryKey: ["driver-salary-masters", id],
    queryFn: async () => (await api.get(`/drivers/${id}/salary-masters`)).data,
  });
  const { data: rollup } = useQuery({
    queryKey: ["driver-ledger-monthly", id],
    queryFn: async () => (await api.get(`/drivers/${id}/ledger/monthly`, { params: { months: 12 } })).data,
  });

  const driver = ledger?.driver;
  const entries = ledger?.entries || [];

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["driver-ledger", id] });
    qc.invalidateQueries({ queryKey: ["driver-ledger-monthly", id] });
  };

  const addEntry = useMutation({
    mutationFn: async () => (await api.post(`/drivers/${id}/ledger`, {
      ...entryForm, amount: Number(entryForm.amount),
    })).data,
    onSuccess: () => {
      toast.success("Ledger entry added");
      invalidateAll();
      setShowEntryModal(false);
      setEntryForm({ entry_date: todayISO(), entry_type: "advance", amount: "", remarks: "" });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const addSalary = useMutation({
    mutationFn: async () => (await api.post(`/drivers/${id}/salary-masters`, {
      ...salaryForm, monthly_salary: Number(salaryForm.monthly_salary),
    })).data,
    onSuccess: () => {
      toast.success("Salary master added");
      qc.invalidateQueries({ queryKey: ["driver-salary-masters", id] });
      setShowSalaryModal(false);
      setSalaryForm({ monthly_salary: "", effective_from: monthISO() + "-01", remarks: "" });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const settle = useMutation({
    mutationFn: async () => (await api.post(`/drivers/${id}/ledger/settle`, {
      ...settleForm, paid_amount: Number(settleForm.paid_amount),
    })).data,
    onSuccess: () => {
      toast.success("Settlement recorded");
      invalidateAll();
      setShowSettleModal(false);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const postSalary = useMutation({
    mutationFn: async () => (await api.post(`/drivers/${id}/ledger/post-monthly-salary`, postForm)).data,
    onSuccess: (d) => {
      toast.success(d.updated ? `Salary updated for ${postForm.month}` : `Salary posted for ${postForm.month}`);
      invalidateAll();
      setShowPostModal(false);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const deleteEntry = useMutation({
    mutationFn: async (eid) => (await api.delete(`/drivers/${id}/ledger/${eid}`)).data,
    onSuccess: () => { toast.success("Entry deleted"); invalidateAll(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const exportLedger = (fmt) => {
    const p = new URLSearchParams({ format: fmt });
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo) p.set("date_to", dateTo);
    const url = `${api.defaults.baseURL}/drivers/${id}/ledger/export?${p.toString()}`;
    // Attach the Bearer via a temporary anchor because HTMLAnchor won't send headers.
    // We use fetch → blob → download so auth header is honored.
    api.get(`/drivers/${id}/ledger/export`, { params: { format: fmt, date_from: dateFrom, date_to: dateTo }, responseType: "blob" })
      .then((res) => {
        const blob = new Blob([res.data], { type: fmt === "csv" ? "text/csv" : "application/pdf" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `driver-ledger-${driver?.name || id}-${dateFrom || "all"}_to_${dateTo || "now"}.${fmt}`;
        link.click();
      })
      .catch(() => toast.error("Export failed"));
  };

  return (
    <div className="space-y-6" data-testid="driver-ledger-page">
      {/* HEADER */}
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <Link to="/drivers" className="text-xs text-zinc-500 hover:text-zinc-950 inline-flex items-center gap-1 mb-2">
            <ArrowLeft size={12} /> Back to Drivers
          </Link>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Driver Ledger</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            {driver?.name || "…"}
          </h1>
          <div className="text-xs text-zinc-500 mt-1">{driver?.phone || "—"}</div>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to={`/drivers/${id}/history`}
            data-testid="link-trip-history"
            className={btnGhost}
          >
            Trip History <ChevronRight size={12} />
          </Link>
          <button data-testid="export-csv-btn" onClick={() => exportLedger("csv")} className={btnGhost}>
            <Download size={12} /> CSV
          </button>
          <button data-testid="export-pdf-btn" onClick={() => exportLedger("pdf")} className={btnGhost}>
            <FileText size={12} /> PDF
          </button>
        </div>
      </header>

      {/* STAT TILES */}
      <div className="grid grid-cols-4 gap-3">
        <StatTile
          label="Opening Balance"
          value={fmtCurrency(ledger?.opening_balance || 0)}
          subtitle={dateFrom ? `Before ${dateFrom}` : "Start of records"}
          testid="stat-opening"
        />
        <StatTile
          label="Total Credit (Earned)"
          value={fmtCurrency(ledger?.credit_total || 0)}
          tone="credit"
          testid="stat-credit"
        />
        <StatTile
          label="Total Debit (Paid/Deducted)"
          value={fmtCurrency(ledger?.debit_total || 0)}
          tone="debit"
          testid="stat-debit"
        />
        <StatTile
          label="Closing Balance"
          value={fmtCurrency(ledger?.closing_balance || 0)}
          subtitle={(ledger?.closing_balance || 0) >= 0 ? "Owed to driver" : "Owed by driver"}
          tone="accent"
          testid="stat-closing"
        />
      </div>

      {/* CONTROL STRIP */}
      <div className="flex flex-wrap items-center gap-2 border border-zinc-200 rounded-sm bg-white p-3">
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 block">From</label>
          <input data-testid="ledger-date-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className={icSm} />
        </div>
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 block">To</label>
          <input data-testid="ledger-date-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className={icSm} />
        </div>
        <button data-testid="ledger-clear-dates" onClick={() => { setDateFrom(""); setDateTo(""); }} className="text-xs text-zinc-500 hover:text-zinc-950 self-end pb-1.5 ml-2">Clear</button>

        <div className="grow" />

        <button data-testid="add-entry-btn" onClick={() => setShowEntryModal(true)} className={btnPrimary}>
          <Plus size={12} /> Add Payment / Deduction
        </button>
        <button data-testid="post-salary-btn" onClick={() => setShowPostModal(true)} className={btnGhost}>
          <IndianRupee size={12} /> Post Monthly Salary
        </button>
        <button data-testid="settle-btn" onClick={() => setShowSettleModal(true)} className={btnGhost}>
          <Wallet size={12} /> Monthly Settlement
        </button>
      </div>

      {/* SALARY MASTERS */}
      <section className="border border-zinc-200 rounded-sm bg-white">
        <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3">
          <h3 className="text-sm font-bold uppercase tracking-wider">Salary Master · Effective-Dated</h3>
          <button data-testid="add-salary-btn" onClick={() => setShowSalaryModal(true)} className={btnPrimary}>
            <Plus size={12} /> Add Salary
          </button>
        </div>
        <table className="w-full text-sm" data-testid="salary-masters-table">
          <thead className="text-[10px] uppercase tracking-wider text-zinc-500 border-b border-zinc-200">
            <tr>
              <th className="px-4 py-2 text-left">Effective From</th>
              <th className="px-4 py-2 text-left">Effective To</th>
              <th className="px-4 py-2 text-right">Monthly Salary</th>
              <th className="px-4 py-2 text-left">Version</th>
              <th className="px-4 py-2 text-left">Remarks</th>
            </tr>
          </thead>
          <tbody>
            {(salaryMasters?.items || []).map((s) => (
              <tr key={s.id} className="border-b border-zinc-100" data-testid={`salary-row-${s.id}`}>
                <td className="px-4 py-2 font-mono">{s.effective_from}</td>
                <td className="px-4 py-2 font-mono text-zinc-500">{s.effective_to || "—"}</td>
                <td className="px-4 py-2 text-right tabular-nums font-semibold">{fmtCurrency(s.monthly_salary)}</td>
                <td className="px-4 py-2 text-xs text-zinc-500">v{s.version}</td>
                <td className="px-4 py-2 text-xs text-zinc-600">{s.remarks || "—"}</td>
              </tr>
            ))}
            {(salaryMasters?.items || []).length === 0 && (
              <tr><td colSpan={5} className="px-4 py-12 text-center text-zinc-400" data-testid="salary-empty">
                No salary records yet. Add the driver&apos;s current salary above.
              </td></tr>
            )}
          </tbody>
        </table>
      </section>

      {/* LEDGER TABLE */}
      <section className="border border-zinc-200 rounded-sm bg-white">
        <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3">
          <h3 className="text-sm font-bold uppercase tracking-wider">Ledger Transactions</h3>
          <div className="text-xs text-zinc-500">{entries.length} entries</div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="ledger-table">
            <thead className="text-[10px] uppercase tracking-wider text-zinc-500 border-b border-zinc-200 bg-zinc-50">
              <tr>
                <th className="px-4 py-2 text-left">Date</th>
                <th className="px-4 py-2 text-left">Type</th>
                <th className="px-4 py-2 text-left">Reference</th>
                <th className="px-4 py-2 text-left">Remarks</th>
                <th className="px-4 py-2 text-right">Credit</th>
                <th className="px-4 py-2 text-right">Debit</th>
                <th className="px-4 py-2 text-right">Balance</th>
                <th className="px-2 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {loadingLedger && (
                <tr><td colSpan={8} className="px-4 py-12 text-center text-zinc-400">Loading…</td></tr>
              )}
              {!loadingLedger && entries.length === 0 && (
                <tr><td colSpan={8} className="px-4 py-12 text-center text-zinc-400" data-testid="ledger-empty">
                  No transactions in this window. Post monthly salary or add a payment to get started.
                </td></tr>
              )}
              {entries.map((e) => {
                const ref = e.reference || {};
                let refDisp = "";
                if (ref.kind === "trip") refDisp = `Trip · LR ${ref.lr_number || (ref.id || "").slice(0, 8)}`;
                else if (ref.kind === "salary_master") refDisp = `Salary v${ref.version || 1} · ${ref.month || ""}`;
                else if (ref.kind === "settlement") refDisp = `Settlement · ${ref.month || ""}`;
                return (
                  <tr key={e.id} className="border-b border-zinc-100 hover:bg-zinc-50" data-testid={`ledger-row-${e.id}`}>
                    <td className="px-4 py-2 font-mono text-xs">{e.entry_date}</td>
                    <td className="px-4 py-2 text-xs">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-[10px] uppercase tracking-wider font-semibold border ${
                        e.direction === "credit" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-rose-50 text-rose-700 border-rose-200"
                      }`}>
                        {e.direction === "credit" ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                        {ENTRY_TYPE_LABEL[e.entry_type] || e.entry_type}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-xs text-zinc-600">{refDisp || (e.source === "system" ? "System" : "Manual")}</td>
                    <td className="px-4 py-2 text-xs text-zinc-500 max-w-[240px] truncate">{e.remarks || "—"}</td>
                    <td className="px-4 py-2 text-right font-mono tabular-nums text-emerald-700">{e.direction === "credit" ? fmtCurrency(e.amount) : ""}</td>
                    <td className="px-4 py-2 text-right font-mono tabular-nums text-rose-700">{e.direction === "debit" ? fmtCurrency(e.amount) : ""}</td>
                    <td className="px-4 py-2 text-right font-mono tabular-nums font-semibold">{fmtCurrency(e.balance)}</td>
                    <td className="px-2 py-2">
                      {e.source === "manual" && (
                        <button data-testid={`delete-entry-${e.id}`}
                          onClick={() => { if (window.confirm("Delete this ledger entry?")) deleteEntry.mutate(e.id); }}
                          className="text-rose-600 hover:text-rose-800 p-1"
                          title="Delete manual entry">
                          <Trash2 size={12} />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* MONTHLY ROLLUP */}
      <section className="border border-zinc-200 rounded-sm bg-white">
        <div className="border-b border-zinc-200 px-4 py-3">
          <h3 className="text-sm font-bold uppercase tracking-wider">Monthly Rollup · Last 12 Months</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="monthly-rollup-table">
            <thead className="text-[10px] uppercase tracking-wider text-zinc-500 border-b border-zinc-200 bg-zinc-50">
              <tr>
                <th className="px-4 py-2 text-left">Month</th>
                <th className="px-4 py-2 text-right">Salary</th>
                <th className="px-4 py-2 text-right">Advance</th>
                <th className="px-4 py-2 text-right">Trip Recovery</th>
                <th className="px-4 py-2 text-right">Other Deduction</th>
                <th className="px-4 py-2 text-right">Other Payment</th>
                <th className="px-4 py-2 text-right">Settlement</th>
                <th className="px-4 py-2 text-right">Net Change</th>
              </tr>
            </thead>
            <tbody>
              {(rollup?.items || []).map((r) => (
                <tr key={r.month} className="border-b border-zinc-100" data-testid={`rollup-row-${r.month}`}>
                  <td className="px-4 py-2 font-mono text-xs font-semibold">{r.month || "—"}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-emerald-700">{r.salary ? fmtCurrency(r.salary) : "—"}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-rose-700">{r.advance ? fmtCurrency(r.advance) : "—"}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-rose-700">{r.trip_recovery ? fmtCurrency(r.trip_recovery) : "—"}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-rose-700">{r.other_deduction ? fmtCurrency(r.other_deduction) : "—"}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-rose-700">{r.other_payment ? fmtCurrency(r.other_payment) : "—"}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-rose-700">{r.settlement ? fmtCurrency(r.settlement) : "—"}</td>
                  <td className={`px-4 py-2 text-right tabular-nums font-semibold ${r.net_change >= 0 ? "text-emerald-700" : "text-rose-700"}`}>
                    {fmtCurrency(r.net_change)}
                  </td>
                </tr>
              ))}
              {(rollup?.items || []).length === 0 && (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-zinc-400">No activity yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* ADD PAYMENT / DEDUCTION MODAL */}
      {showEntryModal && (
        <Modal title="Add Payment / Deduction" onClose={() => setShowEntryModal(false)} testid="entry-modal">
          <form onSubmit={(e) => { e.preventDefault(); addEntry.mutate(); }} className="space-y-3">
            <F label="Type *">
              <select data-testid="entry-type" value={entryForm.entry_type} onChange={(e) => setEntryForm({ ...entryForm, entry_type: e.target.value })} className={ic}>
                <option value="advance">Advance (paid to driver)</option>
                <option value="other_payment">Other Payment (paid to driver)</option>
                <option value="other_deduction">Other Deduction</option>
                <option value="salary">Salary (manual credit)</option>
              </select>
            </F>
            <F label="Date *"><input data-testid="entry-date" type="date" required value={entryForm.entry_date} onChange={(e) => setEntryForm({ ...entryForm, entry_date: e.target.value })} className={ic} /></F>
            <F label="Amount (₹) *"><input data-testid="entry-amount" type="number" min="0.01" step="0.01" required value={entryForm.amount} onChange={(e) => setEntryForm({ ...entryForm, amount: e.target.value })} className={ic} /></F>
            <F label="Remarks"><textarea rows={2} data-testid="entry-remarks" value={entryForm.remarks} onChange={(e) => setEntryForm({ ...entryForm, remarks: e.target.value })} className={ic} /></F>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => setShowEntryModal(false)} className={btnGhost}>Cancel</button>
              <button data-testid="save-entry-btn" type="submit" disabled={addEntry.isPending} className={btnPrimary}>
                {addEntry.isPending ? "Saving..." : "Save Entry"}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* ADD SALARY MASTER MODAL */}
      {showSalaryModal && (
        <Modal title="Add Salary Master · New Version" onClose={() => setShowSalaryModal(false)} testid="salary-modal">
          <form onSubmit={(e) => { e.preventDefault(); addSalary.mutate(); }} className="space-y-3">
            <F label="Monthly Salary (₹) *"><input data-testid="salary-amount" type="number" min="0" step="0.01" required value={salaryForm.monthly_salary} onChange={(e) => setSalaryForm({ ...salaryForm, monthly_salary: e.target.value })} className={ic} /></F>
            <F label="Effective From *"><input data-testid="salary-effective-from" type="date" required value={salaryForm.effective_from} onChange={(e) => setSalaryForm({ ...salaryForm, effective_from: e.target.value })} className={ic} /></F>
            <F label="Remarks"><textarea rows={2} data-testid="salary-remarks" value={salaryForm.remarks} onChange={(e) => setSalaryForm({ ...salaryForm, remarks: e.target.value })} className={ic} /></F>
            <div className="text-xs text-zinc-500 bg-amber-50 border border-amber-200 p-2 rounded-sm">
              Prior open-ended salary will automatically end the day before this effective date. Historical months keep their old salary — no retroactive recalculation.
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => setShowSalaryModal(false)} className={btnGhost}>Cancel</button>
              <button data-testid="save-salary-btn" type="submit" disabled={addSalary.isPending} className={btnPrimary}>
                {addSalary.isPending ? "Saving..." : "Save Salary"}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* POST MONTHLY SALARY MODAL */}
      {showPostModal && (
        <Modal title="Post Monthly Salary" onClose={() => setShowPostModal(false)} testid="post-salary-modal">
          <form onSubmit={(e) => { e.preventDefault(); postSalary.mutate(); }} className="space-y-3">
            <F label="Month *"><input data-testid="post-month" type="month" required value={postForm.month} onChange={(e) => setPostForm({ ...postForm, month: e.target.value })} className={ic} /></F>
            <div className="text-xs text-zinc-500">
              The salary master effective on the last day of this month will be posted as a credit entry. Reposting the same month is idempotent.
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => setShowPostModal(false)} className={btnGhost}>Cancel</button>
              <button data-testid="confirm-post-salary-btn" type="submit" disabled={postSalary.isPending} className={btnPrimary}>
                {postSalary.isPending ? "Posting..." : "Post Salary"}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* SETTLEMENT MODAL */}
      {showSettleModal && (
        <Modal title="Monthly Settlement" onClose={() => setShowSettleModal(false)} testid="settle-modal">
          <form onSubmit={(e) => { e.preventDefault(); settle.mutate(); }} className="space-y-3">
            <F label="Month *"><input data-testid="settle-month" type="month" required value={settleForm.month} onChange={(e) => setSettleForm({ ...settleForm, month: e.target.value })} className={ic} /></F>
            <F label="Amount Paid (₹) *"><input data-testid="settle-amount" type="number" min="0" step="0.01" required value={settleForm.paid_amount} onChange={(e) => setSettleForm({ ...settleForm, paid_amount: e.target.value })} className={ic} /></F>
            <F label="Remarks"><textarea rows={2} data-testid="settle-remarks" value={settleForm.remarks} onChange={(e) => setSettleForm({ ...settleForm, remarks: e.target.value })} className={ic} /></F>
            <div className="text-xs text-zinc-500">
              Sets a settlement debit entry dated the last day of the month. Set amount to 0 to clear a previous settlement.
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => setShowSettleModal(false)} className={btnGhost}>Cancel</button>
              <button data-testid="confirm-settle-btn" type="submit" disabled={settle.isPending} className={btnPrimary}>
                {settle.isPending ? "Saving..." : "Save Settlement"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

function Modal({ title, onClose, testid, children }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4" data-testid={testid}>
      <div className="bg-white w-full max-w-md border border-zinc-950 rounded-sm">
        <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
          <h3 className="font-bold">{title}</h3>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-950 text-lg leading-none">×</button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

function F({ label, children }) {
  return (
    <div>
      <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">{label}</label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
