import React, { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { X } from "lucide-react";

/** Iter136 P0 · Standalone Expense form drawer.
 *
 * Reuses POST/PUT /api/expenses. Never sends vendor_bill_id or
 * mechanic_work_order_id — those payable-twin fields belong to
 * RepairWorkspace's chain and are intentionally hidden here to
 * prevent operators from creating duplicate payables.
 */
const CATEGORIES = [
  "Driver Food", "Parking", "Toll", "Loading Charges", "Unloading Charges",
  "Weighment", "Labour", "Detention", "Cleaning",
  "Insurance", "Road Tax", "Permit", "Fitness", "Tyres",
  "Engine Oil", "AdBlue", "Repair", "Spare Parts", "Office / General",
  "Others",
];

const PARTY_TYPES = [
  { value: "none", label: "None" },
  { value: "cash", label: "Cash" },
  { value: "vendor", label: "Vendor" },
  { value: "mechanic", label: "Mechanic" },
  { value: "supplier", label: "Supplier" },
  { value: "driver", label: "Driver" },
];

export default function ExpenseForm({ mode = "create", row = null, vehicles = [], onClose, onSaved }) {
  const editing = mode === "edit" && row;
  const [form, setForm] = useState(() => ({
    date: editing ? row.date : new Date().toISOString().slice(0, 10),
    category: editing ? row.category : "Insurance",
    subcategory: editing ? row.subcategory || "" : "",
    amount: editing ? String(row.amount) : "",
    narration: editing ? row.narration || "" : "",
    remarks: editing ? row.remarks || "" : "",
    vehicle_id: editing ? row.vehicle_id || "" : "",
    trip_id: editing ? row.trip_id || "" : "",
    party_type: editing ? row.party_type || "none" : "none",
    party_id: editing ? row.party_id || "" : "",
    party_name: editing ? row.party_name || "" : "",
    settlement_mode: editing ? row.settlement_mode || "cash_now" : "cash_now",
    file_ids: editing ? row.file_ids || [] : [],
  }));
  const [uploading, setUploading] = useState(false);
  const [otherCat, setOtherCat] = useState(!CATEGORIES.includes(form.category));

  const save = useMutation({
    mutationFn: async () => {
      // Build payload — DO NOT include vendor_bill_id / mechanic_work_order_id.
      const body = {
        date: form.date,
        category: form.category.trim(),
        subcategory: form.subcategory.trim(),
        amount: parseFloat(form.amount),
        narration: form.narration,
        remarks: form.remarks,
        vehicle_id: form.vehicle_id || "",
        trip_id: form.trip_id || "",
        party_type: form.party_type || "none",
        party_id: form.party_type && form.party_type !== "none" && form.party_type !== "cash" ? form.party_id : "",
        party_name: form.party_name || "",
        settlement_mode: form.settlement_mode,
        supplier_owned_vehicle: false,
        supplier_settlement_mode: "n/a",
        file_ids: form.file_ids,
      };
      if (editing) {
        return (await api.put(`/expenses/${row.id}`, body)).data;
      }
      return (await api.post("/expenses", body)).data;
    },
    onSuccess: () => { toast.success(editing ? "Expense updated" : "Expense created"); onSaved && onSaved(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Save failed"),
  });

  const uploadFile = async (fileList) => {
    if (!fileList || !fileList.length) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", fileList[0]);
      fd.append("category", "general");
      const resp = await api.post("/files/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setForm((f) => ({ ...f, file_ids: [...f.file_ids, resp.data.id || resp.data.file_id] }));
      toast.success("File attached");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally { setUploading(false); }
  };

  const valid = form.date && form.category && parseFloat(form.amount) > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-end bg-zinc-900/60 p-0" data-testid="expense-drawer">
      <div className="bg-white w-full max-w-lg h-full overflow-y-auto border-l shadow-xl">
        <div className="p-4 border-b flex items-center justify-between sticky top-0 bg-white z-10">
          <h3 className="text-lg font-semibold">{editing ? "Edit Expense" : "New Expense"}</h3>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-900" data-testid="drawer-close"><X size={18}/></button>
        </div>
        <div className="p-4 space-y-3 text-sm">
          <Field label="Date">
            <input type="date" value={form.date} onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
                   className="w-full border rounded px-2 py-1" data-testid="field-date"/>
          </Field>
          <Field label="Category">
            <select value={otherCat ? "__other" : form.category}
                    onChange={(e) => {
                      if (e.target.value === "__other") { setOtherCat(true); setForm((f) => ({ ...f, category: "" })); }
                      else { setOtherCat(false); setForm((f) => ({ ...f, category: e.target.value })); }
                    }}
                    className="w-full border rounded px-2 py-1" data-testid="field-category">
              {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              <option value="__other">Other…</option>
            </select>
            {otherCat && (
              <input value={form.category} onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
                     placeholder="Custom category" className="w-full border rounded px-2 py-1 mt-1" data-testid="field-category-other"/>
            )}
          </Field>
          <Field label="Amount (₹)">
            <input type="number" step="0.01" value={form.amount}
                   onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
                   className="w-full border rounded px-2 py-1" data-testid="field-amount"/>
          </Field>
          <Field label="Description / Narration">
            <input value={form.narration} onChange={(e) => setForm((f) => ({ ...f, narration: e.target.value }))}
                   className="w-full border rounded px-2 py-1" data-testid="field-narration"/>
          </Field>
          <Field label="Remarks">
            <input value={form.remarks} onChange={(e) => setForm((f) => ({ ...f, remarks: e.target.value }))}
                   className="w-full border rounded px-2 py-1" data-testid="field-remarks"/>
          </Field>
          <Field label="Vehicle (optional)">
            <select value={form.vehicle_id} onChange={(e) => setForm((f) => ({ ...f, vehicle_id: e.target.value }))}
                    className="w-full border rounded px-2 py-1" data-testid="field-vehicle">
              <option value="">— None —</option>
              {vehicles.map((v) => <option key={v.id} value={v.id}>{v.vehicle_number}</option>)}
            </select>
          </Field>
          <Field label="Trip ID (optional)">
            <input value={form.trip_id} onChange={(e) => setForm((f) => ({ ...f, trip_id: e.target.value }))}
                   placeholder="trip_… (leave blank if not trip-related)"
                   className="w-full border rounded px-2 py-1 font-mono text-xs" data-testid="field-trip"/>
          </Field>
          <Field label="Party Type">
            <select value={form.party_type} onChange={(e) => setForm((f) => ({ ...f, party_type: e.target.value }))}
                    className="w-full border rounded px-2 py-1" data-testid="field-party-type">
              {PARTY_TYPES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </Field>
          {["vendor", "mechanic", "supplier", "driver"].includes(form.party_type) && (
            <Field label="Party Name">
              <input value={form.party_name}
                     onChange={(e) => setForm((f) => ({ ...f, party_name: e.target.value }))}
                     placeholder="e.g. Local Tyre Co"
                     className="w-full border rounded px-2 py-1"
                     data-testid="field-party-name"/>
            </Field>
          )}
          <Field label="Settlement">
            <select value={form.settlement_mode} onChange={(e) => setForm((f) => ({ ...f, settlement_mode: e.target.value }))}
                    className="w-full border rounded px-2 py-1" data-testid="field-settlement">
              <option value="cash_now">Cash now</option>
              <option value="payable">Payable</option>
            </select>
          </Field>
          <Field label="Attachments">
            <input type="file" onChange={(e) => uploadFile(e.target.files)} disabled={uploading}
                   className="w-full text-xs" data-testid="field-file"/>
            {form.file_ids.length > 0 && (
              <div className="text-xs text-zinc-500 mt-1">Attached: {form.file_ids.length} file(s)</div>
            )}
          </Field>
        </div>
        <div className="p-4 border-t flex justify-end gap-2 sticky bottom-0 bg-white">
          <button onClick={onClose} className="px-3 py-1 border rounded" data-testid="drawer-cancel">Cancel</button>
          <button onClick={() => save.mutate()} disabled={!valid || save.isPending}
                  className="px-3 py-1 bg-zinc-950 text-white rounded disabled:opacity-50" data-testid="drawer-save">
            {save.isPending ? "Saving…" : editing ? "Update" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <div className="text-xs text-zinc-500 mb-1">{label}</div>
      {children}
    </label>
  );
}
