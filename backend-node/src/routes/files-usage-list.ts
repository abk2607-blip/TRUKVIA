import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7j · Files-usage summary read-only shadow.
 *
 *   GET /api/files/usage
 *
 * Faithful shadow of:
 *   backend/routers/files.py::file_usage (L94-109)
 *
 * Python (verbatim):
 * ```
 * @router.get("/files/usage")
 * async def file_usage(user=Depends(get_current_user)):
 *     docs = await db.files.find(
 *         {"user_id": user["user_id"], "is_deleted": False},
 *         {"_id": 0, "size": 1, "category": 1}
 *     ).to_list(5000)
 *     total = sum(int(d.get("size", 0) or 0) for d in docs)
 *     by_cat = {}
 *     for d in docs:
 *         c = d.get("category", "general")
 *         by_cat[c] = by_cat.get(c, 0) + int(d.get("size", 0) or 0)
 *     limit = 500 * 1024 * 1024  # 500MB soft cap
 *     return {
 *         "total_bytes": total,
 *         "limit_bytes": limit,
 *         "pct": round(min(100, total / limit * 100), 2) if limit else 0,
 *         "file_count": len(docs),
 *         "by_category": by_cat,
 *     }
 * ```
 *
 * ── SEMANTICS PRESERVED VERBATIM ────────────────────────────────────
 *   * `int(d.get("size", 0) or 0)` — missing/None/0/False/"" → 0; numbers
 *     truncate toward zero (matches Python `int(float)`). Fixtures use
 *     non-negative int sizes; symbolic behavior mirrored for parity.
 *   * `d.get("category", "general")` — KEY-BASED default. Missing key →
 *     "general". Key PRESENT with value `null` / `""` / other string →
 *     that literal value is used as the by_cat key. NOT `d.get(k) or default`.
 *   * `by_cat` insertion-order preserved (dict since Py 3.7; V8 objects
 *     preserve string-key insertion order). No sort applied.
 *   * `limit_bytes` = `500 * 1024 * 1024` = 524288000 (constant int).
 *   * `pct` = round(min(100, total/limit*100), 2) — limit is always
 *     truthy so the `else 0` branch never executes. Python 3 division
 *     `/` is float; `min(100, float)` returns 100 (int) when capped or
 *     the float otherwise; `round(int, 2)` returns int, `round(float, 2)`
 *     returns float. Gate 9e renders both exactly (int `100`, float `x.0`).
 *
 * ── USER-ONLY SCOPE (Gate 7i axis carried forward) ──────────────────
 *   NO `activeCompanyId`. Base filter is `{user_id, is_deleted: false}`.
 *   Same-user rows across arbitrary `company_id` values remain visible;
 *   cross-user rows excluded.
 *
 * Zero writer hook / audit / backfill / recompute / FinTxn / counters /
 * idempotency / cross-collection reads on the GET path. No object-store
 * call. Files writers + object-store egress remain Python-authoritative.
 */

/*
 * ── GATE 9e · EXACT PYTHON REPRESENTATION (verified live) ─────────────
 *   The response is rendered byte-for-byte like FastAPI's JSONResponse
 *   (`json.dumps(..., ensure_ascii=False, separators=(",", ":"))`):
 *   * `pct`: `min(100, total / limit * 100)` is the INT 100 when the float
 *     is >= 100, otherwise a float; `round(float, 2)` is CPython's correctly
 *     rounded half-even; floats render with Python `repr` (`0.0`, `100.0`,
 *     `-0.0`, `2.35`).
 *   * `int(v or 0)`: bool True → 1; int32/int64 exact (BigInt totals);
 *     double truncates, NaN/inf → ValueError/OverflowError → 500; str via
 *     Python `int()` (whitespace strip, sign, `_` separators, Unicode
 *     digits, 4300-digit limit) else ValueError → 500; other truthy BSON
 *     values (Decimal128, ObjectId, datetime, non-empty list/dict …) →
 *     TypeError → 500.
 *   * `by_category` is a Python dict: insertion order kept; keys merge on
 *     Python hash/equality (True == 1 == 1.0, "1" distinct); the FIRST
 *     key object is rendered (`null`, `true`, `1`, `1.0`, iso datetime);
 *     unhashable (list/dict) or NaN/inf keys → 500.
 *   * Motor `to_list(5000)` sends no server-side limit: iterate, stop at 5000.
 */

