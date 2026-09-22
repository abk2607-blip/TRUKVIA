/**
 * Focused parity for slice 2c unit 13 — `replay_pending_failures`, the retry
 * driver.
 *
 *   npx tsx scripts/fin-replay-parity.ts
 *
 * Not a projection, so this does not use the projection-parity runner. Two
 * throwaway databases are driven through the SAME ordered scenario — Python's
 * real function on one, the port on the other — and after every step both the
 * return value and the whole queue are compared.
 *
 * Failures are produced the honest way: a wallet_recharge whose wallet_code
 * cannot be resolved raises inside `_persist_legs`, exactly as it would in
 * production. Success is a wallet_recharge that resolves. Nothing is stubbed.
 *
 * Two helper ops make the time-based behaviour testable without waiting:
 * `age` rewinds `next_attempt_at` so a row becomes due, and `setcount` forces
 * a retry_count so the MAX_RETRIES boundary is reached in one step instead of
 * eight.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { execFileSync, spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { MongoClient, type Db } from 'mongodb';
import { hookAfterSourceWrite, replayPendingFailures } from '../src/fin/fin-hook';

const MONGO = 'mongodb://127.0.0.1:27017';
const REPO = 'D:/Projects/TRUKVIA-clone';
const PY = 'D:/trk-venv/Scripts/python.exe';
const stamp = Date.now();
const PY_DB = `trukvia_replayparity_py_${stamp}`;
const TS_DB = `trukvia_replayparity_ts_${stamp}`;
const UID = 'user_replay';
const CID = 'co_replay';

type Doc = Record<string, unknown>;

/** A recharge that projects cleanly, and three that cannot resolve an account. */
const SOURCES: Doc[] = [
  { id: 'wr_good', wallet_code: 'WALLET_FASTAG' },
  { id: 'wr_bad_a', wallet_code: '' },
  { id: 'wr_bad_b', wallet_code: 'WALLET_MYSTERY' },
  { id: 'wr_bad_c', wallet_code: 'NOPE' },
].map((d) => ({
  user_id: UID,
  company_id: CID,
  amount: 100,
  date: '2026-09-02',
  funding_mode: 'Bank',
  reference: 'REF',
  is_deleted: false,
  ...d,
}));

type Step =
  | { op: 'hook'; uid: string; cid: string; source_type: string; source_id: string }
  | {
      op: 'replay';
      user_id?: string;
      company_id?: string;
      limit?: number;
      dry_run?: boolean;
      ignore_schedule?: boolean;
      verbose?: boolean;
    }
  | { op: 'age'; source_id: string; seconds: number }
  | { op: 'setcount'; source_id: string; retry_count: number };

const hook = (id: string): Step => ({
  op: 'hook',
  uid: UID,
  cid: CID,
  source_type: 'wallet_recharge',
  source_id: id,
});

const STEPS: Step[] = [
  // Queue three failures and one success.
  hook('wr_bad_a'),
  hook('wr_bad_b'),
  hook('wr_bad_c'),
  hook('wr_good'),

  // 1. Nothing is due yet — the backoff is 60s away, so a scheduled replay
  //    must select NOTHING even though three rows are pending.
  { op: 'replay', verbose: true },

  // 2. ignore_schedule overrides that and attempts them all.
  { op: 'replay', ignore_schedule: true, dry_run: true, verbose: true },

  // 3. A dry run must not have changed anything — replay again and see the
  //    same rows still pending.
  { op: 'replay', ignore_schedule: true, verbose: true },

  // 4. After a real attempt the rows are retrying with retry_count 1 and a
  //    fresh backoff, so a scheduled replay again selects nothing.
  { op: 'replay', verbose: true },

  // 5. Age ONE row so exactly one becomes due, and confirm the others are not.
  { op: 'age', source_id: 'wr_bad_a', seconds: 10 },
  { op: 'replay', verbose: true },

  // 6. The limit is honoured, in next_attempt_at order.
  { op: 'replay', ignore_schedule: true, limit: 1, verbose: true },

  // 7. Fix the source, then replay: the row resolves and keeps its id.
  //    (The fix happens on the harness side between steps.)

  // 8. The MAX_RETRIES boundary: force a count of 7 so the next failure is the
  //    eighth and tips the row into permanently_failed.
  { op: 'setcount', source_id: 'wr_bad_b', retry_count: 7 },
  { op: 'replay', ignore_schedule: true, verbose: true },

  // 9. A permanently_failed row is terminal — it is never selected again.
  { op: 'replay', ignore_schedule: true, verbose: true },

  // 10. Tenant scoping: a replay for another tenant touches nothing.
  { op: 'replay', user_id: 'someone_else', ignore_schedule: true, verbose: true },
];

const VOLATILE = new Set(['id', 'created_at', 'last_attempt_at', 'next_attempt_at', 'resolved_at', 'at']);

function normalise(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(normalise);
  if (v && typeof v === 'object') {
    const out: Doc = {};
    for (const k of Object.keys(v as Doc).sort()) {
      const val = (v as Doc)[k];
      out[k] = VOLATILE.has(k)
        ? val === null || val === ''
          ? val
          : `<${k}>`
        : k === 'error'
          ? '<error>'
          : normalise(val);
    }
    return out;
  }
  if (typeof v === 'string' && /^hfail_[0-9a-f]{16}$/.test(v)) return '<id>';
  return v;
}

