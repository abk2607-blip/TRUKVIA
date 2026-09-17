import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6w · SupplierPayment list read-only shadow.
 *
 *   GET /api/suppliers/{sid}/payments
 *
 * Faithful shadow of:
 *   backend/routers/suppliers.py::list_payments (lines 298–306)
 *
 * STRICTLY READ-ONLY. Class-C — Python handler executes ONLY
 * `db.supplier_payments.find(...).sort([('date', -1)]).to_list(5000)`.
 * Zero writer hook, zero audit call, zero backfill, zero recompute,
 * zero FinTxn / approvals / policy / counters / idempotency touch,
 * zero cross-collection reads on the GET path.
 *
 * ── GATE-6w BINDINGS ─────────────────────────────────────────────────
 *
 *   1. DUAL SOFT-DELETE / SOFT-REVERSED PREDICATES — filter includes
 *      BOTH `is_deleted: {$ne: true}` AND `is_reversed: {$ne: true}`
 *      applied as AND. MongoDB `$ne:true` semantics apply to each:
 *        * `true`   → excluded
 *        * `false`  → included
 *        * missing → INCLUDED (unequal to `true`)
 *        * `null`  → included
 *
 *   2. 5000 CAP — matches Gate 6t/6u/6v.
 *
 *   3. ACTIVE-COMPANY CONSUMPTION — `activeCompanyId()` result is
 *      inserted into the filter. `X-Company-Id` owned override changes
 *      the returned rowset; unowned / no-header falls back to default.
 *
 *   4. NO 404 BRANCH — unlike DETAIL endpoints in earlier gates, this
 *      LIST-scoped-to-supplier endpoint performs NO supplier-existence
 *      check. Unknown sid / wrong-company sid / no matching payments
 *      ALL return HTTP 200 with body `[]`. This mirrors the Python
 *      source exactly (no `find_one` on suppliers).
 *
 * Gate-7 writer boundary (out of scope for Gate 6w):
 *   POST / PUT / DELETE `/api/suppliers/{sid}/payments*` remain
 *   Python-authoritative (fire hook_after_source_write + audit +
 *   party-bank snapshot capture).
 */

interface SupplierPaymentDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  supplier_id?: string;
  date?: string;
  is_deleted?: boolean | null;
  is_reversed?: boolean | null;
  [k: string]: unknown;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerSupplierPaymentsListReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6w (read-only)
  app.get<{ Params: { sid: string } }>(
    '/api/suppliers/:sid/payments',
    async (
      req: FastifyRequest<{ Params: { sid: string } }>,
      reply: FastifyReply,
    ) => {
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

      // 2. Active-company consumed in filter.
      const cid = await activeCompanyId(req, userId, db);
      const { sid } = req.params;

      // 3. Filter with dual $ne:true — plain string equality otherwise.
      const filter: Record<string, unknown> = {
        user_id: userId,
        company_id: cid,
        supplier_id: sid,
        is_deleted: { $ne: true },
        is_reversed: { $ne: true },
      };

      // 4. Read with EXACT projection / sort / cap.
      const rows = await db
        .collection<SupplierPaymentDoc>('supplier_payments')
        .find(filter as Filter<SupplierPaymentDoc>, { projection: { _id: 0, user_id: 0 } })
        .sort([['date', -1]])
        .limit(5000)
        .toArray();

      // Unknown sid / wrong-company sid / no matches → naturally returns [].
      // NO supplier-existence lookup. NO 404 branch.
      return rows;
    },
  );
}
