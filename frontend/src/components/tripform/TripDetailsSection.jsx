// Iter55 — Extracted verbatim from TripForm.jsx. Pure JSX; state lives in parent.
import React from "react";
import SearchableSelect from "@/components/SearchableSelect";
import { Section, Field } from "./FormPrimitives";
import { inputCls } from "./tripFormDefaults";

export default function TripDetailsSection({
  form, setForm,
  customers, vehicles, drivers, products,
  setQaOpen,
}) {
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
            onChange={(v) => setForm({ ...form, customer_id: v })}
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
      </div>
    </Section>
  );
}
