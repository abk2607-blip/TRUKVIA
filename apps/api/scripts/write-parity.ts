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
import { Double, MongoClient, type Db } from 'mongodb';
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
/**
 * A THIRD process: a Python instance pointed at the NestJS database, acting as
 * that stack's internal projection hook. In production both services share one
 * database; the harness only separates them so the two stacks cannot see each
 * other's writes, so the hook needs its own Python against NEST_DB.
 */
const HOOK_PORT = 8403;
const stamp = Date.now();
const PY_DB = `trukvia_wparity_py_${stamp}`;
const NEST_DB = `trukvia_wparity_nest_${stamp}`;
const TOKEN = 'wparity-token';
const STAFF_TOKEN = 'wparity-staff-token';
/**
 * The harness exercises the INTERNAL projection hook end to end: its Python is
 * started with a secret, and its NestJS is pointed at that Python's
 * /internal/fin/reproject. Set WPARITY_NO_HOOK=1 to exercise the TypeScript
 * port fallback instead.
 */
const INTERNAL_TOKEN = `wparity-internal-${'x'.repeat(40)}`;
const USE_HOOK = process.env.WPARITY_NO_HOOK !== '1';
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
  // ledger rows stamp when they were projected
  'projected_at',
  // day-closure lifecycle stamps, including each history event's `at`
  'closed_at',
  'reopened_at',
  'at',
]);

/**
 * An audit row's `changes` map is built by Python's `_diff_dict`, which
 * iterates `set(old.keys()) | set(new.keys())` — so its key order is arbitrary
 * by construction and is not part of any contract. Its keys are sorted before
 * comparison; the entries themselves are still compared exactly.
 */
const ORDER_INSENSITIVE = new Set(['changes']);

/**
 * fin_txn rows are created by an UPSERT, and MongoDB builds an upserted
 * document from the filter's equality fields. pymongo and the Node driver
 * serialise that filter in different orders, so the stored key order differs
 * even for an identical call — verified directly:
 *   pymongo → _id, company_id, ref_source_key, user_id, id, ...
 *   node    → _id, ref_source_key, user_id, company_id, id, ...
 * The VALUES are identical (12,032 rows verified by fin-projection-parity), and
 * JSON objects are unordered, so these documents are compared key-insensitively.
 */
const ORDER_INSENSITIVE_COLLECTIONS = new Set(['fin_txn']);

function deepSortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(deepSortKeys);
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(value as Record<string, unknown>).sort()) {
      out[k] = deepSortKeys((value as Record<string, unknown>)[k]);
    }
    return out;
  }
  return value;
}

/**
 * Generated ids appear INSIDE strings too — a ledger row's ref_source_key is
 * "vendor_bill:<generated id>:suspense_debit" and its source_id is the raw id.
 * Those differ between the two stacks by design, so the id token is replaced
 * while the surrounding structure is still compared.
 */
const GENERATED_ID = /(ven|vbl|vpay|audit|fintxn|acc|fdc)_[0-9a-zA-Z]{8,}/g;
const scrub = (s: string): string => s.replace(GENERATED_ID, '<gen>');

