import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate, type AuthUser } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6m · Company bank account read-only shadow.
 *
 *   GET /api/company-bank-accounts
 *
 * Faithful shadow of:
 *   backend/routers/company_bank_accounts.py::list_company_bank_accounts
 *   (lines 29–39)
 *
 * STRICTLY READ-ONLY. Class-C — Python handler is a pure
 * `find().sort().to_list()` chain. No writer hook, no audit call, no
 * backfill, no recompute, no effective-balance projection, no FinTxn
 * emission, no approvals/policy interaction, no paired-linkage refresh.
 *
 * Preserved semantics:
 *   * No query params. No `q`. No `active_only`.
 *   * Filter EXACTLY `{ user_id: uid, company_id: cid }`.
 *   * Projection `{ _id: 0, user_id: 0 }`.
 *   * Sort `created_at` DESC.
 *   * Cap 500.
 *   * Return `[strip_full_number(row, allow_full) for row in rows]` where
 *     `allow_full = party_role_can_view_full(user)`.
 *
 * ── NEW PARITY DIMENSION (Gate-6m): ROLE-BASED FIELD MASKING ──────────
 *
 * `party_role_can_view_full` (services_bank_accounts.py:146-148) is the
 * authoritative privileged-role predicate:
 *
 *   role = (user.get("effective_role") or user.get("role") or "").lower()
 *   return role in ("owner", "accountant", "admin")
 *
 * Privileged roles are EXACTLY: owner, accountant, admin (three, NOT two).
 * `admin` is included as a full-view role per authoritative source.
 *
 * `strip_full_number` (services_bank_accounts.py:129-138):
 *
 *   if not doc: return doc
 *   out = dict(doc)                                   # SHALLOW COPY
 *   if not allow_full:
 *       out["account_number"] = out.get("masked_display") or \
 *           mask_account_number(out.get("account_number", ""))
 *   return out
 *
 * `mask_account_number` (services_bank_accounts.py:11-18):
 *
 *   s = (acc or "").strip()
 *   if not s:            return ""
 *   if len(s) <= 4:      return "X" * len(s)
 *   return "X" * (len(s) - 4) + s[-4:]
 *
 * Both helpers are duplicated INLINE per the Gate-6m six-file ceiling.
 * Locked auth.ts / tenant.ts / errors.ts / prior-gate route files MUST
 * NOT be modified.
 */

// ── Privileged-role predicate (authoritative Python semantics inline) ─
// Python: role = (user.get("effective_role") or user.get("role") or "").lower()
// Node's AuthUser already coalesces `effective_role` from
// session.effective_role || session.role in the locked auth.ts (Gate-2),
// so the `role` fallback in the Python chain is preserved implicitly at
// the session-lookup layer. The explicit `|| ''` here mirrors Python's
// final falsy-fallback to the empty string.
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
// Shallow-copy semantics; original row never mutated; masked_display
// preserved; extra fields preserved; account_number is REPLACED (never
// deleted/renamed) when allow_full=false, using masked_display if
// truthy, else computed via mask_account_number.
function stripFullNumber(
  doc: Record<string, unknown>,
  allowFull: boolean,
): Record<string, unknown> {
  // Python: `if not doc: return doc`. In our Node call-site `doc` is
  // always a driver-returned document (never null), but we keep the
  // guard for structural parity.
  if (!doc) return doc;
  const out: Record<string, unknown> = { ...doc };
  if (!allowFull) {
    // Python `out.get("masked_display") or mask_account_number(...)` —
    // falsy-fallback (undefined, null, "" all trigger the computed mask).
    const md = out['masked_display'];
    out['account_number'] = md
      ? md
      : maskAccountNumber(out['account_number']);
  }
  return out;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerCompanyBankAccountsReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // ── GET /api/company-bank-accounts ─────────────────────────────────
  // migration-allowlisted: phase-3-gate-6m (read-only)
  app.get(
    '/api/company-bank-accounts',
    async (req: FastifyRequest, reply: FastifyReply) => {
      // 1. Auth → 401 with exact literals.
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

      // 2. Active company (X-Company-Id owned override + default fallback).
      const cid = await activeCompanyId(req, uid, db);

      // 3. Compute role-based masking predicate ONCE per request.
      const allowFull = partyRoleCanViewFull(user);

      // 4. Read with exact filter/projection/sort/cap.
      const rows = await db
        .collection('company_bank_accounts')
        .find(
          { user_id: uid, company_id: cid } as Filter<Record<string, unknown>>,
          { projection: { _id: 0, user_id: 0 } },
        )
        .sort([['created_at', -1]])
        .limit(500)
        .toArray();

      // 5. Apply masking to each row.
      return rows.map((r) => stripFullNumber(r, allowFull));
    },
  );
}
