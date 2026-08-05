import React, { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, API } from "@/api";
import { toast } from "sonner";
import { Upload, Trash2, File as FileIcon, Image as ImageIcon, FileText, Download } from "lucide-react";

const CATEGORIES = [
  { value: "general", label: "General" },
  { value: "vehicle_doc", label: "Vehicle Document" },
  { value: "fuel_bill", label: "Fuel Bill" },
  { value: "lr_proof", label: "LR / Proof" },
  { value: "trip_attachment", label: "Trip Attachment" },
];

const iconFor = (ct) => {
  if (!ct) return FileIcon;
  if (ct.startsWith("image/")) return ImageIcon;
  if (ct === "application/pdf") return FileText;
  return FileIcon;
};

const fmtSize = (n) => {
  if (!n) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
};

export default function Files() {
  const qc = useQueryClient();
  const [category, setCategory] = useState("general");
  const [uploading, setUploading] = useState(false);
  const [preview, setPreview] = useState(null);

  const { data: files = [] } = useQuery({
    queryKey: ["files"],
    queryFn: async () => (await api.get("/files")).data,
  });

  const del = useMutation({
    mutationFn: async (id) => (await api.delete(`/files/${id}`)).data,
    onSuccess: () => { toast.success("Deleted"); qc.invalidateQueries({ queryKey: ["files"] }); },
  });

  const onUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) { toast.error("Max 10MB"); return; }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      await api.post(`/files/upload?category=${encodeURIComponent(category)}`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success("Uploaded");
      qc.invalidateQueries({ queryKey: ["files"] });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const openPreview = async (f) => {
    try {
      const res = await api.get(`/files/${f.id}/download`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      setPreview({ url, name: f.original_filename, type: f.content_type });
    } catch { toast.error("Fetch failed"); }
  };

  useEffect(() => () => { if (preview?.url) URL.revokeObjectURL(preview.url); }, [preview]);

  return (
    <div className="space-y-6" data-testid="files-page">
      <header className="flex items-end justify-between border-b border-zinc-200 pb-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Storage</div>
          <h1 className="mt-1 text-4xl font-black tracking-tighter">
            <span className="telugu">ఫైల్‌లు</span>
            <span className="text-zinc-400"> · Files</span>
          </h1>
        </div>
      </header>

      <section className="border border-zinc-200 bg-white rounded-sm p-5">
        <div className="text-sm font-bold uppercase tracking-wider mb-3">Upload New File</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Category</label>
            <select data-testid="file-category" value={category} onChange={(e) => setCategory(e.target.value)} className="mt-1 w-full border border-zinc-300 px-3 py-2 rounded-sm text-sm">
              {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </div>
          <div className="md:col-span-2">
            <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">File (max 10MB)</label>
            <input
              data-testid="file-upload-input"
              type="file"
              accept="image/*,application/pdf,.csv,.txt,.json"
              disabled={uploading}
              onChange={onUpload}
              className="mt-1 w-full text-sm border border-zinc-300 rounded-sm px-3 py-2"
            />
            {uploading && <div className="text-xs text-zinc-500 mt-1">Uploading...</div>}
          </div>
        </div>
        <div className="text-xs text-zinc-500 mt-2">Files are stored securely with Emergent Object Storage. Each user has an isolated bucket prefix.</div>
      </section>

      <section className="border border-zinc-200 bg-white rounded-sm">
        <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">Your Files ({files.length})</div>
        <table className="w-full text-sm" data-testid="files-table">
          <thead className="bg-zinc-50 text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="px-4 py-2 text-left">Name</th>
              <th className="px-4 py-2 text-left">Category</th>
              <th className="px-4 py-2 text-left">Type</th>
              <th className="px-4 py-2 text-right">Size</th>
              <th className="px-4 py-2 text-left">Uploaded</th>
              <th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {files.map((f) => {
              const Icon = iconFor(f.content_type);
              return (
                <tr key={f.id} data-testid={`file-row-${f.id}`} className="border-t border-zinc-100">
                  <td className="px-4 py-2 flex items-center gap-2">
                    <Icon size={14} className="text-zinc-500" />
                    <span className="font-semibold text-sm">{f.original_filename}</span>
                  </td>
                  <td className="px-4 py-2 text-xs">{CATEGORIES.find((c) => c.value === f.category)?.label || f.category}</td>
                  <td className="px-4 py-2 text-xs text-zinc-500 font-mono">{f.content_type}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs">{fmtSize(f.size)}</td>
                  <td className="px-4 py-2 text-xs">{new Date(f.created_at).toLocaleDateString("en-IN")}</td>
                  <td className="px-4 py-2 text-right whitespace-nowrap">
                    <button data-testid={`preview-${f.id}`} onClick={() => openPreview(f)} className="text-xs px-2 py-1 border border-zinc-200 rounded-sm hover:bg-zinc-950 hover:text-white mr-1">
                      Preview
                    </button>
                    <button data-testid={`delete-file-${f.id}`} onClick={() => { if (window.confirm("Soft-delete this file?")) del.mutate(f.id); }} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-50">
                      <Trash2 size={12} /> Delete
                    </button>
                  </td>
                </tr>
              );
            })}
            {files.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-12 text-center text-zinc-400">No files yet.</td></tr>
            )}
          </tbody>
        </table>
      </section>

      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/70 backdrop-blur-sm p-4" onClick={() => setPreview(null)} data-testid="file-preview-modal">
          <div className="bg-white border border-zinc-950 rounded-sm max-w-4xl w-full max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
              <div className="font-bold truncate">{preview.name}</div>
              <div className="flex gap-2">
                <a href={preview.url} download={preview.name} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white">
                  <Download size={12} /> Download
                </a>
                <button onClick={() => setPreview(null)} className="text-xs px-2 py-1 border border-zinc-300 rounded-sm">Close</button>
              </div>
            </div>
            <div className="p-4">
              {preview.type?.startsWith("image/") ? (
                <img src={preview.url} alt={preview.name} className="max-w-full mx-auto" />
              ) : preview.type === "application/pdf" ? (
                <iframe title="pdf" src={preview.url} className="w-full h-[75vh]" />
              ) : (
                <div className="text-center text-zinc-500 text-sm py-10">No inline preview available. Click Download.</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
