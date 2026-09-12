import { api } from "@/api";

/**
 * Iter150J — Approval Queue / Detail / lifecycle helpers.
 * The Approval Queue is review-only; there is no payment-creation surface
 * here. Payments are drafted from their existing drawers exactly as before
 * — the axios interceptor transparently reroutes them into the approval
 * envelope.
 */

export async function listApprovals({
  status = "",
  entity_kind = "",
  include_all = false,
  limit = 200,
} = {}) {
  const params = { limit };
  if (status) params.status = status;
  if (entity_kind) params.entity_kind = entity_kind;
  if (include_all) params.include_all = true;
  return (await api.get("/approvals", { params })).data;
}

export async function getApproval(aid) {
  return (await api.get(`/approvals/${aid}`)).data;
}

export async function pendingCount() {
  return (await api.get("/approvals/summary/pending")).data;
}

export async function approveApproval(aid, note = "") {
  return (await api.post(`/approvals/${aid}/approve`, { note })).data;
}

export async function rejectApproval(aid, reason) {
  return (await api.post(`/approvals/${aid}/reject`, { reason })).data;
}

export async function withdrawApproval(aid, reason = "") {
  return (await api.post(`/approvals/${aid}/withdraw`, { reason })).data;
}

export async function resubmitApproval(aid, payload, note = "") {
  return (await api.post(`/approvals/${aid}/resubmit`, { payload, note })).data;
}

export const ENTITY_KIND_LABEL = {
  trip: "Trip",
  invoice: "Invoice",
  supplier_payment: "Supplier Payment",
  vendor_payment: "Vendor Payment",
  mechanic_payment: "Mechanic Payment",
  driver_payment: "Driver Payment",
};

export const STATUS_LABEL = {
  DRAFT: "Draft",
  PENDING_APPROVAL: "Pending",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  WITHDRAWN: "Withdrawn",
  POSTED: "Posted",
  EXECUTION_FAILED: "Execution Failed",
};
