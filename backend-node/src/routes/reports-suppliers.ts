import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-8e · Reports supplier list read-only shadow.
 *
 *   GET /api/reports/suppliers
 *
 * Faithful shadow of:
 *   backend/routers/reports.py::list_suppliers (L480-516)
 *
 * Python (verbatim):
 * ```
 * @router.get("/reports/suppliers")
 * async def list_suppliers(request: Request, user=Depends(get_current_user)):
 *     uid = user["user_id"]
 *     cid = await _active_company_id(request, user)
 *     trip_sups = await db.trips.distinct(
 *         "supplier_name", {"user_id": uid, "company_id": cid, "vehicle_type": "supplier"})
 *     veh_sups = await db.vehicles.distinct(
 *         "supplier_name", {"user_id": uid, "company_id": cid, "vehicle_type": "supplier"})
 *     seen = set()
 *     result = []
 *     for name in (trip_sups + veh_sups):
 *         n = (name or "").strip()
 *         key = n.lower()
 *         if not n or key in seen:
 *             continue
 *         seen.add(key)
 *         mob = ""
 *         v = await db.vehicles.find_one(
 *             {"user_id": uid, "company_id": cid, "vehicle_type": "supplier",
 *              "supplier_name": {"$regex": f"^{n}$", "$options": "i"}},
 *             {"_id": 0, "supplier_mobile": 1, "owner_phone": 1})
 *         if v:
 *             mob = (v.get("supplier_mobile") or v.get("owner_phone") or "").strip()
 *         result.append({"name": n, "mobile": mob})
 *     result.sort(key=lambda x: x["name"].lower())
 *     return result
 * ```
 *
 * STRICTLY READ-ONLY. distinct(trips) → distinct(vehicles) → one
 * vehicles.find_one per newly seen name, strictly in that order. No writes.
 *
 * ── GATE-8e BINDINGS ────────────────────────────────────────────────
 *
 *   1. ORDER: auth (locked 401 literals) → `_active_company_id` (locked
 *      tenant helper) → reads. No query parameters (all ignored).
 *
 *   2. NAMES: iterate trip values then vehicle values, each in server
 *      distinct order. `(name or "")` — any Python-falsy value (None / "" /
 *      0 / 0.0 / False / {} / []) is skipped; `.strip()` on a truthy
 *      non-string (number, bool, date, dict, list, ObjectId, Decimal128 …)
 *      raises AttributeError → 500 AT THAT POSITION (earlier lookups have
 *      already run). strip() = CPython str.isspace set. De-dupe key and sort
 *      key = CPython 3.11 `str.lower()` (Unicode 14.0; see pyLower).
 *
 *   3. LOOKUP (per new name, sequential): vehicles.find_one({user_id,
 *      company_id, vehicle_type:"supplier", supplier_name: {$regex:
 *      "^" + n + "$", $options: "i"}}, {_id:0, supplier_mobile:1,
 *      owner_phone:1}) — the name is NOT escaped (Python contract): regex
 *      metacharacters keep their meaning and an invalid pattern makes
 *      MongoDB fail the query → unhandled → 500.
 *
 *   4. MOBILE: `supplier_mobile or owner_phone or ""` (first Python-truthy
 *      value) then strip(); a truthy non-string → 500.
 *
 *   5. SORT: Python sorts str by CODE POINT (not UTF-16 unit, not locale)
 *      on name.lower(); keys are unique after de-dupe.
 *
 *   6. RESPONSE: JSON array of {"name", "mobile"}; exact `application/json`;
 *      any unhandled failure → 500 `Internal Server Error` (text/plain).
 *
 *   7. HEAD: FastAPI answers 405 + `allow: GET` (verified live) — Fastify
 *      auto-HEAD disabled for this route and the 405 reproduced explicitly.
 *
 * Not reproduced (theoretical, recorded): a BSON Binary supplier_name /
 * mobile decodes to Python `bytes`, which has .strip(); Node answers 500.
 */

type Doc = Record<string, unknown>;

class PyServerError extends Error {}

const bsonType = (v: unknown): string | undefined =>
  typeof v === 'object' && v !== null ? ((v as { _bsontype?: string })._bsontype) : undefined;

// Python truthiness for values decoded with promoteValues:false.
function pyTruthy(v: unknown): boolean {
  if (v === null || v === undefined) return false;
  if (typeof v === 'boolean') return v;
  if (typeof v === 'string') return v.length > 0;
  if (typeof v === 'number') return v !== 0;
  if (Array.isArray(v)) return v.length > 0;
  if (v instanceof Date) return true;
  const t = bsonType(v);
  if (t === 'Double' || t === 'Int32') return (v as { value: number }).value !== 0; // NaN is truthy
  if (t === 'Long') return !(v as { isZero(): boolean }).isZero();
  if (t === 'Binary') return (v as { length(): number }).length() > 0;
  if (t !== undefined) return true; // ObjectId, Decimal128, Timestamp, Regex, MinKey, …
  return Object.keys(v as object).length > 0;
}

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

