import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7q · FinTxn detail read-only shadow.
 *
 *   GET /api/fin/fin-txn/{txid}
 *
 * Faithful shadow of:
 *   backend/routers/fin_day_book.py::get_fin_txn (L124-162)
 *
 * STRICTLY READ-ONLY. Class-C — Python performs at most two reads:
 *   1. fin_txn.find_one({id: txid, user_id, company_id}, {_id:0, user_id:0})
 *   2. <coll_map[source_type]>.find_one({user_id, company_id, id: source_id},
 *                                       {_id:0, user_id:0})
 * Zero writer hook / audit / reproject / backfill. The owner-only
 * `POST /api/fin/reproject` bridge in the same router is OUT OF SCOPE.
 *
 * ── GATE-7q BINDINGS ────────────────────────────────────────────────
 *
 *   1. ORDER: auth → `_active_company_id` → txn read → 404
 *      {"detail": "FinTxn not found"} → best-effort source lookup.
 *
 *   2. SOURCE LOOKUP (best effort, Python `try/except Exception: pass`):
 *        stype = row.source_type or ""   ;   sid = row.source_id or ""
 *        only when `stype in coll_map` (string key, exact match) →
 *        find_one in the mapped collection; `if src` → {collection, doc}.
 *      Any failure (unhashable stype, DB error) → `source: {}`.
 *      `driver_payment` is intentionally ABSENT from coll_map (known
 *      Iter150C gap) — reproduced verbatim, not fixed here.
 *
 *   3. RESPONSE: `{txn, source}` — `source` is `{}` or `{collection, doc}`.
 *      Both projections strip `_id` AND `user_id`.
 *
 *   4. EMPTY SEGMENT / ENCODED SLASH — Starlette `[^/]+` params on the
 *      decoded path: `//`-style empty or decoded "/" `txid` never reaches
 *      the handler → 404 {"detail":"Not Found"} before auth.
 */

type Doc = Record<string, unknown>;

// Python `coll_map` — insertion order irrelevant; exact string keys only.
const COLL_MAP = new Map<string, string>([
  ['invoice', 'invoices'],
  ['credit_debit_note', 'credit_debit_notes'],
  ['supplier_payment', 'supplier_payments'],
  ['vendor_payment', 'vendor_payments'],
  ['mechanic_payment', 'mechanic_payments'],
  ['expense', 'expenses'],
  ['vendor_bill', 'vendor_bills'],
  ['mechanic_work_order', 'mechanic_work_orders'],
  ['trip_customer_receipt', 'trips'],
  ['wallet_recharge', 'wallet_recharges'],
  ['wallet_transfer', 'wallet_transfers'],
  ['wallet_adjustment', 'wallet_adjustments'],
]);

// Python truthiness for values Mongo can return (used for `x or ""`).
function pyTruthy(v: unknown): boolean {
  if (v === null || v === undefined) return false;
  if (typeof v === 'boolean') return v;
  if (typeof v === 'number') return v !== 0;
  if (typeof v === 'bigint') return v !== 0n;
  if (typeof v === 'string') return v.length > 0;
  if (Array.isArray(v)) return v.length > 0;
  if (v instanceof Date) return true;
  const bsonType = (v as { _bsontype?: unknown })._bsontype;
  if (bsonType === 'Binary') return (v as { length(): number }).length() > 0;
  if (bsonType !== undefined) return true;
  return Object.keys(v as object).length > 0;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerFinTxnDetailRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7q (read-only)
  app.get('/api/fin/fin-txn/:txid', async (req: FastifyRequest, reply: FastifyReply) => {
    const txid = (req.params as { txid: string }).txid;

    // 0. Starlette never routes an empty segment or decoded "/" into a param.
    if (txid === '' || txid.includes('/')) {
      reply.code(404);
      return { detail: 'Not Found' };
    }

    // 1. Auth FIRST — locked 401 literals.
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

    // 2. Active-company resolution (locked helper).
    const cid = await activeCompanyId(req, userId, db);

    // 3. Primary read.
    const row = await db
      .collection<Doc>('fin_txn')
      .findOne(
        { id: txid, user_id: userId, company_id: cid } as Filter<Doc>,
        { projection: { _id: 0, user_id: 0 } },
      );
    if (!row || Object.keys(row).length === 0) {
      reply.code(404);
      return { detail: 'FinTxn not found' };
    }

    // 4. Best-effort source back-reference (Python try/except: pass).
    let source: Doc = {};
    try {
      const stype = pyTruthy(row['source_type']) ? row['source_type'] : '';
      const sid = pyTruthy(row['source_id']) ? row['source_id'] : '';
      const coll = typeof stype === 'string' ? COLL_MAP.get(stype) : undefined;
      if (coll !== undefined) {
        const src = await db
          .collection<Doc>(coll)
          .findOne(
            { user_id: userId, company_id: cid, id: sid } as Filter<Doc>,
            { projection: { _id: 0, user_id: 0 } },
          );
        if (pyTruthy(src)) {
          source = { collection: coll, doc: src };
        }
      }
    } catch {
      source = {};
    }

    return { txn: row, source };
  });
}
