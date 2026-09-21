/**
 * Shared orchestration for a party-payment projection parity run.
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
 *
 * ONE implementation, configured per source type. mechanic_payment and
 * supplier_payment differ only in their fixtures and their extra assertions,
 * and a second copy of this file would drift from the first.
 */
import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { createServer, type Server } from 'node:http';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { MongoClient, type Db } from 'mongodb';
import { hookAfterSourceWrite } from '../../src/fin/fin-hook';

const MONGO = 'mongodb://127.0.0.1:27017';
const REPO = 'D:/Projects/TRUKVIA-clone';
const PY = 'D:/trk-venv/Scripts/python.exe';

export type Doc = Record<string, unknown>;
export type Report = (ok: boolean, name: string, detail?: string) => void;

export interface ParityConfig {
  /** The fin_txn source_type, e.g. "supplier_payment". */
  sourceType: string;
  /** The MongoDB collection holding the source documents. */
  collection: string;
  /** Short slug used in the throwaway database names. */
  slug: string;
  nestPort: number;
  /** The seeded source documents, across both tenants. */
  documents: Doc[];
  /** ids expected to project ZERO legs. */
  zeroLegged: string[];
  /** An id that exists under BOTH tenants, to prove scoping. */
  sharedId: string;
  /** Extra assertions over the TypeScript ledger rows. */
  extraChecks?: (rows: Doc[], report: Report) => void;
}

/**
 * ASYNCHRONOUS on purpose. execFileSync blocks the Node event loop, which
 * means an in-process HTTP stub can never accept a connection while Python is
 * running — the ok=false check below would hang until Python's own timeout
 * fired on every document. Spawning and awaiting keeps the loop free.
 */
function runPythonDriver(
  dbName: string,
  sourceType: string,
  specPath: string,
  extraEnv: Record<string, string> = {},
): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(
      PY,
      [`${REPO}/apps/api/scripts/fin_party_payment_driver.py`, dbName, sourceType, specPath],
      {
        cwd: `${REPO}/backend`,
        env: {
          ...process.env,
          PYTHONUTF8: '1',
          // Python puts the SCRIPT's directory on sys.path, not the cwd.
          PYTHONPATH: `${REPO}/backend`,
          MONGO_URL: MONGO,
          DB_NAME: dbName,
          ...extraEnv,
        },
        stdio: 'ignore',
        shell: false,
      },
    );
    child.on('error', reject);
    child.on('exit', (code) =>
      code === 0 ? resolve() : reject(new Error(`python driver exited ${code}`)),
    );
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