function normalise(value: unknown, key?: string): unknown {
  if (typeof value === 'string') return scrub(value);
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
  await db.collection('vehicles').insertOne({
    id: 'veh_seed_1',
    user_id: UID,
    company_id: CID,
    vehicle_number: 'AP16AB1234',
  });

  // ── slice 2b: day-closure fixtures ────────────────────────────────────
  // A second identity that resolves to a NON-owner role, so the 403 guard is
  // actually exercised. auth remaps a team_members row whose owner_user_id
  // differs from the member's own user_id.
  await db.collection('user_sessions').insertOne({
    session_token: STAFF_TOKEN,
    user_id: 'user_wparity_staff',
    expires_at: new Date(Date.now() + 86_400_000),
    created_at: new Date(),
  });
  await db.collection('users').insertOne({
    user_id: 'user_wparity_staff',
    email: 'staff@example.com',
    name: 'Staff Member',
  });
  await db.collection('team_members').insertOne({
    email: 'staff@example.com',
    owner_user_id: UID,
    role: 'accountant',
    active: true,
  });

  // Python's startup creates the unique (user_id, company_id, close_date)
  // index; the NestJS database never runs that startup, so the harness has to
  // create it or the concurrent-write 409 branch could not exist there.
  await db.collection('fin_day_closures').createIndex(
    { user_id: 1, company_id: 1, close_date: 1 },
    { unique: true },
  );

  /**
   * Ledger legs for the snapshot. Amounts are chosen to exercise the parts
   * that have actually broken before:
   *   • 52400 is a whole number, so it must come back as 52400.0 and be
   *     stored as a BSON double, not an int32;
   *   • 10.005 twice sums to 20.009999999999998, whose round() outcome
   *     depends on using Python's exact half-to-even rule;
   *   • a leg dated after the close date must be excluded;
   *   • a reversed (non-active) leg must be excluded.
   */
  const leg = (
    id: string,
    code: string,
    direction: string,
    amount: number,
    txnDate: string,
    status = 'active',
  ): Record<string, unknown> => ({
    id,
    user_id: UID,
    company_id: CID,
    account_code: code,
    direction,
    amount: new Double(amount),
    txn_date: txnDate,
    status,
    created_at: `${txnDate}T00:00:00.000000+00:00`,
  });
  await db.collection('fin_txn').insertMany([
    leg('fintxn_s1', 'CASH', 'in', 52400, '2026-09-01'),
    leg('fintxn_s2', 'CASH', 'out', 10.005, '2026-09-01'),
    leg('fintxn_s3', 'CASH', 'out', 10.005, '2026-09-02'),
    leg('fintxn_s4', 'AR', 'in', 0, '2026-09-02'),
    leg('fintxn_s5', 'EXPENSE_DEFAULT', 'out', 1234.56, '2026-09-02'),
    leg('fintxn_s6', 'CASH', 'in', 999, '2026-09-30'),
    leg('fintxn_s7', 'CASH', 'in', 777, '2026-09-01', 'reversed'),
  ]);

  // An already-closed day, for the 409 and the reopen path.
  await db.collection('fin_day_closures').insertOne({
    id: 'fdc_seed_closed01',
    user_id: UID,
    company_id: CID,
    close_date: '2026-09-05',
    status: 'closed',
    closed_at: '2026-09-05T10:00:00.000000+00:00',
    closed_by: UID,
    close_notes: 'seeded',
    snapshot: { CASH: { in: new Double(52400), out: new Double(20.01), net: new Double(52379.99) } },
    snapshot_source_count: 4,
    reopened_at: '',
    reopened_by: '',
    reopen_reason: '',
    history: [
      {
        event: 'closed',
        at: '2026-09-05T10:00:00.000000+00:00',
        by: UID,
        notes: 'seeded',
        snapshot: { CASH: { in: new Double(52400), out: new Double(20.01), net: new Double(52379.99) } },
        snapshot_source_count: 4,
      },
    ],
    created_at: '2026-09-05T10:00:00.000000+00:00',
    modified_at: '',
  });

  // A day already reopened, so the reopen 409 and the re-close path both exist.
  await db.collection('fin_day_closures').insertOne({
    id: 'fdc_seed_reopen1',
    user_id: UID,
    company_id: CID,
    close_date: '2026-09-06',
    status: 'reopened',
    closed_at: '2026-09-06T10:00:00.000000+00:00',
    closed_by: UID,
    close_notes: 'seeded reopened',
    snapshot: { CASH: { in: new Double(1), out: new Double(0), net: new Double(1) } },
    snapshot_source_count: 1,
    reopened_at: '2026-09-06T11:00:00.000000+00:00',
    reopened_by: UID,
    reopen_reason: 'seeded reason',
    history: [
      {
        event: 'closed',
        at: '2026-09-06T10:00:00.000000+00:00',
        by: UID,
        notes: 'seeded reopened',
        snapshot: { CASH: { in: new Double(1), out: new Double(0), net: new Double(1) } },
        snapshot_source_count: 1,
      },
      { event: 'reopened', at: '2026-09-06T11:00:00.000000+00:00', by: UID, reason: 'seeded reason' },
    ],
    created_at: '2026-09-06T10:00:00.000000+00:00',
    modified_at: '2026-09-06T11:00:00.000000+00:00',
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
        ...(USE_HOOK ? { TRUKVIA_INTERNAL_TOKEN: INTERNAL_TOKEN } : {}),
      },
      stdio: 'ignore',
      shell: false,
    },
  );
}

