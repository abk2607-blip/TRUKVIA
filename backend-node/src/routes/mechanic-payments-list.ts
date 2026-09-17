import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6x · MechanicPayment list read-only shadow.
 *
 *   GET /api/mechanics/{mid}/payments
 *
 * Faithful shadow of:
 *   backend/routers/mechanics.py::list_mechanic_payments (lines 152–160)
 *
 * STRICTLY READ-ONLY. Class-C — Python handler executes ONLY
 * `db.mechanic_payments.find(...).sort([('date', -1)]).to_list(5000)`.
 * Zero writer hook, zero audit call, zero backfill, zero recompute,
 * zero FinTxn / approvals / policy / counters / idempotency touch,
 * zero cross-collection reads on the GET path.
 *
 * ── GATE-6x BINDINGS ─────────────────────────────────────────────────
 *
 *   1. SINGLE SOFT-DELETE PREDICATE — filter includes `is_deleted:
 *      {$ne: true}`. MongoDB `$ne:true` semantics:
 *        * `true`   → excluded
 *        * `false`  → included
 *        * missing → INCLUDED (unequal to `true`)
 *        * `null`  → included
 *
 *   2. 5000 CAP — matches Gate 6t/6u/6v/6w.
 *
 *   3. ACTIVE-COMPANY CONSUMPTION — `activeCompanyId()` result is
 *      inserted into the filter. `X-Company-Id` owned override changes
 *      the returned rowset; unowned / no-header falls back to default.
 *
 *   4. NO 404 BRANCH — this LIST-scoped-to-mechanic endpoint performs
 *      NO mechanic-existence check (unlike POST). Unknown mid /
 *      wrong-company mid / no matching payments ALL return HTTP 200
 *      with body `[]`. Mirrors Python source exactly (no `find_one`
 *      on mechanics).
 *
 * Gate-7 writer boundary (out of scope for Gate 6x):
 *   POST / PUT / DELETE `/api/mechanics/{mid}/payments*` remain
 *   Python-authoritative (fire hook_after_source_write + audit +
 *   party-bank snapshot + company-bank source snapshot capture).
 */

interface MechanicPaymentDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  mechanic_id?: string;
  date?: string;
  is_deleted?: boolean | null;
  [k: string]: unknown;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerMechanicPaymentsListReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6x (read-only)
  app.get<{ Params: { mid: string } }>(
    '/api/mechanics/:mid/payments',
    async (
      req: FastifyRequest<{ Params: { mid: string } }>,
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
      const { mid } = req.params;

      // 3. Filter — plain string equality + single $ne:true predicate.
      const filter: Record<string, unknown> = {
        user_id: userId,
        company_id: cid,
        mechanic_id: mid,
        is_deleted: { $ne: true },
      };

      // 4. Read with EXACT projection / sort / cap.
      const rows = await db
        .collection<MechanicPaymentDoc>('mechanic_payments')
        .find(filter as Filter<MechanicPaymentDoc>, { projection: { _id: 0, user_id: 0 } })
        .sort([['date', -1]])
        .limit(5000)
        .toArray();

      // Unknown mid / wrong-company mid / no matches → naturally returns [].
      // NO mechanic-existence lookup. NO 404 branch. NO 422.
      return rows;
    },
  );
}
