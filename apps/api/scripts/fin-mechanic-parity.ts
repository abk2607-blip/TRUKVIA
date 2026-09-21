/**
 * Focused parity for slice 2c unit 2 — the `mechanic_payment` projection.
 *
 *   npx tsx scripts/fin-mechanic-parity.ts
 *
 * Three throwaway MongoDB databases, seeded identically:
 *
 *   PY      Python's real hook_after_source_write projects locally
 *   TS      the NestJS port projects in-process
 *   BRIDGE  Python's hook DELEGATES to a live NestJS over the reverse bridge,
 *           so Python writes nothing and NestJS writes everything
 *
 * PY is the reference. TS and BRIDGE must both reproduce it exactly, which
 * covers the ledger maths and the end-to-end reverse direction in one run.
 *
 * Every source document is reprojected TWICE on each side, so delete-then-
 * insert idempotency is part of the comparison rather than a separate test.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { MongoClient, type Db } from 'mongodb';
import { hookAfterSourceWrite } from '../src/fin/fin-hook';

const MONGO = 'mongodb://127.0.0.1:27017';
const REPO = 'D:/Projects/TRUKVIA-clone';
const PY = 'D:/trk-venv/Scripts/python.exe';
const stamp = Date.now();
const PY_DB = `trukvia_mechparity_py_${stamp}`;
const TS_DB = `trukvia_mechparity_ts_${stamp}`;
const BRIDGE_DB = `trukvia_mechparity_bridge_${stamp}`;
const NEST_PORT = 8421;
const INTERNAL_TOKEN = `mechparity-internal-${'x'.repeat(40)}`;

const UID = 'user_mechparity';
const CID = 'co_mechparity';
/** A second tenant, to prove one scope cannot project another's document. */
const UID2 = 'user_mechparity_other';
const CID2 = 'co_mechparity_other';

type Doc = Record<string, unknown>;

/**
 * Cases chosen for what they exercise, not for coverage of the happy path:
 * every guard in _party_payment_legs, both directions, every account-resolving
 * mode including an unknown one, the rounding rule, and the narration strip.
 */
function payments(): Doc[] {
  const base = (over: Doc): Doc => ({
    user_id: UID,
    company_id: CID,
    mechanic_id: 'mech_1',
    date: '2026-09-02',
    amount: 1000,
    mode: 'Bank',
    type: 'payment_out',
    ref_no: 'MP-001',
    is_deleted: false,
    is_reversed: false,
    ...over,
  });
  return [
    base({ id: 'mpay_out_bank' }),
    base({ id: 'mpay_out_cash', mode: 'Cash' }),
    base({ id: 'mpay_out_upi', mode: 'UPI' }),
    base({ id: 'mpay_out_unknown_mode', mode: 'Crypto' }), // -> BANK_DEFAULT
    base({ id: 'mpay_out_blank_mode', mode: '' }), // falsy -> "Bank"
    base({ id: 'mpay_out_missing_mode', mode: undefined }),
    base({ id: 'mpay_in_receipt', type: 'receipt_in' }),
    base({ id: 'mpay_in_receipt_cash', type: 'receipt_in', mode: 'Cash' }),
    base({ id: 'mpay_missing_type', type: undefined }), // -> payment_out
    base({ id: 'mpay_blank_type', type: '' }), // falsy -> payment_out
    base({ id: 'mpay_unknown_type', type: 'refund' }), // not payment_out -> receipt branch
    // guards: each must project ZERO legs
    base({ id: 'mpay_deleted', is_deleted: true }),
    base({ id: 'mpay_reversed', is_reversed: true }),
    base({ id: 'mpay_zero', amount: 0 }),
    base({ id: 'mpay_negative', amount: -50 }),
    base({ id: 'mpay_null_amount', amount: null }),
    base({ id: 'mpay_missing_amount', amount: undefined }),
    // money semantics
    base({ id: 'mpay_round_half_even', amount: 2.675 }), // Python round() -> 2.67
    base({ id: 'mpay_round_tie', amount: 0.125 }), // exact tie -> 0.12
    base({ id: 'mpay_paise', amount: 1234.56 }),
    base({ id: 'mpay_string_amount', amount: '750.25' }),
    base({ id: 'mpay_big', amount: 98765432.1 }),
    // narration and party edges
    base({ id: 'mpay_no_ref', ref_no: '' }), // strip(" ·") eats the separator
    base({ id: 'mpay_missing_ref', ref_no: undefined }),
    base({ id: 'mpay_long_ref', ref_no: 'R'.repeat(500) }), // narration caps at 400
    base({ id: 'mpay_unicode_ref', ref_no: 'ref · भुगतान · 数' }),
    base({ id: 'mpay_no_mechanic', mechanic_id: '' }),
    base({ id: 'mpay_missing_mechanic', mechanic_id: undefined }),
    base({ id: 'mpay_missing_date', date: undefined }),
    // a second tenant holding the SAME id, to prove scoping
    base({ id: 'mpay_out_bank', user_id: UID2, company_id: CID2, amount: 4242, ref_no: 'OTHER' }),
  ];
}

