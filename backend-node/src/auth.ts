import type { Db } from 'mongodb';
import type { FastifyRequest } from 'fastify';
import { HttpError } from './errors.js';

/**
 * TRUKVIA Node · Phase-3 · Gate-2 · session authentication (read-only shadow).
 *
 * Faithful shadow of `backend/auth.py::get_current_user` for the subset of
 * behaviour required by the first read-only route.
 *
 * IMPORTANT — documented parity limitation vs Python:
 *
 *   Python performs a rolling-refresh WRITE on `user_sessions.last_refreshed_at`
 *   every ROLLING_REFRESH_MIN_INTERVAL_SEC seconds. This Node port deliberately
 *   OMITS that write to honour the Phase-3 read-only guarantee. Session TTL /
 *   expiry semantics are otherwise preserved:
 *
 *     - Missing token           → 401 "Not authenticated"
 *     - Token, no session row   → 401 "Invalid session"
 *     - Token, session expired  → 401 "Session expired"
 *
 * The Python demo-token bypass is NOT implemented here; production sessions
 * flow the same lookup path in both stacks.
 */

export interface AuthUser {
  user_id: string;
  effective_role: string;
  email?: string;
}

interface UserSessionDoc {
  session_token: string;
  user_id: string;
  effective_role?: string;
  role?: string;
  email?: string;
  expires_at: string | Date;
}

function extractSessionToken(req: FastifyRequest): string | null {
  const cookieHeader = req.headers['cookie'];
  if (typeof cookieHeader === 'string') {
    for (const part of cookieHeader.split(';')) {
      const [rawName, ...rest] = part.split('=');
      if (rawName?.trim() === 'session_token' && rest.length > 0) {
        const raw = rest.join('=').trim();
        if (raw) return decodeURIComponent(raw);
      }
    }
  }
  const auth = req.headers['authorization'];
  const bearer = typeof auth === 'string' ? auth : null;
  if (bearer && bearer.startsWith('Bearer ')) {
    const t = bearer.slice('Bearer '.length).trim();
    return t.length > 0 ? t : null;
  }
  return null;
}

function parseExpiresAt(raw: unknown): Date | null {
  if (raw instanceof Date) return Number.isNaN(raw.getTime()) ? null : raw;
  if (typeof raw === 'string') {
    const d = new Date(raw);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  return null;
}

export async function authenticate(req: FastifyRequest, db: Db): Promise<AuthUser> {
  const token = extractSessionToken(req);
  if (!token) {
    throw new HttpError(401, 'Not authenticated');
  }
  const session = await db
    .collection<UserSessionDoc>('user_sessions')
    .findOne({ session_token: token }, { projection: { _id: 0 } });
  if (!session) {
    throw new HttpError(401, 'Invalid session');
  }
  const exp = parseExpiresAt(session.expires_at);
  if (!exp || exp.getTime() < Date.now()) {
    throw new HttpError(401, 'Session expired');
  }
  return {
    user_id: session.user_id,
    effective_role: session.effective_role ?? session.role ?? '',
    ...(session.email !== undefined ? { email: session.email } : {}),
  };
}
