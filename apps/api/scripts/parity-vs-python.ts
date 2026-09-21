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

async function firstVendorId(): Promise<string> {
  const r = await fetch(`${PY}/api/vendors`, { headers: auth() });
  const rows = (await r.json()) as Array<{ id: string }>;
  return rows[0]?.id ?? 'none';
}

function auth(extra: Record<string, string> = {}): Record<string, string> {
  return { authorization: `Bearer ${TOKEN}`, ...extra };
}

async function main(): Promise<void> {
  const vid = await firstVendorId();
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
