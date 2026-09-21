/**
 * Write parity: the same request sent to Python and to NestJS, each against its
 * OWN isolated copy of the data, then both the response and the resulting
 * MongoDB document compared.
 *
 * Why isolated copies: a write changes state, so the two stacks cannot share a
 * database or the second call would see the first call's effect.
 *
 *   npx tsx scripts/write-parity.ts
 *
 * The harness owns the whole lifecycle: it creates two throwaway Mongo
 * databases, seeds identical fixtures, starts a Python uvicorn and a NestJS
 * process pointed at them, runs the matrix, then drops the databases.
 *
 * Volatile fields (generated ids, timestamps) are normalised before comparison
 * and their SHAPE is asserted separately.
 */
import { execSync, spawn, type ChildProcess } from 'node:child_process';
import { MongoClient, type Db } from 'mongodb';
import { Pool } from 'pg';

const MONGO = 'mongodb://127.0.0.1:27017';
const PG_ADMIN = process.env.PG_URL ?? 'postgres://postgres@127.0.0.1:5433/trukvia';
/**
 * The harness needs its OWN Postgres database as well as its own Mongo ones.
 * NestJS writes refresh a Postgres read copy, so pointing it at the shared
 * database let harness fixtures leak into real data — caught on 2026-09-21,
 * 16 stray vendor rows.
 */
const PG_DB = `trukvia_wparity_${Date.now()}`;
const PG_URL = PG_ADMIN.replace(/\/[^/]+$/, `/${PG_DB}`);
const REPO = 'D:/Projects/TRUKVIA-clone';
const PY_PORT = 8401;
const NEST_PORT = 8402;
const stamp = Date.now();
const PY_DB = `trukvia_wparity_py_${stamp}`;
const NEST_DB = `trukvia_wparity_nest_${stamp}`;
const TOKEN = 'wparity-token';
const UID = 'user_wparity';
const CID = 'co_wparity';

const VOLATILE = new Set([
  'id',
  'created_at',
  'modified_at',
  'deactivated_at',
  'timestamp',
  '_id',
  'user_id',
  // audit rows reference the generated vendor id
  'entity_id',
]);

/**
 * An audit row's `changes` map is built by Python's `_diff_dict`, which
 * iterates `set(old.keys()) | set(new.keys())` — so its key order is arbitrary
 * by construction and is not part of any contract. Its keys are sorted before
 * comparison; the entries themselves are still compared exactly.
 */
const ORDER_INSENSITIVE = new Set(['changes']);

function normalise(value: unknown, key?: string): unknown {
  if (Array.isArray(value)) return value.map((v) => normalise(v));
  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    if (key && ORDER_INSENSITIVE.has(key)) entries.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    const out: Record<string, unknown> = {};
    for (const [k, v] of entries) {
      out[k] = VOLATILE.has(k) ? `<${k}>` : normalise(v, k);
    }
    return out;
  }
  return value;
}

async function seed(db: Db): Promise<void> {
  await db.collection('user_sessions').insertOne({
    session_token: TOKEN,
    user_id: UID,
    expires_at: new Date(Date.now() + 86_400_000),
    created_at: new Date(),
  });
  await db.collection('users').insertOne({
    user_id: UID,
    email: 'wparity@example.com',
    name: 'Write Parity',
  });
  await db.collection('companies').insertOne({
    id: CID,
    user_id: UID,
    name: 'Parity Co',
    is_default: true,
  });
  await db.collection('vendors').insertOne({
    id: 'ven_seed_1',
    user_id: UID,
    company_id: CID,
    name: 'Seed Vendor',
    contact_person: 'Person',
    mobile: '9999999999',
    alt_mobile: '',
    address: '',
    state: '',
    city: '',
    gst_in: '',
    pan: '',
    msme_number: '',
    bank_name: '',
    account_number: '',
    ifsc: '',
    branch: '',
    payment_terms: '',
    opening_balance: 0.0,
    opening_balance_type: 'payable',
    remarks: '',
    is_active: true,
    created_by: UID,
    created_at: '2026-09-01T00:00:00.000000+00:00',
    modified_by: '',
    modified_at: '',
    deactivated_by: '',
    deactivated_at: '',
    deactivation_reason: '',
    imported_from: '',
    imported_ref: '',
    imported_batch: '',
    is_historical: false,
  });
}

