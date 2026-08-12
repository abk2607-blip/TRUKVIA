import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X, Truck, AlertTriangle, CheckCircle2, Users } from "lucide-react";
import FileAttachments from "@/components/FileAttachments";
import { StateSelect } from "@/lib/states";
import SearchableSelect from "@/components/SearchableSelect";
import { QuickAddSupplier } from "@/components/QuickAddModals";

const EMPTY = {
  vehicle_number: "", vehicle_type: "own", is_active: true,
  owner_name: "", owner_phone: "", owner_state: "",
  supplier_id: "", supplier_name: "", supplier_contact_person: "", supplier_mobile: "", supplier_state: "", supplier_gstin: "",
  make_model: "", capacity_tons: 0,
  rc_expiry: "", fc_expiry: "", insurance_expiry: "", permit_expiry: "", puc_expiry: "",
  remarks: "", notes: "",
};

const DOCS = [
  ["rc_expiry", "RC"],
  ["fc_expiry", "FC"],
  ["insurance_expiry", "Insurance"],
  ["permit_expiry", "Permit"],
  ["puc_expiry", "PUC"],
];

export default function Vehicles() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [showQaSupplier, setShowQaSupplier] = useState(false);

  const { data: vehicles = [] } = useQuery({
    queryKey: ["vehicles"],
    queryFn: async () => (await api.get("/vehicles")).data,
  });
  const { data: suppliers = [] } = useQuery({
    queryKey: ["suppliers"],
    queryFn: async () => (await api.get("/suppliers")).data,
  });

  const save = useMutation({
    mutationFn: async () => {
      const payload = { ...form, capacity_tons: Number(form.capacity_tons) };
      return editing
        ? (await api.put(`/vehicles/${editing.id}`, { ...editing, ...payload })).data
        : (await api.post("/vehicles", payload)).data;
    },
    onSuccess: () => {
      toast.success(editing ? "Vehicle updated" : "Vehicle added");
      qc.invalidateQueries({ queryKey: ["vehicles"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setOpen(false); setEditing(null); setForm(EMPTY);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const del = useMutation({
    mutationFn: async (id) => (await api.delete(`/vehicles/${id}`)).data,
    onSuccess: () => { toast.success("Deleted"); qc.invalidateQueries({ queryKey: ["vehicles"] }); },
  });

  const openEdit = (v) => { setEditing(v); setForm({ ...EMPTY, ...v }); setOpen(true); };
  const openNew = () => { setEditing(null); setForm(EMPTY); setOpen(true); };

  return (
    <div className="space-y-6" data-testid="vehicles-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Master</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">వాహనాలు</span>
            <span className="text-zinc-400"> · Vehicles</span>
          </h1>
        </div>
        <button data-testid="add-vehicle-btn" onClick={openNew} className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2">
          <Plus size={14} /> Add Vehicle
        </button>
      </header>

      <div className="border border-zinc-200 bg-white rounded-sm overflow-x-auto">
        <table className="w-full text-sm" data-testid="vehicles-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-3 py-2 font-semibold">Vehicle</th>
              <th className="text-left px-3 py-2 font-semibold">Type</th>
              <th className="text-left px-3 py-2 font-semibold">Owner / Supplier</th>
              <th className="text-left px-3 py-2 font-semibold">Make/Model</th>
              <th className="text-right px-3 py-2 font-semibold">Cap (T)</th>
              <th className="text-center px-3 py-2 font-semibold">Status</th>
              {DOCS.map(([, label]) => (
                <th key={label} className="text-left px-3 py-2 font-semibold">{label}</th>
              ))}
              <th className="text-right px-3 py-2 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {vehicles.map((v) => (
              <tr key={v.id} data-testid={`vehicle-row-${v.id}`} className="border-t border-zinc-100">
                <td className="px-3 py-3 font-mono font-bold flex items-center gap-2"><Truck size={14} className="text-zinc-400" /> {v.vehicle_number}</td>
                <td className="px-3 py-3 text-xs">
                  {v.vehicle_type === "supplier" ? (
                    <span data-testid={`vehicle-type-badge-${v.id}`} className="inline-block px-2 py-0.5 rounded-full bg-amber-50 text-amber-800 border border-amber-200 text-[10px] uppercase tracking-wider font-bold">Supplier</span>
                  ) : (
                    <span data-testid={`vehicle-type-badge-${v.id}`} className="inline-block px-2 py-0.5 rounded-full bg-sky-50 text-sky-800 border border-sky-200 text-[10px] uppercase tracking-wider font-bold">Own</span>
                  )}
                </td>
                <td className="px-3 py-3 text-xs" data-testid={`vehicle-owner-cell-${v.id}`}>
                  {v.vehicle_type === "supplier" ? (v.supplier_name || <span className="text-rose-600">— not linked</span>) : (v.owner_name || "—")}
                </td>
                <td className="px-3 py-3 text-xs">{v.make_model || "—"}</td>
                <td className="px-3 py-3 text-right font-mono">{Number(v.capacity_tons || 0).toFixed(1)}</td>
                <td className="px-3 py-3 text-center">
                  {v.is_active === false ? (
                    <span data-testid={`vehicle-status-${v.id}`} className="inline-block px-2 py-0.5 rounded-full bg-zinc-100 text-zinc-600 border border-zinc-300 text-[10px] uppercase tracking-wider font-bold">Inactive</span>
                  ) : (
                    <span data-testid={`vehicle-status-${v.id}`} className="inline-block px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 text-[10px] uppercase tracking-wider font-bold">Active</span>
                  )}
                </td>
                {DOCS.map(([field]) => {
                  const a = v.alerts?.[field];
                  return (
                    <td key={field} className="px-3 py-3 text-xs">
                      {a ? (
                        <ExpiryBadge alert={a} />
                      ) : <span className="text-zinc-400">—</span>}
                    </td>
                  );
                })}
                <td className="px-3 py-3 text-right whitespace-nowrap">
                  <button data-testid={`edit-vehicle-${v.id}`} onClick={() => openEdit(v)} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-zinc-200 rounded-sm mr-2 hover:bg-zinc-950 hover:text-white">
                    <Pencil size={12} /> Edit
                  </button>
                  <button data-testid={`delete-vehicle-${v.id}`} onClick={() => { if (window.confirm("Delete?")) del.mutate(v.id); }} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-50">
                    <Trash2 size={12} /> Delete
                  </button>
                </td>
              </tr>
            ))}
            {vehicles.length === 0 && (
              <tr><td colSpan={13} className="px-4 py-12 text-center text-zinc-400">No vehicles registered.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4" data-testid="vehicle-modal">
          <div className="bg-white w-full max-w-2xl max-h-[90vh] flex flex-col border border-zinc-950 rounded-sm">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200 flex-shrink-0">
              <h3 className="font-bold">{editing ? "Edit Vehicle" : "New Vehicle"}</h3>
              <button onClick={() => setOpen(false)}><X size={18} /></button>
            </div>
            <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="flex flex-col flex-1 min-h-0">
              <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-3 overflow-y-auto flex-1">
              <F label="Vehicle Number *"><input data-testid="vehicle-number" required value={form.vehicle_number} onChange={(e) => setForm({ ...form, vehicle_number: e.target.value.toUpperCase() })} className={ic} placeholder="AP16TA1234" /></F>
              <F label="Vehicle Type">
                <select data-testid="vehicle-type" value={form.vehicle_type} onChange={(e) => setForm({ ...form, vehicle_type: e.target.value })} className={ic}>
                  <option value="own">Own</option>
                  <option value="supplier">Supplier (Hired)</option>
                </select>
              </F>
              <F label="Owner Name"><input data-testid="vehicle-owner" value={form.owner_name} onChange={(e) => setForm({ ...form, owner_name: e.target.value })} className={ic} /></F>
              <F label="Owner Phone"><input data-testid="vehicle-owner-phone" value={form.owner_phone} onChange={(e) => setForm({ ...form, owner_phone: e.target.value })} className={ic} placeholder="For renewal reminders" /></F>
              {form.vehicle_type === "supplier" && (
                <>
                  <div className="md:col-span-2 border border-amber-200 bg-amber-50 rounded-sm p-3">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-amber-800 flex items-center gap-1"><Users size={12} /> Supplier · linked by ID (not free text) *</label>
                    <div className="mt-1 flex items-center gap-2">
                      <div className="flex-1">
                        <SearchableSelect
                          dataTestId="vehicle-supplier-picker"
                          value={form.supplier_id || ""}
                          onChange={(sid) => {
                            const s = suppliers.find((x) => x.id === sid);
                            setForm({
                              ...form,
                              supplier_id: sid,
                              supplier_name: s ? s.name : "",
                              supplier_contact_person: s?.contact_person || form.supplier_contact_person,
                              supplier_mobile: s?.mobile || form.supplier_mobile,
                              supplier_gstin: s?.gst_in || form.supplier_gstin,
                              supplier_state: s?.state || form.supplier_state,
                            });
                          }}
                          placeholder="Search supplier by name / phone / GSTIN…"
                          options={suppliers.map((s) => ({
                            value: s.id,
                            label: s.name,
                            meta: [s.mobile, s.gst_in].filter(Boolean).join(" · "),
                          }))}
                        />
                      </div>
                      <button
                        type="button"
                        data-testid="vehicle-quickadd-supplier-btn"
                        onClick={() => setShowQaSupplier(true)}
                        className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-1 whitespace-nowrap"
                      ><Plus size={12} /> New</button>
                    </div>
                    {!form.supplier_id && (
                      <div className="text-[10px] text-rose-700 mt-1 font-bold">
                        ⚠ Supplier ID is required for supplier vehicles. Linking by ID keeps the master consistent.
                      </div>
                    )}
                    {form.supplier_name && (
                      <div className="text-[10px] text-zinc-600 mt-2">
                        Linked to <span className="font-bold">{form.supplier_name}</span>
                        {form.supplier_mobile && <> · {form.supplier_mobile}</>}
                        {form.supplier_gstin && <> · {form.supplier_gstin}</>}
                      </div>
                    )}
                  </div>
                </>
              )}
              <F label="Make/Model"><input data-testid="vehicle-model" value={form.make_model} onChange={(e) => setForm({ ...form, make_model: e.target.value })} className={ic} placeholder="Tata LPT 3118" /></F>
              <F label="Capacity (Tons)"><input data-testid="vehicle-capacity" type="number" step="0.1" min="0" value={form.capacity_tons} onChange={(e) => setForm({ ...form, capacity_tons: e.target.value })} className={ic} /></F>
              <F label="Active Status">
                <div className="flex items-center gap-2 pt-2">
                  <label className="inline-flex items-center gap-2 cursor-pointer text-sm">
                    <input
                      data-testid="vehicle-is-active"
                      type="checkbox"
                      checked={form.is_active !== false}
                      onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                      className="h-4 w-4 accent-emerald-600"
                    />
                    <span className={form.is_active !== false ? "text-emerald-800 font-semibold" : "text-zinc-500"}>
                      {form.is_active !== false ? "Active — selectable for new Trips" : "Inactive — hidden from Trip picker"}
                    </span>
                  </label>
                </div>
              </F>
              <F label="Remarks"><input data-testid="vehicle-remarks" value={form.remarks} onChange={(e) => setForm({ ...form, remarks: e.target.value })} className={ic} /></F>
              {DOCS.map(([field, label]) => (
                <F key={field} label={`${label} Expiry`}>
                  <input data-testid={`vehicle-${field}`} type="date" value={form[field] || ""} onChange={(e) => setForm({ ...form, [field]: e.target.value })} className={ic} />
                </F>
              ))}
              <div className="md:col-span-2">
                <F label="Notes"><textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={ic} /></F>
              </div>
              {editing && (
                <div className="md:col-span-2">
                  <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 block mb-1">Document Scans (RC / FC / Insurance)</label>
                  <FileAttachments linkedType="vehicle" linkedId={editing.id} category="vehicle_doc" title="Vehicle Documents" />
                </div>
              )}
              </div>
              <div className="px-5 py-3 border-t border-zinc-200 bg-white flex justify-end gap-2 flex-shrink-0 sticky bottom-0">
                <button type="button" onClick={() => setOpen(false)} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
                <button data-testid="save-vehicle-btn" type="submit" disabled={save.isPending} className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
                  {save.isPending ? "Saving..." : "Save"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showQaSupplier && (
        <QuickAddSupplier
          onCreated={(s) => {
            setForm((f) => ({
              ...f,
              supplier_id: s.id,
              supplier_name: s.name,
              supplier_contact_person: s.contact_person || f.supplier_contact_person,
              supplier_mobile: s.mobile || f.supplier_mobile,
              supplier_gstin: s.gst_in || f.supplier_gstin,
              supplier_state: s.state || f.supplier_state,
            }));
          }}
          onClose={() => setShowQaSupplier(false)}
        />
      )}
    </div>
  );
}

function ExpiryBadge({ alert }) {
  const style =
    alert.status === "expired"
      ? "bg-rose-50 border-rose-300 text-rose-800"
      : alert.status === "expiring"
      ? "bg-amber-50 border-amber-300 text-amber-800"
      : "bg-emerald-50 border-emerald-300 text-emerald-800";
  const Icon = alert.status === "ok" ? CheckCircle2 : AlertTriangle;
  return (
    <div className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm border font-mono ${style}`}>
      <Icon size={10} />
      <span>{alert.date}</span>
      <span className="text-[10px]">({alert.days >= 0 ? `${alert.days}d` : `${Math.abs(alert.days)}d ago`})</span>
    </div>
  );
}

const ic = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";
function F({ label, children }) {
  return (
    <div>
      <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">{label}</label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