// `(x or "").strip()` — falsy → "", str → stripped, anything else → AttributeError.
function orEmptyStrip(v: unknown): string {
  if (!pyTruthy(v)) return '';
  if (typeof v !== 'string') throw new PyServerError('AttributeError: .strip() on non-str');
  return pyStrip(v);
}

// ── CPython 3.11 (Unicode 14.0) str.lower() ───────────────────────────
// Code points unassigned in Unicode 14 but assigned in Node's ICU (Unicode
// 17): Python leaves them unchanged AND treats them as neither cased nor
// case-ignorable, so splitting at them and lowercasing each segment is
// exact (incl. Final_Sigma). Verified: every code point + a 40 000-string
// randomized Final_Sigma corpus, 0 mismatches (plain toLowerCase: 10 434).
const POST_14_ASSIGNED: ReadonlyArray<readonly [number, number]> = [
  [0x88f, 0x88f], [0x897, 0x897], [0xc5c, 0xc5c], [0xcdc, 0xcdc], [0xcf3, 0xcf3], [0xece, 0xece],
  [0x1acf, 0x1add], [0x1ae0, 0x1aeb], [0x1b4e, 0x1b4f], [0x1b7f, 0x1b7f], [0x1c89, 0x1c8a], [0x20c1, 0x20c1],
  [0x2427, 0x2429], [0x2b96, 0x2b96], [0x2ffc, 0x2fff], [0x31e4, 0x31e5], [0x31ef, 0x31ef], [0xa7cb, 0xa7cf],
  [0xa7d2, 0xa7d2], [0xa7d4, 0xa7d4], [0xa7da, 0xa7dc], [0xa7f1, 0xa7f1], [0xfbc3, 0xfbd2], [0xfd90, 0xfd91],
  [0xfdc8, 0xfdce], [0x105c0, 0x105f3], [0x10940, 0x10959], [0x10d40, 0x10d65], [0x10d69, 0x10d85],
  [0x10d8e, 0x10d8f], [0x10ec2, 0x10ec7], [0x10ed0, 0x10ed8], [0x10efa, 0x10eff], [0x1123f, 0x11241],
  [0x11380, 0x11389], [0x1138b, 0x1138b], [0x1138e, 0x1138e], [0x11390, 0x113b5], [0x113b7, 0x113c0],
  [0x113c2, 0x113c2], [0x113c5, 0x113c5], [0x113c7, 0x113ca], [0x113cc, 0x113d5], [0x113d7, 0x113d8],
  [0x113e1, 0x113e2], [0x116d0, 0x116e3], [0x11b00, 0x11b09], [0x11b60, 0x11b67], [0x11bc0, 0x11be1],
  [0x11bf0, 0x11bf9], [0x11db0, 0x11ddb], [0x11de0, 0x11de9], [0x11f00, 0x11f10], [0x11f12, 0x11f3a],
  [0x11f3e, 0x11f5a], [0x1342f, 0x1342f], [0x13439, 0x13455], [0x13460, 0x143fa], [0x16100, 0x16139],
  [0x16d40, 0x16d79], [0x16ea0, 0x16eb8], [0x16ebb, 0x16ed3], [0x16ff2, 0x16ff6], [0x187f8, 0x187ff],
  [0x18cff, 0x18cff], [0x18d09, 0x18d1e], [0x18d80, 0x18df2], [0x1b132, 0x1b132], [0x1b155, 0x1b155],
  [0x1cc00, 0x1ccfc], [0x1cd00, 0x1ceb3], [0x1ceba, 0x1ced0], [0x1cee0, 0x1cef0], [0x1d2c0, 0x1d2d3],
  [0x1df25, 0x1df2a], [0x1e030, 0x1e06d], [0x1e08f, 0x1e08f], [0x1e4d0, 0x1e4f9], [0x1e5d0, 0x1e5fa],
  [0x1e5ff, 0x1e5ff], [0x1e6c0, 0x1e6de], [0x1e6e0, 0x1e6f5], [0x1e6fe, 0x1e6ff], [0x1f6d8, 0x1f6d8],
  [0x1f6dc, 0x1f6dc], [0x1f774, 0x1f77f], [0x1f7d9, 0x1f7d9], [0x1f8b2, 0x1f8bb], [0x1f8c0, 0x1f8c1],
  [0x1f8d0, 0x1f8d8], [0x1fa54, 0x1fa57], [0x1fa75, 0x1fa77], [0x1fa87, 0x1fa8a], [0x1fa8e, 0x1fa8f],
  [0x1faad, 0x1faaf], [0x1fabb, 0x1fabf], [0x1fac6, 0x1fac6], [0x1fac8, 0x1fac8], [0x1facd, 0x1facf],
  [0x1fada, 0x1fadc], [0x1fadf, 0x1fadf], [0x1fae8, 0x1faea], [0x1faef, 0x1faef], [0x1faf7, 0x1faf8],
  [0x1fbcb, 0x1fbef], [0x1fbfa, 0x1fbfa], [0x2b739, 0x2b73f], [0x2cea2, 0x2cead], [0x2ebf0, 0x2ee5d],
  [0x31350, 0x33479],
];

