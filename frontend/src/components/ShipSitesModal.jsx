// Iter66 · Phase B — Ship-To Sites manager modal.
// Opened per-customer from Customers.jsx.
// Backend: nested under /api/customers/{cid}/ship-sites.
import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, MapPin, Star, X, AlertTriangle, CheckCircle2 } from "lucide-react";
import { StateSelect, INDIA_STATES } from "@/lib/states";

const EMPTY = {
  site_name: "", address: "", gstin: "", state: "", state_code: "",
  pincode: "", contact_person: "", phone: "",
  is_default: false, is_active: true,
};

const ic = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";
const lbl = "text-[10px] font-bold uppercase tracking-wider text-zinc-500";

// Iter127c-invoice-shipto v3.2 (Feb 2026 · user-approved) — GSTIN → State
// auto-derivation. The first two digits of a well-formed GSTIN carry the
// Indian State Code; look up the name from the canonical INDIA_STATES map.
// Returns { state_code, state } or { "", "" } when GSTIN is blank/invalid.
const _GSTIN_RE = /^([0-9]{2})([A-Z]{5}[0-9]{4}[A-Z])([0-9A-Z])Z([0-9A-Z])$/;
function deriveStateFromGstin(gstin) {
  const g = (gstin || "").trim().replace(/^\s*(?:gstin|gstn|gst)\b[\s:.-]*/i, "").replace(/\s+/g, "").toUpperCase();
  const m = g.match(_GSTIN_RE);
  if (!m) return { state_code: "", state: "" };
  const code = m[1];
  const hit = INDIA_STATES.find((s) => s.code === code);
  return hit ? { state_code: code, state: hit.name } : { state_code: "", state: "" };
}