type Bson = { _bsontype?: string; value?: unknown; toString?: () => string } & Record<string, unknown>;

class PyServerError extends Error {}

// CPython `int(str)` whitespace: non-ASCII Unicode spaces are first mapped to ' '
// (_PyUnicode_TransformDecimalAndSpaceToASCII), then only ASCII whitespace is
// stripped. So \x1c-\x1f are NOT stripped; \x85, \xa0, 　 … are; U+FEFF is not.
const PY_WS = '\\t\\n\\x0b\\x0c\\r\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const PY_STR_STRIP = new RegExp(`^[${PY_WS}]+|[${PY_WS}]+$`, 'g');
const ND = /^\p{Nd}$/u;
const isNd = (cp: number): boolean => cp >= 0 && cp <= 0x10ffff && ND.test(String.fromCodePoint(cp));

// Unicode Nd digits come in aligned runs of ten starting at value 0.
function ndValue(cp: number): number {
  let start = cp;
  while (isNd(start - 1)) start--;
  return (cp - start) % 10;
}

// CPython 3.11 `int(str)` (base 10).
function pyIntFromStr(raw: string): bigint {
  const s = raw.replace(PY_STR_STRIP, '');
  const m = /^([+-]?)(\p{Nd}+(?:_\p{Nd}+)*)$/u.exec(s);
  if (!m) throw new PyServerError('invalid literal for int() with base 10');
  const digits = [...(m[2] as string).replace(/_/g, '')].map((ch) => {
    const cp = ch.codePointAt(0) as number;
    return cp >= 0x30 && cp <= 0x39 ? cp - 0x30 : ndValue(cp);
  });
  if (digits.length > 4300) throw new PyServerError('Exceeds the limit (4300 digits) for integer string conversion');
  const v = BigInt(digits.join(''));
  return m[1] === '-' ? -v : v;
}

// CPython `int(bytes)`: ASCII whitespace strip; ASCII digits / sign / `_` only.
function pyIntFromBytes(buf: Uint8Array): bigint {
  const s = Buffer.from(buf).toString('latin1').replace(/^[ \t\n\r\x0b\x0c]+|[ \t\n\r\x0b\x0c]+$/g, '');
  const m = /^([+-]?)([0-9]+(?:_[0-9]+)*)$/.exec(s);
  if (!m) throw new PyServerError('invalid literal for int() with base 10');
  const digits = (m[2] as string).replace(/_/g, '');
  if (digits.length > 4300) throw new PyServerError('Exceeds the limit (4300 digits) for integer string conversion');
  const v = BigInt(digits);
  return m[1] === '-' ? -v : v;
}

// Python `int(v or 0)` over a PyMongo-decoded BSON value.
function pyIntOrZero(v: unknown): bigint {
  if (v === undefined || v === null || v === false || v === '') return 0n;
  if (v === true) return 1n;
  if (typeof v === 'string') return pyIntFromStr(v);
  if (typeof v === 'number') {
    // Only from promoted readers (e.g. unit-test fakes); the live read keeps BSON types.
    if (v === 0) return 0n;
    if (!Number.isFinite(v)) throw new PyServerError('cannot convert float NaN/infinity to integer');
    return BigInt(Math.trunc(v));
  }
  if (Array.isArray(v)) {
    if (v.length === 0) return 0n; // [] is falsy
    throw new PyServerError('int() argument must be a string, a bytes-like object or a real number, not list');
  }
  const b = v as Bson;
  switch (b._bsontype) {
    case 'Int32':
      return BigInt(b.value as number);
    case 'Long':
      return BigInt((b.toString as () => string).call(b));
    case 'Double': {
      const x = b.value as number;
      if (x === 0) return 0n; // 0.0 / -0.0 are falsy
      if (!Number.isFinite(x)) throw new PyServerError('cannot convert float NaN/infinity to integer');
      return BigInt(Math.trunc(x));
    }
    case 'Binary': {
      const bin = b as unknown as { buffer: Uint8Array; position: number };
      const buf = bin.buffer.subarray(0, bin.position);
      return buf.length === 0 ? 0n : pyIntFromBytes(buf); // b"" is falsy
    }
    case 'Code': {
      const code = String((b as unknown as { code: string }).code);
      return code === '' ? 0n : pyIntFromStr(code); // PyMongo Code is a str
    }
    default:
      break;
  }
  if (typeof v === 'object' && b._bsontype === undefined && !(v instanceof Date) && Object.keys(v).length === 0) {
    return 0n; // {} is falsy
  }
  throw new PyServerError('int() argument must be a string, a bytes-like object or a real number');
}

