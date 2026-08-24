// Iter101 — Fetch protected PDF endpoints with the Bearer token attached
// and open the result via a Blob URL. This is required because <a href>
// browser navigation cannot attach the Authorization header (we don't use
// cookie auth), so the previous `<a href={.../lr}>` opened a 401 page.
import { api, errMsg } from "@/api";
import { toast } from "sonner";

async function _openBlob(pdfData, filenameHint) {
  const url = URL.createObjectURL(new Blob([pdfData], { type: "application/pdf" }));
  // Open in new tab — the PDF viewer renders the preview and offers Download.
  const win = window.open(url, "_blank");
  if (!win) {
    // Pop-up blocked — trigger a plain download instead.
    const a = document.createElement("a");
    a.href = url;
    a.download = filenameHint || "document.pdf";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
  // Release the URL after 90s — long enough for the tab to finish loading.
  setTimeout(() => URL.revokeObjectURL(url), 90_000);
}

export async function openTripLrPdf(tripId, filenameHint, opts = {}) {
  try {
    const copy = (opts.copy || "original").toLowerCase();
    const res = await api.get(`/trips/${tripId}/lr`, {
      responseType: "blob",
      timeout: 45_000,
      params: { copy },
    });
    const suffix = copy !== "original" ? `_${copy.toUpperCase()}` : "";
    await _openBlob(res.data, filenameHint || `LR_${tripId}${suffix}.pdf`);
  } catch (e) {
    toast.error(errMsg(e, "LR download failed"));
    throw e;
  }
}

// Iter122 — Download a ZIP containing all three LR carriage copies
// (Original / Duplicate / Triplicate). Uses the same Bearer-token pattern as
// openTripLrPdf so the auth header rides along.
export async function downloadTripLrAllCopiesZip(tripId, filenameHint) {
  try {
    const res = await api.get(`/trips/${tripId}/lr/all-copies`, {
      responseType: "blob",
      timeout: 60_000,
    });
    const url = URL.createObjectURL(new Blob([res.data], { type: "application/zip" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = filenameHint || `LR_${tripId}_all_copies.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 90_000);
    toast.success("All 3 LR copies downloaded (Original · Duplicate · Triplicate)");
  } catch (e) {
    toast.error(errMsg(e, "LR All-Copies ZIP download failed"));
    throw e;
  }
}

export async function previewLrFromDraft(tripDraft) {
  try {
    const res = await api.post("/trips/lr/preview", tripDraft, {
      responseType: "blob", timeout: 45_000,
    });
    await _openBlob(res.data, "LR_Preview.pdf");
  } catch (e) {
    // Blob errors — extract JSON detail if server returned one.
    let msg = "LR preview failed";
    try {
      if (e?.response?.data instanceof Blob) {
        const text = await e.response.data.text();
        try { msg = JSON.parse(text)?.detail || msg; } catch { msg = text || msg; }
      } else {
        msg = errMsg(e, msg);
      }
    } catch {}
    toast.error(msg);
    throw e;
  }
}

export async function openInvoicePdf(invoiceId, filenameHint) {
  try {
    const res = await api.get(`/invoices/${invoiceId}/pdf`, { responseType: "blob", timeout: 45_000 });
    await _openBlob(res.data, filenameHint || `INV_${invoiceId}.pdf`);
  } catch (e) {
    toast.error(errMsg(e, "Invoice download failed"));
    throw e;
  }
}
