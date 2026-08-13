import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X, Truck, AlertTriangle, CheckCircle2, Users, Upload, Download } from "lucide-react";
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
  // Iter64 · Priority 2 — deactivate/reactivate dialog + audit history modal
  const [statusDialog, setStatusDialog] = useState(null); // { mode: 'deactivate'|'reactivate', reason, effective_date }
  const [showAudit, setShowAudit] = useState(null); // vehicle object or null
  const [bulkImport, setBulkImport] = useState(null); // {file, preview, busy}

  const { data: vehicles = [] } = useQuery({
    queryKey: ["vehicles"],
    queryFn: async () => (await api.get("/vehicles")).data,
  });
  const { data: suppliers = [] } = useQuery({
    queryKey: ["suppliers"],
    queryFn: async () => (await api.get("/suppliers")).data,
  });
  const { data: audit } = useQuery({
    queryKey: ["vehicle-audit", showAudit?.id],
    queryFn: async () => (await api.get(`/vehicles/${showAudit.id}/status-audit`)).data,
    enabled: !!showAudit?.id,
  });
  const statusMut = useMutation({
    mutationFn: async () => (await api.patch(`/vehicles/${editing.id}/status`, {
      is_active: statusDialog.mode === "reactivate",
      reason: statusDialog.reason,
      effective_date: statusDialog.effective_date,
    })).data,
    onSuccess: (d) => {
      toast.success(`Vehicle ${d.action}`);
      setForm((f) => ({ ...f, is_active: d.new_is_active }));
      setStatusDialog(null);
      qc.invalidateQueries({ queryKey: ["vehicles"] });
      qc.invalidateQueries({ queryKey: ["vehicle-audit", editing.id] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
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
        <div className="flex items-center gap-2">
          <button data-testid="bulk-import-btn" onClick={() => setBulkImport({ file: null, preview: null, busy: false })} className="px-3 py-2 text-xs uppercase tracking-wider font-semibold border border-zinc-950 text-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white inline-flex items-center gap-2">
            <Upload size={14} /> Bulk Import
          </button>
          <button data-testid="add-vehicle-btn" onClick={openNew} className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 inline-flex items-center gap-2">
            <Plus size={14} /> Add Vehicle
          </button>
        </div>
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
                {editing?.id ? (
                  <div className="pt-2 space-y-2">
                    <div className="flex items-center gap-3 text-sm">
                      {form.is_active !== false ? (
                        <span data-testid="vehicle-form-status" className="inline-block px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 text-[10px] uppercase tracking-wider font-bold">Currently Active</span>
                      ) : (
                        <span data-testid="vehicle-form-status" className="inline-block px-2 py-0.5 rounded-full bg-zinc-100 text-zinc-600 border border-zinc-300 text-[10px] uppercase tracking-wider font-bold">Currently Inactive</span>
                      )}
                      <button
                        type="button"
                        data-testid="vehicle-toggle-status-btn"
                        onClick={() => setStatusDialog({ mode: form.is_active !== false ? "deactivate" : "reactivate", reason: "", effective_date: new Date().toISOString().slice(0,10) })}
                        className="text-xs px-3 py-1 border border-zinc-300 rounded-sm hover:bg-zinc-50 uppercase tracking-wider"
                      >{form.is_active !== false ? "Make Inactive…" : "Reactivate…"}</button>
                      <button
                        type="button"
                        data-testid="vehicle-view-audit-btn"
                        onClick={() => setShowAudit(editing)}
                        className="text-xs px-3 py-1 border border-indigo-200 text-indigo-800 rounded-sm hover:bg-indigo-50 uppercase tracking-wider"
                      >Audit History</button>
                    </div>
                    <div className="text-[10px] text-zinc-500">Inactive vehicles are hidden from new Trips. Historical Trips remain unchanged.</div>
                  </div>
                ) : (
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
                )}
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

      {/* Iter64 · Priority 3 — Bulk Vehicle Import (CSV/XLSX preview → commit) */}
      {bulkImport && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/45 backdrop-blur-sm p-4" data-testid="bulk-import-modal">
          <div className="bg-white w-full max-w-4xl border border-zinc-950 rounded-sm shadow-2xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
              <h3 className="font-bold">Bulk Import Vehicles</h3>
              <button onClick={() => setBulkImport(null)} className="text-zinc-500 hover:text-zinc-950 text-lg leading-none">×</button>
            </div>
            <div className="p-5 space-y-4 overflow-y-auto">
              <div className="text-xs text-zinc-600 bg-amber-50 border border-amber-200 p-3 rounded-sm space-y-1">
                <div><b>CSV / XLSX columns:</b> vehicle_number, vehicle_type (own/supplier), supplier_name OR supplier_id, owner_name, owner_phone, make_model, capacity_tons, remarks, is_active (true/false)</div>
                <div><b>Duplicates:</b> existing vehicle numbers (and duplicates within the file) are rejected with an error line — not silently overwritten.</div>
                <div><b>Suppliers:</b> for supplier vehicles, the supplier_id or supplier_name must already exist in Supplier Master (case-insensitive match). Add missing suppliers first.</div>
                <div><b>Sample:</b> <a data-testid="download-sample-csv" href="#" onClick={(e) => { e.preventDefault(); downloadSampleVehicleCSV(); }} className="text-indigo-700 underline">CSV</a> · <a data-testid="download-sample-xlsx" href="#" onClick={async (e) => { e.preventDefault(); const res = await api.get("/vehicles/bulk-import/sample.xlsx", { responseType: "blob" }); const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([res.data])); link.download = "vehicles_sample_import.xlsx"; link.click(); }} className="text-indigo-700 underline">Excel (.xlsx)</a></div>
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Select CSV or XLSX file *</label>
                <input
                  data-testid="bulk-import-file"
                  type="file"
                  accept=".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    setBulkImport({ file: f, preview: null, busy: true });
                    try {
                      const fd = new FormData(); fd.append("file", f);
                      const res = await api.post("/vehicles/bulk-import/preview", fd, { headers: { "Content-Type": "multipart/form-data" } });
                      setBulkImport({ file: f, preview: res.data, busy: false });
                    } catch (err) {
                      toast.error(err?.response?.data?.detail || "Preview failed");
                      setBulkImport({ file: null, preview: null, busy: false });
                    }
                  }}
                  className="mt-1 block w-full text-sm border border-zinc-300 rounded-sm px-3 py-2 file:mr-3 file:py-1 file:px-3 file:border-0 file:rounded-sm file:bg-zinc-950 file:text-white file:cursor-pointer"
                />
              </div>
              {bulkImport.busy && <div className="text-sm text-zinc-500">Analyzing…</div>}
              {bulkImport.preview && (
                <div className="space-y-3" data-testid="bulk-import-preview">
                  <div className="grid grid-cols-3 gap-3">
                    <div className="border border-zinc-200 bg-white p-3 rounded-sm">
                      <div className="text-[10px] uppercase text-zinc-500 font-bold">Total Rows</div>
                      <div className="text-2xl font-black" data-testid="bulk-total-rows">{bulkImport.preview.total_rows}</div>
                    </div>
                    <div className="border border-emerald-200 bg-emerald-50 p-3 rounded-sm">
                      <div className="text-[10px] uppercase text-emerald-700 font-bold">Ready to Import</div>
                      <div className="text-2xl font-black text-emerald-800" data-testid="bulk-valid-count">{bulkImport.preview.valid_count}</div>
                    </div>
                    <div className="border border-rose-200 bg-rose-50 p-3 rounded-sm">
                      <div className="text-[10px] uppercase text-rose-700 font-bold">Errors — Will Skip</div>
                      <div className="text-2xl font-black text-rose-800" data-testid="bulk-error-count">{bulkImport.preview.error_count}</div>
                    </div>
                  </div>
                  {bulkImport.preview.errors?.length > 0 && (
                    <div>
                      <div className="text-[10px] uppercase font-bold text-rose-700 mb-1">Validation Errors</div>
                      <div className="max-h-40 overflow-y-auto border border-rose-200 rounded-sm">
                        <table className="w-full text-xs" data-testid="bulk-errors-table">
                          <thead className="bg-rose-50 sticky top-0"><tr><th className="text-left px-3 py-1">Row #</th><th className="text-left px-3 py-1">Vehicle</th><th className="text-left px-3 py-1">Errors</th></tr></thead>
                          <tbody>
                            {bulkImport.preview.errors.map((e, i) => (
                              <tr key={i} className="border-t border-rose-100" data-testid={`bulk-error-row-${e.row_number}`}>
                                <td className="px-3 py-1 font-mono">{e.row_number}</td>
                                <td className="px-3 py-1 font-mono">{e.vehicle_number || "—"}</td>
                                <td className="px-3 py-1 text-rose-700">{e.errors.join("; ")}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                  {bulkImport.preview.valid_count > 0 && (
                    <div>
                      <div className="text-[10px] uppercase font-bold text-emerald-700 mb-1">Preview (first 20 rows to import)</div>
                      <div className="max-h-52 overflow-y-auto border border-emerald-200 rounded-sm">
                        <table className="w-full text-xs" data-testid="bulk-valid-table">
                          <thead className="bg-emerald-50 sticky top-0"><tr><th className="px-2 py-1 text-left">Vehicle</th><th className="px-2 py-1 text-left">Type</th><th className="px-2 py-1 text-left">Owner / Supplier</th><th className="px-2 py-1 text-left">Make</th><th className="px-2 py-1 text-right">Cap</th><th className="px-2 py-1 text-center">Active</th></tr></thead>
                          <tbody>
                            {bulkImport.preview.valid.slice(0, 20).map((v, i) => (
                              <tr key={i} className="border-t border-emerald-100">
                                <td className="px-2 py-1 font-mono">{v.vehicle_number}</td>
                                <td className="px-2 py-1">{v.vehicle_type}</td>
                                <td className="px-2 py-1">{v.vehicle_type === "supplier" ? v.supplier_name : v.owner_name || "—"}</td>
                                <td className="px-2 py-1">{v.make_model || "—"}</td>
                                <td className="px-2 py-1 text-right font-mono">{v.capacity_tons}</td>
                                <td className="px-2 py-1 text-center">{v.is_active ? "✓" : "✗"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
            <div className="border-t border-zinc-200 p-4 flex items-center justify-end gap-2 bg-zinc-50">
              <button data-testid="bulk-import-cancel" onClick={() => setBulkImport(null)} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-white">Cancel</button>
              <button
                data-testid="bulk-import-confirm"
                disabled={bulkImport.busy || !bulkImport.file || !bulkImport.preview || bulkImport.preview.valid_count === 0}
                onClick={async () => {
                  setBulkImport({ ...bulkImport, busy: true });
                  try {
                    const fd = new FormData(); fd.append("file", bulkImport.file);
                    const res = await api.post("/vehicles/bulk-import", fd, { headers: { "Content-Type": "multipart/form-data" } });
                    toast.success(`Imported ${res.data.inserted} vehicles`);
                    qc.invalidateQueries({ queryKey: ["vehicles"] });
                    setBulkImport(null);
                  } catch (err) {
                    toast.error(err?.response?.data?.detail || "Import failed");
                    setBulkImport({ ...bulkImport, busy: false });
                  }
                }}
                className="px-6 py-2 text-xs uppercase tracking-wider font-semibold bg-emerald-600 text-white rounded-sm hover:bg-emerald-700 disabled:opacity-50"
              >{bulkImport.busy ? "Importing…" : `Import ${bulkImport.preview?.valid_count || 0} Vehicles`}</button>
            </div>
          </div>
        </div>
      )}

      {/* Iter64 · Priority 2 — Vehicle status change dialog */}
      {statusDialog && editing?.id && (() => {
        // Iter65 · Priority 4 — compute inactive duration for reactivation guard
        let inactiveDays = 0;
        if (statusDialog.mode === "reactivate" && editing.last_status_change_effective_date) {
          try {
            const dt = new Date(editing.last_status_change_effective_date + "T00:00:00");
            inactiveDays = Math.floor((Date.now() - dt.getTime()) / (1000 * 60 * 60 * 24));
          } catch { inactiveDays = 0; }
        }
        const showLongInactiveWarning = statusDialog.mode === "reactivate" && inactiveDays > 90;
        return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/45 backdrop-blur-sm p-4" data-testid="vehicle-status-dialog">
          <div className="bg-white w-full max-w-lg border border-zinc-950 rounded-sm shadow-2xl">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
              <h3 className="font-bold">
                {statusDialog.mode === "deactivate" ? "Deactivate Vehicle" : "Reactivate Vehicle"}
                <span className="ml-2 font-mono text-zinc-600 text-sm">{editing.vehicle_number}</span>
              </h3>
              <button onClick={() => setStatusDialog(null)} className="text-zinc-500 hover:text-zinc-950 text-lg leading-none">×</button>
            </div>
            <div className="p-5 space-y-3">
              <div className="text-xs text-zinc-600 bg-amber-50 border border-amber-200 p-2 rounded-sm">
                {statusDialog.mode === "deactivate"
                  ? "Inactive vehicles are hidden from new Trip pickers. Historical Trips using this vehicle remain unchanged. A mandatory reason is recorded in the audit trail."
                  : "Reactivation makes the vehicle available for new Trips again. The reactivation event is recorded permanently — prior inactive history is preserved."}
              </div>
              {showLongInactiveWarning && (
                <div className="text-xs bg-rose-50 border border-rose-300 rounded-sm p-3 space-y-1" data-testid="vehicle-reactivate-warning">
                  <div className="font-bold text-rose-800 flex items-center gap-1"><AlertTriangle size={12} /> This vehicle has been INACTIVE for {inactiveDays} days</div>
                  <div className="text-rose-700">Last inactive effective date: <span className="font-mono font-semibold">{editing.last_status_change_effective_date}</span></div>
                  <div className="text-rose-700">Reason: <span className="italic">{editing.last_status_change_reason || "—"}</span></div>
                  <div className="text-[11px] text-zinc-700 mt-2">Please confirm you have re-verified RC, FC, Insurance, Permit and PUC documents before reactivating. The complete inactive/reactivation audit history will be preserved.</div>
                  <label className="flex items-center gap-2 mt-2 cursor-pointer text-xs">
                    <input
                      data-testid="vehicle-reactivate-confirm-check"
                      type="checkbox"
                      checked={!!statusDialog.long_inactive_ack}
                      onChange={(e) => setStatusDialog({ ...statusDialog, long_inactive_ack: e.target.checked })}
                      className="h-4 w-4 accent-rose-600"
                    />
                    <span className="font-semibold text-rose-800">I have verified the vehicle is fit to return to service.</span>
                  </label>
                </div>
              )}
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Reason (min 3 chars) *</label>
                <textarea data-testid="vehicle-status-reason" rows={3} autoFocus value={statusDialog.reason}
                  onChange={(e) => setStatusDialog({ ...statusDialog, reason: e.target.value })}
                  placeholder={statusDialog.mode === "deactivate" ? "e.g. Sold on 2026-02-01, RC transferred" : "e.g. Back in service after repair"}
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white" />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Effective Date *</label>
                <input data-testid="vehicle-status-effective-date" type="date" value={statusDialog.effective_date}
                  onChange={(e) => setStatusDialog({ ...statusDialog, effective_date: e.target.value })}
                  className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white" />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" data-testid="vehicle-status-cancel" onClick={() => setStatusDialog(null)}
                  className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-50">Cancel</button>
                <button type="button" data-testid="vehicle-status-confirm"
                  disabled={statusMut.isPending || statusDialog.reason.trim().length < 3 || !statusDialog.effective_date || (showLongInactiveWarning && !statusDialog.long_inactive_ack)}
                  onClick={() => statusMut.mutate()}
                  className={`px-4 py-2 text-xs uppercase tracking-wider text-white rounded-sm disabled:opacity-50 ${statusDialog.mode === "deactivate" ? "bg-rose-600 hover:bg-rose-700" : "bg-emerald-600 hover:bg-emerald-700"}`}
                >{statusMut.isPending ? "Saving…" : (statusDialog.mode === "deactivate" ? "Confirm Deactivate" : "Confirm Reactivate")}</button>
              </div>
            </div>
          </div>
        </div>
        );
      })()}

      {/* Iter64 · Priority 2 — Vehicle audit history viewer */}
      {showAudit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/45 backdrop-blur-sm p-4" data-testid="vehicle-audit-modal">
          <div className="bg-white w-full max-w-2xl border border-zinc-950 rounded-sm shadow-2xl max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
              <h3 className="font-bold">Status Audit History <span className="ml-2 font-mono text-zinc-600 text-sm">{showAudit.vehicle_number}</span></h3>
              <button onClick={() => setShowAudit(null)} className="text-zinc-500 hover:text-zinc-950 text-lg leading-none">×</button>
            </div>
            <div className="p-5 overflow-y-auto">
              {(!audit || audit.total === 0) ? (
                <div className="text-center text-zinc-400 py-8" data-testid="vehicle-audit-empty">No status changes recorded yet.</div>
              ) : (
                <table className="w-full text-sm" data-testid="vehicle-audit-table">
                  <thead className="text-[10px] uppercase tracking-wider text-zinc-500 border-b border-zinc-200">
                    <tr>
                      <th className="text-left px-2 py-2">When</th>
                      <th className="text-left px-2 py-2">Action</th>
                      <th className="text-left px-2 py-2">Effective</th>
                      <th className="text-left px-2 py-2">Reason</th>
                      <th className="text-left px-2 py-2">Changed By</th>
                    </tr>
                  </thead>
                  <tbody>
                    {audit.items.map((a) => (
                      <tr key={a.id} className="border-b border-zinc-100" data-testid={`audit-row-${a.id}`}>
                        <td className="px-2 py-2 font-mono text-xs">{(a.changed_at || "").slice(0, 19).replace("T", " ")}</td>
                        <td className="px-2 py-2 text-xs">
                          <span className={`inline-block px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider font-bold border ${
                            a.action === "deactivated" ? "bg-rose-50 text-rose-800 border-rose-200" : "bg-emerald-50 text-emerald-800 border-emerald-200"
                          }`}>{a.action}</span>
                        </td>
                        <td className="px-2 py-2 font-mono text-xs">{a.effective_date}</td>
                        <td className="px-2 py-2 text-xs text-zinc-700">{a.reason}</td>
                        <td className="px-2 py-2 text-xs text-zinc-500">{a.changed_by_email || a.changed_by}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
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

function downloadSampleVehicleCSV() {
  const csv = [
    "vehicle_number,vehicle_type,supplier_name,supplier_id,owner_name,owner_phone,make_model,capacity_tons,remarks,is_active",
    "AP16TA1001,own,,,Ravi Kumar,9998887777,Tata LPT 3118,25,Own truck,true",
    "AP16TA1002,supplier,Kondapalli Fleet Owners,,,,Ashok Leyland 3720,32,Hired,true",
    "AP16TA1003,own,,,Sita Rao,,BharatBenz 2823,26,,false",
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "vehicles_sample_import.csv";
  a.click();
}
