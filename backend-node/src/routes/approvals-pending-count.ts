import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7f · Approvals pending-count read-only shadow.
 *
 *   GET /api/approvals/summary/pending
 *
 * Faithful shadow of:
 *   backend/routers/approvals.py::api_pending_count (lines 49–56)
 *
 * STRICTLY READ-ONLY. Class-C — Python handler executes ONLY
 *   db.approvals.count_documents({
 *     user_id, company_id, status: "PENDING_APPROVAL"
 *   })
 *
 * Zero writer hook / audit / backfill / recompute / FinTxn / approvals
 * mutation / counters / idempotency / cross-collection reads.
 *
 * ── GATE-7f BINDINGS ────────────────────────────────────────────────
 *
 *   1. NEW PARITY AXES vs Gates 6a–7e:
 *      * First read against the `approvals` collection.
 *      * First use of `countDocuments` operator in the Node shadow.
 *      * Fixed-shape response `{ count: <integer> }`.
 *      * No query parameters, no 422/400/404 branch.
 *
 *   2. AUTH PRECEDENCE — 401 fires BEFORE any approvals DB access.
 *
 *   3. FILTER — exactly `{ user_id, company_id, status: "PENDING_APPROVAL" }`.
 *      No `is_deleted`, no `is_active`, no additional statuses.
 *
 * Approvals writer boundary (Python-authoritative, out of scope):
 *   POST /api/approvals               (submit / auto-execute)
 *   POST /api/approvals/{aid}/approve (checker approve → execute)
 *   POST /api/approvals/{aid}/reject
 *   POST /api/approvals/{aid}/withdraw
 *   POST /api/approvals/{aid}/resubmit
 */

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerApprovalsPendingCountRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7f (read-only)
  app.get(
    '/api/approvals/summary/pending',
    async (req: FastifyRequest, reply: FastifyReply) => {
      // 1. Auth FIRST — locked 401 literals precede any approvals access.
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

      // 3. Count — mirrors Python line 52-55 exactly.
      const count = await db.collection('approvals').countDocuments({
        user_id: userId,
        company_id: cid,
        status: 'PENDING_APPROVAL',
      });

      // 4. Fixed-shape response.
      return { count };
    },
  );
}
