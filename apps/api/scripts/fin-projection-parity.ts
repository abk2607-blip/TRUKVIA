/**
 * Ledger parity: Python's reproject_source vs the TypeScript vendor port.
 *
 * Both run over the SAME real vendor documents, each into its own throwaway
 * MongoDB database, and every resulting fin_txn row is compared field by field.
 *
 *   npx tsx scripts/fin-projection-parity.ts [--limit 400]
 *
 * Source data is copied from the local restore of production, so the matrix
 * includes the awkward rows: reversed payments, soft-deleted payments, bills
 * with and without a paired expense, and every payment `mode`.
 *
 * Exit code 1 on any mismatch.
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { MongoClient, type Db } from 'mongodb';
import { hookAfterSourceWrite } from '../src/fin/fin-hook';

const MONGO = 'mongodb://127.0.0.1:27017';
const SRC_DB = process.env.NEST_MONGO_DB ?? 'trukvia_local_20260921';
const PY = 'D:/trk-venv/Scripts/python.exe';
const REPO = 'D:/Projects/TRUKVIA-clone';
const stamp = Date.now();
const PY_DB = `trukvia_finparity_py_${stamp}`;
const TS_DB = `trukvia_finparity_ts_${stamp}`;

const args = process.argv.slice(2);
const limitIdx = args.indexOf('--limit');
const LIMIT = limitIdx >= 0 ? Number(args[limitIdx + 1]) : 400;

/** Written by the projection at persist time; not part of the contract. */
const VOLATILE = new Set(['created_at', 'projected_at', '_id']);

function normalise(row: Record<string, unknown>): string {
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(row).sort()) {
    if (VOLATILE.has(k)) continue;
    out[k] = row[k];
  }
  return JSON.stringify(out);
}

async function copyFixtures(src: Db, dst: Db): Promise<{ payments: string[]; bills: string[] }> {
  const payments = await src.collection('vendor_payments').find({}).limit(LIMIT).toArray();
  const bills = await src.collection('vendor_bills').find({}).limit(LIMIT).toArray();
  const vendorIds = new Set(
    [...payments, ...bills].map((d) => String((d as Record<string, unknown>)['vendor_id'])),
  );
  const vendors = await src
    .collection('vendors')
    .find({ id: { $in: [...vendorIds] } })
    .toArray();
  // expenses decide the paired/orphan branch for bills
  const billIds = bills.map((b) => String((b as Record<string, unknown>)['id']));
  const expenses = await src
    .collection('expenses')
    .find({ vendor_bill_id: { $in: billIds } })
    .toArray();

  if (payments.length) await dst.collection('vendor_payments').insertMany(payments);
  if (bills.length) await dst.collection('vendor_bills').insertMany(bills);
  if (vendors.length) await dst.collection('vendors').insertMany(vendors);
  if (expenses.length) await dst.collection('expenses').insertMany(expenses);

  return {
    payments: payments.map((p) => String((p as Record<string, unknown>)['id'])),
    bills: billIds,
  };
}

const PY_DRIVER = `
import asyncio, json, os, sys
sys.path.insert(0, r"${REPO}/backend")
os.environ["MONGO_URL"] = "${MONGO}"
os.environ["DB_NAME"] = "${PY_DB}"
os.environ.setdefault("EMERGENT_LLM_KEY", "")
from services_fin_txn import reproject_source

async def main():
    # The work list is passed as a FILE: a JSON argv payload blows past the
    # Windows command-line limit at a few hundred sources.
    spec = json.loads(open(sys.argv[1], encoding="utf-8").read())
    for source_type in ("vendor_payment", "vendor_bill"):
        for sid, uid, cid in spec[source_type]:
            await reproject_source(uid, cid, source_type, sid)
    print("python projection done")

asyncio.run(main())
`;