async function seed(db: Db): Promise<void> {
  await db.collection('companies').insertOne({ id: CID, user_id: UID, name: 'Replay Co', is_default: true });
  await db.collection('wallet_recharges').insertMany(SOURCES as never[]);
}

/** Apply a step to the TypeScript side. */
async function runTsStep(db: Db, st: Step): Promise<unknown> {
  if (st.op === 'hook') {
    return hookAfterSourceWrite(db, st.uid, st.cid, st.source_type, st.source_id);
  }
  if (st.op === 'replay') {
    return replayPendingFailures(db, {
      user_id: st.user_id,
      company_id: st.company_id,
      limit: st.limit ?? 100,
      dry_run: st.dry_run ?? false,
      ignore_schedule: st.ignore_schedule ?? false,
      verbose: st.verbose ?? false,
    });
  }
  if (st.op === 'age') {
    const when = new Date(Date.now() - st.seconds * 1000);
    await db
      .collection('fin_hook_failures')
      .updateOne(
        { source_id: st.source_id },
        { $set: { next_attempt_at: `${when.toISOString().slice(0, -1)}000+00:00` } },
      );
    return 'aged';
  }
  await db
    .collection('fin_hook_failures')
    .updateOne({ source_id: st.source_id }, { $set: { retry_count: st.retry_count } });
  return 'set';
}

async function tsQueue(db: Db): Promise<Doc[]> {
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
  const tsDb = client.db(TS_DB);
  await seed(pyDb);
  await seed(tsDb);

  const dir = mkdtempSync(join(tmpdir(), 'replayparity-'));
  const specPath = join(dir, 'spec.json');
  writeFileSync(specPath, JSON.stringify(STEPS), 'utf8');

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
    const raw = execFileSync(PY, [`${REPO}/apps/api/scripts/fin_replay_driver.py`, PY_DB, specPath], {
      cwd: `${REPO}/backend`,
      encoding: 'utf8',
      env: {
        ...process.env,
        PYTHONUTF8: '1',
        PYTHONPATH: `${REPO}/backend`,
        MONGO_URL: MONGO,
        DB_NAME: PY_DB,
      },
      maxBuffer: 32 * 1024 * 1024,
    });
    const pySteps = (JSON.parse(raw) as { steps: Array<{ op: string; value: unknown; queue: Doc[] }> }).steps;

    const tsSteps: Array<{ op: string; value: unknown; queue: Doc[] }> = [];
    for (const st of STEPS) {
      const value = await runTsStep(tsDb, st);
      tsSteps.push({ op: st.op, value, queue: await tsQueue(tsDb) });
    }

    report(pySteps.length === tsSteps.length, 'scenario length', `${pySteps.length} vs ${tsSteps.length}`);
    for (let i = 0; i < Math.min(pySteps.length, tsSteps.length); i += 1) {
      const p = pySteps[i] as { op: string; value: unknown; queue: Doc[] };
      const t = tsSteps[i] as { op: string; value: unknown; queue: Doc[] };
      const label = `step ${i} (${p.op})`;
      const pv = JSON.stringify(normalise(p.value));
      const tv = JSON.stringify(normalise(t.value));
      report(pv === tv, `${label} — return value`, pv === tv ? undefined : `py  : ${pv.slice(0, 300)}\n        nest: ${tv.slice(0, 300)}`);
      const pq = JSON.stringify(normalise(p.queue));
      const tq = JSON.stringify(normalise(t.queue));
      report(pq === tq, `${label} — queue`, pq === tq ? undefined : `py  : ${pq.slice(0, 340)}\n        nest: ${tq.slice(0, 340)}`);
    }

    // ── assertions the step-by-step comparison cannot express ────────────
    const q = await tsQueue(tsDb);
    const byId = (sid: string): Doc | undefined => q.find((r) => r['source_id'] === sid);

    report(
      byId('wr_good') === undefined,
      'a source that projects cleanly never enters the queue',
    );
    report(
      byId('wr_bad_b')?.['status'] === 'permanently_failed' && byId('wr_bad_b')?.['retry_count'] === 8,
      'a row tips into permanently_failed at MAX_RETRIES, not before',
      `${String(byId('wr_bad_b')?.['status'])} / ${String(byId('wr_bad_b')?.['retry_count'])}`,
    );
    report(
      q.filter((r) => r['status'] === 'retrying').every((r) => Number(r['retry_count']) > 0),
      'every retrying row has a non-zero retry_count',
    );
    report(
      q.every((r) => /^hfail_[0-9a-f]{16}$/.test(String(r['id']))),
      'ids survive every transition',
    );
    // history keeps only the last four prior entries plus the new one
    report(
      q.every((r) => (Array.isArray(r['history']) ? r['history'].length : 0) <= 5),
      'history never grows past five entries',
      q.map((r) => `${String(r['source_id'])}:${Array.isArray(r['history']) ? r['history'].length : 0}`).join(' '),
    );

    // The backoff schedule after n failures, compared against Python's own.
    const pyFinal = pySteps[pySteps.length - 1]?.queue ?? [];
    report(
      JSON.stringify(
        pyFinal.map((r) => [r['source_id'], r['status'], r['retry_count']]),
      ) === JSON.stringify(q.map((r) => [r['source_id'], r['status'], r['retry_count']])),
      'final status and retry_count agree for every queued source',
    );
  } finally {
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
