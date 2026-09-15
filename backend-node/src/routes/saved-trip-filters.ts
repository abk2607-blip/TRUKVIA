import type { FastifyInstance } from 'fastify';
import type { Db } from 'mongodb';
import { z } from 'zod';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';
import { newId } from '../id.js';

/**
 * TRUKVIA · Phase-3 · Gate-4 · first non-financial WRITER.
 *   POST /api/saved-trip-filters
 * Faithful shadow of
 *   backend/routers/saved_filters.py::create_saved_filter
 *
 * Behaviour parity (verbatim):
 *   - Zod boundary mirrors Pydantic SavedFilterCreate:
 *       name: string, 1..64 (Zod max_length); missing/wrong-type => 422
 *   - After strip: empty => 400 {"detail":"name required"}
 *   - name silently truncated to 64
 *   - filter_state omitted => {}; opaque passthrough (no deep validation)
 *   - Client-supplied id/user_id/company_id/created_at/_id ignored
 *   - id = newId("sf") (^sf[a-f0-9]{16}$)
 *   - created_at = new Date().toISOString() in UTC
 *   - Insert into saved_trip_filters, return inserted doc, drop _id
 *   - Duplicates allowed, always insert (never upsert)
 *   - No writes to companies/audit_logs/fin_txn/payment_corrections/user_sessions
 */

const BodySchema = z.object({
  name: z.string().min(1).max(64),
  filter_state: z.record(z.unknown()).optional(),
});

interface SavedTripFilterDoc {
  id: string;
  user_id: string;
  company_id: string;
  name: string;
  filter_state: Record<string, unknown>;
  created_at: string;
}

export async function registerSavedTripFiltersRoute(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-4
  app.post('/api/saved-trip-filters', async (req, reply) => {
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
      return { detail: 'name required' };
    }

    const cid = await activeCompanyId(req, userId, db);

    const doc: SavedTripFilterDoc = {
      id: newId('sf'),
      user_id: userId,
      company_id: cid,
      name: name.slice(0, 64),
      filter_state: parsed.data.filter_state ?? {},
      created_at: new Date().toISOString(),
    };

    await db.collection<SavedTripFilterDoc>('saved_trip_filters').insertOne({ ...doc });
    return doc;
  });
}
