import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-8c · Driver shortage-policy resolve read-only shadow.
 *
 *   GET /api/driver-shortage-policies/resolve?trip_date=...&product_category=...
 *
 * Faithful shadow of:
 *   backend/routers/driver_shortage_policies.py::resolve_policy_endpoint (L310-324)
 *   backend/routers/driver_shortage_policies.py::resolve_policy_for_trip  (L32-78)
 *
 * Python (verbatim, abridged):
 * ```
 * async def resolve_policy_endpoint(request, user=Depends(get_current_user),
 *                                   trip_date: str = "", product_category: str = ""):
 *     if not trip_date:
 *         raise HTTPException(status_code=400, detail="trip_date required (YYYY-MM-DD)")
 *     cid = await _active_company_id(request, user)
 *     p = await resolve_policy_for_trip(user["user_id"], cid, trip_date,
 *                                       product_category=product_category or None)
 *     return {"policy": p, "trip_date": trip_date}
 *
 * async def resolve_policy_for_trip(user_id, company_id, trip_date, product_category=None):
 *     if not trip_date: return None
 *     q_base = {"user_id": user_id, "company_id": company_id, "active": True,
 *               "effective_from": {"$lte": trip_date},
 *               "$or": [{"effective_to": {"$exists": False}}, {"effective_to": None},
 *                       {"effective_to": {"$gte": trip_date}}]}
 *     if product_category:
 *         p = await db.driver_shortage_policies.find_one(
 *             {**q_base, "product_category": product_category},
 *             sort=[("effective_from", -1), ("version", -1)])
 *         if p: p.pop("_id", None); return p
 *     p = await db.driver_shortage_policies.find_one(
 *         {**q_base, "$and": [{"$or": [{"product_category": {"$exists": False}},
 *                                      {"product_category": None}, {"product_category": ""}]}]},
 *         sort=[("effective_from", -1), ("version", -1)])
 *     if p: p.pop("_id", None)
 *     return p
 * ```
 *
 * STRICTLY READ-ONLY. At most two find_one reads; no write / backfill / audit.
 *
 * ── GATE-8c BINDINGS ────────────────────────────────────────────────
 *
 *   1. ORDER: auth (locked 401 literals) → `if not trip_date` 400 (BEFORE
 *      company resolution — no company read / repair on a 400) →
 *      `_active_company_id` (locked tenant helper) → READ #1? → READ #2?.
 *
 *   2. PARAMS: `trip_date: str = ""`, `product_category: str = ""` — plain
 *      optional strings, never parsed or trimmed, no 422 surface. Starlette
 *      query decoding (local copy, Gate 7v); repeated key → LAST value.
 *
 *   3. READ #1 only when product_category is truthy: filter = q_base +
 *      {product_category} (key order preserved), NO projection, sort
 *      effective_from -1, version -1, limit 1 single batch. A hit wins.
 *   4. READ #2 (fallback, always when READ #1 absent or empty): q_base +
 *      $and[$or[$exists false, null, ""]] — same sort / no projection.
 *      `_id` popped from whichever document is returned.
 *
 *   5. RESPONSE {"policy": doc | null, "trip_date": <raw trip_date>}; JSON =
 *      jsonable_encoder + json.dumps rebuilt from the typed document
 *      (promoteValues:false); NaN / unencodable BSON → 500 text/plain.
 *
 *   6. CONTENT-TYPE exactly `application/json` (Buffer payload).
 *
 *   7. HEAD: Starlette's first PARTIAL match for this path is the earlier
 *      `PUT /driver-shortage-policies/{pid}` route → 405 with `allow: PUT`
 *      (verified live). Reproduced for this route only (auto-HEAD disabled).
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

// ── Starlette QueryParams: latin-1 → CPython 3.11 parse_qsl (local copy, Gate 7v) ──
const HEX = /^[0-9A-Fa-f]{2}$/;
const UTF8_REPLACE = new TextDecoder('utf-8', { fatal: false, ignoreBOM: true });

// urllib.parse.unquote_to_bytes(<ASCII run>).decode('utf-8', 'replace')
function unquoteAsciiRun(run: string): string {
  const bits = run.split('%');
  if (bits.length === 1) return run;
  const bytes: number[] = [];
  const pushAscii = (t: string): void => {
    for (let i = 0; i < t.length; i++) bytes.push(t.charCodeAt(i));
  };
  pushAscii(bits[0] as string);
  for (let i = 1; i < bits.length; i++) {
    const item = bits[i] as string;
    const h = item.slice(0, 2);
    if (HEX.test(h)) {
      bytes.push(parseInt(h, 16));
      pushAscii(item.slice(2));
    } else {
      bytes.push(0x25);
      pushAscii(item);
    }
  }
  return UTF8_REPLACE.decode(Uint8Array.from(bytes));
}

