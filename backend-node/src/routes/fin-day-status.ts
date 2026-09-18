import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7o · Fin day-status read-only shadow.
 *
 *   GET /api/fin/day-status?date=YYYY-MM-DD
 *
 * Faithful shadow of:
 *   backend/routers/fin_day_closing.py::day_status (L326-362)
 *
 * STRICTLY READ-ONLY. Class-C — Python handler executes at most
 *   db.fin_day_closures.find_one({user_id, company_id, close_date: date},
 *     {_id:0, status:1, closed_at:1, closed_by:1, reopened_at:1, reopened_by:1})
 *   db.fin_txn.find_one({user_id, company_id, status:"active",
 *     txn_date:{$lte: date}, created_at:{$gt: closed_at}}, {_id:0, id:1})
 * Zero writer hook / audit / snapshot capture / backfill.
 *
 * ── GATE-7o BINDINGS ────────────────────────────────────────────────
 *
 *   1. ORDER (verified live): auth → required `date` (FastAPI 422 `missing`)
 *      → `if not date` 400 → `_parse_iso_date(date, field="date")` 400 →
 *      `_active_company_id` → reads. Auth precedes every validation.
 *
 *   2. 400 literals:
 *        ""        → {"detail": "date is required (YYYY-MM-DD)"}
 *        invalid   → {"detail": "date must be ISO YYYY-MM-DD"}
 *      Validation = CPython 3.11 C `date.fromisoformat` (see Gate 7n).
 *
 *   3. PYTHON TRUTHINESS is reproduced where Python branches on it:
 *        * `if not doc` — a projected closure with none of the five fields
 *          is `{}` → treated as NOT FOUND.
 *        * `doc.get("closed_at")` gates the fin_txn lookup.
 *        * `bool(find_one(...))` — a matching fin_txn without `id`
 *          projects to `{}` → False.
 *
 *   4. RESPONSE (key order preserved):
 *        not found → {date, is_closed: false}
 *        found     → {date, is_closed, status, closed_at, closed_by,
 *                     reopened_at, reopened_by, has_late_entries}
 *      `status` missing → null (dict.get); the other four missing → "".
 *      Present-but-null values stay null.
 *
 *   5. Repeated query keys → LAST occurrence (Starlette MultiDict.get).
 */

interface ClosureStatusDoc {
  status?: unknown;
  closed_at?: unknown;
  closed_by?: unknown;
  reopened_at?: unknown;
  reopened_by?: unknown;
  [k: string]: unknown;
}

// ── CPython 3.11 C `date.fromisoformat` acceptance (local copy, Gate 7n) ──
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

function ordToYear(ord: number): number {
  let n = ord - 1;
  const n400 = Math.floor(n / 146097); n -= n400 * 146097;
  const n100 = Math.floor(n / 36524); n -= n100 * 36524;
  const n4 = Math.floor(n / 1461); n -= n4 * 1461;
  const n1 = Math.floor(n / 365);
  const year = n400 * 400 + n100 * 100 + n4 * 4 + n1 + 1;
  return n1 === 4 || n100 === 4 ? year - 1 : year;
}

function isoWeekDateValid(year: number, week: number, day: number): boolean {
  if (year < 1) return false;
  const jan1 = ymdToOrd(year, 1, 1);
  const firstWeekday = (jan1 + 6) % 7;
  if (week <= 0 || week >= 53) {
    const has53 = week === 53 && (firstWeekday === 3 || (firstWeekday === 2 && isLeap(year)));
    if (!has53) return false;
  }
  if (day <= 0 || day >= 8) return false;
  const week1Monday = jan1 - firstWeekday + (firstWeekday > 3 ? 7 : 0);
  const y = ordToYear(week1Monday + (week - 1) * 7 + day - 1);
  return y >= 1 && y <= 9999;
}

