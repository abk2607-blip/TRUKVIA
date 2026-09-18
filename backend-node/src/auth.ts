import type { Db } from 'mongodb';
import type { FastifyRequest } from 'fastify';
import { HttpError } from './errors.js';

/**
 * TRUKVIA Node · session authentication — READ-ONLY shadow of
 * `backend/auth.py::get_current_user` (L115-188).
 *
 * Phase-4 · Gate-9b: the full authenticated IDENTITY CONTEXT is reproduced
 * (the Phase-2/3 version returned `session.user_id` / `session.effective_role`
 * directly, which diverged for real login sessions and for staff users).
 *
 * Python order (reproduced; every step is a READ):
 *   1. Token: `request.cookies.get("session_token")` — Starlette cookie_parser
 *      on the FIRST `Cookie` header (split ";", key/value at first "=", Python
 *      str.strip(), http.cookies._unquote, LAST duplicate key wins). If falsy,
 *      the FIRST `Authorization` header: `startswith("Bearer ")` → `auth[7:]`
 *      (NOT trimmed). Missing / empty → 401 "Not authenticated".
 *   2. `user_sessions.find_one({session_token}, {_id:0})` → none → 401
 *      "Invalid session".
 *   3. `expires_at`: str → CPython 3.11 C `datetime.fromisoformat`; naive →
 *      UTC; `< now` → 401 "Session expired". Missing / None / non-date /
 *      unparseable → Python raises (AttributeError / ValueError) → 500.
 *   4. (Python: rolling-refresh WRITE on user_sessions — deliberately NOT
 *      ported; it stays a Python responsibility, see Gate 9a.)
 *   5. `users.find_one({user_id: session["user_id"]}, {_id:0})` — a missing
 *      `user_id` key raises (500); `if not user` (None or {}) → 401
 *      "User not found".
 *   6. `team_members.find_one({email: user["email"], active: True}, {_id:0})`
 *      — a users doc without `email` raises (500).
 *      If tm (non-empty) AND tm.owner_user_id is truthy AND differs from
 *      user.user_id → STAFF: data scope user_id = tm.owner_user_id,
 *      effective_role = tm.get("role", "accountant"), is_staff = True.
 *      Otherwise → effective_role = "owner", is_staff = False.
 *
 * `AuthUser.effective_role` carries the role chain the only Node consumers
 * (company/party bank-account masking — Python
 * `party_role_can_view_full`) evaluate: `effective_role or user.role`
 * (users-doc `role`), with Python truthiness. The consumers apply the final
 * `or ""`.
 *
 * Python's demo-token branch is unreachable in production (DEMO_TOKEN = "")
 * and is not implemented here. Unexpected failures are thrown as plain
 * errors (HTTP 500 — body format is the framework error handler's, Gate 9d).
 */

export interface AuthUser {
  /** Data-scope user id: the owner's id for staff (Python `user["user_id"]`). */
  user_id: string;
  /** Python `effective_role or role` (masking-relevant role chain). */
  effective_role: string;
  /** Python `is_staff`. */
  is_staff: boolean;
  /** users-doc email (Python `user["email"]`). */
  email?: string;
}

type Doc = Record<string, unknown>;

class AuthServerError extends Error {
  constructor(why: string) {
    super(why);
    this.name = 'AuthServerError';
  }
}

// ── Python truthiness (values decoded with default driver promotion) ───
function pyTruthy(v: unknown): boolean {
  if (v === null || v === undefined) return false;
  if (typeof v === 'boolean') return v;
  if (typeof v === 'string') return v.length > 0;
  if (typeof v === 'number') return v !== 0;
  if (typeof v === 'bigint') return v !== 0n;
  if (Array.isArray(v)) return v.length > 0;
  if (v instanceof Date) return true;
  const t = (v as { _bsontype?: string })._bsontype;
  if (t === 'Long') return !(v as { isZero(): boolean }).isZero();
  if (t === 'Binary') return (v as { length(): number }).length() > 0;
  if (t !== undefined) return true;
  return Object.keys(v as object).length > 0;
}

