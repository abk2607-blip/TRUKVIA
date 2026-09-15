import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { z } from 'zod';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6j · Vendor master read-only shadow.
 *
 *   GET /api/vendors
 *   GET /api/vendors/{vid}
 *
 * Faithful shadows of:
 *   backend/routers/vendors.py::list_vendors (lines 43-62)
 *   backend/routers/vendors.py::get_vendor   (lines 84-93)
 *
 * STRICTLY READ-ONLY. Class-C — neither handler invokes any writer
 * hook, audit call, backfill, recompute, effective-balance,
 * FinTxn emission, or paired-linkage refresh in Python.
 *
 * Preserved semantics:
 *   * `active_only` — FastAPI/Pydantic v2 boolean-string parsing
 *     (verbatim tokens). Missing → false. Invalid → 422. When true,
 *     ONLY literal boolean `is_active: true` matches (equality, not
 *     truthiness — mirrors Python `if active_only:` gating an
 *     equality query).
 *   * `q` — truthy incoming string builds an `$or` regex filter
 *     across `name`, `mobile`, `contact_person` with
 *     `$options: 'i'`. Raw string passed to Mongo (server-side
 *     regex evaluation). NO JavaScript RegExp construction, NO
 *     escaping, NO trimming or normalization.
 *   * List projection strips `_id` and `user_id`; sort `name` ASC;
 *     cap 20,000 rows.
 *   * Detail: composite `{ id, user_id, company_id }` scoping only —
 *     NO `is_deleted` / NO `is_active` filter. Inactive vendors are
 *     still returned. Miss → 404 `{ "detail": "Vendor not found" }`.
 */

// ── FastAPI/Pydantic v2 boolean-string coercion (verbatim tokens) ─────
// Duplicated INLINE per Gate-6j implementation directive — locked
// Gate-6g / Gate-6i files MUST NOT be modified.
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
export async function registerVendorsReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // ── GET /api/vendors ───────────────────────────────────────────────
  // migration-allowlisted: phase-3-gate-6j (read-only)
  app.get('/api/vendors', async (req: FastifyRequest, reply: FastifyReply) => {
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
    //    Only apply when truthy (matches Python `if q:`).
    if (q.q) {
      filter['$or'] = [
        { name: { $regex: q.q, $options: 'i' } },
        { mobile: { $regex: q.q, $options: 'i' } },
        { contact_person: { $regex: q.q, $options: 'i' } },
      ];
    }

    // 6. Read with projection + sort ASC + cap.
    const rows = await db
      .collection('vendors')
      .find(filter as Filter<Record<string, unknown>>, {
        projection: { _id: 0, user_id: 0 },
      })
      .sort([['name', 1]])
      .limit(20000)
      .toArray();

    return rows;
  });

  // ── GET /api/vendors/{vid} ─────────────────────────────────────────
  // migration-allowlisted: phase-3-gate-6j (read-only)
  app.get<{ Params: { vid: string } }>(
    '/api/vendors/:vid',
    async (
      req: FastifyRequest<{ Params: { vid: string } }>,
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
      //    NO is_deleted / NO is_active guard — inactive vendors visible.
      const doc = await db.collection('vendors').findOne(
        {
          id: req.params.vid,
          user_id: userId,
          company_id: activeCid,
        },
        { projection: { _id: 0, user_id: 0 } },
      );

      if (!doc) {
        reply.code(404);
        return { detail: 'Vendor not found' };
      }
      return doc;
    },
  );
}
