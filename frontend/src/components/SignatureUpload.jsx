import React, { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errMsg } from "@/api";
import { toast } from "sonner";
import { Upload, Trash2, RefreshCw, ImageIcon } from "lucide-react";

/**
 * Iter134 · Signature Upload UI Correction — operator-friendly.
 *
 * Reuses the shipped POST /api/files/upload with linked_type="company",
 * category="signature". No new file API introduced. On successful upload:
 *   – `onChange(file_id)` is fired so parent Settings state updates
 *   – `onModeAuto("image")` flips signature_mode automatically
 *
 * The raw file_id is NEVER shown as a primary input. It is kept only in
 * component state and pushed into the parent form on Save.
 */
export default function SignatureUpload({ companyId, fileId, onChange, onModeAuto }) {
  const qc = useQueryClient();
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);

  // Load the resolved file record if we have a fileId; also list previously
  // uploaded signature files for this company so replacement is trivial.
  const meta = useQuery({
    queryKey: ["signature-file", fileId],
    queryFn: async () => {
      if (!fileId) return null;
      const rows = (await api.get("/files", {
        params: { linked_type: "company", linked_id: companyId, category: "signature" },
      })).data;
      return rows.find((r) => r.id === fileId) || null;
    },
    enabled: !!fileId && !!companyId,
  });

  const pickUrl = (fid) => {
    // Signed proxy URL via existing endpoint; used only for preview.
    const base = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
    const tok = typeof window !== "undefined" ? localStorage.getItem("session_token") : "";
    // Same-origin call is preferred; add token as query for iframe/img safety
    return `${base}/api/files/${fid}/download${tok ? `?_t=${encodeURIComponent(tok)}` : ""}`;
  };

  const upload = useMutation({
    mutationFn: async (file) => {
      if (!file) return null;
      if (!/^image\/(png|jpeg|jpg|webp)$/i.test(file.type)) {
        throw new Error("Please upload a PNG, JPG or WebP image");
      }
      const fd = new FormData();
      fd.append("file", file);
      const r = await api.post(
        `/files/upload?category=signature&linked_type=company&linked_id=${encodeURIComponent(companyId)}`,
        fd,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      return r.data;
    },
    onSuccess: (data) => {
      if (!data) return;
      onChange(data.id);
      if (onModeAuto) onModeAuto("image");
      toast.success("Signature uploaded");
      qc.invalidateQueries({ queryKey: ["signature-file", data.id] });
    },
    onError: (e) => toast.error(errMsg(e, "Upload failed")),
    onSettled: () => setBusy(false),
  });

  const remove = useMutation({
    mutationFn: async () => {
      // Do NOT hard-delete the underlying file — matches project convention
      // (existing FileAttachments Trash flow soft-deletes via API); here we
      // simply detach: clear the signature_file_id so the PDF reverts to
      // text-only. Old file remains for audit history.
      onChange("");
      return true;
    },
    onSuccess: () => toast.success("Signature detached (previous file retained for audit)"),
  });

  const onPick = (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setBusy(true);
    upload.mutate(f);
  };

  return (
    <div className="space-y-2" data-testid="signature-upload">
      <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
        Signature Image
      </div>
      {fileId ? (
        <div className="flex items-start gap-3 border border-zinc-200 rounded-sm p-3 bg-white">
          <div className="w-32 h-16 border rounded-sm bg-zinc-50 flex items-center justify-center overflow-hidden shrink-0">
            <img
              src={pickUrl(fileId)}
              alt="signature"
              className="max-w-full max-h-full object-contain"
              data-testid="signature-preview"
              onError={(e) => { e.currentTarget.style.display = "none"; }}
            />
          </div>
          <div className="flex-1 text-xs">
            <div className="font-semibold" data-testid="signature-filename">
              {meta.data?.filename || (fileId ? "Signature configured" : "—")}
            </div>
            {meta.data?.size ? (
              <div className="text-zinc-500 text-[11px] mt-0.5">
                {(meta.data.size / 1024).toFixed(1)} KB · {meta.data.content_type || "image"}
              </div>
            ) : null}
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                data-testid="signature-replace-btn"
                disabled={busy || !companyId}
                onClick={() => inputRef.current?.click()}
                className="text-xs px-2 py-1 border border-zinc-300 rounded-sm hover:bg-zinc-950 hover:text-white inline-flex items-center gap-1 disabled:opacity-50"
              >
                <RefreshCw size={12} /> Replace Signature
              </button>
              <button
                type="button"
                data-testid="signature-remove-btn"
                disabled={busy}
                onClick={() => remove.mutate()}
                className="text-xs px-2 py-1 border border-rose-300 text-rose-700 rounded-sm hover:bg-rose-50 inline-flex items-center gap-1 disabled:opacity-50"
              >
                <Trash2 size={12} /> Remove
              </button>
            </div>
          </div>
        </div>
      ) : (
        <button
          type="button"
          data-testid="signature-upload-btn"
          disabled={busy || !companyId}
          onClick={() => inputRef.current?.click()}
          className="w-full border-2 border-dashed border-zinc-300 rounded-sm py-6 text-sm text-zinc-600 hover:border-zinc-950 hover:text-zinc-900 inline-flex flex-col items-center gap-2 disabled:opacity-50"
        >
          <ImageIcon size={20} />
          <span className="font-semibold inline-flex items-center gap-2">
            <Upload size={14} /> Upload Signature
          </span>
          <span className="text-[11px] text-zinc-500">PNG, JPG or WebP · max ~5 MB</span>
        </button>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        data-testid="signature-file-input"
        onChange={onPick}
      />
      <p className="text-[11px] text-zinc-500">
        The uploaded image appears inside the existing signature cell of the invoice PDF. This
        is a decorative signature — not a legally-binding digital signature (DSC).
      </p>
    </div>
  );
}
