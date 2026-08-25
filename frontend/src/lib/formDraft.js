// Iter126c · Form-draft preservation module.
//
// Pure, testable helpers used by the `useFormDraft` hook and by the
// AuthContext logout handler. NO React, NO axios, NO side-effects except
// on `sessionStorage`. This keeps the module trivially unit-testable
// under jsdom and safe to mock.
//
// Everything user-facing (banner, autosave, restore prompt) lives in
// `/app/frontend/src/hooks/useFormDraft.js`.
//
// Contract locked in /app/memory/PRD.md :: Iter126c.

export const DRAFT_KEY_PREFIX = "iter126c:draft:v1:";
export const DRAFT_SCHEMA_VERSION = 1;
export const STALE_MS = 24 * 60 * 60 * 1000; // 24 h — matches Iter126b replay window
export const MAX_STRING_LEN = 2048;          // 2 KB per string field

// Blocked keys (case-insensitive). Any key path that matches ANY of these
// regexes is dropped BEFORE the draft is written. Defence-in-depth: the
// scoped forms (Trip / Invoice) don't hold most of these fields today, but
// a future refactor must never leak them to sessionStorage.
export const SENSITIVE_KEY_PATTERNS = [
  /password/i,
  /^otp$/i, /_otp$/i,
  /token/i,
  /secret/i,
  /api[_-]?key/i,
  /session/i,
  /^photo$/i, /photo_data_url/i, /image_data_url/i, /signature/i,
  /^cvv$/i, /card[_-]?number/i,
  /bank[_-]?account/i, /^upi(_|$)/i, /cheque/i, /ref[_-]?no/i,
  /account[_-]?no/i, /ifsc/i,
];

function _isSensitiveKey(k) {
  return SENSITIVE_KEY_PATTERNS.some((rx) => rx.test(String(k)));
}

/**
 * Deep-copy `form`, drop sensitive keys, strip base64 payloads, trim long
 * strings. Never throws — a broken sanitiser must NEVER prevent a save.
 */
export function sanitizeDraft(form) {
  const out = _walk(form, new WeakSet());
  return out;
}

function _walk(v, seen) {
  if (v == null) return v;
  if (typeof v === "string") {
    if (v.startsWith("data:")) return ""; // base64 preview / signature
    return v.length > MAX_STRING_LEN ? v.slice(0, MAX_STRING_LEN) : v;
  }
  if (typeof v === "number" || typeof v === "boolean") return v;
  if (v instanceof Date) return v.toISOString();
  if (v instanceof File || v instanceof Blob) return `<file: ${v.name || "blob"}>`;
  if (Array.isArray(v)) return v.map((x) => _walk(x, seen));
  if (typeof v === "object") {
    if (seen.has(v)) return null; // cycle guard
    seen.add(v);
    const out = {};
    for (const [k, val] of Object.entries(v)) {
      if (_isSensitiveKey(k)) continue;
      out[k] = _walk(val, seen);
    }
    return out;
  }
  return null;
}

/** Composite sessionStorage key — see PRD Iter126c §4. */
export function buildDraftKey({ route, recordId, userId, companyId }) {
  const routePart = recordId ? `${route}#${recordId}` : route;
  return `${DRAFT_KEY_PREFIX}${routePart}:${companyId || "_"}:${userId || "_"}`;
}

/** Cheap non-crypto content hash for change-detection. */
export function draftSha(form) {
  const s = _stableStringify(form);
  let h = 5381;
  for (let i = 0; i < s.length; i += 1) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0;
  return h.toString(16);
}

function _stableStringify(v) {
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  if (Array.isArray(v)) return `[${v.map(_stableStringify).join(",")}]`;
  const keys = Object.keys(v).sort();
  return `{${keys.map((k) => JSON.stringify(k) + ":" + _stableStringify(v[k])).join(",")}}`;
}

