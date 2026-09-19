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
 * TRUKVIA · Phase-3 · Gate-6q · Trip template read-only shadow.
 *
 *   GET /api/templates
 *   GET /api/templates/{tid}
 *
 * Faithful shadow of:
 *   backend/routers/templates.py::list_templates (lines 16–23)
 *   backend/routers/templates.py::get_template   (lines 39–45)
 *
 * STRICTLY READ-ONLY. Class-C — Python handlers are pure
 * `find().sort().to_list()` / `find_one()` chains with no writer hook,
 * no audit call, no `hook_after_source_write`, no backfill, no
 * recompute, no FinTxn emission, no counters / idempotency /
 * approvals / policy_changes touch, and no unrelated collection reads.
 *
 * ── GATE-6q NEW DIMENSIONS (BIND PRECISELY) ─────────────────────────
 *   1. COMPANY-SHARED SCOPE — filters carry ONLY `company_id`
 *      (LIST) or `{id, company_id}` (DETAIL). NO `user_id`. Any
 *      authenticated user whose active company resolves to `cid` sees
 *      the same rows regardless of who authored them.
 *   2. DETAIL 404 LITERAL — missing row OR wrong-company row raises
 *      HTTP 404 with exact detail literal `"Template not found"`
 *      (Python `raise HTTPException(status_code=404, detail="Template
 *      not found")`). Node MUST emit
 *      `reply.code(404); return { detail: 'Template not found' }`.
 *   3. LIST BEHAVIOR — additionally filters `is_active: true`; sorts
 *      `name` ASC; explicit `.to_list(500)` cap. Empty result → `200
 *      []`. No 404 path on LIST.
 *   4. DETAIL BEHAVIOR — no `is_active` in filter (retired/inactive
 *      templates remain individually addressable by id within their
 *      company).
 *
 * Preserved semantics (verbatim from Python):
 *   * No query params. No body. `tid` accepted as-is with no
 *     validation / coercion.
 *   * Both routes strip `_id` and `user_id` from the projection.
 *
 * Gate-7 writer boundary (out of scope for Gate 6q):
 *   POST /api/templates, PUT /api/templates/{tid},
 *   DELETE /api/templates/{tid} remain Python-authoritative.
 */

interface TemplateDoc {
  id?: string;
  name?: string;
  user_id?: string;
  company_id?: string;
  is_active?: boolean;
  [k: string]: unknown;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerTemplatesReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // ── GET /api/templates ────────────────────────────────────────────
  // migration-allowlisted: phase-3-gate-6q (read-only)
  app.get(
    '/api/templates',
    async (req: FastifyRequest, reply: FastifyReply) => {
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

      // 3. Read with EXACT filter/projection/sort/cap.
      //    NOTE: filter carries ONLY company_id + is_active — NO user_id.
      const rows = await motorToList(
        db
        .collection<TemplateDoc>('templates')
        .find(
          { company_id: cid, is_active: true } as Filter<TemplateDoc>,
          { projection: { _id: 0, user_id: 0 } },
        )
        .sort([['name', 1]]),
        500,
      );

      return rows;
    },
  );

  // ── GET /api/templates/:tid ───────────────────────────────────────
  // migration-allowlisted: phase-3-gate-6q (read-only)
  app.get<{ Params: { tid: string } }>(
    '/api/templates/:tid',
    async (
      req: FastifyRequest<{ Params: { tid: string } }>,
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
      const { tid } = req.params;

      // 3. Read with EXACT filter/projection. NO user_id key. No limit.
      const doc = await db
        .collection<TemplateDoc>('templates')
        .findOne(
          { id: tid, company_id: cid } as Filter<TemplateDoc>,
          { projection: { _id: 0, user_id: 0 } },
        );

      // 4. Missing / wrong-company → 404 with EXACT Python literal.
      if (!doc) {
        reply.code(404);
        return { detail: 'Template not found' };
      }

      return doc;
    },
  );
}
