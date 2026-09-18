import type { Db } from 'mongodb';
import type { FastifyRequest } from 'fastify';

/**
 * TRUKVIA Node · Phase-3 · Gate-2 · active-company resolver (read-only).
 *
 * Faithful shadow of `backend/routers/supplier_ledger.py::_active_company_id`.
 *
 *   1. If the request carries `X-Company-Id` (case-insensitive; first raw
 *      occurrence wins, Gate 9c) and that company is owned by the
 *      authenticated user, use it.
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
  // Gate 9c: Starlette `request.headers.get("x-company-id")` returns the FIRST
  // raw occurrence (name matched case-insensitively). Node joins duplicates in
  // `req.headers` as "a, b", so read `rawHeaders` instead. A single header that
  // itself contains a comma stays one literal value. No extra trim: llhttp
  // already strips SP/HTAB exactly like h11; JS trim would also drop NBSP,
  // which Python keeps.
  const raw = req.raw.rawHeaders;
  for (let i = 0; i + 1 < raw.length; i += 2) {
    if ((raw[i] as string).toLowerCase() === 'x-company-id') return raw[i + 1] as string;
  }
  return '';
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
