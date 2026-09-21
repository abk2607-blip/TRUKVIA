import type { Db } from 'mongodb';
import { randomUUID } from 'node:crypto';
import { callPythonHook, hookConfigured } from './hook-client';
import { reprojectVendorSourceOrThrow, VENDOR_SOURCE_TYPES } from './projection';

/**
 * Phase 6 · slice 2c, unit 1 — the canonical post-write projection hook.
 *
 * Port of backend/services_fin_txn_hooks.py: `hook_after_source_write` and the
 * `fin_hook_failures` queue it maintains. The ledger maths itself is NOT here;
 * this is the layer that decides what happens when a projection fails.
 *
 * WHY THIS SLICE EXISTS
 * ---------------------
 * The slice-1b vendor port already wrote a `fin_hook_failures` row on failure,
 * but wrote its OWN shape:
 *
 *     { user_id, company_id, source_type, source_id, error, failed_at, origin }
 *
 * Python's retry driver `replay_pending_failures` selects on
 * `status ∈ {pending, retrying}` and `next_attempt_at`, and then reads
 * `row["retry_count"]`. A row without those fields is never selected, so a
 * projection that failed on the NestJS side was queued into a table nothing
 * drains — silently, and for as long as the row existed. The same code also
 * never cleared a prior failure after a later success, so a resolved problem
 * stayed on the books.
 *
 * This module fixes both by reproducing the Python contract exactly: the same
 * document, the same statuses, the same backoff, the same reopen rules, and the
 * same auto-resolve on success.
 *
 * WHAT IS DELIBERATELY NOT HERE
 * -----------------------------
 * The retry driver itself (`replay_pending_failures`), reconciliation,
 * `GET /api/fin/accounts`, `backfill_tenant`, and the NINE source projections
 * that have no TypeScript port yet. Those nine delegate to Python through the
 * existing forward bridge, so the verified implementation still owns them.
 * Four are ported: vendor_payment, vendor_bill, mechanic_payment and — since
 * slice 2c unit 3 — supplier_payment.
 */

type Doc = Record<string, unknown>;

/**
 * services_fin_txn.SUPPORTED_SOURCE_TYPES, in declaration order.
 *
 * There are THIRTEEN, not the twelve the literal in that file lists. The
 * bottom of services_fin_txn.py monkey-patches the module at import time:
 *
 *     if "driver_payment" not in SUPPORTED_SOURCE_TYPES:
 *         SUPPORTED_SOURCE_TYPES.append("driver_payment")
 *     reproject_source = _iter150i_reproject_source
 *
 * so `driver_payment` is appended at the END and `reproject_source` is
 * replaced by a wrapper that handles it. Reading only the literal gives a
 * twelve-item list, and since the hook renders this list verbatim into its
 * unsupported-type error, the difference is visible in a response body — which
 * is how the parity harness caught it on 2026-09-21.
 */
export const SUPPORTED_SOURCE_TYPES: string[] = [
  'invoice',
  'credit_debit_note',
  'supplier_payment',
  'vendor_payment',
  'mechanic_payment',
  'expense',
  'vendor_bill',
  'mechanic_work_order',
  'trip_customer_receipt',
  'wallet_recharge',
  'wallet_transfer',
  'wallet_adjustment',
  // appended by the Iter150I monkey-patch, not by the literal
  'driver_payment',
];

/** The subset with a TypeScript projection. Everything else goes to Python. */
const TS_PORTED = new Set<string>(VENDOR_SOURCE_TYPES);

export const MAX_RETRIES = 8;
export const BACKOFF_BASE_SECONDS = 60;
export const BACKOFF_CAP_SECONDS = 24 * 3600;

export const FAILURE_STATUS_PENDING = 'pending';
export const FAILURE_STATUS_RETRYING = 'retrying';
export const FAILURE_STATUS_RESOLVED = 'resolved';
export const FAILURE_STATUS_PERMANENTLY_FAILED = 'permanently_failed';

