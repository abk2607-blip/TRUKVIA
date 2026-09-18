import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7s · Fin Day Book read-only shadow.
 *
 *   GET /api/fin/day-book
 *
 * Faithful shadow of:
 *   backend/routers/fin_day_book.py::day_book (L54-121)
 *
 * STRICTLY READ-ONLY. Class-C — Python performs exactly one read:
 *   fin_txn.find(q, {_id:0, user_id:0})
 *     .sort([("txn_date", -1), ("created_at", -1)])
 *     .to_list(int(max(1, min(limit, 20000))))
 * and aggregates per-account totals in memory. The router's reproject /
 * backfill / ensure_system_accounts imports serve OTHER endpoints only.
 *
 * ── GATE-7s BINDINGS (verified against the live Python server) ───────
 *
 *   1. ORDER: auth (401) → FastAPI query validation (422: `missing`
 *      date_from / date_to, `int_parsing` / `int_parsing_size` limit — one
 *      list, declaration order) → `_active_company_id` → handler 400
 *      `date_from and date_to are required (YYYY-MM-DD)` for "" values.
 *
 *   2. FILTER: {user_id, company_id, txn_date:{$gte,$lte}, status:"active"}
 *      + truthy account_code, account_id, source_type, party_id,
 *      vehicle_id, trip_id (in that order). Repeated keys → last wins.
 *
 *   3. SORT txn_date DESC, created_at DESC. Motor `to_list(n)` sends NO
 *      server limit → read ≤ n from the unlimited sorted cursor (a
 *      `.limit()` would reorder ties). n = int(max(1, min(limit, 20000))).
 *
 *   4. TOTALS: `totals.setdefault(account_code or "", {in,out,net})`,
 *      `float(amount or 0)`, `direction == "in"` → in else out; then per
 *      account round(in,2), round(out,2), net = round(in - out, 2).
 *      float() = CPython 3.11 PyFloat_FromString (Unicode-14 tables);
 *      round = exact round-half-even (BigInt). Dict semantics: insertion
 *      order, hash merging (True == 1 == 1.0), unhashable key → 500,
 *      jsonable_encoder re-keying (bytes / datetime → str collide with
 *      equal str keys: first position, LAST value; numeric keys stay
 *      numeric → duplicate JSON keys).
 *
 *   5. BODY bytes = FastAPI jsonable_encoder + json.dumps(ensure_ascii=
 *      False, allow_nan=False, separators=(",",":")) rebuilt from typed
 *      documents (promoteValues:false). NaN / ±Infinity anywhere,
 *      unencodable BSON (ObjectId, Decimal128, Timestamp, Regex, Min/MaxKey,
 *      DBRef), invalid-UTF-8 Binary → 500 `Internal Server Error`
 *      (text/plain; charset=utf-8).
 *
 *   6. CONTENT-TYPE: every JSON response of this route is exactly
 *      `application/json` (Python JSONResponse) — sent as a Buffer so
 *      Fastify does not append a charset. Route-local; no global change.
 */

type Doc = Record<string, unknown>;

class PyServerError extends Error {}
const fail = (why: string): never => { throw new PyServerError(why); };

const bsonType = (v: unknown): string | undefined =>
  typeof v === 'object' && v !== null ? ((v as { _bsontype?: string })._bsontype) : undefined;

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

// ── Python truthiness on typed (promoteValues:false) values ─────────────
function pyTruthy(v: unknown): boolean {
  if (v === null || v === undefined) return false;
  if (typeof v === 'boolean') return v;
  if (typeof v === 'number') return v !== 0;
  if (typeof v === 'string') return v.length > 0;
  if (Array.isArray(v)) return v.length > 0;
  if (v instanceof Date) return true;
  const t = bsonType(v);
  if (t === 'Double' || t === 'Int32') return (v as { value: number }).value !== 0;
  if (t === 'Long') return !(v as { isZero(): boolean }).isZero();
  if (t === 'Binary') return (v as { length(): number }).length() > 0;
  if (t === 'Code') return (v as { code: string }).code.length > 0;
  if (t === 'BSONSymbol') return String((v as { value: string }).value).length > 0;
  if (t !== undefined) return true;
  return Object.keys(v as object).length > 0;
}

