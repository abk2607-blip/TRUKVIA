import type { FastifyInstance } from 'fastify';
import type { Db } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6a · first Trip read-only shadow.
 *   GET /api/trips/{tid}
 * Faithful shadow of
 *   backend/routers/trips.py::get_trip
 *
 * STRICTLY READ-ONLY (Slice-6a directive):
 *   - Node performs ZERO writes to trips, expenses, driver_ledger,
 *     fin_txn, audit_logs, counters, user_sessions, or any other
 *     collection.
 *   - Python's `_lazy_migrate_supplier_entries` post-read `update_one`
 *     write-back is intentionally NOT ported (see Gate-6a Class-B
 *     observation). For fresh (Iter91+) trips already carrying the
 *     `supplier_diesel_entries` / `supplier_advance_entries` arrays,
 *     the response is byte-identical to Python. Legacy pre-Iter91
 *     supplier trips are out-of-scope for this parity slice.
 *   - Response projection mirrors Python `{_id:0, user_id:0}`.
 *   - No `hook_after_source_write`, no `_log_audit`.
 *
 * 404 body literal (Invariant P):
 *   {"detail":"Trip not found"}
 */
export async function registerTripsReadRoute(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6a (read-only)
  app.get<{ Params: { tid: string } }>('/api/trips/:tid', async (req, reply) => {
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
    const tid = req.params.tid;

    const doc = await db.collection('trips').findOne(
      { id: tid, user_id: userId, company_id: cid },
      { projection: { _id: 0, user_id: 0 } },
    );

    if (!doc) {
      reply.code(404);
      return { detail: 'Trip not found' };
    }

    return doc;
  });
}
