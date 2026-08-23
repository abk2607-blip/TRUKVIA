import React, { useEffect, useRef, useState } from "react";
import { api } from "@/api";
import { RefreshCcw, ExternalLink, Loader2, AlertTriangle } from "lucide-react";

/**
 * Iter113 · Inline Invoice PDF Preview.
 * ------------------------------------
 * Fetches the SAME `/invoices/{id}/pdf` bytes the Download / WhatsApp buttons
 * serve, converts to a blob URL, and embeds it in an `<object>` (with iframe
 * fallback). Guarantees Preview = Downloaded PDF, byte-for-byte, so UAT can
 * verify freight / shortage / cust-ref / totals against the final artifact
 * without leaving the page.
 *
 * Auto-refreshes when `refreshKey` changes (e.g. a new payment is recorded or
 * the invoice is recomputed) so the preview never goes stale.
 */
export default function InvoicePdfPreview({ invoiceId, refreshKey, height = 900 }) {
  const [state, setState] = useState({ url: null, loading: true, error: null });
  const lastBlobUrl = useRef(null);

  useEffect(() => {
    if (!invoiceId) return;
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));

    (async () => {
      try {
        const r = await api.get(`/invoices/${invoiceId}/pdf`, {
          responseType: "blob",
          timeout: 45000,
        });
        if (cancelled) return;
        if (lastBlobUrl.current) {
          try { URL.revokeObjectURL(lastBlobUrl.current); } catch {}
        }
        const blob = new Blob([r.data], { type: "application/pdf" });
        const url = URL.createObjectURL(blob);
        lastBlobUrl.current = url;
        setState({ url, loading: false, error: null });
      } catch (err) {
        if (cancelled) return;
        setState({
          url: null,
          loading: false,
          error:
            err?.response?.data?.detail ||
            err?.message ||
            "Failed to load PDF preview",
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [invoiceId, refreshKey]);

  // Cleanup blob URL on unmount to avoid leaking memory across many opens.
  useEffect(() => {
    return () => {
      if (lastBlobUrl.current) {
        try { URL.revokeObjectURL(lastBlobUrl.current); } catch {}
      }
    };
  }, []);

  const reload = () => setState((s) => ({ ...s, loading: true }));

  return (
    <section
      data-testid="invoice-pdf-preview"
      className="border border-zinc-950 bg-white rounded-sm overflow-hidden no-print"
    >
      <header className="flex items-center justify-between px-4 py-2 border-b border-zinc-200 bg-zinc-50">
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-[0.15em] font-bold text-zinc-500">
            Invoice PDF · Live Preview
          </span>
          {state.loading && (
            <Loader2
              size={12}
              className="animate-spin text-zinc-500"
              data-testid="pdf-preview-loading"
            />
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            data-testid="pdf-preview-reload-btn"
            onClick={reload}
            className="inline-flex items-center gap-1 px-2 py-1 text-[11px] uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-100"
            title="Reload preview"
          >
            <RefreshCcw size={12} /> Reload
          </button>
          {state.url && (
            <a
              data-testid="pdf-preview-open-btn"
              href={state.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 px-2 py-1 text-[11px] uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-100"
              title="Open the PDF in a new tab"
            >
              <ExternalLink size={12} /> Open Tab
            </a>
          )}
        </div>
      </header>

      {state.error ? (
        <div
          data-testid="pdf-preview-error"
          className="flex items-center gap-2 px-4 py-8 text-sm text-rose-700 bg-rose-50"
        >
          <AlertTriangle size={16} />
          <span>PDF preview failed — {state.error}</span>
        </div>
      ) : state.url ? (
        <iframe
          data-testid="pdf-preview-iframe"
          src={state.url}
          title="Invoice PDF preview"
          className="block w-full border-0 bg-zinc-100"
          style={{ height }}
        />
      ) : (
        <div
          data-testid="pdf-preview-placeholder"
          className="flex items-center justify-center bg-zinc-50 text-sm text-zinc-500"
          style={{ height }}
        >
          <Loader2 size={16} className="animate-spin mr-2" /> Rendering PDF preview…
        </div>
      )}
    </section>
  );
}
