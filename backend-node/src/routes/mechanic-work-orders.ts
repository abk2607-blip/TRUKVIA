import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6u · MechanicWorkOrder read-only shadow.
 *
 *   GET /api/mechanic-work-orders?mechanic_id=&vehicle_id=&repair_event_id=&trip_id=
 *   GET /api/mechanic-work-orders/{wid}
 *
 * Faithful shadow of:
 *   backend/routers/mechanic_work_orders.py::list_mechanic_work_orders (63–80)
 *   backend/routers/mechanic_work_orders.py::get_mechanic_work_order    (113–123)
 *
 * STRICTLY READ-ONLY. Class-C — Python handlers execute ONLY
 * `db.mechanic_work_orders.find(...).sort().to_list(5000)` and `.find_one(...)`.
 * Zero writer hook, zero audit call, zero backfill, zero recompute,
 * zero FinTxn / approvals / policy / counters / idempotency touch,
 * zero cross-collection reads on the GET paths (unlike POST/PUT/DELETE
 * which are out of scope for Gate 6u).
 *
 * ── GATE-6u BINDINGS ─────────────────────────────────────────────────
 *
 *   1. SOFT-DELETE PREDICATE — filter includes `is_deleted: {$ne: true}`
 *      on BOTH endpoints. MongoDB `$ne:true` semantics:
 *        * `is_deleted:true`   → excluded
 *        * `is_deleted:false`  → included
 *        * `is_deleted` missing → INCLUDED (unequal to `true`)
 *        * `is_deleted:null`   → included
 *
 *   2. 5000 CAP (LIST) — matches Gate 6t; DETAIL has no cap.
 *
 *   3. ACTIVE-COMPANY CONSUMPTION — `activeCompanyId()` result is
 *      inserted into the filter. `X-Company-Id` owned override changes
 *      the returned rowset; unowned / no-header falls back to default.
 *
 *   4. DETAIL 404 LITERAL — missing / wrong-company / soft-deleted wid
 *      ALL take the same branch → HTTP 404 with EXACT literal
 *      `"MechanicWorkOrder not found"`.
 *
 * Gate-7 writer boundary (out of scope for Gate 6u):
 *   POST/PUT/DELETE `/api/mechanic-work-orders` remain Python-authoritative.
 */

interface MechanicWorkOrderDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  mechanic_id?: string;
  vehicle_id?: string;
  repair_event_id?: string;
  trip_id?: string;
  work_date?: string;
  is_deleted?: boolean | null;
  [k: string]: unknown;
}

function firstStr(v: unknown): string | undefined {
  if (typeof v === 'string') return v;
  if (Array.isArray(v)) {
    const first = v[0];
    return typeof first === 'string' ? first : undefined;
  }
  return undefined;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerMechanicWorkOrdersReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6u (read-only)
  app.get(
    '/api/mechanic-work-orders',
    async (req: FastifyRequest, reply: FastifyReply) => {
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

      // 3. Optional truthy-gated filters (plain string equality).
      const q = (req.query ?? {}) as Record<string, unknown>;
      const mechanicId = firstStr(q['mechanic_id']);
      const vehicleId = firstStr(q['vehicle_id']);
      const repairEventId = firstStr(q['repair_event_id']);
      const tripId = firstStr(q['trip_id']);

      const filter: Record<string, unknown> = {
        user_id: userId,
        company_id: cid,
        is_deleted: { $ne: true },
      };
      if (mechanicId) filter['mechanic_id'] = mechanicId;
      if (vehicleId) filter['vehicle_id'] = vehicleId;
      if (repairEventId) filter['repair_event_id'] = repairEventId;
      if (tripId) filter['trip_id'] = tripId;

      // 4. Read with EXACT projection / sort / cap.
      const rows = await db
        .collection<MechanicWorkOrderDoc>('mechanic_work_orders')
        .find(filter as Filter<MechanicWorkOrderDoc>, { projection: { _id: 0, user_id: 0 } })
        .sort([['work_date', -1]])
        .limit(5000)
        .toArray();

      return rows;
    },
  );

  // migration-allowlisted: phase-3-gate-6u (read-only)
  app.get<{ Params: { wid: string } }>(
    '/api/mechanic-work-orders/:wid',
    async (
      req: FastifyRequest<{ Params: { wid: string } }>,
      reply: FastifyReply,
    ) => {
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
      const cid = await activeCompanyId(req, userId, db);
      const { wid } = req.params;

      const doc = await db
        .collection<MechanicWorkOrderDoc>('mechanic_work_orders')
        .findOne(
          {
            id: wid, user_id: userId, company_id: cid,
            is_deleted: { $ne: true },
          } as Filter<MechanicWorkOrderDoc>,
          { projection: { _id: 0, user_id: 0 } },
        );

      if (!doc) {
        reply.code(404);
        return { detail: 'MechanicWorkOrder not found' };
      }
      return doc;
    },
  );
}