function isPost14(cp: number): boolean {
  let lo = 0;
  let hi = POST_14_ASSIGNED.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const [a, b] = POST_14_ASSIGNED[mid] as readonly [number, number];
    if (cp < a) hi = mid - 1;
    else if (cp > b) lo = mid + 1;
    else return true;
  }
  return false;
}

function pyLower(s: string): string {
  let out = '';
  let seg = '';
  for (const ch of s) {
    if (isPost14(ch.codePointAt(0) as number)) {
      out += seg.toLowerCase() + ch;
      seg = '';
    } else {
      seg += ch;
    }
  }
  return out + seg.toLowerCase();
}

// Python str ordering: lexicographic by code point.
function pyStrCmp(a: string, b: string): number {
  const x = [...a];
  const y = [...b];
  const n = Math.min(x.length, y.length);
  for (let i = 0; i < n; i++) {
    const d = (x[i] as string).codePointAt(0)! - (y[i] as string).codePointAt(0)!;
    if (d !== 0) return d;
  }
  return x.length - y.length;
}

// JSON responses of this route are exactly `application/json` (no charset).
const sendJson = (reply: FastifyReply, status: number, body: string): FastifyReply =>
  reply.code(status).header('content-type', 'application/json').send(Buffer.from(body, 'utf8'));

const METHOD_NOT_ALLOWED = Buffer.from('{"detail":"Method Not Allowed"}', 'utf8');

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerReportsSuppliersRoute(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-8e (read-only)
  app.get('/api/reports/suppliers', { exposeHeadRoute: false }, async (req: FastifyRequest, reply: FastifyReply) => {
    // 1. Auth FIRST — locked 401 literals.
    let uid: string;
    try {
      uid = (await authenticate(req, db)).user_id;
    } catch (err) {
      if (err instanceof HttpError) return sendJson(reply, err.status, JSON.stringify({ detail: err.detail }));
      throw err;
    }

    // 2. Active-company resolution (locked helper).
    const cid = await activeCompanyId(req, uid, db);

    try {
      const scope = (): Doc => ({ user_id: uid, company_id: cid, vehicle_type: 'supplier' });
      // 3. READ #1 / READ #2 — distinct, in Python order, no limit.
      const tripSups = (await db.collection<Doc>('trips')
        .distinct('supplier_name', scope() as Filter<Doc>, { promoteValues: false })) as unknown[];
      const vehSups = (await db.collection<Doc>('vehicles')
        .distinct('supplier_name', scope() as Filter<Doc>, { promoteValues: false })) as unknown[];

      // 4. De-dupe on pyLower(strip(name)); one sequential lookup per new name.
      const seen = new Set<string>();
      const result: { name: string; mobile: string; key: string }[] = [];
      for (const name of [...tripSups, ...vehSups]) {
        const n = orEmptyStrip(name);
        const key = pyLower(n);
        if (!n || seen.has(key)) continue;
        seen.add(key);
        let mob = '';
        const v = await db.collection<Doc>('vehicles').findOne(
          { ...scope(), supplier_name: { $regex: `^${n}$`, $options: 'i' } } as Filter<Doc>,
          { projection: { _id: 0, supplier_mobile: 1, owner_phone: 1 }, promoteValues: false },
        );
        if (v !== null && pyTruthy(v)) {
          const sm = v['supplier_mobile'];
          mob = orEmptyStrip(pyTruthy(sm) ? sm : v['owner_phone']);
        }
        result.push({ name: n, mobile: mob, key });
      }

      // 5. Python sort — code-point order on name.lower() (keys unique).
      result.sort((a, b) => pyStrCmp(a.key, b.key));
      return sendJson(reply, 200,
        `[${result.map((r) => `{"name":${JSON.stringify(r.name)},"mobile":${JSON.stringify(r.mobile)}}`).join(',')}]`);
    } catch {
      // Any unhandled Python exception (AttributeError, OperationFailure on an
      // invalid regex, …) → Starlette ServerErrorMiddleware plain 500.
      return reply.code(500).header('content-type', 'text/plain; charset=utf-8').send('Internal Server Error');
    }
  });

  // FastAPI registers GET only on this path → HEAD is 405 before auth (verified live).
  app.head('/api/reports/suppliers', async (_req: FastifyRequest, reply: FastifyReply) =>
    reply.code(405).header('allow', 'GET').header('content-type', 'application/json').send(METHOD_NOT_ALLOWED));
}
