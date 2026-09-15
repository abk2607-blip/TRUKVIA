import type { FastifyInstance } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { z } from 'zod';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6b · Trips list read-only shadow.
 *   GET /api/trips
 * Faithful shadow of
 *   backend/routers/trips.py::list_trips + _build_trip_filter_query
 *
 * STRICTLY READ-ONLY. Node performs ZERO writes on ANY collection.
 *
 * Gate-6b Class-B observation — Python-only legacy multi-company
 * backfill preserved for strict parity.
 *   Python `list_trips` invokes `_backfill_to_default(user_id)` on every
 *   request which may write to `companies` and legacy tenant collections.
 *   Node intentionally does NOT reproduce this write. For fresh multi-
 *   company tenants this is a Python-side no-op, so response parity holds.
 *
 * Response contract:
 *   - Raw JSON array of Trip docs (projection `{_id:0, user_id:0}`).
 *   - Sort: `[(date,-1), (created_at,-1)]` — string-compare, no Date coerce.
 *   - Pagination via response headers:
 *       X-Total-Count, X-Has-More,
 *       Access-Control-Expose-Headers: X-Total-Count, X-Has-More
 *   - `ids` short-circuit: bypass filter builder + sort + pagination +
 *     headers; return `[]` if empty after strip.
 */

// Bounds mirror FastAPI `Query(2000, ge=1, le=2000)` / `Query(0, ge=0)`.
const QuerySchema = z.object({
  customer_id: z.string().optional(),
  vehicle_id: z.string().optional(),
  supplier_id: z.string().optional(),
  status: z.string().optional(),
  date: z.string().optional(),
  date_from: z.string().optional(),
  date_to: z.string().optional(),
  q: z.string().optional(),
  halting_only: z.union([z.literal('true'), z.literal('false'), z.boolean()]).optional(),
  missing_cust_ref: z.union([z.literal('true'), z.literal('false'), z.boolean()]).optional(),
  ids: z.string().optional(),
  limit: z.coerce.number().int().min(1).max(2000).default(2000),
  offset: z.coerce.number().int().min(0).default(0),
});

const asBool = (v: unknown): boolean => v === true || v === 'true';

// Mirror Python `re.escape` for the set of regex metacharacters that could
// appear in a Trip `q` search. Bounded escape function — no ReDoS.
function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

interface FilterOpts {
  userId: string; cid: string;
  customer_id?: string; vehicle_id?: string; supplier_id?: string; status?: string;
  date?: string; date_from?: string; date_to?: string;
  q?: string; halting_only?: boolean; missing_cust_ref?: boolean;
}

async function buildTripFilter(db: Db, o: FilterOpts): Promise<Filter<Record<string, unknown>>> {
  const q: Record<string, unknown> = { user_id: o.userId, company_id: o.cid };
  if (o.customer_id) q['customer_id'] = o.customer_id;
  if (o.vehicle_id) q['vehicle_id'] = o.vehicle_id;
  if (o.supplier_id) q['supplier_id'] = o.supplier_id;
  if (o.status) q['status'] = o.status;
  if (o.halting_only) q['halting_amount'] = { $gt: 0 };
  if (o.missing_cust_ref) {
    const blank = { $in: [null, ''] };
    const andList = (q['$and'] as unknown[] | undefined) ?? [];
    q['$and'] = [
      ...andList,
      { $or: [{ customer_reference_number: blank }, { customer_reference_number: { $exists: false } }] },
      { $or: [{ customer_invoice_no: blank }, { customer_invoice_no: { $exists: false } }] },
      { $or: [{ waybill_no: blank }, { waybill_no: { $exists: false } }] },
    ];
  }
  if (o.date) {
    q['date'] = o.date;
  } else {
    const rng: Record<string, string> = {};
    if (o.date_from) rng['$gte'] = o.date_from;
    if (o.date_to) rng['$lte'] = o.date_to;
    if (Object.keys(rng).length) q['date'] = rng;
  }
  if (o.q && o.q.trim()) {
    const pattern = new RegExp(escapeRegex(o.q.trim()), 'i');
    let custIds: string[] = [];
    try {
      const custDocs = await db.collection('customers').find(
        { user_id: o.userId, company_id: o.cid, name: pattern },
        { projection: { id: 1, _id: 0 } },
      ).limit(50).toArray();
      custIds = custDocs.map((c) => c['id'] as string);
    } catch { custIds = []; }
    const orClauses: Record<string, unknown>[] = [
      { lr_number: pattern }, { vehicle_number: pattern },
      { from_location: pattern }, { to_location: pattern },
      { external_invoice_no: pattern }, { customer_invoice_no: pattern },
      { waybill_no: pattern }, { driver_name: pattern }, { supplier_name: pattern },
    ];
    if (custIds.length) orClauses.push({ customer_id: { $in: custIds } });
    q['$or'] = orClauses;
  }
  return q as Filter<Record<string, unknown>>;
}

export async function registerTripsListRoute(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6b (read-only)
  app.get('/api/trips', async (req, reply) => {
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

    const parsed = QuerySchema.safeParse(req.query);
    if (!parsed.success) {
      reply.code(422);
      return {
        detail: parsed.error.issues.map((i) => ({
          loc: ['query', ...i.path.map(String)],
          msg: i.message, type: i.code,
        })),
      };
    }
    const p = parsed.data;
    const cid = await activeCompanyId(req, userId, db);

    // NOTE (Gate-6b Class-B): Python calls `_backfill_to_default(user_id)`
    // here. Node intentionally does not. Zero writes on this route.

    const trips = db.collection('trips');

    // `ids` short-circuit — bypass filter builder + sort + pagination.
    // Matches Python `if ids:` (falsy on empty string → falls through).
    if (p.ids) {
      const idList = p.ids.split(',').map((s) => s.trim()).filter((s) => s.length > 0);
      if (idList.length === 0) return [];
      return await trips.find(
        { user_id: userId, company_id: cid, id: { $in: idList } },
        { projection: { _id: 0, user_id: 0 } },
      ).toArray();
    }

    const mongoQ = await buildTripFilter(db, {
      userId, cid,
      customer_id: p.customer_id, vehicle_id: p.vehicle_id, supplier_id: p.supplier_id,
      status: p.status, date: p.date, date_from: p.date_from, date_to: p.date_to,
      q: p.q, halting_only: asBool(p.halting_only), missing_cust_ref: asBool(p.missing_cust_ref),
    });

    const total = await trips.countDocuments(mongoQ);
    const docs = await trips.find(mongoQ, { projection: { _id: 0, user_id: 0 } })
      .sort([['date', -1], ['created_at', -1]])
      .skip(p.offset).limit(p.limit)
      .toArray();

    reply.header('X-Total-Count', String(total));
    reply.header('X-Has-More', (p.offset + docs.length) < total ? 'true' : 'false');
    reply.header('Access-Control-Expose-Headers', 'X-Total-Count, X-Has-More');
    return docs;
  });
}
