import React from "react";

/**
 * Iter150J · ApprovalRevisionDiff — before / after payload diff view.
 * Read-only. Renders a per-key list of changed fields on the payload.
 * Bank-account numbers are never stored inside the approval payload
 * (only `bank_account_id` / `company_bank_account_id` references), so
 * this component is safe to render inline.
 */
export default function ApprovalRevisionDiff({ revision }) {
  if (!revision) return null;
  const diff = revision.diff || {};
  const keys = Object.keys(diff);
  if (!keys.length) {
    return (
      <div className="text-xs text-zinc-500 italic" data-testid="approval-revision-diff-empty">
        No field-level changes recorded for this revision.
      </div>
    );
  }
  return (
    <div className="space-y-1" data-testid="approval-revision-diff">
      {keys.map((k) => {
        const [before, after] = diff[k];
        return (
          <div key={k} className="border border-zinc-200 rounded-sm p-2 text-xs"
               data-testid={`approval-revision-diff-row-${k}`}>
            <div className="font-bold uppercase tracking-wide text-[10px] text-zinc-500">
              {k}
            </div>
            <div className="grid grid-cols-2 gap-2 mt-1">
              <div className="bg-rose-50 border border-rose-200 rounded-sm p-1">
                <div className="text-[9px] text-rose-600 uppercase">Before</div>
                <div className="break-all">{JSON.stringify(before)}</div>
              </div>
              <div className="bg-emerald-50 border border-emerald-200 rounded-sm p-1">
                <div className="text-[9px] text-emerald-600 uppercase">After</div>
                <div className="break-all">{JSON.stringify(after)}</div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
