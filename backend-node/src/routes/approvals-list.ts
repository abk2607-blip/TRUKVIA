import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7g · Approvals list read-only shadow.
 *
 *   GET /api/approvals
 *
 * Faithful shadow of:
 *   backend/routers/approvals.py::api_list_approvals (L33-46)
 *   → services_approvals.list_approvals            (L527-541)
 *
 * STRICTLY READ-ONLY. Class-C — Python executes ONLY
 *   db.approvals.find(q, {_id:0}).sort("created_at", -1).limit(min(500, limit))
 *
 * Zero writer hook / audit / backfill / recompute / FinTxn / approvals
 * mutation / counters / idempotency / cross-collection reads.
 *
 * ── GATE-7g BINDINGS ────────────────────────────────────────────────
 *
 *   1. FastAPI 0.110.1 executes `Depends(get_current_user)` INSIDE
 *      `solve_dependencies` (fastapi/dependencies/utils.py L549) BEFORE
 *      `request_params_to_args` reaches query validation (L610).
 *      A raised `HTTPException(401)` in `get_current_user` short-circuits
 *      the coroutine, so query validation never runs. Therefore:
 *        · unauthenticated + invalid query  → 401 (auth wins)
 *        · authenticated  + invalid query  → 422 (Pydantic envelope)
 *        · authenticated  + valid   query  → 200
 *      AUTH PRECEDES QUERY VALIDATION.
 *
 *   2. Pydantic v2 (2.13.4) 422 envelopes reproduced verbatim for:
 *      * bool_parsing        (include_all)
 *      * int_parsing         (limit)
 *      * greater_than_equal  (limit < 1)  — ctx: {ge: 1}
 *      * less_than_equal     (limit > 500) — ctx: {le: 500}
 *
 *   3. Projection `{_id: 0}` — strips only `_id`; **user_id preserved**.
 *
 *   4. include_all semantics (verified against source):
 *      * status truthy → q.status = status (include_all IGNORED)
 *      * status falsy + include_all=false → q.status = {$in: [
 *          "PENDING_APPROVAL", "REJECTED", "WITHDRAWN" ]}
 *      * status falsy + include_all=true → no status predicate
 *
 * Approvals writer boundary (Python-authoritative, out of scope):
 *   POST /api/approvals · POST /api/approvals/{aid}/{approve|reject|withdraw|resubmit}
 */

// ── Pydantic 2.13.4 bool-parsing mimic ─────────────────────────────
//    Accepted spellings: true/True/TRUE, false/False/FALSE, 1, 0,
//    yes/Yes/YES, no/No/NO, on/On/ON, off/Off/OFF.
const TRUE_TOKENS = new Set(['true', '1', 'yes', 'on']);
const FALSE_TOKENS = new Set(['false', '0', 'no', 'off']);

function parseBoolStrict(raw: string): { ok: true; value: boolean } | { ok: false; raw: string } {
  const key = raw.toLowerCase();
  if (TRUE_TOKENS.has(key)) return { ok: true, value: true };
  if (FALSE_TOKENS.has(key)) return { ok: true, value: false };
  return { ok: false, raw };
}

// ── Pydantic 2.13.4 int-parsing mimic ──────────────────────────────
//    Accepts leading '+' and surrounding whitespace (verified via
//    FastAPI TestClient probe in pre-flight). Rejects blank, non-ints,
//    floats (e.g. "1.5"), embedded whitespace, and arbitrary text.
function parseIntStrict(raw: string): { ok: true; value: number } | { ok: false; raw: string } {
  const trimmed = raw.trim();
  if (trimmed === '') return { ok: false, raw };
  if (!/^[+-]?\d+$/.test(trimmed)) return { ok: false, raw };
  const n = Number(trimmed);
  if (!Number.isInteger(n)) return { ok: false, raw };
  return { ok: true, value: n };
}

function boolParsingErr(raw: string): Record<string, unknown> {
  return {
    type: 'bool_parsing',
    loc: ['query', 'include_all'],
    msg: 'Input should be a valid boolean, unable to interpret input',
    input: raw,
    url: 'https://errors.pydantic.dev/2.13/v/bool_parsing',
  };
}

