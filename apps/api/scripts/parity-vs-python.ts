/**
 * Live parity check: NestJS (PostgreSQL) vs Python (MongoDB) for the vendors slice.
 *
 * Both servers must already run against the same logical dataset. Unlike the
 * Fastify checker, byte equality IS expected here: Postgres keeps the numeric
 * type, so money renders Python-style (0.0, not 0).
 *
 *   npx tsx scripts/parity-vs-python.ts --token <session token>
 *     [--py http://127.0.0.1:8001] [--nest http://127.0.0.1:8003]
 *
 * Exit code 1 on any mismatch.
 */
const args = process.argv.slice(2);
const argOf = (n: string, d: string): string => {
  const i = args.indexOf(n);
  return i >= 0 && args[i + 1] ? (args[i + 1] as string) : d;
};
const PY = argOf('--py', 'http://127.0.0.1:8001');
const NEST = argOf('--nest', 'http://127.0.0.1:8003');
const TOKEN = argOf('--token', process.env.TRUKVIA_TOKEN ?? '');

if (!TOKEN) {
  console.error('--token is required (a session_token present in both backends\' data)');
  process.exit(2);
}

interface Case {
  path: string;
  headers?: Record<string, string>;
  note?: string;
}

async function firstId(path: string): Promise<string> {
  const r = await fetch(`${PY}${path}`, { headers: auth() });
  const rows = (await r.json()) as Array<{ id: string }>;
  return rows[0]?.id ?? 'none';
}

/** A vendor that actually has payments, so the shape logic is exercised. */
async function vendorWithPayments(vendorIds: string[]): Promise<string> {
  for (const id of vendorIds.slice(0, 40)) {
    const r = await fetch(`${PY}/api/vendors/${id}/payments`, { headers: auth() });
    const rows = (await r.json()) as unknown[];
    if (rows.length) return id;
  }
  return vendorIds[0] ?? 'none';
}

function auth(extra: Record<string, string> = {}): Record<string, string> {
  return { authorization: `Bearer ${TOKEN}`, ...extra };
}

async function main(): Promise<void> {
  const vid = await firstId('/api/vendors');
  const bid = await firstId('/api/vendor-bills');
  const allVendors = (await (await fetch(`${PY}/api/vendors`, { headers: auth() })).json()) as Array<{
    id: string;
  }>;
  const payVid = await vendorWithPayments(allVendors.map((v) => v.id));
  const payments = (await (
    await fetch(`${PY}/api/vendors/${payVid}/payments`, { headers: auth() })
  ).json()) as Array<{ id: string }>;
  const pid = payments[0]?.id ?? 'none';
  const cases: Case[] = [
    { path: '/api/vendors' },
    { path: '/api/vendors?active_only=true' },
    { path: '/api/vendors?active_only=false' },
    { path: '/api/vendors?active_only=1' },
    { path: '/api/vendors?active_only=0' },
    { path: '/api/vendors?active_only=maybe', note: '422 envelope' },
    { path: '/api/vendors?q=UAT' },
    { path: '/api/vendors?q=a' },
    { path: '/api/vendors?q=%5EA', note: 'regex anchor' },
    { path: '/api/vendors?q=zzz-no-match' },
    { path: '/api/vendors?q=UAT&active_only=true' },
    { path: `/api/vendors/${vid}` },
    { path: '/api/vendors/does-not-exist', note: '404 envelope' },
    { path: '/api/vendors', headers: {}, note: 'no auth -> 401' },
    { path: '/api/vendors', headers: { authorization: 'Bearer nope' }, note: 'bad token -> 401' },
    // vendor bills
    { path: '/api/vendor-bills' },
    { path: `/api/vendor-bills?vendor_id=${vid}` },
    { path: '/api/vendor-bills?vendor_id=does-not-exist' },
    { path: '/api/vendor-bills?trip_id=does-not-exist' },
    { path: '/api/vendor-bills?vehicle_id=&repair_event_id=', note: 'empty filters ignored' },
    { path: `/api/vendor-bills/${bid}` },
    { path: '/api/vendor-bills/does-not-exist', note: '404 envelope' },
    { path: '/api/vendor-bills', headers: {}, note: 'no auth -> 401' },
    // vendor payments and corrections
    { path: `/api/vendors/${payVid}/payments`, note: 'covers the six document shapes' },
    { path: '/api/vendors/does-not-exist/payments', note: 'unknown vendor -> [] not 404' },
    { path: `/api/vendor-payments/${pid}/corrections` },
    { path: '/api/vendor-payments/does-not-exist/corrections', note: 'unknown payment -> []' },
    { path: `/api/vendor-payments/${pid}/corrections`, headers: {}, note: 'no auth -> 401' },
  ];

  let pass = 0;
  let fail = 0;
  for (const c of cases) {
    const headers = c.headers === undefined ? auth() : c.headers;
    const [a, b] = await Promise.all([
      fetch(PY + c.path, { headers, redirect: 'manual' }),
      fetch(NEST + c.path, { headers, redirect: 'manual' }),
    ]);
    const [ta, tb] = await Promise.all([a.text(), b.text()]);
    const same = a.status === b.status && ta === tb;
    if (same) pass += 1;
    else fail += 1;
    const label = c.note ? `${c.path}  (${c.note})` : c.path;
    console.log(
      `  ${same ? 'PASS' : 'FAIL'}  ${label}  py=${a.status} nest=${b.status}` +
        (same ? '' : `\n        py  : ${ta.slice(0, 160)}\n        nest: ${tb.slice(0, 160)}`),
    );
  }

  console.log(`\ncases ${cases.length}   PASS ${pass}   FAIL ${fail}`);
  console.log('criterion: identical status AND byte-identical body');
  process.exit(fail ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
