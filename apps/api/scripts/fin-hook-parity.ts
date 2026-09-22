/**
 * Focused parity for slice 2c unit 1 — the canonical projection hook and the
 * fin_hook_failures queue, plus the reverse Python → NestJS bridge.
 *
 *   npx tsx scripts/fin-hook-parity.ts
 *
 * Two throwaway MongoDB databases, seeded identically. The SAME scenario list
 * is driven through Python's real services_fin_txn_hooks functions against one,
 * and through the TypeScript port against the other, then every returned value
 * and every resulting fin_hook_failures document is compared.
 *
 * This is deliberately NOT an HTTP test for the queue part: the failure paths
 * need an induced projection error, which is far easier and far more honest to
 * trigger by calling the functions directly than by trying to break a live
 * write. The reverse bridge IS tested over HTTP, because its whole contract is
 * the authorisation edge.
 *
 * Volatile fields (generated ids, timestamps) are normalised, and their SHAPE
 * and RELATIONSHIPS are asserted separately — a backoff that fires at the wrong
 * time would otherwise slip through normalisation unnoticed.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { MongoClient, type Db } from 'mongodb';
import {
  computeNextAttempt,
  hookAfterSourceWrite,
  recordFailure,
  resolveFailure,
  FAILURE_STATUS_PERMANENTLY_FAILED,
} from '../src/fin/fin-hook';

const MONGO = 'mongodb://127.0.0.1:27017';
const REPO = 'D:/Projects/TRUKVIA-clone';
const PY = 'D:/trk-venv/Scripts/python.exe';
const stamp = Date.now();
const PY_DB = `trukvia_hookparity_py_${stamp}`;
const TS_DB = `trukvia_hookparity_ts_${stamp}`;
const UID = 'user_hookparity';
const CID = 'co_hookparity';
const VP_ID = 'vpay_hookparity01';
const INTERNAL_TOKEN = `hookparity-internal-${'x'.repeat(40)}`;
const PY_PORT = 8411;
const NEST_PORT = 8412;
const TOKEN = 'hookparity-token';

type Doc = Record<string, unknown>;

const VOLATILE = new Set([
  'id',
  'created_at',
  'last_attempt_at',
  'next_attempt_at',
  'resolved_at',
  'failure_id',
  'resolved_failure_id',
]);

/**
 * `fin_hook_failures` rows are created by an UPSERT, and MongoDB builds the
 * upserted document's first fields from the filter's equality terms. pymongo
 * and the Node driver hand the server that filter differently, so the four key
 * fields land in a different ORDER even for an identical call — observed on
 * 2026-09-21 as
 *   py   : source_type, user_id, company_id, source_id, …
 *   nest : source_id, source_type, company_id, user_id, …
 * with every value identical and the ten $set fields in the same order on both
 * sides. It is not even stable between runs. This is the same effect already
 * documented for fin_txn in scripts/write-parity.ts, so these documents are
 * compared key-insensitively; membership and values stay exact.
 */
function deepSortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(deepSortKeys);
  if (value && typeof value === 'object') {
    const out: Doc = {};
    for (const k of Object.keys(value as Doc).sort()) out[k] = deepSortKeys((value as Doc)[k]);
    return out;
  }
  return value;
}

function normalise(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalise);
  if (value && typeof value === 'object') {
    const out: Doc = {};
    for (const [k, v] of Object.entries(value as Doc)) {
      out[k] = VOLATILE.has(k) ? (v === null || v === '' ? v : `<${k}>`) : normalise(v);
    }
    return out;
  }
  if (typeof value === 'string' && /^hfail_[0-9a-f]{16}$/.test(value)) return '<id>';
  return value;
}

async function seed(db: Db): Promise<void> {
  await db.collection('companies').insertOne({ id: CID, user_id: UID, name: 'Hook Co', is_default: true });
  await db.collection('vendors').insertOne({
    id: 'ven_hookparity01',
    user_id: UID,
    company_id: CID,
    name: 'Hook Vendor',
    is_active: true,
  });
  // One real vendor payment, so the success path actually projects legs.
  await db.collection('vendor_payments').insertOne({
    id: VP_ID,
    user_id: UID,
    company_id: CID,
    vendor_id: 'ven_hookparity01',
    date: '2026-09-02',
    amount: 5000,
    mode: 'Bank',
    ref_no: 'TXN-HOOK-1',
    payment_direction: 'payment_out',
    vendor_bill_id: '',
    notes: '',
    is_deleted: false,
  });
}