// Python float repr (`float_repr_style == 'short'`).
function pyFloatRepr(x: number): string {
  if (Object.is(x, -0)) return '-0.0';
  if (x === 0) return '0.0';
  const [mant, expStr] = x.toExponential().split('e') as [string, string];
  const exp = Number(expStr);
  const neg = mant.startsWith('-');
  const digits = mant.replace('-', '').replace('.', '');
  let out: string;
  if (exp >= -4 && exp < 16) {
    if (exp >= 0) {
      const intPart = digits.slice(0, exp + 1).padEnd(exp + 1, '0');
      const frac = digits.slice(exp + 1);
      out = `${intPart}.${frac || '0'}`;
    } else {
      out = `0.${'0'.repeat(-exp - 1)}${digits}`;
    }
  } else {
    const m = digits.length > 1 ? `${digits[0] as string}.${digits.slice(1)}` : digits;
    out = `${m}e${exp < 0 ? '-' : '+'}${String(Math.abs(exp)).padStart(2, '0')}`;
  }
  return neg ? `-${out}` : out;
}

// CPython `int / int` true division: the exactly rounded (half-even) double.
function pyTrueDiv(a: bigint, b: bigint): number {
  if (a === 0n) return 0;
  const neg = a < 0n !== b < 0n;
  const x = a < 0n ? -a : a;
  const y = b < 0n ? -b : b;
  if (x <= 2n ** 53n && y <= 2n ** 53n) return (neg ? -1 : 1) * (Number(x) / Number(y));
  const shift = 55 - (x.toString(2).length - y.toString(2).length);
  const num = shift > 0 ? x << BigInt(shift) : x;
  const den = shift < 0 ? y << BigInt(-shift) : y;
  let q = num / den;
  const sticky = num % den !== 0n;
  const extra = q.toString(2).length - 53;
  const rem = q & ((1n << BigInt(extra)) - 1n);
  q >>= BigInt(extra);
  const half = 1n << BigInt(extra - 1);
  if (rem > half || (rem === half && (sticky || (q & 1n) === 1n))) q += 1n;
  const v = Number(q) * 2 ** (extra - shift);
  return neg ? -v : v;
}

// CPython `round(x, 2)` for a finite float: correctly rounded, ties half-even.
function pyRound2(x: number): number {
  if (!Number.isFinite(x) || Math.abs(x) >= 1e21) return x;
  // Exact decimal ties exist only for x = k/8 with odd k (…125 / …375 / …625 / …875).
  if (Number.isInteger(x * 8) && !Number.isInteger(x * 4)) {
    const n = x * 100; // exact: an odd multiple of 12.5
    const lo = Math.floor(n);
    const pick = lo % 2 === 0 ? lo : lo + 1;
    const a = Math.abs(pick);
    const r = parseFloat(`${pick < 0 ? '-' : ''}${Math.floor(a / 100)}.${String(a % 100).padStart(2, '0')}`);
    return r === 0 && x < 0 ? -0 : r;
  }
  const r = parseFloat(x.toFixed(2));
  return r === 0 && x < 0 ? -0 : r;
}

