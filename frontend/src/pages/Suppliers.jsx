import React, { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { NavLink, Routes, Route, Navigate, useParams, useNavigate, Link } from "react-router-dom";
import { api, fmtCurrency } from "@/api";
import { toast } from "sonner";
import { Handshake, Plus, Users, Truck, Wallet, FileText, AlertCircle, TrendingUp, Download, Printer, MessageCircle, Trash2, X, Edit3, Search } from "lucide-react";
import SearchableSelect from "@/components/SearchableSelect";

const inputCls = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";
const labelCls = "text-[10px] uppercase font-bold text-zinc-500 tracking-wider mb-1 block";

const tabs = [
  { to: "list",        en: "List",        te: "సప్లయర్లు",     icon: Users,       testid: "sup-tab-list" },
  { to: "add",         en: "Add",         te: "కొత్తది జోడించు", icon: Plus,        testid: "sup-tab-add" },
  { to: "vehicles",    en: "Vehicles",    te: "వాహనాలు",       icon: Truck,       testid: "sup-tab-vehicles" },
  { to: "payments",    en: "Payments",    te: "చెల్లింపులు",     icon: Wallet,      testid: "sup-tab-payments" },
  { to: "statement",   en: "Statement",   te: "స్టేట్‌మెంట్",    icon: FileText,    testid: "sup-tab-statement" },
  { to: "outstanding", en: "Outstanding", te: "బకాయిలు",       icon: AlertCircle, testid: "sup-tab-outstanding" },
  { to: "pl",          en: "P&L",         te: "P&L",           icon: TrendingUp,  testid: "sup-tab-pl" },
];

export default function Suppliers() {
  return (
    <div className="p-6 max-w-[1600px] mx-auto" data-testid="suppliers-page">
      <div className="flex items-center gap-2 mb-4">
        <Handshake className="text-amber-600" />
        <h1 className="text-2xl font-black tracking-tight"><span className="telugu">సప్లయర్లు</span> · Suppliers</h1>
      </div>
      <nav className="flex flex-wrap gap-1 border-b border-zinc-200 mb-6">
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to} data-testid={t.testid}
            className={({ isActive }) =>
              `flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider font-bold border-b-2 -mb-px ${isActive ? "border-zinc-950 text-zinc-950" : "border-transparent text-zinc-500 hover:text-zinc-800"}`
            }>
            <t.icon size={14} />
            <span>{t.en}</span>
          </NavLink>
        ))}
      </nav>
      <Routes>
        <Route index element={<SupplierDashboard />} />
        <Route path="list" element={<SupplierList />} />
        <Route path="add" element={<SupplierForm />} />
        <Route path="edit/:sid" element={<SupplierForm />} />
        <Route path="vehicles" element={<SupplierVehicles />} />
        <Route path="payments" element={<SupplierPayments />} />
        <Route path="statement" element={<SupplierStatement />} />
        <Route path="outstanding" element={<SupplierOutstanding />} />
        <Route path="pl" element={<SupplierPLTab />} />
      </Routes>
    </div>
  );
}

