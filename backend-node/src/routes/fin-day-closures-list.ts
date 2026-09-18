import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7m · Fin day-closures list read-only shadow.
 *
 *   GET /api/fin/day-closures
 *
 * Faithful shadow of:
 *   backend/routers/fin_day_closing.py::list_closures (L224-246)
 *
 * STRICTLY READ-ONLY. Class-C — Python handler executes ONLY
 *   db.fin_day_closures.find(q, {_id: 0, user_id: 0})
 *     .sort("close_date", -1).to_list(int(max(1, min(limit, 5000))))
 * Zero writer hook / audit / snapshot capture / FinTxn read / backfill.
 *
 * ── GATE-7m BINDINGS ────────────────────────────────────────────────
 *
 *   1. AUTH PRECEDES QUERY VALIDATION (FastAPI 0.110.1 solve_dependencies,
 *      same as Gate 7g). Unauthenticated → 401 literals regardless of a
 *      malformed `limit`.
 *
 *   2. `limit: int = 500` — NO ge/le constraints. The only 422 envelopes
 *      are `int_parsing` and `int_parsing_size`. Out-of-range integers are
 *      CLAMPED by the handler: int(max(1, min(limit, 5000))).
 *
 *   3. Pydantic 2.13.4 str→int coercion reproduced from source
 *      (pydantic-core 2.46.4 `src/input/shared.rs::str_as_int` +
 *      jiter 0.14.0 `NumberInt::try_from`), including:
 *        * strict JSON-int fast path on the RAW string; a digit run whose
 *          end offset (incl. a leading '-') exceeds 4300 → int_parsing_size
 *        * fallback clean: Rust `trim()` (Unicode White_Space — includes
 *          U+0085/U+00A0, excludes U+FEFF), '+' strip, sign handling,
 *          leading-zero strip, `.0+` strip, single-underscore strip
 *        * fallback result that fails strict parse (any reason) → int_parsing
 *      Accepts e.g. "1.0", "1_000", " 5 ", "+5", "05"; rejects "1.5",
 *      "1e3", "0x10", "", "1_", "1__0".
 *
 *   4. FILTER ASSEMBLY (exact Python order preserved):
 *      q = { user_id, company_id }
 *      if date_from or date_to:
 *          rng = {}; if date_from: rng.$gte; if date_to: rng.$lte
 *          q.close_date = rng
 *      if status: q.status = status
 *      Plain lexicographic strings — no date parsing, no trim.
 *
 *   5. PROJECTION strips `_id` AND `user_id`. SORT close_date DESC.
 *      Response = wrapper `{ rows, count }` (count = len(rows)).
 *
 *   6. Repeated query keys → LAST occurrence (Starlette MultiDict.get).
 *
 * Fin day-closing writer boundary (Python-authoritative, out of scope):
 *   POST /api/fin/day-closures · POST /api/fin/day-closures/{d}/reopen
 */

interface FinDayClosureDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  close_date?: string;
  status?: string;
  [k: string]: unknown;
}

// ── Pydantic 2.13.4 / pydantic-core 2.46.4 int coercion ───────────────
const PYDANTIC_INT_URL = 'https://errors.pydantic.dev/2.13/v/int_parsing';
const PYDANTIC_INT_MSG = 'Input should be a valid integer, unable to parse string as an integer';
const PYDANTIC_INT_SIZE_URL = 'https://errors.pydantic.dev/2.13/v/int_parsing_size';
const PYDANTIC_INT_SIZE_MSG = 'Unable to parse input string as an integer, exceeded maximum size';

// Rust `char::is_whitespace` (Unicode White_Space property).
const RUST_WS = '\\u0009-\\u000D\\u0020\\u0085\\u00A0\\u1680\\u2000-\\u200A\\u2028\\u2029\\u202F\\u205F\\u3000';
const RUST_TRIM_RE = new RegExp(`^[${RUST_WS}]+|[${RUST_WS}]+$`, 'g');

type StrictInt = { kind: 'ok'; value: bigint } | { kind: 'size' } | { kind: 'invalid' };
type ParsedInt = { ok: true; value: bigint } | { ok: false; type: 'int_parsing' | 'int_parsing_size' };

const isDigit = (c: string | undefined): boolean => c !== undefined && c >= '0' && c <= '9';

