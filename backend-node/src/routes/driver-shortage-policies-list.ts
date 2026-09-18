import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import { BSONRegExp, Long, type Db, type Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-8d · Driver shortage-policy list read-only shadow.
 *
 *   GET /api/driver-shortage-policies?q=&active_only=&limit=&offset=
 *
 * Faithful shadow of:
 *   backend/routers/driver_shortage_policies.py::list_policies (L186-216)
 *
 * Python (verbatim):
 * ```
 * @router.get("/driver-shortage-policies")
 * async def list_policies(request: Request, user=Depends(get_current_user),
 *                         q: str = "", active_only: bool = False,
 *                         limit: int = 50, offset: int = 0):
 *     cid = await _active_company_id(request, user)
 *     mongo_q: dict = {"user_id": user["user_id"], "company_id": cid}
 *     if active_only:
 *         mongo_q["active"] = True
 *     if q and q.strip():
 *         import re as _re
 *         pat = _re.compile(_re.escape(q.strip()), _re.IGNORECASE)
 *         mongo_q["$or"] = [{"name": pat}, {"remarks": pat}, {"product_category": pat}]
 *     total = await db.driver_shortage_policies.count_documents(mongo_q)
 *     limit = min(max(1, int(limit or 50)), 500)
 *     offset = max(0, int(offset or 0))
 *     docs = await (db.driver_shortage_policies.find(mongo_q, {"_id": 0})
 *                   .sort([("effective_from", -1), ("version", -1)])
 *                   .skip(offset).limit(limit)
 *                   .to_list(limit))
 *     return {"items": docs, "total": total, "limit": limit, "offset": offset}
 * ```
 *
 * STRICTLY READ-ONLY. count_documents + one find; no write / backfill / seed.
 *
 * ── GATE-8d BINDINGS ────────────────────────────────────────────────
 *
 *   1. ORDER: auth (locked 401 literals) → FastAPI query validation (422,
 *      errors in declaration order q, active_only, limit, offset) →
 *      `_active_company_id` → count → find.
 *
 *   2. PARAMS (Starlette-exact decoding, local copy of Gate 7v; repeated key
 *      → LAST value):
 *        q           str,  default ""  — never invalid
 *        active_only bool, default False — pydantic-core str→bool: exact,
 *                    case-insensitive 1/0/true/false/t/f/yes/no/y/n/on/off,
 *                    NO trimming; anything else → `bool_parsing`
 *        limit/offset int, defaults 50/0 — pydantic-core str→int (local
 *                    copy, Gate 7m/7s): `int_parsing` / `int_parsing_size`
 *
 *   3. FILTER (key order): {user_id, company_id} [+ active: true when
 *      active_only] [+ $or [{name}, {remarks}, {product_category}] when
 *      q.strip() (CPython str.isspace set) is non-empty]. The pattern is
 *      CPython `re.escape(q.strip())` sent as a BSON regex with options "iu"
 *      (PyMongo encodes re.IGNORECASE + the implicit re.UNICODE).
 *
 *   4. count_documents(filter) → total (before the clamp). Then
 *      limit = min(max(1, limit or 50), 500), offset = max(0, offset or 0)
 *      on arbitrary-precision integers.
 *
 *   5. find(filter, {_id: 0}) sort effective_from -1, version -1, SERVER-SIDE
 *      skip + limit (exactly as Motor sends them — profiler-compared; skip
 *      omitted when 0). skip > int32 is sent as an exact BSON Int64 like
 *      PyMongo (raw find command — the cursor API only takes a JS number).
 *      An offset > 2^63-1 cannot be BSON-encoded by PyMongo → unhandled
 *      OverflowError → 500 after the count; reproduced.
 *
 *   6. RESPONSE {"items", "total", "limit", "offset"} — JSON from typed
 *      documents (promoteValues:false); NaN / unencodable BSON → 500
 *      `Internal Server Error` (text/plain; charset=utf-8).
 *
 *   7. CONTENT-TYPE exactly `application/json` (Buffer payload).
 *
 *   8. HEAD: Starlette's first partial match on this path is this GET route
 *      → 405 + `allow: GET` before auth (verified live). Fastify auto-HEAD
 *      disabled for this route and the 405 reproduced explicitly.
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

// ── Pydantic 2.13.4 / pydantic-core 2.46.4 str→int (local copy, Gate 7m) ──
const RUST_WS = '\\u0009-\\u000D\\u0020\\u0085\\u00A0\\u1680\\u2000-\\u200A\\u2028\\u2029\\u202F\\u205F\\u3000';
const RUST_TRIM_RE = new RegExp(`^[${RUST_WS}]+|[${RUST_WS}]+$`, 'g');
type StrictInt = { kind: 'ok'; value: bigint } | { kind: 'size' } | { kind: 'invalid' };
const isDigitCh = (c: string | undefined): boolean => c !== undefined && c >= '0' && c <= '9';

function jiterStrictInt(s: string): StrictInt {
  let i = 0;
  if (s[0] === '-') i = 1;
  const first = s[i];
  if (first === '0') return i + 1 === s.length ? { kind: 'ok', value: 0n } : { kind: 'invalid' };
  if (first === undefined || first < '1' || first > '9') return { kind: 'invalid' };
  let j = i;
  while (isDigitCh(s[j])) j++;
  if (j > 4300) return { kind: 'size' };
  if (j !== s.length) return { kind: 'invalid' };
  return { kind: 'ok', value: BigInt(s) };
}

function stripLeadingZeros(s: string): string | null {
  const c0 = s[0];
  if (c0 === undefined) return null;
  if (c0 !== '0') return (c0 >= '1' && c0 <= '9') || c0 === '-' ? s : null;
  for (let i = 1; i < s.length; i++) {
    const c = s[i] as string;
    if (c === '0' || c === '_') continue;
    if ((c >= '1' && c <= '9') || c === '-') return s.slice(i);
    if (c === '.') return s.slice(i - 1);
    return null;
  }
  return s.slice(s.length - 1);
}

function stripUnderscores(s: string): string | null {
  if (s.startsWith('_') || s.endsWith('_') || !s.includes('_') || s.includes('__')) return null;
  return s.replace(/_/g, '');
}

function cleanIntStr(orig: string): string | null {
  let s = orig.replace(RUST_TRIM_RE, '');
  if (s.startsWith('+')) {
    const suffix = s.slice(1);
    if (suffix.startsWith('-')) return null;
    s = suffix;
  }
  let negative = false;
  if (s.startsWith('-')) {
    const suffix = s.slice(1);
    if (suffix.startsWith('-') || suffix.startsWith('+')) return null;
    negative = true;
    s = suffix;
  }
  const z = stripLeadingZeros(s);
  if (z === null) return null;
  s = z;
  const dot = s.indexOf('.');
  if (dot !== -1) {
    const decimal = s.slice(dot + 1);
    if (decimal.length > 0 && /^0+$/.test(decimal)) s = s.slice(0, dot);
  }
  const stripped = stripUnderscores(s);
  if (stripped !== null) return negative ? `-${stripped}` : stripped;
  if (orig.length === s.length) return null;
  return negative ? `-${s}` : s;
}

function parsePydanticInt(raw: string): { ok: true; value: bigint } | { ok: false; type: 'int_parsing' | 'int_parsing_size' } {
  const fast = jiterStrictInt(raw);
  if (fast.kind === 'ok') return { ok: true, value: fast.value };
  if (fast.kind === 'size') return { ok: false, type: 'int_parsing_size' };
  const cleaned = cleanIntStr(raw);
  if (cleaned === null) return { ok: false, type: 'int_parsing' };
  const slow = jiterStrictInt(cleaned);
  return slow.kind === 'ok' ? { ok: true, value: slow.value } : { ok: false, type: 'int_parsing' };
}

// ── pydantic-core str→bool (verified against pydantic 2.13.4) ────────────
const BOOL_TRUE = new Set(['1', 'on', 't', 'true', 'y', 'yes']);
const BOOL_FALSE = new Set(['0', 'off', 'f', 'false', 'n', 'no']);
function parsePydanticBool(raw: string): boolean | null {
  const s = raw.toLowerCase();
  if (s.length > 5) return null; // longest accepted token is "false"
  if (BOOL_TRUE.has(s)) return true;
  if (BOOL_FALSE.has(s)) return false;
  return null;
}

// ── CPython 3.11 str.strip() / re.escape ─────────────────────────────────
const PY_SPACE = new Set<number>([
  0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0,
  0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007,
  0x2008, 0x2009, 0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000,
]);

function pyStrip(s: string): string {
  const cps = [...s];
  let a = 0;
  let b = cps.length;
  while (a < b && PY_SPACE.has((cps[a] as string).codePointAt(0) as number)) a++;
  while (b > a && PY_SPACE.has((cps[b - 1] as string).codePointAt(0) as number)) b--;
  return cps.slice(a, b).join('');
}

// re._special_chars_map = {i: '\\' + chr(i) for i in b'()[]{}?*+-|^$\\.&~# \t\n\r\v\f'}
const PY_RE_SPECIAL = new Set('()[]{}?*+-|^$\\.&~# \t\n\r\v\f');
const pyReEscape = (s: string): string => [...s].map((c) => (PY_RE_SPECIAL.has(c) ? `\\${c}` : c)).join('');

// JSON responses of this route are exactly `application/json` (no charset).
const sendJson = (reply: FastifyReply, status: number, body: string): FastifyReply =>
  reply.code(status).header('content-type', 'application/json').send(Buffer.from(body, 'utf8'));
const sendServerError = (reply: FastifyReply): FastifyReply =>
  reply.code(500).header('content-type', 'text/plain; charset=utf-8').send('Internal Server Error');

const METHOD_NOT_ALLOWED = Buffer.from('{"detail":"Method Not Allowed"}', 'utf8');
const INT64_MAX = (1n << 63n) - 1n;
const INT32_MAX = 2147483647n;

// Raw `find` with an exact BSON Int64 skip (same fields as the cursor path), then getMore.
async function findWithInt64Skip(db: Db, filter: Doc, skip: bigint, limit: number): Promise<Doc[]> {
  const opts = { promoteValues: false } as const;
  type CursorReply = { cursor: { id: Long; firstBatch?: Doc[]; nextBatch?: Doc[] } };
  const first = (await db.command({
    find: 'driver_shortage_policies', filter, sort: { effective_from: -1, version: -1 },
    projection: { _id: 0 }, skip: Long.fromBigInt(skip), limit,
  }, opts)) as unknown as CursorReply;
  const docs: Doc[] = [...(first.cursor.firstBatch ?? [])];
  let id = first.cursor.id;
  try {
    while (!id.isZero() && docs.length < limit) {
      const more = (await db.command({ getMore: id, collection: 'driver_shortage_policies' }, opts)) as unknown as CursorReply;
      docs.push(...(more.cursor.nextBatch ?? []));
      id = more.cursor.id;
    }
  } finally {
    if (!id.isZero()) await db.command({ killCursors: 'driver_shortage_policies', cursors: [id] }).catch(() => undefined);
  }
  return docs.slice(0, limit);
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerDriverShortagePoliciesListRoute(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-8d (read-only)
  app.get('/api/driver-shortage-policies', { exposeHeadRoute: false },
    async (req: FastifyRequest, reply: FastifyReply) => {
      // 1. Auth FIRST — locked 401 literals.
      let userId: string;
      try {
        userId = (await authenticate(req, db)).user_id;
      } catch (err) {
        if (err instanceof HttpError) return sendJson(reply, err.status, JSON.stringify({ detail: err.detail }));
        throw err;
      }

      // 2. FastAPI query validation — errors in declaration order.
      const rawUrl = req.raw.url ?? '';
      const q = pyQueryLast(rawUrl, 'q') ?? '';
      const activeRaw = pyQueryLast(rawUrl, 'active_only');
      const limitRaw = pyQueryLast(rawUrl, 'limit');
      const offsetRaw = pyQueryLast(rawUrl, 'offset');
      const errors: Doc[] = [];
      let activeOnly = false;
      if (activeRaw !== undefined) {
        const b = parsePydanticBool(activeRaw);
        if (b === null) {
          errors.push({
            type: 'bool_parsing', loc: ['query', 'active_only'],
            msg: 'Input should be a valid boolean, unable to interpret input', input: activeRaw,
            url: 'https://errors.pydantic.dev/2.13/v/bool_parsing',
          });
        } else {
          activeOnly = b;
        }
      }
      const intParam = (name: string, raw: string | undefined, dflt: bigint): bigint => {
        if (raw === undefined) return dflt;
        const p = parsePydanticInt(raw);
        if (p.ok) return p.value;
        errors.push({
          type: p.type, loc: ['query', name],
          msg: p.type === 'int_parsing'
            ? 'Input should be a valid integer, unable to parse string as an integer'
            : 'Unable to parse input string as an integer, exceeded maximum size',
          input: raw, url: `https://errors.pydantic.dev/2.13/v/${p.type}`,
        });
        return dflt;
      };
      const limitIn = intParam('limit', limitRaw, 50n);
      const offsetIn = intParam('offset', offsetRaw, 0n);
      if (errors.length > 0) return sendJson(reply, 422, JSON.stringify({ detail: errors }));

      // 3. Active-company resolution (locked helper).
      const cid = await activeCompanyId(req, userId, db);

      // 4. Filter — Python dict insertion order.
      const filter: Doc = { user_id: userId, company_id: cid };
      if (activeOnly) filter['active'] = true;
      const stripped = pyStrip(q);
      if (q && stripped) {
        const pat = new BSONRegExp(pyReEscape(stripped), 'iu');
        filter['$or'] = [{ name: pat }, { remarks: pat }, { product_category: pat }];
      }

      const coll = db.collection<Doc>('driver_shortage_policies');
      try {
        // 5. READ #1 — count_documents on the unclamped filter.
        const total = await coll.countDocuments(filter as Filter<Doc>);

        // 6. Python clamps on arbitrary-precision ints.
        let limit = limitIn === 0n ? 50n : limitIn;
        limit = limit < 1n ? 1n : limit > 500n ? 500n : limit;
        let offset = offsetIn === 0n ? 0n : offsetIn;
        if (offset < 0n) offset = 0n;
        // PyMongo cannot BSON-encode skip > int64 → OverflowError → 500 (no find sent).
        if (offset > INT64_MAX) return sendServerError(reply);

        // 7. READ #2 — find with server-side skip + limit (Motor command shape).
        let docs: Doc[];
        if (offset <= INT32_MAX) {
          let cursor = coll
            .find(filter as Filter<Doc>, { projection: { _id: 0 }, promoteValues: false })
            .sort({ effective_from: -1, version: -1 });
          if (offset > 0n) cursor = cursor.skip(Number(offset));
          docs = await cursor.limit(Number(limit)).toArray();
        } else {
          // PyMongo sends skip > int32 as BSON int64; the driver's cursor API only
          // accepts a JS number (→ BSON double, rounded above 2^53). Issue the
          // identical find command with an exact Int64 skip, then drain getMore.
          docs = await findWithInt64Skip(db, filter, offset, Number(limit));
        }

        return sendJson(reply, 200,
          `{"items":${pyJson(docs)},"total":${total},"limit":${limit},"offset":${offset}}`);
      } catch (err) {
        if (err instanceof PyServerError) return sendServerError(reply);
        throw err;
      }
    });

  // Starlette first partial match = this GET route → HEAD 405 allow: GET before auth (verified live).
  app.head('/api/driver-shortage-policies', async (_req: FastifyRequest, reply: FastifyReply) =>
    reply.code(405).header('allow', 'GET').header('content-type', 'application/json').send(METHOD_NOT_ALLOWED));
}
