import { useEffect, useState } from "react";
import { api } from "@/api";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

const EMPTY = {
  name: "", customer_id: "", from_location: "", to_location: "",
  load_details: "", product_type: "", round_trip_kms: 0,
  freight_mode: "per_ton", rate_per_ton: 0, rate_per_km_per_ton: 0, fixed_amount: 0,
  hsn_sac: "996791", gst_type: "cgst_sgst", halting_rate_per_day: 0, remarks: "",
};

const inputCls = "w-full px-3 py-2 rounded-md border border-zinc-300 focus:border-zinc-800 focus:ring-1 focus:ring-zinc-800 text-sm";

export default function TripTemplates() {
  const [list, setList] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [editing, setEditing] = useState(null);   // null = list view, object = edit view
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const [tpl, cust] = await Promise.all([
      api.get("/templates"), api.get("/customers"),
    ]);
    setList(tpl.data || []);
    setCustomers(cust.data || []);
  };
  useEffect(() => { load(); }, []);

  const startNew = () => setEditing({ ...EMPTY });
  const startEdit = (tpl) => setEditing({ ...tpl });
  const cancel = () => setEditing(null);

  const save = async () => {
    if (!editing.name?.trim()) {
      toast.error("Template name is required");
      return;
    }
    setSaving(true);
    try {
      if (editing.id) {
        await api.put(`/templates/${editing.id}`, editing);
        toast.success("Template updated");
      } else {
        await api.post("/templates", editing);
        toast.success("Template created");
      }
      setEditing(null);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Save failed");
    } finally { setSaving(false); }
  };

  const remove = async (tpl) => {
    if (!window.confirm(`Delete template "${tpl.name}"?`)) return;
    try {
      await api.delete(`/templates/${tpl.id}`);
      toast.success("Deleted");
      load();
    } catch (e) { toast.error("Delete failed"); }
  };

  const F = (k) => (e) => setEditing({ ...editing, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value });

  if (editing) {
    return (
      <div className="space-y-4 max-w-3xl" data-testid="template-form">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">{editing.id ? "Edit" : "New"} Trip Template</h1>
          <div className="flex gap-2">
            <Button variant="outline" onClick={cancel} data-testid="template-cancel">Cancel</Button>
            <Button onClick={save} disabled={saving} data-testid="template-save">{saving ? "Saving…" : "Save"}</Button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="Template Name *"><input data-testid="tpl-name" className={inputCls} value={editing.name} onChange={F("name")} /></Field>
          <Field label="Customer">
            <select data-testid="tpl-customer" className={inputCls} value={editing.customer_id} onChange={F("customer_id")}>
              <option value="">— select —</option>
              {customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
          <Field label="Loading Point (From)"><input className={inputCls} value={editing.from_location} onChange={F("from_location")} /></Field>
          <Field label="Unloading Point (To)"><input className={inputCls} value={editing.to_location} onChange={F("to_location")} /></Field>
          <Field label="Material / Load"><input className={inputCls} value={editing.load_details} onChange={F("load_details")} placeholder="Bitumen VG 40" /></Field>
          <Field label="Product Type">
            <select className={inputCls} value={editing.product_type} onChange={F("product_type")}>
              <option value="">— select —</option>
              {["VG-10", "VG-30", "VG-40", "CRMB", "PMB", "Emulsion", "Other"].map(o => <option key={o}>{o}</option>)}
            </select>
          </Field>
          <Field label="Distance (Round Trip KMs)"><input type="number" className={inputCls} value={editing.round_trip_kms} onChange={F("round_trip_kms")} /></Field>
          <Field label="Freight Mode">
            <select className={inputCls} value={editing.freight_mode} onChange={F("freight_mode")}>
              <option value="per_ton">Per Ton</option>
              <option value="round_trip">Per KM per Ton</option>
              <option value="fixed">Fixed</option>
            </select>
          </Field>
          {editing.freight_mode === "per_ton" && <Field label="Rate per Ton (₹)"><input type="number" className={inputCls} value={editing.rate_per_ton} onChange={F("rate_per_ton")} /></Field>}
          {editing.freight_mode === "round_trip" && <Field label="Rate per KM per Ton (₹)"><input type="number" className={inputCls} value={editing.rate_per_km_per_ton} onChange={F("rate_per_km_per_ton")} /></Field>}
          {editing.freight_mode === "fixed" && <Field label="Fixed Amount (₹)"><input type="number" className={inputCls} value={editing.fixed_amount} onChange={F("fixed_amount")} /></Field>}
          <Field label="HSN / SAC"><input className={inputCls} value={editing.hsn_sac} onChange={F("hsn_sac")} /></Field>
          <Field label="GST Type">
            <select className={inputCls} value={editing.gst_type} onChange={F("gst_type")}>
              <option value="cgst_sgst">CGST + SGST</option>
              <option value="igst">IGST</option>
              <option value="rcm">RCM</option>
            </select>
          </Field>
          <Field label="Halting Rate / Day (₹)"><input type="number" className={inputCls} value={editing.halting_rate_per_day} onChange={F("halting_rate_per_day")} /></Field>
          <Field label="Default Remarks / Notes" className="md:col-span-2">
            <textarea rows={3} className={inputCls} value={editing.remarks} onChange={F("remarks")} />
          </Field>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="templates-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Trip Templates</h1>
          <div className="text-sm text-zinc-500">Save frequently-used routes &amp; rates for one-click trip creation.</div>
        </div>
        <Button onClick={startNew} data-testid="template-new">+ New Template</Button>
      </div>

      {list.length === 0 ? (
        <div className="text-center text-zinc-500 py-16 border border-dashed rounded-lg">
          No templates yet. Create your first frequently-used trip route.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {list.map(tpl => {
            const cust = customers.find(c => c.id === tpl.customer_id);
            return (
              <div key={tpl.id} className="border rounded-lg p-4 bg-white space-y-2" data-testid={`template-card-${tpl.id}`}>
                <div className="font-semibold">{tpl.name}</div>
                <div className="text-xs text-zinc-500">
                  {tpl.from_location} → {tpl.to_location}
                </div>
                <div className="text-xs">
                  {cust?.name || "—"} · {tpl.load_details || "—"} · {tpl.product_type || ""}
                </div>
                <div className="text-xs text-zinc-500">
                  Rate: {tpl.freight_mode === "per_ton" ? `₹${tpl.rate_per_ton}/T` :
                         tpl.freight_mode === "round_trip" ? `₹${tpl.rate_per_km_per_ton}/km/T × ${tpl.round_trip_kms}km` :
                         `₹${tpl.fixed_amount} fixed`}
                </div>
                <div className="pt-2 flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => startEdit(tpl)} data-testid={`template-edit-${tpl.id}`}>Edit</Button>
                  <Button size="sm" variant="outline" onClick={() => remove(tpl)} data-testid={`template-delete-${tpl.id}`}>Delete</Button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Field({ label, children, className = "" }) {
  return (
    <div className={className}>
      <div className="text-xs font-semibold text-zinc-600 mb-1">{label}</div>
      {children}
    </div>
  );
}
