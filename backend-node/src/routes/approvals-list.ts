import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

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
 * TRUKVIA · Phase-3 · Gate-7g · Approvals list read-only shadow.
 *
 *   GET /api/approvals
 *
 * Faithful shadow of:
 *   backend/routers/approvals.py::api_list_approvals (L33-46)
 *   → services_approvals.list_approvals            (L527-541)
 *
 * STRICTLY READ-ONLY. Class-C — Python executes ONLY
 *   db.approvals.find(q, {_id:0}).sort("created_at", -1).limit(min(500, limit))
 *
 * Zero writer hook / audit / backfill / recompute / FinTxn / approvals
 * mutation / counters / idempotency / cross-collection reads.
 *
 * ── GATE-7g BINDINGS ────────────────────────────────────────────────
 *
 *   1. FastAPI 0.110.1 executes `Depends(get_current_user)` INSIDE
 *      `solve_dependencies` (fastapi/dependencies/utils.py L549) BEFORE
 *      `request_params_to_args` reaches query validation (L610).
 *      A raised `HTTPException(401)` in `get_current_user` short-circuits
 *      the coroutine, so query validation never runs. Therefore:
 *        · unauthenticated + invalid query  → 401 (auth wins)
 *        · authenticated  + invalid query  → 422 (Pydantic envelope)
 *        · authenticated  + valid   query  → 200
 *      AUTH PRECEDES QUERY VALIDATION.
 *
 *   2. Pydantic v2 (2.13.4) 422 envelopes reproduced verbatim for:
 *      * bool_parsing        (include_all)
 *      * int_parsing         (limit)
 *      * greater_than_equal  (limit < 1)  — ctx: {ge: 1}
 *      * less_than_equal     (limit > 500) — ctx: {le: 500}
 *
 *   3. Projection `{_id: 0}` — strips only `_id`; **user_id preserved**.
 *
 *   4. include_all semantics (verified against source):
 *      * status truthy → q.status = status (include_all IGNORED)
 *      * status falsy + include_all=false → q.status = {$in: [
 *          "PENDING_APPROVAL", "REJECTED", "WITHDRAWN" ]}
 *      * status falsy + include_all=true → no status predicate
 *
 * Approvals writer boundary (Python-authoritative, out of scope):
 *   POST /api/approvals · POST /api/approvals/{aid}/{approve|reject|withdraw|resubmit}
 */

// ── Pydantic 2.13.4 bool-parsing mimic ─────────────────────────────
//    Accepted spellings: true/True/TRUE, false/False/FALSE, 1, 0,
//    yes/Yes/YES, no/No/NO, on/On/ON, off/Off/OFF.
const TRUE_TOKENS = new Set(['true', '1', 'yes', 'on']);
const FALSE_TOKENS = new Set(['false', '0', 'no', 'off']);

function parseBoolStrict(raw: string): { ok: true; value: boolean } | { ok: false; raw: string } {
  const key = raw.toLowerCase();
  if (TRUE_TOKENS.has(key)) return { ok: true, value: true };
  if (FALSE_TOKENS.has(key)) return { ok: true, value: false };
  return { ok: false, raw };
}


function boolParsingErr(raw: string): Record<string, unknown> {
  return {
    type: 'bool_parsing',
    loc: ['query', 'include_all'],
    msg: 'Input should be a valid boolean, unable to interpret input',
    input: raw,
    url: 'https://errors.pydantic.dev/2.13/v/bool_parsing',
  };
}

function greaterThanEqualErr(raw: string): Record<string, unknown> {
  return {
    type: 'greater_than_equal',
    loc: ['query', 'limit'],
    msg: 'Input should be greater than or equal to 1',
    input: raw,
    ctx: { ge: 1 },
    url: 'https://errors.pydantic.dev/2.13/v/greater_than_equal',
  };
}

function lessThanEqualErr(raw: string): Record<string, unknown> {
  return {
    type: 'less_than_equal',
    loc: ['query', 'limit'],
    msg: 'Input should be less than or equal to 500',
    input: raw,
    ctx: { le: 500 },
    url: 'https://errors.pydantic.dev/2.13/v/less_than_equal',
  };
}

interface ApprovalDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  status?: string;
  entity_kind?: string;
  created_at?: string;
  [k: string]: unknown;
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerApprovalsListRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7g (read-only)
  app.get('/api/approvals', async (req: FastifyRequest, reply: FastifyReply) => {
    const q = (req.query ?? {}) as Record<string, unknown>;

    // 1. Auth FIRST — reproduces FastAPI 0.110.1 `solve_dependencies`
    //    ordering: `Depends(get_current_user)` runs before Pydantic
    //    query validation. A 401 short-circuits the coroutine so query
    //    validation never runs.
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

    // 2. Query validation — Pydantic v2 semantics, declaration-order
    //    errors (include_all before limit) to match FastAPI's error array.
    const errors: Record<string, unknown>[] = [];

    let includeAll = false;
    if (typeof q['include_all'] !== 'undefined') {
      const raw = String(q['include_all']);
      const p = parseBoolStrict(raw);
      if (!p.ok) errors.push(boolParsingErr(raw));
      else includeAll = p.value;
    }

    let limit = 200;
    // Gate 9e: Starlette query value (last occurrence) + exact Pydantic int.
    const limitRaw = pyQueryLast(req.raw.url ?? '', 'limit');
    if (limitRaw !== undefined) {
      const p = parsePydanticInt(limitRaw);
      if (!p.ok) {
        errors.push(limitParseErr(p.type, limitRaw));
      } else if (p.value < 1n) {
        errors.push(greaterThanEqualErr(limitRaw));
      } else if (p.value > 500n) {
        errors.push(lessThanEqualErr(limitRaw));
      } else {
        limit = Number(p.value);
      }
    }

    if (errors.length > 0) {
      reply.code(422);
      return { detail: errors };
    }

    // 3. Active-company resolution (locked helper).
    const cid = await activeCompanyId(req, userId, db);

    // 4. Build filter conditionally — mirror Python exactly.
    const statusRaw = typeof q['status'] === 'undefined' ? '' : String(q['status']);
    const entityKindRaw = typeof q['entity_kind'] === 'undefined' ? '' : String(q['entity_kind']);
    const filter: Record<string, unknown> = { user_id: userId, company_id: cid };
    if (statusRaw) {
      filter['status'] = statusRaw;
    } else if (!includeAll) {
      filter['status'] = { $in: ['PENDING_APPROVAL', 'REJECTED', 'WITHDRAWN'] };
    }
    if (entityKindRaw) filter['entity_kind'] = entityKindRaw;

    // 5. Read — projection strips _id only (user_id preserved), sort
    //    created_at DESC, cap min(500, limit) — technically redundant
    //    given le=500 but preserves the Python contract literally.
    const rows = await db
      .collection<ApprovalDoc>('approvals')
      .find(filter as Filter<ApprovalDoc>, { projection: { _id: 0 } })
      .sort([['created_at', -1]])
      .limit(Math.min(500, limit))
      .toArray();

    // Bare-array response — matches Python exactly.
    return rows;
  });
}
