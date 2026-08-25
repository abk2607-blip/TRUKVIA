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
import { useCallback, useEffect, useRef, useState } from "react";
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
  };
}