function startPython(): ChildProcess {
  return spawn(
    'D:/trk-venv/Scripts/python.exe',
    ['-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', String(PY_PORT), '--log-level', 'warning'],
    {
      cwd: `${REPO}/backend`,
      env: {
        ...process.env,
        MONGO_URL: MONGO,
        DB_NAME: PY_DB,
        DISABLE_SCHEDULER: '1',
        EMERGENT_LLM_KEY: '',
        REGRESSION_GUARD_PERIODIC: '0',
        PYTHONUTF8: '1',
      },
      stdio: 'ignore',
      shell: false,
    },
  );
}

function startNest(): ChildProcess {
  return spawn('npx', ['tsx', 'src/main.ts'], {
    cwd: `${REPO}/apps/api`,
    env: {
      ...process.env,
      PORT: String(NEST_PORT),
      NEST_MONGO_URL: MONGO,
      NEST_MONGO_DB: NEST_DB,
      PG_URL,
    },
    stdio: 'ignore',
    shell: true,
  });
}

/**
 * Kill whatever holds a port. `child.kill()` on Windows kills the shell, not
 * the node process it spawned, so a previous run can leave a server listening
 * and the next run then talks to a stale database. Killing by port is the only
 * reliable cleanup here.
 */
function killPort(port: number): void {
  try {
    const out = execSync(`netstat -ano | findstr :${port}`, { encoding: 'utf8' });
    const pids = new Set(
      out
        .split(String.fromCharCode(10))
        .filter((l) => l.includes('LISTENING'))
        .map((l) => l.trim().split(/\s+/).pop())
        .filter((p): p is string => Boolean(p) && p !== '0'),
    );
    for (const pid of pids) {
      try {
        execSync(`taskkill /F /PID ${pid}`, { stdio: 'ignore' });
      } catch {
        /* already gone */
      }
    }
  } catch {
    /* nothing listening */
  }
}