const has = (o: object, k: string): boolean => Object.prototype.hasOwnProperty.call(o, k);

// ── Token extraction (Starlette Request.cookies / Request.headers) ──────
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

// http.cookies._unquote
function pyCookieUnquote(str: string): string {
  if (str.length < 2 || str[0] !== '"' || str[str.length - 1] !== '"') return str;
  const s = str.slice(1, -1);
  const octal = /\\[0-3][0-7][0-7]/g;
  const quote = /[\\]./g;
  let i = 0;
  let out = '';
  while (i >= 0 && i < s.length) {
    octal.lastIndex = i;
    quote.lastIndex = i;
    const o = octal.exec(s);
    const q = quote.exec(s);
    if (!o && !q) {
      out += s.slice(i);
      break;
    }
    const j = o ? o.index : -1;
    const k = q ? q.index : -1;
    if (q && (!o || k < j)) {
      out += s.slice(i, k) + (s[k + 1] as string);
      i = k + 2;
    } else {
      out += s.slice(i, j) + String.fromCharCode(parseInt(s.slice(j + 1, j + 4), 8));
      i = j + 4;
    }
  }
  return out;
}

// starlette.requests.cookie_parser — last duplicate key wins.
function pyCookieParser(cookieString: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const chunk of cookieString.split(';')) {
    const eq = chunk.indexOf('=');
    const key = pyStrip(eq >= 0 ? chunk.slice(0, eq) : '');
    const val = pyStrip(eq >= 0 ? chunk.slice(eq + 1) : chunk);
    if (key || val) out.set(key, pyCookieUnquote(val));
  }
  return out;
}

// Starlette Headers.get → FIRST occurrence (latin-1 decoded, like rawHeaders).
function firstRawHeader(req: FastifyRequest, name: string): string | undefined {
  const raw = req.raw.rawHeaders;
  for (let i = 0; i + 1 < raw.length; i += 2) {
    if ((raw[i] as string).toLowerCase() === name) return raw[i + 1] as string;
  }
  return undefined;
}

function extractSessionToken(req: FastifyRequest): string | null {
  const cookieHeader = firstRawHeader(req, 'cookie');
  if (cookieHeader !== undefined) {
    const t = pyCookieParser(cookieHeader).get('session_token');
    if (t) return t;
  }
  const auth = firstRawHeader(req, 'authorization') ?? '';
  if (auth.startsWith('Bearer ')) {
    const t = auth.slice(7);
    if (t) return t;
  }
  return null;
}

