import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7w · Saved trip filters list read-only shadow.
 *
 *   GET /api/saved-trip-filters
 *
 * Faithful shadow of:
 *   backend/routers/saved_filters.py::list_saved_filters (L25-32)
 *
 * Python (verbatim):
 * ```
 * @router.get("/saved-trip-filters")
 * async def list_saved_filters(request: Request, user=Depends(get_current_user)):
 *     cid = await _active_company_id(request, user)
 *     docs = await db.saved_trip_filters.find(
 *         {"user_id": user["user_id"], "company_id": cid},
 *         {"_id": 0},
 *     ).sort("created_at", -1).limit(50).to_list(50)
 *     return docs
 * ```
 *
 * STRICTLY READ-ONLY. One read on saved_trip_filters; no backfill, no audit.
 *
 * LISTING: the path is on `.migration-deferred` (NOT the Class-C allowlist)
 * because the parked Gate-4 POST writer shares it (Gate-7t invariants B1/B2).
 * This GET is parity-proven but not cutover-eligible until the writer phase.
 *
 * ── GATE-7w BINDINGS ────────────────────────────────────────────────
 *
 *   1. ORDER: auth (locked 401 literals) → `_active_company_id` (locked
 *      tenant helper) → read. No query parameters (all ignored, no 422/400).
 *
 *   2. READ: filter {user_id, company_id}, projection {_id: 0} (user_id and
 *      company_id are PRESERVED), sort created_at DESC, SERVER-SIDE limit 50
 *      (`.limit(50)` is part of the Python cursor, so the same find command
 *      — incl. its tie order — is sent; to_list(50) never cuts further).
 *
 *   3. BODY = FastAPI jsonable_encoder + json.dumps(ensure_ascii=False,
 *      allow_nan=False, compact) rebuilt from typed documents
 *      (promoteValues:false): whole doubles "5.0", naive datetime isoformat,
 *      NaN/±Infinity or unencodable BSON → 500 `Internal Server Error`
 *      (text/plain; charset=utf-8). Top level is a JSON array.
 *
 *   4. CONTENT-TYPE exactly `application/json` (Buffer payload).
 *
 *   5. HEAD: FastAPI answers 405 + `allow: GET` (verified live) — Fastify
 *      auto-HEAD disabled for this route and the 405 reproduced explicitly.
 */

type Doc = Record<string, unknown>;

class PyServerError extends Error {}
const fail = (why: string): never => { throw new PyServerError(why); };

const bsonType = (v: unknown): string | undefined =>
  typeof v === 'object' && v !== null ? ((v as { _bsontype?: string })._bsontype) : undefined;

const binaryBytes = (v: unknown): Uint8Array => {
  const b = v as { buffer: Uint8Array; length(): number };
  return b.buffer.subarray(0, b.length());
};

// ── Python json.dumps / FastAPI jsonable_encoder (local copy, Gate 7r/7s) ──
function pyFloatRepr(x: number): string {
  if (!Number.isFinite(x)) return fail('json: out of range float');
  if (x === 0) return Object.is(x, -0) ? '-0.0' : '0.0';
  const sign = x < 0 ? '-' : '';
  const [mant, exp] = Math.abs(x).toExponential().split('e') as [string, string];
  const digits = mant.replace('.', '');
  const decpt = Number(exp) + 1;
  if (decpt > -4 && decpt <= 16) {
    if (decpt <= 0) return `${sign}0.${'0'.repeat(-decpt)}${digits}`;
    if (decpt >= digits.length) return `${sign}${digits}${'0'.repeat(decpt - digits.length)}.0`;
    return `${sign}${digits.slice(0, decpt)}.${digits.slice(decpt)}`;
  }
  const e = decpt - 1;
  const m = digits.length > 1 ? `${digits[0]}.${digits.slice(1)}` : digits;
  return `${sign}${m}e${e < 0 ? '-' : '+'}${String(Math.abs(e)).padStart(2, '0')}`;
}

