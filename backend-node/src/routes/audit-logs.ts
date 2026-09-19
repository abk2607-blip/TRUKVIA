import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter, FindCursor } from 'mongodb';
import { authenticate } from '../auth.js';
import { HttpError } from '../errors.js';

// ── Gate 9e · Motor `to_list(n)` (route-local) ────────────────────────
// Motor sends NO server-side limit for `to_list(n)`; a `.limit(n)` turns the
// sort into a top-k whose tie order at the cap differs (verified live). Read
// the sorted cursor and stop after n documents, exactly like Motor.
async function motorToList<T>(cursor: FindCursor<T>, n: number): Promise<T[]> {
  const out: T[] = [];
  try {
    if (n <= 0) {
      await cursor.hasNext(); // to_list(0) still issues the find, returns []
      return out;
    }
    for await (const doc of cursor) {
      out.push(doc);
      if (out.length >= n) break;
    }
  } finally {
    await cursor.close();
  }
  return out;
}
// ── Gate 9e · Pydantic 2.13.4 / pydantic-core 2.46.4 int coercion (route-local copy
//    of the live-verified Gate-7m port) ────────────────────────────────────────
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

function limitParseErr(type: 'int_parsing' | 'int_parsing_size', input: string): Record<string, unknown> {
  return {
    type,
    loc: ['query', 'limit'],
    msg: type === 'int_parsing' ? PYDANTIC_INT_MSG : PYDANTIC_INT_SIZE_MSG,
    input,
    url: type === 'int_parsing' ? PYDANTIC_INT_URL : PYDANTIC_INT_SIZE_URL,
  };
}

// ── Starlette QueryParams: latin-1 → CPython 3.11 parse_qsl (Gate-7v copy) ──
const QS_HEX = /^[0-9A-Fa-f]{2}$/;
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
    if (QS_HEX.test(h)) {
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
  return s.replace(/[\x00-\x7f]+/g, (run) => unquoteAsciiRun(run));
}

// Last occurrence of `key` (ImmutableMultiDict.get), undefined when absent.
function pyQueryLast(rawUrl: string, key: string): string | undefined {
  const qi = rawUrl.indexOf('?');
  if (qi < 0) return undefined;
  let found: string | undefined;
  for (const field of rawUrl.slice(qi + 1).split('&')) {
    if (!field) continue;
    const eq = field.indexOf('=');
    const name = eq < 0 ? field : field.slice(0, eq);
    const value = eq < 0 ? '' : field.slice(eq + 1);
    if (pyUnquotePlus(name) === key) found = pyUnquotePlus(value);
  }
  return found;
}

/**
 * TRUKVIA · Phase-3 · Gate-6s · Audit-log read-only shadow.
 *
 *   GET /api/audit-logs
 *     ?module=&action=&entity_id=&start=&end=&limit=
 *
 * Faithful shadow of:
 *   backend/routers/audit_router.py::list_audit_logs  (lines 29–49)
 *
 * STRICTLY READ-ONLY. Class-C — the Python handler executes ONLY
 * `db.audit_logs.find().sort().to_list(min(int(limit), 500))`.
 * Zero writer hook, zero audit call, zero backfill, zero recompute,
 * zero FinTxn emission, zero approvals / policy / counters /
 * idempotency touch, zero unrelated collection reads.
 *
 * ── GATE-6s NEW DIMENSIONS (BIND PRECISELY) ─────────────────────────
 *
 *   1. NO `activeCompanyId()` INVOCATION — this endpoint is strictly
 *      user-scoped. The Python route does NOT call `_active_company_id`,
 *      so Node MUST NOT call `activeCompanyId()` either (invocation
 *      parity in the negative direction — same tenant-resolver DB
 *      touch surface = none).
 *
 *   2. TRUTHY-GATED OPTIONAL FILTERS — `module`, `action`, `entity_id`
 *      are added to the DB filter ONLY when truthy. Empty string is
 *      omitted from the filter (mirrors Python `if module: q["module"] = module`).
 *
 *   3. `end + "T23:59:59"` LITERAL SUFFIX — the range upper bound is a
 *      Python string concatenation with no timezone, no ISO validation.
 *      Node MUST reproduce the exact suffix.
 *
 *   4. `limit` FASTAPI COERCION — declared `int = 200`. Non-integer
 *      values (`"abc"`) trigger FastAPI/Pydantic-v2 422 `int_parsing`
 *      before the handler runs. Node reproduces the exact body.
 *
 *   5. HARD 500 CAP — `min(int(limit), 500)`. Callers cannot exceed
 *      500 rows regardless of request.
 *
 * Gate-7 writer boundary (out of scope for Gate 6s):
 *   Audit logs are produced by writer routes across the codebase
 *   (create/update/delete on business collections). Read parity here
 *   does NOT include any write behavior.
 */