function pyDateFromIsoformatOk(s: string): boolean {
  const b = Buffer.from(s, 'utf8');
  const len = b.length;
  if (len !== 7 && len !== 8 && len !== 10) return false;
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
  if (year === null) return false;
  const sep = at(p) === 0x2d;
  if (sep) p++;
  if (at(p) === 0x57) {
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

// ── Python truthiness for values Mongo can return ─────────────────────
function pyTruthy(v: unknown): boolean {
  if (v === null || v === undefined) return false;
  if (typeof v === 'boolean') return v;
  if (typeof v === 'number') return v !== 0; // NaN is truthy in Python too
  if (typeof v === 'bigint') return v !== 0n;
  if (typeof v === 'string') return v.length > 0;
  if (Array.isArray(v)) return v.length > 0;
  if (v instanceof Date) return true;
  const bsonType = (v as { _bsontype?: unknown })._bsontype;
  if (bsonType === 'Binary') return (v as { length(): number }).length() > 0;
  if (bsonType !== undefined) return true; // ObjectId, Decimal128, Timestamp, …
  return Object.keys(v as object).length > 0;
}

// Last occurrence wins for repeated keys (Starlette MultiDict.get).
function qParam(query: Record<string, unknown>, key: string): string | undefined {
  const v = query[key];
  if (v === undefined || v === null) return undefined;
  if (Array.isArray(v)) return v.length ? String(v[v.length - 1]) : undefined;
  return String(v);
}

const has = (o: object, k: string): boolean => Object.prototype.hasOwnProperty.call(o, k);

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerFinDayStatusRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7o (read-only)
  app.get('/api/fin/day-status', async (req: FastifyRequest, reply: FastifyReply) => {
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

    // 2. Required `date: str` — FastAPI/Pydantic v2 `missing` envelope.
    const date = qParam((req.query ?? {}) as Record<string, unknown>, 'date');
    if (date === undefined) {
      reply.code(422);
      return {
        detail: [{
          type: 'missing',
          loc: ['query', 'date'],
          msg: 'Field required',
          input: null,
          url: 'https://errors.pydantic.dev/2.13/v/missing',
        }],
      };
    }

    // 3. Handler-side validation (Python order).
    if (!date) {
      reply.code(400);
      return { detail: 'date is required (YYYY-MM-DD)' };
    }
    if (!pyDateFromIsoformatOk(date)) {
      reply.code(400);
      return { detail: 'date must be ISO YYYY-MM-DD' };
    }

    // 4. Active-company resolution (locked helper).
    const cid = await activeCompanyId(req, userId, db);

    // 5. Closure probe — exact filter / inclusion projection.
    const doc = await db
      .collection<ClosureStatusDoc>('fin_day_closures')
      .findOne(
        { user_id: userId, company_id: cid, close_date: date } as Filter<ClosureStatusDoc>,
        { projection: { _id: 0, status: 1, closed_at: 1, closed_by: 1, reopened_at: 1, reopened_by: 1 } },
      );
    if (!pyTruthy(doc)) {
      return { date, is_closed: false };
    }
    const d = doc as ClosureStatusDoc;
    const isClosed = d.status === 'closed';

    // 6. Late-entry flag — only when closed and closed_at is truthy.
    let hasLate = false;
    if (isClosed && pyTruthy(d.closed_at)) {
      const late = await db.collection('fin_txn').findOne(
        {
          user_id: userId, company_id: cid, status: 'active',
          txn_date: { $lte: date },
          created_at: { $gt: d.closed_at },
        },
        { projection: { _id: 0, id: 1 } },
      );
      hasLate = pyTruthy(late);
    }

    return {
      date,
      is_closed: isClosed,
      status: has(d, 'status') ? d.status : null,
      closed_at: has(d, 'closed_at') ? d.closed_at : '',
      closed_by: has(d, 'closed_by') ? d.closed_by : '',
      reopened_at: has(d, 'reopened_at') ? d.reopened_at : '',
      reopened_by: has(d, 'reopened_by') ? d.reopened_by : '',
      has_late_entries: hasLate,
    };
  });
}