const binaryBytes = (v: unknown): Uint8Array => {
  const b = v as { buffer: Uint8Array; length(): number };
  return b.buffer.subarray(0, b.length());
};

// ── CPython 3.11 float() (local copy, Gate 7r) ──────────────────────────
const UNI14_DIGIT_ZEROS = [
  0x30, 0x660, 0x6f0, 0x7c0, 0x966, 0x9e6, 0xa66, 0xae6, 0xb66, 0xbe6, 0xc66, 0xce6, 0xd66, 0xde6, 0xe50,
  0xed0, 0xf20, 0x1040, 0x1090, 0x17e0, 0x1810, 0x1946, 0x19d0, 0x1a80, 0x1a90, 0x1b50, 0x1bb0, 0x1c40,
  0x1c50, 0xa620, 0xa8d0, 0xa900, 0xa9d0, 0xa9f0, 0xaa50, 0xabf0, 0xff10, 0x104a0, 0x10d30, 0x11066,
  0x110f0, 0x11136, 0x111d0, 0x112f0, 0x11450, 0x114d0, 0x11650, 0x116c0, 0x11730, 0x118e0, 0x11950,
  0x11c50, 0x11d50, 0x11da0, 0x16a60, 0x16ac0, 0x16b50, 0x1d7ce, 0x1d7d8, 0x1d7e2, 0x1d7ec, 0x1d7f6,
  0x1e140, 0x1e2f0, 0x1e950, 0x1fbf0,
];
const UNI14_NON_ASCII_SPACES = new Set([
  0x85, 0xa0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009,
  0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000,
]);

function uni14Decimal(cp: number): number {
  for (const z of UNI14_DIGIT_ZEROS) if (cp >= z && cp <= z + 9) return cp - z;
  return -1;
}

const isAsciiSpace = (c: string): boolean => c === ' ' || c === '\t' || c === '\n' || c === '\v' || c === '\f' || c === '\r';
const FLOAT_RE = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;
const SPECIAL_RE = /^([+-]?)(inf|infinity|nan)$/i;

function pyFloatFromString(input: string, unicode: boolean): number {
  let s = '';
  if (unicode) {
    for (const ch of input) {
      const cp = ch.codePointAt(0) as number;
      if (cp < 127) { s += ch; continue; }
      if (UNI14_NON_ASCII_SPACES.has(cp)) { s += ' '; continue; }
      const d = uni14Decimal(cp);
      if (d < 0) return fail('float: invalid character');
      s += String.fromCharCode(0x30 + d);
    }
  } else {
    s = input;
  }
  if (s.includes('_')) {
    let prev = '';
    let out = '';
    for (const c of s) {
      if (c === '_') {
        if (!isDigitCh(prev)) return fail('float: bad underscore');
      } else {
        out += c;
        if (prev === '_' && !isDigitCh(c)) return fail('float: bad underscore');
      }
      prev = c;
    }
    if (prev === '_') return fail('float: trailing underscore');
    s = out;
  }
  let a = 0;
  let z = s.length;
  while (a < z && isAsciiSpace(s[a] as string)) a++;
  while (z > a && isAsciiSpace(s[z - 1] as string)) z--;
  const body = s.slice(a, z);
  const sp = SPECIAL_RE.exec(body);
  if (sp) {
    if ((sp[2] as string).toLowerCase() === 'nan') return NaN;
    return sp[1] === '-' ? -Infinity : Infinity;
  }
  if (!FLOAT_RE.test(body)) return fail('float: not a number');
  return Number(body);
}

function pyFloat(v: unknown): number {
  if (!pyTruthy(v)) return 0;
  if (typeof v === 'boolean') return 1;
  if (typeof v === 'string') return pyFloatFromString(v, true);
  const t = bsonType(v);
  if (t === 'Double' || t === 'Int32') return (v as { value: number }).value;
  if (t === 'Long') return Number(BigInt((v as { toString(): string }).toString()));
  if (t === 'Code') return pyFloatFromString((v as { code: string }).code, true);
  if (t === 'Binary') return pyFloatFromString(Buffer.from(binaryBytes(v)).toString('latin1'), false);
  return fail('float: unsupported type');
}

