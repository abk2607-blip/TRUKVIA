// Iter126c · React hook that wraps `/app/frontend/src/lib/formDraft.js`
// and drives the restore banner UX.
//
// Iter126c-UAT-fix (Feb 2026) · MEANINGFULLY-DIRTY GATE.
// Iter126c-UAT-fix v2 (Feb 2026) · BANNER = MOUNT-DISCOVERY ONLY + NEW-ONLY.
//   • The Restore banner now surfaces ONLY when a valid draft was ALREADY on
//     disk at mount time (i.e. from a PREVIOUS interrupted session). It does
//     NOT flip on when the autosave silently writes the CURRENT session's
//     draft. Draft persistence and draft-recovery notification are now two
//     independent state machines.
//   • The hook auto-disables the mount-probe on edit routes (recordId
//     non-empty). Phase 1 draft-recovery is NEW records only:
//       /trips/new           → banner may appear on next visit if unsaved
//       /trips/:id/edit      → NEVER shows banner (existing DB record is
//                              the source of truth)
//       /invoices/new        → banner may appear on next visit if unsaved
//       /invoices/:id/edit   → NEVER shows banner (Phase 1 scope)
//   • Autosave continues to write silently in the background so a browser
//     crash / power loss / backend interruption / tab close still leaves a
//     recoverable draft on disk.
//
// Preserved safety guarantees (verified by regression tests):
//   • sensitive-field filtering (formDraft.js :: sanitizeDraft)
//   • 24-hour expiry
//   • per-user + per-company isolation
//   • logout wipe (formDraft.js :: clearAllForUser)
//   • successful-save clear (clearOnSuccess())
//   • Discard behaviour (discard())
//   • meaningfully-dirty gate (sha === baselineSha ⇒ never persist)
import { useCallback, useEffect, useRef, useState } from "react";
import {
  buildDraftKey, loadDraft, saveDraft, clearDraft,
  humanAge, sanitizeDraft, draftSha, chooseSaveKey,
} from "../lib/formDraft";

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
  // Iter126c-UAT-fix v2 · draft-recovery is NEW-record only for Phase 1.
  // On edit routes (recordId truthy) we short-circuit: no probe, no banner,
  // no autosave (existing DB row IS the source of truth).
  const isEditRoute = Boolean(recordId);
  const effectiveEnabled = enabled && !isEditRoute;

  const compositeKey = buildDraftKey({ route, recordId, userId, companyId });
  // `existingDraft` = state used ONLY by the callbacks (restore/discard/…).
  // It's split from the banner-visibility state below so that autosave-writes
  // during the current session don't retro-flip the Restore banner.
  const [existingDraft, setExistingDraft] = useState(null);
  const [decided, setDecided] = useState(false); // user restored OR discarded
  // Iter126c-UAT-fix v2 · Banner-visibility state. Set to a truthy value
  // ONLY by the mount-probe when a draft from a PREVIOUS session was found.
  // Autosave writes NEVER touch this state, so the banner never flips on
  // while the user is actively working in the current session.
  const [mountDraft, setMountDraft] = useState(null);
  const debounceRef = useRef(null);
  const boundKeyRef = useRef({ key: null, sha: null });

  // Iter126c-UAT-fix · Baseline sha captured on FIRST render — the sha of
  // the untouched mount state. Any autosave whose sha matches the baseline
  // AND no draft exists yet is skipped (see meaningfully-dirty gate below).
  const baselineShaRef = useRef(null);
  if (baselineShaRef.current === null && form) {
    baselineShaRef.current = draftSha(sanitizeDraft(form));
  }

  // -------- on-mount: probe for an existing draft (NEW routes only) --------
  useEffect(() => {
    if (!effectiveEnabled) return;
    const d = loadDraft(compositeKey, { userId });
    if (d) {
      setExistingDraft(d);
      // The banner ONLY reflects mount-time discovery. This is the single
      // gate that makes the Restore banner appear.
      setMountDraft(d);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compositeKey, effectiveEnabled, userId]);

  // -------- debounced autosave (still runs on New routes) --------
  useEffect(() => {
    if (!effectiveEnabled) return;
    if (!form) return;
    // If a PREVIOUS-session draft is currently being offered to the user
    // (banner visible), don't overwrite it until they decide.
    if (mountDraft && !decided) return;

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      const cleaned = sanitizeDraft(form);
      const sha = draftSha(cleaned);

      // Meaningfully-dirty gate — skip write when sanitised form is byte-
      // identical to the untouched mount snapshot AND we haven't already
      // written something.
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
      // NOTE: we deliberately do NOT setMountDraft here — the banner must
      // stay hidden while the user is actively working.
    }, DEBOUNCE_MS);
    return () => debounceRef.current && clearTimeout(debounceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form, compositeKey, decided, effectiveEnabled, mountDraft]);

  // -------- public API --------
  const restore = useCallback(() => {
    if (!existingDraft) return;
    setForm((prev) => ({ ...prev, ...existingDraft.form }));
    setDecided(true);
    setMountDraft(null); // hide banner
  }, [existingDraft, setForm]);

  const discard = useCallback(() => {
    clearDraft(compositeKey);
    setExistingDraft(null);
    setMountDraft(null);
    setDecided(true);
  }, [compositeKey]);

  const getKeyForSave = useCallback(() => {
    const { key, sha } = chooseSaveKey(existingDraft, form);
    boundKeyRef.current = { key, sha };
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
    setMountDraft(null);
    boundKeyRef.current = { key: null, sha: null };
  }, [compositeKey]);

  return {
    // banner state — TRUE only when a PREVIOUS session's draft was
    // discovered on mount AND the user hasn't decided yet. Never flips on
    // from a live autosave write.
    banner: Boolean(mountDraft && !decided),
    age: mountDraft ? humanAge(mountDraft.updated_at) : "",
    // actions
    restore, discard, getKeyForSave, clearOnSuccess,
    // internals — exposed only for tests
    _key: compositeKey,
    _draft: existingDraft,
    _mountDraft: mountDraft,
    _baselineSha: baselineShaRef.current,
    _isEditRoute: isEditRoute,
  };
}