export default function ShipSitesModal({ customer, onClose }) {
  const qc = useQueryClient();
  const [form, setForm] = React.useState(EMPTY);
  const [editing, setEditing] = React.useState(null);
  const [showForm, setShowForm] = React.useState(false);

  const { data } = useQuery({
    queryKey: ["ship-sites", customer.id],
    queryFn: async () => (await api.get(`/customers/${customer.id}/ship-sites`)).data,
  });
  const sites = data?.items || [];

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["ship-sites", customer.id] });
    qc.invalidateQueries({ queryKey: ["customers"] });
    qc.invalidateQueries({ queryKey: ["customers-paginated"] });
    qc.invalidateQueries({ queryKey: ["customer-detail"] });
  };
  const save = useMutation({
    mutationFn: async () => {
      if (editing?.id) {
        return (await api.put(`/customers/${customer.id}/ship-sites/${editing.id}`, form)).data;
      }
      return (await api.post(`/customers/${customer.id}/ship-sites`, form)).data;
    },
    onSuccess: () => { toast.success(editing ? "Site updated" : "Site added"); invalidate(); setShowForm(false); setEditing(null); setForm(EMPTY); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });
  const del = useMutation({
    mutationFn: async (sid) => (await api.delete(`/customers/${customer.id}/ship-sites/${sid}`)).data,
    onSuccess: () => { toast.success("Site deactivated"); invalidate(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/45 backdrop-blur-sm p-4" data-testid="ship-sites-modal">
      <div className="bg-white w-full max-w-3xl border border-zinc-950 rounded-sm shadow-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
          <h3 className="font-bold flex items-center gap-2"><MapPin size={16} /> Ship-To Sites — <span className="text-zinc-600 font-normal">{customer.name}</span></h3>
          <button onClick={onClose} data-testid="close-ship-sites-modal" className="text-zinc-500 hover:text-zinc-950 text-lg leading-none">×</button>
        </div>
        <div className="p-5 overflow-y-auto space-y-4">
          <div className="text-xs text-zinc-600 bg-indigo-50 border border-indigo-200 p-2 rounded-sm">
            A customer can have multiple ship-to / consignee sites (project sites, depots, unloading points).
            Add each once, then simply pick the site when creating a Trip — the address, GSTIN and state auto-fill the Invoice.
            Deleting a site soft-deactivates it — historical Trips referencing it stay intact.
          </div>
          {!showForm && (
            <div className="flex justify-end">
              <button data-testid="add-ship-site-btn" onClick={() => { setEditing(null); setForm(EMPTY); setShowForm(true); }}
                className="inline-flex items-center gap-1 text-xs px-3 py-1.5 uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800">
                <Plus size={12} /> Add Ship-To Site
              </button>
            </div>
          )}
          {showForm && (
            <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="border border-zinc-300 rounded-sm p-4 bg-zinc-50" data-testid="ship-site-form">
              <div className="grid grid-cols-2 gap-3">
                <F label="Site / Consignee Name *"><input required data-testid="site-name" value={form.site_name} onChange={(e) => setForm({ ...form, site_name: e.target.value })} className={ic} placeholder="Vijayawada Plant" /></F>
                <F label="Contact Person"><input data-testid="site-contact" value={form.contact_person} onChange={(e) => setForm({ ...form, contact_person: e.target.value })} className={ic} /></F>
                <F label="Phone"><input data-testid="site-phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className={ic} /></F>
                <F label="GSTIN (if different from billing)">
                  <input
                    data-testid="site-gstin"
                    value={form.gstin}
                    onChange={(e) => {
                      const raw = e.target.value.toUpperCase();
                      // v3.2 · Auto-derive State + State Code when GSTIN becomes
                      // well-formed. NEVER silently overwrite a manually-entered
                      // conflicting value — see the warning banner below.
                      const derived = deriveStateFromGstin(raw);
                      setForm((f) => {
                        const next = { ...f, gstin: raw };
                        if (derived.state_code) {
                          if (!f.state_code) next.state_code = derived.state_code;
                          if (!f.state)      next.state      = derived.state;
                        }
                        return next;
                      });
                    }}
                    className={ic}
                    placeholder="e.g. 36AAUFM1425D1ZC"
                  />
                  {(() => {
                    // Inline validation + derivation UX.
                    if (!form.gstin) return null;
                    const derived = deriveStateFromGstin(form.gstin);
                    if (!derived.state_code) {
                      return (
                        <div data-testid="site-gstin-invalid" className="mt-1 flex items-start gap-1 text-[10px] text-rose-700">
                          <AlertTriangle size={11} className="mt-0.5 flex-shrink-0" />
                          <span>GSTIN format looks invalid — State will not be auto-derived.</span>
                        </div>
                      );
                    }
                    const conflict = (
                      (form.state_code && form.state_code !== derived.state_code) ||
                      (form.state && form.state !== derived.state)
                    );
                    if (conflict) {
                      return (
                        <div data-testid="site-gstin-state-conflict" className="mt-1 flex items-start gap-1 text-[10px] text-amber-800 bg-amber-50 border border-amber-300 px-2 py-1 rounded-sm">
                          <AlertTriangle size={11} className="mt-0.5 flex-shrink-0" />
                          <span>
                            GSTIN indicates <b>{derived.state}</b> (code {derived.state_code}), but you've
                            entered <b>{form.state || "—"}</b> (code {form.state_code || "—"}). Please verify.
                            <button
                              type="button"
                              data-testid="site-gstin-accept-derived"
                              onClick={() => setForm((f) => ({ ...f, state: derived.state, state_code: derived.state_code }))}
                              className="ml-1 underline font-semibold hover:text-amber-950"
                            >Use {derived.state}</button>
                          </span>
                        </div>
                      );
                    }
                    return (
                      <div data-testid="site-gstin-derived" className="mt-1 flex items-center gap-1 text-[10px] text-emerald-700">
                        <CheckCircle2 size={11} />
                        <span>State auto-derived from GSTIN: <b>{derived.state}</b> (code {derived.state_code}).</span>
                      </div>
                    );
                  })()}
                </F>
                <F label="State"><StateSelect value={form.state} onChange={(v) => setForm({ ...form, state: v })} dataTestId="site-state" className={ic + " bg-white"} /></F>
                <F label="State Code"><input data-testid="site-state-code" value={form.state_code} onChange={(e) => setForm({ ...form, state_code: e.target.value })} className={ic} placeholder="37" /></F>
                <F label="PIN Code"><input data-testid="site-pincode" value={form.pincode} onChange={(e) => setForm({ ...form, pincode: e.target.value })} className={ic} /></F>
                <div className="flex items-end">
                  <label className="inline-flex items-center gap-2 cursor-pointer text-sm">
                    <input data-testid="site-is-default" type="checkbox" checked={!!form.is_default} onChange={(e) => setForm({ ...form, is_default: e.target.checked })} className="h-4 w-4 accent-amber-600" />
                    <Star size={14} className={form.is_default ? "text-amber-500" : "text-zinc-400"} />
                    <span className={form.is_default ? "text-amber-800 font-semibold" : "text-zinc-500"}>{form.is_default ? "Default for this customer" : "Mark as default"}</span>
                  </label>
                </div>
                <div className="col-span-2">
                  <F label="Site Address"><textarea rows={2} data-testid="site-address" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} className={ic} placeholder="NH-16, Kondapalli SEZ, Krishna Dt., AP 521228" /></F>
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-3">
                <button type="button" onClick={() => { setShowForm(false); setEditing(null); setForm(EMPTY); }} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
                <button type="submit" data-testid="save-ship-site-btn" disabled={save.isPending} className="px-4 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm disabled:opacity-50">{save.isPending ? "Saving…" : (editing ? "Update Site" : "Add Site")}</button>
              </div>
            </form>
          )}
          <table className="w-full text-sm" data-testid="ship-sites-table">
            <thead className="text-[10px] uppercase tracking-wider text-zinc-500 border-b border-zinc-200 bg-zinc-50">
              <tr>
                <th className="text-left px-3 py-2">Site Name</th>
                <th className="text-left px-3 py-2">Address</th>
                <th className="text-left px-3 py-2">State</th>
                <th className="text-left px-3 py-2">GSTIN</th>
                <th className="text-center px-3 py-2">Default</th>
                <th className="text-center px-3 py-2">Status</th>
                <th className="text-right px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {sites.length === 0 && (
                <tr><td colSpan={7} className="text-center py-8 text-zinc-400" data-testid="ship-sites-empty">No sites yet. Add one to enable auto-populated Ship-To on Invoices.</td></tr>
              )}
              {sites.map((s) => (
                <tr key={s.id} className={`border-b border-zinc-100 ${s.is_active === false ? "opacity-60" : ""}`} data-testid={`ship-site-row-${s.id}`}>
                  <td className="px-3 py-2 font-semibold">{s.site_name}</td>
                  <td className="px-3 py-2 text-xs text-zinc-600 max-w-[240px] truncate" title={s.address}>{s.address || "—"}</td>
                  <td className="px-3 py-2 text-xs">{s.state || "—"}{s.pincode ? ` · ${s.pincode}` : ""}</td>
                  <td className="px-3 py-2 font-mono text-xs">{s.gstin || "—"}</td>
                  <td className="px-3 py-2 text-center">{s.is_default ? <Star size={14} className="inline text-amber-500 fill-amber-500" /> : <span className="text-zinc-300">—</span>}</td>
                  <td className="px-3 py-2 text-center">
                    {s.is_active === false ? <span className="inline-block px-2 py-0.5 rounded-full bg-zinc-100 text-zinc-600 border border-zinc-300 text-[10px] uppercase tracking-wider font-bold">Inactive</span> : <span className="inline-block px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 text-[10px] uppercase tracking-wider font-bold">Active</span>}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button data-testid={`edit-site-${s.id}`} onClick={() => { setEditing(s); setForm({ ...EMPTY, ...s }); setShowForm(true); }} className="text-xs px-2 py-1 border border-zinc-200 rounded-sm mr-2 hover:bg-zinc-950 hover:text-white"><Pencil size={12} /></button>
                    {s.is_active !== false && (
                      <button data-testid={`delete-site-${s.id}`} onClick={() => { if (window.confirm(`Deactivate ship-to site "${s.site_name}"?`)) del.mutate(s.id); }} className="text-xs px-2 py-1 border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-600 hover:text-white"><Trash2 size={12} /></button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function F({ label, children }) {
  return (
    <div>
      <label className={lbl}>{label}</label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
