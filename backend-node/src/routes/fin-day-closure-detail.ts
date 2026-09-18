import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7n · Fin day-closure detail read-only shadow.
 *
 *   GET /api/fin/day-closures/:close_date
 *
 * Faithful shadow of:
 *   backend/routers/fin_day_closing.py::get_closure (L249-264)
 *
 * STRICTLY READ-ONLY. Class-C — Python handler executes ONLY
 *   db.fin_day_closures.find_one({user_id, company_id, close_date},
 *                                {_id: 0, user_id: 0})
 * Zero writer hook / audit / snapshot capture / FinTxn read / backfill.
 *
 * ── GATE-7n BINDINGS ────────────────────────────────────────────────
 *
 *   1. ORDER (verified live): auth → `_parse_iso_date(close_date)` →
 *      `_active_company_id` → find_one. Unauthenticated → 401 literals even
 *      for a malformed date.
 *
 *   2. `_parse_iso_date` = CPython 3.11 C `date.fromisoformat`:
 *        * UTF-8 BYTE length must be 7, 8 or 10
 *        * ASCII digits only; `YYYY[-]MM[-]DD` or ISO week
 *          `YYYY[-]Www[[-]D]`, separator use must be consistent
 *        * bytes past the parsed fields are ignored ("2026050112" is valid)
 *        * resulting date must be 0001-01-01 … 9999-12-31
 *      Failure → 400 {"detail": "close_date must be ISO YYYY-MM-DD"}.
 *
 *   3. The RAW path segment (not a normalised date) is used both in the
 *      Mongo filter and in the 404 literal:
 *        404 {"detail": "No closure exists for <close_date>"}
 *
 *   4. PROJECTION strips `_id` AND `user_id`. Bare document response.
 *
 *   5. ENCODED SLASH — Starlette routes on the percent-DECODED path, so a
 *      segment containing "/" (e.g. `2026%2F05%2F01`) never reaches this
 *      handler in Python → 404 {"detail":"Not Found"} before auth. Fastify
 *      routes on the raw path and would match, so the handler reproduces
 *      that 404 first. (A decoded path that lands on another Python route,
 *      e.g. `x%2Flate-entries`, is a framework-routing gap tracked for the
 *      dedicated framework gate.)
 *
 * Fin day-closing writer boundary (Python-authoritative, out of scope):
 *   POST /api/fin/day-closures · POST /api/fin/day-closures/{d}/reopen
 *   GET  /api/fin/day-closures/{d}/late-entries remains Python-only.
 */

interface FinDayClosureDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  close_date?: string;
  [k: string]: unknown;
}

// ── CPython 3.11 `_datetimemodule.c` date arithmetic (C truncation) ──
const DAYS_BEFORE_MONTH = [0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
const DAYS_IN_MONTH = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

const isLeap = (y: number): boolean => y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);

function daysInMonth(y: number, m: number): number {
  return m === 2 && isLeap(y) ? 29 : (DAYS_IN_MONTH[m] as number);
}

function daysBeforeYear(y: number): number {
  const x = y - 1;
  return x * 365 + Math.trunc(x / 4) - Math.trunc(x / 100) + Math.trunc(x / 400);
}

function ymdToOrd(y: number, m: number, d: number): number {
  return daysBeforeYear(y) + (DAYS_BEFORE_MONTH[m] as number) + (m > 2 && isLeap(y) ? 1 : 0) + d;
}

// Proleptic-Gregorian ordinal → year only (month/day are valid by construction).
function ordToYear(ord: number): number {
  let n = ord - 1;
  const n400 = Math.floor(n / 146097); n -= n400 * 146097;
  const n100 = Math.floor(n / 36524); n -= n100 * 36524;
  const n4 = Math.floor(n / 1461); n -= n4 * 1461;
  const n1 = Math.floor(n / 365);
  const year = n400 * 400 + n100 * 100 + n4 * 4 + n1 + 1;
  return n1 === 4 || n100 === 4 ? year - 1 : year;
}

// `iso_to_ymd` + `new_date` range check. ISO year 0000 never yields a valid date.
function isoWeekDateValid(year: number, week: number, day: number): boolean {
  if (year < 1) return false;
  const jan1 = ymdToOrd(year, 1, 1);
  const firstWeekday = (jan1 + 6) % 7; // Monday = 0
  if (week <= 0 || week >= 53) {
    const has53 = week === 53 && (firstWeekday === 3 || (firstWeekday === 2 && isLeap(year)));
    if (!has53) return false;
  }
  if (day <= 0 || day >= 8) return false;
  const week1Monday = jan1 - firstWeekday + (firstWeekday > 3 ? 7 : 0);
  const y = ordToYear(week1Monday + (week - 1) * 7 + day - 1);
  return y >= 1 && y <= 9999;
}

// CPython 3.11 C `date.fromisoformat` acceptance (no normalisation needed:
// Python discards the parsed value and queries with the raw string).
function pyDateFromIsoformatOk(s: string): boolean {
  const b = Buffer.from(s, 'utf8');
  const len = b.length;
  if (len !== 7 && len !== 8 && len !== 10) return false;
  const at = (i: number): number => (i < len ? (b[i] as number) : 0); // NUL-terminated
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
  if (year === null) return false;
  const sep = at(p) === 0x2d;
  if (sep) p++;

  if (at(p) === 0x57 /* W */) {
    p++;
    const week = digits(2);
    if (week === null) return false;
    let day = 1;
    if (p < len) {
      if (sep && at(p++) !== 0x2d) return false;
      const d = digits(1);
      if (d === null) return false;
      day = d;
    }
    return isoWeekDateValid(year, week, day);
  }

  const month = digits(2);
  if (month === null) return false;
  if (sep && at(p++) !== 0x2d) return false;
  const day = digits(2);
  if (day === null) return false;
  if (year < 1 || year > 9999 || month < 1 || month > 12) return false;
  return day >= 1 && day <= daysInMonth(year, month);
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerFinDayClosureDetailRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7n (read-only)
  app.get('/api/fin/day-closures/:close_date', async (req: FastifyRequest, reply: FastifyReply) => {
    const closeDate = (req.params as { close_date: string }).close_date;

    // 0. Starlette never routes a decoded "/" into a path param.
    if (closeDate.includes('/')) {
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

    // 2. `_parse_iso_date(close_date)` — before company resolution.
    if (!pyDateFromIsoformatOk(closeDate)) {
      reply.code(400);
      return { detail: 'close_date must be ISO YYYY-MM-DD' };
    }

    // 3. Active-company resolution (locked helper).
    const cid = await activeCompanyId(req, userId, db);

    // 4. Single read with EXACT filter / projection (raw close_date).
    const doc = await db
      .collection<FinDayClosureDoc>('fin_day_closures')
      .findOne(
        { user_id: userId, company_id: cid, close_date: closeDate } as Filter<FinDayClosureDoc>,
        { projection: { _id: 0, user_id: 0 } },
      );
    if (!doc) {
      reply.code(404);
      return { detail: `No closure exists for ${closeDate}` };
    }
    return doc;
  });
}
