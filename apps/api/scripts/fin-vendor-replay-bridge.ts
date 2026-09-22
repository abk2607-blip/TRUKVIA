/**
 * Slice 2c step 6 — the REPLAY path through the reverse bridge.
 *
 *   npx tsx scripts/fin-vendor-replay-bridge.ts
 *
 * The one Step 6 check the shared projection runner cannot make. That runner
 * proves the two live entry points — the hook and a direct reproject_source —
 * each delegate exactly once. The retry driver is a THIRD entry point: it
 * calls `reproject_source` on its own, for sources that failed earlier, and it
 * reaches the bridge through `_bridged_reproject_source` rather than through
 * the hook's gate. Nothing else in the suite exercises that combination.
 *
 * Two throwaway databases are seeded identically, each with a queue of
 * already-failed vendor_payment and vendor_bill rows:
 *
 *   PY      Python's replay_pending_failures projects locally
 *   BRIDGE  the same call, delegating every reprojection to a live NestJS
 *
 * Seeding the queue directly is not a shortcut around a real failure — it is
 * exactly the state a real failure leaves behind, and it is the only way to
 * queue a vendor_payment at all: that projection has no branch that can fail
 * at persist, because AP_VENDOR and every mode account always resolve.
 *
 * A counting proxy sits in front of NestJS so "exactly once per queued row"
 * is measured rather than assumed.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { spawn } from 'node:child_process';
import { createServer, request, type Server } from 'node:http';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { MongoClient, type Db } from 'mongodb';
import { killPort, ledger, startNest, waitFor, type Doc } from './lib/projection-parity';

const MONGO = 'mongodb://127.0.0.1:27017';
const REPO = 'D:/Projects/TRUKVIA-clone';
const PY = 'D:/trk-venv/Scripts/python.exe';
const stamp = Date.now();
const PY_DB = `trukvia_vreplay_py_${stamp}`;
const BR_DB = `trukvia_vreplay_br_${stamp}`;
const NEST_PORT = 8551;
const PROXY_PORT = 8552;
const INTERNAL_TOKEN = 'test-internal-token-at-least-32-characters-long';

const UID = 'user_vreplay';
const CID = 'co_vreplay';

const vendor_payments: Doc[] = [
  {
    id: 'vp_r1',
    user_id: UID,
    company_id: CID,
    vendor_id: 'vend_1',
    amount: 1000,
    date: '2026-09-02',
    mode: 'Bank',
    type: 'payment_out',
    ref_no: 'VP-R1',
    is_deleted: false,
  },
  {
    id: 'vp_r2',
    user_id: UID,
    company_id: CID,
    vendor_id: 'vend_2',
    amount: 2.675,
    date: '2026-09-03',
    mode: 'Cash',
    type: 'receipt_in',
    ref_no: null, // the literal "None" narration, as fixed in step 6
    is_deleted: false,
  },
  {
    // Queued, then SOFT-DELETED before the replay ran. The reprojection must
    // succeed and write nothing — a resolved row with an empty ledger.
    id: 'vp_r3_deleted',
    user_id: UID,
    company_id: CID,
    vendor_id: 'vend_3',
    amount: 500,
    date: '2026-09-04',
    mode: 'UPI',
    type: 'payment_out',
    ref_no: 'VP-R3',
    is_deleted: true,
  },
];

/** An orphan bill, so the replay covers both vendor source types. */
const vendor_bills: Doc[] = [
  {
    id: 'vb_r1',
    user_id: UID,
    company_id: CID,
    vendor_id: 'vend_1',
    vendor_name: 'Vend One',
    bill_amount: 750,
    bill_date: '2026-09-02',
    bill_number: 'VB-R1',
    is_deleted: false,
  },
];

/** Which sources are queued, and therefore how many bridge calls to expect. */
const QUEUED: Array<[string, string]> = [
  ['vendor_payment', 'vp_r1'],
  ['vendor_payment', 'vp_r2'],
  ['vendor_payment', 'vp_r3_deleted'],
  ['vendor_bill', 'vb_r1'],
];

const iso = (d: Date): string => `${d.toISOString().slice(0, -1)}000+00:00`;

/**
 * The queue rows a previous failure would have left. Shaped exactly as
 * `_record_failure` writes them, with next_attempt_at already in the past so
 * the scheduled selection picks them up without ignore_schedule.
 */
const failures = (): Doc[] =>
  QUEUED.map(([source_type, source_id], i) => ({
    id: `hfail_${'0'.repeat(15)}${i + 1}`,
    user_id: UID,
    company_id: CID,
    source_type,
    source_id,
    action: 'upsert',
    error: 'seeded: a transient failure from an earlier write',
    retry_count: 0,
    created_at: iso(new Date(Date.now() - 3600_000)),
    last_attempt_at: iso(new Date(Date.now() - 3600_000)),
    next_attempt_at: iso(new Date(Date.now() - 600_000)),
    status: 'pending',
    resolved_at: '',
    history: [],
  }));

