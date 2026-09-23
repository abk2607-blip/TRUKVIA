/**
 * Gate 9h · U3 — the fin_accounts seeding safety boundary.
 *
 *   npx tsx scripts/fin-account-seed-safety.ts
 *
 * `ensureSystemAccounts` runs first in every projection. Python re-reads after
 * a failed insert and RE-RAISES when the row still is not there; this port had
 * dropped both, so a refused insert looked like a success: `codeToId` kept the
 * positionally derived id, `persistLegs` found it truthy, and a fin_txn leg was
 * written pointing at an account row that does not exist — silently, with no
 * error and no failure-queue entry.
 *
 * That matters now because Gate 9h would give Node a deliberately narrow role.
 * A refused write must fail the projection, not corrupt the ledger quietly.
 *
 * Five cases, each on its own throwaway database. Nothing is stubbed in the
 * product code: the denial is produced the honest way, by making the real
 * insert fail.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { MongoClient, type Db } from 'mongodb';
import {
  FIN_SYSTEM_ACCOUNTS,
  ensureSystemAccounts,
  reprojectVendorSourceOrThrow,
} from '../src/fin/projection';
import { hookAfterSourceWrite } from '../src/fin/fin-hook';

const MONGO = 'mongodb://127.0.0.1:27017';
const UID = 'user_seedsafety';
const CID = 'co_seedsafety';
const stamp = Date.now();

type Doc = Record<string, unknown>;

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

/** One vendor payment — the simplest projection that resolves AP_VENDOR. */
const PAYMENT: Doc = {
  id: 'vp_seed',
  user_id: UID,
  company_id: CID,
  vendor_id: 'vend_1',
  amount: 1000,
  date: '2026-09-02',
  mode: 'Bank',
  type: 'payment_out',
  ref_no: 'SS-1',
  is_deleted: false,
};

async function seed(db: Db): Promise<void> {
  await db.collection('companies').insertOne({ id: CID, user_id: UID, name: 'Seed Safety Co', is_default: true });
  await db.collection('vendor_payments').insertOne(PAYMENT as never);
}

/** Pre-create every system account, as a fully seeded tenant would have. */
async function preSeedAccounts(db: Db, skip: string[] = []): Promise<void> {
  for (const s of FIN_SYSTEM_ACCOUNTS) {
    if (skip.includes(s.code)) continue;
    await db.collection('fin_accounts').insertOne({
      id: `acc_${s.code.toLowerCase()}_${UID.slice(-6)}_${CID.slice(-6)}`,
      user_id: UID,
      company_id: CID,
      code: s.code,
      name: s.name,
      type: s.type,
      is_system: true,
      is_active: true,
      remarks: 'pre-seeded by the harness',
      created_at: '2026-09-01T00:00:00.000000+00:00',
    } as never);
  }
}

/**
 * Deny creation of ONE account the honest way: a unique index on
 * (user_id, company_id, code) plus a colliding row whose `id` differs from the
 * positional one. The insert then fails with a real MongoDB duplicate-key
 * error, and — crucially — the re-read finds a row, which is the BENIGN path.
 *
 * To produce the NON-benign path the row must be absent after the failure, so
 * a partial unique index is used instead: it rejects the write while leaving
 * the collection empty for that code.
 */
async function denyOneAccount(db: Db, code: string): Promise<void> {
  await db.collection('fin_accounts').createIndex(
    { user_id: 1, company_id: 1, code: 1 },
    {
      name: 'deny_one_code',
      unique: true,
      partialFilterExpression: { code },
    },
  );
  // A sentinel row in a DIFFERENT tenant scope cannot collide, so instead the
  // denial is produced by a validator that refuses this one code outright.
  await db.command({
    collMod: 'fin_accounts',
    validator: { code: { $ne: code } },
    validationAction: 'error',
    validationLevel: 'strict',
  });
}

async function ledger(db: Db): Promise<Doc[]> {
  return db.collection<Doc>('fin_txn').find({}, { projection: { _id: 0 } }).toArray();
}

/**
 * A comparable snapshot of the ledger.
 *
 * Keys are sorted because an upsert-insert builds the document from the filter
 * fields first, and MongoDB does not promise a stable order for them: two
 * identical reprojections can return `user_id` and `ref_source_key` the other
 * way round. Only the ORDER varies, never a value — measured directly — so a
 * raw JSON.stringify compares presentation rather than content. The slice-2c
 * parity harnesses sort keys for exactly this reason.
 */
function snapshot(rows: Doc[]): string {
  const ordered = rows.map((r) => {
    const out: Doc = {};
    for (const k of Object.keys(r).sort()) {
      out[k] = k === 'created_at' || k === 'projected_at' ? '<x>' : r[k];
    }
    return out;
  });
  ordered.sort((a, b) => String(a['ref_source_key']).localeCompare(String(b['ref_source_key'])));
  return JSON.stringify(ordered);
}

