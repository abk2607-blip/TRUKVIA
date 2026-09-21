/**
 * Phase 6 · slice 2a — Finance read parity: NestJS (PostgreSQL) vs Python (MongoDB).
 *
 *   npx tsx scripts/fin-reads-parity.ts --token <session token> [--token2 <other tenant>]
 *
 * Criterion, and why it is not plain byte equality for day-book rows:
 *
 *   MongoDB does not define the order of documents that tie on the sort key.
 *   The day-book sorts on (txn_date DESC, created_at DESC), and real data has
 *   ties — verified on 2026-09-21 that Python returns tied rows in an order
 *   that is neither ascending nor descending by _id, and therefore cannot be
 *   reproduced from another engine. PostgreSQL uses mongo_id as a deterministic
 *   tie-break so OUR output is stable.
 *
 *   So: everything outside `rows` (envelope, totals, count) must be BYTE
 *   identical, and `rows` must match exactly once tied groups are compared as
 *   multisets. A row appearing in the wrong tie group, a missing row, or any
 *   field difference is still a failure.
 *
 * Read-only: GETs only, against the local data copy.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

const args = process.argv.slice(2);
const argOf = (n: string, d = ''): string => {
  const i = args.indexOf(n);
  return i >= 0 && args[i + 1] ? (args[i + 1] as string) : d;
};
const PY = argOf('--py', 'http://127.0.0.1:8001');
const NEST = argOf('--nest', 'http://127.0.0.1:8003');
const TOKENS = [argOf('--token'), argOf('--token2')].filter(Boolean);

if (!TOKENS.length) {
  console.error('--token is required');
  process.exit(2);
}

interface DayBook {
  date_from: string;
  date_to: string;
  rows: Array<Record<string, unknown>>;
  totals: Record<string, unknown>;
  count: number;
}

/** Group consecutive rows that share the sort key, then compare as multisets. */
function rowsMatchModuloTies(a: DayBook['rows'], b: DayBook['rows']): boolean {
  if (a.length !== b.length) return false;
  const key = (r: Record<string, unknown>): string => `${String(r['txn_date'])}|${String(r['created_at'])}`;
  let i = 0;
  while (i < a.length) {
    const k = key(a[i] as Record<string, unknown>);
    let j = i;
    while (j < a.length && key(a[j] as Record<string, unknown>) === k) j += 1;
    // the same window on the other side must carry the same sort key
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
  /** day-book responses are compared tie-aware; everything else byte-exact. */
  dayBook?: boolean;
  noAuth?: boolean;
}

const CASES: Case[] = [
  // day-book — ranges
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31', dayBook: true, note: 'full year' },
  { path: '/api/fin/day-book?date_from=2026-08-01&date_to=2026-09-30', dayBook: true },
  { path: '/api/fin/day-book?date_from=2026-09-14&date_to=2026-09-14', dayBook: true, note: 'single day' },
  { path: '/api/fin/day-book?date_from=2030-01-01&date_to=2030-12-31', dayBook: true, note: 'empty window' },
  { path: '/api/fin/day-book?date_from=2026-12-31&date_to=2026-01-01', dayBook: true, note: 'inverted range' },
  // day-book — limits
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31&limit=1', dayBook: true },
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31&limit=0', dayBook: true, note: 'clamped to 1' },
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31&limit=-5', dayBook: true, note: 'clamped to 1' },
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31&limit=999999', dayBook: true, note: 'clamped to 20000' },
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31&limit=abc', note: '422 int_parsing' },
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31&limit=', note: '422 empty limit' },
  // day-book — filters
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31&account_code=AR', dayBook: true },
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31&account_code=EXPENSE_DEFAULT', dayBook: true },
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31&account_code=NOPE', dayBook: true },
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31&source_type=expense', dayBook: true },
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31&source_type=invoice', dayBook: true },
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31&account_code=&source_type=', dayBook: true, note: 'empty filters ignored' },
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31&account_code=AR&account_code=SALES', dayBook: true, note: 'repeated key: last wins' },
  // day-book — validation
  { path: '/api/fin/day-book', note: '422 both missing' },
  { path: '/api/fin/day-book?date_from=2026-01-01', note: '422 date_to missing' },
  { path: '/api/fin/day-book?date_from=&date_to=', note: '400 empty values' },
  { path: '/api/fin/day-book?date_from=2026-01-01&date_to=2026-12-31', noAuth: true, note: '401' },
  // day-closures
  { path: '/api/fin/day-closures' },
  { path: '/api/fin/day-closures?limit=1' },
  { path: '/api/fin/day-closures?limit=999999', note: 'clamped to 5000' },
  { path: '/api/fin/day-closures?status=closed' },
  { path: '/api/fin/day-closures?status=nope' },
  { path: '/api/fin/day-closures?date_from=2026-01-01&date_to=2026-12-31' },
  { path: '/api/fin/day-closures?date_from=2030-01-01' },
  { path: '/api/fin/day-closures/2026-02-14', note: 'existing closure' },
  { path: '/api/fin/day-closures/2026-01-01', note: '404 envelope' },
  { path: '/api/fin/day-closures', noAuth: true, note: '401' },
];

async function main(): Promise<void> {
  let pass = 0;
  let tieOnly = 0;
  let fail = 0;

  for (const token of TOKENS) {
    for (const c of CASES) {
      const headers = c.noAuth ? {} : { authorization: `Bearer ${token}` };
      const [a, b] = await Promise.all([
        fetch(PY + c.path, { headers }),
        fetch(NEST + c.path, { headers }),
      ]);
      const [ta, tb] = [await a.text(), await b.text()];
      const label = `${c.path.slice(0, 68)}${c.note ? `  (${c.note})` : ''}`;

      if (a.status !== b.status) {
        fail += 1;
        console.log(`  FAIL  ${label}\n        status ${a.status} vs ${b.status}`);
        continue;
      }
      if (ta === tb) {
        pass += 1;
        continue;
      }
      if (!c.dayBook) {
        fail += 1;
        console.log(`  FAIL  ${label}\n        bytes differ (${ta.length} vs ${tb.length})`);
        continue;
      }
      // tie-aware comparison for day-book
      const ja = JSON.parse(ta) as DayBook;
      const jb = JSON.parse(tb) as DayBook;
      const envelopeA = JSON.stringify({ ...ja, rows: null });
      const envelopeB = JSON.stringify({ ...jb, rows: null });
      if (envelopeA !== envelopeB) {
        fail += 1;
        console.log(`  FAIL  ${label}\n        envelope/totals differ`);
        continue;
      }
      if (rowsMatchModuloTies(ja.rows, jb.rows)) {
        tieOnly += 1;
        console.log(`  TIES  ${label}  (${ja.count} rows, identical modulo sort ties)`);
      } else {
        fail += 1;
        console.log(`  FAIL  ${label}\n        rows differ beyond sort ties`);
      }
    }
  }

  const total = pass + tieOnly + fail;
  console.log(`\ncases ${total}   BYTE-IDENTICAL ${pass}   TIE-EQUIVALENT ${tieOnly}   FAIL ${fail}`);
  console.log('criterion: status + envelope + totals byte-identical; rows equal modulo undefined Mongo sort ties');
  process.exit(fail ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
