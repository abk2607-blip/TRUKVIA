import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7b · WalletTransfers list read-only shadow.
 *
 *   GET /api/wallet-transfers
 *
 * Faithful shadow of:
 *   backend/routers/wallet_transfers.py::list_wallet_transfers (lines 27–49)
 *
 * STRICTLY READ-ONLY. Class-C — Python handler executes ONLY
 * `db.wallet_transfers.find(q, {_id:0, user_id:0}).sort("date",-1).to_list(5000)`.
 * Zero writer hook, zero audit call, zero backfill, zero recompute,
 * zero FinTxn / approvals / policy / counters / idempotency touch,
 * zero cross-collection reads on the GET path.
 *
 * ── GATE-7b BINDINGS ────────────────────────────────────────────────
 *
 *   1. STRICT SUBSET of Gate 7a parity surface:
 *      * NO `wallet_code` query parameter (Python source does not
 *        accept one). Client-supplied `?wallet_code=...` is silently
 *        ignored — no filter, no 422.
 *      * `date_from` / `date_to` / `include_deleted` semantics IDENTICAL
 *        to Gate 7a wallet-adjustments.
 *
 *   2. include_deleted BOOL COERCION (Pydantic v2 2.13.4 — byte-exact
 *      envelope preserved from Gate 7a):
 *      * True  set: true, True, TRUE, 1, yes, Yes, YES, on, On, ON
 *      * False set: false, False, FALSE, 0, no, No, NO, off, Off, OFF
 *      * Invalid   → HTTP 422 Pydantic bool_parsing envelope.
 *      * Omitted   → default False.
 *
 *   3. AUTH PRECEDENCE — 401 fires BEFORE query 422 for unauthenticated
 *      requests with malformed include_deleted.
 *
 *   4. DATE RANGE — plain lexicographic strings, inclusive $gte/$lte,
 *      no datetime parsing, no trim, no normalization.
 *
 *   5. FILTER ASSEMBLY (mirrors Python line-for-line):
 *      base = { user_id, company_id }
 *      if !include_deleted: base.is_deleted = { $ne: true }
 *      if date_from|date_to:
 *          rng = {}
 *          if date_from: rng.$gte = date_from
 *          if date_to:   rng.$lte = date_to
 *          base.date = rng
 *
 *   6. NO 404 BRANCH — no cross-collection existence lookup.
 *
 *   7. PROJECTION strips `_id` AND `user_id`. SORT date DESC.
 *      LIMIT 5000. Response = bare JSON array.
 *
 * Gate-7 writer boundary (out of scope for Gate 7b):
 *   POST/PUT/DELETE `/api/wallet-transfers*` remain Python-authoritative
 *   (fire hook_after_source_write + audit).
 */

interface WalletTransferDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  source_wallet_code?: string;
  destination_wallet_code?: string;
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
export async function registerWalletTransfersListReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7b (read-only)
  app.get(
    '/api/wallet-transfers',
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

      // 2. Parse query string. Only the three declared params are
      //    consumed; any extra param (including `wallet_code`) is
      //    silently ignored — matches FastAPI's default behaviour on
      //    undeclared query params.
      const query = (req.query ?? {}) as Record<string, unknown>;
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
      if (dateFrom || dateTo) {
        const rng: Record<string, unknown> = {};
        if (dateFrom) rng['$gte'] = dateFrom;
        if (dateTo) rng['$lte'] = dateTo;
        filter['date'] = rng;
      }

      // 6. Read with EXACT projection / sort / cap.
      const rows = await db
        .collection<WalletTransferDoc>('wallet_transfers')
        .find(filter as Filter<WalletTransferDoc>, {
          projection: { _id: 0, user_id: 0 },
        })
        .sort([['date', -1]])
        .limit(5000)
        .toArray();

      // Empty / no-match → naturally returns []. NO 404 branch.
      return rows;
    },
  );
}