async function waitFor(url: string, tries = 240): Promise<boolean> {
  for (let i = 0; i < tries; i += 1) {
    try {
      const r = await fetch(url);
      if (r.status < 500) return true;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

interface Case {
  name: string;
  method: 'POST' | 'PUT' | 'DELETE';
  path: string;
  body?: unknown;
  auth?: boolean;
  /** Collections whose documents are compared after the call. */
  inspect?: string[];
}

const CASES: Case[] = [
  {
    name: 'create vendor, minimal body',
    method: 'POST',
    path: '/api/vendors',
    body: { name: 'Nest Parity Vendor' },
    inspect: ['vendors', 'audit_logs'],
  },
  {
    name: 'create vendor, full body',
    method: 'POST',
    path: '/api/vendors',
    body: {
      name: 'Full Vendor',
      contact_person: 'Contact',
      mobile: '9000000000',
      gst_in: '37ABAFV9364P1Z8',
      opening_balance: 1500.5,
      opening_balance_type: 'advance',
      remarks: 'seeded by parity harness',
      is_active: false,
    },
    inspect: ['vendors'],
  },
  {
    name: 'create vendor, unknown field ignored',
    method: 'POST',
    path: '/api/vendors',
    body: { name: 'Extra Field Vendor', not_a_field: 'x' },
    inspect: ['vendors'],
  },
  {
    name: 'create vendor, missing name -> 422',
    method: 'POST',
    path: '/api/vendors',
    body: { mobile: '1' },
  },
  {
    name: 'create vendor, bad literal -> 422',
    method: 'POST',
    path: '/api/vendors',
    body: { name: 'Bad Literal', opening_balance_type: 'nope' },
  },
  {
    name: 'create vendor, bad float -> 422',
    method: 'POST',
    path: '/api/vendors',
    body: { name: 'Bad Float', opening_balance: 'abc' },
  },
  {
    name: 'create vendor, no auth -> 401',
    method: 'POST',
    path: '/api/vendors',
    body: { name: 'No Auth' },
    auth: false,
  },
  {
    name: 'update vendor',
    method: 'PUT',
    path: '/api/vendors/ven_seed_1',
    body: { name: 'Seed Vendor Renamed', mobile: '8888888888' },
    inspect: ['vendors', 'audit_logs'],
  },
  {
    name: 'update unknown vendor -> 404',
    method: 'PUT',
    path: '/api/vendors/ven_nope',
    body: { name: 'x' },
  },
  {
    name: 'deactivate vendor',
    method: 'DELETE',
    path: '/api/vendors/ven_seed_1?reason=closed%20account',
    inspect: ['vendors', 'audit_logs'],
  },
  {
    name: 'deactivate unknown vendor -> 404',
    method: 'DELETE',
    path: '/api/vendors/ven_nope',
  },
  {
    name: 'reactivate vendor',
    method: 'POST',
    path: '/api/vendors/ven_seed_1/reactivate',
    inspect: ['vendors', 'audit_logs'],
  },
];

async function createPgDatabase(): Promise<void> {
  const admin = new Pool({ connectionString: PG_ADMIN, max: 1 });
  await admin.query(`CREATE DATABASE "${PG_DB}"`);
  await admin.end();
  const fresh = new Pool({ connectionString: PG_URL, max: 1 });
  await fresh.query('CREATE SCHEMA IF NOT EXISTS trukvia');
  // Mirror the live schema so the write path exercises the real DDL.
  const src = new Pool({ connectionString: PG_ADMIN, max: 1 });
  const cols = await src.query(
    `SELECT table_name, column_name, data_type, character_maximum_length,
            numeric_precision, numeric_scale, is_nullable, column_default
       FROM information_schema.columns WHERE table_schema='trukvia'
      ORDER BY table_name, ordinal_position`,
  );
  const byTable = new Map<string, string[]>();
  for (const c of cols.rows) {
    const t = c.table_name as string;
    let type = c.data_type as string;
    if (type === 'numeric' && c.numeric_precision) {
      type = `numeric(${c.numeric_precision},${c.numeric_scale})`;
    }
    if (type === 'character varying' && c.character_maximum_length) {
      type = `varchar(${c.character_maximum_length})`;
    }
    const def = c.column_default ? ` DEFAULT ${c.column_default}` : '';
    const nn = c.is_nullable === 'NO' ? ' NOT NULL' : '';
    byTable.set(t, [...(byTable.get(t) ?? []), `"${c.column_name}" ${type}${def}${nn}`]);
  }
  for (const [table, defs] of byTable) {
    await fresh.query(`CREATE TABLE trukvia."${table}" (${defs.join(', ')}, PRIMARY KEY (id))`);
  }
  await fresh.end();
  await src.end();
}

async function dropPgDatabase(): Promise<void> {
  const admin = new Pool({ connectionString: PG_ADMIN, max: 1 });
  await admin.query(`DROP DATABASE IF EXISTS "${PG_DB}" WITH (FORCE)`);
  await admin.end();
}

async function main(): Promise<void> {
  await createPgDatabase();
  const client = new MongoClient(MONGO);
  await client.connect();
  const pyDb = client.db(PY_DB);
  const nestDb = client.db(NEST_DB);
  await seed(pyDb);
  await seed(nestDb);

  killPort(PY_PORT);
  killPort(NEST_PORT);
  const py = startPython();
  const nest = startNest();
  let pass = 0;
  let fail = 0;

  try {
    const pyUp = await waitFor(`http://127.0.0.1:${PY_PORT}/api/auth/health`);
    const nestUp = await waitFor(`http://127.0.0.1:${NEST_PORT}/api/vendors`);
    if (!pyUp || !nestUp) throw new Error(`servers did not start (py=${pyUp} nest=${nestUp})`);

    for (const c of CASES) {
      const headers: Record<string, string> = { 'content-type': 'application/json' };
      if (c.auth !== false) headers['authorization'] = `Bearer ${TOKEN}`;
      const init: RequestInit = { method: c.method, headers };
      if (c.body !== undefined) init.body = JSON.stringify(c.body);

      const a = await fetch(`http://127.0.0.1:${PY_PORT}${c.path}`, init);
      const b = await fetch(`http://127.0.0.1:${NEST_PORT}${c.path}`, init);
      const [ta, tb] = [await a.text(), await b.text()];

      const problems: string[] = [];
      if (a.status !== b.status) problems.push(`status ${a.status} vs ${b.status}`);
      else {
        let ja: unknown;
        let jb: unknown;
        try {
          ja = JSON.parse(ta);
          jb = JSON.parse(tb);
        } catch {
          problems.push('non-JSON body');
        }
        const na = JSON.stringify(normalise(ja));
        const nb = JSON.stringify(normalise(jb));
        if (na !== nb) problems.push(`body\n        py  : ${na.slice(0, 260)}\n        nest: ${nb.slice(0, 260)}`);
      }

      for (const coll of c.inspect ?? []) {
        const [da, dbb] = await Promise.all([
          pyDb.collection(coll).find({}).sort({ _id: 1 }).toArray(),
          nestDb.collection(coll).find({}).sort({ _id: 1 }).toArray(),
        ]);
        const na = JSON.stringify(normalise(da));
        const nb = JSON.stringify(normalise(dbb));
        if (na !== nb) {
          let at = 0;
          while (at < Math.min(na.length, nb.length) && na[at] === nb[at]) at += 1;
          problems.push(
            `${coll} documents differ (py ${da.length} rows, nest ${dbb.length} rows) at char ${at}` +
              `\n        py  : …${na.slice(Math.max(0, at - 80), at + 110)}` +
              `\n        nest: …${nb.slice(Math.max(0, at - 80), at + 110)}`,
          );
        }
      }

      if (problems.length) {
        fail += 1;
        console.log(`  FAIL  ${c.name}\n        ${problems.join('\n        ')}`);
      } else {
        pass += 1;
        console.log(`  PASS  ${c.name}  (${a.status})`);
      }
    }

    // generated-value shapes, which normalisation hides
    const created = await nestDb.collection('vendors').findOne({ name: 'Nest Parity Vendor' });
    const shapeOk =
      /^ven_[0-9a-f]{16}$/.test(String(created?.['id'])) &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$/.test(String(created?.['created_at']));
    console.log(`  ${shapeOk ? 'PASS' : 'FAIL'}  generated id and timestamp shape`);
    shapeOk ? (pass += 1) : (fail += 1);

    // the Postgres read copy must reflect the writes
    const pool = new Pool({ connectionString: PG_URL, max: 2 });
    const pgRow = await pool.query('SELECT name, is_active FROM trukvia.vendor WHERE id = $1', [
      'ven_seed_1',
    ]);
    const mongoRow = await nestDb.collection('vendors').findOne({ id: 'ven_seed_1' });
    const synced =
      pgRow.rows[0]?.name === mongoRow?.['name'] &&
      pgRow.rows[0]?.is_active === mongoRow?.['is_active'];
    console.log(`  ${synced ? 'PASS' : 'FAIL'}  Postgres read copy matches the Mongo document`);
    synced ? (pass += 1) : (fail += 1);
    await pool.end();
  } finally {
    py.kill();
    nest.kill();
    killPort(PY_PORT);
    killPort(NEST_PORT);
    await new Promise((r) => setTimeout(r, 1500));
    await pyDb.dropDatabase();
    await nestDb.dropDatabase();
    await client.close();
    await dropPgDatabase();
  }

  console.log(`\ncases ${pass + fail}   PASS ${pass}   FAIL ${fail}`);
  process.exit(fail ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
