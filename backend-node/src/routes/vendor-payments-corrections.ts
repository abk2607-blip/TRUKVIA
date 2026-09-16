import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6o · Vendor payment corrections read-only shadow.
 *
 *   GET /api/vendor-payments/{pid}/corrections
 *
 * Faithful shadow of:
 *   backend/routers/vendor_ledger.py::get_vendor_payment_corrections
 *   (lines 127–132)
 * delegating in Python to:
 *   backend/services_payment_corrections.py::list_corrections
 *   (lines 328–333)
 *
 * STRICTLY READ-ONLY. Class-C — the delegated `list_corrections`
 * helper executes ONLY `db.payment_corrections.find().sort().to_list(1000)`
 * with no writer hook, no audit call, no `hook_after_source_write`,
 * no `_backfill_to_default`, no `_recompute_invoice`, no
 * `_apply_effective_balance`, no FinTxn emission, no policy_changes
 * / approvals / idempotency / counters touch.
 *
 * Preserved semantics (all verbatim from Python):
 *   * Filter EXACTLY:
 *       { user_id: uid, company_id: cid,
 *         payment_type: "vendor", payment_id: pid }
 *   * Projection: { _id: 0, user_id: 0 }
 *   * Sort: `correction_index` ASC
 *   * Limit: 1000 (Python `.to_list(1000)`).
 *   * No query params. No body. No path-param validation.
 *   * Unknown pid → 200 [] (no payment-existence lookup on GET).
 *
 * Cross-payment-type isolation is intrinsic: supplier / mechanic /
 * driver correction rows sharing the same `payment_id` are excluded
 * because `payment_type` is fixed to the string `"vendor"` at the
 * filter level.
 *
 * ── EXPLICIT DIVERGENCE FROM LOCKED GATE-2 ──
 *   `backend-node/src/routes/supplier-payments-corrections.ts`
 *   (Gate-2 locked) uses unbounded `.toArray()`. Python's
 *   `list_corrections` caps at 1000 via `.to_list(1000)`; this Gate-6o
 *   file MUST honour that cap. Gate-2 file remains locked and
 *   untouched — its pre-existing property is a documented Gate-2
 *   divergence and will be revisited by a future auth/limits gate.
 *
 * Gate-7 (Maker-Checker) writer boundary:
 *   POST /api/vendor-payments/{pid}/correct-amount (Python
 *   `apply_amount_reversal_new` → `hook_after_source_write` +
 *   ledger reversal + audit) is out of scope for Gate 6o and remains
 *   Python-authoritative.
 */

interface CorrectionDoc {
  id?: string;
  company_id?: string;
  payment_type?: string;
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
export async function registerVendorPaymentsCorrectionsReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6o (read-only)
  app.get<{ Params: { pid: string } }>(
    '/api/vendor-payments/:pid/corrections',
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

      // 3. Read with exact filter / projection / sort / cap.
      const rows = await db
        .collection<CorrectionDoc>('payment_corrections')
        .find(
          {
            user_id: userId,
            company_id: cid,
            payment_type: 'vendor',
            payment_id: pid,
          } as Filter<CorrectionDoc>,
          { projection: { _id: 0, user_id: 0 } },
        )
        .sort([['correction_index', 1]])
        .limit(1000)
        .toArray();

      return rows;
    },
  );
}