function pyIsoformat(d: Date): string {
  const ms = d.getTime();
  if (Number.isNaN(ms)) return fail('datetime: invalid');
  const y = d.getUTCFullYear();
  if (y < 1 || y > 9999) return fail('datetime: out of range');
  const p2 = (n: number): string => String(n).padStart(2, '0');
  const base = `${String(y).padStart(4, '0')}-${p2(d.getUTCMonth() + 1)}-${p2(d.getUTCDate())}`
    + `T${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}:${p2(d.getUTCSeconds())}`;
  const msPart = d.getUTCMilliseconds();
  return msPart ? `${base}.${String(msPart * 1000).padStart(6, '0')}` : base;
}

const UTF8_STRICT = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
function pyBytesDecode(v: unknown): string {
  try {
    return UTF8_STRICT.decode(binaryBytes(v));
  } catch {
    return fail('bytes: invalid utf-8');
  }
}

function pyJson(v: unknown): string {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'string') return JSON.stringify(v);
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : pyFloatRepr(v);
  if (Array.isArray(v)) return `[${v.map(pyJson).join(',')}]`;
  if (v instanceof Date) return JSON.stringify(pyIsoformat(v));
  const t = bsonType(v);
  if (t === 'Double') return pyFloatRepr((v as { value: number }).value);
  if (t === 'Int32') return String((v as { value: number }).value);
  if (t === 'Long') return (v as { toString(): string }).toString();
  if (t === 'Binary') return JSON.stringify(pyBytesDecode(v));
  if (t === 'Code') return JSON.stringify((v as { code: string }).code);
  if (t === 'BSONSymbol') return JSON.stringify(String((v as { value: string }).value));
  if (t !== undefined || v instanceof RegExp) return fail(`json: unsupported ${t ?? 'RegExp'}`);
  const parts: string[] = [];
  for (const [k, val] of Object.entries(v as Doc)) parts.push(`${JSON.stringify(k)}:${pyJson(val)}`);
  return `{${parts.join(',')}}`;
}

// JSON responses of this route are exactly `application/json` (no charset).
const sendJson = (reply: FastifyReply, status: number, body: string): FastifyReply =>
  reply.code(status).header('content-type', 'application/json').send(Buffer.from(body, 'utf8'));

const METHOD_NOT_ALLOWED = Buffer.from('{"detail":"Method Not Allowed"}', 'utf8');

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerSavedTripFiltersListRoute(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-deferred: phase-3-gate-7w (read-only; path shared with the parked Gate-4 writer)
  app.get('/api/saved-trip-filters', { exposeHeadRoute: false }, async (req: FastifyRequest, reply: FastifyReply) => {
    // 1. Auth FIRST — locked 401 literals.
    let userId: string;
    try {
      userId = (await authenticate(req, db)).user_id;
    } catch (err) {
      if (err instanceof HttpError) return sendJson(reply, err.status, JSON.stringify({ detail: err.detail }));
      throw err;
    }

    // 2. Active-company resolution (locked helper).
    const cid = await activeCompanyId(req, userId, db);

    // 3. Same find command as Motor: filter, projection, sort, server limit 50.
    try {
      const docs = await db
        .collection<Doc>('saved_trip_filters')
        .find({ user_id: userId, company_id: cid } as Filter<Doc>, { projection: { _id: 0 }, promoteValues: false })
        .sort({ created_at: -1 })
        .limit(50)
        .toArray();
      return sendJson(reply, 200, pyJson(docs));
    } catch (err) {
      if (err instanceof PyServerError) {
        return reply.code(500).header('content-type', 'text/plain; charset=utf-8').send('Internal Server Error');
      }
      throw err;
    }
  });

  // FastAPI registers GET (and POST) only → HEAD is 405 before auth (verified live).
  app.head('/api/saved-trip-filters', async (_req: FastifyRequest, reply: FastifyReply) =>
    reply.code(405).header('allow', 'GET').header('content-type', 'application/json').send(METHOD_NOT_ALLOWED));
}