// A by_category key as Python sees it: equality class + rendered JSON key.
function pyDictKey(v: unknown): { eq: string; json: string } {
  if (v === undefined) return { eq: 's:general', json: '"general"' };
  if (v === null) return { eq: 'none', json: '"null"' };
  if (typeof v === 'string') return { eq: `s:${v}`, json: JSON.stringify(v) };
  if (v === true) return { eq: 'n:1', json: '"true"' };
  if (v === false) return { eq: 'n:0', json: '"false"' };
  if (typeof v === 'number') {
    // Only from promoted readers (unit-test fakes): integral → int, else float.
    if (!Number.isFinite(v)) throw new PyServerError('Out of range float values are not JSON compliant');
    return Number.isInteger(v) ? { eq: `n:${BigInt(v).toString()}`, json: `"${String(v)}"` }
      : { eq: `f:${String(v)}`, json: `"${pyFloatRepr(v)}"` };
  }
  const b = v as Bson;
  if (b._bsontype === 'Int32') return { eq: `n:${String(b.value)}`, json: `"${String(b.value)}"` };
  if (b._bsontype === 'Long') {
    const s = (b.toString as () => string).call(b);
    return { eq: `n:${s}`, json: `"${s}"` };
  }
  if (b._bsontype === 'Double') {
    const x = b.value as number;
    if (!Number.isFinite(x)) throw new PyServerError('Out of range float values are not JSON compliant');
    const eq = Number.isInteger(x) ? `n:${BigInt(x).toString()}` : `f:${String(x)}`;
    return { eq, json: `"${pyFloatRepr(x)}"` };
  }
  if (v instanceof Date) {
    // PyMongo naive datetime → jsonable_encoder `isoformat()`.
    const iso = v.toISOString().slice(0, 23);
    const s = v.getUTCMilliseconds() === 0 ? iso.slice(0, 19) : `${iso}000`;
    return { eq: `d:${String(v.getTime())}`, json: JSON.stringify(s) };
  }
  throw new PyServerError('unhashable or unsupported by_category key');
}

export async function registerFilesUsageListRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7j (read-only, USER-SCOPED)
  app.get('/api/files/usage', async (req: FastifyRequest, reply: FastifyReply) => {
    // 1. Auth (401 short-circuit).
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

    // 2. USER-ONLY read (no activeCompanyId, no company_id predicate).
    //    Exact Python filter + projection; Motor `to_list(5000)` = no server
    //    limit, stop after 5000. BSON types kept (promoteValues: false).
    const cursor = db
      .collection<Bson>('files')
      .find(
        { user_id: userId, is_deleted: false } as Filter<Bson>,
        { projection: { _id: 0, size: 1, category: 1 }, promoteValues: false },
      );
    const docs: Bson[] = [];
    try {
      for await (const doc of cursor) {
        docs.push(doc);
        if (docs.length >= 5000) break;
      }
    } finally {
      await cursor.close();
    }

    // 3. Aggregate — verbatim Python semantics (sum first, then by_cat).
    let total = 0n;
    for (const d of docs) total += pyIntOrZero(d['size']);
    const byCat = new Map<string, { json: string; sum: bigint }>();
    for (const d of docs) {
      // `d.get("category", "general")` — key-based default only.
      const key = pyDictKey(Object.prototype.hasOwnProperty.call(d, 'category') ? d['category'] : undefined);
      const add = pyIntOrZero(d['size']);
      const cur = byCat.get(key.eq);
      if (cur) cur.sum += add;
      else byCat.set(key.eq, { json: key.json, sum: add });
    }

    const limitBytes = 500 * 1024 * 1024; // 524288000
    // `round(min(100, total / limit * 100), 2) if limit else 0`
    const ratio = pyTrueDiv(total, BigInt(limitBytes)) * 100;
    const pct = ratio < 100 ? pyFloatRepr(pyRound2(ratio)) : '100';

    const cats = [...byCat.values()].map((c) => `${c.json}:${c.sum.toString()}`).join(',');
    const body =
      `{"total_bytes":${total.toString()},"limit_bytes":${String(limitBytes)},"pct":${pct},` +
      `"file_count":${String(docs.length)},"by_category":{${cats}}}`;
    return reply.header('content-type', 'application/json').send(body);
  });
}
