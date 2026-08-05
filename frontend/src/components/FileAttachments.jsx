import React, { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { toast } from "sonner";
import { Upload, Trash2, Paperclip, Eye } from "lucide-react";

const fmtSize = (n) => {
  if (!n) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
};

/**
 * Reusable inline file attachments component.
 * Props: linkedType (vehicle|trip|fuel), linkedId (string), category (vehicle_doc|trip_attachment|fuel_bill|...), title
 */
export default function FileAttachments({ linkedType, linkedId, category, title = "Attachments", accept = "image/*,application/pdf" }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null);

  const enabled = Boolean(linkedType && linkedId);
  const { data: files = [] } = useQuery({
    queryKey: ["file-attachments", linkedType, linkedId],
    queryFn: async () => (await api.get("/files", { params: { linked_type: linkedType, linked_id: linkedId } })).data,
    enabled,
  });

  const onUpload = async (e) => {
    const list = Array.from(e.target.files || []);
    if (list.length === 0) return;
    setBusy(true);
    try {
      for (const file of list) {
        const fd = new FormData();
        fd.append("file", file);
        await api.post(
          `/files/upload?category=${encodeURIComponent(category)}&linked_type=${encodeURIComponent(linkedType)}&linked_id=${encodeURIComponent(linkedId)}`,
          fd,
          { headers: { "Content-Type": "multipart/form-data" } },
        );
      }
      toast.success(`${list.length} file(s) attached`);
      qc.invalidateQueries({ queryKey: ["file-attachments", linkedType, linkedId] });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Upload failed");
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  };

  const del = useMutation({
    mutationFn: async (id) => (await api.delete(`/files/${id}`)).data,
    onSuccess: () => { toast.success("Deleted"); qc.invalidateQueries({ queryKey: ["file-attachments", linkedType, linkedId] }); },
  });

  const showPreview = async (f) => {
    try {
      const res = await api.get(`/files/${f.id}/download`, { responseType: "blob" });
      setPreview({ url: URL.createObjectURL(res.data), name: f.original_filename, type: f.content_type });
    } catch { toast.error("Fetch failed"); }
  };

  useEffect(() => () => { if (preview?.url) URL.revokeObjectURL(preview.url); }, [preview]);

  if (!enabled) {
    return (
      <div className="border border-dashed border-zinc-300 rounded-sm p-4 text-xs text-zinc-500 bg-zinc-50" data-testid="attachments-disabled">
        Save {linkedType} first to attach files.
      </div>
    );
  }

  return (
    <div className="border border-zinc-200 rounded-sm bg-white" data-testid={`attachments-${linkedType}`}>
      <div className="px-4 py-2 border-b border-zinc-200 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider"><Paperclip size={12} /> {title} ({files.length})</div>
        <label className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-zinc-950 rounded-sm cursor-pointer hover:bg-zinc-950 hover:text-white">
          <Upload size={12} /> {busy ? "Uploading..." : "Add"}
          <input data-testid={`attach-input-${linkedType}`} type="file" multiple accept={accept} onChange={onUpload} disabled={busy} className="hidden" />
        </label>
      </div>
      {files.length > 0 ? (
        <ul className="divide-y divide-zinc-100">
          {files.map((f) => (
            <li key={f.id} data-testid={`attach-row-${f.id}`} className="px-4 py-2 flex items-center justify-between text-sm">
              <div className="min-w-0">
                <div className="truncate font-semibold">{f.original_filename}</div>
                <div className="text-[10px] text-zinc-500 uppercase tracking-wider">{f.content_type} · {fmtSize(f.size)}</div>
              </div>
              <div className="flex gap-1">
                <button data-testid={`view-attach-${f.id}`} onClick={() => showPreview(f)} className="text-xs px-2 py-1 border border-zinc-200 rounded-sm hover:bg-zinc-950 hover:text-white">
                  <Eye size={12} />
                </button>
                <button data-testid={`del-attach-${f.id}`} onClick={() => { if (window.confirm("Delete?")) del.mutate(f.id); }} className="text-xs px-2 py-1 border border-rose-200 text-rose-700 rounded-sm hover:bg-rose-50">
                  <Trash2 size={12} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <div className="px-4 py-6 text-center text-xs text-zinc-400">No files attached.</div>
      )}

      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/70 backdrop-blur-sm p-4" onClick={() => setPreview(null)}>
          <div className="bg-white border border-zinc-950 rounded-sm max-w-4xl w-full max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200">
              <div className="font-bold truncate">{preview.name}</div>
              <button onClick={() => setPreview(null)} className="text-xs px-2 py-1 border border-zinc-300 rounded-sm">Close</button>
            </div>
            <div className="p-4">
              {preview.type?.startsWith("image/") ? (
                <img src={preview.url} alt={preview.name} className="max-w-full mx-auto" />
              ) : preview.type === "application/pdf" ? (
                <iframe title="pdf" src={preview.url} className="w-full h-[75vh]" />
              ) : (
                <a href={preview.url} download={preview.name} className="inline-block text-sm px-4 py-2 bg-zinc-950 text-white rounded-sm">Download</a>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