function startPythonHook(): ChildProcess {
  return spawn(
    'D:/trk-venv/Scripts/python.exe',
    ['-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', String(HOOK_PORT),
     '--log-level', 'warning'],
    {
      cwd: `${REPO}/backend`,
      env: {
        ...process.env,
        MONGO_URL: MONGO,
        DB_NAME: NEST_DB,
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

function startNest(): ChildProcess {
  return spawn('npx', ['tsx', 'src/main.ts'], {
    cwd: `${REPO}/apps/api`,
    env: {
      ...process.env,
      PORT: String(NEST_PORT),
      NEST_MONGO_URL: MONGO,
      NEST_MONGO_DB: NEST_DB,
      PG_URL,
      ...(USE_HOOK
        ? {
            TRUKVIA_FIN_HOOK_URL: `http://127.0.0.1:${HOOK_PORT}/internal/fin/reproject`,
            TRUKVIA_INTERNAL_TOKEN: INTERNAL_TOKEN,
          }
        : { TRUKVIA_FIN_HOOK_URL: '', TRUKVIA_INTERNAL_TOKEN: '' }),
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
  /** Sent verbatim instead of JSON.stringify(body) — for malformed bodies. */
  rawBody?: string;
  /** Override the bearer token, e.g. to exercise a non-owner role. */
  token?: string;
  /** null omits the header entirely; a string replaces application/json. */
  contentType?: string | null;
  /**
   * A difference that is understood, deliberate and documented. The case still
   * runs and is still reported — it is not a skip — but it does not fail the
   * harness. The string says why.
   */
  knownDivergence?: string;
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
  // ── vendor bills ────────────────────────────────────────────────────────
  {
    name: 'create bill',
    method: 'POST',
    path: '/api/vendor-bills',
    body: {
      vendor_id: 'ven_seed_1',
      bill_number: 'B-001',
      bill_date: '2026-09-01',
      bill_amount: 18000,
      vehicle_id: 'veh_seed_1',
      narration: 'brake pads',
    },
    inspect: ['vendor_bills', 'fin_txn', 'fin_accounts'],
  },
  {
    name: 'create bill, duplicate number -> 409',
    method: 'POST',
    path: '/api/vendor-bills',
    body: { vendor_id: 'ven_seed_1', bill_number: 'B-001', bill_date: '2026-09-01', bill_amount: 100 },
  },
  {
    name: 'create bill, unknown vendor -> 400',
    method: 'POST',
    path: '/api/vendor-bills',
    body: { vendor_id: 'ven_nope', bill_date: '2026-09-01', bill_amount: 100 },
  },
  {
    name: 'create bill, zero amount -> 400',
    method: 'POST',
    path: '/api/vendor-bills',
    body: { vendor_id: 'ven_seed_1', bill_date: '2026-09-01', bill_amount: 0 },
  },
  {
    name: 'create bill, missing bill_date -> 422',
    method: 'POST',
    path: '/api/vendor-bills',
    body: { vendor_id: 'ven_seed_1', bill_amount: 100 },
  },
  // ── vendor payments ─────────────────────────────────────────────────────
  {
    name: 'create payment (payment_out, Bank)',
    method: 'POST',
    path: '/api/vendors/ven_seed_1/payments',
    body: { vendor_id: 'ven_seed_1', date: '2026-09-02', amount: 5000, mode: 'Bank', ref_no: 'TXN-1' },
    inspect: ['vendor_payments', 'fin_txn', 'audit_logs'],
  },
  {
    name: 'create payment (receipt_in, Cash)',
    method: 'POST',
    path: '/api/vendors/ven_seed_1/payments',
    body: {
      vendor_id: 'ven_seed_1',
      date: '2026-09-03',
      amount: 1250.75,
      mode: 'Cash',
      type: 'receipt_in',
    },
    inspect: ['vendor_payments', 'fin_txn'],
  },
  {
    name: 'create payment, body without vendor_id -> 422',
    method: 'POST',
    path: '/api/vendors/ven_seed_1/payments',
    body: { date: '2026-09-02', amount: 100 },
  },
  {
    name: 'create payment, unknown vendor -> 404',
    method: 'POST',
    path: '/api/vendors/ven_nope/payments',
    body: { vendor_id: 'ven_nope', date: '2026-09-02', amount: 100 },
  },
  {
    name: 'create payment, zero amount -> 400',
    method: 'POST',
    path: '/api/vendors/ven_seed_1/payments',
    body: { vendor_id: 'ven_seed_1', date: '2026-09-02', amount: 0 },
  },
  {
    name: 'create payment, bad mode -> 422',
    method: 'POST',
    path: '/api/vendors/ven_seed_1/payments',
    body: { vendor_id: 'ven_seed_1', date: '2026-09-02', amount: 100, mode: 'Barter' },
  },
  {
    name: 'create payment, unknown bill -> 400',
    method: 'POST',
    path: '/api/vendors/ven_seed_1/payments',
    body: { vendor_id: 'ven_seed_1', date: '2026-09-02', amount: 100, vendor_bill_id: 'vbl_nope' },
  },
  {
    name: 'delete payment without reason -> 422',
    method: 'DELETE',
    path: '/api/vendors/ven_seed_1/payments/vpay_nope',
  },
  {
    name: 'delete bill, short reason -> 422',
    method: 'DELETE',
    path: '/api/vendor-bills/vbl_nope?reason=ab',
  },

  // ── slice 2b: POST /api/fin/day-closures ──────────────────────────────
  // Pipeline order first: a JSON PARSE error outranks authentication, while a
  // structural body error does not. Both use a bad token so the ordering is
  // unambiguous.
  {
    name: 'close: unparseable JSON with a bad token -> 422 before auth',
    method: 'POST',
    path: '/api/fin/day-closures',
    rawBody: 'not json',
    token: 'bogus-token',
  },
  {
    name: 'close: JSON array with a bad token -> 401, auth first',
    method: 'POST',
    path: '/api/fin/day-closures',
    rawBody: '[1,2]',
    token: 'bogus-token',
  },
  { name: 'close: no auth', method: 'POST', path: '/api/fin/day-closures', body: {}, auth: false },
  {
    name: 'close: JSON array body -> dict_type',
    method: 'POST',
    path: '/api/fin/day-closures',
    rawBody: '[1,2]',
  },
  {
    name: 'close: JSON string body -> dict_type',
    method: 'POST',
    path: '/api/fin/day-closures',
    rawBody: '"hello"',
  },
  { name: 'close: empty body -> missing', method: 'POST', path: '/api/fin/day-closures' },
  {
    name: 'close: body without a JSON content-type',
    method: 'POST',
    path: '/api/fin/day-closures',
    rawBody: 'close_date=2026-09-03',
    contentType: null,
  },
  // CPython decoder messages and offsets
  { name: 'close: brace only', method: 'POST', path: '/api/fin/day-closures', rawBody: '{' },
  { name: 'close: missing colon', method: 'POST', path: '/api/fin/day-closures', rawBody: '{"a"' },
  { name: 'close: trailing comma', method: 'POST', path: '/api/fin/day-closures', rawBody: '{"a":1,}' },
  { name: 'close: extra data', method: 'POST', path: '/api/fin/day-closures', rawBody: '{"a":1}{' },
  {
    name: 'close: unterminated string',
    method: 'POST',
    path: '/api/fin/day-closures',
    rawBody: '{"a":"x',
  },
  {
    name: 'close: control character',
    method: 'POST',
    path: '/api/fin/day-closures',
    rawBody: '{"a":"\t"}',
  },
  {
    name: 'close: bad escape',
    method: 'POST',
    path: '/api/fin/day-closures',
    rawBody: '{"a":"\\q"}',
  },
  {
    name: 'close: bad unicode escape',
    method: 'POST',
    path: '/api/fin/day-closures',
    rawBody: '{"a":"\\u12"}',
  },
  { name: 'close: single quotes', method: 'POST', path: '/api/fin/day-closures', rawBody: "{'a':1}" },
  { name: 'close: whitespace only', method: 'POST', path: '/api/fin/day-closures', rawBody: '  ' },
  { name: 'close: leading zero', method: 'POST', path: '/api/fin/day-closures', rawBody: '01' },
  {
    name: 'close: NaN is accepted by CPython, so parsing must not fail',
    method: 'POST',
    path: '/api/fin/day-closures',
    rawBody: '{"close_date": "", "x": NaN}',
  },
  // authorization
  {
    name: 'close: non-owner -> 403',
    method: 'POST',
    path: '/api/fin/day-closures',
    body: { close_date: '2026-09-03' },
    token: STAFF_TOKEN,
    inspect: ['fin_day_closures'],
  },
  // handler validation
  { name: 'close: no close_date -> 400', method: 'POST', path: '/api/fin/day-closures', body: {} },
  {
    name: 'close: blank close_date -> 400',
    method: 'POST',
    path: '/api/fin/day-closures',
    body: { close_date: '   ' },
  },
  {
    /**
     * `(body.get("close_date") or "").strip()` raises AttributeError on a
     * truthy non-string. Python does not answer 500: the request HANGS.
     * ApprovalGateMiddleware re-dispatches the request on an unhandled
     * exception, and the re-dispatch awaits a request body whose receive
     * channel is already drained, so it blocks forever and ties up the worker.
     * Reproducing that would be absurd; the port treats a non-string as absent
     * and answers 400, which is what the handler was trying to do.
     */
    name: 'close: non-string close_date (Python hangs; port answers 400)',
    method: 'POST',
    path: '/api/fin/day-closures',
    body: { close_date: 20260903 },
    knownDivergence: 'Python hangs on AttributeError re-dispatch; the port returns 400',
  },
  {
    name: 'close: malformed date -> 400',
    method: 'POST',
    path: '/api/fin/day-closures',
    body: { close_date: '03-09-2026' },
  },
  {
    name: 'close: impossible date -> 400',
    method: 'POST',
    path: '/api/fin/day-closures',
    body: { close_date: '2026-02-30' },
  },
  {
    name: 'close: future date -> 422',
    method: 'POST',
    path: '/api/fin/day-closures',
    body: { close_date: '2099-01-01' },
  },
  // the real writes
  {
    name: 'close: fresh close, whole-number and rounded balances',
    method: 'POST',
    path: '/api/fin/day-closures',
    body: { close_date: '2026-09-03', close_notes: '  end of day  ' },
    inspect: ['fin_day_closures', 'audit_logs'],
  },
  {
    name: 'close: same day again -> 409',
    method: 'POST',
    path: '/api/fin/day-closures',
    body: { close_date: '2026-09-03' },
    inspect: ['fin_day_closures'],
  },
  {
    name: 'close: seeded closed day -> 409',
    method: 'POST',
    path: '/api/fin/day-closures',
    body: { close_date: '2026-09-05' },
    inspect: ['fin_day_closures'],
  },
  {
    name: 'close: re-close a reopened day appends history',
    method: 'POST',
    path: '/api/fin/day-closures',
    body: { close_date: '2026-09-06', close_notes: 'second close' },
    inspect: ['fin_day_closures', 'audit_logs'],
  },
  {
    /**
     * CPython 3.11 date.fromisoformat also accepts the BASIC form and ISO week
     * dates. A `/^\d{4}-\d{2}-\d{2}$/` guard rejects both, which is a 400
     * against Python's 200 — found on 2026-09-21 while porting day-status,
     * and fixed by routing the guard through src/common/py-date.ts.
     * close_date is stored as the RAW string, so these are distinct closures.
     */
    name: 'close: basic-form date 20260903 is accepted by CPython',
    method: 'POST',
    path: '/api/fin/day-closures',
    body: { close_date: '20260903' },
    inspect: ['fin_day_closures'],
  },
  {
    name: 'close: ISO week date 2026-W36-4 is accepted by CPython',
    method: 'POST',
    path: '/api/fin/day-closures',
    body: { close_date: '2026-W36-4' },
    inspect: ['fin_day_closures'],
  },
  {
    name: 'close: impossible week 2026-W99-1 -> 400',
    method: 'POST',
    path: '/api/fin/day-closures',
    body: { close_date: '2026-W99-1' },
  },
  {
    name: 'reopen: basic-form path date',
    method: 'POST',
    path: '/api/fin/day-closures/20260903/reopen',
    body: { reopen_reason: 'basic form' },
    inspect: ['fin_day_closures'],
  },
  {
    name: 'close: an empty ledger day still closes',
    method: 'POST',
    path: '/api/fin/day-closures',
    body: { close_date: '2020-01-01' },
    inspect: ['fin_day_closures'],
  },

  // ── slice 2b: POST /api/fin/day-closures/{close_date}/reopen ──────────
  {
    name: 'reopen: unparseable JSON with a bad token -> 422 before auth',
    method: 'POST',
    path: '/api/fin/day-closures/2026-09-05/reopen',
    rawBody: '{bad',
    token: 'bogus-token',
  },
  {
    name: 'reopen: no auth',
    method: 'POST',
    path: '/api/fin/day-closures/2026-09-05/reopen',
    body: { reopen_reason: 'x' },
    auth: false,
  },
  {
    name: 'reopen: non-owner -> 403',
    method: 'POST',
    path: '/api/fin/day-closures/2026-09-05/reopen',
    body: { reopen_reason: 'x' },
    token: STAFF_TOKEN,
    inspect: ['fin_day_closures'],
  },
  {
    name: 'reopen: owner check precedes the path date -> 403 not 400',
    method: 'POST',
    path: '/api/fin/day-closures/not-a-date/reopen',
    body: { reopen_reason: 'x' },
    token: STAFF_TOKEN,
  },
  {
    name: 'reopen: malformed path date -> 400',
    method: 'POST',
    path: '/api/fin/day-closures/not-a-date/reopen',
    body: { reopen_reason: 'x' },
  },
  {
    name: 'reopen: missing reason -> 400',
    method: 'POST',
    path: '/api/fin/day-closures/2026-09-05/reopen',
    body: {},
  },
  {
    name: 'reopen: blank reason -> 400',
    method: 'POST',
    path: '/api/fin/day-closures/2026-09-05/reopen',
    body: { reopen_reason: '   ' },
  },
  {
    name: 'reopen: reason check precedes the missing-closure 404',
    method: 'POST',
    path: '/api/fin/day-closures/2026-01-01/reopen',
    body: {},
  },
  {
    name: 'reopen: unknown closure -> 404',
    method: 'POST',
    path: '/api/fin/day-closures/2026-01-01/reopen',
    body: { reopen_reason: 'nope' },
  },
  {
    name: 'reopen: seeded closed day',
    method: 'POST',
    path: '/api/fin/day-closures/2026-09-05/reopen',
    body: { reopen_reason: '  bank reconciliation  ' },
    inspect: ['fin_day_closures', 'audit_logs'],
  },
  {
    name: 'reopen: already reopened -> 409',
    method: 'POST',
    path: '/api/fin/day-closures/2026-09-05/reopen',
    body: { reopen_reason: 'again' },
    inspect: ['fin_day_closures'],
  },
  {
    name: 'reopen: re-close then reopen again, history keeps growing',
    method: 'POST',
    path: '/api/fin/day-closures/2026-09-06/reopen',
    body: { reopen_reason: 'third event' },
    inspect: ['fin_day_closures', 'audit_logs'],
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
  killPort(HOOK_PORT);
  const py = startPython();
  const nest = startNest();
  const hook = USE_HOOK ? startPythonHook() : null;
  let pass = 0;
  let fail = 0;
  let diverged = 0;

  try {
    const pyUp = await waitFor(`http://127.0.0.1:${PY_PORT}/api/auth/health`);
    const nestUp = await waitFor(`http://127.0.0.1:${NEST_PORT}/api/vendors`);
    const hookUp = USE_HOOK ? await waitFor(`http://127.0.0.1:${HOOK_PORT}/api/auth/health`) : true;
    if (!pyUp || !nestUp || !hookUp) {
      throw new Error(`servers did not start (py=${pyUp} nest=${nestUp} hook=${hookUp})`);
    }

    for (const c of CASES) {
      const headers: Record<string, string> = {};
      if (c.contentType !== null) headers['content-type'] = c.contentType ?? 'application/json';
      if (c.auth !== false) headers['authorization'] = `Bearer ${c.token ?? TOKEN}`;
      const init: RequestInit = { method: c.method, headers };
      if (c.rawBody !== undefined) init.body = c.rawBody;
      else if (c.body !== undefined) init.body = JSON.stringify(c.body);

      /**
       * A per-request deadline. Without it one non-responding case aborts the
       * whole run — which is exactly what a Python handler fault did on
       * 2026-09-21, hiding every case after it.
       */
      const call = async (port: number): Promise<{ status: number; text: string }> => {
        try {
          const r = await fetch(`http://127.0.0.1:${port}${c.path}`, {
            ...init,
            signal: AbortSignal.timeout(20_000),
          });
          return { status: r.status, text: await r.text() };
        } catch (e) {
          return { status: -1, text: `<no response: ${(e as Error).name}>` };
        }
      };
      const a = await call(PY_PORT);
      const b = await call(NEST_PORT);
      const [ta, tb] = [a.text, b.text];

      const problems: string[] = [];
      if (a.status !== b.status) problems.push(`status ${a.status} vs ${b.status}`);
      else {
        let ja: unknown;
        let jb: unknown;
        try {
          ja = JSON.parse(ta);
          jb = JSON.parse(tb);
        } catch {
          problems.push(`non-JSON body
        py  : ${ta.slice(0, 160)}
        nest: ${tb.slice(0, 160)}`);
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
        const order = ORDER_INSENSITIVE_COLLECTIONS.has(coll)
          ? (v: unknown) => deepSortKeys(normalise(v))
          : (v: unknown) => normalise(v);
        const na = JSON.stringify(order(da));
        const nb = JSON.stringify(order(dbb));
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

      if (problems.length && c.knownDivergence) {
        diverged += 1;
        console.log(
          `  DIVERGES  ${c.name}  (py ${a.status}, nest ${b.status})\n        by design: ${c.knownDivergence}`,
        );
      } else if (problems.length) {
        fail += 1;
        console.log(`  FAIL  ${c.name}\n        ${problems.join('\n        ')}`);
      } else {
        pass += 1;
        console.log(`  PASS  ${c.name}  (${a.status})`);
      }
    }

    /**
     * A RAW BYTE comparison of one close, because everything above is compared
     * as parsed JSON and so cannot see float rendering. Python emits a
     * snapshot balance of exactly 52400 as `52400.0`; a JS number renders as
     * `52400`. That difference is invisible to JSON.parse and visible to every
     * client. Volatile tokens are blanked by pattern so the rest is exact.
     */
    const rawClose = async (port: number): Promise<string> => {
      const r = await fetch(`http://127.0.0.1:${port}/api/fin/day-closures`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', authorization: `Bearer ${TOKEN}` },
        body: JSON.stringify({ close_date: '2026-09-04' }),
      });
      return (await r.text())
        .replace(/fdc_[0-9a-f]{16}/g, '<id>')
        .replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00/g, '<ts>');
    };
    const rawPy = await rawClose(PY_PORT);
    const rawNest = await rawClose(NEST_PORT);
    const bytesOk = rawPy === rawNest;
    console.log(`  ${bytesOk ? 'PASS' : 'FAIL'}  close response is byte-identical (float rendering)`);
    if (!bytesOk) {
      console.log(`        py  : ${rawPy.slice(0, 240)}`);
      console.log(`        nest: ${rawNest.slice(0, 240)}`);
    }
    bytesOk ? (pass += 1) : (fail += 1);

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
    hook?.kill();
    killPort(PY_PORT);
    killPort(NEST_PORT);
    killPort(HOOK_PORT);
    await new Promise((r) => setTimeout(r, 1500));
    await pyDb.dropDatabase();
    await nestDb.dropDatabase();
    await client.close();
    await dropPgDatabase();
  }

  console.log(
    `\ncases ${pass + fail + diverged}   PASS ${pass}   KNOWN DIVERGENCE ${diverged}   FAIL ${fail}`,
  );
  process.exit(fail ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
