/**
 * Focused parity for the two Finance reads deferred out of slice 2a:
 *
 *   GET /api/fin/day-status
 *   GET /api/fin/day-closures/{close_date}/late-entries
 *
 *   npx tsx scripts/fin-status-parity.ts --token <session token>
 *
 * Read-only: GETs only, against the local data copy. It also PROVES the two
 * endpoints write nothing, by fingerprinting both stores before and after the
 * whole run and comparing.
 *
 * Criterion
 * ---------
 * Everything is byte-identical except the ORDER of `late-entries.rows`, for
 * the reason slice 2a established for the day-book: MongoDB does not define
 * the order of documents that tie on the sort key, and `late_entries` sorts on
 * `txn_date` ALONE, so every row sharing a date is a tie. Measured on the real
 * copy: 658 rows in 33 date groups, of which only 9 positions coincide with a
 * mongo_id ordering, and not one group is ordered by `_id` ascending OR
 * descending. There is no key that reproduces it.
 *
 * So `rows` is compared as multisets within each tie group, and count, totals,
 * by_source_type and by_days_late_bucket must all match, the first two byte
 * for byte. A missing row, a row in the wrong date group, or any field
 * difference still fails.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { createHash } from 'node:crypto';
import { MongoClient } from 'mongodb';
import { Pool } from 'pg';

const args = process.argv.slice(2);
const argOf = (n: string, d = ''): string => {
  const i = args.indexOf(n);
  return i >= 0 && args[i + 1] ? (args[i + 1] as string) : d;
};
const PY = argOf('--py', 'http://127.0.0.1:8001');
const NEST = argOf('--nest', 'http://127.0.0.1:8003');
const TOKEN = argOf('--token');
const MONGO_URL = argOf('--mongo', 'mongodb://127.0.0.1:27017');
const MONGO_DB = argOf('--db', 'trukvia_local_20260921');
const PG_URL = argOf('--pg', 'postgres://postgres@127.0.0.1:5433/trukvia');

if (!TOKEN) {
  console.error('--token is required');
  process.exit(2);
}

interface LateEntries {
  close_date: string;
  count: number;
  totals: Record<string, unknown>;
  by_source_type: Record<string, number>;
  by_days_late_bucket: Record<string, number>;
  rows: Array<Record<string, unknown>>;
}

/** Group consecutive rows sharing txn_date, then compare each group as a set. */
function rowsMatchModuloTies(a: LateEntries['rows'], b: LateEntries['rows']): boolean {
  if (a.length !== b.length) return false;
  const key = (r: Record<string, unknown>): string => String(r['txn_date']);
  let i = 0;
  while (i < a.length) {
    const k = key(a[i] as Record<string, unknown>);
    let j = i;
    while (j < a.length && key(a[j] as Record<string, unknown>) === k) j += 1;
    for (let x = i; x < j; x += 1) {
      if (key(b[x] as Record<string, unknown>) !== k) return false;
    }
    const left = a.slice(i, j).map((r) => JSON.stringify(r)).sort();
    const right = b.slice(i, j).map((r) => JSON.stringify(r)).sort();
    if (JSON.stringify(left) !== JSON.stringify(right)) return false;
    i = j;
  }
  return true;
}

interface Case {
  path: string;
  note?: string;
  /** late-entries responses are compared tie-aware; everything else exact. */
  lateEntries?: boolean;
  noAuth?: boolean;
  /** Extra request headers, e.g. X-Company-Id for the isolation cases. */
  headers?: Record<string, string>;
}

const CLOSED = '2026-02-14'; // the one real closure in the local copy
/** The company that owns it, and another company owned by the SAME user. */
const OWNING_CO = 'co_c2ac839cf8bf4ff4';
const OTHER_CO = 'co_09e2044551cb4a69';

