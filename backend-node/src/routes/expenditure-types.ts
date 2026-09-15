import type { FastifyInstance } from 'fastify';
import type { Db } from 'mongodb';
import { z } from 'zod';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';
import { newId } from '../id.js';

/**
 * TRUKVIA · Phase-3 · Gate-5 · second non-financial WRITER.
 *   POST /api/expenditure-types
 * Faithful shadow of
 *   backend/routers/expenditure_types.py::create_expenditure_type
 *
 * Path B.3-α: Bucket-B idempotency middleware is NOT extended for this route.
 * Natural dedup on (user_id, company_id, name-after-strip) provides the
 * required idempotent semantics — same behaviour as Python.
 *
 * Behaviour parity (verbatim from Python):
 *   - Zod boundary mirrors Pydantic ExpenditureType (Pydantic default
 *     extra='ignore'): unknown top-level fields are silently dropped.
 *   - name: string (required). Missing → 422 (Zod detail-array).
 *   - name.strip() empty → 400 {"detail":"Name is required"}.
 *   - Existence lookup on { user_id, company_id, name-after-strip } — if
 *     found, return the existing row (projection `{_id:0, user_id:0}`);
 *     NO second insert, NO 409.
 *   - New insert:
 *       id         : payload.id ?? newId("etype_")
 *       is_default : payload.is_default ?? false
 *       created_at : payload.created_at ?? new Date().toISOString()
 *       user_id    : authenticated user (server-stamped, always)
 *       company_id : activeCompanyId(...)          (server-stamped, always)
 *   - Response drops `_id` and `user_id`.
 *   - Zero writes outside `expenditure_types`.
 *   - GET-side _seed_defaults is NOT invoked on POST — fresh tenants stay
 *     empty until the first POST.
 */

const BodySchema = z.object({
  name: z.string(),
  id: z.string().optional(),
  is_default: z.boolean().optional(),
  created_at: z.string().optional(),
});

interface ExpenditureTypeDoc {
  id: string;
  name: string;
  is_default: boolean;
  created_at: string;
  user_id: string;
  company_id: string;
}

export async function registerExpenditureTypesRoute(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-5
  app.post('/api/expenditure-types', async (req, reply) => {
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

    const parsed = BodySchema.safeParse(req.body);
    if (!parsed.success) {
      reply.code(422);
      return {
        detail: parsed.error.issues.map((i) => ({
          loc: ['body', ...i.path.map(String)],
          msg: i.message,
          type: i.code,
        })),
      };
    }

    const name = parsed.data.name.trim();
    if (!name) {
      reply.code(400);
      return { detail: 'Name is required' };
    }

    const cid = await activeCompanyId(req, userId, db);

    const coll = db.collection<ExpenditureTypeDoc>('expenditure_types');
    const existing = await coll.findOne(
      { user_id: userId, company_id: cid, name },
      { projection: { _id: 0, user_id: 0 } },
    );
    if (existing) {
      // Return existing row unmodified (projection already stripped _id + user_id).
      return existing;
    }

    // New insert — model-order matches Python `payload.model_dump()` then
    // handler-appended (user_id, company_id). Response strips user_id and _id.
    const doc: ExpenditureTypeDoc = {
      id: parsed.data.id ?? newId('etype_'),
      name,
      is_default: parsed.data.is_default ?? false,
      created_at: parsed.data.created_at ?? new Date().toISOString(),
      user_id: userId,
      company_id: cid,
    };
    await coll.insertOne({ ...doc });

    // Response order: id, name, is_default, created_at, company_id (parity).
    return {
      id: doc.id,
      name: doc.name,
      is_default: doc.is_default,
      created_at: doc.created_at,
      company_id: doc.company_id,
    };
  });
}
