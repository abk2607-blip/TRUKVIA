import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, fmtCurrency } from "@/api";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";

const EMPTY = {
  customer_id: "",
  date: new Date().toISOString().slice(0, 10),
  vehicle_number: "",
  driver_id: "",
  driver_name: "",
  load_details: "Bitumen VG 40",
  tons: 0,
  from_location: "",
  to_location: "",
  freight_mode: "per_ton",
  rate_per_ton: 0,
  fixed_amount: 0,
  expenses: { diesel: 0, toll: 0, batta: 0, repair: 0, other: 0 },
  notes: "",
};

export default function TripForm() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { id } = useParams();
  const isEdit = Boolean(id);
  const [form, setForm] = useState(EMPTY);

  const { data: customers = [] } = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get("/customers")).data });
  const { data: drivers = [] } = useQuery({ queryKey: ["drivers"], queryFn: async () => (await api.get("/drivers")).data });

  const { data: trip } = useQuery({
    queryKey: ["trip", id],
    queryFn: async () => (await api.get("/trips")).data.find((t) => t.id === id),
    enabled: isEdit,
  });

  useEffect(() => {
    if (trip) setForm({ ...EMPTY, ...trip, expenses: { ...EMPTY.expenses, ...(trip.expenses || {}) } });
  }, [trip]);

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        ...form,
        tons: Number(form.tons),
        rate_per_ton: Number(form.rate_per_ton),
        fixed_amount: Number(form.fixed_amount),
        expenses: Object.fromEntries(Object.entries(form.expenses).map(([k, v]) => [k, Number(v || 0)])),
      };
      if (isEdit) return (await api.put(`/trips/${id}`, payload)).data;
      return (await api.post("/trips", payload)).data;
    },
    onSuccess: () => {
      toast.success(isEdit ? "Trip updated" : "Trip created");
      qc.invalidateQueries({ queryKey: ["trips"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      nav("/trips");
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  // Live computed
  const freight = form.freight_mode === "per_ton"
    ? Number(form.tons || 0) * Number(form.rate_per_ton || 0)
    : Number(form.fixed_amount || 0);
  const totalExpense = Object.values(form.expenses).reduce((s, v) => s + Number(v || 0), 0);
  const profit = freight - totalExpense;

  const setExp = (k, v) => setForm({ ...form, expenses: { ...form.expenses, [k]: v } });

  return (
    <div className="space-y-6" data-testid="trip-form-page">
      <header className="flex items-center gap-3 border-b border-zinc-200 pb-4">
        <button onClick={() => nav(-1)} className="p-2 border border-zinc-200 rounded-sm"><ArrowLeft size={16} /></button>
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Trip Entry</div>
          <h1 className="text-3xl font-black tracking-tighter">
            <span className="telugu">{isEdit ? "ట్రిప్ ఎడిట్" : "కొత్త ట్రిప్"}</span>
            <span className="text-zinc-400"> · {isEdit ? "Edit Trip" : "New Trip"}</span>
          </h1>
        </div>
      </header>

      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-6">
        {/* Basic Details */}
        <Section title="వివరాలు · Trip Details">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Field label="Date · తేదీ" required>
              <input type="date" data-testid="trip-date" required value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Customer · కస్టమర్" required>
              <select data-testid="trip-customer" required value={form.customer_id} onChange={(e) => setForm({ ...form, customer_id: e.target.value })} className={inputCls}>
                <option value="">-- Select Customer --</option>
                {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
            <Field label="Vehicle No · వాహనం" required>
              <input data-testid="trip-vehicle" required value={form.vehicle_number} onChange={(e) => setForm({ ...form, vehicle_number: e.target.value.toUpperCase() })} className={inputCls} placeholder="AP16TA1234" />
            </Field>
            <Field label="Driver · డ్రైవర్">
              <select
                data-testid="trip-driver"
                value={form.driver_id || ""}
                onChange={(e) => {
                  const id = e.target.value;
                  const d = drivers.find((x) => x.id === id);
                  setForm({ ...form, driver_id: id, driver_name: d?.name || "" });
                }}
                className={inputCls}
              >
                <option value="">-- Select Driver --</option>
                {drivers.map((d) => <option key={d.id} value={d.id}>{d.name}{d.phone ? ` · ${d.phone}` : ""}</option>)}
              </select>
            </Field>
            <Field label="Load · లోడ్">
              <input data-testid="trip-load" value={form.load_details} onChange={(e) => setForm({ ...form, load_details: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Tons · టన్నులు" required>
              <input data-testid="trip-tons" required type="number" step="0.01" min="0" value={form.tons} onChange={(e) => setForm({ ...form, tons: e.target.value })} className={inputCls} />
            </Field>
            <Field label="From · నుండి">
              <input data-testid="trip-from" value={form.from_location} onChange={(e) => setForm({ ...form, from_location: e.target.value })} className={inputCls} />
            </Field>
            <Field label="To · వరకు">
              <input data-testid="trip-to" value={form.to_location} onChange={(e) => setForm({ ...form, to_location: e.target.value })} className={inputCls} />
            </Field>
          </div>
        </Section>

        {/* Freight */}
        <Section title="ఫ్రైట్ · Freight Calculation">
          <div className="flex gap-3 mb-4">
            <label data-testid="freight-mode-per-ton" className={`flex-1 border p-3 rounded-sm cursor-pointer ${form.freight_mode === "per_ton" ? "border-zinc-950 bg-zinc-50" : "border-zinc-200"}`}>
              <input type="radio" name="mode" checked={form.freight_mode === "per_ton"} onChange={() => setForm({ ...form, freight_mode: "per_ton" })} className="mr-2" />
              <span className="font-semibold text-sm"><span className="telugu">టన్ను ప్రకారం</span> · Per Ton</span>
              <div className="text-[11px] text-zinc-500 mt-1">Tons × Rate</div>
            </label>
            <label data-testid="freight-mode-fixed" className={`flex-1 border p-3 rounded-sm cursor-pointer ${form.freight_mode === "fixed" ? "border-zinc-950 bg-zinc-50" : "border-zinc-200"}`}>
              <input type="radio" name="mode" checked={form.freight_mode === "fixed"} onChange={() => setForm({ ...form, freight_mode: "fixed" })} className="mr-2" />
              <span className="font-semibold text-sm"><span className="telugu">రౌండ్ ట్రిప్</span> · Fixed</span>
              <div className="text-[11px] text-zinc-500 mt-1">Fixed total amount</div>
            </label>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {form.freight_mode === "per_ton" ? (
              <Field label="Rate per Ton (₹) · రేటు">
                <input data-testid="trip-rate-per-ton" type="number" step="0.01" min="0" value={form.rate_per_ton} onChange={(e) => setForm({ ...form, rate_per_ton: e.target.value })} className={inputCls} />
              </Field>
            ) : (
              <Field label="Fixed Amount (₹) · మొత్తం">
                <input data-testid="trip-fixed-amount" type="number" step="0.01" min="0" value={form.fixed_amount} onChange={(e) => setForm({ ...form, fixed_amount: e.target.value })} className={inputCls} />
              </Field>
            )}
            <div className="md:col-span-2 flex items-end justify-end">
              <div className="bg-amber-50 border border-amber-200 px-4 py-3 rounded-sm text-right" data-testid="freight-preview">
                <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Freight · ఫ్రైట్</div>
                <div className="font-mono text-2xl font-bold text-amber-900">{fmtCurrency(freight)}</div>
              </div>
            </div>
          </div>
        </Section>

        {/* Expenses */}
        <Section title="ఖర్చులు · Expenses">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {[
              ["diesel", "Diesel · డీజిల్"],
              ["toll", "Toll · టోల్"],
              ["batta", "Driver Batta · బాటా"],
              ["repair", "Repair · రిపేర్"],
              ["other", "Other · ఇతర"],
            ].map(([k, lbl]) => (
              <Field key={k} label={lbl}>
                <input data-testid={`exp-${k}`} type="number" step="0.01" min="0" value={form.expenses[k]} onChange={(e) => setExp(k, e.target.value)} className={inputCls} />
              </Field>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-3 gap-4">
            <div className="border border-zinc-200 p-3 rounded-sm text-center">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Total Expense</div>
              <div className="font-mono text-lg font-bold text-rose-700">{fmtCurrency(totalExpense)}</div>
            </div>
            <div className="border border-zinc-200 p-3 rounded-sm text-center">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Freight</div>
              <div className="font-mono text-lg font-bold">{fmtCurrency(freight)}</div>
            </div>
            <div className={`border p-3 rounded-sm text-center ${profit >= 0 ? "border-emerald-300 bg-emerald-50" : "border-rose-300 bg-rose-50"}`} data-testid="trip-profit-preview">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Profit · లాభం</div>
              <div className={`font-mono text-lg font-bold ${profit >= 0 ? "text-emerald-800" : "text-rose-800"}`}>{fmtCurrency(profit)}</div>
            </div>
          </div>
        </Section>

        <Section title="గమనికలు · Notes">
          <textarea data-testid="trip-notes" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={inputCls} />
        </Section>

        <div className="flex justify-end gap-2">
          <button type="button" onClick={() => nav(-1)} className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm">Cancel</button>
          <button data-testid="save-trip-btn" type="submit" disabled={save.isPending} className="px-6 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50">
            {save.isPending ? "Saving..." : (isEdit ? "Update Trip" : "Save Trip")}
          </button>
        </div>
      </form>
    </div>
  );
}

const inputCls = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";

function Section({ title, children }) {
  return (
    <section className="border border-zinc-200 bg-white rounded-sm">
      <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">
        {title}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function Field({ label, required, children }) {
  return (
    <div>
      <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
        {label}{required && " *"}
      </label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
