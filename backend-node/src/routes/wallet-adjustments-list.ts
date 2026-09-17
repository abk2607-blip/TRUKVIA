import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7a · WalletAdjustments list read-only shadow.
 *
 *   GET /api/wallet-adjustments
 *
 * Faithful shadow of:
 *   backend/routers/wallet_adjustments.py::list_wallet_adjustments (lines 37–62)
 *
 * STRICTLY READ-ONLY. Class-C — Python handler executes ONLY
 * `db.wallet_adjustments.find(q, {_id: 0, user_id: 0})
 *      .sort("date", -1).to_list(5000)`.
 * Zero writer hook, zero audit call, zero backfill, zero recompute,
 * zero FinTxn / approvals / policy / counters / idempotency touch,
 * zero cross-collection reads on the GET path.
 *
 * ── GATE-7a BINDINGS ────────────────────────────────────────────────
 *
 *   1. NEW PARITY AXIS — query-string parsing:
 *      * `wallet_code`     Optional[str] · truthy → exact equality
 *      * `date_from`       Optional[str] · truthy → `date: {$gte}`
 *      * `date_to`         Optional[str] · truthy → `date: {$lte}`
 *      * `include_deleted` bool = False · Pydantic v2 bool coercion
 *
 *   2. include_deleted BOOL COERCION (Pydantic v2 semantics —
 *      byte-verified against pydantic 2.13.4 in the parity harness):
 *      * True  set: true, True, TRUE, 1, yes, Yes, YES, on, On, ON
 *      * False set: false, False, FALSE, 0, no, No, NO, off, Off, OFF
 *      * Invalid   → HTTP 422 with EXACT FastAPI/Pydantic v2 envelope:
 *          {
 *            "detail": [{
 *              "type": "bool_parsing",
 *              "loc": ["query", "include_deleted"],
 *              "msg": "Input should be a valid boolean, unable to interpret input",
 *              "input": "<raw value>",
 *              "url": "https://errors.pydantic.dev/2.13/v/bool_parsing"
 *            }]
 *          }
 *      * Blank string "" is INVALID (not falsy default) → 422.
 *      * Omitted parameter → default False.
 *
 *   3. DATE RANGE — plain lexicographic strings. No datetime parsing,
 *      no trim, no timezone. `$gte`/`$lte` are inclusive.
 *
 *   4. FILTER ASSEMBLY (exact Python order preserved):
 *      base = { user_id, company_id }
 *      if !include_deleted: base.is_deleted = { $ne: true }
 *      if wallet_code:      base.wallet_code = <v>
 *      if date_from|date_to:
 *          rng = {}
 *          if date_from: rng.$gte = date_from
 *          if date_to:   rng.$lte = date_to
 *          base.date = rng
 *
 *   5. AUTH PRECEDENCE — locked authenticate() fires BEFORE query
 *      validation. Unauthenticated → 401 literals regardless of
 *      malformed include_deleted.
 *
 *   6. NO 404 BRANCH — no cross-collection existence lookup.
 *
 *   7. PROJECTION strips `_id` AND `user_id` (parity with Gate 6z).
 *      SORT date DESC. LIMIT 5000. Response = bare JSON array.
 *
 * Gate-7 writer boundary (out of scope for Gate 7a):
 *   POST/PUT/DELETE `/api/wallet-adjustments*` and
 *   POST `/api/wallet-adjustments/{wa_id}/reverse` remain
 *   Python-authoritative (fire hook_after_source_write + audit +
 *   append-only reversal semantics).
 */

interface WalletAdjustmentDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  wallet_code?: string;
  date?: string;
  is_deleted?: boolean | null;
  [k: string]: unknown;
}

// ── Pydantic-v2 bool coercion (byte-verified against 2.13.4) ──────────
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

// Read a single query-string value; Fastify may parse repeated keys as
// arrays but our contract expects a scalar — use the LAST occurrence
// to match FastAPI's default behaviour on repeated query parameters.
function qParam(query: Record<string, unknown>, key: string): string | undefined {
  const v = query[key];
  if (v === undefined || v === null) return undefined;
  if (Array.isArray(v)) return v.length ? String(v[v.length - 1]) : undefined;
  return String(v);
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerWalletAdjustmentsListReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7a (read-only)
  app.get(
    '/api/wallet-adjustments',
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

      // 4. Active-company resolution (after auth, before filter build).
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
      const rows = await db
        .collection<WalletAdjustmentDoc>('wallet_adjustments')
        .find(filter as Filter<WalletAdjustmentDoc>, {
          projection: { _id: 0, user_id: 0 },
        })
        .sort([['date', -1]])
        .limit(5000)
        .toArray();

      // Empty / no-match / unknown wallet_code → naturally returns [].
      // NO cross-collection lookup. NO 404 branch.
      return rows;
    },
  );
}
