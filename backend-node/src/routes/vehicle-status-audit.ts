import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-8b · Vehicle status-audit read-only shadow.
 *
 *   GET /api/vehicles/{vid}/status-audit
 *
 * Faithful shadow of:
 *   backend/routers/vehicles.py::list_vehicle_status_audit (L181-200)
 *
 * Python (verbatim):
 * ```
 * @router.get("/vehicles/{vid}/status-audit")
 * async def list_vehicle_status_audit(vid: str, request: Request, user=Depends(get_current_user)):
 *     cid = await _active_company_id(request, user)
 *     v = await db.vehicles.find_one(
 *         {"id": vid, "user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0})
 *     if not v:
 *         raise HTTPException(status_code=404, detail="Vehicle not found")
 *     docs = await (db.vehicle_status_audit_log
 *                   .find({"user_id": user["user_id"], "company_id": cid, "vehicle_id": vid},
 *                         {"_id": 0, "user_id": 0})
 *                   .sort("changed_at", -1)
 *                   .to_list(500))
 *     return {
 *         "vehicle": {"id": v["id"], "vehicle_number": v.get("vehicle_number"),
 *                      "is_active": v.get("is_active", True) is not False},
 *         "items": docs,
 *         "total": len(docs),
 *     }
 * ```
 *
 * STRICTLY READ-ONLY. Two reads, in this order; no backfill / audit. The
 * audit rows are written only by PATCH /api/vehicles/{vid}/status (not migrated).
 *
 * ── GATE-8b BINDINGS ────────────────────────────────────────────────
 *
 *   1. PATH: Starlette `[^/]+` on the decoded path — empty `vid` or one
 *      containing "/" → 404 {"detail":"Not Found"} before auth (as 7p/7z/8a).
 *
 *   2. ORDER: auth (locked 401 literals) → `_active_company_id` (locked
 *      tenant helper) → READ #1 → 404 / READ #2. No query parameters.
 *
 *   3. READ #1: vehicles.find_one({id, user_id, company_id},
 *      {_id: 0, user_id: 0}) — limit 1 single batch. `if not v` (a matched
 *      doc always carries id + company_id → non-empty) → 404
 *      {"detail":"Vehicle not found"}.
 *
 *   4. READ #2: vehicle_status_audit_log.find({user_id, company_id,
 *      vehicle_id}, {_id: 0, user_id: 0}) — user + company + vehicle scoped
 *      (exactly Python's three filters). Sort changed_at DESC. Motor
 *      `to_list(500)` sends NO server limit → unlimited sorted cursor,
 *      iteration stops at 500.
 *
 *   5. WRAPPER (key order): {"vehicle": {"id": v["id"] (raw value),
 *      "vehicle_number": v.get(...) → null when missing, "is_active":
 *      `is not False` → false ONLY for a stored boolean false (missing /
 *      null / 0 / "false" → true)}, "items": docs, "total": len(docs)} —
 *      total = number of returned rows (after the 500 cap), an integer.
 *
 *   6. BODY = FastAPI jsonable_encoder + json.dumps rebuilt from typed
 *      documents (promoteValues:false); NaN / ±Infinity / unencodable BSON
 *      → 500 `Internal Server Error` (text/plain; charset=utf-8).
 *
 *   7. CONTENT-TYPE exactly `application/json` (Buffer payload).
 *
 *   8. HEAD: FastAPI answers 405 + `allow: GET` (verified live) — Fastify
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

const NOT_FOUND = '{"detail":"Not Found"}';
const VEHICLE_NOT_FOUND = '{"detail":"Vehicle not found"}';
const METHOD_NOT_ALLOWED = Buffer.from('{"detail":"Method Not Allowed"}', 'utf8');
const TO_LIST_LENGTH = 500;
const has = (o: object, k: string): boolean => Object.prototype.hasOwnProperty.call(o, k);

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerVehicleStatusAuditRoute(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-8b (read-only)
  app.get('/api/vehicles/:vid/status-audit', { exposeHeadRoute: false },
    async (req: FastifyRequest, reply: FastifyReply) => {
      const vid = (req.params as { vid: string }).vid;

      // 0. Starlette never routes an empty segment or a decoded "/" (`[^/]+`).
      if (vid === '' || vid.includes('/')) return sendJson(reply, 404, NOT_FOUND);

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

      try {
        // 3. READ #1 — vehicle ownership (user + company scoped).
        const v = await db
          .collection<Doc>('vehicles')
          .findOne({ id: vid, user_id: userId, company_id: cid } as Filter<Doc>, {
            projection: { _id: 0, user_id: 0 }, promoteValues: false,
          });
        if (!v || Object.keys(v).length === 0) return sendJson(reply, 404, VEHICLE_NOT_FOUND);

        // 4. READ #2 — user + company + vehicle scoped; unlimited sorted cursor, stop at 500.
        const cursor = db
          .collection<Doc>('vehicle_status_audit_log')
          .find({ user_id: userId, company_id: cid, vehicle_id: vid } as Filter<Doc>, {
            projection: { _id: 0, user_id: 0 }, promoteValues: false,
          })
          .sort({ changed_at: -1 });
        const docs: Doc[] = [];
        try {
          for await (const doc of cursor) {
            docs.push(doc);
            if (docs.length >= TO_LIST_LENGTH) break;
          }
        } finally {
          await cursor.close();
        }

        // 5. Python wrapper — `is not False` is true unless the stored value is boolean false.
        const vehicle = `{"id":${pyJson(v['id'])},`
          + `"vehicle_number":${has(v, 'vehicle_number') ? pyJson(v['vehicle_number']) : 'null'},`
          + `"is_active":${v['is_active'] === false ? 'false' : 'true'}}`;
        return sendJson(reply, 200, `{"vehicle":${vehicle},"items":${pyJson(docs)},"total":${docs.length}}`);
      } catch (err) {
        if (err instanceof PyServerError) {
          return reply.code(500).header('content-type', 'text/plain; charset=utf-8').send('Internal Server Error');
        }
        throw err;
      }
    });

  // FastAPI registers GET only on this path → HEAD is 405 before auth (verified live).
  app.head('/api/vehicles/:vid/status-audit', async (_req: FastifyRequest, reply: FastifyReply) =>
    reply.code(405).header('allow', 'GET').header('content-type', 'application/json').send(METHOD_NOT_ALLOWED));
}