export const NON_TERMINAL_STATUSES = [FAILURE_STATUS_PENDING, FAILURE_STATUS_RETRYING];

/** Python: datetime.now(timezone.utc).isoformat() — microsecond precision. */
const nowIso = (d: Date = new Date()): string => `${d.toISOString().slice(0, -1)}000+00:00`;

/** `min(BASE * 2**retry_count, CAP)` seconds from now. */
export function computeNextAttempt(retryCount: number, from: Date = new Date()): string {
  const delay = Math.min(BACKOFF_BASE_SECONDS * 2 ** retryCount, BACKOFF_CAP_SECONDS);
  return nowIso(new Date(from.getTime() + delay * 1000));
}

/** The one-active-row-per-source key, in Python's field order. */
function failureQuery(uid: string, cid: string, sourceType: string, sourceId: string): Doc {
  return { user_id: uid, company_id: cid, source_type: sourceType, source_id: sourceId };
}

/**
 * Python's `repr()` for the error message. Narrow on purpose: source types are
 * plain identifiers, so only the quoting rule matters.
 */
function pyRepr(s: string): string {
  const escaped = s.replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t');
  return escaped.includes("'") && !escaped.includes('"')
    ? `"${escaped}"`
    : `'${escaped.replace(/'/g, "\\'")}'`;
}

export async function ensureHookIndexes(mongo: Db): Promise<void> {
  await mongo
    .collection('fin_hook_failures')
    .createIndex(
      { user_id: 1, company_id: 1, source_type: 1, source_id: 1 },
      { unique: true, name: 'fin_hook_fail_source_uniq' },
    );
  await mongo
    .collection('fin_hook_failures')
    .createIndex(
      { user_id: 1, company_id: 1, status: 1, next_attempt_at: 1 },
      { name: 'fin_hook_fail_replay_scan' },
    );
}

/**
 * Upsert the failure row.
 *
 * Three distinct cases, and the difference between them matters to the retry
 * driver: an existing pending/retrying row only has its error refreshed, so the
 * driver's schedule and attempt count survive; a resolved or permanently_failed
 * row is REOPENED with retry_count back to 0 and its original `id` and
 * `created_at` preserved; anything else is a new row.
 */
export async function recordFailure(
  mongo: Db,
  uid: string,
  cid: string,
  sourceType: string,
  sourceId: string,
  error: string,
  action = 'upsert',
): Promise<Doc> {
  const coll = mongo.collection<Doc>('fin_hook_failures');
  const key = failureQuery(uid, cid, sourceType, sourceId);
  const now = new Date();
  const nowText = nowIso(now);
  const existing = await coll.findOne(key, { projection: { _id: 0 } });

  if (existing && NON_TERMINAL_STATUSES.includes(String(existing['status']))) {
    await coll.updateOne(key, {
      $set: { error: (error || '').slice(0, 2000), last_attempt_at: nowText },
    });
    // Python returns the UNTRUNCATED error here, unlike what it stored.
    return { ...existing, error, last_attempt_at: nowText };
  }

  const doc: Doc = {
    id: existing ? existing['id'] : `hfail_${randomUUID().replace(/-/g, '').slice(0, 16)}`,
    user_id: uid,
    company_id: cid,
    source_type: sourceType,
    source_id: sourceId,
    action,
    error: (error || '').slice(0, 2000),
    retry_count: 0,
    created_at: existing ? existing['created_at'] : nowText,
    last_attempt_at: nowText,
    next_attempt_at: computeNextAttempt(0, now),
    status: FAILURE_STATUS_PENDING,
    resolved_at: '',
    history: [],
  };
  await coll.updateOne(key, { $set: doc }, { upsert: true });
  return doc;
}

