import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6y · DriverPayment list read-only shadow.
 *
 *   GET /api/drivers/{did}/payments
 *
 * Faithful shadow of:
 *   backend/routers/driver_payments.py::_ensure_driver     (lines 40–45)
 *   backend/routers/driver_payments.py::list_driver_payments (lines 48–56)
 *
 * STRICTLY READ-ONLY. Class-C — Python performs exactly two reads:
 *   1. drivers.find_one({user_id, company_id, id: did}, {_id: 0})
 *   2. driver_payments.find({... is_deleted:{$ne:true}}, {_id: 0}).sort([('date', -1)])
 * No writer hook, no audit, no backfill, no recompute, no FinTxn,
 * no approvals, no policy, no counters, no idempotency, no
 * cross-collection writes.
 *
 * ── GATE-6y BINDINGS ─────────────────────────────────────────────────
 *
 *   1. CROSS-COLLECTION PRE-CHECK — a single `drivers.findOne` is
 *      executed BEFORE the payments read. Unknown / wrong-company did
 *      → HTTP 404 with EXACT literal `"Driver not found"`.
 *
 *   2. SINGLE SOFT-DELETE PREDICATE — `is_deleted:{$ne:true}`. Mongo
 *      canonical semantics (missing key inclusive).
 *
 *   3. PROJECTION ASYMMETRY — payment projection is `{_id: 0}` ONLY.
 *      `user_id` REMAINS in every response document. Do NOT strip.
 *
 *   4. NO 5000 CAP — Python uses unbounded async cursor iteration
 *      (`[d async for d in cur]`) with no `.to_list(5000)`. Node must
 *      NOT introduce `.limit(...)` either.
 *
 *   5. ACTIVE-COMPANY CONSUMPTION — `activeCompanyId()` result is
 *      inserted into BOTH the driver pre-check filter AND the payments
 *      filter. X-Company-Id owned override / unowned fallback / default.
 *
 * Gate-7 writer boundary (out of scope for Gate 6y):
 *   POST/PUT/DELETE `/api/drivers/{did}/payments*` and POST
 *   `/api/driver-payments/{pid}/correct` remain Python-authoritative.
 */

interface DriverPaymentDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  driver_id?: string;
  date?: string;
  is_deleted?: boolean | null;
  [k: string]: unknown;
}

interface DriverDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  [k: string]: unknown;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerDriverPaymentsListReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6y (read-only)
  app.get<{ Params: { did: string } }>(
    '/api/drivers/:did/payments',
    async (
      req: FastifyRequest<{ Params: { did: string } }>,
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
      const { did } = req.params;

      // 3. Cross-collection pre-check on drivers (READ ONLY).
      const driver = await db
        .collection<DriverDoc>('drivers')
        .findOne(
          { user_id: userId, company_id: cid, id: did } as Filter<DriverDoc>,
          { projection: { _id: 0 } },
        );
      if (!driver) {
        reply.code(404);
        return { detail: 'Driver not found' };
      }

      // 4. Payments read — projection strips ONLY `_id`; user_id remains.
      //    No .limit — Python uses unbounded cursor iteration.
      const rows = await db
        .collection<DriverPaymentDoc>('driver_payments')
        .find(
          {
            user_id: userId,
            company_id: cid,
            driver_id: did,
            is_deleted: { $ne: true },
          } as Filter<DriverPaymentDoc>,
          { projection: { _id: 0 } },
        )
        .sort([['date', -1]])
        .toArray();

      return rows;
    },
  );
}
