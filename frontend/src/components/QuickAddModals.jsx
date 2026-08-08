import React, { useState } from "react";
import { api } from "@/api";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { X } from "lucide-react";

const ic = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";
const lbl = "text-[10px] font-bold uppercase tracking-wider text-zinc-500";

function ModalShell({ title, onClose, children, testId }) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-zinc-900/50 backdrop-blur-sm p-4" data-testid={testId}>
      <div className="bg-white w-full max-w-lg border border-zinc-950 rounded-sm max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200 flex-shrink-0">
          <h3 className="font-bold">{title}</h3>
          <button type="button" onClick={onClose} data-testid={`${testId}-close`}><X size={18} /></button>
        </div>
        <div className="p-5 overflow-y-auto flex-1">{children}</div>
      </div>
    </div>
  );
}

export function QuickAddCustomer({ prefillName = "", onCreated, onClose }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: prefillName, phone: "", gstin: "", state: "", address: "", pincode: "" });
  const m = useMutation({
    mutationFn: async () => (await api.post("/customers", f)).data,
    onSuccess: (d) => {
      toast.success("Customer added");
      qc.invalidateQueries({ queryKey: ["customers"] });
      onCreated?.(d);
      onClose?.();
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });
  return (
    <ModalShell title="Quick Add — Customer" onClose={onClose} testId="quickadd-customer-modal">
      <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="space-y-3">
        <div><label className={lbl}>Name *</label><input required data-testid="qa-cust-name" autoFocus value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className={ic} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className={lbl}>Phone</label><input data-testid="qa-cust-phone" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} className={ic} /></div>
          <div><label className={lbl}>GSTIN</label><input data-testid="qa-cust-gstin" value={f.gstin} onChange={(e) => setF({ ...f, gstin: e.target.value.toUpperCase() })} className={ic} /></div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className={lbl}>State</label><input data-testid="qa-cust-state" value={f.state} onChange={(e) => setF({ ...f, state: e.target.value })} className={ic} placeholder="e.g. Andhra Pradesh" /></div>
          <div><label className={lbl}>Pincode</label><input data-testid="qa-cust-pincode" value={f.pincode} onChange={(e) => setF({ ...f, pincode: e.target.value })} className={ic} /></div>
        </div>
        <div><label className={lbl}>Address</label><textarea data-testid="qa-cust-address" rows={2} value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} className={ic} /></div>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
          <button type="submit" data-testid="qa-cust-save" disabled={m.isPending} className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm disabled:opacity-50">{m.isPending ? "Saving…" : "Save Customer"}</button>
        </div>
      </form>
    </ModalShell>
  );
}

export function QuickAddDriver({ prefillName = "", onCreated, onClose }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: prefillName, phone: "", license_number: "", notes: "" });
  const m = useMutation({
    mutationFn: async () => (await api.post("/drivers", f)).data,
    onSuccess: (d) => {
      toast.success("Driver added");
      qc.invalidateQueries({ queryKey: ["drivers"] });
      onCreated?.(d);
      onClose?.();
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });
  return (
    <ModalShell title="Quick Add — Driver" onClose={onClose} testId="quickadd-driver-modal">
      <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="space-y-3">
        <div><label className={lbl}>Name *</label><input required data-testid="qa-drv-name" autoFocus value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className={ic} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className={lbl}>Phone</label><input data-testid="qa-drv-phone" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} className={ic} /></div>
          <div><label className={lbl}>License No.</label><input data-testid="qa-drv-license" value={f.license_number} onChange={(e) => setF({ ...f, license_number: e.target.value })} className={ic} /></div>
        </div>
        <div><label className={lbl}>Notes</label><input data-testid="qa-drv-notes" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} className={ic} /></div>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
          <button type="submit" data-testid="qa-drv-save" disabled={m.isPending} className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm disabled:opacity-50">{m.isPending ? "Saving…" : "Save Driver"}</button>
        </div>
      </form>
    </ModalShell>
  );
}