/** Mark a pending/retrying row resolved. Returns its id, or null. */
export async function resolveFailure(
  mongo: Db,
  uid: string,
  cid: string,
  sourceType: string,
  sourceId: string,
): Promise<string | null> {
  const coll = mongo.collection<Doc>('fin_hook_failures');
  const key = failureQuery(uid, cid, sourceType, sourceId);
  const nowText = nowIso();
  const existing = await coll.findOne(
    { ...key, status: { $in: NON_TERMINAL_STATUSES } },
    { projection: { _id: 0, id: 1 } },
  );
  if (!existing) return null;
  await coll.updateOne(key, {
    $set: { status: FAILURE_STATUS_RESOLVED, resolved_at: nowText, last_attempt_at: nowText },
  });
  return String(existing['id']);
}

export interface HookResult {
  ok: boolean;
  source_type: string;
  source_id: string;
  deleted: number | null;
  written: number | null;
  error: string | null;
  failure_id: string | null;
  resolved_failure_id: string;
}

/**
 * `hook_after_source_write`. Called AFTER the authoritative source write has
 * committed. It NEVER throws: a projection failure must not roll back or
 * invalidate the source, so it is persisted for the retry driver and reported
 * back as ok=false, which the caller must not treat as a source error.
 */
export async function hookAfterSourceWrite(
  mongo: Db,
  uid: string,
  cid: string,
  sourceType: string,
  sourceId: string,
  action = 'upsert',
): Promise<HookResult> {
  if (!SUPPORTED_SOURCE_TYPES.includes(sourceType)) {
    // A caller mistake, not a projection failure: there is no source-to-leg
    // mapping to retry, so nothing is enqueued.
    const msg =
      `unsupported source_type=${pyRepr(sourceType)} — ` +
      `allowed: [${SUPPORTED_SOURCE_TYPES.map(pyRepr).join(', ')}]`;
    return {
      ok: false,
      source_type: sourceType,
      source_id: sourceId,
      deleted: null,
      written: null,
      error: msg,
      failure_id: null,
      resolved_failure_id: '',
    };
  }

  let deleted = 0;
  let written = 0;
  try {
    if (TS_PORTED.has(sourceType)) {
      const r = await reprojectVendorSourceOrThrow(
        mongo,
        uid,
        cid,
        sourceType as (typeof VENDOR_SOURCE_TYPES)[number],
        sourceId,
      );
      deleted = r.deleted;
      written = r.written;
    } else {
      // One of the nine source types with no TypeScript projection yet, so the
      // verified Python implementation still owns it. Unreachable Python is a
      // genuine projection failure and is queued like any other.
      if (!hookConfigured()) {
        throw new Error(`no TypeScript projection for source_type=${sourceType} and no Python hook configured`);
      }
      const r = await callPythonHook(uid, cid, sourceType as never, sourceId);
      if (!r.ok) throw new Error(r.error ?? 'python hook reported failure');
      deleted = r.deleted ?? 0;
      written = r.written ?? 0;
    }
  } catch (err) {
    const error = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
    let failureId = '';
    try {
      const f = await recordFailure(mongo, uid, cid, sourceType, sourceId, error, action);
      failureId = String(f['id'] ?? '');
    } catch {
      // If even the failure row cannot be written, the source still stands.
      failureId = '';
    }
    return {
      ok: false,
      source_type: sourceType,
      source_id: sourceId,
      deleted: null,
      written: null,
      error,
      failure_id: failureId,
      resolved_failure_id: '',
    };
  }

  // Projection succeeded — clear any lingering failure for this source.
  let resolvedId = '';
  try {
    resolvedId = (await resolveFailure(mongo, uid, cid, sourceType, sourceId)) ?? '';
  } catch {
    /* non-fatal, exactly as Python's bare except here */
  }

  return {
    ok: true,
    source_type: sourceType,
    source_id: sourceId,
    deleted: Math.trunc(deleted || 0),
    written: Math.trunc(written || 0),
    error: null,
    failure_id: null,
    resolved_failure_id: resolvedId,
  };
}
