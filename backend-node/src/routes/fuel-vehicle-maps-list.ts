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
 * TRUKVIA · Phase-3 · Gate-7h · Fuel vehicle maps list read-only shadow.
 *
 *   GET /api/fuel/vehicle-maps
 *
 * Faithful shadow of:
 *   backend/routers/fuel_import.py::list_fuel_vehicle_maps (L37-47)
 *
 * STRICTLY READ-ONLY. Class-C — Python executes ONLY
 *   db.fuel_vehicle_maps.find(q, {_id:0, user_id:0})
 *     .sort("source_vehicle_ref", 1).to_list(5000)
 *
 * ── CONTRACT ────────────────────────────────────────────────────────
 *   * Auth via locked authenticate() (AUTH BEFORE QUERY VALIDATION per
 *     Gate 7g finding — but this route has NO query-validation surface
 *     because `source: Optional[str] = None` accepts any string).
 *   * Tenant via locked activeCompanyId() (owned override, unowned
 *     fallback, no-header default).
 *   * Base filter: { user_id, company_id }
 *   * Source predicate ONLY added when raw source is EXACTLY "iocl"
 *     or "bpcl" (case-sensitive, per Python `if source in ("iocl","bpcl")`).
 *     Every other source value (missing, "", "IOCL", "iOcl", "bp",
 *     "other", arbitrary text) is silently dropped — NO 422, NO 400.
 *   * Projection strips `_id` AND `user_id`.
 *   * Sort `source_vehicle_ref` ASC.
 *   * Cap `.to_list(5000)`.
 *   * Response: bare JSON array. Empty → 200 [].
 *
 * Zero writer hook / audit / backfill / recompute / FinTxn / counters /
 * idempotency writes on the GET path. Fuel writers (POST /fuel-import/*,
 * POST /fuel-manual, POST /fuel/vehicle-maps, DELETE /fuel/vehicle-maps/{fvm_id})
 * remain Python-authoritative and OUT OF SCOPE.
 */

interface FuelVehicleMapDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  source?: string;
  source_vehicle_ref?: string;
  vehicle_id?: string;
  vehicle_number?: string;
  [k: string]: unknown;
}

export async function registerFuelVehicleMapsListRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7h (read-only)
  app.get('/api/fuel/vehicle-maps', async (req: FastifyRequest, reply: FastifyReply) => {
    // 1. Auth (401 short-circuit — matches FastAPI solve_dependencies).
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

    // 2. Tenant resolution (locked helper — owned override / unowned
    //    fallback / no-header default).
    const cid = await activeCompanyId(req, userId, db);

    // 3. Raw source query — case-sensitive membership check identical
    //    to Python's `if source in ("iocl", "bpcl")`. Every other value
    //    (missing / "" / "IOCL" / "bp" / arbitrary) silently drops the
    //    predicate; NO 422, NO 400.
    const q = (req.query ?? {}) as Record<string, unknown>;
    const rawSource =
      typeof q['source'] === 'undefined' ? undefined : String(q['source']);

    const filter: Record<string, unknown> = { user_id: userId, company_id: cid };
    if (rawSource === 'iocl' || rawSource === 'bpcl') {
      filter['source'] = rawSource;
    }

    // 4. Read — projection strips _id AND user_id, sort ASC, cap 5000.
    const rows = await motorToList(
      db
      .collection<FuelVehicleMapDoc>('fuel_vehicle_maps')
      .find(filter as Filter<FuelVehicleMapDoc>, { projection: { _id: 0, user_id: 0 } })
      .sort([['source_vehicle_ref', 1]]),
      5000,
    );

    // Bare-array response — matches Python exactly.
    return rows;
  });
}