const CASES: Case[] = [
  // ── day-status: validation order ──────────────────────────────────────
  { path: '/api/fin/day-status?date=2026-01-01', noAuth: true, note: '401 before 422' },
  { path: '/api/fin/day-status', note: '422 missing date' },
  { path: '/api/fin/day-status?date=', note: '400 empty date' },
  { path: '/api/fin/day-status?date=not-a-date', note: '400 bad ISO' },
  { path: '/api/fin/day-status?date=2026-02-30', note: '400 impossible date' },
  { path: '/api/fin/day-status?date=2026-13-01', note: '400 month 13' },
  { path: '/api/fin/day-status?date=0000-01-01', note: '400 year 0' },
  // CPython 3.11 accepts more than YYYY-MM-DD — a regex guard would 400 these
  { path: '/api/fin/day-status?date=20260214', note: 'basic form, accepted' },
  { path: '/api/fin/day-status?date=2026-W07-6', note: 'ISO week date, accepted' },
  { path: '/api/fin/day-status?date=2026-W07', note: 'ISO week, no day' },
  { path: '/api/fin/day-status?date=2026-W99-1', note: '400 impossible week' },
  { path: '/api/fin/day-status?date=2026-02-14&date=2026-01-01', note: 'last key wins' },
  // ── day-status: data ──────────────────────────────────────────────────
  { path: `/api/fin/day-status?date=${CLOSED}`, note: 'the closed day' },
  { path: '/api/fin/day-status?date=2026-01-01', note: 'no closure -> two-key shape' },
  { path: '/api/fin/day-status?date=2020-01-01', note: 'far past, no closure' },
  { path: '/api/fin/day-status?date=2099-12-31', note: 'far future, no closure' },
  { path: '/api/fin/day-status?date=2026-02-13', note: 'day before the closure' },
  { path: '/api/fin/day-status?date=2026-02-15', note: 'day after the closure' },

  // ── late-entries: validation order ────────────────────────────────────
  { path: `/api/fin/day-closures/${CLOSED}/late-entries`, noAuth: true, note: '401' },
  { path: '/api/fin/day-closures/not-a-date/late-entries', note: '400 bad ISO' },
  { path: '/api/fin/day-closures/2026-02-30/late-entries', note: '400 impossible date' },
  // The date PARSES, but the lookup uses the raw string, and the stored
  // close_date is "2026-02-14" — so this is a 404, not a 200.
  { path: '/api/fin/day-closures/20260214/late-entries', note: 'basic form parses, still 404' },
  // ── late-entries: data ────────────────────────────────────────────────
  { path: `/api/fin/day-closures/${CLOSED}/late-entries`, lateEntries: true, note: 'the real case' },
  { path: '/api/fin/day-closures/2026-01-01/late-entries', note: '404 no closure' },
  { path: '/api/fin/day-closures/2020-01-01/late-entries', note: '404 far past' },
  { path: '/api/fin/day-closures/2099-12-31/late-entries', note: '404 far future' },

  // ── tenant / company isolation ────────────────────────────────────────
  // The closure exists for this USER, but under OWNING_CO. Scoped to another
  // of the same user's companies it must be invisible, not merely reordered.
  {
    path: `/api/fin/day-status?date=${CLOSED}`,
    headers: { 'x-company-id': OTHER_CO },
    note: 'other company -> not found shape',
  },
  {
    path: `/api/fin/day-closures/${CLOSED}/late-entries`,
    headers: { 'x-company-id': OTHER_CO },
    note: 'other company -> 404',
  },
  {
    path: `/api/fin/day-status?date=${CLOSED}`,
    headers: { 'x-company-id': OWNING_CO },
    note: 'owning company, explicit header',
  },
  {
    path: `/api/fin/day-closures/${CLOSED}/late-entries`,
    headers: { 'x-company-id': OWNING_CO },
    lateEntries: true,
    note: 'owning company, explicit header',
  },
  // An id belonging to NO user fails the ownership check, so Python falls back
  // to the default company — which is the one that owns the closure.
  {
    path: `/api/fin/day-status?date=${CLOSED}`,
    headers: { 'x-company-id': 'co_does_not_exist' },
    note: 'unowned company id -> falls back to default',
  },
  {
    path: `/api/fin/day-status?date=${CLOSED}`,
    headers: { 'x-company-id': '' },
    note: 'empty header is falsy -> default company',
  },
];

/**
 * A fingerprint of everything these endpoints could possibly touch, compared
 * before and after the run to prove neither writes.
 *
 * `fin_day_closures` is hashed in full — it is small, and it is the document a
 * day-status write would most plausibly touch. `fin_txn` is summarised by the
 * values a write would move. `audit_logs` and `companies` are counted, which
 * catches the two writes that could sneak in from the shared helpers: an audit
 * row, and `_get_or_create_default_company` creating a company.
 *
 * `user_sessions` is counted only, deliberately: Python's auth performs a
 * rolling session refresh at most once per 30s, so its CONTENT legitimately
 * changes during any run. That is authentication, not these endpoints, and it
 * is a pre-existing documented behaviour.
 */
