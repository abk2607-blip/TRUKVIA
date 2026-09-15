import { randomBytes } from 'node:crypto';
import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6h · Company / Supplier read-only shadows.
 *
 *   GET /api/company
 *   GET /api/suppliers/{sid}
 *
 * Faithful shadows of:
 *   backend/routers/companies.py::get_company   (lines 80–86)
 *   backend/routers/suppliers.py::get_supplier  (lines 139–145)
 *
 * STRICTLY READ-ONLY. Node performs ZERO writes on ANY business
 * collection. Both handlers plus the shared `_active_company_id`
 * helper only invoke `find_one`.
 *
 * Deliberate contract preservation:
 *   * `/api/company` MISS path returns HTTP 200 with a fresh default
 *     Company object (NOT 404). Verified 36-field default set — see
 *     `defaultCompany()` — mirrors `backend/models.py:66 · Company`.
 *   * Company `id` field on the miss path is regenerated per request
 *     (`co_` + 16 lowercase hex). Byte parity with Python is IMPOSSIBLE
 *     by design; parity harness tolerates ONLY this one field on the
 *     miss path and asserts the shared shape `^co_[0-9a-f]{16}$`.
 *   * `/api/suppliers/{sid}` uses composite `user_id + company_id`
 *     scoping — cross-user OR cross-company → 404 "Supplier not found".
 *   * Extra stored fields on HIT paths pass through unmodified.
 */

// ── Company defaults (verbatim mirror of backend/models.py:66) ───────
// If the Python `Company` model changes upstream, THIS block must be
// updated in the same commit. Keep the field ordering identical to the
// Python model for reviewer diffing.
function defaultCompany(): Record<string, unknown> {
  return {
    // `id` shape: 'co_' + 16 lowercase-hex chars (matches Python
    // `new_id("co_")` → f"co_{uuid.uuid4().hex[:16]}").
    id: `co_${randomBytes(8).toString('hex')}`,
    name: '',
    address: '',
    phone: '',
    email: '',
    gstin: '',
    pan: '',
    state: '',
    pincode: '',
    bank_name: '',
    account_number: '',
    ifsc: '',
    branch: '',
    hsn_sac: '996791',
    invoice_prefix: 'INV',
    next_invoice_number: 1,
    next_invoice_number_by_fy: {} as Record<string, number>,
    lr_prefix: 'LR',
    next_lr_number: 1,
    logo: '',
    udyam_registration: '',
    signature_file_id: '',
    authorised_signatory_name: '',
    authorised_signatory_designation: '',
    signature_mode: 'none',
    jurisdiction: '',
    system_generated_note: '',
    is_default: false,
    credit_note_prefix: 'CN',
    next_credit_note_number: 1,
    debit_note_prefix: 'DN',
    next_debit_note_number: 1,
    require_cdn_approval: false,
    require_approval_trip: false,
    require_approval_invoice: false,
    require_approval_payment: false,
  };
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerCompanySupplierReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // ── GET /api/company ────────────────────────────────────────────────
  // migration-allowlisted: phase-3-gate-6h (read-only)
  //
  // Note: filter is `{ id: cid, user_id }` WITHOUT a company_id clause
  // — the resolved active-company id IS the row key being fetched.
  app.get('/api/company', async (req: FastifyRequest, reply: FastifyReply) => {
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
    // 2. Active company (X-Company-Id override + default fallback).
    const cid = await activeCompanyId(req, userId, db);
    // 3. Read — no company_id filter (cid IS the row id).
    const doc = await db.collection('companies').findOne(
      { id: cid, user_id: userId },
      { projection: { _id: 0, user_id: 0 } },
    );
    // 4. MISS PATH — 200 with default Company (matches Python
    //    `Company().model_dump()` fallback).
    if (!doc) return defaultCompany();
    // 5. HIT PATH — raw stored doc after projection.
    return doc;
  });

  // ── GET /api/suppliers/{sid} ────────────────────────────────────────
  // migration-allowlisted: phase-3-gate-6h (read-only)
  app.get<{ Params: { sid: string } }>(
    '/api/suppliers/:sid',
    async (
      req: FastifyRequest<{ Params: { sid: string } }>,
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
      const cid = await activeCompanyId(req, userId, db);
      // 3. Composite user_id + company_id scoped read.
      const doc = await db.collection('suppliers').findOne(
        { id: req.params.sid, user_id: userId, company_id: cid },
        { projection: { _id: 0, user_id: 0 } },
      );
      if (!doc) {
        reply.code(404);
        return { detail: 'Supplier not found' };
      }
      return doc;
    },
  );
}
