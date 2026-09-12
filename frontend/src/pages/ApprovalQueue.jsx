import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listApprovals, ENTITY_KIND_LABEL, STATUS_LABEL } from "@/api/approvals";
import ApprovalDetailDialog from "@/components/ApprovalDetailDialog";
import { useAuth } from "@/context/AuthContext";

/**
 * Iter150J · Approval Queue — review-only surface.
 *
 * Lists PENDING_APPROVAL by default with filters for entity_kind and
 * broader status (REJECTED, WITHDRAWN, POSTED, EXECUTION_FAILED). No
 * payment-creation button lives here. Detail dialog is where approve /
 * reject / withdraw actions live.
 */
export default function ApprovalQueue() {
  const { user } = useAuth() || {};
  const canApprove = (user?.permissions || []).includes("approve_transactions");
  const [statusFilter, setStatusFilter] = useState("PENDING_APPROVAL");
  const [kindFilter, setKindFilter] = useState("");
  const [openId, setOpenId] = useState("");

  const list = useQuery({
    queryKey: ["approval-list", statusFilter, kindFilter],
    queryFn: () => listApprovals({
      status: statusFilter === "ALL" ? "" : statusFilter,
      entity_kind: kindFilter,
      include_all: statusFilter === "ALL",
    }),
  });

  const rows = list.data || [];

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="approval-queue-page">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Approvals</h1>
          <p className="text-xs text-zinc-500 mt-1">
            Review Trip, Invoice, and Payment submissions before they post to the ledger.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            className="border border-zinc-300 rounded-sm px-2 py-1.5 text-sm"
            value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
            data-testid="approval-queue-status-filter"
          >
            <option value="PENDING_APPROVAL">Pending</option>
            <option value="REJECTED">Rejected</option>
            <option value="WITHDRAWN">Withdrawn</option>
            <option value="POSTED">Posted</option>
            <option value="EXECUTION_FAILED">Execution Failed</option>
            <option value="ALL">All</option>
          </select>
          <select
            className="border border-zinc-300 rounded-sm px-2 py-1.5 text-sm"
            value={kindFilter} onChange={(e) => setKindFilter(e.target.value)}
            data-testid="approval-queue-kind-filter"
          >
            <option value="">All kinds</option>
            <option value="trip">Trip</option>
            <option value="invoice">Invoice</option>
            <option value="supplier_payment">Supplier Payment</option>
            <option value="vendor_payment">Vendor Payment</option>
            <option value="mechanic_payment">Mechanic Payment</option>
            <option value="driver_payment">Driver Payment</option>
          </select>
        </div>
      </div>

      <div className="border border-zinc-200 rounded-sm bg-white overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-zinc-50 text-xs uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="text-left px-3 py-2">Kind</th>
              <th className="text-left px-3 py-2">Status</th>
              <th className="text-left px-3 py-2">Maker</th>
              <th className="text-left px-3 py-2">Revision</th>
              <th className="text-left px-3 py-2">Submitted</th>
              <th className="text-left px-3 py-2">Party</th>
              <th className="text-right px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody data-testid="approval-queue-tbody">
            {list.isLoading && (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-zinc-500">Loading…</td></tr>
            )}
            {!list.isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-zinc-500" data-testid="approval-queue-empty">
                  No approvals in this view.
                </td>
              </tr>
            )}
            {rows.map((r) => (
              <tr key={r.id} className="border-t hover:bg-zinc-50" data-testid={`approval-row-${r.id}`}>
                <td className="px-3 py-2 font-bold">{ENTITY_KIND_LABEL[r.entity_kind] || r.entity_kind}</td>
                <td className="px-3 py-2">
                  <span className={`inline-block px-2 py-0.5 rounded-sm text-xs font-bold ${
                    r.status === "PENDING_APPROVAL" ? "bg-amber-100 text-amber-800" :
                    r.status === "POSTED" ? "bg-emerald-100 text-emerald-800" :
                    r.status === "REJECTED" ? "bg-rose-100 text-rose-800" :
                    r.status === "EXECUTION_FAILED" ? "bg-rose-200 text-rose-900" :
                    "bg-zinc-100 text-zinc-700"
                  }`}>{STATUS_LABEL[r.status] || r.status}</span>
                </td>
                <td className="px-3 py-2 text-xs break-all">{r.maker_user_id}</td>
                <td className="px-3 py-2 text-xs">v{r.revision_index || 0}</td>
                <td className="px-3 py-2 text-xs">{(r.created_at || "").slice(0, 19).replace("T", " ")}</td>
                <td className="px-3 py-2 text-xs break-all">{r.party_id || "—"}</td>
                <td className="px-3 py-2 text-right">
                  <button
                    className="px-2 py-1 border border-zinc-300 rounded-sm text-xs hover:bg-zinc-100"
                    onClick={() => setOpenId(r.id)}
                    data-testid={`approval-row-open-${r.id}`}
                  >Review</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ApprovalDetailDialog
        approvalId={openId}
        currentUserId={user?.user_id || ""}
        canApprove={canApprove}
        open={!!openId}
        onClose={() => setOpenId("")}
      />
    </div>
  );
}