function startNest(dbName: string, port: number, token: string): ChildProcess {
  return spawn('npx', ['tsx', 'src/main.ts'], {
    cwd: `${REPO}/apps/api`,
    env: {
      ...process.env,
      PORT: String(port),
      NEST_MONGO_URL: MONGO,
      NEST_MONGO_DB: dbName,
      TRUKVIA_INTERNAL_TOKEN: token,
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

/** fin_txn rows, minus the two fields that legitimately differ between runs. */
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
  return (
    `at char ${i}\n        py   : …${a.slice(Math.max(0, i - 90), i + 130)}` +
    `\n        other: …${b.slice(Math.max(0, i - 90), i + 130)}`
  );
}

export async function runPartyPaymentParity(cfg: ParityConfig): Promise<void> {
  const stamp = Date.now();
  const PY_DB = `trukvia_${cfg.slug}parity_py_${stamp}`;
  const TS_DB = `trukvia_${cfg.slug}parity_ts_${stamp}`;
  const BRIDGE_DB = `trukvia_${cfg.slug}parity_bridge_${stamp}`;
  const INTERNAL_TOKEN = `${cfg.slug}parity-internal-${'x'.repeat(40)}`;

  const client = new MongoClient(MONGO);
  await client.connect();
  const pyDb = client.db(PY_DB);
  const tsDb = client.db(TS_DB);
  const brDb = client.db(BRIDGE_DB);

  const tenants = [
    ...new Set(cfg.documents.map((d) => `${String(d['user_id'])}|${String(d['company_id'])}`)),
  ];
  const seed = async (db: Db): Promise<void> => {
    for (const t of tenants) {
      const [uid, cid] = t.split('|');
      await db
        .collection('companies')
        .insertOne({ id: cid, user_id: uid, name: 'Parity Co', is_default: true });
    }
    const docs = cfg.documents.map((d) => {
      const clean: Doc = {};
      for (const [k, v] of Object.entries(d)) if (v !== undefined) clean[k] = v;
      return clean;
    });
    await db.collection(cfg.collection).insertMany(docs as never[]);
  };
  await seed(pyDb);
  await seed(tsDb);
  await seed(brDb);

  const spec = cfg.documents.map(
    (d) => [String(d['id']), String(d['user_id']), String(d['company_id'])] as [string, string, string],
  );
  const dir = mkdtempSync(join(tmpdir(), `${cfg.slug}parity-`));
  const specPath = join(dir, 'spec.json');
  writeFileSync(specPath, JSON.stringify(spec), 'utf8');

  let pass = 0;
  let fail = 0;
  const report: Report = (ok, name, detail) => {
    if (ok) {
      pass += 1;
      console.log(`  PASS  ${name}`);
    } else {
      fail += 1;
      console.log(`  FAIL  ${name}${detail ? `\n        ${detail}` : ''}`);
    }
  };

  try {
    await runPythonDriver(PY_DB, cfg.sourceType, specPath);

    for (let round = 0; round < 2; round += 1) {
      for (const [sid, uid, cid] of spec) {
        const r = await hookAfterSourceWrite(tsDb, uid, cid, cfg.sourceType, sid);
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

    const tsIds = new Set(tsRows.map((r) => String(r['source_id'])));
    report(
      cfg.zeroLegged.every((id) => !tsIds.has(id)),
      'guarded documents project zero legs',
      cfg.zeroLegged.filter((id) => tsIds.has(id)).join(', '),
    );

    const shared = tsRows.filter((r) => r['source_id'] === cfg.sharedId);
    const scopes = new Set(shared.map((r) => `${String(r['user_id'])}|${String(r['company_id'])}`));
    report(scopes.size === 2 && shared.length === 4, 'the shared id projects separately per tenant');

    cfg.extraChecks?.(tsRows, report);

    // ── BRIDGE: Python delegating to a live NestJS ───────────────────────
    killPort(cfg.nestPort);
    const nest = startNest(BRIDGE_DB, cfg.nestPort, INTERNAL_TOKEN);
    const bridgeEnv = {
      TRUKVIA_FIN_NODE_URL: `http://127.0.0.1:${cfg.nestPort}/internal/fin/reproject`,
      TRUKVIA_INTERNAL_TOKEN: INTERNAL_TOKEN,
      TRUKVIA_FIN_NODE_SOURCE_TYPES: cfg.sourceType,
    };
    try {
      if (!(await waitFor(`http://127.0.0.1:${cfg.nestPort}/api/vendors`))) {
        throw new Error('NestJS did not start');
      }
      await runPythonDriver(BRIDGE_DB, cfg.sourceType, specPath, bridgeEnv);
      const brText = JSON.stringify(await ledger(brDb));
      report(
        pyText === brText,
        'reverse bridge: Python delegating to NestJS matches Python native',
        pyText === brText ? undefined : diffAt(pyText, brText),
      );

      // Delegation is per source type, so a different list must NOT delegate.
      await brDb.collection('fin_txn').deleteMany({});
      await runPythonDriver(BRIDGE_DB, cfg.sourceType, specPath, {
        ...bridgeEnv,
        TRUKVIA_FIN_NODE_SOURCE_TYPES: 'some_other_type',
      });
      const offText = JSON.stringify(await ledger(brDb));
      report(
        pyText === offText,
        'delegation stays OFF for a type not in TRUKVIA_FIN_NODE_SOURCE_TYPES',
        pyText === offText ? undefined : diffAt(pyText, offText),
      );

      // And with no env at all — the default every deployment starts from.
      await brDb.collection('fin_txn').deleteMany({});
      await runPythonDriver(BRIDGE_DB, cfg.sourceType, specPath);
      const defaultText = JSON.stringify(await ledger(brDb));
      report(
        pyText === defaultText,
        'delegation is OFF by default, with no env set at all',
        pyText === defaultText ? undefined : diffAt(pyText, defaultText),
      );
    } finally {
      nest.kill();
      killPort(cfg.nestPort);
    }

    /**
     * A well-formed ok=false must NOT fall back. NestJS has already recorded
     * that failure in fin_hook_failures; projecting again in Python would
     * double-handle it and hide a real problem behind a silent success. Only a
     * TRANSPORT failure falls back. A stub standing in for NestJS is the only
     * honest way to produce a deterministic ok=false here.
     */
    await brDb.collection('fin_txn').deleteMany({});
    const stubPort = cfg.nestPort + 1;
    killPort(stubPort);
    const stub: Server = createServer((req, res) => {
      let body = '';
      req.on('data', (c) => (body += c));
      req.on('end', () => {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(
          JSON.stringify({
            ok: false,
            source_type: cfg.sourceType,
            source_id: 'stub',
            deleted: null,
            written: null,
            error: 'stubbed projection failure',
            failure_id: 'hfail_stub',
            resolved_failure_id: '',
          }),
        );
      });
    });
    await new Promise<void>((r) => stub.listen(stubPort, '127.0.0.1', r));
    try {
      await runPythonDriver(BRIDGE_DB, cfg.sourceType, specPath, {
        ...bridgeEnv,
        TRUKVIA_FIN_NODE_URL: `http://127.0.0.1:${stubPort}/internal/fin/reproject`,
      });
      const afterFalse = await ledger(brDb);
      report(
        afterFalse.length === 0,
        'a well-formed ok=false does NOT fall back to the local projection',
        `${afterFalse.length} rows were written locally`,
      );
    } finally {
      await new Promise<void>((r) => stub.close(() => r()));
      killPort(stubPort);
    }

    // ── Fallback: configured, but NestJS is gone ─────────────────────────
    await brDb.collection('fin_txn').deleteMany({});
    await runPythonDriver(BRIDGE_DB, cfg.sourceType, specPath, bridgeEnv);
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
