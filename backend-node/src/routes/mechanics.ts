import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { z } from 'zod';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6l · Mechanic master read-only shadows.
 *
 *   GET /api/mechanics
 *   GET /api/mechanics/{mid}
 *
 * Faithful shadows of:
 *   backend/routers/mechanics.py::list_mechanics (lines 28-47)
 *   backend/routers/mechanics.py::get_mechanic   (lines 69-78)
 *
 * STRICTLY READ-ONLY. Class-C — neither handler invokes any writer
 * hook, audit call, backfill, recompute, effective-balance, FinTxn,
 * or paired-linkage refresh in Python.
 *
 * Preserved semantics:
 *   * `active_only` — FastAPI/Pydantic v2 boolean-string parsing
 *     (verbatim tokens). Missing → false. Invalid → 422. True →
 *     `is_active: true` equality (only literal boolean).
 *   * `q` — truthy string builds `$or` regex over `name`, `mobile`,
 *     `skill` with `$options: 'i'`. Raw string passthrough (server-
 *     side Mongo evaluation). NO JS RegExp construction, NO
 *     escaping, NO normalization.
 *     NOTE: the third field is `skill` — DIFFERENT from Gate-6j
 *     (`vendors`/`contact_person`) and Gate-6k (`suppliers-list`/
 *     `contact_person`). This mirrors Python exactly.
 *   * List projection `{_id: 0, user_id: 0}`; sort `name` ASC; cap 20 000.
 *   * Detail: composite `{ id, user_id, company_id }` scoping only —
 *     NO `is_deleted` / NO `is_active` filter. Inactive mechanics
 *     ARE returned. Miss → 404 `{ "detail": "Mechanic not found" }`.
 */

// ── FastAPI/Pydantic v2 boolean-string coercion (verbatim tokens) ─────
// Duplicated INLINE per Gate-6l implementation directive — locked
// Gate-6g / 6i / 6j / 6k files MUST NOT be modified.
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
export async function registerMechanicsReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // ── GET /api/mechanics ─────────────────────────────────────────────
  // migration-allowlisted: phase-3-gate-6l (read-only)
  app.get('/api/mechanics', async (req: FastifyRequest, reply: FastifyReply) => {
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

    // 5. q — raw regex passthrough over name / mobile / SKILL.
    if (q.q) {
      filter['$or'] = [
        { name: { $regex: q.q, $options: 'i' } },
        { mobile: { $regex: q.q, $options: 'i' } },
        { skill: { $regex: q.q, $options: 'i' } },
      ];
    }

    // 6. Read with projection + sort ASC + cap.
    const rows = await db
      .collection('mechanics')
      .find(filter as Filter<Record<string, unknown>>, {
        projection: { _id: 0, user_id: 0 },
      })
      .sort([['name', 1]])
      .limit(20000)
      .toArray();

    return rows;
  });

  // ── GET /api/mechanics/{mid} ───────────────────────────────────────
  // migration-allowlisted: phase-3-gate-6l (read-only)
  app.get<{ Params: { mid: string } }>(
    '/api/mechanics/:mid',
    async (
      req: FastifyRequest<{ Params: { mid: string } }>,
      reply: FastifyReply,
    ) => {
      // 1. Auth → 401.
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

      // 2. Active company.
      const activeCid = await activeCompanyId(req, userId, db);

      // 3. Composite user_id + company_id scoped read.
      //    NO is_deleted / NO is_active guard — inactive mechanics visible.
      const doc = await db.collection('mechanics').findOne(
        {
          id: req.params.mid,
          user_id: userId,
          company_id: activeCid,
        },
        { projection: { _id: 0, user_id: 0 } },
      );

      if (!doc) {
        reply.code(404);
        return { detail: 'Mechanic not found' };
      }
      return doc;
    },
  );
}