/** RFC-4122 v4 UUID — same helper as api.js so the two are aligned. */
export function newUuid() {
  try {
    if (typeof globalThis.crypto !== "undefined" && globalThis.crypto.randomUUID) {
      return globalThis.crypto.randomUUID();
    }
    if (typeof globalThis.crypto !== "undefined" && globalThis.crypto.getRandomValues) {
      const b = new Uint8Array(16);
      globalThis.crypto.getRandomValues(b);
      b[6] = (b[6] & 0x0f) | 0x40;
      b[8] = (b[8] & 0x3f) | 0x80;
      const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
      return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    }
  } catch {}
  return `ts-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Read a draft. Returns `null` when missing / stale / user mismatch / schema drift. */
export function loadDraft(compositeKey, { userId, appVersion }) {
  try {
    const raw = sessionStorage.getItem(compositeKey);
    if (!raw) return null;
    const d = JSON.parse(raw);
    if (!d || d.v !== DRAFT_SCHEMA_VERSION) return null;
    if (userId && d.user_id && d.user_id !== userId) return null;
    if (appVersion && d.app_version && d.app_version !== appVersion) return null;
    const updated = Number(d.updated_at || 0);
    if (!updated || Date.now() - updated > STALE_MS) return null;
    return d;
  } catch {
    return null;
  }
}

/** Write a draft. Returns the persisted object on success, null on quota / error. */
export function saveDraft(compositeKey, {
  route, form, idempotencyKey, userId, appVersion, existing,
}) {
  const clean = sanitizeDraft(form);
  const sha = draftSha(clean);
  const now = Date.now();
  const doc = {
    v: DRAFT_SCHEMA_VERSION,
    route,
    form: clean,
    idempotency_key: idempotencyKey || (existing && existing.idempotency_key) || newUuid(),
    saved_sha: (existing && existing.saved_sha) || null,   // sha at last Save fire
    sha,
    user_id: userId || null,
    app_version: appVersion || "iter126c",
    created_at: (existing && existing.created_at) || now,
    updated_at: now,
  };
  try {
    sessionStorage.setItem(compositeKey, JSON.stringify(doc));
    return doc;
  } catch {
    return null;
  }
}

/** Clear a specific draft. Safe on missing keys / disabled storage. */
export function clearDraft(compositeKey) {
  try { sessionStorage.removeItem(compositeKey); } catch {}
}

/** Wipe every Iter126c draft from sessionStorage. Called on logout. */
export function wipeAllDrafts() {
  try {
    const keys = [];
    for (let i = 0; i < sessionStorage.length; i += 1) {
      const k = sessionStorage.key(i);
      if (k && k.startsWith(DRAFT_KEY_PREFIX)) keys.push(k);
    }
    for (const k of keys) sessionStorage.removeItem(k);
    return keys.length;
  } catch {
    return 0;
  }
}

/** Human-friendly relative age ("3 minutes ago"). */
export function humanAge(updatedAt, now = Date.now()) {
  const s = Math.max(1, Math.floor((now - Number(updatedAt || 0)) / 1000));
  if (s < 60) return `${s} second${s === 1 ? "" : "s"} ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} minute${m === 1 ? "" : "s"} ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.floor(h / 24);
  return `${d} day${d === 1 ? "" : "s"} ago`;
}

/**
 * Decide which Idempotency-Key to use for the NEXT Save fire.
 *
 * Rules (PRD Iter126c §6):
 *   - If no key yet OR the sanitised form SHA changed since the last Save
 *     fire → mint a new UUID (fresh Save after a material change).
 *   - Otherwise → reuse the bound key (retry of the same Save intent).
 */
export function chooseSaveKey(existingDoc, currentForm) {
  const sha = draftSha(sanitizeDraft(currentForm));
  const materialChange =
    !existingDoc || !existingDoc.saved_sha || existingDoc.saved_sha !== sha;
  if (materialChange) {
    return { key: newUuid(), sha, minted: true };
  }
  return { key: existingDoc.idempotency_key, sha, minted: false };
}