// ── CPython float round(x, 2): exact round-half-even (local copy, Gate 7r) ──
function pyRound2(x: number): number {
  if (!Number.isFinite(x) || x === 0) return x;
  const neg = x < 0;
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, Math.abs(x));
  const hi = view.getUint32(0);
  const lo = view.getUint32(4);
  const expBits = (hi >>> 20) & 0x7ff;
  let mant = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  let e: number;
  if (expBits === 0) {
    e = -1074;
  } else {
    mant |= 1n << 52n;
    e = expBits - 1075;
  }
  let q: bigint;
  if (e >= 0) {
    q = (mant << BigInt(e)) * 100n;
  } else {
    const num = mant * 100n;
    const den = 1n << BigInt(-e);
    q = num / den;
    const twice = 2n * (num % den);
    if (twice > den || (twice === den && (q & 1n) === 1n)) q += 1n;
  }
  return Number(`${neg ? '-' : ''}${q.toString()}e-2`);
}

// ── Python json.dumps / FastAPI jsonable_encoder (local copy, Gate 7r) ──
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

// Python dict key identity (hash/eq) + the key's json.dumps text.
function dictKey(v: unknown): { id: string; text: string } {
  if (!pyTruthy(v)) return { id: 's:', text: '' };
  if (typeof v === 'string') return { id: `s:${v}`, text: v };
  if (typeof v === 'boolean') return { id: 'n:1', text: 'true' };
  if (v instanceof Date) return { id: `d:${v.getTime()}`, text: pyIsoformat(v) };
  const t = bsonType(v);
  if (t === 'Int32') { const n = (v as { value: number }).value; return { id: `n:${n}`, text: String(n) }; }
  if (t === 'Long') { const n = (v as { toString(): string }).toString(); return { id: `n:${n}`, text: n }; }
  if (t === 'Double') {
    const x = (v as { value: number }).value;
    const text = pyFloatRepr(x);
    return { id: Number.isInteger(x) ? `n:${BigInt(x).toString()}` : `f:${text}`, text };
  }
  if (t === 'Binary') {
    return { id: `b:${Buffer.from(binaryBytes(v)).toString('hex')}`, text: pyBytesDecode(v) };
  }
  if (t === 'BSONSymbol') { const s = String((v as { value: string }).value); return { id: `s:${s}`, text: s }; }
  return fail('account_code: unhashable or unencodable');
}

function qParam(query: Record<string, unknown>, key: string): string | undefined {
  const v = query[key];
  if (v === undefined || v === null) return undefined;
  if (Array.isArray(v)) return v.length ? String(v[v.length - 1]) : undefined;
  return String(v);
}

// JSON responses of this route are exactly `application/json` (no charset).
function sendJson(reply: FastifyReply, status: number, body: string): FastifyReply {
  return reply.code(status).header('content-type', 'application/json').send(Buffer.from(body, 'utf8'));
}

