import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7r · Fin day-closure late-entries read-only shadow.
 *
 *   GET /api/fin/day-closures/{close_date}/late-entries
 *
 * Faithful shadow of:
 *   backend/routers/fin_day_closing.py::late_entries (L274-323) + _bucket (L267-271)
 *
 * STRICTLY READ-ONLY. Class-C — Python performs exactly two reads:
 *   1. fin_day_closures.find_one({user_id, company_id, close_date}, {_id:0, closed_at:1})
 *   2. fin_txn.find({user_id, company_id, status:"active", txn_date:{$lte: close_date},
 *        created_at:{$gt: closed_at}}, {_id:0, user_id:0}).sort("txn_date", -1).to_list(5000)
 * `r["days_late"] = …` mutates only the in-memory row. Zero DB writes.
 *
 * ── GATE-7r BINDINGS (all verified against the live Python server) ───
 *
 *   1. ORDER: auth → `_parse_iso_date` 400 → `_active_company_id` → closure
 *      probe → 404 `No closure exists for <raw>` (also when the closure has
 *      no `closed_at`: projection `{}` is falsy) → fin_txn read → aggregate.
 *
 *   2. `float(r.get("amount") or 0)` — CPython 3.11 semantics:
 *        falsy → 0.0 · bool → 1.0 · int32/int64/double → float ·
 *        str (and bson Code, a str subclass) → PyFloat_FromString with the
 *        Unicode-14 decimal/space transform, underscore rules, ASCII strip,
 *        inf/infinity/nan · bson Binary (a bytes subclass) → bytes parse ·
 *        anything else (Decimal128, datetime, ObjectId, list, dict, …) → 500.
 *
 *   3. `round(x, 2)` — exact round-half-even on the binary value (CPython
 *      `double_round` via `_Py_dg_dtoa` mode 3), reproduced with BigInt
 *      arithmetic on the IEEE-754 decomposition. NOT toFixed / Math.round.
 *      `net = round(round(in) - round(out))`.
 *
 *   4. RESPONSE is produced by FastAPI `jsonable_encoder` + `json.dumps(
 *      ensure_ascii=False, allow_nan=False, separators=(",",":"))`. It is
 *      rebuilt byte-for-byte here from the TYPED documents
 *      (`promoteValues:false`): Python float repr (`5.0`, `1e+16`, `-0.0`),
 *      exact int64, naive-UTC datetime isoformat, Binary → UTF-8 decode,
 *      Code → code string. NaN/±Infinity anywhere, invalid UTF-8 Binary,
 *      ObjectId / Decimal128 / Timestamp / Regex / Min/MaxKey / DBRef →
 *      HTTP 500 `Internal Server Error` (text/plain), as Starlette does.
 *
 *   5. `by_source_type` keeps Python dict semantics: insertion order,
 *      hash-equality merging (True == 1 == 1.0, first key's text kept),
 *      unhashable keys (list, dict, Code) → 500. jsonable_encoder then
 *      re-keys by ENCODED key: bytes / datetime keys become str and merge
 *      with equal str keys (first position, last value), while numeric keys
 *      stay numeric so `1` and `"1"` serialise as duplicate JSON keys.
 *      `by_days_late_bucket` has the fixed order 0-7, 8-30, 31-90, 90+.
 *
 *   5b. Motor `to_list(5000)` → no server-side limit; read ≤5000 from the
 *      fully sorted cursor (a `.limit()` reorders txn_date ties).
 *
 *   6. days_late = max(0, (date(close_date) − date(txn_date[:10])).days);
 *      any non-str / unparsable txn_date → 0. `[:10]` slices code points.
 *
 *   7. EMPTY SEGMENT / ENCODED SLASH → 404 {"detail":"Not Found"} before auth.
 */

type Doc = Record<string, unknown>;

class PyServerError extends Error {}
const fail = (why: string): never => { throw new PyServerError(why); };

const bsonType = (v: unknown): string | undefined =>
  typeof v === 'object' && v !== null ? ((v as { _bsontype?: string })._bsontype) : undefined;

// ── CPython 3.11 C `date.fromisoformat` → proleptic ordinal (or null) ──
const DAYS_BEFORE_MONTH = [0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
const DAYS_IN_MONTH = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const isLeap = (y: number): boolean => y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
const daysInMonth = (y: number, m: number): number => (m === 2 && isLeap(y) ? 29 : (DAYS_IN_MONTH[m] as number));

function ymdToOrd(y: number, m: number, d: number): number {
  const x = y - 1;
  return x * 365 + Math.trunc(x / 4) - Math.trunc(x / 100) + Math.trunc(x / 400)
    + (DAYS_BEFORE_MONTH[m] as number) + (m > 2 && isLeap(y) ? 1 : 0) + d;
}

function ordToYear(ord: number): number {
  let n = ord - 1;
  const n400 = Math.floor(n / 146097); n -= n400 * 146097;
  const n100 = Math.floor(n / 36524); n -= n100 * 36524;
  const n4 = Math.floor(n / 1461); n -= n4 * 1461;
  const n1 = Math.floor(n / 365);
  const year = n400 * 400 + n100 * 100 + n4 * 4 + n1 + 1;
  return n1 === 4 || n100 === 4 ? year - 1 : year;
}

function pyIsoDateOrdinal(s: string): number | null {
  const b = Buffer.from(s, 'utf8');
  const len = b.length;
  if (len !== 7 && len !== 8 && len !== 10) return null;
  const at = (i: number): number => (i < len ? (b[i] as number) : 0);
  let p = 0;
  const digits = (n: number): number | null => {
    let v = 0;
    for (let k = 0; k < n; k++) {
      const t = at(p++) - 0x30;
      if (t < 0 || t > 9) return null;
      v = v * 10 + t;
    }
    return v;
  };
  const year = digits(4);
  if (year === null) return null;
  const sep = at(p) === 0x2d;
  if (sep) p++;
  if (at(p) === 0x57) {
    p++;
    const week = digits(2);
    if (week === null) return null;
    let day = 1;
    if (p < len) {
      if (sep && at(p++) !== 0x2d) return null;
      const d = digits(1);
      if (d === null) return null;
      day = d;
    }
    if (year < 1) return null;
    const jan1 = ymdToOrd(year, 1, 1);
    const firstWeekday = (jan1 + 6) % 7;
    if (week <= 0 || week >= 53) {
      if (!(week === 53 && (firstWeekday === 3 || (firstWeekday === 2 && isLeap(year))))) return null;
    }
    if (day <= 0 || day >= 8) return null;
    const ord = jan1 - firstWeekday + (firstWeekday > 3 ? 7 : 0) + (week - 1) * 7 + day - 1;
    const y = ordToYear(ord);
    return y >= 1 && y <= 9999 ? ord : null;
  }
  const month = digits(2);
  if (month === null) return null;
  if (sep && at(p++) !== 0x2d) return null;
  const day = digits(2);
  if (day === null) return null;
  if (year < 1 || year > 9999 || month < 1 || month > 12) return null;
  if (day < 1 || day > daysInMonth(year, month)) return null;
  return ymdToOrd(year, month, day);
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

// ── CPython 3.11 float() ────────────────────────────────────────────────
// Unicode 14.0 decimal-digit runs (value = cp − zero) and non-ASCII spaces
// exactly as Python 3.11 `unicodedata` / Py_UNICODE_ISSPACE define them.
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
const isAsciiDigit = (c: string | undefined): boolean => c !== undefined && c >= '0' && c <= '9';
const FLOAT_RE = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;
const SPECIAL_RE = /^([+-]?)(inf|infinity|nan)$/i;

// PyFloat_FromString: `unicode` = str input (decimal/space transform); else bytes.
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
    s = input; // bytes decoded latin-1; non-ASCII bytes never parse
  }
  // _Py_string_to_number_with_underscores (runs before whitespace strip).
  if (s.includes('_')) {
    let prev = '';
    let out = '';
    for (const c of s) {
      if (c === '_') {
        if (!isAsciiDigit(prev)) return fail('float: bad underscore');
      } else {
        out += c;
        if (prev === '_' && !isAsciiDigit(c)) return fail('float: bad underscore');
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
  return Number(body); // correctly rounded, overflow → ±Infinity (as strtod)
}

// float(r.get("amount") or 0)
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

// ── CPython float round(x, 2): exact round-half-even ───────────────────
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

// ── Python float repr / json.dumps float ────────────────────────────────
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

// datetime.isoformat() of the naive-UTC datetime PyMongo decodes.
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

// FastAPI jsonable_encoder + json.dumps(ensure_ascii=False, allow_nan=False).
// Plain JS numbers are values this handler computed and are Python ints.
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
function sourceKey(v: unknown): { id: string; text: string } {
  if (!pyTruthy(v)) return { id: 's:', text: '' };
  if (typeof v === 'string') return { id: `s:${v}`, text: v };
  if (typeof v === 'boolean') return { id: 'n:1', text: 'true' };
  if (v instanceof Date) return { id: `d:${v.getTime()}`, text: pyIsoformat(v) };
  const t = bsonType(v);
  if (t === 'Int32') { const n = (v as { value: number }).value; return { id: `n:${n}`, text: String(n) }; }
  if (t === 'Long') { const n = (v as { toString(): string }).toString(); return { id: `n:${n}`, text: n }; }
  if (t === 'Double') {
    const x = (v as { value: number }).value;
    const text = pyFloatRepr(x); // NaN / ±Infinity key → json.dumps ValueError → 500
    return { id: Number.isInteger(x) ? `n:${BigInt(x).toString()}` : `f:${text}`, text };
  }
  if (t === 'Binary') {
    const bytes = binaryBytes(v);
    return { id: `b:${Buffer.from(bytes).toString('hex')}`, text: pyBytesDecode(v) };
  }
  if (t === 'BSONSymbol') { const s = String((v as { value: string }).value); return { id: `s:${s}`, text: s }; }
  // list / dict / Code are unhashable; ObjectId, Decimal128, … are not JSON-encodable.
  return fail('source_type: unhashable or unencodable');
}

function bucket(days: number): '0-7' | '8-30' | '31-90' | '90+' {
  if (days <= 7) return '0-7';
  if (days <= 30) return '8-30';
  if (days <= 90) return '31-90';
  return '90+';
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerFinDayClosureLateEntriesRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7r (read-only)
  app.get('/api/fin/day-closures/:close_date/late-entries', async (req: FastifyRequest, reply: FastifyReply) => {
    const closeDate = (req.params as { close_date: string }).close_date;

    // 0. Starlette never routes an empty segment or decoded "/" into a param.
    if (closeDate === '' || closeDate.includes('/')) {
      reply.code(404);
      return { detail: 'Not Found' };
    }

    // 1. Auth FIRST — locked 401 literals.
    let userId: string;
    try {
      userId = (await authenticate(req, db)).user_id;
    } catch (err) {
      if (err instanceof HttpError) {
        reply.code(err.status);
        return { detail: err.detail };
      }
      throw err;
    }

    // 2. `_parse_iso_date(close_date)`.
    const closeOrd = pyIsoDateOrdinal(closeDate);
    if (closeOrd === null) {
      reply.code(400);
      return { detail: 'close_date must be ISO YYYY-MM-DD' };
    }

    // 3. Active-company resolution (locked helper).
    const cid = await activeCompanyId(req, userId, db);

    // 4. Closure probe — `if not closure` on the {closed_at:1} projection.
    const closure = await db
      .collection<Doc>('fin_day_closures')
      .findOne(
        { user_id: userId, company_id: cid, close_date: closeDate } as Filter<Doc>,
        { projection: { _id: 0, closed_at: 1 } },
      );
    if (!closure || Object.keys(closure).length === 0) {
      reply.code(404);
      return { detail: `No closure exists for ${closeDate}` };
    }
    const closedAt = pyTruthy(closure['closed_at']) ? closure['closed_at'] : '';

    try {
      // 5. Late legs — typed values so float / key / JSON rules are exact.
      //    Motor `to_list(5000)` sends NO server-side limit (a limit turns the
      //    blocking sort into a top-k sort and reorders txn_date ties); it
      //    stops reading after 5000 documents. Reproduced here.
      const cursor = db
        .collection<Doc>('fin_txn')
        .find(
          {
            user_id: userId, company_id: cid, status: 'active',
            txn_date: { $lte: closeDate },
            created_at: { $gt: closedAt },
          } as Filter<Doc>,
          { projection: { _id: 0, user_id: 0 }, promoteValues: false },
        )
        .sort([['txn_date', -1]]);
      const rows: Doc[] = [];
      try {
        for await (const doc of cursor) {
          rows.push(doc);
          if (rows.length >= 5000) break;
        }
      } finally {
        await cursor.close();
      }

      // 6. Aggregate exactly as the Python loop.
      const bySource = new Map<string, { text: string; count: number }>();
      const byBucket = { '0-7': 0, '8-30': 0, '31-90': 0, '90+': 0 };
      let tin = 0;
      let tout = 0;
      for (const r of rows) {
        const key = sourceKey(r['source_type']);
        const slot = bySource.get(key.id);
        if (slot) slot.count += 1;
        else bySource.set(key.id, { text: key.text, count: 1 });

        let daysLate = 0;
        const txnDate = r['txn_date'];
        if (typeof txnDate === 'string') {
          const tdOrd = pyIsoDateOrdinal(Array.from(txnDate).slice(0, 10).join(''));
          if (tdOrd !== null) daysLate = closeOrd - tdOrd;
        }
        r['days_late'] = Math.max(0, daysLate);
        byBucket[bucket(r['days_late'] as number)] += 1;

        const amt = pyFloat(r['amount']);
        if (r['direction'] === 'in') tin += amt;
        else tout += amt;
      }
      const totalIn = pyRound2(tin);
      const totalOut = pyRound2(tout);
      const totalNet = pyRound2(totalIn - totalOut);

      // 7. jsonable_encoder re-keys the dict by ENCODED key: str / bytes /
      //    datetime keys all become str and collide (first position, last
      //    value); int / float / bool keys stay non-str and are stringified
      //    later by json.dumps (textual duplicates remain).
      const encoded = new Map<string, { text: string; count: number }>();
      for (const [id, s] of bySource) {
        const encId = id.startsWith('n:') || id.startsWith('f:') ? id : `s:${s.text}`;
        const prev = encoded.get(encId);
        if (prev) prev.count = s.count;
        else encoded.set(encId, { text: s.text, count: s.count });
      }

      // 8. Python-exact JSON body (json.dumps allow_nan=False → 500 on failure).
      const sourceJson = [...encoded.values()].map((s) => `${JSON.stringify(s.text)}:${s.count}`).join(',');
      const body =
        `{"close_date":${JSON.stringify(closeDate)},"count":${rows.length},`
        + `"totals":{"in":${pyFloatRepr(totalIn)},"out":${pyFloatRepr(totalOut)},"net":${pyFloatRepr(totalNet)}},`
        + `"by_source_type":{${sourceJson}},`
        + `"by_days_late_bucket":{"0-7":${byBucket['0-7']},"8-30":${byBucket['8-30']},`
        + `"31-90":${byBucket['31-90']},"90+":${byBucket['90+']}},`
        + `"rows":${pyJson(rows)}}`;
      return reply.code(200).type('application/json').send(body);
    } catch (err) {
      if (err instanceof PyServerError) {
        return reply.code(500).type('text/plain; charset=utf-8').send('Internal Server Error');
      }
      throw err;
    }
  });
}
