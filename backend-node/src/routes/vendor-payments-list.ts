import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6z · VendorPayment list read-only shadow.
 *
 *   GET /api/vendors/{vid}/payments
 *
 * Faithful shadow of:
 *   backend/routers/vendors.py::list_vendor_payments (lines 171–179)
 *
 * STRICTLY READ-ONLY. Class-C — Python handler executes ONLY
 * `db.vendor_payments.find(...).sort("date", -1).to_list(5000)`.
 * Zero writer hook, zero audit call, zero backfill, zero recompute,
 * zero FinTxn / approvals / policy / counters / idempotency touch,
 * zero cross-collection reads on the GET path.
 *
 * ── GATE-6z BINDINGS ─────────────────────────────────────────────────
 *
 *   1. SINGLE SOFT-DELETE PREDICATE — filter includes ONLY
 *      `is_deleted: {$ne: true}`. MongoDB `$ne:true` semantics:
 *        * `true`   → excluded
 *        * `false`  → included
 *        * missing → INCLUDED (unequal to `true`)
 *        * `null`  → included
 *      No `is_reversed` predicate on this GET (Python source
 *      does not include one — see routers/vendors.py:171–179).
 *
 *   2. PROJECTION STRIPS BOTH `_id` AND `user_id` — matches Python
 *      `{"_id": 0, "user_id": 0}`. Every response document has
 *      `user_id` REMOVED. Differs from Gate 6y (drivers) which
 *      keeps `user_id`.
 *
 *   3. 5000 CAP — matches Gate 6t/6u/6v/6w/6x.
 *
 *   4. ACTIVE-COMPANY CONSUMPTION — `activeCompanyId()` result is
 *      inserted into the filter. `X-Company-Id` owned override changes
 *      the returned rowset; unowned / no-header falls back to default.
 *
 *   5. NO 404 BRANCH — unlike DETAIL endpoints and unlike Gate 6y
 *      (drivers), this LIST endpoint performs NO vendor-existence
 *      pre-check. Unknown vid / wrong-company vid / no matching
 *      payments ALL return HTTP 200 with body `[]`. Mirrors the
 *      Python source exactly (no `find_one` on vendors on the GET).
 *
 * Gate-7 writer boundary (out of scope for Gate 6z):
 *   POST / PUT / DELETE `/api/vendors/{vid}/payments*` remain
 *   Python-authoritative (fire audit + party-bank snapshot capture).
 */

interface VendorPaymentDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  vendor_id?: string;
  date?: string;
  is_deleted?: boolean | null;
  [k: string]: unknown;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerVendorPaymentsListReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6z (read-only)
  app.get<{ Params: { vid: string } }>(
    '/api/vendors/:vid/payments',
    async (
      req: FastifyRequest<{ Params: { vid: string } }>,
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
      const { vid } = req.params;

      // 3. Filter with single $ne:true — plain string equality otherwise.
      const filter: Record<string, unknown> = {
        user_id: userId,
        company_id: cid,
        vendor_id: vid,
        is_deleted: { $ne: true },
      };

      // 4. Read with EXACT projection / sort / cap.
      const rows = await db
        .collection<VendorPaymentDoc>('vendor_payments')
        .find(filter as Filter<VendorPaymentDoc>, { projection: { _id: 0, user_id: 0 } })
        .sort([['date', -1]])
        .limit(5000)
        .toArray();

      // Unknown vid / wrong-company vid / no matches → naturally returns [].
      // NO vendor-existence lookup. NO 404 branch.
      return rows;
    },
  );
}