// urllib.parse.unquote_plus(s) on a latin-1-decoded str
function pyUnquotePlus(input: string): string {
  const s = input.replace(/\+/g, ' ');
  if (!s.includes('%')) return s;
  // _asciire = re.compile('([\x00-\x7f]+)'); only ASCII runs are unquoted.
  return s.replace(/[\x00-\x7f]+/g, (run) => unquoteAsciiRun(run));
}

// Last occurrence of `key` (ImmutableMultiDict.get), undefined when absent.
function pyQueryLast(rawUrl: string, key: string): string | undefined {
  const qi = rawUrl.indexOf('?');
  if (qi < 0) return undefined;
  const qs = rawUrl.slice(qi + 1);
  let found: string | undefined;
  for (const field of qs.split('&')) {
    if (!field) continue;
    const eq = field.indexOf('=');
    const name = eq < 0 ? field : field.slice(0, eq);
    const value = eq < 0 ? '' : field.slice(eq + 1);
    if (pyUnquotePlus(name) === key) found = pyUnquotePlus(value);
  }
  return found;
}

// JSON responses of this route are exactly `application/json` (no charset).
const sendJson = (reply: FastifyReply, status: number, body: string): FastifyReply =>
  reply.code(status).header('content-type', 'application/json').send(Buffer.from(body, 'utf8'));

const TRIP_DATE_REQUIRED = '{"detail":"trip_date required (YYYY-MM-DD)"}';
const METHOD_NOT_ALLOWED = Buffer.from('{"detail":"Method Not Allowed"}', 'utf8');
const SORT = { effective_from: -1, version: -1 } as const;

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerDriverShortagePolicyResolveRoute(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-8c (read-only)
  app.get('/api/driver-shortage-policies/resolve', { exposeHeadRoute: false },
    async (req: FastifyRequest, reply: FastifyReply) => {
      // 1. Auth FIRST — locked 401 literals.
      let userId: string;
      try {
        userId = (await authenticate(req, db)).user_id;
      } catch (err) {
        if (err instanceof HttpError) return sendJson(reply, err.status, JSON.stringify({ detail: err.detail }));
        throw err;
      }

      // 2. Optional plain-str params (default ""); 400 before company resolution.
      const rawUrl = req.raw.url ?? '';
      const tripDate = pyQueryLast(rawUrl, 'trip_date') ?? '';
      const productCategory = pyQueryLast(rawUrl, 'product_category') ?? '';
      if (!tripDate) return sendJson(reply, 400, TRIP_DATE_REQUIRED);

      // 3. Active-company resolution (locked helper).
      const cid = await activeCompanyId(req, userId, db);

      try {
        const coll = db.collection<Doc>('driver_shortage_policies');
        const qBase = (): Doc => ({
          user_id: userId, company_id: cid, active: true,
          effective_from: { $lte: tripDate },
          $or: [
            { effective_to: { $exists: false } },
            { effective_to: null },
            { effective_to: { $gte: tripDate } },
          ],
        });

        // 4. READ #1 — exact product_category (only when truthy); a hit wins.
        let p: Doc | null = null;
        if (productCategory) {
          p = await coll.findOne({ ...qBase(), product_category: productCategory } as Filter<Doc>,
            { sort: SORT, promoteValues: false });
          if (p !== null && Object.keys(p).length === 0) p = null;
        }

        // 5. READ #2 — catch-all fallback (missing / null / "").
        if (p === null) {
          p = await coll.findOne({
            ...qBase(),
            $and: [{ $or: [{ product_category: { $exists: false } }, { product_category: null }, { product_category: '' }] }],
          } as Filter<Doc>, { sort: SORT, promoteValues: false });
        }

        let policy = 'null';
        if (p !== null) {
          delete p['_id'];
          policy = pyJson(p);
        }
        return sendJson(reply, 200, `{"policy":${policy},"trip_date":${JSON.stringify(tripDate)}}`);
      } catch (err) {
        if (err instanceof PyServerError) {
          return reply.code(500).header('content-type', 'text/plain; charset=utf-8').send('Internal Server Error');
        }
        throw err;
      }
    });

  // Starlette: first partial match is PUT /driver-shortage-policies/{pid} → 405 allow: PUT (verified live).
  app.head('/api/driver-shortage-policies/resolve', async (_req: FastifyRequest, reply: FastifyReply) =>
    reply.code(405).header('allow', 'PUT').header('content-type', 'application/json').send(METHOD_NOT_ALLOWED));
}