const OPTIONAL_FILTERS = ['account_code', 'account_id', 'source_type', 'party_id', 'vehicle_id', 'trip_id'] as const;

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerFinDayBookRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7s (read-only)
  app.get('/api/fin/day-book', async (req: FastifyRequest, reply: FastifyReply) => {
    // 1. Auth FIRST — locked 401 literals.
    let userId: string;
    try {
      userId = (await authenticate(req, db)).user_id;
    } catch (err) {
      if (err instanceof HttpError) return sendJson(reply, err.status, JSON.stringify({ detail: err.detail }));
      throw err;
    }

    // 2. FastAPI query validation — errors collected in declaration order.
    const query = (req.query ?? {}) as Record<string, unknown>;
    const dateFrom = qParam(query, 'date_from');
    const dateTo = qParam(query, 'date_to');
    const limitRaw = qParam(query, 'limit');
    const errors: Doc[] = [];
    const missing = (name: string): Doc => ({
      type: 'missing', loc: ['query', name], msg: 'Field required', input: null,
      url: 'https://errors.pydantic.dev/2.13/v/missing',
    });
    if (dateFrom === undefined) errors.push(missing('date_from'));
    if (dateTo === undefined) errors.push(missing('date_to'));
    let limit = 5000;
    if (limitRaw !== undefined) {
      const p = parsePydanticInt(limitRaw);
      if (!p.ok) {
        errors.push({
          type: p.type, loc: ['query', 'limit'],
          msg: p.type === 'int_parsing'
            ? 'Input should be a valid integer, unable to parse string as an integer'
            : 'Unable to parse input string as an integer, exceeded maximum size',
          input: limitRaw, url: `https://errors.pydantic.dev/2.13/v/${p.type}`,
        });
      } else {
        limit = p.value < 1n ? 1 : p.value > 20000n ? 20000 : Number(p.value);
      }
    }
    if (errors.length > 0) return sendJson(reply, 422, JSON.stringify({ detail: errors }));

    // 3. Active-company resolution BEFORE the handler's 400 (Python order).
    const cid = await activeCompanyId(req, userId, db);
    if (!dateFrom || !dateTo) {
      return sendJson(reply, 400, JSON.stringify({ detail: 'date_from and date_to are required (YYYY-MM-DD)' }));
    }

    // 4. Filter assembly — mirrors Python line-for-line.
    const filter: Doc = {
      user_id: userId, company_id: cid,
      txn_date: { $gte: dateFrom, $lte: dateTo },
      status: 'active',
    };
    for (const k of OPTIONAL_FILTERS) {
      const v = qParam(query, k);
      if (v) filter[k] = v;
    }

    try {
      // 5. Unlimited sorted cursor; stop after n documents (Motor to_list).
      const cursor = db
        .collection<Doc>('fin_txn')
        .find(filter as Filter<Doc>, { projection: { _id: 0, user_id: 0 }, promoteValues: false })
        .sort([['txn_date', -1], ['created_at', -1]]);
      const rows: Doc[] = [];
      try {
        for await (const doc of cursor) {
          rows.push(doc);
          if (rows.length >= limit) break;
        }
      } finally {
        await cursor.close();
      }

      // 6. Per-account totals — Python dict semantics.
      const totals = new Map<string, { text: string; tin: number; tout: number }>();
      for (const r of rows) {
        const key = dictKey(r['account_code']);
        let t = totals.get(key.id);
        if (!t) {
          t = { text: key.text, tin: 0, tout: 0 };
          totals.set(key.id, t);
        }
        const amt = pyFloat(r['amount']);
        if (r['direction'] === 'in') t.tin += amt;
        else t.tout += amt;
      }

      // 7. Rounding, then jsonable_encoder re-keying (first position, last value).
      const encoded = new Map<string, { text: string; json: string }>();
      for (const [id, t] of totals) {
        const tin = pyRound2(t.tin);
        const tout = pyRound2(t.tout);
        const net = pyRound2(tin - tout);
        const json = `{"in":${pyFloatRepr(tin)},"out":${pyFloatRepr(tout)},"net":${pyFloatRepr(net)}}`;
        const encId = id.startsWith('n:') || id.startsWith('f:') ? id : `s:${t.text}`;
        const prev = encoded.get(encId);
        if (prev) prev.json = json;
        else encoded.set(encId, { text: t.text, json });
      }
      const totalsJson = [...encoded.values()].map((e) => `${JSON.stringify(e.text)}:${e.json}`).join(',');

      // 8. Python-exact body (json.dumps allow_nan=False → 500 on failure).
      const body = `{"date_from":${JSON.stringify(dateFrom)},"date_to":${JSON.stringify(dateTo)},`
        + `"rows":${pyJson(rows)},"totals":{${totalsJson}},"count":${rows.length}}`;
      return sendJson(reply, 200, body);
    } catch (err) {
      if (err instanceof PyServerError) {
        return reply.code(500).header('content-type', 'text/plain; charset=utf-8').send('Internal Server Error');
      }
      throw err;
    }
  });
}
