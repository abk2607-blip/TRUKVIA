import React, { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { Save, Upload, Trash2 } from "lucide-react";
import { StateSelect } from "@/lib/states";
import SignatureUpload from "@/components/SignatureUpload";
import BankAccountsSection from "@/components/BankAccountsSection";

const EMPTY = {
  name: "", address: "", phone: "", email: "",
  gstin: "", pan: "", state: "",
  bank_name: "", account_number: "", ifsc: "", branch: "",
  hsn_sac: "996791", invoice_prefix: "INV", next_invoice_number: 1,
  logo: "",
  udyam_registration: "",
};

export default function Settings() {
  const qc = useQueryClient();
  const [form, setForm] = useState(EMPTY);
  const fileRef = useRef();

  const { data } = useQuery({ queryKey: ["company"], queryFn: async () => (await api.get("/company")).data });
  const { data: companies = [] } = useQuery({
    queryKey: ["companies"],
    queryFn: async () => (await api.get("/companies")).data,
  });

  useEffect(() => { if (data) setForm({ ...EMPTY, ...data }); }, [data]);

  const save = useMutation({
    mutationFn: async () => (await api.put("/company", { ...form, next_invoice_number: Number(form.next_invoice_number) })).data,
    onSuccess: () => { toast.success("Settings saved"); qc.invalidateQueries({ queryKey: ["company"] }); qc.invalidateQueries({ queryKey: ["companies"] }); },
    onError: () => toast.error("Failed to save"),
  });

  const addCompany = useMutation({
    mutationFn: async (name) => (await api.post("/companies", { name })).data,
    onSuccess: () => { toast.success("Company added"); qc.invalidateQueries({ queryKey: ["companies"] }); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });
  const setDefault = useMutation({
    mutationFn: async (cid) => (await api.post(`/companies/${cid}/set-default`)).data,
    onSuccess: () => { toast.success("Default updated"); qc.invalidateQueries({ queryKey: ["companies"] }); },
  });
  const delCompany = useMutation({
    mutationFn: async (cid) => (await api.delete(`/companies/${cid}`)).data,
    onSuccess: () => { toast.success("Company deleted"); qc.invalidateQueries({ queryKey: ["companies"] }); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed"),
  });

  const uploadLogo = useMutation({
    mutationFn: async (file) => {
      const fd = new FormData();
      fd.append("file", file);
      return (await api.post("/company/logo", fd, { headers: { "Content-Type": "multipart/form-data" } })).data;
    },
    onSuccess: (d) => { toast.success("Logo uploaded"); setForm({ ...form, logo: d.logo }); qc.invalidateQueries({ queryKey: ["company"] }); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Upload failed"),
  });

  const removeLogo = useMutation({
    mutationFn: async () => (await api.delete("/company/logo")).data,
    onSuccess: () => { toast.success("Logo removed"); setForm({ ...form, logo: "" }); qc.invalidateQueries({ queryKey: ["company"] }); },
  });

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="space-y-6" data-testid="settings-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Configuration</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">సెట్టింగ్‌లు</span>
            <span className="text-zinc-400"> · Company Settings</span>
          </h1>
        </div>
        <button data-testid="save-settings-btn" onClick={() => save.mutate()} disabled={save.isPending} className="inline-flex items-center gap-2 px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800">
          <Save size={14} /> {save.isPending ? "Saving..." : "Save"}
        </button>
      </header>

      <section className="border border-zinc-950 bg-white rounded-sm" data-testid="companies-section">
        <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider flex items-center justify-between">
          <span>All Companies · అన్ని కంపెనీలు</span>
          <button data-testid="add-company-btn" onClick={() => {
            const name = window.prompt("New company name?");
            if (name && name.trim()) addCompany.mutate(name.trim());
          }} className="text-[10px] uppercase tracking-wider px-2 py-1 bg-zinc-950 text-white rounded-sm">+ Add</button>
        </div>
        <div className="p-5 space-y-2">
          {companies.map((c) => (
            <div key={c.id} data-testid={`company-row-${c.id}`} className="flex items-center gap-3 border border-zinc-200 p-2 rounded-sm">
              <div className="flex-1">
                <div className="font-semibold">{c.name || "(unnamed)"}</div>
                <div className="text-[10px] text-zinc-500">{c.state || "State not set"} · GSTIN {c.gstin || "—"} · Prefix {c.invoice_prefix}</div>
              </div>
              {c.is_default ? (
                <span className="text-[10px] uppercase tracking-wider bg-emerald-100 text-emerald-800 px-2 py-1 rounded-sm font-bold">Default</span>
              ) : (
                <button data-testid={`set-default-${c.id}`} onClick={() => setDefault.mutate(c.id)} className="text-[10px] uppercase tracking-wider border border-zinc-200 px-2 py-1 rounded-sm hover:bg-zinc-950 hover:text-white">Make Default</button>
              )}
              {companies.length > 1 && (
                <button data-testid={`delete-company-${c.id}`} onClick={() => window.confirm(`Delete "${c.name}"? Its trips/invoices will be orphaned.`) && delCompany.mutate(c.id)} className="text-[10px] uppercase tracking-wider border border-rose-200 text-rose-700 px-2 py-1 rounded-sm hover:bg-rose-50">Delete</button>
              )}
            </div>
          ))}
          {companies.length === 0 && <div className="text-sm text-zinc-500">No companies yet — a default will be created automatically.</div>}
          <div className="text-[11px] text-zinc-500 bg-zinc-50 border border-zinc-100 rounded-sm p-2">
            Switch active company anytime from the sidebar dropdown. Trips, invoices, reports are scoped per-company. Customers, vehicles, drivers, products are shared across companies.
          </div>
        </div>
      </section>

      <section className="border border-zinc-200 bg-white rounded-sm" data-testid="logo-section">
        <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">Logo · లోగో</div>
        <div className="p-5 flex items-center gap-5">
          <div className="w-24 h-24 border-2 border-dashed border-zinc-300 rounded-sm flex items-center justify-center bg-zinc-50">
            {form.logo ? (
              <img data-testid="logo-preview" src={form.logo} alt="Company logo" className="max-w-full max-h-full object-contain" />
            ) : (
              <span className="text-[10px] text-zinc-400 text-center px-2">No logo</span>
            )}
          </div>
          <div className="flex-1">
            <input
              ref={fileRef}
              data-testid="logo-file-input"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadLogo.mutate(f); }}
              className="hidden"
            />
            <div className="flex gap-2">
              <button
                type="button"
                data-testid="upload-logo-btn"
                onClick={() => fileRef.current?.click()}
                disabled={uploadLogo.isPending}
                className="inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider border border-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white"
              >
                <Upload size={14} /> {uploadLogo.isPending ? "Uploading..." : "Upload Logo"}
              </button>
              {form.logo && (
                <button
                  type="button"
                  data-testid="remove-logo-btn"
                  onClick={() => { if (window.confirm("Remove logo?")) removeLogo.mutate(); }}
                  className="inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-50"
                >
                  <Trash2 size={14} /> Remove
                </button>
              )}
            </div>
            <div className="mt-2 text-xs text-zinc-500">PNG / JPG / WEBP · max 1MB · appears on the top-left of every invoice PDF</div>
          </div>
        </div>
      </section>

      <section className="border border-zinc-200 bg-white rounded-sm">
        <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">Company · సంస్థ</div>
        <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
          <F label="Company Name · పేరు"><input data-testid="setting-name" value={form.name} onChange={set("name")} className={inputCls} /></F>
          <F label="Phone · ఫోన్"><input data-testid="setting-phone" value={form.phone} onChange={set("phone")} className={inputCls} /></F>
          <div className="md:col-span-2">
            <F label="Address · చిరునామా"><textarea data-testid="setting-address" rows={3} value={form.address} onChange={set("address")} className={inputCls} /></F>
          </div>
          <F label="Email"><input data-testid="setting-email" value={form.email} onChange={set("email")} className={inputCls} /></F>
          <F label="State · రాష్ట్రం"><StateSelect value={form.state} onChange={(v) => setForm({ ...form, state: v })} dataTestId="setting-state" className={inputCls + " bg-white"} /></F>
          <F label="GSTIN"><input data-testid="setting-gstin" value={form.gstin} onChange={set("gstin")} className={inputCls} /></F>
          <F label="PAN"><input data-testid="setting-pan" value={form.pan} onChange={set("pan")} className={inputCls} /></F>
          <F label="HSN/SAC (default 996791)"><input data-testid="setting-hsn" value={form.hsn_sac} onChange={set("hsn_sac")} className={inputCls} /></F>
          <div className="md:col-span-2">
            <F label="MSME / Udyam Registration No · MSME / ఉద్యమ్ రిజిస్ట్రేషన్ నెంబర్">
              <input
                data-testid="setting-udyam"
                value={form.udyam_registration}
                onChange={set("udyam_registration")}
                placeholder="UDYAM-AP-01-1234567"
                className={inputCls}
              />
              <div className="text-[10px] text-zinc-500 mt-1">Appears in the Terms &amp; Conditions section of every Transport Invoice PDF for this company.</div>
            </F>
          </div>
        </div>
      </section>

      <section className="border border-zinc-200 bg-white rounded-sm">
        <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">Bank · బ్యాంక్ వివరాలు</div>
        <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
          <F label="Bank Name"><input data-testid="setting-bank" value={form.bank_name} onChange={set("bank_name")} className={inputCls} /></F>
          <F label="Account No"><input data-testid="setting-account" value={form.account_number} onChange={set("account_number")} className={inputCls} /></F>
          <F label="IFSC"><input data-testid="setting-ifsc" value={form.ifsc} onChange={set("ifsc")} className={inputCls} /></F>
          <F label="Branch"><input data-testid="setting-branch" value={form.branch} onChange={set("branch")} className={inputCls} /></F>
        </div>
        <div className="px-5 pb-5">
          <BankAccountsSection kind="company" />
        </div>
      </section>

      <section className="border border-zinc-200 bg-white rounded-sm">
        <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">Invoice Numbering</div>
        <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
          <F label="Invoice Prefix"><input data-testid="setting-prefix" value={form.invoice_prefix} onChange={set("invoice_prefix")} className={inputCls} /></F>
          <F label="Next Invoice Number (legacy fallback)"><input data-testid="setting-next-num" type="number" min="1" value={form.next_invoice_number} onChange={set("next_invoice_number")} className={inputCls} /></F>
          <div className="md:col-span-2 text-[11px] text-zinc-500">
            From Iter134 the running sequence is FY-scoped. `Next Invoice Number` is retained as a one-time seed for the current FY only.
          </div>
        </div>
      </section>

      <section className="border border-zinc-200 bg-white rounded-sm">
        <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">Invoice Presentation (Iter134)</div>
        <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
          <F label="Authorised Signatory Name">
            <input data-testid="setting-signatory-name" value={form.authorised_signatory_name || ""}
              onChange={set("authorised_signatory_name")} className={inputCls} placeholder="e.g. Rajesh Kumar" />
          </F>
          <F label="Authorised Signatory Designation">
            <input data-testid="setting-signatory-designation" value={form.authorised_signatory_designation || ""}
              onChange={set("authorised_signatory_designation")} className={inputCls} placeholder="e.g. Partner" />
          </F>
          <F label="Jurisdiction (empty = clause hidden)">
            <input data-testid="setting-jurisdiction" value={form.jurisdiction || ""}
              onChange={set("jurisdiction")} className={inputCls} placeholder="e.g. Vijayawada" />
          </F>
          <F label="System-generated Note (max 200 chars)">
            <input data-testid="setting-system-note" maxLength={200} value={form.system_generated_note || ""}
              onChange={set("system_generated_note")} className={inputCls}
              placeholder="e.g. This is a computer-generated tax invoice." />
          </F>
          <div className="md:col-span-2">
            <SignatureUpload
              companyId={form.id || ""}
              fileId={form.signature_file_id || ""}
              onChange={(fid) => setForm((f) => ({
                ...f,
                signature_file_id: fid,
                // Keep signature_mode consistent with presence of an image
                signature_mode: fid ? "image" : (f.signature_mode === "image" ? "none" : f.signature_mode),
              }))}
              onModeAuto={(mode) => setForm((f) => ({ ...f, signature_mode: mode }))}
            />
          </div>
          <F label="Signature Mode">
            <select data-testid="setting-signature-mode" value={form.signature_mode || "image"}
              onChange={set("signature_mode")} className={inputCls}>
              <option value="none">None (text-only signature block)</option>
              <option value="image">Signature Image</option>
              <option value="dsc" disabled>Digital Signature / DSC (future — not active)</option>
            </select>
          </F>
        </div>
      </section>
    </div>
  );
}

const inputCls = "w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none bg-white";

function F({ label, children }) {
  return (
    <div>
      <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">{label}</label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