/** The TypeScript side of the same scenario list the Python driver runs. */
async function runTsScenario(db: Db): Promise<Array<{ step: string; value: unknown; rows: Doc[] }>> {
  const steps: Array<{ step: string; value: unknown; rows: Doc[] }> = [];
  // Sorted by the BUSINESS key, not by `id`: ids are random, so sorting on
  // them orders the two databases' rows differently for no reason.
  const dump = async (): Promise<Doc[]> => {
    const rows = await db
      .collection<Doc>('fin_hook_failures')
      .find({}, { projection: { _id: 0 } })
      .toArray();
    return rows.sort((a, b) =>
      `${String(a['source_type'])}|${String(a['source_id'])}`.localeCompare(
        `${String(b['source_type'])}|${String(b['source_id'])}`,
      ),
    );
  };
  const step = async (name: string, value: unknown): Promise<void> => {
    steps.push({ step: name, value, rows: await dump() });
  };

  await step('hook_unsupported', await hookAfterSourceWrite(db, UID, CID, 'banana', 'x1'));
  await step('record_new', await recordFailure(db, UID, CID, 'vendor_payment', VP_ID, 'boom one', 'upsert'));
  await step('record_refresh', await recordFailure(db, UID, CID, 'vendor_payment', VP_ID, 'boom two', 'upsert'));
  await step('resolve', await resolveFailure(db, UID, CID, 'vendor_payment', VP_ID));
  await step('resolve_again', await resolveFailure(db, UID, CID, 'vendor_payment', VP_ID));
  await step(
    'record_reopen',
    await recordFailure(db, UID, CID, 'vendor_payment', VP_ID, 'boom three', 'delete_cascade'),
  );
  await db
    .collection('fin_hook_failures')
    .updateOne(
      { user_id: UID, company_id: CID, source_type: 'vendor_payment', source_id: VP_ID },
      { $set: { status: FAILURE_STATUS_PERMANENTLY_FAILED, retry_count: 8 } },
    );
  await step(
    'record_reopen_from_permanent',
    await recordFailure(db, UID, CID, 'vendor_payment', VP_ID, 'boom four', 'upsert'),
  );
  await step('hook_success', await hookAfterSourceWrite(db, UID, CID, 'vendor_payment', VP_ID));
  await step(
    'record_long_error',
    await recordFailure(db, UID, CID, 'vendor_bill', 'vbl_long', 'E'.repeat(2500), 'upsert'),
  );
  const base = new Date();
  await step(
    'backoff',
    Array.from({ length: 12 }, (_, n) =>
      Math.round((Date.parse(computeNextAttempt(n, base)) - base.getTime()) / 1000),
    ),
  );
  return steps;
}

function startServer(kind: 'py' | 'nest', port: number, dbName: string): ChildProcess {
  if (kind === 'py') {
    return spawn(
      PY,
      ['-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', String(port), '--log-level', 'warning'],
      {
        cwd: `${REPO}/backend`,
        env: {
          ...process.env,
          MONGO_URL: MONGO,
          DB_NAME: dbName,
          DISABLE_SCHEDULER: '1',
          EMERGENT_LLM_KEY: '',
          REGRESSION_GUARD_PERIODIC: '0',
          PYTHONUTF8: '1',
          TRUKVIA_INTERNAL_TOKEN: INTERNAL_TOKEN,
        },
        stdio: 'ignore',
        shell: false,
      },
    );
  }
  return spawn('npx', ['tsx', 'src/main.ts'], {
    cwd: `${REPO}/apps/api`,
    env: {
      ...process.env,
      PORT: String(port),
      NEST_MONGO_URL: MONGO,
      NEST_MONGO_DB: dbName,
      TRUKVIA_INTERNAL_TOKEN: INTERNAL_TOKEN,
      // The reverse bridge must project LOCALLY, so the forward bridge is off.
      TRUKVIA_FIN_HOOK_URL: '',
    },
    stdio: 'ignore',
    shell: true,
  });
}

function killPort(port: number): void {
  try {
    const out = execFileSync('netstat', ['-ano'], { encoding: 'utf8' });
    for (const line of out.split('\n')) {
      if (line.includes(`127.0.0.1:${port}`) && line.includes('LISTENING')) {
        const pid = line.trim().split(/\s+/).pop();
        if (pid && pid !== '0') {
          try {
            execFileSync('taskkill', ['/F', '/PID', pid], { stdio: 'ignore' });
          } catch {
            /* already gone */
          }
        }
      }
    }
  } catch {
    /* netstat unavailable */
  }
}

