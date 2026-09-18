import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db } from 'mongodb';
import { authenticate } from '../auth.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7v · GSTIN offline lookup read-only shadow.
 *
 *   GET /api/gstin/lookup?gstin=...
 *
 * Faithful shadow of:
 *   backend/routers/gst.py::gstin_lookup (L31-72)
 *   backend/services.py STATE_CODES / STATE_CODE_TO_NAME / _GSTIN_RE /
 *   _gstin_checksum (effective definitions L717-741)
 *
 * STRICTLY READ-ONLY. Class-C — after `get_current_user` the Python handler
 * touches NO database, NO network and NO file: it is a pure offline parse.
 * No company resolution (`_active_company_id` is NOT called by Python).
 *
 * ── GATE-7v BINDINGS ────────────────────────────────────────────────
 *
 *   1. ORDER: auth (locked 401 literals) → required `gstin: str`
 *      (FastAPI 422 `missing`) → normalise → `if not g` 400
 *      {"detail":"GSTIN is required"} → parse.
 *
 *   2. QUERY DECODING = Starlette `QueryParams(scope["query_string"])`:
 *      bytes → latin-1 → `urllib.parse.parse_qsl(keep_blank_values=True)`
 *      (split on "&" only, empty fields skipped, "+" → " ", CPython 3.11
 *      `unquote` incl. its ASCII-run split and UTF-8 errors="replace").
 *      Repeated key → LAST occurrence (ImmutableMultiDict.get). Parsed
 *      locally from the raw request target so the echoed `gstin` is
 *      byte-identical to Python for every input.
 *
 *   3. NORMALISATION `(gstin or "").strip().upper().replace(" ", "")`:
 *        * strip() — CPython str.isspace() set (29 code points; differs
 *          from JS trim(): includes U+001C–U+001F and U+0085, excludes U+FEFF).
 *        * upper() — CPython 3.11 / Unicode 14.0 full case mapping. JS
 *          toUpperCase() agrees except for code points that gained an
 *          uppercase mapping after Unicode 14 (UPPER_POST_14 below —
 *          verified by an exhaustive 0..0x10FFFF differential against
 *          Python 3.11.9 on Node 24.21.0 / ICU 78.3 / Unicode 17.0).
 *        * replace(" ", "") — ASCII space only.
 *
 *   4. PARSE: ASCII regex `^([0-9]{2})([A-Z]{5}[0-9]{4}[A-Z])([0-9A-Z])(Z)([0-9A-Z])$`
 *      (Python `$` also matches before a trailing "\n", unreachable after
 *      strip()). Checksum = exact copy of `_gstin_checksum`.
 *
 *   5. RESPONSE (key order preserved), note depends on GSTIN_LOOKUP_API_KEY
 *      being truthy in the process environment at request time (as Python
 *      reads os.environ per request). JSON bytes = FastAPI JSONResponse
 *      (`ensure_ascii=False`, compact separators), exact `application/json`.
 *
 *   6. HEAD: FastAPI answers 405 + `allow: GET` (verified live) — Fastify
 *      auto-HEAD disabled for this route and the 405 reproduced explicitly.
 */

// ── services.py STATE_CODE_TO_NAME (derived table, verbatim values) ────
// {v: k.title().replace("And ", "and ").replace("Of ", "of ")} over
// STATE_CODES, then the six explicit overrides (07/35/26/01/37/36).
const STATE_CODE_TO_NAME: Readonly<Record<string, string>> = {
  '01': 'Jammu and Kashmir',
  '02': 'Himachal Pradesh',
  '03': 'Punjab',
  '04': 'Chandigarh',
  '05': 'Uttarakhand',
  '06': 'Haryana',
  '07': 'Delhi',
  '08': 'Rajasthan',
  '09': 'Uttar Pradesh',
  '10': 'Bihar',
  '11': 'Sikkim',
  '12': 'Arunachal Pradesh',
  '13': 'Nagaland',
  '14': 'Manipur',
  '15': 'Mizoram',
  '16': 'Tripura',
  '17': 'Meghalaya',
  '18': 'Assam',
  '19': 'West Bengal',
  '20': 'Jharkhand',
  '21': 'Odisha',
  '22': 'Chhattisgarh',
  '23': 'Madhya Pradesh',
  '24': 'Gujarat',
  '26': 'Dadra and Nagar Haveli and Daman and Diu',
  '27': 'Maharashtra',
  '29': 'Karnataka',
  '30': 'Goa',
  '31': 'Lakshadweep',
  '32': 'Kerala',
  '33': 'Tamil Nadu',
  '34': 'Puducherry',
  '35': 'Andaman and Nicobar Islands',
  '36': 'Telangana',
  '37': 'Andhra Pradesh',
  '38': 'Ladakh',
};

// ── services.py _GSTIN_RE / _GSTIN_CHECK_ALPHABET / _gstin_checksum ───
const GSTIN_RE = /^([0-9]{2})([A-Z]{5}[0-9]{4}[A-Z])([0-9A-Z])(Z)([0-9A-Z])$/;
const GSTIN_CHECK_ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';

