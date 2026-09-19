import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter, FindCursor } from 'mongodb';
import { authenticate, type AuthUser } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

// ── Gate 9e · Motor `to_list(n)` (route-local) ────────────────────────
// Motor sends NO server-side limit for `to_list(n)`; a `.limit(n)` turns the
// sort into a top-k whose tie order at the cap differs (verified live). Read
// the sorted cursor and stop after n documents, exactly like Motor.
async function motorToList<T>(cursor: FindCursor<T>, n: number): Promise<T[]> {
  const out: T[] = [];
  try {
    if (n <= 0) {
      await cursor.hasNext(); // to_list(0) still issues the find, returns []
      return out;
    }
    for await (const doc of cursor) {
      out.push(doc);
      if (out.length >= n) break;
    }
  } finally {
    await cursor.close();
  }
  return out;
}

/**
 * TRUKVIA · Phase-3 · Gate-6r · Party bank account read-only shadow.
 *
 *   GET /api/party-bank-accounts?party_type=&party_id=
 *
 * Faithful shadow of:
 *   backend/routers/party_bank_accounts.py::list_party_bank_accounts
 *   (lines 43–59)
 *
 * STRICTLY READ-ONLY. Class-C — the Python handler executes ONLY
 * `db.party_bank_accounts.find().sort().to_list()` plus a per-row
 * `strip_full_number(...)` transform. Zero writer hook, zero audit
 * call, zero backfill, zero recompute, zero FinTxn emission, zero
 * approvals / policy_changes / counters / idempotency touch, zero
 * unrelated collection reads.
 *
 * ── GATE-6r NEW DIMENSIONS (BIND PRECISELY) ─────────────────────────
 *
 *   1. REQUIRED QUERY PARAMS — both `party_type` and `party_id` are
 *      required. Missing → HTTP 422 with FastAPI/Pydantic-v2 detail
 *      shape reproduced verbatim below.
 *
 *   2. TUPLE-MEMBERSHIP 400 — invalid `party_type` → HTTP 400 with
 *      EXACT literal (single-quoted tuple repr, mandatory space after
 *      each comma):
 *        "unsupported party_type. Allowed: ('supplier', 'vendor',
 *         'mechanic', 'driver', 'customer')"
 *
 *   3. AUTH-ORDER SHORT-CIRCUIT — authentication runs BEFORE query
 *      validation. Unauthenticated / invalid / expired requests
 *      surface the locked 401 literal without ever computing the
 *      422/400 shape. Confirmed against the running Python backend
 *      during Gate 6r Pre-flight.
 *
 *   4. NO `company_id` IN FILTER — the party master carries the
 *      tenant discriminator (via `party_type + party_id`), so the
 *      Python route deliberately omits `company_id` from the DB
 *      filter. `activeCompanyId()` is STILL invoked to preserve the
 *      exact tenant-resolver DB touch surface (Python binds `cid`
 *      but never consumes it).
 *
 *   5. GATE-6m MASKING SEMANTICS REUSED — the three inline helpers
 *      (`partyRoleCanViewFull`, `maskAccountNumber`, `stripFullNumber`)
 *      are duplicated verbatim from
 *      `services_bank_accounts.py::party_role_can_view_full /
 *       mask_account_number / strip_full_number` per the six-file
 *      ceiling. Locked Gate 6m file NOT modified.
 *
 * Gate-7 writer boundary (out of scope for Gate 6r):
 *   POST / PUT / set-primary / deactivate / replace / reveal
 *   (which writes an audit log) remain Python-authoritative.
 */

// ── PARTY_TYPES tuple parity (bind exact Python repr) ─────────────────
// Python: `PARTY_TYPES = ("supplier", "vendor", "mechanic", "driver", "customer")`
// f-string: `f"unsupported party_type. Allowed: {PARTY_TYPES}"` →
//   `unsupported party_type. Allowed: ('supplier', 'vendor', 'mechanic', 'driver', 'customer')`
// This string is BYTE-critical for parity — never mutate its formatting.
const PARTY_TYPES: readonly string[] = [
  'supplier', 'vendor', 'mechanic', 'driver', 'customer',
];
const PARTY_TYPES_REPR = "('supplier', 'vendor', 'mechanic', 'driver', 'customer')";

// ── Privileged-role predicate (verbatim Python semantics inline) ──────
// Python: role = (user.get("effective_role") or user.get("role") or "").lower()
// AuthUser already coalesces effective_role from session.effective_role ||
// session.role at Gate-2 auth.ts:87. The trailing `|| ''` mirrors Python's
// falsy-fallback to empty string when both are missing.
const PRIVILEGED_ROLES = new Set(['owner', 'accountant', 'admin']);