async function waitFor(url: string, tries = 90): Promise<boolean> {
  for (let i = 0; i < tries; i += 1) {
    try {
      const r = await fetch(url);
      if (r.status > 0) return true;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

interface BridgeCase {
  name: string;
  headers?: Record<string, string>;
  body?: unknown;
  raw?: string;
  /**
   * Compare the STATUS only, with the reason. Used where the two sides
   * legitimately differ because NestJS has ported a source type Python's own
   * internal endpoint still refuses — the allowlist is rendered into the 400
   * body, so the text differs by design.
   */
  statusOnly?: string;
  /** Different statuses ARE the contract here; both are asserted literally. */
  expect?: { py: number; nest: number };
}

const BRIDGE_CASES: BridgeCase[] = [
  { name: 'no token -> 401', body: { user_id: UID, company_id: CID, source_type: 'vendor_payment', source_id: VP_ID } },
  {
    name: 'wrong token -> 401',
    headers: { 'x-internal-token': 'nope' },
    body: { user_id: UID, company_id: CID, source_type: 'vendor_payment', source_id: VP_ID },
  },
  {
    name: 'right token, same length, wrong value -> 401',
    headers: { 'x-internal-token': `y${INTERNAL_TOKEN.slice(1)}` },
    body: { user_id: UID, company_id: CID, source_type: 'vendor_payment', source_id: VP_ID },
  },
  {
    name: 'missing user_id -> 400',
    headers: { 'x-internal-token': INTERNAL_TOKEN },
    body: { company_id: CID, source_type: 'vendor_payment', source_id: VP_ID },
  },
  {
    name: 'blank source_id -> 400',
    headers: { 'x-internal-token': INTERNAL_TOKEN },
    body: { user_id: UID, company_id: CID, source_type: 'vendor_payment', source_id: '   ' },
  },
  {
    /**
     * Deliberately a NON-source-type rather than a real-but-unported one.
     * This fixture used "expense", which broke the moment expense was ported:
     * NestJS started answering 200 while Python still answered 400. A value
     * that will never be a source type keeps the case testing the allowlist
     * itself rather than the porting schedule.
     */
    name: 'unsupported source_type -> 400',
    headers: { 'x-internal-token': INTERNAL_TOKEN },
    body: { user_id: UID, company_id: CID, source_type: 'not_a_source_type', source_id: 'x' },
    statusOnly: 'the allowlist is rendered into the body, and the two sides have ported different amounts',
  },
  {
    name: 'source_type absent -> 400',
    headers: { 'x-internal-token': INTERNAL_TOKEN },
    body: { user_id: UID, company_id: CID, source_id: 'x' },
    statusOnly: 'same allowlist text difference',
  },
  {
    /**
     * The asymmetry, asserted rather than assumed: Python's internal endpoint
     * still refuses mechanic_payment, while NestJS accepts it because it owns
     * that projection now. That is exactly what lets Python delegate this one
     * source type without NestJS being able to bounce the work back.
     */
    name: 'mechanic_payment: Python refuses, NestJS accepts',
    headers: { 'x-internal-token': INTERNAL_TOKEN },
    body: { user_id: UID, company_id: CID, source_type: 'mechanic_payment', source_id: 'mpay_none' },
    expect: { py: 400, nest: 200 },
  },
  {
    name: 'valid reproject -> 200',
    headers: { 'x-internal-token': INTERNAL_TOKEN },
    body: { user_id: UID, company_id: CID, source_type: 'vendor_payment', source_id: VP_ID },
  },
  {
    name: 'valid reproject, unknown source_id -> 200 with 0 written',
    headers: { 'x-internal-token': INTERNAL_TOKEN },
    body: { user_id: UID, company_id: CID, source_type: 'vendor_payment', source_id: 'vpay_nope' },
  },
];

async function main(): Promise<void> {
  const client = new MongoClient(MONGO);
  await client.connect();
  const pyDb = client.db(PY_DB);
  const tsDb = client.db(TS_DB);
  await seed(pyDb);
  await seed(tsDb);

  let pass = 0;
  let fail = 0;
  const report = (ok: boolean, name: string, detail?: string): void => {
    if (ok) {
      pass += 1;
      console.log(`  PASS  ${name}`);
    } else {
      fail += 1;
      console.log(`  FAIL  ${name}${detail ? `\n        ${detail}` : ''}`);
    }
  };

  try {
    // ── the queue: Python reference vs the TypeScript port ────────────────
    const pyRaw = execFileSync(PY, [`${REPO}/apps/api/scripts/fin_hook_driver.py`, PY_DB, UID, CID, VP_ID], {
      cwd: `${REPO}/backend`,
      encoding: 'utf8',
      // Python puts the SCRIPT's directory on sys.path, not the cwd, so backend/
      // has to be named explicitly for `from db import db` to resolve.
      env: { ...process.env, PYTHONUTF8: '1', MONGO_URL: MONGO, DB_NAME: PY_DB, PYTHONPATH: `${REPO}/backend` },
      maxBuffer: 32 * 1024 * 1024,
    });
    const pySteps = (JSON.parse(pyRaw) as { steps: Array<{ step: string; value: unknown; rows: Doc[] }> }).steps;
    const tsSteps = await runTsScenario(tsDb);

    if (pySteps.length !== tsSteps.length) {
      report(false, 'scenario length', `py ${pySteps.length} vs ts ${tsSteps.length}`);
    }
    for (let i = 0; i < Math.min(pySteps.length, tsSteps.length); i += 1) {
      const p = pySteps[i] as { step: string; value: unknown; rows: Doc[] };
      const t = tsSteps[i] as { step: string; value: unknown; rows: Doc[] };
      /**
       * Return values are compared BYTE-EXACT, because they are built in code
       * and their key order is a real contract — with one exception.
       * `record_refresh` returns `{**existing, ...}`, and `existing` was read
       * back from MongoDB, so it carries the server-assigned upsert key order
       * described above rather than anything the code chose.
       */
      const ordered = p.step === 'record_refresh' ? deepSortKeys : (v: unknown) => v;
      const pv = JSON.stringify(ordered(normalise(p.value)));
      const tv = JSON.stringify(ordered(normalise(t.value)));
      report(pv === tv, `${p.step} — return value`, pv === tv ? undefined : `py  : ${pv.slice(0, 300)}\n        nest: ${tv.slice(0, 300)}`);
      const pr = JSON.stringify(deepSortKeys(normalise(p.rows)));
      const tr = JSON.stringify(deepSortKeys(normalise(t.rows)));
      report(pr === tr, `${p.step} — fin_hook_failures`, pr === tr ? undefined : `py  : ${pr.slice(0, 340)}\n        nest: ${tr.slice(0, 340)}`);
    }

    // Shape and relationships that normalisation hides.
    const tsRows = await tsDb.collection<Doc>('fin_hook_failures').find({}).toArray();
    const idsOk = tsRows.every((r) => /^hfail_[0-9a-f]{16}$/.test(String(r['id'])));
    report(idsOk, 'generated failure ids have Python\u2019s shape');
    const stampsOk = tsRows.every((r) =>
      [r['created_at'], r['last_attempt_at'], r['next_attempt_at']].every((v) =>
        /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$/.test(String(v)),
      ),
    );
    report(stampsOk, 'timestamps are Python isoformat with microseconds');
    const longRow = tsRows.find((r) => r['source_id'] === 'vbl_long');
    report(String(longRow?.['error'] ?? '').length === 2000, 'long error truncated to 2000 characters');

    // The retry driver selects on these two fields — the whole point of 2c-1.
    const scanOk = tsRows.every(
      (r) => typeof r['status'] === 'string' && typeof r['next_attempt_at'] === 'string' && typeof r['retry_count'] === 'number',
    );
    report(scanOk, 'every row carries status, next_attempt_at and retry_count');

    // ── the reverse bridge over HTTP ──────────────────────────────────────
    killPort(PY_PORT);
    killPort(NEST_PORT);
    const py = startServer('py', PY_PORT, PY_DB);
    const nest = startServer('nest', NEST_PORT, TS_DB);
    try {
      const up = await waitFor(`http://127.0.0.1:${PY_PORT}/api/auth/health`);
      const nestUp = await waitFor(`http://127.0.0.1:${NEST_PORT}/api/vendors`);
      if (!up || !nestUp) throw new Error(`servers did not start (py=${up} nest=${nestUp})`);

      for (const c of BRIDGE_CASES) {
        const init: RequestInit = {
          method: 'POST',
          headers: { 'content-type': 'application/json', ...(c.headers ?? {}) },
          body: c.raw ?? JSON.stringify(c.body ?? {}),
        };
        const [a, b] = await Promise.all([
          fetch(`http://127.0.0.1:${PY_PORT}/internal/fin/reproject`, init),
          fetch(`http://127.0.0.1:${NEST_PORT}/internal/fin/reproject`, init),
        ]);
        const [ta, tb] = [await a.text(), await b.text()];
        let same: boolean;
        if (c.expect) same = a.status === c.expect.py && b.status === c.expect.nest;
        else if (c.statusOnly) same = a.status === b.status;
        else same = a.status === b.status && ta === tb;
        const suffix = c.statusOnly ? `  (status only: ${c.statusOnly})` : '';
        report(
          same,
          `bridge: ${c.name}${suffix}`,
          same ? undefined : `py  : ${a.status} ${ta.slice(0, 200)}\n        nest: ${b.status} ${tb.slice(0, 200)}`,
        );
      }
    } finally {
      py.kill();
      nest.kill();
      killPort(PY_PORT);
      killPort(NEST_PORT);
    }
  } finally {
    await new Promise((r) => setTimeout(r, 1000));
    await pyDb.dropDatabase();
    await tsDb.dropDatabase();
    await client.close();
  }

  console.log(`\nchecks ${pass + fail}   PASS ${pass}   FAIL ${fail}`);
  process.exit(fail ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
