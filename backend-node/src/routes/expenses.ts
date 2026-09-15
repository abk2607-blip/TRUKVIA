import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { z } from 'zod';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6i · Expense read-only shadows.
 *
 *   GET /api/expenses
 *   GET /api/expenses/{eid}
 *
 * Faithful shadows of:
 *   backend/routers/expenses.py::list_expenses (lines 145-198)
 *   backend/routers/expenses.py::get_expense   (lines 229-239)
 *
 * STRICTLY READ-ONLY. Class-C — neither handler invokes any writer
 * hook, audit call, backfill, recompute, effective-balance
 * projection, FinTxn emission, or paired-linkage refresh in Python.
 *
 * Preserved semantics:
 *   * `include_cancelled` / `include_reversed` — FastAPI/Pydantic v2
 *     boolean-string parsing (verbatim tokens); invalid string → 422.
 *   * `is_deleted` / `is_reversed` guards use MongoDB `$ne: true`.
 *     ONLY literal boolean `true` is excluded — `false`, missing key,
 *     `null`, `0`, `""` and every other non-`true` value remain
 *     visible. No JavaScript truthiness folding.
 *   * `source_type` — comma-separated: split, trim, drop empty parts.
 *     One remaining part → equality; multiple → `$in`; zero → filter
 *     omitted. No case folding, no deduplication.
 *   * `date_from` / `date_to` — raw incoming strings passed straight
 *     into the Mongo filter (stored dates are ISO strings, compared
 *     lexicographically). NO `new Date()` coercion.
 *   * Projection strips `_id` and `user_id`; every other stored field
 *     passes through unmodified.
 *   * List sort `date` DESC; cap 20,000 rows.
 *   * Detail miss → 404 `{ "detail": "Expense not found" }`.
 */

// ── FastAPI/Pydantic v2 boolean-string coercion (verbatim tokens) ─────
// Duplicated INLINE per Gate-6i implementation directive — the locked
// Gate-6g file MUST NOT be modified.
const BOOL_TRUE = new Set(['1', 't', 'true', 'on', 'yes']);
const BOOL_FALSE = new Set(['0', 'f', 'false', 'off', 'n', 'no']);

function coerceFastapiBool(v: unknown): boolean | 'invalid' {
  if (typeof v !== 'string') return 'invalid';
  const s = v.trim().toLowerCase();
  if (BOOL_TRUE.has(s)) return true;
  if (BOOL_FALSE.has(s)) return false;
  return 'invalid';
}

function boolField() {
  return z
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
    });
}

const ListQuerySchema = z.object({
  trip_id: z.string().optional(),
  vehicle_id: z.string().optional(),
  repair_event_id: z.string().optional(),
  vendor_bill_id: z.string().optional(),
  mechanic_work_order_id: z.string().optional(),
  party_type: z.string().optional(),
  party_id: z.string().optional(),
  category: z.string().optional(),
  source_type: z.string().optional(),
  date_from: z.string().optional(),
  date_to: z.string().optional(),
  include_reversed: boolField(),
  include_cancelled: boolField(),
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
export async function registerExpensesReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // ── GET /api/expenses ───────────────────────────────────────────────
  // migration-allowlisted: phase-3-gate-6i (read-only)
  app.get('/api/expenses', async (req: FastifyRequest, reply: FastifyReply) => {
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

    // 4. Default guards — literal boolean `true` exclusion only.
    if (!q.include_cancelled) filter['is_deleted'] = { $ne: true };
    if (!q.include_reversed) filter['is_reversed'] = { $ne: true };

    // 5. Truthy-only equality filters (Python `if x:` — empty strings skipped).
    if (q.trip_id) filter['trip_id'] = q.trip_id;
    if (q.vehicle_id) filter['vehicle_id'] = q.vehicle_id;
    if (q.repair_event_id) filter['repair_event_id'] = q.repair_event_id;
    if (q.vendor_bill_id) filter['vendor_bill_id'] = q.vendor_bill_id;
    if (q.mechanic_work_order_id) filter['mechanic_work_order_id'] = q.mechanic_work_order_id;
    if (q.party_type) filter['party_type'] = q.party_type;
    if (q.party_id) filter['party_id'] = q.party_id;
    if (q.category) filter['category'] = q.category;

    // 6. source_type — CSV split/trim/drop-empty (verbatim Python semantics).
    if (q.source_type) {
      const parts = q.source_type
        .split(',')
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
      if (parts.length > 1) filter['source_type'] = { $in: parts };
      else if (parts.length === 1) filter['source_type'] = parts[0];
      // parts.length === 0 → filter omitted.
    }

    // 7. Date bounds — raw strings, lexicographic Mongo comparison.
    if (q.date_from || q.date_to) {
      const d: Record<string, string> = {};
      if (q.date_from) d['$gte'] = q.date_from;
      if (q.date_to) d['$lte'] = q.date_to;
      filter['date'] = d;
    }

    // 8. Read with projection + sort DESC + cap.
    const rows = await db
      .collection('expenses')
      .find(filter as Filter<Record<string, unknown>>, {
        projection: { _id: 0, user_id: 0 },
      })
      .sort([['date', -1]])
      .limit(20000)
      .toArray();

    return rows;
  });

  // ── GET /api/expenses/{eid} ─────────────────────────────────────────
  // migration-allowlisted: phase-3-gate-6i (read-only)
  app.get<{ Params: { eid: string } }>(
    '/api/expenses/:eid',
    async (
      req: FastifyRequest<{ Params: { eid: string } }>,
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

      // 3. Composite user_id + company_id scoped read with soft-delete guard.
      const doc = await db.collection('expenses').findOne(
        {
          id: req.params.eid,
          user_id: userId,
          company_id: activeCid,
          is_deleted: { $ne: true },
        },
        { projection: { _id: 0, user_id: 0 } },
      );

      if (!doc) {
        reply.code(404);
        return { detail: 'Expense not found' };
      }
      return doc;
    },
  );
}