async function seed(db: Db): Promise<void> {
  for (const [uid, cid] of [
    [UID, CID],
    [UID2, CID2],
  ]) {
    await db.collection('companies').insertOne({ id: cid, user_id: uid, name: 'Mech Co', is_default: true });
  }
  const docs = payments().map((d) => {
    const clean: Doc = {};
    for (const [k, v] of Object.entries(d)) if (v !== undefined) clean[k] = v;
    return clean;
  });
  await db.collection('mechanic_payments').insertMany(docs as never[]);
}

/** [source_id, uid, cid] for every seeded payment, both tenants. */
function spec(): Array<[string, string, string]> {
  return payments().map((d) => [String(d['id']), String(d['user_id']), String(d['company_id'])]);
}

function runPythonDriver(dbName: string, specPath: string, extraEnv: Record<string, string> = {}): void {
  execFileSync(PY, [`${REPO}/apps/api/scripts/fin_mechanic_driver.py`, dbName, specPath], {
    cwd: `${REPO}/backend`,
    encoding: 'utf8',
    env: {
      ...process.env,
      PYTHONUTF8: '1',
      PYTHONPATH: `${REPO}/backend`,
      MONGO_URL: MONGO,
      DB_NAME: dbName,
      ...extraEnv,
    },
    maxBuffer: 32 * 1024 * 1024,
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

function startNest(dbName: string): ChildProcess {
  return spawn('npx', ['tsx', 'src/main.ts'], {
    cwd: `${REPO}/apps/api`,
    env: {
      ...process.env,
      PORT: String(NEST_PORT),
      NEST_MONGO_URL: MONGO,
      NEST_MONGO_DB: dbName,
      TRUKVIA_INTERNAL_TOKEN: INTERNAL_TOKEN,
      // The bridge must project LOCALLY, never bounce back to Python.
      TRUKVIA_FIN_HOOK_URL: '',
    },
    stdio: 'ignore',
    shell: true,
  });
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

/** fin_txn rows, minus the fields that legitimately differ between runs. */
async function ledger(db: Db): Promise<Doc[]> {
  const rows = await db
    .collection<Doc>('fin_txn')
    .find({}, { projection: { _id: 0 } })
    .toArray();
  return rows
    .map((r) => {
      const out: Doc = {};
      for (const k of Object.keys(r).sort()) {
        // created_at and projected_at are wall-clock stamps of the run itself.
        out[k] = k === 'created_at' || k === 'projected_at' ? `<${k}>` : r[k];
      }
      return out;
    })
    .sort((a, b) =>
      `${String(a['user_id'])}|${String(a['ref_source_key'])}`.localeCompare(
        `${String(b['user_id'])}|${String(b['ref_source_key'])}`,
      ),
    );
}

async function accounts(db: Db): Promise<Doc[]> {
  const rows = await db
    .collection<Doc>('fin_accounts')
    .find({}, { projection: { _id: 0, created_at: 0 } })
    .toArray();
  return rows.sort((a, b) =>
    `${String(a['user_id'])}|${String(a['code'])}`.localeCompare(
      `${String(b['user_id'])}|${String(b['code'])}`,
    ),
  );
}

function diffAt(a: string, b: string): string {
  let i = 0;
  while (i < Math.min(a.length, b.length) && a[i] === b[i]) i += 1;
  return `at char ${i}\n        py  : …${a.slice(Math.max(0, i - 90), i + 130)}\n        other: …${b.slice(Math.max(0, i - 90), i + 130)}`;
}

async function main(): Promise<void> {
  const client = new MongoClient(MONGO);
  await client.connect();
  const pyDb = client.db(PY_DB);
  const tsDb = client.db(TS_DB);
  const brDb = client.db(BRIDGE_DB);
  await seed(pyDb);
  await seed(tsDb);
  await seed(brDb);

  const dir = mkdtempSync(join(tmpdir(), 'mechparity-'));
  const specPath = join(dir, 'spec.json');
  writeFileSync(specPath, JSON.stringify(spec()), 'utf8');

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
    // ── PY: the reference ────────────────────────────────────────────────
    runPythonDriver(PY_DB, specPath);

    // ── TS: the port, in process, each source twice ──────────────────────
    for (let pass2 = 0; pass2 < 2; pass2 += 1) {
      for (const [sid, uid, cid] of spec()) {
        const r = await hookAfterSourceWrite(tsDb, uid, cid, 'mechanic_payment', sid);
        if (!r.ok) throw new Error(`ts projection failed for ${sid}: ${r.error}`);
      }
    }

    const pyRows = await ledger(pyDb);
    const tsRows = await ledger(tsDb);
    console.log(`fin_txn rows: python ${pyRows.length}, typescript ${tsRows.length}`);
    report(pyRows.length === tsRows.length, 'leg count', `py ${pyRows.length} vs ts ${tsRows.length}`);
    const pyText = JSON.stringify(pyRows);
    const tsText = JSON.stringify(tsRows);
    report(pyText === tsText, 'fin_txn rows identical', pyText === tsText ? undefined : diffAt(pyText, tsText));

    const pyAcc = JSON.stringify(await accounts(pyDb));
    const tsAcc = JSON.stringify(await accounts(tsDb));
    report(pyAcc === tsAcc, 'fin_accounts identical', pyAcc === tsAcc ? undefined : diffAt(pyAcc, tsAcc));

    // Guards must produce nothing at all, not a zero-amount leg.
    const zeroLegged = [
      'mpay_deleted',
      'mpay_reversed',
      'mpay_zero',
      'mpay_negative',
      'mpay_null_amount',
      'mpay_missing_amount',
    ];
    const tsIds = new Set(tsRows.map((r) => String(r['source_id'])));
    report(
      zeroLegged.every((id) => !tsIds.has(id)),
      'guarded documents project zero legs',
      zeroLegged.filter((id) => tsIds.has(id)).join(', '),
    );

    // Tenant isolation: the shared id exists under both scopes, separately.
    const shared = tsRows.filter((r) => r['source_id'] === 'mpay_out_bank');
    const scopes = new Set(shared.map((r) => `${String(r['user_id'])}|${String(r['company_id'])}`));
    report(scopes.size === 2 && shared.length === 4, 'the shared id projects separately per tenant');

    // ── BRIDGE: Python delegating to a live NestJS ───────────────────────
    killPort(NEST_PORT);
    const nest = startNest(BRIDGE_DB);
    try {
      if (!(await waitFor(`http://127.0.0.1:${NEST_PORT}/api/vendors`))) {
        throw new Error('NestJS did not start');
      }
      runPythonDriver(BRIDGE_DB, specPath, {
        TRUKVIA_FIN_NODE_URL: `http://127.0.0.1:${NEST_PORT}/internal/fin/reproject`,
        TRUKVIA_INTERNAL_TOKEN: INTERNAL_TOKEN,
        TRUKVIA_FIN_NODE_SOURCE_TYPES: 'mechanic_payment',
      });
      const brRows = await ledger(brDb);
      const brText = JSON.stringify(brRows);
      report(
        pyText === brText,
        'reverse bridge: Python delegating to NestJS matches Python native',
        pyText === brText ? undefined : diffAt(pyText, brText),
      );
    } finally {
      nest.kill();
      killPort(NEST_PORT);
    }

    // ── Fallback: the bridge is configured but NestJS is gone ────────────
    await brDb.collection('fin_txn').deleteMany({});
    runPythonDriver(BRIDGE_DB, specPath, {
      TRUKVIA_FIN_NODE_URL: `http://127.0.0.1:${NEST_PORT}/internal/fin/reproject`,
      TRUKVIA_INTERNAL_TOKEN: INTERNAL_TOKEN,
      TRUKVIA_FIN_NODE_SOURCE_TYPES: 'mechanic_payment',
    });
    const fbText = JSON.stringify(await ledger(brDb));
    report(
      pyText === fbText,
      'an unreachable NestJS falls back to the local projection',
      pyText === fbText ? undefined : diffAt(pyText, fbText),
    );
  } finally {
    await pyDb.dropDatabase();
    await tsDb.dropDatabase();
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