async function main(): Promise<void> {
  const client = new MongoClient(MONGO);
  await client.connect();
  const dbs: string[] = [];
  const mk = async (tag: string): Promise<Db> => {
    const name = `trukvia_seedsafety_${tag}_${stamp}`;
    dbs.push(name);
    const db = client.db(name);
    await db.createCollection('fin_accounts');
    await seed(db);
    return db;
  };

  try {
    // ── A. every account already exists → projection succeeds ────────────
    {
      const db = await mk('a');
      await preSeedAccounts(db);
      const before = await db.collection('fin_accounts').countDocuments();
      const r = await reprojectVendorSourceOrThrow(db, UID, CID, 'vendor_payment', 'vp_seed');
      const rows = await ledger(db);
      report(r.written === 2 && rows.length === 2, 'A. existing accounts: projection succeeds (2 legs)', `written ${r.written}, rows ${rows.length}`);
      report(
        (await db.collection('fin_accounts').countDocuments()) === before,
        'A. no account row was created when none was missing',
      );
    }

    // ── B. one account missing, insert permitted → created, succeeds ─────
    {
      const db = await mk('b');
      await preSeedAccounts(db, ['DRIVER_OUTFLOW']);
      const before = await db.collection('fin_accounts').countDocuments();
      const r = await reprojectVendorSourceOrThrow(db, UID, CID, 'vendor_payment', 'vp_seed');
      const after = await db.collection('fin_accounts').countDocuments();
      report(after === before + 1, 'B. missing account is created when the insert is permitted', `${before} -> ${after}`);
      report(r.written === 2 && (await ledger(db)).length === 2, 'B. projection still succeeds');
      const created = await db.collection<Doc>('fin_accounts').findOne({ code: 'DRIVER_OUTFLOW' });
      report(
        created?.['id'] === `acc_driver_outflow_${UID.slice(-6)}_${CID.slice(-6)}`,
        'B. the deterministic positional id is preserved',
        String(created?.['id']),
      );
    }

    // ── C. one account missing, insert DENIED → must fail, no ledger ─────
    {
      const db = await mk('c');
      await preSeedAccounts(db, ['DRIVER_OUTFLOW']);
      await denyOneAccount(db, 'DRIVER_OUTFLOW');

      let threw: unknown = null;
      try {
        await reprojectVendorSourceOrThrow(db, UID, CID, 'vendor_payment', 'vp_seed');
      } catch (e) {
        threw = e;
      }
      report(threw !== null, 'C. a denied account creation THROWS instead of continuing');

      const rows = await ledger(db);
      report(
        rows.length === 0,
        'C. NO fin_txn row was written for the failed projection',
        `${rows.length} rows leaked: ${JSON.stringify(rows.map((r) => r['ref_source_key']))}`,
      );
      report(
        (await db.collection('fin_accounts').countDocuments({ code: 'DRIVER_OUTFLOW' })) === 0,
        'C. the denied account really was not created',
      );
    }

    // ── D. the failure reaches the existing failure-handling path ────────
    {
      const db = await mk('d');
      await preSeedAccounts(db, ['DRIVER_OUTFLOW']);
      await denyOneAccount(db, 'DRIVER_OUTFLOW');

      const res = await hookAfterSourceWrite(db, UID, CID, 'vendor_payment', 'vp_seed');
      report(res.ok === false, 'D. the hook reports ok=false rather than a silent success', JSON.stringify(res.ok));
      report(typeof res.error === 'string' && res.error.length > 0, 'D. an error message is carried back', String(res.error).slice(0, 80));
      report(
        (await db.collection('fin_hook_failures').countDocuments()) === 1,
        'D. exactly one fin_hook_failures row was queued for the retry driver',
      );
      report((await ledger(db)).length === 0, 'D. still no ledger row');
      const q = await db.collection<Doc>('fin_hook_failures').findOne({});
      report(q?.['status'] === 'pending' && q?.['source_id'] === 'vp_seed', 'D. the queued row names the right source');
    }

    // ── E. normal parity is unchanged: same input, same output twice ─────
    {
      const db = await mk('e');
      await preSeedAccounts(db);
      await reprojectVendorSourceOrThrow(db, UID, CID, 'vendor_payment', 'vp_seed');
      const first = snapshot(await ledger(db));
      await reprojectVendorSourceOrThrow(db, UID, CID, 'vendor_payment', 'vp_seed');
      const second = snapshot(await ledger(db));
      report(first === second, 'E. reprojection remains idempotent and byte-identical');

      const m = await ensureSystemAccounts(db, UID, CID);
      report(
        Object.keys(m).length === FIN_SYSTEM_ACCOUNTS.length,
        'E. ensureSystemAccounts still returns every code',
        `${Object.keys(m).length} of ${FIN_SYSTEM_ACCOUNTS.length}`,
      );
      report(
        (await ledger(db)).every((r) => String(r['account_id']).startsWith('acc_')),
        'E. every ledger row still resolves to a real account id',
      );
    }
  } finally {
    for (const n of dbs) await client.db(n).dropDatabase();
    await client.close();
  }

  console.log(`\nchecks ${pass + fail}   PASS ${pass}   FAIL ${fail}`);
  process.exit(fail ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