// ── CPython 3.11 C `datetime.fromisoformat` (Modules/_datetimemodule.c) ──
// Faithful port over the UTF-8 bytes (PyUnicode_AsUTF8AndSize) with the C
// NUL terminator modelled by `at()`. Returns UTC epoch ms, or null where
// Python raises ValueError. Naive results are treated as UTC (auth.py).
const DAYS_BEFORE_MONTH = [0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
const DAYS_IN_MONTH = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const isLeap = (y: number): boolean => y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
const daysInMonth = (y: number, m: number): number => (m === 2 && isLeap(y) ? 29 : (DAYS_IN_MONTH[m] as number));
const daysBeforeYear = (y: number): number => {
  const x = y - 1;
  return x * 365 + Math.floor(x / 4) - Math.floor(x / 100) + Math.floor(x / 400);
};
const ymdToOrd = (y: number, m: number, d: number): number =>
  daysBeforeYear(y) + (DAYS_BEFORE_MONTH[m] as number) + (m > 2 && isLeap(y) ? 1 : 0) + d;

// ord_to_ymd (C)
function ordToYmd(ordinal: number): [number, number, number] {
  let n = ordinal - 1;
  const n400 = Math.floor(n / 146097); n %= 146097; if (n < 0) n += 146097;
  let year = n400 * 400 + 1;
  const n100 = Math.floor(n / 36524); n %= 36524;
  const n4 = Math.floor(n / 1461); n %= 1461;
  const n1 = Math.floor(n / 365); n %= 365;
  year += n100 * 100 + n4 * 4 + n1;
  if (n1 === 4 || n100 === 4) return [year - 1, 12, 31];
  const leap = n1 === 3 && (n4 !== 24 || n100 === 3);
  let month = (n + 50) >> 5;
  let preceding = (DAYS_BEFORE_MONTH[month] as number) + (month > 2 && leap ? 1 : 0);
  if (preceding > n) {
    month -= 1;
    preceding -= (DAYS_IN_MONTH[month] as number) + (month === 2 && leap ? 1 : 0);
  }
  return [year, month, n - preceding + 1];
}

class IsoBuf {
  constructor(readonly b: Uint8Array) {}
  at(i: number): number { return i >= 0 && i < this.b.length ? (this.b[i] as number) : 0; }
  digit(i: number): boolean { const c = this.at(i); return c >= 0x30 && c <= 0x39; }
  // parse_digits: accumulate n ASCII digits at p → [value, newP] | null
  digits(p: number, n: number, init = 0): [number, number] | null {
    let v = init;
    for (let k = 0; k < n; k++) {
      const t = this.at(p++) - 0x30;
      if (t < 0 || t > 9) return null;
      v = v * 10 + t;
    }
    return [v, p];
  }
}

// _find_isoformat_datetime_separator (C)
function isoFindSeparator(s: IsoBuf, len: number): number {
  if (len === 7) return 7;
  if (s.at(4) === 0x2d) {
    if (s.at(5) === 0x57) {
      if (len < 8) return -1;
      if (len > 8 && s.at(8) === 0x2d) {
        if (len === 9) return -1;
        if (len > 10 && s.digit(10)) return 8;
        return 10;
      }
      return 8;
    }
    return 10;
  }
  if (s.at(4) === 0x57) {
    let idx = 7;
    for (; idx < len; ++idx) if (!s.digit(idx)) break;
    if (idx < 9) return idx;
    return idx % 2 === 0 ? 7 : 8;
  }
  return 8;
}

// parse_isoformat_date (C): 0 ok, <0 error
function isoParseDate(s: IsoBuf, len: number, out: number[]): number {
  let r = s.digits(0, 4);
  if (!r) return -1;
  out[0] = r[0];
  let p = r[1];
  const usesSep = s.at(p) === 0x2d;
  if (usesSep) ++p;
  if (s.at(p) === 0x57) {
    p++;
    r = s.digits(p, 2);
    if (!r) return -3;
    const isoWeek = r[0];
    p = r[1];
    let isoDay: number;
    if (p < len) {
      if (usesSep && s.at(p++) !== 0x2d) return -2;
      r = s.digits(p, 1);
      if (!r) return -4;
      isoDay = r[0];
    } else {
      isoDay = 1;
    }
    // iso_to_ymd (C)
    const y = out[0];
    if (isoWeek <= 0 || isoWeek >= 53) {
      let outOfRange = true;
      if (isoWeek === 53) {
        const firstWeekday = (ymdToOrd(y, 1, 1) + 6) % 7;
        if (firstWeekday === 3 || (firstWeekday === 2 && isLeap(y))) outOfRange = false;
      }
      if (outOfRange) return -2;
    }
    if (isoDay <= 0 || isoDay >= 8) return -3;
    const firstDay = ymdToOrd(y, 1, 1);
    const firstWeekday = (firstDay + 6) % 7;
    let week1Monday = firstDay - firstWeekday;
    if (firstWeekday > 3) week1Monday += 7;
    const ymd = ordToYmd(week1Monday + (isoWeek - 1) * 7 + isoDay - 1);
    out[0] = ymd[0]; out[1] = ymd[1]; out[2] = ymd[2];
    return 0;
  }
  r = s.digits(p, 2);
  if (!r) return -1;
  out[1] = r[0];
  p = r[1];
  if (usesSep && s.at(p++) !== 0x2d) return -2;
  r = s.digits(p, 2);
  if (!r) return -3;
  out[2] = r[0];
  return 0;
}

// parse_hh_mm_ss_ff (C): <0 error, 0 end-of-string, 1 more follows
function isoParseHhMmSsFf(s: IsoBuf, start: number, end: number, out: number[]): number {
  out[0] = out[1] = out[2] = out[3] = 0;
  let p = start;
  let hasSep = true;
  for (let i = 0; i < 3; ++i) {
    const r = s.digits(p, 2);
    if (!r) return -3;
    out[i] = r[0];
    p = r[1];
    const c = s.at(p++);
    if (i === 0) hasSep = c === 0x3a;
    if (p >= end) return c !== 0 ? 1 : 0;
    else if (hasSep && c === 0x3a) continue;
    else if (c === 0x2e || c === 0x2c) break;
    else if (!hasSep) --p;
    else return -4;
  }
  const remains = end - p;
  const toParse = remains >= 6 ? 6 : remains;
  const r = s.digits(p, toParse);
  if (!r) return -3;
  let micro = r[0];
  p = r[1];
  const correction = [100000, 10000, 1000, 100, 10];
  if (toParse < 6) micro *= correction[toParse - 1] ?? Number.NaN;
  out[3] = micro;
  while (s.digit(p)) ++p;
  return s.at(p) !== 0 ? 1 : 0;
}

// parse_isoformat_time (C): 0 naive, 1 aware, <0 error
function isoParseTime(s: IsoBuf, start: number, len: number, out: number[], tz: number[]): number {
  const end = start + len;
  let tzPos = start;
  do {
    const c = s.at(tzPos);
    if (c === 0x5a || c === 0x2b || c === 0x2d) break;
  } while (++tzPos < end);
  let rv = isoParseHhMmSsFf(s, start, tzPos, out);
  if (rv < 0) return rv;
  if (tzPos === end) return rv === 1 ? -5 : 0;
  if (s.at(tzPos) === 0x5a) {
    tz[0] = 0; tz[1] = 0;
    return s.at(tzPos + 1) !== 0 ? -5 : 1;
  }
  const sign = s.at(tzPos) === 0x2d ? -1 : 1;
  const z = [0, 0, 0, 0];
  rv = isoParseHhMmSsFf(s, tzPos + 1, end, z);
  tz[0] = sign * ((z[0] as number) * 3600 + (z[1] as number) * 60 + (z[2] as number));
  tz[1] = sign * (z[3] as number);
  return rv ? -5 : 1;
}

function pyFromIsoformatUtcMs(str: string): number | null {
  // len < 7 (code points) → ValueError. _sanitize_isoformat_str: the first
  // non-ASCII character found at code-point position 7, 8 or 10 (the only
  // possible separator slots) is replaced by 'T' before UTF-8 encoding.
  const cps = [...str];
  if (cps.length < 7) return null;
  for (const pos of [7, 8, 10]) {
    if (pos > cps.length) break;
    const c = cps[pos];
    if (c !== undefined && (c.codePointAt(0) as number) > 127) {
      cps[pos] = 'T';
      break;
    }
  }
  const s = new IsoBuf(new Uint8Array(Buffer.from(cps.join(''), 'utf8')));
  const len = s.b.length;
  const sep = isoFindSeparator(s, len);
  if (sep < 0) return null;
  const date = [0, 0, 0];
  const time = [0, 0, 0, 0];
  const tz = [0, 0];
  let rv = isoParseDate(s, sep, date);
  if (!rv && len > sep) rv = isoParseTime(s, sep + 1, len - sep - 1, time, tz);
  if (rv < 0) return null;
  const [y, m, d] = date as [number, number, number];
  const [hh, mi, ss, us] = time as [number, number, number, number];
  // new_datetime argument checks + timezone() range (strictly within ±24h)
  if (y < 1 || y > 9999 || m < 1 || m > 12 || d < 1 || d > daysInMonth(y, m)) return null;
  if (hh > 23 || mi > 59 || ss > 59 || !(us >= 0 && us <= 999999)) return null;
  const offUs = rv === 1 ? BigInt(tz[0] as number) * 1_000_000n + BigInt(tz[1] as number) : 0n;
  if ((offUs < 0n ? -offUs : offUs) >= 86_400_000_000n) return null;
  const dt = new Date(0);
  dt.setUTCFullYear(y, m - 1, d);
  dt.setUTCHours(hh, mi, ss, 0);
  // exact microseconds, then floor to ms (Python `(dt - epoch) // 1ms`)
  const totalUs = BigInt(dt.getTime()) * 1000n + BigInt(us) - offUs;
  const q = totalUs / 1000n;
  return Number(totalUs < 0n && q * 1000n !== totalUs ? q - 1n : q);
}

function expiresAtMs(raw: unknown): number {
  if (raw instanceof Date) {
    const t = raw.getTime();
    if (Number.isNaN(t)) throw new AuthServerError('expires_at: invalid date');
    return t; // naive BSON datetime → UTC (Python .replace(tzinfo=utc))
  }
  if (typeof raw === 'string') {
    const t = pyFromIsoformatUtcMs(raw);
    if (t === null) throw new AuthServerError('expires_at: invalid isoformat'); // ValueError → 500
    return t;
  }
  throw new AuthServerError('expires_at: no tzinfo'); // None / missing / other → AttributeError → 500
}

export async function authenticate(req: FastifyRequest, db: Db): Promise<AuthUser> {
  // 1. Token.
  const token = extractSessionToken(req);
  if (!token) throw new HttpError(401, 'Not authenticated');

  // 2. Session.
  const session = await db.collection<Doc>('user_sessions').findOne({ session_token: token }, { projection: { _id: 0 } });
  if (!session) throw new HttpError(401, 'Invalid session');

  // 3. Expiry.
  if (expiresAtMs(session['expires_at']) < Date.now()) throw new HttpError(401, 'Session expired');

  // 4. (Python rolling-refresh write — intentionally not ported.)

  // 5. users — session["user_id"] (KeyError → 500); `if not user` → 401.
  if (!has(session, 'user_id')) throw new AuthServerError('session: KeyError user_id');
  const user = await db.collection<Doc>('users').findOne(
    { user_id: session['user_id'] ?? null }, { projection: { _id: 0 } },
  );
  if (!user || Object.keys(user).length === 0) throw new HttpError(401, 'User not found');

  // 6. team_members — user["email"] (KeyError → 500).
  if (!has(user, 'email')) throw new AuthServerError('users: KeyError email');
  const tm = await db.collection<Doc>('team_members').findOne(
    { email: user['email'] ?? null, active: true }, { projection: { _id: 0 } },
  );

  let scopeUserId: unknown;
  let effectiveRole: unknown;
  let isStaff: boolean;
  if (tm && Object.keys(tm).length > 0 && pyTruthy(tm['owner_user_id'])) {
    if (!has(user, 'user_id')) throw new AuthServerError('users: KeyError user_id');
    if (tm['owner_user_id'] !== user['user_id']) {
      scopeUserId = tm['owner_user_id'];
      effectiveRole = has(tm, 'role') ? tm['role'] : 'accountant';
      isStaff = true;
    } else {
      scopeUserId = user['user_id'];
      effectiveRole = 'owner';
      isStaff = false;
    }
  } else {
    scopeUserId = user['user_id'];
    effectiveRole = 'owner';
    isStaff = false;
  }

  // Masking role chain: `effective_role or user.role` (consumers add `or ""`).
  const roleChain = pyTruthy(effectiveRole) ? effectiveRole : user['role'];
  return {
    user_id: scopeUserId as string,
    effective_role: (pyTruthy(roleChain) ? roleChain : '') as string,
    is_staff: isStaff,
    ...(typeof user['email'] === 'string' ? { email: user['email'] } : {}),
  };
}
