import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7d · PolicyChanges list read-only shadow.
 *
 *   GET /api/policy-changes
 *
 * Faithful shadow of:
 *   backend/routers/policy_changes.py::list_policy_change_events (lines 484–494)
 *
 * STRICTLY READ-ONLY. Class-C — Python handler executes ONLY
 * `db.policy_change_events.find(q, {_id:0})
 *      .sort("created_at",-1).to_list(max(1, min(200, int(limit))))`.
 * Zero writer hook / audit / backfill / recompute / FinTxn / approvals /
 * counters / idempotency / cross-collection reads on the GET path.
 *
 * ── GATE-7d BINDINGS ────────────────────────────────────────────────
 *
 *   1. NEW PARITY AXES vs Gates 7a–7c:
 *      * `int_parsing` 422 envelope (Pydantic v2 2.13.4 byte-exact).
 *      * Server-side clamp `max(1, min(200, int(limit)))`.
 *      * Wrapped response `{ items, total }` — NOT a bare array.
 *      * Projection retains `user_id` (only `_id` stripped).
 *      * Sort key `created_at` DESC (new field).
 *
 *   2. Pydantic v2 int semantics (byte-verified 2.13.4):
 *      * Accepts optional surrounding whitespace, optional `+`/`-` sign,
 *        digits only.
 *      * REJECTS `""`, `"1.5"`, `"abc"`, `"null"`, `"None"` → 422.
 *      * Omitted → default 50.
 *
 *   3. AUTH PRECEDENCE — 401 fires BEFORE query 422.
 *
 *   4. NO 404 branch — no customer-existence lookup.
 *
 * Writer boundary (Python-authoritative, out of scope for Gate 7d):
 *   POST /api/policy-changes/apply* — Policy Change apply flows.
 *   POST /api/policy-changes/{event_id}/revert — mandatory reason, 400/
 *     404/409 semantics, per-trip snapshot restore, audit crumb.
 */

interface PolicyChangeEventDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  customer_id?: string;
  created_at?: string;
  [k: string]: unknown;
}

// ── Pydantic-v2 int coercion (route-local; byte-verified 2.13.4) ─────
const PYDANTIC_INT_URL = 'https://errors.pydantic.dev/2.13/v/int_parsing';
const PYDANTIC_INT_MSG = 'Input should be a valid integer, unable to parse string as an integer';
// Matches Pydantic v2 accepted int strings: optional whitespace, optional
// leading sign, one or more digits, optional trailing whitespace.
const INT_RE = /^\s*[+-]?\d+\s*$/;

function coerceInt(raw: string): number | null {
  if (!INT_RE.test(raw)) return null;
  const n = parseInt(raw.trim(), 10);
  if (!Number.isFinite(n)) return null;
  return n;
}

function pydanticIntParsing422(input: string): Record<string, unknown> {
  return {
    detail: [
      {
        type: 'int_parsing',
        loc: ['query', 'limit'],
        msg: PYDANTIC_INT_MSG,
        input,
        url: PYDANTIC_INT_URL,
      },
    ],
  };
}

function qParam(query: Record<string, unknown>, key: string): string | undefined {
  const v = query[key];
  if (v === undefined || v === null) return undefined;
  if (Array.isArray(v)) return v.length ? String(v[v.length - 1]) : undefined;
  return String(v);
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerPolicyChangesListReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7d (read-only)
  app.get(
    '/api/policy-changes',
    async (req: FastifyRequest, reply: FastifyReply) => {
      // 1. Auth FIRST — locked 401 literals. Auth precedes query 422.
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

      // 2. Parse query string.
      const query = (req.query ?? {}) as Record<string, unknown>;
      const customerId = qParam(query, 'customer_id');
      const limitRaw = qParam(query, 'limit');

      // 3. int coercion — Pydantic v2 semantics. Default 50.
      let parsedLimit = 50;
      if (limitRaw !== undefined) {
        const n = coerceInt(limitRaw);
        if (n === null) {
          reply.code(422);
          return pydanticIntParsing422(limitRaw);
        }
        parsedLimit = n;
      }
      // Server-side clamp AFTER Pydantic accepts.
      const effectiveLimit = Math.max(1, Math.min(200, parsedLimit));

      // 4. Active-company resolution.
      const cid = await activeCompanyId(req, userId, db);

      // 5. Filter assembly — mirrors Python line-for-line.
      const filter: Record<string, unknown> = {
        user_id: userId,
        company_id: cid,
      };
      if (customerId) {
        filter['customer_id'] = customerId;
      }

      // 6. Read with EXACT projection / sort / clamped cap.
      const rows = await db
        .collection<PolicyChangeEventDoc>('policy_change_events')
        .find(filter as Filter<PolicyChangeEventDoc>, {
          projection: { _id: 0 },
        })
        .sort([['created_at', -1]])
        .limit(effectiveLimit)
        .toArray();

      // Wrapped response — matches Python exactly.
      return { items: rows, total: rows.length };
    },
  );
}
