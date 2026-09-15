import { createHash } from 'node:crypto';
import type { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import type { Db } from 'mongodb';

/**
 * TRUKVIA · Phase-3 · Gate-4 — Node Bucket-B idempotency port.
 * Faithful shadow of `backend/idempotency.py`. Scope is deliberately narrow:
 * only ONE route (`POST /api/saved-trip-filters`). Additional entries require
 * a separate authorised gate.
 *
 * Semantics (verbatim from Python):
 *   - Only POST + allowlisted paths + key len 8..128 activates.
 *   - Composite `_id` = sha256(user | company_or_'_' | METHOD | path | key).
 *   - Leader claims via insertOne({_id}); dup = follower.
 *   - Follower polls every 150ms up to 30s; if leader completes → replay.
 *   - handler throw → delete claim row.
 *   - cache only when status < 500 and body <= 5 MiB.
 *   - 5xx/oversize → delete claim (no cache).
 *   - Replay adds `x-idempotent-replay: 1`.
 *   - `ensureIdempotencyIndex` is safe/idempotent.
 */

const BUCKET_B_PATTERNS: readonly RegExp[] = [
  /^\/api\/saved-trip-filters$/,
];

const KEY_MIN_LEN = 8;
const KEY_MAX_LEN = 128;
const TTL_SECONDS = 24 * 3600;
const MAX_STORED_BYTES = 5 * 1024 * 1024;
const POLL_INTERVAL_MS = 150;
const POLL_TIMEOUT_MS = 30_000;

const PRESERVE_HEADERS = new Set<string>([
  'content-type',
  'content-disposition',
  'x-iter125-included',
  'x-iter125-skipped',
  'x-iter125-reasons',
  'x-iter125-pdfs',
]);

export function matchesBucketB(method: string, path: string): boolean {
  if (method.toUpperCase() !== 'POST') return false;
  return BUCKET_B_PATTERNS.some((rx) => rx.test(path));
}

export function compositeId(
  userId: string,
  companyId: string,
  method: string,
  path: string,
  key: string,
): string {
  const payload = `${userId}|${companyId || '_'}|${method}|${path}|${key}`;
  return createHash('sha256').update(payload, 'utf8').digest('hex');
}

interface SessionLite { user_id: string }

async function resolveUserAndCompany(req: FastifyRequest, db: Db): Promise<{ userId: string | null; companyId: string }> {
  let token: string | null = null;
  const cookie = req.headers['cookie'];
  if (typeof cookie === 'string') {
    for (const part of cookie.split(';')) {
      const [n, ...rest] = part.split('=');
      if (n?.trim() === 'session_token' && rest.length > 0) {
        const raw = rest.join('=').trim();
        if (raw) token = decodeURIComponent(raw);
        break;
      }
    }
  }
  if (!token) {
    const auth = req.headers['authorization'];
    if (typeof auth === 'string' && auth.startsWith('Bearer ')) {
      const t = auth.slice(7).trim();
      if (t) token = t;
    }
  }
  if (!token) return { userId: null, companyId: '' };
  try {
    const s = await db.collection<SessionLite>('user_sessions').findOne(
      { session_token: token }, { projection: { _id: 0, user_id: 1 } });
    if (!s) return { userId: null, companyId: '' };
    const cid = req.headers['x-company-id'];
    const first = Array.isArray(cid) ? cid[0] : cid;
    return { userId: s.user_id, companyId: typeof first === 'string' ? first : '' };
  } catch {
    return { userId: null, companyId: '' };
  }
}

interface ClaimRow {
  _id: string;
  status: 'in_progress' | 'completed';
  status_code?: number;
  response_body_b64?: string;
  response_headers?: Record<string, string>;
  media_type?: string;
}

export async function ensureIdempotencyIndex(db: Db): Promise<void> {
  try {
    await db.collection('idempotency_keys').createIndex(
      { created_at: 1 },
      { expireAfterSeconds: TTL_SECONDS, name: 'ttl_created_at' },
    );
  } catch {
    /* mirror Python: log-and-swallow; index may pre-exist */
  }
}

export function registerIdempotency(app: FastifyInstance, deps: { db: Db }): void {
  const { db } = deps;

  app.addHook('onRequest', async (req, reply) => {
    const path = req.url.split('?')[0] ?? '';
    const method = req.method;
    const key = (req.headers['idempotency-key'] as string | undefined ?? '').trim();

    if (!key || !matchesBucketB(method, path)) return;
    if (key.length < KEY_MIN_LEN || key.length > KEY_MAX_LEN) return;

    const { userId, companyId } = await resolveUserAndCompany(req, db);
    if (!userId) return;

    const kid = compositeId(userId, companyId, method, path, key);
    const coll = db.collection<ClaimRow>('idempotency_keys');
    const now = new Date();

    let claimed = true;
    try {
      await coll.insertOne({
        _id: kid, status: 'in_progress',
        // metadata for parity with Python's row shape
        ...(({ user_id: userId, company_id: companyId, method, path, key, created_at: now }) as unknown as object),
      } as unknown as ClaimRow);
    } catch {
      claimed = false;
    }

    if (!claimed) {
      // Follower path
      const deadline = Date.now() + POLL_TIMEOUT_MS;
      for (;;) {
        const row = await coll.findOne({ _id: kid });
        if (row && row.status === 'completed') {
          await sendReplay(reply, row);
          return;
        }
        if (Date.now() >= deadline) return; // fall through: run handler as fresh leader
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      }
    }

    // Leader path — attach onSend to capture and cache the response.
    (req as unknown as { __idem_kid?: string }).__idem_kid = kid;
  });

  app.addHook('onSend', async (req, reply, payload) => {
    const kid = (req as unknown as { __idem_kid?: string }).__idem_kid;
    if (!kid) return payload;

    const coll = db.collection<ClaimRow>('idempotency_keys');
    const status = reply.statusCode;

    let body: Buffer;
    if (Buffer.isBuffer(payload)) body = payload;
    else if (typeof payload === 'string') body = Buffer.from(payload, 'utf8');
    else if (payload == null) body = Buffer.alloc(0);
    else {
      // Streams / iterables are not cacheable in this minimal port
      try { await coll.deleteOne({ _id: kid }); } catch { /* noop */ }
      return payload;
    }

    const cacheable = status < 500 && body.length <= MAX_STORED_BYTES;
    if (!cacheable) {
      try { await coll.deleteOne({ _id: kid }); } catch { /* noop */ }
      return payload;
    }

    const preserved: Record<string, string> = {};
    for (const [h, v] of Object.entries(reply.getHeaders())) {
      if (typeof v === 'string' && PRESERVE_HEADERS.has(h.toLowerCase())) preserved[h.toLowerCase()] = v;
    }
    try {
      await coll.updateOne(
        { _id: kid },
        { $set: {
          status: 'completed',
          status_code: status,
          response_body_b64: body.toString('base64'),
          response_headers: preserved,
          media_type: preserved['content-type']?.split(';')[0]?.trim() ?? '',
          completed_at: new Date(),
        } },
      );
    } catch { /* mirror Python: log-and-swallow */ }
    return payload;
  });

  // Handler threw → also clear claim so a retry can proceed.
  app.addHook('onError', async (req) => {
    const kid = (req as unknown as { __idem_kid?: string }).__idem_kid;
    if (!kid) return;
    try { await db.collection<ClaimRow>('idempotency_keys').deleteOne({ _id: kid }); } catch { /* noop */ }
  });
}

async function sendReplay(reply: FastifyReply, row: ClaimRow): Promise<void> {
  const status = row.status_code ?? 200;
  const headers = row.response_headers ?? {};
  for (const [h, v] of Object.entries(headers)) reply.header(h, v);
  reply.header('x-idempotent-replay', '1');
  reply.code(status);
  const body = row.response_body_b64 ? Buffer.from(row.response_body_b64, 'base64') : Buffer.alloc(0);
  await reply.send(body);
}