export function QuickAddVehicle({ prefillNumber = "", onCreated, onClose }) {
  const qc = useQueryClient();
  const [f, setF] = useState({
    vehicle_number: prefillNumber.toUpperCase(),
    vehicle_type: "own",
    owner_name: "",
    owner_phone: "",
    make_model: "",
    capacity_tons: 0,
    supplier_name: "",
    supplier_mobile: "",
  });
  const m = useMutation({
    mutationFn: async () => (await api.post("/vehicles", { ...f, capacity_tons: Number(f.capacity_tons || 0) })).data,
    onSuccess: (d) => {
      toast.success("Vehicle added");
      qc.invalidateQueries({ queryKey: ["vehicles"] });
      onCreated?.(d);
      onClose?.();
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });
  return (
    <ModalShell title="Quick Add — Vehicle" onClose={onClose} testId="quickadd-vehicle-modal">
      <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div><label className={lbl}>Vehicle Number *</label><input required data-testid="qa-veh-number" autoFocus value={f.vehicle_number} onChange={(e) => setF({ ...f, vehicle_number: e.target.value.toUpperCase() })} className={ic} placeholder="AP16TA1234" /></div>
          <div>
            <label className={lbl}>Type</label>
            <select data-testid="qa-veh-type" value={f.vehicle_type} onChange={(e) => setF({ ...f, vehicle_type: e.target.value })} className={ic}>
              <option value="own">Own</option>
              <option value="supplier">Supplier (Hired)</option>
            </select>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className={lbl}>Owner Name</label><input data-testid="qa-veh-owner" value={f.owner_name} onChange={(e) => setF({ ...f, owner_name: e.target.value })} className={ic} /></div>
          <div><label className={lbl}>Owner Phone</label><input data-testid="qa-veh-owner-phone" value={f.owner_phone} onChange={(e) => setF({ ...f, owner_phone: e.target.value })} className={ic} /></div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className={lbl}>Make / Model</label><input data-testid="qa-veh-model" value={f.make_model} onChange={(e) => setF({ ...f, make_model: e.target.value })} className={ic} placeholder="Tata LPT 3118" /></div>
          <div><label className={lbl}>Capacity (Tons)</label><input type="number" step="0.1" min="0" data-testid="qa-veh-capacity" value={f.capacity_tons} onChange={(e) => setF({ ...f, capacity_tons: e.target.value })} className={ic} /></div>
        </div>
        {f.vehicle_type === "supplier" && (
          <div className="grid grid-cols-2 gap-3">
            <div><label className={lbl}>Supplier Name</label><input data-testid="qa-veh-sup-name" value={f.supplier_name} onChange={(e) => setF({ ...f, supplier_name: e.target.value })} className={ic} /></div>
            <div><label className={lbl}>Supplier Mobile</label><input data-testid="qa-veh-sup-mobile" value={f.supplier_mobile} onChange={(e) => setF({ ...f, supplier_mobile: e.target.value })} className={ic} /></div>
          </div>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
          <button type="submit" data-testid="qa-veh-save" disabled={m.isPending} className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm disabled:opacity-50">{m.isPending ? "Saving…" : "Save Vehicle"}</button>
        </div>
      </form>
    </ModalShell>
  );
}

export function QuickAddProduct({ prefillName = "", onCreated, onClose }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: prefillName || "Bitumen VG 40", hsn_sac: "996791", default_rate: 0 });
  const m = useMutation({
    mutationFn: async () => (await api.post("/products", { ...f, default_rate: Number(f.default_rate || 0) })).data,
    onSuccess: (d) => {
      toast.success("Product added");
      qc.invalidateQueries({ queryKey: ["products"] });
      onCreated?.(d);
      onClose?.();
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });
  return (
    <ModalShell title="Quick Add — Product" onClose={onClose} testId="quickadd-product-modal">
      <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="space-y-3">
        <div><label className={lbl}>Name *</label><input required data-testid="qa-prd-name" autoFocus value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className={ic} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className={lbl}>HSN/SAC</label><input data-testid="qa-prd-hsn" value={f.hsn_sac} onChange={(e) => setF({ ...f, hsn_sac: e.target.value })} className={ic} /></div>
          <div><label className={lbl}>Default Rate (₹/MT)</label><input type="number" step="0.01" min="0" data-testid="qa-prd-rate" value={f.default_rate} onChange={(e) => setF({ ...f, default_rate: e.target.value })} className={ic} /></div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
          <button type="submit" data-testid="qa-prd-save" disabled={m.isPending} className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm disabled:opacity-50">{m.isPending ? "Saving…" : "Save Product"}</button>
        </div>
      </form>
    </ModalShell>
  );
}
