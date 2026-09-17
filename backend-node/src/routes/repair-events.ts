import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6t · RepairEvent read-only shadow.
 *
 *   GET /api/repair-events?vehicle_id=&trip_id=&status=
 *   GET /api/repair-events/{rid}
 *
 * Faithful shadow of:
 *   backend/routers/repair_events.py::list_repair_events (lines 39–54)
 *   backend/routers/repair_events.py::get_repair_event   (lines 91–101)
 *
 * STRICTLY READ-ONLY. Class-C — Python handlers execute ONLY
 * `db.repair_events.find(...).sort().to_list(5000)` and `.find_one(...)`.
 * Zero writer hook, zero audit call, zero backfill, zero recompute,
 * zero FinTxn / approvals / policy / counters / idempotency touch,
 * zero cross-collection reads on the GET paths.
 *
 * ── GATE-6t NEW DIMENSIONS (BIND PRECISELY) ─────────────────────────
 *
 *   1. SOFT-DELETE PREDICATE — filter includes `is_deleted: {$ne: true}`
 *      on BOTH endpoints. MongoDB `$ne:true` semantics:
 *        * `is_deleted:true`   → excluded
 *        * `is_deleted:false`  → included
 *        * `is_deleted` missing → INCLUDED (unequal to `true`)
 *        * `is_deleted:null`   → included
 *
 *   2. 5000 CAP (LIST) — larger than prior gates' 500 cap; DETAIL has
 *      no cap.
 *
 *   3. ACTIVE-COMPANY CONSUMPTION — `activeCompanyId()` result is
 *      inserted into the filter (unlike Gate 6r/6s where it was only
 *      invocation-parity). `X-Company-Id` owned override changes the
 *      returned rowset; unowned falls back to default.
 *
 *   4. DETAIL 404 LITERAL — missing / wrong-company / soft-deleted rid
 *      ALL take the same branch → HTTP 404 with EXACT literal
 *      `"RepairEvent not found"`.
 *
 * Gate-7 writer boundary (out of scope for Gate 6t):
 *   POST/PUT/DELETE `/api/repair-events` remain Python-authoritative.
 */

interface RepairEventDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  vehicle_id?: string;
  trip_id?: string;
  status?: string;
  event_date?: string;
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
export async function registerRepairEventsReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6t (read-only)
  app.get(
    '/api/repair-events',
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

      // 2. Active-company MUST be consumed in the filter (Gate-6t new
      //    dimension vs 6r/6s where invocation was invocation-parity only).
      const cid = await activeCompanyId(req, userId, db);

      // 3. Optional truthy-gated filters.
      const q = (req.query ?? {}) as Record<string, unknown>;
      const vehicleId = firstStr(q['vehicle_id']);
      const tripId = firstStr(q['trip_id']);
      const status = firstStr(q['status']);

      const filter: Record<string, unknown> = {
        user_id: userId,
        company_id: cid,
        is_deleted: { $ne: true },
      };
      if (vehicleId) filter['vehicle_id'] = vehicleId;
      if (tripId) filter['trip_id'] = tripId;
      if (status) filter['status'] = status;

      // 4. Read with EXACT projection / sort / cap.
      const rows = await db
        .collection<RepairEventDoc>('repair_events')
        .find(filter as Filter<RepairEventDoc>, { projection: { _id: 0, user_id: 0 } })
        .sort([['event_date', -1]])
        .limit(5000)
        .toArray();

      return rows;
    },
  );

  // migration-allowlisted: phase-3-gate-6t (read-only)
  app.get<{ Params: { rid: string } }>(
    '/api/repair-events/:rid',
    async (
      req: FastifyRequest<{ Params: { rid: string } }>,
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
      const { rid } = req.params;

      const doc = await db
        .collection<RepairEventDoc>('repair_events')
        .findOne(
          {
            id: rid, user_id: userId, company_id: cid,
            is_deleted: { $ne: true },
          } as Filter<RepairEventDoc>,
          { projection: { _id: 0, user_id: 0 } },
        );

      if (!doc) {
        reply.code(404);
        return { detail: 'RepairEvent not found' };
      }
      return doc;
    },
  );
}
