import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { X } from "lucide-react";
import {
  getApproval, approveApproval, rejectApproval, withdrawApproval,
  ENTITY_KIND_LABEL, STATUS_LABEL,
} from "@/api/approvals";
import ApprovalRevisionDiff from "@/components/ApprovalRevisionDiff";

/**
 * Iter150J · ApprovalDetailDialog — review-only surface.
 *
 * Actions available:
 *   - Approve (checker · one-click executes writer)
 *   - Reject with reason (checker)
 *   - Withdraw (maker on own pending item)
 *
 * The queue never exposes a payment-creation button; edits happen via a
 * separate resubmit flow when the maker chooses to revise a REJECTED /
 * WITHDRAWN item from the original drawer.
 */
export default function ApprovalDetailDialog({ approvalId, currentUserId, canApprove, open, onClose }) {
  const qc = useQueryClient();
  const [rejectReason, setRejectReason] = useState("");
  const [withdrawReason, setWithdrawReason] = useState("");

  const detail = useQuery({
    queryKey: ["approval-detail", approvalId],
    queryFn: () => getApproval(approvalId),
    enabled: open && !!approvalId,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["approval-list"] });
    qc.invalidateQueries({ queryKey: ["approval-pending-count"] });
    qc.invalidateQueries({ queryKey: ["approval-detail", approvalId] });
  };

  const approveM = useMutation({
    mutationFn: () => approveApproval(approvalId, ""),
    onSuccess: () => { toast.success("Approved & posted"); invalidate(); onClose && onClose(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Approve failed"),
  });
  const rejectM = useMutation({
    mutationFn: () => rejectApproval(approvalId, rejectReason.trim()),
    onSuccess: () => { toast.success("Rejected"); invalidate(); onClose && onClose(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Reject failed"),
  });
  const withdrawM = useMutation({
    mutationFn: () => withdrawApproval(approvalId, withdrawReason.trim()),
    onSuccess: () => { toast.success("Withdrawn"); invalidate(); onClose && onClose(); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Withdraw failed"),
  });

  if (!open) return null;

  const apr = detail.data?.approval;
  const revisions = detail.data?.revisions || [];
  const audits = detail.data?.audits || [];

  const status = apr?.status || "";
  const isPending = status === "PENDING_APPROVAL";
  const isMaker = apr && apr.maker_user_id === currentUserId;
  const canReject = isPending && canApprove && !isMaker;
  const canApproveNow = isPending && canApprove && !isMaker;
  const canWithdraw = isPending && (isMaker || canApprove);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/60 p-4"
         data-testid="approval-detail-dialog">
      <div className="bg-white w-full max-w-3xl border rounded-sm max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white">
          <div>
            <h3 className="font-bold" data-testid="approval-detail-title">
              Approval #{approvalId?.slice(0, 8)}
            </h3>
            <div className="text-xs text-zinc-500">
              {apr ? `${ENTITY_KIND_LABEL[apr.entity_kind] || apr.entity_kind} · ${STATUS_LABEL[status] || status}` : "Loading…"}
            </div>
          </div>
          <button onClick={onClose} data-testid="approval-detail-close"><X size={18} /></button>
        </div>

        <div className="p-5 space-y-4">
          {detail.isLoading && <div className="text-sm text-zinc-500">Loading…</div>}
          {apr && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                <div><div className="text-zinc-500">Kind</div><div className="font-bold">{ENTITY_KIND_LABEL[apr.entity_kind]}</div></div>
                <div><div className="text-zinc-500">Status</div><div className="font-bold" data-testid="approval-detail-status">{STATUS_LABEL[status] || status}</div></div>
                <div><div className="text-zinc-500">Revision</div><div className="font-bold">v{apr.revision_index || 0}</div></div>
                <div><div className="text-zinc-500">Maker</div><div className="font-bold break-all">{apr.maker_user_id}</div></div>
                {apr.checker_user_id && (
                  <div><div className="text-zinc-500">Checker</div><div className="font-bold break-all">{apr.checker_user_id}</div></div>
                )}
                {apr.entity_id && (
                  <div><div className="text-zinc-500">Posted Entity</div><div className="font-bold break-all">{apr.entity_id}</div></div>
                )}
                {apr.auto_approved && (
                  <div><div className="text-zinc-500">Auto</div><div className="font-bold">Solo-Owner</div></div>
                )}
              </div>

              <div>
                <div className="text-xs font-bold uppercase tracking-wider text-zinc-500 mb-1">Payload</div>
                <pre className="bg-zinc-50 border border-zinc-200 rounded-sm p-2 text-xs overflow-x-auto"
                     data-testid="approval-detail-payload">
{JSON.stringify(apr.payload || {}, null, 2)}
                </pre>
              </div>

              {apr.reject_reason && (
                <div className="text-xs bg-rose-50 border border-rose-200 rounded-sm p-2">
                  <b>Rejection reason:</b> {apr.reject_reason}
                </div>
              )}
              {apr.withdraw_reason && (
                <div className="text-xs bg-amber-50 border border-amber-200 rounded-sm p-2">
                  <b>Withdraw reason:</b> {apr.withdraw_reason}
                </div>
              )}
              {apr.execution_error && (
                <div className="text-xs bg-rose-100 border border-rose-300 rounded-sm p-2" data-testid="approval-detail-exec-error">
                  <b>Execution error:</b> {apr.execution_error}
                </div>
              )}

              {revisions.length > 0 && (
                <div>
                  <div className="text-xs font-bold uppercase tracking-wider text-zinc-500 mb-1">
                    Revisions ({revisions.length})
                  </div>
                  <div className="space-y-2" data-testid="approval-detail-revisions">
                    {revisions.map((r) => (
                      <div key={r.id} className="border border-zinc-200 rounded-sm p-2">
                        <div className="text-xs text-zinc-500">v{r.revision_index} · {r.edited_at}</div>
                        <ApprovalRevisionDiff revision={r} />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <div className="text-xs font-bold uppercase tracking-wider text-zinc-500 mb-1">Audit trail</div>
                <div className="space-y-1 text-xs" data-testid="approval-detail-audits">
                  {audits.map((a) => (
                    <div key={a.id} className="border border-zinc-200 rounded-sm p-2">
                      <div className="font-bold uppercase tracking-wide">{a.action}</div>
                      <div className="text-zinc-500">{a.at} · {a.actor_user_id}{a.note ? ` · ${a.note}` : ""}</div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>

        <div className="border-t px-5 py-3 sticky bottom-0 bg-white flex flex-wrap gap-2 items-center">
          {canApproveNow && (
            <button
              className="px-3 py-1.5 rounded-sm bg-emerald-600 text-white text-sm font-bold hover:bg-emerald-700"
              disabled={approveM.isPending}
              onClick={() => approveM.mutate()}
              data-testid="approval-detail-approve-btn"
            >
              {approveM.isPending ? "Approving…" : "Approve & Post"}
            </button>
          )}
          {canReject && (
            <>
              <input type="text" placeholder="Reject reason (required)"
                className="border border-zinc-300 rounded-sm px-2 py-1.5 text-sm flex-1 min-w-[200px]"
                value={rejectReason} onChange={(e) => setRejectReason(e.target.value)}
                data-testid="approval-detail-reject-reason" />
              <button
                className="px-3 py-1.5 rounded-sm bg-rose-600 text-white text-sm font-bold hover:bg-rose-700 disabled:opacity-50"
                disabled={rejectM.isPending || !rejectReason.trim()}
                onClick={() => rejectM.mutate()}
                data-testid="approval-detail-reject-btn"
              >Reject</button>
            </>
          )}
          {canWithdraw && (
            <>
              <input type="text" placeholder="Withdraw reason (optional)"
                className="border border-zinc-300 rounded-sm px-2 py-1.5 text-sm flex-1 min-w-[200px]"
                value={withdrawReason} onChange={(e) => setWithdrawReason(e.target.value)}
                data-testid="approval-detail-withdraw-reason" />
              <button
                className="px-3 py-1.5 rounded-sm bg-amber-600 text-white text-sm font-bold hover:bg-amber-700 disabled:opacity-50"
                disabled={withdrawM.isPending}
                onClick={() => withdrawM.mutate()}
                data-testid="approval-detail-withdraw-btn"
              >Withdraw</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