async function fingerprint(): Promise<string> {
  const mc = await MongoClient.connect(MONGO_URL);
  const db = mc.db(MONGO_DB);
  const parts: string[] = [];

  const closures = await db.collection('fin_day_closures').find({}).sort({ _id: 1 }).toArray();
  parts.push(`fin_day_closures:${createHash('sha256').update(JSON.stringify(closures)).digest('hex')}`);

  const [txnAgg] = await db
    .collection('fin_txn')
    .aggregate([
      {
        $group: {
          _id: null,
          n: { $sum: 1 },
          amount: { $sum: '$amount' },
          maxCreated: { $max: '$created_at' },
          maxProjected: { $max: '$projected_at' },
          maxModified: { $max: '$modified_at' },
        },
      },
    ])
    .toArray();
  parts.push(`fin_txn:${JSON.stringify(txnAgg ?? {})}`);

  for (const coll of ['fin_accounts', 'audit_logs', 'companies', 'user_sessions', 'users']) {
    parts.push(`${coll}:${await db.collection(coll).countDocuments({})}`);
  }
  await mc.close();

  const pool = new Pool({ connectionString: PG_URL, max: 1 });
  for (const t of ['fin_txn', 'fin_day_closure', 'fin_account']) {
    const r = await pool.query(`SELECT count(*)::int AS n FROM trukvia.${t}`);
    parts.push(`pg.${t}:${r.rows[0].n}`);
  }
  const pgClosure = await pool.query(
    'SELECT id, status, closed_at, reopened_at, modified_at, snapshot::text FROM trukvia.fin_day_closure ORDER BY id',
  );
  parts.push(`pg.closures:${createHash('sha256').update(JSON.stringify(pgClosure.rows)).digest('hex')}`);
  await pool.end();
  return parts.join('|');
}

async function main(): Promise<void> {
  const before = await fingerprint();

  let pass = 0;
  let tieOnly = 0;
  let fail = 0;

  for (const c of CASES) {
    const headers: Record<string, string> = {
      ...(c.noAuth ? {} : { authorization: `Bearer ${TOKEN}` }),
      ...(c.headers ?? {}),
    };
    const [a, b] = await Promise.all([
      fetch(PY + c.path, { headers }),
      fetch(NEST + c.path, { headers }),
    ]);
    const [ta, tb] = [await a.text(), await b.text()];
    const label = `${c.path.slice(0, 60)}${c.note ? `  (${c.note})` : ''}`;

    if (a.status !== b.status) {
      fail += 1;
      console.log(`  FAIL  ${label}\n        status ${a.status} vs ${b.status}`);
      console.log(`        py  : ${ta.slice(0, 180)}`);
      console.log(`        nest: ${tb.slice(0, 180)}`);
      continue;
    }
    if (ta === tb) {
      pass += 1;
      console.log(`  PASS  ${label}  (${a.status})`);
      continue;
    }
    if (!c.lateEntries) {
      fail += 1;
      console.log(`  FAIL  ${label}\n        py  : ${ta.slice(0, 200)}\n        nest: ${tb.slice(0, 200)}`);
      continue;
    }
    const ja = JSON.parse(ta) as LateEntries;
    const jb = JSON.parse(tb) as LateEntries;
    /**
     * `by_source_type` is compared as a MAPPING: Python inserts each
     * source_type on its FIRST appearance while walking the rows, so its key
     * order is derived from the row order and inherits the same undefined-ness
     * as the rows themselves. It happens to agree on this data, but relying on
     * that would make the harness fail for a tenant whose ties fall the other
     * way — exactly what happened to day-book's `totals` on 2026-09-21.
     * `by_days_late_bucket` has a FIXED literal order and stays byte-exact.
     */
    const sortKeys = (o: Record<string, unknown>): Record<string, unknown> =>
      Object.fromEntries(Object.entries(o ?? {}).sort(([x], [y]) => (x < y ? -1 : 1)));
    const envelope = (j: LateEntries): string =>
      JSON.stringify({
        close_date: j.close_date,
        count: j.count,
        totals: j.totals,
        by_source_type: sortKeys(j.by_source_type),
        by_days_late_bucket: j.by_days_late_bucket,
      });
    if (envelope(ja) !== envelope(jb)) {
      fail += 1;
      console.log(`  FAIL  ${label}\n        aggregates differ`);
      console.log(`        py  : ${envelope(ja).slice(0, 220)}`);
      console.log(`        nest: ${envelope(jb).slice(0, 220)}`);
      continue;
    }
    if (rowsMatchModuloTies(ja.rows, jb.rows)) {
      tieOnly += 1;
      console.log(`  TIES  ${label}  (${ja.count} rows, identical modulo txn_date ties)`);
    } else {
      fail += 1;
      console.log(`  FAIL  ${label}\n        rows differ beyond sort ties`);
    }
  }

  const after = await fingerprint();
  const noWrites = before === after;
  console.log(
    `\n  ${noWrites ? 'PASS' : 'FAIL'}  no writes: MongoDB and PostgreSQL unchanged across the run`,
  );
  if (!noWrites) {
    console.log(`        before: ${before}`);
    console.log(`        after : ${after}`);
    fail += 1;
  } else {
    pass += 1;
  }

  console.log(`\ncases ${pass + tieOnly + fail}   BYTE-IDENTICAL ${pass}   TIE-EQUIVALENT ${tieOnly}   FAIL ${fail}`);
  console.log('criterion: byte-identical throughout; late-entries rows equal modulo undefined Mongo txn_date ties');
  process.exit(fail ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
