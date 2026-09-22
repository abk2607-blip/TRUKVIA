import type { Db } from 'mongodb';
import { pyTruthy } from '../common/identity';
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
 * Reconciliation, `GET /api/fin/accounts` and `backfill_tenant` — all three
 * are outside slice 2c entirely.
 *
 * As of unit 13 every one of the thirteen source types has a TypeScript
 * projection, and the retry driver `replay_pending_failures` lives at the
 * bottom of this file. The forward bridge to Python remains in place and is
 * still the preferred direction for the vendor types; nothing has been
 * retired.
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

/**
 * The subset with a TypeScript projection. As of slice 2c unit 12 that is all
 * thirteen, so the Python-delegating branch below is now a safety net rather
 * than a routine path — it still matters if a future source type is added to
 * SUPPORTED_SOURCE_TYPES before it is ported here.
 */
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


// ── The retry driver ─────────────────────────────────────────────────────

export interface ReplayOptions {
  user_id?: string;
  company_id?: string;
  limit?: number;
  dry_run?: boolean;
  ignore_schedule?: boolean;
  verbose?: boolean;
}

export interface ReplayReport {
  attempted: number;
  succeeded: number;
  failed: number;
  permanently_failed: number;
  remaining: number;
  rows: Doc[];
  dry_run: boolean;
}

/**
 * `services_fin_txn_hooks.replay_pending_failures` — drain the queue.
 *
 * Two things about it shape everything else:
 *
 *   • it calls `reproject_source` DIRECTLY, not the hook, precisely so it can
 *     observe the raw outcome without recursively re-recording a failure. In
 *     this port that means it goes through the bridged reproject layer, so an
 *     ENABLED source type delegates to NestJS on retry as well — correct, and
 *     worth knowing before enabling one in a live environment;
 *   • a row's `id` and `created_at` are never rewritten. Every transition is a
 *     `$set` of named fields, so the queue keeps one durable record per source
 *     across its whole retry history.
 *
 * Transitions:
 *   success               -> resolved (+ resolved_at, last_attempt_at)
 *   failure, count < MAX  -> retrying, retry_count+1, fresh backoff, history
 *   failure, count >= MAX -> permanently_failed, same fields
 *
 * `history` keeps only the LAST FOUR prior entries plus the new one, so a row
 * that fails repeatedly does not grow without bound.
 */
export async function replayPendingFailures(
  mongo: Db,
  opts: ReplayOptions = {},
): Promise<ReplayReport> {
  const coll = mongo.collection<Doc>('fin_hook_failures');
  const nowText = nowIso();

  const q: Doc = { status: { $in: NON_TERMINAL_STATUSES } };
  if (pyTruthy(opts.user_id)) q['user_id'] = opts.user_id;
  if (pyTruthy(opts.company_id)) q['company_id'] = opts.company_id;
  if (!opts.ignore_schedule) q['next_attempt_at'] = { $lte: nowText };

  let cursor = coll.find(q, { projection: { _id: 0 } }).sort({ next_attempt_at: 1 });
  // Python: `if limit:` — a limit of 0 means NO limit, not "none of them".
  if (pyTruthy(opts.limit)) {
    cursor = cursor.limit(Math.trunc(Math.max(1, Math.min(Number(opts.limit), 10000))));
  }
  const rows = await cursor.toArray();

  let attempted = 0;
  let succeeded = 0;
  let failed = 0;
  let perm = 0;
  const verboseRows: Doc[] = [];

  for (const row of rows) {
    attempted += 1;
    if (opts.dry_run) {
      if (opts.verbose) {
        verboseRows.push({
          id: row['id'],
          source_type: row['source_type'],
          source_id: row['source_id'],
          retry_count: row['retry_count'],
          status: row['status'],
          would_retry: true,
        });
      }
      continue;
    }

    try {
      const { deleted, written } = await reprojectForReplay(
        mongo,
        String(row['user_id']),
        String(row['company_id']),
        String(row['source_type']),
        String(row['source_id']),
      );
      await coll.updateOne(
        { id: row['id'] },
        { $set: { status: FAILURE_STATUS_RESOLVED, resolved_at: nowIso(), last_attempt_at: nowIso() } },
      );
      succeeded += 1;
      if (opts.verbose) {
        verboseRows.push({
          id: row['id'],
          source_type: row['source_type'],
          source_id: row['source_id'],
          result: 'resolved',
          deleted,
          written,
        });
      }
    } catch (ex) {
      const err = ex instanceof Error ? `${ex.name}: ${ex.message}` : String(ex);
      const newCount = Math.trunc(Number(row['retry_count'] ?? 0)) + 1;
      // Only the last four prior entries are kept.
      const history = (Array.isArray(row['history']) ? row['history'] : []).slice(-4);
      history.push({ attempt: newCount, at: nowIso(), error: err.slice(0, 400) });

      let newStatus: string;
      if (newCount >= MAX_RETRIES) {
        newStatus = FAILURE_STATUS_PERMANENTLY_FAILED;
        perm += 1;
        if (opts.verbose) {
          verboseRows.push({
            id: row['id'],
            source_type: row['source_type'],
            source_id: row['source_id'],
            result: 'permanently_failed',
            retry_count: newCount,
            error: err,
          });
        }
      } else {
        newStatus = FAILURE_STATUS_RETRYING;
        failed += 1;
        if (opts.verbose) {
          verboseRows.push({
            id: row['id'],
            source_type: row['source_type'],
            source_id: row['source_id'],
            result: 'will_retry',
            retry_count: newCount,
            error: err,
          });
        }
      }
      await coll.updateOne(
        { id: row['id'] },
        {
          $set: {
            status: newStatus,
            retry_count: newCount,
            error: err.slice(0, 2000),
            last_attempt_at: nowIso(),
            next_attempt_at: computeNextAttempt(newCount),
            history,
          },
        },
      );
    }
  }

  // `remaining` drops the schedule filter: every non-terminal row in scope.
  const remainingQ: Doc = { ...q, status: { $in: NON_TERMINAL_STATUSES } };
  delete remainingQ['next_attempt_at'];
  const remaining = await coll.countDocuments(remainingQ);

  return {
    attempted,
    succeeded,
    failed,
    permanently_failed: perm,
    remaining,
    rows: verboseRows,
    dry_run: Boolean(opts.dry_run),
  };
}

/**
 * The replay's projection call. It mirrors `reproject_source`, NOT the hook, so
 * an exception propagates and the driver above decides what it means.
 */
async function reprojectForReplay(
  mongo: Db,
  uid: string,
  cid: string,
  sourceType: string,
  sourceId: string,
): Promise<{ deleted: number; written: number }> {
  if (TS_PORTED.has(sourceType)) {
    return reprojectVendorSourceOrThrow(
      mongo,
      uid,
      cid,
      sourceType as (typeof VENDOR_SOURCE_TYPES)[number],
      sourceId,
    );
  }
  if (!hookConfigured()) {
    throw new Error(`no TypeScript projection for source_type=${sourceType} and no Python hook configured`);
  }
  const r = await callPythonHook(uid, cid, sourceType as never, sourceId);
  if (!r.ok) throw new Error(r.error ?? 'python hook reported failure');
  return { deleted: r.deleted ?? 0, written: r.written ?? 0 };
}
