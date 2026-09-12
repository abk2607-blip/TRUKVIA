import React, { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errMsg } from "@/api";
import { toast } from "sonner";
import { Plus, Pencil, X, Search, Wrench, BookOpen } from "lucide-react";
import { StateSelect } from "@/lib/states";
import { useAuth } from "@/context/AuthContext";
import BankAccountsSection from "@/components/BankAccountsSection";

/**
 * Iter133 · Turn 3 · Slice A — Vendors Master.
 * Backend: GET/POST /api/vendors  ·  PUT /api/vendors/{vid}  ·
 *          POST /api/vendors/{vid}/reactivate  ·  DELETE /api/vendors/{vid}
 * Deep-link Ledger → /vendor-ledger/:id (already shipped in PartyLedger.jsx).
 */
const EMPTY = {
  name: "",
  contact_person: "",
  mobile: "",
  alt_mobile: "",
  address: "",
  city: "",
  state: "",
  gst_in: "",
  pan: "",
  msme_number: "",
  bank_name: "",
  account_number: "",
  ifsc: "",
  branch: "",
  payment_terms: "",
  opening_balance: 0,
  opening_balance_type: "payable",
  remarks: "",
  is_active: true,
};

export default function Vendors() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const isAdmin = ["owner", "admin"].includes((user?.effective_role || "").toLowerCase());
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [q, setQ] = useState("");

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ["vendors"],
    queryFn: async () => (await api.get("/vendors")).data,
  });

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return rows;
    return rows.filter((v) =>
      [v.name, v.mobile, v.contact_person, v.gst_in, v.city]
        .filter(Boolean)
        .some((x) => String(x).toLowerCase().includes(s))
    );
  }, [rows, q]);

  const save = useMutation({
    mutationFn: async () => {
      const body = { ...form, opening_balance: Number(form.opening_balance || 0) };
      return editing
        ? (await api.put(`/vendors/${editing.id}`, { ...editing, ...body })).data
        : (await api.post("/vendors", body)).data;
    },
    onSuccess: () => {
      toast.success(editing ? "Vendor updated" : "Vendor added");
      qc.invalidateQueries({ queryKey: ["vendors"] });
      setOpen(false); setEditing(null); setForm(EMPTY);
    },
    onError: (e) => toast.error(errMsg(e, "Save failed")),
  });

  const deact = useMutation({
    mutationFn: async ({ id, reason }) =>
      (await api.delete(`/vendors/${id}`, { params: { reason } })).data,
    onSuccess: () => {
      toast.success("Vendor deactivated");
      qc.invalidateQueries({ queryKey: ["vendors"] });
    },
    onError: (e) => toast.error(errMsg(e, "Deactivate failed")),
  });
  const react = useMutation({
    mutationFn: async (id) => (await api.post(`/vendors/${id}/reactivate`, {})).data,
    onSuccess: () => {
      toast.success("Vendor reactivated");
      qc.invalidateQueries({ queryKey: ["vendors"] });
    },
    onError: (e) => toast.error(errMsg(e, "Reactivate failed")),
  });

  const openNew = () => { setEditing(null); setForm(EMPTY); setOpen(true); };
  const openEdit = (v) => { setEditing(v); setForm({ ...EMPTY, ...v }); setOpen(true); };

  return (
    <div className="space-y-6" data-testid="vendors-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Master</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter flex items-center gap-2">
            <Wrench size={26} /> Vendors
          </h1>
          <div className="text-xs text-zinc-500 mt-1">Spare-parts / workshop vendors. Distinct from Suppliers (hired vehicle owners) and Mechanics (labour).</div>
        </div>
        <button data-testid="add-vendor-btn" onClick={openNew}
          className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2">
          <Plus size={14} /> Add Vendor
        </button>
      </header>

      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input data-testid="vendor-search"
            value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Search vendor name, mobile, GSTIN…"
            className="w-full border border-zinc-300 pl-9 pr-3 py-2 rounded-sm text-sm outline-none focus:border-zinc-950 bg-white" />
        </div>
        <div className="text-xs text-zinc-500" data-testid="vendor-count">
          {q ? `${filtered.length} matches` : `${rows.length} vendors`}
        </div>
      </div>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-x-auto">
        <table className="w-full text-sm" data-testid="vendors-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-3 py-2 font-semibold">Name</th>
              <th className="text-left px-3 py-2 font-semibold">Contact</th>
              <th className="text-left px-3 py-2 font-semibold">Mobile</th>
              <th className="text-left px-3 py-2 font-semibold">GSTIN</th>
              <th className="text-left px-3 py-2 font-semibold">City / State</th>
              <th className="text-center px-3 py-2 font-semibold">Status</th>
              <th className="text-right px-3 py-2 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && <tr><td colSpan={7} className="p-6 text-center text-zinc-400">Loading…</td></tr>}
            {!isLoading && filtered.length === 0 && (
              <tr><td colSpan={7} className="p-8 text-center text-zinc-400">
                {q ? `No vendors match “${q}”.` : "No vendors yet."}
              </td></tr>
            )}
            {filtered.map((v) => (
              <tr key={v.id} data-testid={`vendor-row-${v.id}`} className="border-t border-zinc-100 hover:bg-zinc-50">
                <td className="px-3 py-3 font-semibold">{v.name}</td>
                <td className="px-3 py-3 text-xs">{v.contact_person || "—"}</td>
                <td className="px-3 py-3 text-xs font-mono">{v.mobile || "—"}</td>
                <td className="px-3 py-3 text-xs font-mono">{v.gst_in || "—"}</td>
                <td className="px-3 py-3 text-xs">{[v.city, v.state].filter(Boolean).join(", ") || "—"}</td>
                <td className="px-3 py-3 text-center">
                  {v.is_active !== false ? (
                    <span data-testid={`vendor-status-${v.id}`} className="inline-block px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 text-[10px] uppercase font-bold">Active</span>
                  ) : (
                    <span data-testid={`vendor-status-${v.id}`} className="inline-block px-2 py-0.5 rounded-full bg-zinc-100 text-zinc-600 border border-zinc-300 text-[10px] uppercase font-bold">Inactive</span>
                  )}
                </td>
                <td className="px-3 py-3 text-right whitespace-nowrap">
                  <Link data-testid={`vendor-ledger-${v.id}`} to={`/vendor-ledger/${v.id}`}
                    className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-indigo-300 text-indigo-800 rounded-sm mr-2 hover:bg-indigo-50">
                    <BookOpen size={12} /> Ledger
                  </Link>
                  <button data-testid={`edit-vendor-${v.id}`} onClick={() => openEdit(v)}
                    className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-zinc-200 rounded-sm mr-2 hover:bg-zinc-950 hover:text-white">
                    <Pencil size={12} /> Edit
                  </button>
                  {isAdmin && v.is_active !== false && (
                    <button data-testid={`deactivate-vendor-${v.id}`}
                      onClick={() => {
                        const reason = window.prompt("Reason for deactivation:");
                        if (reason && reason.trim()) deact.mutate({ id: v.id, reason: reason.trim() });
                      }}
                      className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-50">
                      Deactivate
                    </button>
                  )}
                  {isAdmin && v.is_active === false && (
                    <button data-testid={`reactivate-vendor-${v.id}`} onClick={() => react.mutate(v.id)}
                      className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-emerald-200 text-emerald-700 rounded-sm hover:bg-emerald-50">
                      Reactivate
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/50 p-4" data-testid="vendor-modal">
          <div className="bg-white w-full max-w-2xl max-h-[90vh] flex flex-col border rounded-sm">
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <h3 className="font-bold">{editing ? "Edit Vendor" : "New Vendor"}</h3>
              <button onClick={() => setOpen(false)} data-testid="vendor-modal-close"><X size={18} /></button>
            </div>
            <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="flex flex-col flex-1 min-h-0">
              <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-3 overflow-y-auto flex-1">
                <F label="Name *">
                  <input required data-testid="vendor-name" value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })} className={ic} />
                </F>
                <F label="Contact Person">
                  <input data-testid="vendor-contact-person" value={form.contact_person}
                    onChange={(e) => setForm({ ...form, contact_person: e.target.value })} className={ic} />
                </F>
                <F label="Mobile">
                  <input data-testid="vendor-mobile" value={form.mobile}
                    onChange={(e) => setForm({ ...form, mobile: e.target.value })} className={ic} />
                </F>
                <F label="Alt Mobile">
                  <input data-testid="vendor-alt-mobile" value={form.alt_mobile}
                    onChange={(e) => setForm({ ...form, alt_mobile: e.target.value })} className={ic} />
                </F>
                <F label="GSTIN">
                  <input data-testid="vendor-gstin" value={form.gst_in}
                    onChange={(e) => setForm({ ...form, gst_in: e.target.value.toUpperCase() })} className={ic} />
                </F>
                <F label="PAN">
                  <input data-testid="vendor-pan" value={form.pan}
                    onChange={(e) => setForm({ ...form, pan: e.target.value.toUpperCase() })} className={ic} />
                </F>
                <F label="City">
                  <input data-testid="vendor-city" value={form.city}
                    onChange={(e) => setForm({ ...form, city: e.target.value })} className={ic} />
                </F>
                <F label="State">
                  <StateSelect data-testid="vendor-state" value={form.state}
                    onChange={(v) => setForm({ ...form, state: v })} />
                </F>
                <div className="md:col-span-2">
                  <F label="Address">
                    <input data-testid="vendor-address" value={form.address}
                      onChange={(e) => setForm({ ...form, address: e.target.value })} className={ic} />
                  </F>
                </div>
                <F label="Payment Terms">
                  <input data-testid="vendor-payment-terms" value={form.payment_terms}
                    onChange={(e) => setForm({ ...form, payment_terms: e.target.value })} className={ic}
                    placeholder="e.g. Net 30" />
                </F>
                <F label="MSME Number">
                  <input data-testid="vendor-msme" value={form.msme_number}
                    onChange={(e) => setForm({ ...form, msme_number: e.target.value })} className={ic} />
                </F>
                <F label="Opening Balance">
                  <input data-testid="vendor-opening-balance" type="number" step="0.01" min="0"
                    value={form.opening_balance}
                    onChange={(e) => setForm({ ...form, opening_balance: e.target.value })} className={ic} />
                </F>
                <F label="Opening Type">
                  <select data-testid="vendor-opening-type" value={form.opening_balance_type}
                    onChange={(e) => setForm({ ...form, opening_balance_type: e.target.value })} className={ic}>
                    <option value="payable">Payable (owed to vendor)</option>
                    <option value="advance">Advance (paid to vendor)</option>
                  </select>
                </F>
                <F label="Bank Name">
                  <input data-testid="vendor-bank-name" value={form.bank_name}
                    onChange={(e) => setForm({ ...form, bank_name: e.target.value })} className={ic} />
                </F>
                <F label="Account Number">
                  <input data-testid="vendor-account-number" value={form.account_number}
                    onChange={(e) => setForm({ ...form, account_number: e.target.value })} className={ic} />
                </F>
                <F label="IFSC">
                  <input data-testid="vendor-ifsc" value={form.ifsc}
                    onChange={(e) => setForm({ ...form, ifsc: e.target.value.toUpperCase() })} className={ic} />
                </F>
                <F label="Branch">
                  <input data-testid="vendor-branch" value={form.branch}
                    onChange={(e) => setForm({ ...form, branch: e.target.value })} className={ic} />
                </F>
                <div className="md:col-span-2">
                  <BankAccountsSection kind="party" partyType="vendor" partyId={editing?.id || ""} />
                </div>
                <div className="md:col-span-2">
                  <F label="Remarks">
                    <input data-testid="vendor-remarks" value={form.remarks}
                      onChange={(e) => setForm({ ...form, remarks: e.target.value })} className={ic} />
                  </F>
                </div>
              </div>
              <div className="px-5 py-3 border-t bg-white flex justify-end gap-2 sticky bottom-0">
                <button type="button" onClick={() => setOpen(false)}
                  className="px-4 py-2 text-xs uppercase tracking-wider border rounded-sm">Cancel</button>
                <button type="submit" data-testid="save-vendor-btn" disabled={save.isPending || !form.name}
                  className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
                  {save.isPending ? "Saving…" : "Save"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

const ic = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm outline-none focus:border-zinc-950 bg-white";
function F({ label, children }) {
  return (
    <div>
      <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">{label}</label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
