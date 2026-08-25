// Iter126c · Restore banner. Sticky (no auto-dismiss) until the user chooses.
import React from "react";

export default function DraftRestoreBanner({ draft }) {
  if (!draft || !draft.banner) return null;
  return (
    <div
      data-testid="iter126c-restore-banner"
      className="border border-amber-300 bg-amber-50 rounded-sm px-4 py-3 flex flex-col sm:flex-row sm:items-center gap-3"
    >
      <div className="flex-1 text-sm text-amber-900">
        <div className="font-bold uppercase tracking-wider text-xs mb-0.5">
          💾 Unsaved draft found
        </div>
        <div className="text-xs">
          From <span data-testid="iter126c-restore-age">{draft.age}</span> — restore it,
          or discard to start fresh. This banner stays until you choose.
        </div>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          data-testid="iter126c-restore-btn"
          onClick={draft.restore}
          className="px-4 py-2 text-xs uppercase tracking-wider font-semibold bg-amber-900 text-amber-50 rounded-sm hover:bg-amber-800"
        >
          Restore
        </button>
        <button
          type="button"
          data-testid="iter126c-discard-btn"
          onClick={draft.discard}
          className="px-4 py-2 text-xs uppercase tracking-wider font-semibold border border-amber-300 text-amber-900 rounded-sm hover:bg-amber-100"
        >
          Discard
        </button>
      </div>
    </div>
  );
}
