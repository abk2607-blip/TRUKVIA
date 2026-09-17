import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6s · Audit-log read-only shadow.
 *
 *   GET /api/audit-logs
 *     ?module=&action=&entity_id=&start=&end=&limit=
 *
 * Faithful shadow of:
 *   backend/routers/audit_router.py::list_audit_logs  (lines 29–49)
 *
 * STRICTLY READ-ONLY. Class-C — the Python handler executes ONLY
 * `db.audit_logs.find().sort().to_list(min(int(limit), 500))`.
 * Zero writer hook, zero audit call, zero backfill, zero recompute,
 * zero FinTxn emission, zero approvals / policy / counters /
 * idempotency touch, zero unrelated collection reads.
 *
 * ── GATE-6s NEW DIMENSIONS (BIND PRECISELY) ─────────────────────────
 *
 *   1. NO `activeCompanyId()` INVOCATION — this endpoint is strictly
 *      user-scoped. The Python route does NOT call `_active_company_id`,
 *      so Node MUST NOT call `activeCompanyId()` either (invocation
 *      parity in the negative direction — same tenant-resolver DB
 *      touch surface = none).
 *
 *   2. TRUTHY-GATED OPTIONAL FILTERS — `module`, `action`, `entity_id`
 *      are added to the DB filter ONLY when truthy. Empty string is
 *      omitted from the filter (mirrors Python `if module: q["module"] = module`).
 *
 *   3. `end + "T23:59:59"` LITERAL SUFFIX — the range upper bound is a
 *      Python string concatenation with no timezone, no ISO validation.
 *      Node MUST reproduce the exact suffix.
 *
 *   4. `limit` FASTAPI COERCION — declared `int = 200`. Non-integer
 *      values (`"abc"`) trigger FastAPI/Pydantic-v2 422 `int_parsing`
 *      before the handler runs. Node reproduces the exact body.
 *
 *   5. HARD 500 CAP — `min(int(limit), 500)`. Callers cannot exceed
 *      500 rows regardless of request.
 *
 * Gate-7 writer boundary (out of scope for Gate 6s):
 *   Audit logs are produced by writer routes across the codebase
 *   (create/update/delete on business collections). Read parity here
 *   does NOT include any write behavior.
 */

interface AuditLogDoc {
  id?: string;
  user_id?: string;
  module?: string;
  action?: string;
  entity_id?: string;
  timestamp?: string;
  [k: string]: unknown;
}

// FastAPI/Pydantic-v2 detail entry for `int_parsing` on `?limit=abc`.
// Observed live against the running Python backend at implementation
// time (see harness.py — `observed_py_422_int_parsing` audit field).
// Bind precisely; Pydantic-minor version changes require a one-line
// refresh here.
function pydanticIntParsingLimit(rawInput: string): Record<string, unknown> {
  return {
    type: 'int_parsing',
    loc: ['query', 'limit'],
    msg: 'Input should be a valid integer, unable to parse string as an integer',
    input: rawInput,
    url: 'https://errors.pydantic.dev/2.13/v/int_parsing',
  };
}

// Parse an optional string query param — return `undefined` if
// missing, otherwise the trimmed value as-is. Preserves Python's
// truthiness semantics (empty string is falsy → omitted from filter).
function firstStr(v: unknown): string | undefined {
  if (typeof v === 'string') return v;
  if (Array.isArray(v)) {
    const first = v[0];
    return typeof first === 'string' ? first : undefined;
  }
  return undefined;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerAuditLogsReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6s (read-only)
  app.get(
    '/api/audit-logs',
    async (req: FastifyRequest, reply: FastifyReply) => {
      // 1. Auth FIRST — locked 401 literals short-circuit 422.
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

      // NOTE: No activeCompanyId() invocation — Python does not call
      // _active_company_id on this route (audit_router.py:30–48).

      // 2. Query params.
      const q = (req.query ?? {}) as Record<string, unknown>;
      const module_ = firstStr(q['module']);
      const action = firstStr(q['action']);
      const entityId = firstStr(q['entity_id']);
      const start = firstStr(q['start']);
      const end = firstStr(q['end']);
      const limitRaw = firstStr(q['limit']);

      // 3. limit coercion → FastAPI 422 shape on non-integer input.
      let limit = 200;
      if (limitRaw !== undefined) {
        // Python `int(...)` accepts optional leading sign + digits, and
        // strips surrounding whitespace. FastAPI's Pydantic-v2 int
        // coercer is stricter (int_parsing) — replicate that here.
        const trimmed = limitRaw.trim();
        if (!/^[+-]?\d+$/.test(trimmed)) {
          reply.code(422);
          return { detail: [pydanticIntParsingLimit(limitRaw)] };
        }
        limit = parseInt(trimmed, 10);
      }
      // 4. Hard 500 cap. Negative / zero pass through to `.limit()`
      //    unchanged to mirror Python behaviour verbatim.
      limit = Math.min(limit, 500);

      // 5. Build filter — always `user_id`; optional truthy-gated keys.
      const filter: Record<string, unknown> = { user_id: userId };
      if (module_) filter['module'] = module_;
      if (action) filter['action'] = action;
      if (entityId) filter['entity_id'] = entityId;

      // 6. Range filter — `start or end` in Python (either truthy).
      if (start || end) {
        const rng: Record<string, string> = {};
        if (start) rng['$gte'] = start;
        if (end) rng['$lte'] = end + 'T23:59:59'; // exact Python literal
        filter['timestamp'] = rng;
      }

      // 7. Read with EXACT projection / sort / cap.
      const rows = await db
        .collection<AuditLogDoc>('audit_logs')
        .find(filter as Filter<AuditLogDoc>, { projection: { _id: 0, user_id: 0 } })
        .sort([['timestamp', -1]])
        .limit(limit)
        .toArray();

      return rows;
    },
  );
}
