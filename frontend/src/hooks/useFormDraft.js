// Iter126c · React hook that wraps `/app/frontend/src/lib/formDraft.js`
// and drives the restore banner UX.
//
// Usage
//   const draft = useFormDraft({
//     route: "/trips/new",
//     recordId,                          // optional — for edit routes
//     form, setForm,                     // controlled form state
//     saveMutation,                      // { isPending, isSuccess, isError, error }
//     onGetIdempotencyKey,               // ref-setter that the save mutation
//                                        // reads BEFORE firing the axios call
//   });
//
//   // Somewhere in JSX (above the <form>):
//   <DraftRestoreBanner draft={draft} />
//
// The hook exposes:
//   .banner             boolean — draft exists & not yet resolved
//   .age                "3 minutes ago"
//   .restore()          merges draft.form into React form state
//   .discard()          deletes the draft
//   .getKeyForSave()    returns Idempotency-Key for next Save (rotates on
//                       material change, reuses on retry)
//   .clearOnSuccess()   erases the draft key & clears local state
//
// Iter126c-UAT-fix (Feb 2026) · MEANINGFULLY-DIRTY GATE.
// A draft is written ONLY after the sanitised form buffer diverges from the
// untouched mount baseline. Blank New Trip → no draft. Untouched Invoice
// (customer_id="", selected={}, rcm=true, hsnSac="996791", invoiceDate=today,
// notes="") → no draft. As soon as the user picks a customer, edits notes,
// toggles rcm, adds a trip line, etc. the sha changes and autosave kicks in.
// This eliminates the "Unsaved draft found — from 3 seconds ago" ghost banner
// that appeared on a freshly-mounted form with no user input.
//
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  buildDraftKey, loadDraft, saveDraft, clearDraft,
  humanAge, sanitizeDraft, draftSha, chooseSaveKey,
} from "@/lib/formDraft";

const DEBOUNCE_MS = 800;

export function useFormDraft({
  route,
  recordId = "",
  form,
  setForm,
  userId,
  companyId,
  enabled = true,
}) {
  const compositeKey = buildDraftKey({ route, recordId, userId, companyId });
  const [existingDraft, setExistingDraft] = useState(null);
  const [decided, setDecided] = useState(false); // user restored OR discarded
  const debounceRef = useRef(null);
  const boundKeyRef = useRef({ key: null, sha: null });

  // Iter126c-UAT-fix · Baseline sha captured on FIRST render. This is the
  // sha of the untouched mount state (EMPTY form, default policy values,
  // auto-populated date, empty strings — everything the user did NOT touch).
  // We compare every candidate autosave against this baseline and skip the
  // write when they match, so blank forms never persist a draft.
  const baselineShaRef = useRef(null);
  if (baselineShaRef.current === null && form) {
    baselineShaRef.current = draftSha(sanitizeDraft(form));
  }

  // -------- on-mount: probe for an existing draft --------
  useEffect(() => {
    if (!enabled) return;
    const d = loadDraft(compositeKey, { userId });
    if (d) setExistingDraft(d);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compositeKey, enabled, userId]);

  // -------- debounced autosave --------
  useEffect(() => {
    if (!enabled) return;
    if (!form) return;
    // Skip autosave until the user has decided about the restore prompt
    // (we don't want the untouched initial state to overwrite the draft).
    if (existingDraft && !decided) return;

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      const cleaned = sanitizeDraft(form);
      const sha = draftSha(cleaned);

      // Iter126c-UAT-fix · Meaningfully-dirty gate. If the current sha
      // matches the untouched-mount baseline AND no draft exists yet, the
      // user hasn't provided any meaningful input — do NOT persist. This
      // is what prevented "blank New Trip" from showing a ghost restore
      // banner after reload.
      if (!existingDraft && sha === baselineShaRef.current) return;

      // Skip write when nothing meaningful changed since the last flush.
      const prev = existingDraft && existingDraft.sha;
      if (prev === sha) return;
      const written = saveDraft(compositeKey, {
        route, form, userId,
        existing: existingDraft,
        idempotencyKey: (existingDraft && existingDraft.idempotency_key) || undefined,
      });
      if (written) setExistingDraft(written);
    }, DEBOUNCE_MS);
    return () => debounceRef.current && clearTimeout(debounceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form, compositeKey, decided, enabled]);

  // -------- public API --------
  const restore = useCallback(() => {
    if (!existingDraft) return;
    setForm((prev) => ({ ...prev, ...existingDraft.form }));
    setDecided(true);
  }, [existingDraft, setForm]);

  const discard = useCallback(() => {
    clearDraft(compositeKey);
    setExistingDraft(null);
    setDecided(true);
  }, [compositeKey]);

  const getKeyForSave = useCallback(() => {
    const { key, sha, minted } = chooseSaveKey(existingDraft, form);
    boundKeyRef.current = { key, sha };
    // Persist the bound key + saved_sha so a page reload during a Save
    // still knows which key was in flight (used by the "retry replays" flow).
    const written = saveDraft(compositeKey, {
      route, form, userId,
      existing: existingDraft ? { ...existingDraft, saved_sha: sha } : { saved_sha: sha },
      idempotencyKey: key,
    });
    if (written) setExistingDraft(written);
    return key;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingDraft, form, compositeKey, route, userId]);

  const clearOnSuccess = useCallback(() => {
    clearDraft(compositeKey);
    setExistingDraft(null);
    boundKeyRef.current = { key: null, sha: null };
  }, [compositeKey]);

  return {
    // banner state
    banner: Boolean(existingDraft && !decided),
    age: existingDraft ? humanAge(existingDraft.updated_at) : "",
    // actions
    restore, discard, getKeyForSave, clearOnSuccess,
    // internals — exposed only for tests
    _key: compositeKey,
    _draft: existingDraft,
    _baselineSha: baselineShaRef.current,
  };
}
