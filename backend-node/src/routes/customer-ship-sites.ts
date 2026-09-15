import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db } from 'mongodb';
import { z } from 'zod';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6g · Customer Ship-Sites read-only shadow.
 *
 *   GET /api/customers/{cid}/ship-sites
 *
 * Faithful shadow of `backend/routers/customers.py::list_ship_sites`
 * (lines 313–321) + helper `_get_customer_or_404` (303–310).
 *
 * STRICTLY READ-ONLY. Node performs ZERO writes on ANY business
 * collection. The Python handler is itself pure-read (no
 * `_backfill_to_default`, no `_recompute_invoice`, no
 * `_apply_effective_balance`, no `_log_audit`, no writer hooks).
 *
 * DELIBERATE contract preservation:
 *   * X-Company-Id IS consulted here via `activeCompanyId` — unlike
 *     Gate 6e which was `user_id`-only. Customer master-data is
 *     tenant-scoped.
 *   * Ship-sites are returned AS-STORED. NO GSTIN normalization, NO
 *     state derivation, NO resolver invocation. Contrast with Gate 6e
 *     which cleans on render — Gate 6g feeds the edit UI (raw form).
 *   * `active_only=true` filters ONLY the literal boolean `False`.
 *     Missing / null / true / 0 / "" / non-bool truthy values all
 *     remain visible (`s.is_active !== false`).
 */

// ── FastAPI/Pydantic v2 boolean-string coercion (verbatim tokens) ─────
// Truthy: 1, t, true, on, yes  (case-insensitive)
// Falsy : 0, f, false, off, n, no  (case-insensitive)
// Any other value → 422 (parity with Pydantic ValidationError).
const BOOL_TRUE = new Set(['1', 't', 'true', 'on', 'yes']);
const BOOL_FALSE = new Set(['0', 'f', 'false', 'off', 'n', 'no']);

function coerceFastapiBool(v: unknown): boolean | 'invalid' {
  if (typeof v !== 'string') return 'invalid';
  const s = v.trim().toLowerCase();
  if (BOOL_TRUE.has(s)) return true;
  if (BOOL_FALSE.has(s)) return false;
  return 'invalid';
}

// ── Query schema ──────────────────────────────────────────────────────
// Python default is `active_only: bool = False`. Missing → false.
// Present but unparseable → 422 (matches FastAPI param-parse behaviour,
// which fires BEFORE dependency resolution).
const QuerySchema = z.object({
  active_only: z
    .string()
    .optional()
    .transform((v, ctx) => {
      if (v === undefined) return false;
      const b = coerceFastapiBool(v);
      if (b === 'invalid') {
        ctx.addIssue({
          code: 'custom',
          message: 'value is not a valid boolean',
        });
        return z.NEVER;
      }
      return b;
    }),
});

function zodDetail(err: z.ZodError): { detail: unknown } {
  return {
    detail: err.issues.map((i) => ({
      loc: ['query', ...i.path.map(String)],
      msg: i.message,
      type: i.code,
    })),
  };
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerCustomerShipSitesRoute(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6g (read-only)
  app.get<{ Params: { cid: string } }>(
    '/api/customers/:cid/ship-sites',
    async (req: FastifyRequest<{ Params: { cid: string } }>, reply: FastifyReply) => {
      // 1. Query validation → 422 BEFORE auth (FastAPI param-parse parity).
      const parsed = QuerySchema.safeParse(req.query);
      if (!parsed.success) {
        reply.code(422);
        return zodDetail(parsed.error);
      }

      // 2. Auth → 401.
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

      // 3. Active company (X-Company-Id override + default fallback).
      const activeCid = await activeCompanyId(req, userId, db);

      // 4. Customer lookup — user_id + company_id scoped.
      const customerId = req.params.cid;
      const doc = (await db.collection('customers').findOne(
        { id: customerId, user_id: userId, company_id: activeCid },
        { projection: { _id: 0, user_id: 0 } },
      )) as Record<string, unknown> | null;

      if (!doc) {
        reply.code(404);
        return { detail: 'Customer not found' };
      }

      // 5. Raw sites — Python `doc.get("ship_sites") or []`.
      //    Missing / null / non-array → [].
      const raw = doc['ship_sites'];
      let sites: Record<string, unknown>[] = Array.isArray(raw)
        ? (raw as Record<string, unknown>[])
        : [];

      // 6. active_only filter — ONLY literal boolean `false` is excluded.
      //    Python: `s.get("is_active") is not False`.
      //    Node   : `s.is_active !== false` (strict inequality on bool).
      if (parsed.data.active_only) {
        sites = sites.filter((s) => s['is_active'] !== false);
      }

      // 7. Response — items returned AS-STORED (no normalization).
      return { items: sites, total: sites.length };
    },
  );
}
