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
 * TRUKVIA · Phase-3 · Gate-7p · Driver salary-masters list read-only shadow.
 *
 *   GET /api/drivers/{did}/salary-masters
 *
 * Faithful shadow of:
 *   backend/routers/driver_ledger.py::_assert_driver        (L78-85)
 *   backend/routers/driver_ledger.py::list_salary_masters   (L91-99)
 *
 * STRICTLY READ-ONLY. Class-C — Python performs exactly two reads:
 *   1. drivers.find_one({id: did, user_id, company_id}, {_id: 0, user_id: 0})
 *   2. driver_salary_masters.find({user_id, company_id, driver_id: did}, {_id: 0})
 *        .sort([("effective_from", -1), ("version", -1)]).to_list(500)
 * Zero writer hook / audit / backfill / recompute / FinTxn.
 *
 * ── GATE-7p BINDINGS ────────────────────────────────────────────────
 *
 *   1. ORDER: auth → `_active_company_id` → driver pre-check → list.
 *
 *   2. DRIVER PRE-CHECK — Python `if not drv` on the projected driver.
 *      Missing / cross-user / cross-company → 404 {"detail":"Driver not found"}.
 *
 *   3. PROJECTION ASYMMETRY — salary masters use `{_id: 0}` ONLY:
 *      `user_id` REMAINS in every item. Do NOT strip.
 *
 *   4. SORT effective_from DESC, then version DESC. CAP 500.
 *      Response = wrapper `{ items }`.
 *
 *   5. EMPTY SEGMENT / ENCODED SLASH — Starlette routes on the decoded path
 *      with `[^/]+` params, so an empty `did` (`//`) or one containing "/"
 *      never reaches this handler in Python → 404
 *      {"detail":"Not Found"} before auth. (A decoded path landing on
 *      another Python route, e.g. `x%2Fledger` → DELETE-only
 *      /drivers/{did}/ledger/{eid} → 405, is a framework-routing gap tracked
 *      for the dedicated framework gate.)
 *
 * Writer boundary (Python-authoritative, out of scope):
 *   POST /api/drivers/{did}/salary-masters (closes prior open-ended master).
 */

interface DriverDoc {
  id?: string;
  company_id?: string;
  [k: string]: unknown;
}

interface SalaryMasterDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  driver_id?: string;
  effective_from?: string;
  version?: number;
  [k: string]: unknown;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerDriverSalaryMastersListRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7p (read-only)
  app.get('/api/drivers/:did/salary-masters', async (req: FastifyRequest, reply: FastifyReply) => {
    const did = (req.params as { did: string }).did;

    // 0. Starlette never routes an empty segment or a decoded "/" into a
    //    path param (`[^/]+`); Fastify does for `//` and `%2F`.
    if (did === '' || did.includes('/')) {
      reply.code(404);
      return { detail: 'Not Found' };
    }

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

    // 2. Active-company resolution (locked helper).
    const cid = await activeCompanyId(req, userId, db);

    // 3. Driver pre-check — exact filter / projection. `if not drv`.
    const drv = await db
      .collection<DriverDoc>('drivers')
      .findOne(
        { id: did, user_id: userId, company_id: cid } as Filter<DriverDoc>,
        { projection: { _id: 0, user_id: 0 } },
      );
    if (!drv || Object.keys(drv).length === 0) {
      reply.code(404);
      return { detail: 'Driver not found' };
    }

    // 4. Salary masters — projection strips ONLY _id; sort; cap 500.
    const items = await motorToList(
      db
      .collection<SalaryMasterDoc>('driver_salary_masters')
      .find(
        { user_id: userId, company_id: cid, driver_id: did } as Filter<SalaryMasterDoc>,
        { projection: { _id: 0 } },
      )
      .sort([['effective_from', -1], ['version', -1]]),
      500,
    );

    return { items };
  });
}