function partyRoleCanViewFull(user: AuthUser): boolean {
  const raw = user.effective_role || '';
  return PRIVILEGED_ROLES.has(raw.toLowerCase());
}

// ── mask_account_number (verbatim Python inline) ──────────────────────
function maskAccountNumber(acc: unknown): string {
  const s = (typeof acc === 'string' ? acc : '').trim();
  if (!s) return '';
  if (s.length <= 4) return 'X'.repeat(s.length);
  return 'X'.repeat(s.length - 4) + s.slice(-4);
}

// ── strip_full_number (verbatim Python inline) ────────────────────────
function stripFullNumber(
  doc: Record<string, unknown>,
  allowFull: boolean,
): Record<string, unknown> {
  if (!doc) return doc;
  const out: Record<string, unknown> = { ...doc };
  if (!allowFull) {
    const md = out['masked_display'];
    out['account_number'] = md ? md : maskAccountNumber(out['account_number']);
  }
  return out;
}

// ── Query helpers ─────────────────────────────────────────────────────
function firstStr(v: unknown): string | undefined {
  if (typeof v === 'string') return v;
  if (Array.isArray(v)) {
    const first = v[0];
    return typeof first === 'string' ? first : undefined;
  }
  return undefined;
}

// FastAPI/Pydantic-v2 "missing required query param" detail entry.
// Observed live against the running Python backend (Pre-flight parity
// harness — see /tmp/gate6r_parity_results.json.observed_py_422):
//   Python (Pydantic 2.13) emits:
//     { type: "missing", loc: ["query", <field>], msg: "Field required",
//       input: null, url: "https://errors.pydantic.dev/2.13/v/missing" }
// All five keys are reproduced verbatim below. The `url` value is
// Pydantic-minor-version-dependent; upgrading Pydantic requires a
// coordinated one-line refresh here.
function pydanticMissingEntry(field: 'party_type' | 'party_id'): Record<string, unknown> {
  return {
    type: 'missing',
    loc: ['query', field],
    msg: 'Field required',
    input: null,
    url: 'https://errors.pydantic.dev/2.13/v/missing',
  };
}

interface PartyBankAccountDoc {
  id?: string;
  user_id?: string;
  party_type?: string;
  party_id?: string;
  account_number?: string;
  masked_display?: string;
  created_at?: string;
  [k: string]: unknown;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerPartyBankAccountsReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6r (read-only)
  app.get(
    '/api/party-bank-accounts',
    async (req: FastifyRequest, reply: FastifyReply) => {
      // 1. Auth FIRST — 401 short-circuits 422/400 (auth-order parity).
      let user: AuthUser;
      try {
        user = await authenticate(req, db);
      } catch (err) {
        if (err instanceof HttpError) {
          reply.code(err.status);
          return { detail: err.detail };
        }
        throw err;
      }
      const uid = user.user_id;

      // 2. Active-company invocation-parity (cid is intentionally UNUSED
      //    downstream — mirrors Python which binds but does not consume).
      await activeCompanyId(req, uid, db);

      // 3. Required-param validation → FastAPI/Pydantic-v2 422.
      const q = (req.query ?? {}) as Record<string, unknown>;
      const partyType = firstStr(q['party_type']);
      const partyId = firstStr(q['party_id']);
      const missing: Record<string, unknown>[] = [];
      if (partyType === undefined) missing.push(pydanticMissingEntry('party_type'));
      if (partyId === undefined) missing.push(pydanticMissingEntry('party_id'));
      if (missing.length > 0) {
        reply.code(422);
        return { detail: missing };
      }

      // 4. Tuple-membership 400 (byte-exact Python literal).
      if (!PARTY_TYPES.includes(partyType!)) {
        reply.code(400);
        return { detail: `unsupported party_type. Allowed: ${PARTY_TYPES_REPR}` };
      }

      // 5. Compute masking predicate ONCE per request.
      const allowFull = partyRoleCanViewFull(user);

      // 6. Read with EXACT filter/projection/sort/cap. NO company_id.
      const rows = await motorToList(
        db
        .collection<PartyBankAccountDoc>('party_bank_accounts')
        .find(
          {
            user_id: uid,
            party_type: partyType!,
            party_id: partyId!,
          } as Filter<PartyBankAccountDoc>,
          { projection: { _id: 0, user_id: 0 } },
        )
        .sort([['created_at', -1]]),
        500,
      );

      // 7. Apply per-row masking. Never mutates the source row.
      return rows.map((r) => stripFullNumber(r, allowFull));
    },
  );
}
