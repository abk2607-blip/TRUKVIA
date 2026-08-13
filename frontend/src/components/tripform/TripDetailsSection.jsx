// Iter55 — Extracted verbatim from TripForm.jsx. Pure JSX; state lives in parent.
// Iter66 · Phase B — added Ship-To Site picker + Customer Reference Number.
import React from "react";
import SearchableSelect from "@/components/SearchableSelect";
import { Section, Field } from "./FormPrimitives";
import { inputCls } from "./tripFormDefaults";

export default function TripDetailsSection({
  form, setForm,
  customers, vehicles, drivers, products,
  setQaOpen,
}) {
  // Selected customer's active ship sites
  const selectedCustomer = customers.find((c) => c.id === form.customer_id);
  const shipSites = (selectedCustomer?.ship_sites || []).filter((s) => s.is_active !== false);

  // Auto-select customer's default site whenever customer changes AND no site picked yet.
  React.useEffect(() => {
    if (!form.customer_id || form.ship_site_id) return;
    const def = shipSites.find((s) => s.is_default);
    if (def) setForm((f) => ({ ...f, ship_site_id: def.id }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.customer_id]);

  return (
    <Section title="వివరాలు · Trip Details">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Field label="Date · తేదీ" required>
          <input type="date" data-testid="trip-date" required value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={inputCls} />
        </Field>
        <Field label="Customer · కస్టమర్" required>
          <SearchableSelect
            dataTestId="trip-customer"
            value={form.customer_id}
            onChange={(v) => setForm({ ...form, customer_id: v, ship_site_id: "" })}
            onCreateNew={() => setQaOpen("customer")}
            createLabel="+ Add New Customer"
            placeholder="Search customer…"
            options={customers.map((c) => ({
              value: c.id,
              label: c.name,
              meta: [c.gstin, c.state, c.phone].filter(Boolean).join(" · "),
            }))}
          />
        </Field>
        <Field label="Vehicle No · వాహనం" required>
          <SearchableSelect
            dataTestId="trip-vehicle-select"
            value={vehicles.find((v) => v.vehicle_number === form.vehicle_number)?.id || ""}
            onChange={(vid) => {
              const v = vehicles.find((x) => x.id === vid);
              if (v) {
                setForm({
                  ...form,
                  vehicle_id: v.id,
                  vehicle_number: v.vehicle_number,
                  vehicle_type: v.vehicle_type || "own",
                  supplier_id: v.vehicle_type === "supplier" ? (v.supplier_id || "") : "",
                  supplier_name: v.vehicle_type === "supplier" ? (v.supplier_name || "") : "",
                });
              } else {
                setForm({ ...form, vehicle_id: "", vehicle_number: "" });
              }
            }}
            onCreateNew={() => setQaOpen("vehicle")}
            createLabel="+ Add New Vehicle"
            placeholder="Search vehicle…"
            options={vehicles
              // Iter63 · C — hide inactive vehicles from picker, but keep the
              // currently-selected one visible when editing an old trip.
              .filter((v) => v.is_active !== false || v.vehicle_number === form.vehicle_number)
              .map((v) => ({
                value: v.id,
                label: v.vehicle_number,
                meta: [
                  v.vehicle_type === "supplier" ? "Supplier" : "Own",
                  v.vehicle_type === "supplier" ? v.supplier_name : v.owner_name,
                  v.is_active === false ? "· INACTIVE" : "",
                ].filter(Boolean).join(" · "),
              }))}
          />
          <input
            data-testid="trip-vehicle"
            required
            value={form.vehicle_number}
            onChange={(e) => setForm({ ...form, vehicle_number: e.target.value.toUpperCase() })}
            className={`${inputCls} mt-1`}
            placeholder="Or type new: AP16TA1234"
          />
        </Field>
        <Field label="Driver · డ్రైవర్">
          <SearchableSelect
            dataTestId="trip-driver"
            value={form.driver_id || ""}
            onChange={(did) => {
              const d = drivers.find((x) => x.id === did);
              setForm({ ...form, driver_id: did, driver_name: d?.name || "", driver_mobile: d?.phone || form.driver_mobile });
            }}
            onCreateNew={() => setQaOpen("driver")}
            createLabel="+ Add New Driver"
            placeholder="Search driver…"
            options={drivers.map((d) => ({
              value: d.id,
              label: d.name,
              meta: d.phone || "",
            }))}
          />
        </Field>
        <Field label="Product / Load · లోడ్">
          <SearchableSelect
            dataTestId="trip-product"
            value={form.product_id || ""}
            onChange={(pid) => {
              const p = products.find((x) => x.id === pid);
              if (p) {
                setForm({
                  ...form,
                  product_id: pid,
                  load_details: p.name,
                  hsn_sac: p.hsn_sac,
                  rate_per_ton: form.freight_mode === "per_ton" && p.default_rate ? p.default_rate : form.rate_per_ton,
                });
              } else {
                setForm({ ...form, product_id: "" });
              }
            }}
            onCreateNew={() => setQaOpen("product")}
            createLabel="+ Add New Product"
            placeholder="Search product…"
            options={products.map((p) => ({
              value: p.id,
              label: p.name,
              meta: `HSN ${p.hsn_sac}${p.default_rate ? ` · ₹${p.default_rate}/MT` : ""}`,
            }))}
          />
          <input data-testid="trip-load" value={form.load_details} onChange={(e) => setForm({ ...form, load_details: e.target.value, product_id: "" })} className={`${inputCls} mt-1`} placeholder="Or type free-text load details" />
        </Field>
        <Field label="Loading Qty (in Tons) · లోడింగ్" required>
          <input data-testid="trip-tons" required type="number" step="0.001" min="0" value={form.tons} onChange={(e) => setForm({ ...form, tons: e.target.value })} className={inputCls} />
        </Field>
        <Field label="From · నుండి">
          <input data-testid="trip-from" value={form.from_location} onChange={(e) => setForm({ ...form, from_location: e.target.value })} className={inputCls} />
        </Field>
        <Field label="To · వరకు">
          <input data-testid="trip-to" value={form.to_location} onChange={(e) => setForm({ ...form, to_location: e.target.value })} className={inputCls} />
        </Field>

        {/* Iter66 · Phase B — Ship-To Site picker (only when customer has sites) */}
        <Field label="Ship-To Site · అన్‌లోడింగ్ సైట్">
          <div className="flex items-center gap-2">
            <div className="flex-1">
              <SearchableSelect
                dataTestId="trip-ship-site"
                value={form.ship_site_id || ""}
                onChange={(sid) => setForm({ ...form, ship_site_id: sid || "" })}
                placeholder={selectedCustomer ? "Select site…" : "Pick customer first"}
                options={shipSites.map((s) => ({
                  value: s.id,
                  label: s.site_name + (s.is_default ? " · Default" : ""),
                  meta: [s.address, s.state, s.pincode].filter(Boolean).join(" · "),
                }))}
              />
            </div>
            {selectedCustomer && (
              <button
                type="button"
                data-testid="trip-quickadd-ship-site-btn"
                onClick={() => setQaOpen("ship-site")}
                className="px-3 py-2 text-xs uppercase tracking-wider font-semibold bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 whitespace-nowrap"
              >+ New</button>
            )}
          </div>
          {form.ship_site_id && (() => {
            const s = shipSites.find((x) => x.id === form.ship_site_id);
            return s ? (
              <div className="text-[10px] text-zinc-600 mt-1">
                {s.address || "—"}{s.gstin ? ` · GSTIN ${s.gstin}` : ""}
              </div>
            ) : null;
          })()}
          {selectedCustomer && shipSites.length === 0 && (
            <div className="text-[10px] text-zinc-500 mt-1">No sites saved for this customer. The "To" location above will be used as the fallback ship-to on the invoice.</div>
          )}
        </Field>
        <Field label="Customer Ref / Ref No. · కస్టమర్ రిఫరెన్స్">
          <input
            data-testid="trip-customer-reference"
            value={form.customer_reference_number || ""}
            onChange={(e) => setForm({ ...form, customer_reference_number: e.target.value })}
            className={inputCls}
            placeholder="e.g. CUS-INV-2026-4567"
          />
          <div className="text-[10px] text-zinc-500 mt-1">Customer's own invoice / reference number for this trip. Blank stays blank — never inherited from another trip.</div>
        </Field>
      </div>
    </Section>
  );
}