const SPEC = [
  // First drain: every due row is attempted, through whichever path is live.
  { op: 'replay', verbose: true },
  // Second drain: nothing may be reselected, and no ledger row may double.
  { op: 'replay', verbose: true },
];

const VOLATILE = new Set(['created_at', 'last_attempt_at', 'next_attempt_at', 'resolved_at', 'at']);

function normalise(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(normalise);
  if (v && typeof v === 'object') {
    const out: Doc = {};
    for (const k of Object.keys(v as Doc).sort()) {
      const val = (v as Doc)[k];
      out[k] = VOLATILE.has(k) ? (val === null || val === '' ? val : `<${k}>`) : normalise(val);
    }
    return out;
  }
  return v;
}

function runReplayDriver(dbName: string, specPath: string, extraEnv: Record<string, string> = {}): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(PY, [`${REPO}/apps/api/scripts/fin_replay_driver.py`, dbName, specPath], {
      cwd: `${REPO}/backend`,
      env: {
        ...process.env,
        PYTHONUTF8: '1',
        PYTHONPATH: `${REPO}/backend`,
        MONGO_URL: MONGO,
        DB_NAME: dbName,
        ...extraEnv,
      },
      shell: false,
    });
    let out = '';
    child.stdout.on('data', (d) => {
      out += String(d);
    });
    child.on('error', reject);
    child.on('exit', (code) => (code === 0 ? resolve(out) : reject(new Error(`replay driver exited ${code}`))));
  });
}

async function seed(db: Db): Promise<void> {
  await db.collection('companies').insertOne({ id: CID, user_id: UID, name: 'Replay Vendor Co', is_default: true });
  await db.collection('vendor_payments').insertMany(vendor_payments as never[]);
  await db.collection('vendor_bills').insertMany(vendor_bills as never[]);
  await db.collection('fin_hook_failures').insertMany(failures() as never[]);
}

async function queueOf(db: Db): Promise<Doc[]> {
  const rows = await db
    .collection<Doc>('fin_hook_failures')
    .find({}, { projection: { _id: 0 } })
    .toArray();
  return rows.sort((a, b) =>
    `${String(a['source_type'])}|${String(a['source_id'])}`.localeCompare(
      `${String(b['source_type'])}|${String(b['source_id'])}`,
    ),
  );
}

