import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6v · VendorBill read-only shadow.
 *
 *   GET /api/vendor-bills?vendor_id=&vehicle_id=&repair_event_id=&trip_id=
 *   GET /api/vendor-bills/{bid}
 *
 * Faithful shadow of:
 *   backend/routers/vendor_bills.py::list_vendor_bills (lines 66–83)
 *   backend/routers/vendor_bills.py::get_vendor_bill   (lines 124–134)
 *
 * STRICTLY READ-ONLY. Class-C — Python handlers execute ONLY
 * `db.vendor_bills.find(...).sort().to_list(5000)` and `.find_one(...)`.
 * Zero writer hook, zero audit call, zero backfill, zero recompute,
 * zero FinTxn / approvals / policy / counters / idempotency touch,
 * zero cross-collection reads on the GET paths.
 *
 * ── GATE-6v BINDINGS ─────────────────────────────────────────────────
 *
 *   1. SOFT-DELETE PREDICATE — filter includes `is_deleted: {$ne: true}`
 *      on BOTH endpoints. MongoDB `$ne:true` semantics:
 *        * `is_deleted:true`   → excluded
 *        * `is_deleted:false`  → included
 *        * `is_deleted` missing → INCLUDED (unequal to `true`)
 *        * `is_deleted:null`   → included
 *
 *   2. 5000 CAP (LIST) — matches Gate 6t/6u; DETAIL has no cap.
 *
 *   3. ACTIVE-COMPANY CONSUMPTION — `activeCompanyId()` result is
 *      inserted into the filter. `X-Company-Id` owned override changes
 *      the returned rowset; unowned / no-header falls back to default.
 *
 *   4. DETAIL 404 LITERAL — missing / wrong-company / soft-deleted bid
 *      ALL take the same branch → HTTP 404 with EXACT literal
 *      `"VendorBill not found"`.
 *
 * Gate-7 writer boundary (out of scope for Gate 6v):
 *   POST/PUT/DELETE `/api/vendor-bills` remain Python-authoritative.
 */

interface VendorBillDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  vendor_id?: string;
  vehicle_id?: string;
  repair_event_id?: string;
  trip_id?: string;
  bill_date?: string;
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
export async function registerVendorBillsReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6v (read-only)
  app.get(
    '/api/vendor-bills',
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
      const vendorId = firstStr(q['vendor_id']);
      const vehicleId = firstStr(q['vehicle_id']);
      const repairEventId = firstStr(q['repair_event_id']);
      const tripId = firstStr(q['trip_id']);

      const filter: Record<string, unknown> = {
        user_id: userId,
        company_id: cid,
        is_deleted: { $ne: true },
      };
      if (vendorId) filter['vendor_id'] = vendorId;
      if (vehicleId) filter['vehicle_id'] = vehicleId;
      if (repairEventId) filter['repair_event_id'] = repairEventId;
      if (tripId) filter['trip_id'] = tripId;

      // 4. Read with EXACT projection / sort / cap.
      const rows = await db
        .collection<VendorBillDoc>('vendor_bills')
        .find(filter as Filter<VendorBillDoc>, { projection: { _id: 0, user_id: 0 } })
        .sort([['bill_date', -1]])
        .limit(5000)
        .toArray();

      return rows;
    },
  );

  // migration-allowlisted: phase-3-gate-6v (read-only)
  app.get<{ Params: { bid: string } }>(
    '/api/vendor-bills/:bid',
    async (
      req: FastifyRequest<{ Params: { bid: string } }>,
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
      const { bid } = req.params;

      const doc = await db
        .collection<VendorBillDoc>('vendor_bills')
        .findOne(
          {
            id: bid, user_id: userId, company_id: cid,
            is_deleted: { $ne: true },
          } as Filter<VendorBillDoc>,
          { projection: { _id: 0, user_id: 0 } },
        );

      if (!doc) {
        reply.code(404);
        return { detail: 'VendorBill not found' };
      }
      return doc;
    },
  );
}