/* ================= Iter47 — Supplier Dashboard (6 KPI cards + top payables) ================= */
function SupplierDashboard() {
  const nav = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ["suppliers-dashboard"],
    queryFn: async () => (await api.get("/suppliers-dashboard")).data,
  });
  if (isLoading || !data) return <div className="text-sm text-zinc-500 text-center py-16">Loading…</div>;
  const t = data.totals;
  const cards = [
    { k: "Total Suppliers", v: t.total_suppliers, sub: `${t.active_suppliers} active`, tid: "sd-total-suppliers" },
    { k: "Supplier Vehicles", v: t.active_vehicles, sub: "active", tid: "sd-active-vehicles" },
    { k: "Total Freight (Trips)", v: fmtCurrency(t.total_freight), sub: "supplier-side freight", tid: "sd-total-freight" },
    { k: "Total Advances", v: fmtCurrency(t.total_advances), sub: "given at trip time", tid: "sd-total-advances" },
    { k: "Total Payments", v: fmtCurrency(t.total_payments), sub: "cash / bank / UPI", tid: "sd-total-payments" },
    { k: "Total Outstanding", v: fmtCurrency(t.total_outstanding), sub: "payable now", tid: "sd-total-outstanding", highlight: true },
  ];
  const top = data.suppliers.slice(0, 8);
  return (
    <div className="space-y-4" data-testid="sup-dashboard">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {cards.map(c => (
          <div key={c.k} data-testid={c.tid}
            className={`border rounded-sm p-3 ${c.highlight ? "border-amber-400 bg-amber-50" : "border-zinc-200 bg-white"}`}>
            <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">{c.k}</div>
            <div className="mt-1 font-mono font-bold text-base">{c.v}</div>
            <div className="text-[10px] text-zinc-500 mt-0.5">{c.sub}</div>
          </div>
        ))}
      </div>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-hidden">
        <div className="px-4 py-2 border-b border-zinc-200 flex items-center justify-between">
          <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500">Top Suppliers by Outstanding</div>
          <Link to="outstanding" className="text-[10px] uppercase font-bold text-zinc-500 hover:text-zinc-950">View All →</Link>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-600">
            <tr>
              <th className="text-left px-3 py-2">Supplier</th>
              <th className="text-left px-3 py-2">Mobile</th>
              <th className="text-right px-3 py-2">Closing Balance</th>
              <th className="text-center px-3 py-2">Status</th>
              <th className="w-24"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {top.map(s => (
              <tr key={s.supplier_id} data-testid={`sd-row-${s.supplier_id}`}
                className="hover:bg-amber-50 cursor-pointer"
                onClick={() => nav(`edit/${s.supplier_id}`)}>
                <td className="px-3 py-2 font-bold">{s.supplier_name}</td>
                <td className="px-3 py-2 text-xs font-mono">{s.mobile || "—"}</td>
                <td className="px-3 py-2 text-right font-mono font-bold text-rose-700">
                  {fmtCurrency(Math.abs(s.closing_balance))} {s.closing_type === "advance" ? "Cr" : "Dr"}
                </td>
                <td className="px-3 py-2 text-center">
                  <span className={`text-[10px] px-2 py-0.5 rounded-sm font-bold ${s.is_active ? "bg-emerald-100 text-emerald-800" : "bg-zinc-200 text-zinc-700"}`}>
                    {s.is_active ? "ACTIVE" : "INACTIVE"}
                  </span>
                </td>
                <td className="px-2 py-2 text-right text-[10px]">
                  <Link to={`../suppliers/statement`} className="uppercase font-bold text-zinc-500 hover:text-zinc-950" onClick={(e) => e.stopPropagation()}>Ledger →</Link>
                </td>
              </tr>
            ))}
            {top.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-10 text-center text-zinc-400 text-sm">No suppliers yet — add one to begin.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ================= Supplier Selector Hook ================= */
function useSuppliers() {
  return useQuery({ queryKey: ["suppliers"], queryFn: async () => (await api.get("/suppliers")).data });
}

/* ================= List ================= */
function SupplierList() {
  const [q, setQ] = useState("");
  const { data = [], isLoading } = useSuppliers();
  const rows = data.filter(s => !q || s.name.toLowerCase().includes(q.toLowerCase()) || (s.mobile || "").includes(q));

  return (
    <div className="space-y-3">
      <div className="flex gap-2 items-center">
        <Search size={16} className="text-zinc-400" />
        <input data-testid="sup-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name or mobile"
          className={`${inputCls} max-w-md`} />
        <Link to="../add" data-testid="sup-goto-add" className="ml-auto px-3 py-2 bg-zinc-950 text-white text-xs uppercase tracking-wider font-bold rounded-sm hover:bg-zinc-800">+ New Supplier</Link>
      </div>
      <div className="border border-zinc-200 rounded-sm overflow-hidden bg-white">
        <table className="w-full text-sm">
          <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-wider">
            <tr>
              <th className="text-left px-3 py-2">Name</th>
              <th className="text-left px-3 py-2">Contact</th>
              <th className="text-left px-3 py-2">Mobile</th>
              <th className="text-left px-3 py-2">GSTIN</th>
              <th className="text-right px-3 py-2">Opening</th>
              <th className="text-center px-3 py-2">Status</th>
              <th className="w-40"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {isLoading && <tr><td colSpan={7} className="px-3 py-10 text-center text-zinc-400">Loading…</td></tr>}
            {!isLoading && rows.length === 0 && <tr><td colSpan={7} className="px-3 py-10 text-center text-zinc-400">No suppliers</td></tr>}
            {rows.map(s => (
              <tr key={s.id} data-testid={`sup-row-${s.id}`} className="hover:bg-amber-50">
                <td className="px-3 py-2 font-bold">{s.name}</td>
                <td className="px-3 py-2">{s.contact_person || "—"}</td>
                <td className="px-3 py-2 font-mono">{s.mobile || "—"}</td>
                <td className="px-3 py-2 font-mono text-xs">{s.gst_in || "—"}</td>
                <td className="px-3 py-2 text-right font-mono">
                  {s.opening_balance ? `${fmtCurrency(s.opening_balance)} ${s.opening_balance_type === "advance" ? "Cr" : "Dr"}` : "—"}
                </td>
                <td className="px-3 py-2 text-center">
                  <span className={`text-[10px] px-2 py-0.5 rounded-sm font-bold ${s.is_active ? "bg-emerald-100 text-emerald-800" : "bg-zinc-200 text-zinc-700"}`}>
                    {s.is_active ? "ACTIVE" : "INACTIVE"}
                  </span>
                </td>
                <td className="px-3 py-2 text-right space-x-2">
                  <Link to={`../edit/${s.id}`} data-testid={`sup-edit-${s.id}`} className="text-[10px] uppercase font-bold text-zinc-500 hover:text-zinc-950"><Edit3 size={13} className="inline"/> Edit</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ================= Add / Edit ================= */
const EMPTY_SUP = {
  name: "", contact_person: "", mobile: "", alt_mobile: "", address: "", state: "", city: "",
  gst_in: "", pan: "", msme_number: "",
  bank_name: "", account_number: "", ifsc: "", branch: "",
  payment_terms: "", opening_balance: 0, opening_balance_type: "payable",
  remarks: "", is_active: true,
};

function SupplierForm() {
  const { sid } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [form, setForm] = useState(EMPTY_SUP);
  const { data } = useQuery({
    queryKey: ["supplier", sid], enabled: !!sid,
    queryFn: async () => (await api.get(`/suppliers/${sid}`)).data,
  });
  React.useEffect(() => { if (data) setForm({ ...EMPTY_SUP, ...data }); }, [data]);

  const save = useMutation({
    mutationFn: async () => {
      const payload = { ...form, opening_balance: Number(form.opening_balance || 0) };
      if (sid) return (await api.put(`/suppliers/${sid}`, payload)).data;
      return (await api.post("/suppliers", payload)).data;
    },
    onSuccess: () => {
      toast.success(sid ? "Supplier updated" : "Supplier created");
      qc.invalidateQueries({ queryKey: ["suppliers"] });
      nav("../list");
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Save failed"),
  });

  const F = (k, label, opts = {}) => (
    <div>
      <label className={labelCls}>{label}{opts.required && " *"}</label>
      <input data-testid={`sup-field-${k}`} type={opts.type || "text"} value={form[k] ?? ""}
        onChange={(e) => setForm({ ...form, [k]: e.target.value })}
        className={inputCls} placeholder={opts.placeholder || ""} />
    </div>
  );

  return (
    <form onSubmit={(e) => { e.preventDefault(); if (!form.name.trim()) { toast.error("Name required"); return; } save.mutate(); }} className="space-y-6" data-testid="sup-form">
      <div className="border border-zinc-200 bg-white rounded-sm p-4">
        <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-3">Basic Info</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {F("name", "Supplier Name", { required: true })}
          {F("contact_person", "Contact Person")}
          {F("mobile", "Mobile Number")}
          {F("alt_mobile", "Alternate Mobile")}
          <div className="md:col-span-2">
            <label className={labelCls}>Address</label>
            <input data-testid="sup-field-address" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} className={inputCls} />
          </div>
          {F("city", "City")}
          {F("state", "State")}
        </div>
      </div>

      <div className="border border-zinc-200 bg-white rounded-sm p-4">
        <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-3">Compliance</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {F("gst_in", "GSTIN")}
          {F("pan", "PAN")}
          {F("msme_number", "MSME / UDYAM No.")}
        </div>
      </div>

      <div className="border border-zinc-200 bg-white rounded-sm p-4">
        <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-3">Bank Details</div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          {F("bank_name", "Bank Name")}
          {F("account_number", "Account Number")}
          {F("ifsc", "IFSC")}
          {F("branch", "Branch")}
        </div>
      </div>

      <div className="border border-zinc-200 bg-white rounded-sm p-4">
        <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-3">Terms &amp; Opening Balance</div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          {F("payment_terms", "Payment Terms", { placeholder: "e.g. Net 15 days" })}
          {F("opening_balance", "Opening Balance", { type: "number" })}
          <div>
            <label className={labelCls}>Opening Type</label>
            <select data-testid="sup-field-opening_balance_type" value={form.opening_balance_type}
              onChange={(e) => setForm({ ...form, opening_balance_type: e.target.value })} className={inputCls}>
              <option value="payable">Payable (Dr — we owe)</option>
              <option value="advance">Advance (Cr — paid in advance)</option>
            </select>
          </div>
          <div>
            <label className={labelCls}>Status</label>
            <select data-testid="sup-field-is_active" value={form.is_active ? "1" : "0"}
              onChange={(e) => setForm({ ...form, is_active: e.target.value === "1" })} className={inputCls}>
              <option value="1">Active</option>
              <option value="0">Inactive</option>
            </select>
          </div>
        </div>
        <div className="mt-3">
          <label className={labelCls}>Remarks</label>
          <textarea data-testid="sup-field-remarks" value={form.remarks} onChange={(e) => setForm({ ...form, remarks: e.target.value })} className={inputCls} rows={2} />
        </div>
      </div>

      <div className="flex gap-2 justify-end">
        <button type="button" onClick={() => nav("../list")} data-testid="sup-cancel" className="px-4 py-2 text-xs uppercase tracking-wider font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100">Cancel</button>
        <button type="submit" data-testid="sup-save" disabled={save.isPending} className="px-6 py-2 text-xs uppercase tracking-wider font-bold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
          {save.isPending ? "Saving…" : (sid ? "Update" : "Create")}
        </button>
      </div>
    </form>
  );
}

/* ================= Supplier Selector (shared) ================= */
function SupplierPicker({ value, onChange, testid = "sup-picker" }) {
  const { data: suppliers = [] } = useSuppliers();
  const options = suppliers.map(s => ({
    value: s.id,
    label: s.name,
    meta: s.mobile || "",
  }));
  return (
    <SearchableSelect
      dataTestId={testid}
      options={options}
      value={value}
      onChange={(v) => onChange(v)}
      placeholder="— Select supplier —"
      allowClear
    />
  );
}

/* ================= Vehicles Tab ================= */
function SupplierVehicles() {
  const [sid, setSid] = useState("");
  const { data = [], isLoading } = useQuery({
    queryKey: ["supplier-vehicles", sid], enabled: !!sid,
    queryFn: async () => (await api.get(`/suppliers/${sid}/vehicles`)).data,
  });
  return (
    <div className="space-y-3">
      <div className="max-w-md">
        <label className={labelCls}>Select Supplier</label>
        <SupplierPicker value={sid} onChange={setSid} testid="sup-veh-picker" />
      </div>
      {sid && (
        <div className="border border-zinc-200 rounded-sm overflow-hidden bg-white">
          <table className="w-full text-sm">
            <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-wider">
              <tr>
                <th className="text-left px-3 py-2">Vehicle No.</th>
                <th className="text-left px-3 py-2">Type</th>
                <th className="text-left px-3 py-2">Owner</th>
                <th className="text-left px-3 py-2">Driver</th>
                <th className="text-center px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {isLoading && <tr><td colSpan={5} className="px-3 py-10 text-center text-zinc-400">Loading…</td></tr>}
              {!isLoading && data.length === 0 && <tr><td colSpan={5} className="px-3 py-10 text-center text-zinc-400">No vehicles linked yet. Add from Vehicles master with vehicle_type=supplier.</td></tr>}
              {data.map(v => (
                <tr key={v.id} className="hover:bg-amber-50">
                  <td className="px-3 py-2 font-mono font-bold">{v.vehicle_number}</td>
                  <td className="px-3 py-2">{v.body_type || "—"}</td>
                  <td className="px-3 py-2">{v.owner_name || "—"}</td>
                  <td className="px-3 py-2">{v.driver_name || "—"}</td>
                  <td className="px-3 py-2 text-center">
                    <span className={`text-[10px] px-2 py-0.5 rounded-sm font-bold ${v.is_active ? "bg-emerald-100 text-emerald-800" : "bg-zinc-200 text-zinc-700"}`}>
                      {v.is_active ? "ACTIVE" : "INACTIVE"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="text-[11px] text-zinc-500 italic">Manage supplier vehicles from <Link to="/vehicles" className="underline">Vehicles</Link> master — set <b>Vehicle Type = Supplier</b> and <b>Supplier Name</b> matching this record.</div>
    </div>
  );
}

/* ================= Payments Tab ================= */
const EMPTY_PAY = {
  date: new Date().toISOString().slice(0, 10),
  amount: "", mode: "NEFT", ref_no: "", against: "outstanding", trip_id: "", lr_number: "", remarks: "",
  type: "payment_out",
};

function SupplierPayments() {
  const [sid, setSid] = useState("");
  const [draft, setDraft] = useState(EMPTY_PAY);
  const [deletingId, setDeletingId] = useState(null);
  const [deleteReason, setDeleteReason] = useState("");
  const qc = useQueryClient();

  const { data: pays = [], isLoading } = useQuery({
    queryKey: ["supplier-payments", sid], enabled: !!sid,
    queryFn: async () => (await api.get(`/suppliers/${sid}/payments`)).data,
  });

  const add = useMutation({
    mutationFn: async () => {
      const payload = { ...draft, supplier_id: sid, amount: Number(draft.amount) };
      return (await api.post(`/suppliers/${sid}/payments`, payload)).data;
    },
    onSuccess: () => {
      toast.success("Payment recorded");
      setDraft(EMPTY_PAY);
      qc.invalidateQueries({ queryKey: ["supplier-payments", sid] });
      qc.invalidateQueries({ queryKey: ["supplier-ledger"] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Save failed"),
  });

  const del = useMutation({
    mutationFn: async ({ pid, reason }) =>
      (await api.delete(`/suppliers/${sid}/payments/${pid}?reason=${encodeURIComponent(reason)}`)).data,
    onSuccess: () => {
      toast.success("Payment deleted");
      setDeletingId(null); setDeleteReason("");
      qc.invalidateQueries({ queryKey: ["supplier-payments", sid] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Delete failed"),
  });

  return (
    <div className="space-y-4">
      <div className="max-w-md">
        <label className={labelCls}>Select Supplier</label>
        <SupplierPicker value={sid} onChange={setSid} testid="sup-pay-picker" />
      </div>

      {sid && (
        <>
          {/* Add form */}
          <div className="border border-zinc-200 bg-zinc-50 rounded-sm p-4" data-testid="sup-pay-form">
            <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 mb-2">Enter Payment</div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <div>
                <label className={labelCls}>Date</label>
                <input data-testid="sp-date" type="date" value={draft.date} onChange={(e) => setDraft({ ...draft, date: e.target.value })} className={inputCls} />
              </div>
              <div>
                <label className={labelCls}>Amount (₹)</label>
                <input data-testid="sp-amount" type="number" step="0.01" min="0" value={draft.amount} onChange={(e) => setDraft({ ...draft, amount: e.target.value })} className={inputCls} />
              </div>
              <div>
                <label className={labelCls}>Mode</label>
                <select data-testid="sp-mode" value={draft.mode} onChange={(e) => setDraft({ ...draft, mode: e.target.value })} className={inputCls}>
                  {["Cash","Bank","UPI","IMPS","NEFT","RTGS","Cheque","Other"].map(m => <option key={m}>{m}</option>)}
                </select>
              </div>
              <div>
                <label className={labelCls}>Against</label>
                <select data-testid="sp-against" value={draft.against} onChange={(e) => setDraft({ ...draft, against: e.target.value })} className={inputCls}>
                  <option value="advance">Advance</option>
                  <option value="trip">Trip / Freight</option>
                  <option value="outstanding">Outstanding Balance</option>
                  <option value="other">Other</option>
                </select>
              </div>
              <div>
                <label className={labelCls}>Ref / Txn No.</label>
                <input data-testid="sp-ref" value={draft.ref_no} onChange={(e) => setDraft({ ...draft, ref_no: e.target.value })} className={inputCls} />
              </div>
              <div>
                <label className={labelCls}>LR / Trip No.</label>
                <input data-testid="sp-lr" value={draft.lr_number} onChange={(e) => setDraft({ ...draft, lr_number: e.target.value })} className={inputCls} placeholder="Optional" />
              </div>
              <div className="md:col-span-2">
                <label className={labelCls}>Remarks</label>
                <input data-testid="sp-remarks" value={draft.remarks} onChange={(e) => setDraft({ ...draft, remarks: e.target.value })} className={inputCls} />
              </div>
            </div>
            <div className="mt-3 text-right">
              <button data-testid="sp-add-btn" onClick={() => { if (!draft.amount || Number(draft.amount) <= 0) { toast.error("Enter amount"); return; } add.mutate(); }}
                className="px-6 py-2 text-xs uppercase tracking-wider font-bold bg-emerald-600 text-white rounded-sm hover:bg-emerald-700">
                + Record Payment
              </button>
            </div>
          </div>

          {/* Payments list */}
          <div className="border border-zinc-200 rounded-sm overflow-hidden bg-white">
            <table className="w-full text-sm">
              <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-wider">
                <tr>
                  <th className="text-left px-3 py-2">Date</th>
                  <th className="text-left px-3 py-2">Mode</th>
                  <th className="text-left px-3 py-2">Against</th>
                  <th className="text-left px-3 py-2">Ref / LR</th>
                  <th className="text-left px-3 py-2">Remarks</th>
                  <th className="text-right px-3 py-2">Amount</th>
                  <th className="w-10"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {isLoading && <tr><td colSpan={7} className="px-3 py-10 text-center text-zinc-400">Loading…</td></tr>}
                {!isLoading && pays.length === 0 && <tr><td colSpan={7} className="px-3 py-10 text-center text-zinc-400">No payments</td></tr>}
                {pays.map(p => (
                  <tr key={p.id} data-testid={`sp-row-${p.id}`} className="hover:bg-amber-50">
                    <td className="px-3 py-2 font-mono">{p.date}</td>
                    <td className="px-3 py-2">{p.mode}</td>
                    <td className="px-3 py-2 capitalize">{p.against}</td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {p.ref_no && <div>{p.ref_no}</div>}
                      {p.lr_number && <div className="text-zinc-500">{p.lr_number}</div>}
                    </td>
                    <td className="px-3 py-2 text-zinc-600 italic">{p.remarks || "—"}</td>
                    <td className="px-3 py-2 text-right font-mono font-bold">{fmtCurrency(p.amount)}</td>
                    <td className="px-3 py-2 text-center">
                      <button data-testid={`sp-del-${p.id}`} onClick={() => setDeletingId(p.id)} className="text-rose-600 hover:bg-rose-50 rounded p-1"><Trash2 size={13}/></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Delete-with-reason modal */}
      {deletingId && (
        <div className="fixed inset-0 z-50 bg-zinc-950/50 flex items-center justify-center p-4" onClick={() => setDeletingId(null)}>
          <div className="bg-white rounded-sm border border-zinc-200 max-w-md w-full p-5" onClick={(e) => e.stopPropagation()} data-testid="sp-delete-modal">
            <div className="text-lg font-bold mb-3">Delete Payment</div>
            <label className={labelCls}>Reason (mandatory)</label>
            <textarea data-testid="sp-delete-reason" value={deleteReason} onChange={(e) => setDeleteReason(e.target.value)} className={inputCls} rows={3} placeholder="Why is this payment being deleted?" />
            <div className="flex gap-2 justify-end mt-3">
              <button onClick={() => setDeletingId(null)} className="px-3 py-2 text-xs uppercase font-bold border border-zinc-300 rounded-sm">Cancel</button>
              <button data-testid="sp-confirm-delete" onClick={() => { if (deleteReason.trim().length < 3) { toast.error("Reason must be ≥3 chars"); return; } del.mutate({ pid: deletingId, reason: deleteReason }); }}
                className="px-4 py-2 text-xs uppercase font-bold bg-rose-600 text-white rounded-sm hover:bg-rose-700">Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ================= Statement / Ledger Tab ================= */
function SupplierStatement() {
  const today = new Date();
  const fmt = (d) => d.toISOString().slice(0, 10);
  const [sid, setSid] = useState("");
  const [start, setStart] = useState(fmt(new Date(today.getFullYear(), today.getMonth(), 1)));
  const [end, setEnd] = useState(fmt(today));
  const [filterVeh, setFilterVeh] = useState("");
  const [filterLR, setFilterLR] = useState("");
  const [filterType, setFilterType] = useState("all");

  const { data, isLoading } = useQuery({
    queryKey: ["supplier-ledger", sid, start, end], enabled: !!sid,
    queryFn: async () => (await api.get(`/suppliers/${sid}/ledger`, { params: { start, end } })).data,
  });

  // Client-side filter (keeps single-source-of-truth on backend, but per user's Phase 2 spec)
  const filteredEntries = useMemo(() => {
    if (!data) return [];
    return data.entries.filter((e) => {
      if (filterType !== "all" && e.type !== filterType && !(filterType === "payment" && e.type.startsWith("payment"))) return false;
      if (filterVeh && !(e.vehicle_number || "").toLowerCase().includes(filterVeh.toLowerCase())) return false;
      if (filterLR && !(e.lr_number || "").toLowerCase().includes(filterLR.toLowerCase())) return false;
      return true;
    });
  }, [data, filterType, filterVeh, filterLR]);

  const suppliers = (useSuppliers().data || []);
  const supName = suppliers.find(s => s.id === sid)?.name || "";
  const downloadPdf = async () => {
    if (!supName) return;
    const resp = await api.get("/reports/supplier-statement.pdf", {
      params: { supplier_name: supName, start, end }, responseType: "blob",
    });
    const url = URL.createObjectURL(new Blob([resp.data], { type: "application/pdf" }));
    const a = document.createElement("a"); a.href = url;
    a.download = `supplier_statement_${supName.replace(/\s+/g, "_")}_${start}_${end}.pdf`;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  };
  const shareWa = async () => {
    if (!supName) return;
    try {
      const { data: r } = await api.post("/reports/supplier-statement/share", null, {
        params: { supplier_name: supName, start, end },
      });
      window.open(r.whatsapp_url, "_blank", "noopener");
      if (!r.supplier_mobile_available) toast.info(`No mobile on file for ${supName}`);
      else toast.success(`WhatsApp ready — ${r.supplier_mobile}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Share failed");
    }
  };

  return (
    <div className="space-y-3" data-testid="sup-statement">
      <div className="grid grid-cols-1 md:grid-cols-7 gap-3 items-end bg-zinc-50 border border-zinc-200 rounded-sm p-4">
        <div className="md:col-span-2">
          <label className={labelCls}>Supplier</label>
          <SupplierPicker value={sid} onChange={setSid} testid="sup-led-picker" />
        </div>
        <div>
          <label className={labelCls}>From</label>
          <input data-testid="sup-led-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>To</label>
          <input data-testid="sup-led-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Vehicle No.</label>
          <input data-testid="sup-led-filter-veh" value={filterVeh} onChange={(e) => setFilterVeh(e.target.value)} className={inputCls} placeholder="Filter…" />
        </div>
        <div>
          <label className={labelCls}>LR / Trip No.</label>
          <input data-testid="sup-led-filter-lr" value={filterLR} onChange={(e) => setFilterLR(e.target.value)} className={inputCls} placeholder="Filter…" />
        </div>
        <div>
          <label className={labelCls}>Type</label>
          <select data-testid="sup-led-filter-type" value={filterType} onChange={(e) => setFilterType(e.target.value)} className={inputCls}>
            <option value="all">All</option>
            <option value="opening">Opening</option>
            <option value="trip_freight">Trip Freight</option>
            <option value="trip_advance">Advance</option>
            <option value="trip_diesel">Diesel</option>
            <option value="cust_diesel_adj">Cust. Diesel Adj</option>
            <option value="trip_shortage">Shortage</option>
            <option value="trip_recovery">Recovery</option>
            <option value="trip_bonus">Bonus</option>
            <option value="payment">Payments</option>
          </select>
        </div>
        <div className="md:col-span-7 flex flex-wrap gap-2">
          <button type="button" onClick={() => { const d = new Date(today.getFullYear(), today.getMonth(), 1); setStart(fmt(d)); setEnd(fmt(today)); }} className="px-3 py-1.5 text-[10px] uppercase font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100">This Month</button>
          <button type="button" onClick={() => { const y = today.getMonth()===0 ? today.getFullYear()-1 : today.getFullYear(); const m = today.getMonth()===0 ? 11 : today.getMonth()-1; setStart(fmt(new Date(y,m,1))); setEnd(fmt(new Date(y,m+1,0))); }} className="px-3 py-1.5 text-[10px] uppercase font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100">Last Month</button>
          {sid && (
            <div className="ml-auto flex gap-2">
              <button data-testid="sup-led-pdf" onClick={downloadPdf} className="inline-flex items-center gap-1 px-3 py-1.5 text-[10px] uppercase font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100"><Download size={12}/> PDF</button>
              <button data-testid="sup-led-print" onClick={() => window.print()} className="inline-flex items-center gap-1 px-3 py-1.5 text-[10px] uppercase font-bold border border-zinc-300 rounded-sm hover:bg-zinc-100"><Printer size={12}/> Print</button>
              <button data-testid="sup-led-wa" onClick={shareWa} className="inline-flex items-center gap-1 px-3 py-1.5 text-[10px] uppercase font-bold bg-emerald-600 text-white rounded-sm hover:bg-emerald-700"><MessageCircle size={12}/> WhatsApp</button>
            </div>
          )}
        </div>
      </div>

      {sid && data && (
        <div className="border border-zinc-200 rounded-sm bg-white">
          <div className="px-4 py-3 border-b border-zinc-200">
            <div className="text-lg font-bold">{data.supplier.name}</div>
            <div className="text-[11px] text-zinc-500">{filteredEntries.length} of {data.entries.length} entries · {start} → {end}</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-zinc-100 text-[10px] uppercase tracking-wider text-zinc-600">
                <tr>
                  <th className="text-left px-3 py-2">Date</th>
                  <th className="text-left px-3 py-2">Particulars</th>
                  <th className="text-left px-3 py-2">LR / Vehicle</th>
                  <th className="text-left px-3 py-2">Ref</th>
                  <th className="text-right px-3 py-2">Debit</th>
                  <th className="text-right px-3 py-2">Credit</th>
                  <th className="text-right px-3 py-2">Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 font-mono">
                {isLoading && <tr><td colSpan={7} className="px-3 py-10 text-center text-zinc-400">Loading…</td></tr>}
                {!isLoading && filteredEntries.map((e, i) => (
                  <tr key={i} data-testid={`sup-led-row-${i}`} className={e.type === "opening" ? "bg-zinc-50 font-bold" : ""}>
                    <td className="px-3 py-1.5">{e.type === "opening" ? "Opening" : e.date}</td>
                    <td className="px-3 py-1.5">{e.particulars}</td>
                    <td className="px-3 py-1.5 text-zinc-500 text-xs">
                      {e.lr_number && <div>{e.lr_number}</div>}
                      {e.vehicle_number && <div className="text-zinc-400">{e.vehicle_number}</div>}
                    </td>
                    <td className="px-3 py-1.5 text-zinc-500 text-xs">{e.ref_no || "—"}</td>
                    <td className="px-3 py-1.5 text-right">{e.debit ? fmtCurrency(e.debit) : "—"}</td>
                    <td className="px-3 py-1.5 text-right">{e.credit ? fmtCurrency(e.credit) : "—"}</td>
                    <td className={`px-3 py-1.5 text-right font-bold ${e.balance < 0 ? "text-emerald-800" : ""}`}>{fmtCurrency(e.balance)}</td>
                  </tr>
                ))}
                {!isLoading && (
                  <tr className="bg-amber-50 font-bold border-t-2 border-zinc-950">
                    <td colSpan={4} className="px-3 py-2 text-right uppercase text-[10px]">Total (all)</td>
                    <td className="px-3 py-2 text-right">{fmtCurrency(data.totals.debit)}</td>
                    <td className="px-3 py-2 text-right">{fmtCurrency(data.totals.credit)}</td>
                    <td className="px-3 py-2 text-right" data-testid="sup-led-closing">
                      {fmtCurrency(Math.abs(data.totals.closing_balance))} {data.totals.closing_type === "advance" ? "Cr" : "Dr"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ================= Outstanding Tab ================= */
function SupplierOutstanding() {
  const { data, isLoading } = useQuery({
    queryKey: ["suppliers-dashboard"],
    queryFn: async () => (await api.get("/suppliers-dashboard")).data,
  });
  const rows = data?.suppliers?.filter(s => s.outstanding_payable > 0) || [];
  return (
    <div className="space-y-3" data-testid="sup-outstanding">
      {isLoading ? (
        <div className="text-sm text-zinc-500 text-center py-10">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="text-sm text-zinc-500 text-center py-10 border border-dashed border-zinc-300 rounded-sm">No outstanding payables</div>
      ) : (
        <div className="border border-zinc-200 rounded-sm overflow-hidden bg-white">
          <table className="w-full text-sm">
            <thead className="bg-zinc-950 text-white text-[10px] uppercase tracking-wider">
              <tr>
                <th className="text-left px-3 py-2">Supplier</th>
                <th className="text-left px-3 py-2">Mobile</th>
                <th className="text-right px-3 py-2">Outstanding</th>
                <th className="text-center px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 font-mono">
              {rows.map(s => (
                <tr key={s.supplier_id} data-testid={`sup-out-${s.supplier_id}`} className="hover:bg-amber-50">
                  <td className="px-3 py-2 font-bold">{s.supplier_name}</td>
                  <td className="px-3 py-2 text-xs">{s.mobile || "—"}</td>
                  <td className="px-3 py-2 text-right font-bold text-rose-700">{fmtCurrency(s.outstanding_payable)}</td>
                  <td className="px-3 py-2 text-center text-[10px]">{s.is_active ? "ACTIVE" : "INACTIVE"}</td>
                </tr>
              ))}
              <tr className="bg-amber-50 font-bold border-t-2 border-zinc-950">
                <td colSpan={2} className="px-3 py-2 uppercase text-[10px]">Total</td>
                <td className="px-3 py-2 text-right" data-testid="sup-out-total">{fmtCurrency(data.totals.total_outstanding)}</td>
                <td></td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ================= P&L Tab — link to Reports > Supplier P&L ================= */
function SupplierPLTab() {
  return (
    <div className="text-center py-16 border border-dashed border-zinc-300 rounded-sm">
      <TrendingUp className="mx-auto text-amber-600 mb-3" size={32} />
      <div className="text-sm text-zinc-500">Deep P&L reporting lives under <Link to="/reports/supplier-pl" className="underline font-bold">Reports → Supplier P&L</Link> — with margin per supplier and the printable Statement.</div>
    </div>
  );
}
