import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db } from 'mongodb';
import { z } from 'zod';
import { authenticate } from '../auth.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6f · Credit / Debit Note read-only shadows.
 *
 *   GET /api/credit-notes
 *   GET /api/credit-notes/{nid}
 *   GET /api/debit-notes
 *   GET /api/debit-notes/{nid}
 *
 * Faithful shadows of `backend/routers/notes.py`:
 *   list_credit_notes  (336–354)
 *   get_credit_note    (357–363)
 *   list_debit_notes   (588–602)
 *   get_debit_note     (605–612)
 *
 * STRICTLY READ-ONLY. Node performs ZERO writes on ANY business
 * collection. All four Python handlers are pure reads (no
 * `_recompute_invoice`, no `_apply_effective_balance`, no `_log_audit`,
 * no `hook_after_source_write`) — nothing to skip / no Class-B stance
 * required.
 *
 * DELIBERATE CROSS-KIND QUIRK preserved verbatim:
 *   GET /api/credit-notes/{nid} does NOT filter kind="credit".
 *   A debit-kind document with a matching id + user_id WILL be returned.
 *   Do NOT "fix" this.
 *
 * FEATURE FLAG:
 *   `ENABLE_CDN != "1"` → 404 {"detail":"Not Found"} (note capital F).
 *   Read on every request from `process.env` — not cached at module load.
 *   Distinct from the note-missing 404 {"detail":"Not found"} literal.
 *
 * X-Company-Id NOT consulted. Node must not invent company filtering.
 */

// ── Feature flag ──────────────────────────────────────────────────────
// Runtime read — matches Python `os.environ.get("ENABLE_CDN") == "1"`.
function isCdnEnabled(): boolean {
  return process.env['ENABLE_CDN'] === '1';
}

// ── Query schema (shared by both list routes) ─────────────────────────
// Python: `Query(default=100, le=500)`; non-int / >500 → 422 BEFORE auth
// (FastAPI parity — parameter validation fires ahead of dependencies).
const ListQuerySchema = z.object({
  customer_id: z.string().optional(),
  invoice_id: z.string().optional(),
  status: z.string().optional(),
  limit: z.coerce.number().int().max(500).default(100),
});

type ListQuery = z.infer<typeof ListQuerySchema>;

// ── Zod 422 detail (matches Gate 6c/6d convention) ────────────────────
function zodDetail(err: z.ZodError): { detail: unknown } {
  return {
    detail: err.issues.map((i) => ({
      loc: ['query', ...i.path.map(String)],
      msg: i.message,
      type: i.code,
    })),
  };
}

// ── Shared list handler (kind = 'credit' | 'debit') ───────────────────
async function handleList(
  req: FastifyRequest,
  reply: FastifyReply,
  db: Db,
  kind: 'credit' | 'debit',
): Promise<unknown> {
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

  // 3. Feature flag (mirrors `_require_flag()` — first line of handler
  //    body in Python, runs AFTER auth resolution).
  if (!isCdnEnabled()) {
    reply.code(404);
    return { detail: 'Not Found' };
  }

  const { customer_id, invoice_id, status, limit }: ListQuery = parsed.data;

  // 4. Build filter (append only when truthy — Python `if x:` skips '' / None).
  const q: Record<string, unknown> = { user_id: userId, kind };
  if (customer_id) q['customer_id'] = customer_id;
  if (invoice_id) q['invoice_id'] = invoice_id;
  if (status) q['status'] = status;

  // 5. Pure read.
  const docs = await db
    .collection('credit_debit_notes')
    .find(q, { projection: { _id: 0, user_id: 0 } })
    .sort([['note_date', -1]])
    .limit(limit)
    .toArray();
  return docs;
}

// ── Shared detail handler ────────────────────────────────────────────
async function handleDetail(
  req: FastifyRequest,
  reply: FastifyReply,
  db: Db,
  nid: string,
  kind: 'credit' | 'debit' | null, // null → no kind clause (credit quirk)
): Promise<unknown> {
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

  // 2. Feature flag.
  if (!isCdnEnabled()) {
    reply.code(404);
    return { detail: 'Not Found' };
  }

  // 3. Filter — NO kind clause when `kind === null` (credit-detail quirk).
  const filter: Record<string, unknown> = { id: nid, user_id: userId };
  if (kind !== null) filter['kind'] = kind;

  const doc = await db
    .collection('credit_debit_notes')
    .findOne(filter, { projection: { _id: 0, user_id: 0 } });

  if (!doc) {
    reply.code(404);
    return { detail: 'Not found' };
  }
  return doc;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerCreditDebitNoteRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6f (read-only)
  app.get('/api/credit-notes', async (req, reply) =>
    handleList(req, reply, db, 'credit'),
  );

  // migration-allowlisted: phase-3-gate-6f (read-only)
  //
  // DELIBERATE cross-kind quirk — Python `get_credit_note` filter is
  // {id, user_id} WITHOUT a kind clause. Preserved verbatim by passing
  // `null` as the kind argument.
  app.get<{ Params: { nid: string } }>(
    '/api/credit-notes/:nid',
    async (req, reply) => handleDetail(req, reply, db, req.params.nid, null),
  );

  // migration-allowlisted: phase-3-gate-6f (read-only)
  app.get('/api/debit-notes', async (req, reply) =>
    handleList(req, reply, db, 'debit'),
  );

  // migration-allowlisted: phase-3-gate-6f (read-only)
  //
  // Symmetric with credit-detail EXCEPT: Python explicitly filters
  // kind="debit". Preserved verbatim.
  app.get<{ Params: { nid: string } }>(
    '/api/debit-notes/:nid',
    async (req, reply) => handleDetail(req, reply, db, req.params.nid, 'debit'),
  );
}
