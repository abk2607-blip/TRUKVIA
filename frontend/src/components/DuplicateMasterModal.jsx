// Iter127a UAT · Shared "already exists" modal.
//
// Replaces the raw JSON toast that leaked when the backend returned
// a 409 { code: "duplicate_master" } for Customer / Supplier or a 200
// { duplicate: true } for Vehicle. Renders a clean, user-facing dialog
// with Open Existing / Cancel actions. NO business-logic knowledge —
// callers hand it the existing record + a "how do I open this" callback.
//
// Consumers pass:
//   entity     "customer" | "supplier" | "vehicle"
//   existing   { id, name?, gstin?, phone?, vehicle_number? }   — from API
//   onOpenExisting(existing)   — parent decides navigation / edit
//   onCancel()                 — dismiss, keep create form open
//
// The parser at the bottom (`parseDuplicate`) extracts the payload from
// either the 409 axios error or the 200 vehicle response with duplicate:true.
import React from "react";

const TITLES = {
  customer: "Customer Already Exists",
  supplier: "Supplier Already Exists",
  vehicle:  "Vehicle Already Exists",
};

const MESSAGES = {
  customer: {
    gstin:   "A customer with this GSTIN already exists.",
    pan:     "A customer with this PAN already exists.",
    name:    "A customer with this name already exists. Please verify whether this is the same company with a different state GST registration.",
    phone:   "A customer with this phone number already exists.",
    default: "A customer with these details already exists.",
  },
  supplier: {
    gstin:   "A supplier with this GSTIN already exists.",
    pan:     "A supplier with this PAN already exists.",
    name:    "A supplier with this name already exists.",
    mobile:  "A supplier with this mobile number already exists.",
    default: "A supplier with these details already exists.",
  },
  vehicle: {
    vehicle_number: "A vehicle with this registration number already exists.",
    default:        "A vehicle with these details already exists.",
  },
};

export default function DuplicateMasterModal({ open, entity, existing, matchedField, onOpenExisting, onCancel, onContinueCreate, headerLabel }) {
  if (!open || !existing) return null;
  const title = TITLES[entity] || "Record Already Exists";
  const label = headerLabel || (onContinueCreate ? "Possible Duplicate" : "Duplicate Detected");
  const message =
    (MESSAGES[entity] || {})[matchedField] ||
    (MESSAGES[entity] || {}).default ||
    "This record already exists.";
  const rows = [];
  if (entity === "vehicle" && existing.vehicle_number) {
    rows.push(["Vehicle Number", existing.vehicle_number]);
  } else if (existing.name) {
    rows.push([entity === "supplier" ? "Supplier Name" : "Customer Name", existing.name]);
  }
  if (existing.gstin) rows.push(["GSTIN", existing.gstin]);
  if (existing.state) rows.push(["State", existing.state]);
  if (existing.phone && entity !== "vehicle") rows.push(["Phone", existing.phone]);

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-zinc-900/50 backdrop-blur-sm p-4"
      data-testid={`iter127a-duplicate-modal iter127a-duplicate-modal-${entity}`}
    >
      <div className="bg-white w-full max-w-md border border-zinc-950 rounded-sm">
        <div className="px-5 py-3 border-b border-zinc-200">
          <div className="text-[10px] uppercase tracking-wider font-bold text-amber-700">
            {label}
          </div>
          <h3 className="mt-0.5 font-bold text-lg" data-testid="iter127a-duplicate-title">{title}</h3>
        </div>
        <div className="px-5 py-4 space-y-3">
          <p className="text-sm text-zinc-700" data-testid="iter127a-duplicate-message">{message}</p>
          {rows.length > 0 && (
            <dl className="border border-zinc-200 rounded-sm divide-y divide-zinc-200 text-sm" data-testid="iter127a-duplicate-details">
              {rows.map(([k, v]) => (
                <div key={k} className="flex px-3 py-2">
                  <dt className="w-32 text-[11px] uppercase tracking-wider font-bold text-zinc-500">{k}</dt>
                  <dd className="flex-1 font-medium text-zinc-950">{v}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
        <div className="px-5 py-3 border-t border-zinc-200 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            data-testid="iter127a-duplicate-cancel"
            className="px-4 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm hover:bg-zinc-50"
          >
            Cancel
          </button>
          {onContinueCreate && (
            <button
              type="button"
              onClick={() => onContinueCreate(existing)}
              data-testid="iter127a-duplicate-continue-create"
              className="px-4 py-2 text-xs uppercase tracking-wider border border-amber-700 text-amber-800 rounded-sm hover:bg-amber-50"
            >
              Continue Creating
            </button>
          )}
          <button
            type="button"
            onClick={() => onOpenExisting?.(existing)}
            data-testid="iter127a-duplicate-open-existing"
            className="px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800"
          >
            Open Existing
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Parsers ────────────────────────────────────────────────────────────────
// Given an axios error object, returns { existing, matchedField } if it's a
// backend Iter127a 409 duplicate_master response — else null. Never throws.
//
// Iter127a-UAT-fix v2: the Iter102 response interceptor in `api.js` runs
// BEFORE this parser and flattens `err.response.data.detail` from the
// structured dict `{code:"duplicate_master", existing:{…}}` down to a plain
// user-friendly string, moving the original dict to `detail_raw`. Read
// `detail_raw` first so we still see the structured payload; fall back to
// `detail` for callers that don't wear the api.js interceptor (jest tests).
export function parseDuplicateError(err) {
  try {
    const status = err?.response?.status;
    if (status !== 409) return null;
    const data = err?.response?.data;
    if (!data) return null;
    const detail = (data.detail_raw !== undefined) ? data.detail_raw : data.detail;
    if (!detail || typeof detail !== "object") return null;
    if (detail.code !== "duplicate_master") return null;
    return { existing: detail.existing || {}, matchedField: detail.matched_field || "" };
  } catch { return null; }
}

// Given a vehicle-create RESPONSE body (200), returns { existing, matchedField }
// when the backend flagged it as an Iter72/127a idempotent duplicate hit.
export function parseVehicleDuplicateResponse(data) {
  if (!data || data.duplicate !== true) return null;
  return {
    existing: {
      id: data.id,
      name: data.vehicle_number || "",
      vehicle_number: data.vehicle_number || "",
    },
    matchedField: data.matched_field || "vehicle_number",
  };
}
