import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6p · Driver payment corrections read-only shadow.
 *
 *   GET /api/driver-payments/{pid}/corrections
 *
 * Faithful shadow of:
 *   backend/routers/driver_payments.py::list_driver_payment_corrections
 *   (lines 284–292)
 *
 * STRICTLY READ-ONLY. Class-C — the Python handler is a pure
 * `db.driver_payment_corrections.find().sort()` async cursor iteration
 * with no writer hook, no audit call, no `hook_after_source_write`,
 * no `_backfill_to_default`, no `_recompute_invoice`, no
 * `_apply_effective_balance`, no FinTxn emission, no policy_changes
 * / approvals / idempotency / counters touch.
 *
 * ── GATE-6p CONTRACT DIFFERENCES vs GATE-6n/6o (BIND PRECISELY) ──
 *   1. Collection: `driver_payment_corrections` (DEDICATED — NOT the
 *      shared `payment_corrections` collection used by 6n/6o).
 *   2. Filter has 3 keys: `{ user_id, company_id, payment_id }` — NO
 *      `payment_type` key (cross-payment-type isolation is intrinsic
 *      via the dedicated collection).
 *   3. Projection is `{ _id: 0 }` ONLY. `user_id` MUST REMAIN PRESENT
 *      in every returned row (Python does NOT strip `user_id`).
 *   4. NO artificial `.limit(N)` cap. Python uses
 *      `[d async for d in cur]` (no `.to_list(1000)`). Node MUST NOT
 *      add `.limit(1000)`.
 *
 * Preserved semantics (verbatim from Python):
 *   * No query params. No body. No path-param validation.
 *   * Unknown pid → 200 [] (no payment-existence lookup on GET).
 *
 * Gate-7 (Maker-Checker) writer boundary:
 *   POST /api/driver-payments/{pid}/correct-amount (Python
 *   `apply_amount_reversal_new` → `hook_after_source_write` +
 *   ledger reversal + audit + `driver_payment_corrections.insert_one`)
 *   is out of scope for Gate 6p and remains Python-authoritative.
 */

interface DriverCorrectionDoc {
  id?: string;
  user_id?: string; // MUST REMAIN in response (projection only strips _id).
  company_id?: string;
  payment_id?: string;
  correction_index?: number;
  kind?: string;
  correction_reason?: string;
  before?: unknown;
  after?: unknown;
  diff?: unknown;
  linked_reversal_id?: string;
  linked_new_id?: string;
  force_reconciled_override?: boolean;
  corrected_by?: string;
  corrected_at?: string;
  [k: string]: unknown;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerDriverPaymentsCorrectionsReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6p (read-only)
  app.get<{ Params: { pid: string } }>(
    '/api/driver-payments/:pid/corrections',
    async (
      req: FastifyRequest<{ Params: { pid: string } }>,
      reply: FastifyReply,
    ) => {
      // 1. Auth → 401 with exact locked literals.
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

      // 2. Active company (X-Company-Id owned override + default fallback).
      const cid = await activeCompanyId(req, userId, db);
      const { pid } = req.params;

      // 3. Read with exact filter / projection / sort. NO explicit limit —
      //    Python uses `[d async for d in cur]` with no `.to_list(N)` cap.
      const rows = await db
        .collection<DriverCorrectionDoc>('driver_payment_corrections')
        .find(
          {
            user_id: userId,
            company_id: cid,
            payment_id: pid,
          } as Filter<DriverCorrectionDoc>,
          { projection: { _id: 0 } },
        )
        .sort([['correction_index', 1]])
        .toArray();

      return rows;
    },
  );
}