async function main(): Promise<void> {
  const client = new MongoClient(MONGO);
  await client.connect();
  const pyDb = client.db(PY_DB);
  const brDb = client.db(BR_DB);
  await seed(pyDb);
  await seed(brDb);

  const dir = mkdtempSync(join(tmpdir(), 'vreplay-'));
  const specPath = join(dir, 'spec.json');
  writeFileSync(specPath, JSON.stringify(SPEC), 'utf8');

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

  killPort(NEST_PORT);
  killPort(PROXY_PORT);
  let nest: ReturnType<typeof startNest> | undefined;
  let proxy: Server | undefined;
  const seen: string[] = [];

  try {
    // ── PY: the retry driver projecting locally ────────────────────────
    const pyRaw = await runReplayDriver(PY_DB, specPath);
    const pySteps = (JSON.parse(pyRaw) as { steps: Array<{ value: Doc; queue: Doc[] }> }).steps;
    const pyLedger = JSON.stringify(await ledger(pyDb));

    report(
      Number(pySteps[0]?.value?.['attempted']) === QUEUED.length,
      'PY: the first drain attempts every due row',
      JSON.stringify(pySteps[0]?.value),
    );

    // ── BRIDGE: the same drain, delegating to a live NestJS ────────────
    nest = startNest(BR_DB, NEST_PORT, INTERNAL_TOKEN);
    if (!(await waitFor(`http://127.0.0.1:${NEST_PORT}/api/vendors`))) {
      throw new Error('NestJS did not start');
    }

    proxy = createServer((req, res) => {
      const chunks: Buffer[] = [];
      req.on('data', (c: Buffer) => chunks.push(c));
      req.on('end', () => {
        const body = Buffer.concat(chunks);
        try {
          const parsed = JSON.parse(body.toString('utf8')) as Doc;
          seen.push(`${String(parsed['source_type'])}/${String(parsed['source_id'])}`);
        } catch {
          seen.push('<unparseable>');
        }
        const up = request(
          {
            host: '127.0.0.1',
            port: NEST_PORT,
            method: req.method,
            path: req.url,
            headers: { ...req.headers, host: `127.0.0.1:${NEST_PORT}` },
          },
          (ur) => {
            res.writeHead(ur.statusCode ?? 502, ur.headers);
            ur.pipe(res);
          },
        );
        up.on('error', () => {
          res.writeHead(502).end('{}');
        });
        up.end(body);
      });
    });
    await new Promise<void>((r) => proxy!.listen(PROXY_PORT, '127.0.0.1', r));

    const bridgeEnv = {
      TRUKVIA_FIN_NODE_URL: `http://127.0.0.1:${PROXY_PORT}/internal/fin/reproject`,
      TRUKVIA_INTERNAL_TOKEN: INTERNAL_TOKEN,
      TRUKVIA_FIN_NODE_SOURCE_TYPES: 'vendor_payment,vendor_bill',
    };
    const brRaw = await runReplayDriver(BR_DB, specPath, bridgeEnv);
    const brSteps = (JSON.parse(brRaw) as { steps: Array<{ value: Doc; queue: Doc[] }> }).steps;
    const brLedger = JSON.stringify(await ledger(brDb));

    // 1. The ledger the bridge produced is the ledger Python produces.
    report(pyLedger === brLedger, 'the replayed ledger is identical through the bridge');

    // 2. Exactly one delegation per queued row, and not one more.
    report(
      seen.length === QUEUED.length,
      'the retry driver delegates exactly ONCE per queued row',
      `${seen.length} calls: ${seen.join(', ')}`,
    );
    report(
      JSON.stringify([...seen].sort()) ===
        JSON.stringify(QUEUED.map(([t, i]) => `${t}/${i}`).sort()),
      'every delegation names the source it was queued for',
      seen.join(', '),
    );

    // 3. The queue ends in the same state on both sides.
    for (let i = 0; i < SPEC.length; i += 1) {
      const p = JSON.stringify(normalise(pySteps[i]?.value));
      const b = JSON.stringify(normalise(brSteps[i]?.value));
      report(p === b, `drain ${i + 1}: the report matches`, p === b ? undefined : `py  : ${p}\n        br  : ${b}`);
      const pq = JSON.stringify(normalise(pySteps[i]?.queue));
      const bq = JSON.stringify(normalise(brSteps[i]?.queue));
      report(pq === bq, `drain ${i + 1}: the queue matches`, pq === bq ? undefined : `py  : ${pq.slice(0, 300)}\n        br  : ${bq.slice(0, 300)}`);
    }

    // 4. The second drain must reselect nothing — a resolved row is terminal.
    report(
      Number(brSteps[1]?.value?.['attempted']) === 0,
      'the second drain attempts nothing: every row is already resolved',
      JSON.stringify(brSteps[1]?.value),
    );
    report(
      seen.length === QUEUED.length,
      'the second drain makes no further bridge calls',
      `${seen.length} total`,
    );

    // 5. No duplicate ledger rows, and the ids are the deterministic ones.
    const rows = await ledger(brDb);
    const keys = rows.map((r) => `${String(r['user_id'])}|${String(r['ref_source_key'])}`);
    report(new Set(keys).size === keys.length, 'no duplicate ledger rows after two drains', `${keys.length} rows`);
    report(
      rows.every((r) => r['id'] === `fintxn_${String(r['ref_source_key']).replace(/:/g, '_').slice(0, 60)}`),
      'fin_txn ids follow the ref_source_key rule',
    );

    // 6. The specific rows this scenario exists to produce.
    const byKey = (k: string): Doc | undefined => rows.find((r) => r['ref_source_key'] === k);
    report(
      byKey('vendor_payment:vp_r2:bank_debit')?.['narration'] === 'Vendor receipt_in · None',
      'a replayed payment carries the corrected "None" narration',
      String(byKey('vendor_payment:vp_r2:bank_debit')?.['narration']),
    );
    report(
      byKey('vendor_bill:vb_r1:suspense_debit')?.['account_code'] === 'SUSPENSE',
      'the queued orphan bill replays through the bridge too',
    );
    report(
      rows.every((r) => r['source_id'] !== 'vp_r3_deleted'),
      'a source soft-deleted since it was queued replays to ZERO rows',
    );
    const q = await queueOf(brDb);
    report(
      q.find((r) => r['source_id'] === 'vp_r3_deleted')?.['status'] === 'resolved',
      'and that row still resolves — writing nothing is a success, not a failure',
      String(q.find((r) => r['source_id'] === 'vp_r3_deleted')?.['status']),
    );
    report(
      q.every((r) => r['status'] === 'resolved' && r['retry_count'] === 0),
      'every queued row resolved on the first attempt, with no retry recorded',
      q.map((r) => `${String(r['source_id'])}:${String(r['status'])}/${String(r['retry_count'])}`).join(' '),
    );
    report(
      q.every((r) => /^hfail_0{15}\d$/.test(String(r['id']))),
      'the queue ids survived the replay unchanged',
    );
  } finally {
    nest?.kill();
    killPort(NEST_PORT);
    if (proxy) await new Promise<void>((r) => proxy!.close(() => r()));
    killPort(PROXY_PORT);
    await pyDb.dropDatabase();
    await brDb.dropDatabase();
    await client.close();
  }

  console.log(`\nchecks ${pass + fail}   PASS ${pass}   FAIL ${fail}`);
  process.exit(fail ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