interface AuditLogDoc {
  id?: string;
  user_id?: string;
  module?: string;
  action?: string;
  entity_id?: string;
  timestamp?: string;
  [k: string]: unknown;
}

// Parse an optional string query param — return `undefined` if
// missing, otherwise the trimmed value as-is. Preserves Python's
// truthiness semantics (empty string is falsy → omitted from filter).
function firstStr(v: unknown): string | undefined {
  if (typeof v === 'string') return v;
  if (Array.isArray(v)) {
    const first = v[0];
    return typeof first === 'string' ? first : undefined;
  }
  return undefined;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerAuditLogsReadRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-6s (read-only)
  app.get(
    '/api/audit-logs',
    async (req: FastifyRequest, reply: FastifyReply) => {
      // 1. Auth FIRST — locked 401 literals short-circuit 422.
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

      // NOTE: No activeCompanyId() invocation — Python does not call
      // _active_company_id on this route (audit_router.py:30–48).

      // 2. Query params.
      const q = (req.query ?? {}) as Record<string, unknown>;
      const module_ = firstStr(q['module']);
      const action = firstStr(q['action']);
      const entityId = firstStr(q['entity_id']);
      const start = firstStr(q['start']);
      const end = firstStr(q['end']);
      // Gate 9e: Starlette query value (last occurrence, Python unquote_plus).
      const limitRaw = pyQueryLast(req.raw.url ?? '', 'limit');

      // 3. limit coercion → exact Pydantic 2.13.4 int semantics (Gate 9e).
      let limitBig = 200n;
      if (limitRaw !== undefined) {
        const p = parsePydanticInt(limitRaw);
        if (!p.ok) {
          reply.code(422);
          return { detail: [limitParseErr(p.type, limitRaw)] };
        }
        limitBig = p.value;
      }
      // 4. `to_list(min(int(limit), 500))`: 0 → [] (find still issued);
      //    negative → Motor ValueError("length must be non-negative") → 500.
      if (limitBig > 500n) limitBig = 500n;
      if (limitBig < 0n) throw new Error('to_list: length must be non-negative');
      const limit = Number(limitBig);

      // 5. Build filter — always `user_id`; optional truthy-gated keys.
      const filter: Record<string, unknown> = { user_id: userId };
      if (module_) filter['module'] = module_;
      if (action) filter['action'] = action;
      if (entityId) filter['entity_id'] = entityId;

      // 6. Range filter — `start or end` in Python (either truthy).
      if (start || end) {
        const rng: Record<string, string> = {};
        if (start) rng['$gte'] = start;
        if (end) rng['$lte'] = end + 'T23:59:59'; // exact Python literal
        filter['timestamp'] = rng;
      }

      // 7. Read with EXACT projection / sort / cap.
      const rows = await motorToList(
        db
        .collection<AuditLogDoc>('audit_logs')
        .find(filter as Filter<AuditLogDoc>, { projection: { _id: 0, user_id: 0 } })
        .sort([['timestamp', -1]]),
        limit,
      );

      return rows;
    },
  );
}