function intParsingErr(raw: string): Record<string, unknown> {
  return {
    type: 'int_parsing',
    loc: ['query', 'limit'],
    msg: 'Input should be a valid integer, unable to parse string as an integer',
    input: raw,
    url: 'https://errors.pydantic.dev/2.13/v/int_parsing',
  };
}

function greaterThanEqualErr(raw: string): Record<string, unknown> {
  return {
    type: 'greater_than_equal',
    loc: ['query', 'limit'],
    msg: 'Input should be greater than or equal to 1',
    input: raw,
    ctx: { ge: 1 },
    url: 'https://errors.pydantic.dev/2.13/v/greater_than_equal',
  };
}

function lessThanEqualErr(raw: string): Record<string, unknown> {
  return {
    type: 'less_than_equal',
    loc: ['query', 'limit'],
    msg: 'Input should be less than or equal to 500',
    input: raw,
    ctx: { le: 500 },
    url: 'https://errors.pydantic.dev/2.13/v/less_than_equal',
  };
}

interface ApprovalDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  status?: string;
  entity_kind?: string;
  created_at?: string;
  [k: string]: unknown;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerApprovalsListRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7g (read-only)
  app.get('/api/approvals', async (req: FastifyRequest, reply: FastifyReply) => {
    const q = (req.query ?? {}) as Record<string, unknown>;

    // 1. Auth FIRST — reproduces FastAPI 0.110.1 `solve_dependencies`
    //    ordering: `Depends(get_current_user)` runs before Pydantic
    //    query validation. A 401 short-circuits the coroutine so query
    //    validation never runs.
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

    // 2. Query validation — Pydantic v2 semantics, declaration-order
    //    errors (include_all before limit) to match FastAPI's error array.
    const errors: Record<string, unknown>[] = [];

    let includeAll = false;
    if (typeof q['include_all'] !== 'undefined') {
      const raw = String(q['include_all']);
      const p = parseBoolStrict(raw);
      if (!p.ok) errors.push(boolParsingErr(raw));
      else includeAll = p.value;
    }

    let limit = 200;
    if (typeof q['limit'] !== 'undefined') {
      const raw = String(q['limit']);
      const p = parseIntStrict(raw);
      if (!p.ok) {
        errors.push(intParsingErr(raw));
      } else if (p.value < 1) {
        errors.push(greaterThanEqualErr(raw));
      } else if (p.value > 500) {
        errors.push(lessThanEqualErr(raw));
      } else {
        limit = p.value;
      }
    }

    if (errors.length > 0) {
      reply.code(422);
      return { detail: errors };
    }

    // 3. Active-company resolution (locked helper).
    const cid = await activeCompanyId(req, userId, db);

    // 4. Build filter conditionally — mirror Python exactly.
    const statusRaw = typeof q['status'] === 'undefined' ? '' : String(q['status']);
    const entityKindRaw = typeof q['entity_kind'] === 'undefined' ? '' : String(q['entity_kind']);
    const filter: Record<string, unknown> = { user_id: userId, company_id: cid };
    if (statusRaw) {
      filter['status'] = statusRaw;
    } else if (!includeAll) {
      filter['status'] = { $in: ['PENDING_APPROVAL', 'REJECTED', 'WITHDRAWN'] };
    }
    if (entityKindRaw) filter['entity_kind'] = entityKindRaw;

    // 5. Read — projection strips _id only (user_id preserved), sort
    //    created_at DESC, cap min(500, limit) — technically redundant
    //    given le=500 but preserves the Python contract literally.
    const rows = await db
      .collection<ApprovalDoc>('approvals')
      .find(filter as Filter<ApprovalDoc>, { projection: { _id: 0 } })
      .sort([['created_at', -1]])
      .limit(Math.min(500, limit))
      .toArray();

    // Bare-array response — matches Python exactly.
    return rows;
  });
}
