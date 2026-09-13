import type { FastifyInstance } from 'fastify';
import type { Db } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA Node · Phase-3 · Gate-2 · first read-only route.
 *
 *   GET /api/supplier-payments/:pid/corrections
 *
 * Faithful shadow of
 *   backend/routers/supplier_ledger.py::list_supplier_payment_corrections
 * delegating (in Python) to
 *   backend/services_payment_corrections.py::list_corrections
 *
 * Behaviour reproduced VERBATIM from Python:
 *
 *   1. Requires authentication (session_token cookie OR `Authorization: Bearer …`).
 *      Exact 401 detail strings match `error-string-parity.md`.
 *   2. Resolves the active company via `X-Company-Id` override / user default / first.
 *   3. Queries `payment_corrections` filtered by
 *      { user_id, company_id, payment_type: "supplier", payment_id: pid }.
 *   4. Sorts ascending by `correction_index`.
 *   5. Projects OUT `_id` and `user_id`.
 *   6. Returns a JSON array (empty [] when no rows match — including when the
 *      supplier payment id does not exist, matches Python which does NOT call
 *      `_load_payment` on the list endpoint).
 *   7. Ownership / role: the GET endpoint intentionally does NOT invoke
 *      `_ensure_admin` in Python; any authenticated user of the tenant may
 *      view correction history. The two POST correction endpoints (NOT part
 *      of this gate) remain admin-only.
 *
 * READ-ONLY guarantee: this handler NEVER invokes insert/update/delete/replace
 * or bulk-write on any collection. Tests spy on the injected DB and assert
 * write-method call-count is zero.
 */

interface CorrectionDoc {
  id: string;
  company_id: string;
  payment_type: string;
  payment_id: string;
  correction_index: number;
  kind: string;
  correction_reason: string;
  before: unknown;
  after: unknown;
  diff: unknown;
  linked_reversal_id?: string;
  linked_new_id?: string;
  force_reconciled_override?: boolean;
  corrected_by?: string;
  corrected_at?: string;
}

export interface RouteDeps {
  db: Db;
}

export async function registerSupplierCorrectionsRoute(
  app: FastifyInstance,
  deps: RouteDeps,
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-2
  app.get<{ Params: { pid: string } }>(
    '/api/supplier-payments/:pid/corrections',
    async (req, reply) => {
      let userId: string;
      try {
        const user = await authenticate(req, db);
        userId = user.user_id;
      } catch (err) {
        if (err instanceof HttpError) {
          reply.code(err.status);
          return { detail: err.detail };
        }
        throw err;
      }

      const cid = await activeCompanyId(req, userId, db);
      const { pid } = req.params;

      const rows = await db
        .collection<CorrectionDoc>('payment_corrections')
        .find(
          { user_id: userId, company_id: cid, payment_type: 'supplier', payment_id: pid },
          { projection: { _id: 0, user_id: 0 } },
        )
        .sort({ correction_index: 1 })
        .toArray();

      return rows;
    },
  );
}
