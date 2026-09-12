import React from "react";
import { useQuery } from "@tanstack/react-query";
import { pendingCount } from "@/api/approvals";

/**
 * Iter150J · PendingApprovalBadge — small counter chip for the nav link.
 * Poll interval is deliberately conservative (30s) so it does not add
 * request pressure to the tenant. Renders nothing while the count is 0.
 */
export default function PendingApprovalBadge() {
  const q = useQuery({
    queryKey: ["approval-pending-count"],
    queryFn: () => pendingCount(),
    refetchInterval: 30000,
    staleTime: 15000,
  });
  const n = q.data?.count || 0;
  if (!n) return null;
  return (
    <span
      className="ml-auto inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-sm bg-rose-600 text-white text-[10px] font-bold"
      data-testid="pending-approval-badge"
    >{n}</span>
  );
}
