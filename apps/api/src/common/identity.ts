/**
 * TRUKVIA · Phase 6 · slice 1 — auth identity + tenant resolution.
 *
 * PORTED, not re-derived, from the gate-locked implementations:
 *   backend-node/src/auth.ts   (Gate 9b — login identity + role parity)
 *   backend-node/src/tenant.ts (Gate 9c — X-Company-Id first raw occurrence)
 *
 * Those gates fixed live P0 defects (owners seeing masked bank numbers, staff
 * seeing empty results, duplicate company headers resolving to the wrong
 * tenant). Re-deriving this logic from the Python source would reintroduce
 * them, so this file mirrors the locked TypeScript.
 *
 * Sessions, users, team_members and companies still live in MongoDB during
 * slice 1: Python remains their writer. Only vendor data comes from Postgres.
 */
import type { IncomingMessage } from 'node:http';
import type { Db } from 'mongodb';

export class HttpError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(typeof detail === 'string' ? detail : 'http error');
  }
}

export interface AuthUser {
  user_id: string;
  effective_role: string;
  is_staff: boolean;
  email?: string;
}

type Doc = Record<string, unknown>;

const has = (o: object, k: string): boolean => Object.prototype.hasOwnProperty.call(o, k);

/** Python truthiness for the values this code path can see. */
function pyTruthy(v: unknown): boolean {
  if (v === undefined || v === null || v === false) return false;
  if (v === '' || v === 0) return false;
  if (Array.isArray(v)) return v.length > 0;
  return true;
}

/** CPython datetime.fromisoformat, as ported at Gate 9b: string OR BSON date. */
function expiresAtMs(v: unknown): number {
  if (v instanceof Date) return v.getTime();
  if (typeof v === 'number') return v;
  if (typeof v !== 'string') return -Infinity;
  // fromisoformat accepts "+00:00" and a bare (naive) timestamp, which Python
  // then treats as UTC in this codebase.
  const s = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(v) ? v : `${v}+00:00`;
  const ms = Date.parse(s);
  return Number.isNaN(ms) ? -Infinity : ms;
}

export function extractSessionToken(req: IncomingMessage): string | null {
  const auth = req.headers['authorization'];
  if (typeof auth === 'string' && auth.startsWith('Bearer ')) {
    const t = auth.slice(7);
    if (t) return t;
  }
  const cookie = req.headers['cookie'];
  if (typeof cookie === 'string') {
    for (const part of cookie.split(';')) {
      const [k, ...rest] = part.trim().split('=');
      if (k === 'session_token' && rest.length) return rest.join('=');
    }
  }
  return null;
}

/** Port of auth.ts::authenticate. Throws HttpError(401) exactly where Python does. */
export async function authenticate(req: IncomingMessage, mongo: Db): Promise<AuthUser> {
  const token = extractSessionToken(req);
  if (!token) throw new HttpError(401, 'Not authenticated');

  const session = await mongo
    .collection<Doc>('user_sessions')
    .findOne({ session_token: token }, { projection: { _id: 0 } });
  if (!session) throw new HttpError(401, 'Invalid session');

  if (expiresAtMs(session['expires_at']) < Date.now()) throw new HttpError(401, 'Session expired');

  if (!has(session, 'user_id')) throw new HttpError(500, 'Internal Server Error');
  const user = await mongo
    .collection<Doc>('users')
    .findOne({ user_id: session['user_id'] ?? null }, { projection: { _id: 0 } });
  if (!user || Object.keys(user).length === 0) throw new HttpError(401, 'User not found');

  // Python reads user["email"] unconditionally: a users doc without it is a 500.
  if (!has(user, 'email')) throw new HttpError(500, 'Internal Server Error');

  const tm = await mongo
    .collection<Doc>('team_members')
    .findOne({ email: user['email'] ?? null, active: true }, { projection: { _id: 0 } });

  let scopeUserId: unknown;
  let effectiveRole: unknown;
  let isStaff: boolean;
  if (tm && Object.keys(tm).length > 0 && pyTruthy(tm['owner_user_id'])) {
    if (!has(user, 'user_id')) throw new HttpError(500, 'Internal Server Error');
    if (tm['owner_user_id'] !== user['user_id']) {
      scopeUserId = tm['owner_user_id'];
      effectiveRole = has(tm, 'role') ? tm['role'] : 'accountant';
      isStaff = true;
    } else {
      scopeUserId = user['user_id'];
      effectiveRole = 'owner';
      isStaff = false;
    }
  } else {
    scopeUserId = user['user_id'];
    effectiveRole = 'owner';
    isStaff = false;
  }

  const roleChain = pyTruthy(effectiveRole) ? effectiveRole : user['role'];
  return {
    user_id: scopeUserId as string,
    effective_role: (pyTruthy(roleChain) ? roleChain : '') as string,
    is_staff: isStaff,
    ...(typeof user['email'] === 'string' ? { email: user['email'] } : {}),
  };
}

/**
 * Port of tenant.ts::readCompanyHeader — Starlette returns the FIRST raw
 * occurrence of a duplicated header. Node exposes duplicates joined with ", ",
 * and req.rawHeaders preserves the original order, so read from there.
 * A single header whose value contains a comma stays one literal value.
 * No trimming beyond what the HTTP parser already strips (SP/HTAB).
 */
export function readCompanyHeader(req: IncomingMessage): string {
  const raw = req.rawHeaders;
  for (let i = 0; i + 1 < raw.length; i += 2) {
    if ((raw[i] ?? '').toLowerCase() === 'x-company-id') return raw[i + 1] ?? '';
  }
  return '';
}

/** Port of tenant.ts::activeCompanyId. Companies still live in MongoDB. */
export async function activeCompanyId(
  req: IncomingMessage,
  uid: string,
  mongo: Db,
): Promise<string> {
  const companies = mongo.collection<Doc>('companies');
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
  if (typeof def?.['id'] === 'string') return def['id'] as string;
  const any = await companies.findOne({ user_id: uid }, { projection: { id: 1, _id: 0 } });
  return typeof any?.['id'] === 'string' ? (any['id'] as string) : '';
}