// jiter 0.14.0 `NumberInt::try_from(&[u8])` — whole string must be a JSON int.
function jiterStrictInt(s: string): StrictInt {
  let i = 0;
  if (s[0] === '-') i = 1;
  const first = s[i];
  if (first === '0') {
    return i + 1 === s.length ? { kind: 'ok', value: 0n } : { kind: 'invalid' };
  }
  if (first === undefined || first < '1' || first > '9') return { kind: 'invalid' };
  let j = i;
  while (isDigit(s[j])) j++;
  // Big-int chunk loop guard: `(new_index - start) > 4300` → NumberOutOfRange.
  if (j > 4300) return { kind: 'size' };
  if (j !== s.length) return { kind: 'invalid' };
  return { kind: 'ok', value: BigInt(s) };
}

// pydantic-core `strip_leading_zeros`.
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

// pydantic-core `strip_underscores`.
function stripUnderscores(s: string): string | null {
  if (s.startsWith('_') || s.endsWith('_') || !s.includes('_') || s.includes('__')) return null;
  return s.replace(/_/g, '');
}

// pydantic-core `clean_int_str`.
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
  // `s` is always a sub-slice of `orig`, so equal length ⇔ nothing changed.
  if (orig.length === s.length) return null;
  return negative ? `-${s}` : s;
}

// pydantic-core `str_as_int`.
function parsePydanticInt(raw: string): ParsedInt {
  const fast = jiterStrictInt(raw);
  if (fast.kind === 'ok') return { ok: true, value: fast.value };
  if (fast.kind === 'size') return { ok: false, type: 'int_parsing_size' };
  const cleaned = cleanIntStr(raw);
  if (cleaned === null) return { ok: false, type: 'int_parsing' };
  const slow = jiterStrictInt(cleaned);
  return slow.kind === 'ok' ? { ok: true, value: slow.value } : { ok: false, type: 'int_parsing' };
}

function limitError(type: 'int_parsing' | 'int_parsing_size', input: string): Record<string, unknown> {
  return {
    detail: [
      {
        type,
        loc: ['query', 'limit'],
        msg: type === 'int_parsing' ? PYDANTIC_INT_MSG : PYDANTIC_INT_SIZE_MSG,
        input,
        url: type === 'int_parsing' ? PYDANTIC_INT_URL : PYDANTIC_INT_SIZE_URL,
      },
    ],
  };
}

// Python: int(max(1, min(limit, 5000))).
function clampLimit(v: bigint): number {
  if (v < 1n) return 1;
  if (v > 5000n) return 5000;
  return Number(v);
}

// Last occurrence wins for repeated keys (Starlette MultiDict.get).
function qParam(query: Record<string, unknown>, key: string): string | undefined {
  const v = query[key];
  if (v === undefined || v === null) return undefined;
  if (Array.isArray(v)) return v.length ? String(v[v.length - 1]) : undefined;
  return String(v);
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerFinDayClosuresListRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7m (read-only)
  app.get('/api/fin/day-closures', async (req: FastifyRequest, reply: FastifyReply) => {
    // 1. Auth FIRST — locked 401 literals. Auth precedes query 422.
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

    // 2. Query parsing — only `limit` can fail validation.
    const query = (req.query ?? {}) as Record<string, unknown>;
    const dateFrom = qParam(query, 'date_from');
    const dateTo = qParam(query, 'date_to');
    const status = qParam(query, 'status');
    const limitRaw = qParam(query, 'limit');

    let limit = 500;
    if (limitRaw !== undefined) {
      const p = parsePydanticInt(limitRaw);
      if (!p.ok) {
        reply.code(422);
        return limitError(p.type, limitRaw);
      }
      limit = clampLimit(p.value);
    }

    // 3. Active-company resolution (locked helper).
    const cid = await activeCompanyId(req, userId, db);

    // 4. Filter assembly — mirrors Python line-for-line.
    const filter: Record<string, unknown> = { user_id: userId, company_id: cid };
    if (dateFrom || dateTo) {
      const rng: Record<string, unknown> = {};
      if (dateFrom) rng['$gte'] = dateFrom;
      if (dateTo) rng['$lte'] = dateTo;
      filter['close_date'] = rng;
    }
    if (status) {
      filter['status'] = status;
    }

    // 5. Read with EXACT projection / sort / clamped cap.
    const rows = await db
      .collection<FinDayClosureDoc>('fin_day_closures')
      .find(filter as Filter<FinDayClosureDoc>, { projection: { _id: 0, user_id: 0 } })
      .sort([['close_date', -1]])
      .limit(limit)
      .toArray();

    return { rows, count: rows.length };
  });
}
