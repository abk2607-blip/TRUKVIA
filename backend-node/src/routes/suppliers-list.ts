import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { z } from 'zod';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6k · Supplier master list read-only shadow.
 *
 *   GET /api/suppliers
 *
 * Faithful shadow of `backend/routers/suppliers.py::list_suppliers`
 * (lines 45-67). Completes the Gate-6h-deferred pair — the detail
 * endpoint `GET /api/suppliers/{sid}` remains owned by Gate 6h's
 * `company-supplier-reads.ts` (LOCKED, MUST NOT be touched).
 *
 * STRICTLY READ-ONLY. Class-C — no writer hook, audit call,
 * backfill, recompute, effective-balance, FinTxn, or paired-linkage
 * refresh in Python.
 *
 * Preserved semantics:
 *   * `active_only` — FastAPI/Pydantic v2 boolean-string parsing
 *     (verbatim tokens). Missing → false. Invalid → 422. True →
 *     `is_active: true` equality (only literal boolean).
 *   * `q` — truthy string builds `$or` regex over `name`, `mobile`,
 *     `contact_person` with `$options: 'i'`. Raw string passthrough
 *     (server-side Mongo evaluation). NO JS RegExp construction,
 *     NO escaping, NO normalization.
 *   * Projection `{_id: 0, user_id: 0}`; sort `name` ASC; cap 20 000.
 */

// ── FastAPI/Pydantic v2 boolean-string coercion (verbatim tokens) ─────
// Duplicated INLINE per Gate-6k implementation directive — locked
// Gate-6g / Gate-6i / Gate-6j files MUST NOT be modified.
const BOOL_TRUE = new Set(['1', 't', 'true', 'on', 'yes']);
const BOOL_FALSE = new Set(['0', 'f', 'false', 'off', 'n', 'no']);

function coerceFastapiBool(v: unknown): boolean | 'invalid' {
  if (typeof v !== 'string') return 'invalid';
  const s = v.trim().toLowerCase();
  if (BOOL_TRUE.has(s)) return true;
  if (BOOL_FALSE.has(s)) return false;
  return 'invalid';
}

const ListQuerySchema = z.object({
  q: z.string().optional(),
  active_only: z
    .string()
    .optional()
    .transform((v, ctx) => {
      if (v === undefined) return false;
      const b = coerceFastapiBool(v);
      if (b === 'invalid') {
        ctx.addIssue({ code: 'custom', message: 'value is not a valid boolean' });
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
export async function registerSuppliersListReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // ── GET /api/suppliers ─────────────────────────────────────────────
  // migration-allowlisted: phase-3-gate-6k (read-only)
  // Note: Detail `GET /api/suppliers/:sid` is owned by Gate 6h
  // (`company-supplier-reads.ts`). Fastify path-matching resolves the
  // parameterised variant separately — no collision.
  app.get('/api/suppliers', async (req: FastifyRequest, reply: FastifyReply) => {
    // 1. Query validation → 422 BEFORE auth (FastAPI param-parse parity).
    const parsed = ListQuerySchema.safeParse(req.query);
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

    // 3. Active company (X-Company-Id owned override + default fallback).
    const activeCid = await activeCompanyId(req, userId, db);

    const q = parsed.data;
    const filter: Record<string, unknown> = {
      user_id: userId,
      company_id: activeCid,
    };

    // 4. active_only — literal boolean equality when true.
    if (q.active_only) filter['is_active'] = true;

    // 5. q — raw regex passthrough (server-side Mongo evaluation).
    if (q.q) {
      filter['$or'] = [
        { name: { $regex: q.q, $options: 'i' } },
        { mobile: { $regex: q.q, $options: 'i' } },
        { contact_person: { $regex: q.q, $options: 'i' } },
      ];
    }

    // 6. Read with projection + sort ASC + cap.
    const rows = await db
      .collection('suppliers')
      .find(filter as Filter<Record<string, unknown>>, {
        projection: { _id: 0, user_id: 0 },
      })
      .sort([['name', 1]])
      .limit(20000)
      .toArray();

    return rows;
  });
}
