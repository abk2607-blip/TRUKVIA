import type { Db } from 'mongodb';
import type { FastifyRequest } from 'fastify';

/**
 * TRUKVIA Node · Phase-3 · Gate-2 · active-company resolver (read-only).
 *
 * Faithful shadow of `backend/routers/supplier_ledger.py::_active_company_id`.
 *
 *   1. If the request carries `X-Company-Id` (case-insensitive) and that
 *      company is owned by the authenticated user, use it.
 *   2. Otherwise, use the user's default company (`is_default: true`).
 *   3. Otherwise, use any company owned by the user.
 *   4. Otherwise, empty string.
 *
 * Read-only: this function performs `findOne` lookups only. It never writes.
 */

interface CompanyDoc {
  id: string;
  is_default?: boolean;
  user_id?: string;
}

function readCompanyHeader(req: FastifyRequest): string {
  // Fastify normalises header names to lower-case; both `x-company-id` and
  // `X-Company-Id` end up on the same key. We accept the array form too.
  const raw = req.headers['x-company-id'];
  const first = Array.isArray(raw) ? raw[0] : raw;
  return typeof first === 'string' ? first.trim() : '';
}

export async function activeCompanyId(
  req: FastifyRequest,
  uid: string,
  db: Db,
): Promise<string> {
  const companies = db.collection<CompanyDoc>('companies');
  const override = readCompanyHeader(req);
  if (override) {
    const owned = await companies.findOne(
      { id: override, user_id: uid },
      { projection: { id: 1, _id: 0 } },
    );
    if (owned) return override;
  }
  const def = await companies.findOne(
    { user_id: uid, is_default: true },
    { projection: { id: 1, _id: 0 } },
  );
  if (def?.id) return def.id;
  const any = await companies.findOne(
    { user_id: uid },
    { projection: { id: 1, _id: 0 } },
  );
  return any?.id ?? '';
}