async function main(): Promise<void> {
  const client = new MongoClient(MONGO);
  await client.connect();
  const src = client.db(SRC_DB);
  const pyDb = client.db(PY_DB);
  const tsDb = client.db(TS_DB);

  try {
    const ids = await copyFixtures(src, pyDb);
    await copyFixtures(src, tsDb);

    // (id, user_id, company_id) triples, since the projection is tenant-scoped
    const triples = async (db: Db, coll: string, list: string[]) => {
      const rows = await db
        .collection(coll)
        .find({ id: { $in: list } }, { projection: { _id: 0, id: 1, user_id: 1, company_id: 1 } })
        .toArray();
      return rows.map((r) => [String(r['id']), String(r['user_id']), String(r['company_id'])]);
    };
    const spec = {
      vendor_payment: await triples(pyDb, 'vendor_payments', ids.payments),
      vendor_bill: await triples(pyDb, 'vendor_bills', ids.bills),
    };

    console.log(
      `projecting ${spec.vendor_payment.length} payments and ${spec.vendor_bill.length} bills through both stacks`,
    );

    const specPath = join(mkdtempSync(join(tmpdir(), 'finparity-')), 'spec.json');
    writeFileSync(specPath, JSON.stringify(spec), 'utf8');
    execFileSync(PY, ['-c', PY_DRIVER, specPath], {
      encoding: 'utf8',
      env: { ...process.env, PYTHONUTF8: '1' },
    });

    for (const [sid, uid, cid] of spec.vendor_payment) {
      const r = await hookAfterSourceWrite(tsDb, uid!, cid!, 'vendor_payment', sid!);
      if (!r.ok) throw new Error(`ts projection failed for ${sid}: ${r.error}`);
    }
    for (const [sid, uid, cid] of spec.vendor_bill) {
      const r = await hookAfterSourceWrite(tsDb, uid!, cid!, 'vendor_bill', sid!);
      if (!r.ok) throw new Error(`ts projection failed for ${sid}: ${r.error}`);
    }

    const [pyRows, tsRows] = await Promise.all([
      pyDb.collection('fin_txn').find({}).sort({ ref_source_key: 1 }).toArray(),
      tsDb.collection('fin_txn').find({}).sort({ ref_source_key: 1 }).toArray(),
    ]);
    const [pyAcc, tsAcc] = await Promise.all([
      pyDb.collection('fin_accounts').find({}).sort({ code: 1 }).toArray(),
      tsDb.collection('fin_accounts').find({}).sort({ code: 1 }).toArray(),
    ]);

    console.log(`fin_txn rows: python ${pyRows.length}, typescript ${tsRows.length}`);
    console.log(`fin_accounts: python ${pyAcc.length}, typescript ${tsAcc.length}`);

    let mismatches = 0;
    const byKey = new Map(tsRows.map((r) => [String(r['ref_source_key']), r]));
    for (const p of pyRows) {
      const key = String(p['ref_source_key']);
      const t = byKey.get(key);
      if (!t) {
        mismatches += 1;
        if (mismatches <= 5) console.log(`  MISSING in typescript: ${key}`);
        continue;
      }
      const a = normalise(p as Record<string, unknown>);
      const b = normalise(t as Record<string, unknown>);
      if (a !== b) {
        mismatches += 1;
        if (mismatches <= 5) {
          let at = 0;
          while (at < Math.min(a.length, b.length) && a[at] === b[at]) at += 1;
          console.log(`  DIFFERS ${key} at char ${at}`);
          console.log(`    python    : …${a.slice(Math.max(0, at - 60), at + 90)}`);
          console.log(`    typescript: …${b.slice(Math.max(0, at - 60), at + 90)}`);
        }
      }
      byKey.delete(key);
    }
    for (const key of byKey.keys()) {
      mismatches += 1;
      if (mismatches <= 10) console.log(`  EXTRA in typescript: ${key}`);
    }

    // account catalogue must match on the fields the projection relies on
    let accMismatch = 0;
    for (let i = 0; i < Math.max(pyAcc.length, tsAcc.length); i += 1) {
      const a = pyAcc[i];
      const b = tsAcc[i];
      if (!a || !b || a['id'] !== b['id'] || a['code'] !== b['code'] || a['type'] !== b['type']) {
        accMismatch += 1;
        if (accMismatch <= 3) console.log(`  ACCOUNT differs: ${String(a?.['code'])} vs ${String(b?.['code'])}`);
      }
    }

    const total = pyRows.length;
    console.log(
      `\nledger rows compared ${total}   mismatches ${mismatches}   account mismatches ${accMismatch}`,
    );
    process.exit(mismatches || accMismatch ? 1 : 0);
  } finally {
    await pyDb.dropDatabase();
    await tsDb.dropDatabase();
    await client.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
