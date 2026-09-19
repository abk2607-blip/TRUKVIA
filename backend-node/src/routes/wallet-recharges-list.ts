import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter, FindCursor } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

// ── Gate 9e · Motor `to_list(n)` (route-local) ────────────────────────
// Motor sends NO server-side limit for `to_list(n)`; a `.limit(n)` turns the
// sort into a top-k whose tie order at the cap differs (verified live). Read
// the sorted cursor and stop after n documents, exactly like Motor.
async function motorToList<T>(cursor: FindCursor<T>, n: number): Promise<T[]> {
  const out: T[] = [];
  try {
    if (n <= 0) {
      await cursor.hasNext(); // to_list(0) still issues the find, returns []
      return out;
    }
    for await (const doc of cursor) {
      out.push(doc);
      if (out.length >= n) break;
    }
  } finally {
    await cursor.close();
  }
  return out;
}

/**
 * TRUKVIA · Phase-3 · Gate-7c · WalletRecharges list read-only shadow.
 *
 *   GET /api/wallet-recharges
 *
 * Faithful shadow of:
 *   backend/routers/wallet_recharges.py::list_wallet_recharges (lines 28–53)
 *
 * STRICTLY READ-ONLY. Class-C — Python handler executes ONLY
 * `db.wallet_recharges.find(q, {_id:0, user_id:0}).sort("date",-1).to_list(5000)`.
 * Zero writer hook / audit / backfill / recompute / FinTxn / approvals /
 * policy / counters / idempotency / cross-collection reads on the GET path.
 *
 * ── GATE-7c BINDINGS ────────────────────────────────────────────────
 *
 *   1. Contract IDENTICAL LINE-FOR-LINE to Gate 7a wallet-adjustments
 *      except for the collection name (`wallet_recharges`) and route
 *      path. Same four query params, same filter assembly, same
 *      projection/sort/limit, same auth+422 precedence, same byte-exact
 *      Pydantic v2 bool_parsing envelope.
 *
 *   2. include_deleted BOOL COERCION (Pydantic v2 2.13.4):
 *      * True  set: true, True, TRUE, 1, yes, Yes, YES, on, On, ON
 *      * False set: false, False, FALSE, 0, no, No, NO, off, Off, OFF
 *      * Invalid   → HTTP 422 with byte-exact Pydantic envelope.
 *      * Omitted   → default False.
 *
 *   3. AUTH PRECEDENCE — 401 fires BEFORE query 422.
 *
 *   4. FILTER ASSEMBLY (mirrors Python line-for-line):
 *      base = { user_id, company_id }
 *      if !include_deleted: base.is_deleted = { $ne: true }
 *      if wallet_code:      base.wallet_code = <v>
 *      if date_from|date_to:
 *          rng = {}
 *          if date_from: rng.$gte = date_from
 *          if date_to:   rng.$lte = date_to
 *          base.date = rng
 *
 *   5. NO 404 BRANCH — no cross-collection existence lookup.
 *
 * Gate-7 writer boundary (out of scope for Gate 7c):
 *   POST / PUT / DELETE `/api/wallet-recharges*` remain
 *   Python-authoritative (fire hook_after_source_write + audit).
 */

interface WalletRechargeDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  wallet_code?: string;
  funding_mode?: string;
  date?: string;
  is_deleted?: boolean | null;
  [k: string]: unknown;
}

// ── Pydantic-v2 bool coercion (route-local; duplicated from Gate 7a) ──
const PYDANTIC_BOOL_URL = 'https://errors.pydantic.dev/2.13/v/bool_parsing';
const PYDANTIC_BOOL_MSG = 'Input should be a valid boolean, unable to interpret input';
const TRUE_TOKENS = new Set(['true', 'True', 'TRUE', '1', 'yes', 'Yes', 'YES', 'on', 'On', 'ON']);
const FALSE_TOKENS = new Set(['false', 'False', 'FALSE', '0', 'no', 'No', 'NO', 'off', 'Off', 'OFF']);

function coerceBool(raw: string): boolean | null {
  if (TRUE_TOKENS.has(raw)) return true;
  if (FALSE_TOKENS.has(raw)) return false;
  return null;
}

function pydanticBoolParsing422(input: string): Record<string, unknown> {
  return {
    detail: [
      {
        type: 'bool_parsing',
        loc: ['query', 'include_deleted'],
        msg: PYDANTIC_BOOL_MSG,
        input,
        url: PYDANTIC_BOOL_URL,
      },
    ],
  };
}

function qParam(query: Record<string, unknown>, key: string): string | undefined {
  const v = query[key];
  if (v === undefined || v === null) return undefined;
  if (Array.isArray(v)) return v.length ? String(v[v.length - 1]) : undefined;
  return String(v);
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerWalletRechargesListReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7c (read-only)
  app.get(
    '/api/wallet-recharges',
    async (req: FastifyRequest, reply: FastifyReply) => {
      // 1. Auth FIRST — locked 401 literals. Auth precedes query 422.
      let userId: string;
      try {
        userId = (await authenticate(req, db)).user_id;
      } catch (err) {
        if (err instanceof HttpError) {
          reply.code(err.status);
          return { detail: err.detail };
        }
        throw err;
      }

      // 2. Parse query string.
      const query = (req.query ?? {}) as Record<string, unknown>;
      const walletCode = qParam(query, 'wallet_code');
      const dateFrom = qParam(query, 'date_from');
      const dateTo = qParam(query, 'date_to');
      const includeDeletedRaw = qParam(query, 'include_deleted');

      // 3. include_deleted bool coercion — Pydantic v2 semantics.
      let includeDeleted = false;
      if (includeDeletedRaw !== undefined) {
        const b = coerceBool(includeDeletedRaw);
        if (b === null) {
          reply.code(422);
          return pydanticBoolParsing422(includeDeletedRaw);
        }
        includeDeleted = b;
      }

      // 4. Active-company resolution.
      const cid = await activeCompanyId(req, userId, db);

      // 5. Filter assembly — mirrors Python line-for-line.
      const filter: Record<string, unknown> = {
        user_id: userId,
        company_id: cid,
      };
      if (!includeDeleted) {
        filter['is_deleted'] = { $ne: true };
      }
      if (walletCode) {
        filter['wallet_code'] = walletCode;
      }
      if (dateFrom || dateTo) {
        const rng: Record<string, unknown> = {};
        if (dateFrom) rng['$gte'] = dateFrom;
        if (dateTo) rng['$lte'] = dateTo;
        filter['date'] = rng;
      }

      // 6. Read with EXACT projection / sort / cap.
      const rows = await motorToList(
        db
        .collection<WalletRechargeDoc>('wallet_recharges')
        .find(filter as Filter<WalletRechargeDoc>, {
          projection: { _id: 0, user_id: 0 },
        })
        .sort([['date', -1]]),
        5000,
      );

      // NO 404. Unknown wallet_code / empty result → 200 [].
      return rows;
    },
  );
}
