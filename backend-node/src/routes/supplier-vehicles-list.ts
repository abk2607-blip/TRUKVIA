import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter, FindCursor } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

// ── Gate 9e · Motor `to_list(n)` (route-local) ────────────────────────
// Motor sends NO server-side limit for `to_list(n)`; a `.limit(n)` turns the
// sort into a top-k whose tie order at the cap differs (verified live). Read
// the sorted cursor and stop after n documents, exactly like Motor.
async function motorToList<T>(cursor: FindCursor<T>, n: number): Promise<T[]> {
  const out: T[] = [];
  try {
    if (n <= 0) {
      await cursor.hasNext(); // to_list(0) still issues the find, returns []
      return out;
    }
    for await (const doc of cursor) {
      out.push(doc);
      if (out.length >= n) break;
    }
  } finally {
    await cursor.close();
  }
  return out;
}

/**
 * TRUKVIA · Phase-3 · Gate-7e · Supplier vehicles list read-only shadow.
 *
 *   GET /api/suppliers/{sid}/vehicles
 *
 * Faithful shadow of:
 *   backend/routers/suppliers.py::supplier_vehicles (lines 275–291)
 *
 * STRICTLY READ-ONLY. Class-C — Python handler executes ONLY
 *   1. `db.suppliers.find_one({id, user_id, company_id}, {_id:0, name:1})`
 *   2. `db.vehicles.find(q, {_id:0, user_id:0}).sort("vehicle_number", 1).to_list(500)`
 *
 * Zero writer hook / audit / backfill / recompute / FinTxn / approvals /
 * counters / idempotency / hidden cross-collection writes.
 *
 * ── GATE-7e BINDINGS ────────────────────────────────────────────────
 *
 *   1. NEW PARITY AXES vs Gates 7a–7d:
 *      * PATH parameter `{sid}` (first Gate-7 route with a path param).
 *      * Cross-collection precheck (`suppliers.findOne` → `vehicles.find`).
 *      * 404 branch (`"Supplier not found"`) after successful auth.
 *      * Dynamic anchored case-insensitive `$regex` built from the
 *        stored `supplier.name` — UNESCAPED, per authoritative Python.
 *      * `$or` between exact `supplier_id` equality and the regex.
 *      * Ascending sort on `vehicle_number`.
 *      * Hard cap 500 rows.
 *      * Bare-array response (NOT wrapped).
 *      * No 422 branch (no query parameters).
 *      * No `is_active` predicate on the supplier precheck — inactive
 *        suppliers still return their vehicles.
 *
 *   2. AUTH PRECEDENCE — 401 fires BEFORE the supplier precheck / 404.
 *
 *   3. REGEX RULE — supplier.name is passed VERBATIM to Mongo:
 *      * No JS RegExp construction in the route handler.
 *      * No `.replace()` / escape helper.
 *      * `^` and `$` anchors preserved.
 *      * `$options: "i"` preserved.
 *      * MongoDB server-side evaluation ⇒ byte parity with Python.
 *
 * Writer boundary (Python-authoritative, out of scope):
 *   POST /suppliers · PUT /suppliers/{sid} · DELETE /suppliers/{sid}
 *   POST /suppliers/{sid}/reactivate · POST /vehicles · PUT /vehicles/{vid}
 *   PATCH /vehicles/{vid}/status · DELETE /vehicles/{vid} · bulk-import
 */

interface SupplierDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  name?: string;
  [k: string]: unknown;
}

interface VehicleDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  vehicle_type?: string;
  vehicle_number?: string;
  supplier_id?: string;
  supplier_name?: string;
  [k: string]: unknown;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerSupplierVehiclesListReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7e (read-only)
  app.get<{ Params: { sid: string } }>(
    '/api/suppliers/:sid/vehicles',
    async (
      req: FastifyRequest<{ Params: { sid: string } }>,
      reply: FastifyReply,
    ) => {
      // 1. Auth FIRST — locked 401 literals precede supplier lookup / 404.
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

      // 3. Path parameter.
      const sid = req.params.sid;

      // 4. Supplier precheck — mirrors Python line 279 exactly.
      //    Composite {id, user_id, company_id} scope ⇒ missing / wrong-user /
      //    wrong-company all yield the same 404. No `is_active` predicate.
      const sup = await db
        .collection<SupplierDoc>('suppliers')
        .findOne(
          { id: sid, user_id: userId, company_id: cid },
          { projection: { _id: 0, name: 1 } },
        );
      if (!sup) {
        reply.code(404);
        return { detail: 'Supplier not found' };
      }

      // 5. Vehicle query — mirrors Python lines 283-289 exactly.
      //    supplier.name passes VERBATIM into the Mongo `$regex` predicate;
      //    no escaping / normalization / JS RegExp construction. The same
      //    server-side Mongo engine that Python calls evaluates the pattern.
      const supplierName = String((sup as { name?: unknown }).name ?? '');
      const filter: Record<string, unknown> = {
        user_id: userId,
        company_id: cid,
        vehicle_type: 'supplier',
        $or: [
          { supplier_id: sid },
          {
            supplier_name: {
              $regex: `^${supplierName}$`,
              $options: 'i',
            },
          },
        ],
      };

      // 6. Read with EXACT projection / sort / cap.
      const rows = await motorToList(
        db
        .collection<VehicleDoc>('vehicles')
        .find(filter as Filter<VehicleDoc>, {
          projection: { _id: 0, user_id: 0 },
        })
        .sort([['vehicle_number', 1]]),
        500,
      );

      // Bare-array response — matches Python exactly.
      return rows;
    },
  );
}
