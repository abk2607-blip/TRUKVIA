import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7z · Driver salary-settlement hint read-only shadow.
 *
 *   GET /api/drivers/{did}/salary-settlement-hint?month=...
 *
 * Faithful shadow of:
 *   backend/routers/driver_payments.py::salary_settlement_hint (L294-304)
 *
 * Python (verbatim):
 * ```
 * @router.get("/drivers/{did}/salary-settlement-hint")
 * async def salary_settlement_hint(did: str, month: str, request: Request,
 *                                     user=Depends(get_current_user)):
 *     uid, cid = user["user_id"], await _active_company_id(request, user)
 *     existing = await db.driver_ledger_entries.find_one(
 *         {"user_id": uid, "company_id": cid, "driver_id": did,
 *          "month": month, "kind": "settlement"}, {"_id": 0})
 *     return {"possible_duplicate": bool(existing),
 *             "existing_settlement": existing or None}
 * ```
 *
 * STRICTLY READ-ONLY. One find_one on driver_ledger_entries. No driver
 * existence check (Python has none — `_ensure_driver` is NOT called).
 *
 * ── PYTHON BEHAVIOUR COPIED, NOT FIXED ──────────────────────────────
 * The only settlement writer (driver_ledger.py::settle, L394-412) stores
 * `entry_type: "settlement"`, `month_key` and `reference.{kind,month}` —
 * never top-level `month` / `kind`. So for real data this filter never
 * matches and the hint is always {"possible_duplicate":false,
 * "existing_settlement":null}. Node sends the IDENTICAL filter; a document
 * that does carry top-level month + kind:"settlement" is returned verbatim.
 *
 * ── GATE-7z BINDINGS ────────────────────────────────────────────────
 *
 *   1. PATH: Starlette `[^/]+` on the decoded path — empty `did` or one
 *      containing "/" → 404 {"detail":"Not Found"} before auth (as 7p).
 *
 *   2. ORDER (verified live): auth 401 → required `month: str` 422
 *      `missing` → `_active_company_id` → read. `month` is a plain str: any
 *      value (incl. "", "1.0", Unicode) is accepted verbatim, no parsing.
 *
 *   3. QUERY DECODING = Starlette `QueryParams`: latin-1 → CPython 3.11
 *      parse_qsl/unquote (local copy, Gate 7v); repeated key → LAST value.
 *
 *   4. RESPONSE key order {possible_duplicate, existing_settlement}; the
 *      document keeps user_id (projection {_id:0}); `existing or None` →
 *      null when not found. JSON = jsonable_encoder + json.dumps rebuilt
 *      from the typed document (promoteValues:false); NaN / unencodable
 *      BSON → 500 `Internal Server Error` (text/plain; charset=utf-8).
 *
 *   5. CONTENT-TYPE exactly `application/json` (Buffer payload).
 *
 *   6. HEAD: FastAPI answers 405 + `allow: GET` (verified live) — Fastify
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

const NOT_FOUND = '{"detail":"Not Found"}';
const MONTH_MISSING = JSON.stringify({
  detail: [{
    type: 'missing', loc: ['query', 'month'], msg: 'Field required', input: null,
    url: 'https://errors.pydantic.dev/2.13/v/missing',
  }],
});
const METHOD_NOT_ALLOWED = Buffer.from('{"detail":"Method Not Allowed"}', 'utf8');

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerDriverSalarySettlementHintRoute(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7z (read-only)
  app.get('/api/drivers/:did/salary-settlement-hint', { exposeHeadRoute: false },
    async (req: FastifyRequest, reply: FastifyReply) => {
      const did = (req.params as { did: string }).did;

      // 0. Starlette never routes an empty segment or a decoded "/" (`[^/]+`).
      if (did === '' || did.includes('/')) return sendJson(reply, 404, NOT_FOUND);

      // 1. Auth FIRST — locked 401 literals.
      let userId: string;
      try {
        userId = (await authenticate(req, db)).user_id;
      } catch (err) {
        if (err instanceof HttpError) return sendJson(reply, err.status, JSON.stringify({ detail: err.detail }));
        throw err;
      }

      // 2. Required `month: str` — any string (incl. "") is valid.
      const month = pyQueryLast(req.raw.url ?? '', 'month');
      if (month === undefined) return sendJson(reply, 422, MONTH_MISSING);

      // 3. Active-company resolution (locked helper).
      const cid = await activeCompanyId(req, userId, db);

      try {
        // 4. Python's exact filter (top-level month + kind — copied, not fixed).
        const existing = await db
          .collection<Doc>('driver_ledger_entries')
          .findOne(
            { user_id: userId, company_id: cid, driver_id: did, month, kind: 'settlement' } as Filter<Doc>,
            { projection: { _id: 0 }, promoteValues: false },
          );
        const found = existing !== null && Object.keys(existing).length > 0;
        return sendJson(reply, 200,
          `{"possible_duplicate":${found ? 'true' : 'false'},"existing_settlement":${found ? pyJson(existing) : 'null'}}`);
      } catch (err) {
        if (err instanceof PyServerError) {
          return reply.code(500).header('content-type', 'text/plain; charset=utf-8').send('Internal Server Error');
        }
        throw err;
      }
    });

  // FastAPI registers GET only on this path → HEAD is 405 before auth (verified live).
  app.head('/api/drivers/:did/salary-settlement-hint', async (_req: FastifyRequest, reply: FastifyReply) =>
    reply.code(405).header('allow', 'GET').header('content-type', 'application/json').send(METHOD_NOT_ALLOWED));
}