function gstinChecksum(gstin14: string): string {
  let total = 0;
  for (let idx = 0; idx < gstin14.length; idx++) {
    const v = GSTIN_CHECK_ALPHABET.indexOf(gstin14[idx] as string);
    const factor = idx % 2 ? 2 : 1;
    const prod = v * factor;
    total += Math.floor(prod / 36) + (prod % 36);
  }
  return GSTIN_CHECK_ALPHABET[(36 - (total % 36)) % 36] as string;
}

const OFFLINE_NOTE =
  'Offline parse only. Full name/address needs a paid GSTIN API (Signzy/ClearTax). ' +
  'Configure GSTIN_LOOKUP_API_KEY to enable.';

// ── CPython 3.11 str.strip() whitespace (str.isspace) ─────────────────
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

// ── CPython 3.11 (Unicode 14.0) str.upper() ───────────────────────────
// Code points whose uppercase mapping was added after Unicode 14 — Python
// 3.11 leaves them unchanged.
const UPPER_POST_14: ReadonlyArray<readonly [number, number]> = [
  [0x019b, 0x019b], [0x0264, 0x0264], [0x1c8a, 0x1c8a],
  [0xa7cd, 0xa7cd], [0xa7cf, 0xa7cf], [0xa7d3, 0xa7d3], [0xa7d5, 0xa7d5], [0xa7db, 0xa7db],
  [0x10d70, 0x10d85], [0x16ebb, 0x16ed3],
];

function pyUpper(s: string): string {
  let out = '';
  for (const ch of s) {
    const cp = ch.codePointAt(0) as number;
    if (cp < 0x80) {
      out += cp >= 0x61 && cp <= 0x7a ? String.fromCharCode(cp - 0x20) : ch;
    } else if (UPPER_POST_14.some(([lo, hi]) => cp >= lo && cp <= hi)) {
      out += ch;
    } else {
      out += ch.toUpperCase();
    }
  }
  return out;
}

// ── Starlette QueryParams: latin-1 → CPython 3.11 parse_qsl ───────────
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

const METHOD_NOT_ALLOWED = Buffer.from('{"detail":"Method Not Allowed"}', 'utf8');

const sendJson = (reply: FastifyReply, status: number, body: unknown): FastifyReply =>
  reply.code(status).header('content-type', 'application/json').send(Buffer.from(JSON.stringify(body), 'utf8'));

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerGstinLookupRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7v (read-only)
  app.get('/api/gstin/lookup', { exposeHeadRoute: false }, async (req: FastifyRequest, reply: FastifyReply) => {
    // 1. Auth FIRST — locked 401 literals.
    try {
      await authenticate(req, db);
    } catch (err) {
      if (err instanceof HttpError) return sendJson(reply, err.status, { detail: err.detail });
      throw err;
    }

    // 2. Required `gstin: str` — FastAPI/Pydantic v2 `missing` envelope.
    const gstin = pyQueryLast(req.raw.url ?? '', 'gstin');
    if (gstin === undefined) {
      return sendJson(reply, 422, {
        detail: [{
          type: 'missing',
          loc: ['query', 'gstin'],
          msg: 'Field required',
          input: null,
          url: 'https://errors.pydantic.dev/2.13/v/missing',
        }],
      });
    }

    // 3. (gstin or "").strip().upper().replace(" ", "")
    const g = pyUpper(pyStrip(gstin)).replace(/ /g, '');
    if (!g) return sendJson(reply, 400, { detail: 'GSTIN is required' });

    // 4. Offline parse — exact Python result dict (key order preserved).
    const m = GSTIN_RE.exec(g);
    const result: Record<string, unknown> = {
      gstin: g, valid_format: m !== null, checksum_ok: false, state_code: '', state: '',
      pan: '', entity_code: '', source: 'offline_parse', legal_name: null,
      trade_name: null, address: null, note: null,
    };
    if (m) {
      const stateCode = m[1] as string;
      const expectedCheck = gstinChecksum(g.slice(0, 14));
      result['state_code'] = stateCode;
      result['state'] = Object.prototype.hasOwnProperty.call(STATE_CODE_TO_NAME, stateCode)
        ? STATE_CODE_TO_NAME[stateCode]
        : '';
      result['pan'] = m[2] as string;
      result['entity_code'] = m[3] as string;
      result['checksum_ok'] = expectedCheck === g[14];
    }
    if (!process.env['GSTIN_LOOKUP_API_KEY']) result['note'] = OFFLINE_NOTE;
    return sendJson(reply, 200, result);
  });

  // FastAPI registers GET only → HEAD is 405 before auth (verified live).
  app.head('/api/gstin/lookup', async (_req: FastifyRequest, reply: FastifyReply) =>
    reply.code(405).header('allow', 'GET').header('content-type', 'application/json').send(METHOD_NOT_ALLOWED));
}
