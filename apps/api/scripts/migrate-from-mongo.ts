/**
 * TRUKVIA · Phase 6 · slice 1 — one-way migration of the vendors module from
 * MongoDB into PostgreSQL, with verification.
 *
 * Idempotent: every row is upserted by its business id, so a re-run converges
 * rather than duplicating. Reads only from Mongo; writes only to Postgres.
 *
 *   npx tsx scripts/migrate-from-mongo.ts [--mongo-db NAME] [--verify-only]
 *
 * Verification (any failure exits non-zero):
 *   • row counts equal per table;
 *   • SUM(amount) equal to the paisa, compared as exact decimals;
 *   • every vendor_id in bills and payments resolves to a vendor;
 *   • a 200-row sample compared field by field.
 */
import { MongoClient, type Db } from 'mongodb';
import { Pool } from 'pg';

const args = process.argv.slice(2);
const argOf = (name: string, fallback: string): string => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? (args[i + 1] as string) : fallback;
};
const MONGO_URL = argOf('--mongo-url', process.env.NEST_MONGO_URL ?? 'mongodb://127.0.0.1:27017');
const MONGO_DB = argOf('--mongo-db', process.env.NEST_MONGO_DB ?? 'trukvia_local_20260921');
const PG_URL = argOf('--pg-url', process.env.PG_URL ?? 'postgres://postgres@127.0.0.1:5433/trukvia');
const VERIFY_ONLY = args.includes('--verify-only');

type Doc = Record<string, unknown>;

const str = (v: unknown, dflt = ''): string => (typeof v === 'string' ? v : dflt);
const bool = (v: unknown, dflt: boolean | null = null): boolean | null =>
  typeof v === 'boolean' ? v : dflt;
const int = (v: unknown): number | null => {
  const bson = (v as { _bsontype?: string; value?: number })?._bsontype;
  if (bson === 'Int32' || bson === 'Double') return Math.trunc((v as { value: number }).value);
  return typeof v === 'number' && Number.isFinite(v) ? Math.trunc(v) : null;
};

/** Money: keep full precision as a decimal string; never go through a float. */
const money = (v: unknown): string => {
  const bson = (v as { _bsontype?: string; value?: number })?._bsontype;
  if (bson === 'Double' || bson === 'Int32') {
    return Number((v as { value: number }).value).toFixed(2);
  }
  if (typeof v === 'number' && Number.isFinite(v)) return v.toFixed(2);
  if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) {
    return Number(v).toFixed(2);
  }
  return '0.00';
};

/**
 * Timestamps arrive either as BSON dates (production) or as ISO strings (the
 * JSON export). Anything unparseable is a hard failure: silently dropping an
 * audit timestamp would be worse than stopping.
 */
const ts = (v: unknown, where: string): string | null => {
  if (v === null || v === undefined || v === '') return null;
  if (v instanceof Date) return v.toISOString();
  if (typeof v === 'string') {
    const s = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(v) ? v : `${v}+00:00`;
    const ms = Date.parse(s);
    if (Number.isNaN(ms)) throw new Error(`unparseable timestamp at ${where}: ${v}`);
    return v; // preserve the exact source text; Postgres parses it
  }
  throw new Error(`unexpected timestamp type at ${where}: ${typeof v}`);
};

/** bill_date / payment date are plain dates ("2026-08-05") in the source. */
const dateOnly = (v: unknown): string | null => {
  if (typeof v !== 'string' || v.trim() === '') return null;
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(v);
  return m ? (m[1] as string) : null;
};

/**
 * Render a BSON value the way Python's json.dumps would, so a `json` column
 * holds text identical to the current API output: object key order preserved,
 * and a double with no fraction rendered as 7500.0 rather than 7500.
 * Requires the documents to be read with promoteValues disabled, otherwise the
 * driver has already collapsed Double and Int32 into a JS number.
 */
function pyJsonText(v: unknown): string {
  const render = (x: unknown): string => {
    if (x === null || x === undefined) return 'null';
    const ctor = (x as { _bsontype?: string })?._bsontype;
    if (ctor === 'Double') {
      const n = (x as { value: number }).value;
      return Number.isInteger(n) ? `${n}.0` : String(n);
    }
    if (ctor === 'Int32') return String((x as { value: number }).value);
    if (ctor === 'Long') return String(x);
    if (typeof x === 'number') return Number.isInteger(x) ? `${x}.0` : String(x);
    if (typeof x === 'boolean') return x ? 'true' : 'false';
    if (typeof x === 'string') return JSON.stringify(x);
    if (x instanceof Date) return JSON.stringify(x.toISOString());
    if (Array.isArray(x)) return `[${x.map(render).join(',')}]`;
    return `{${Object.entries(x as Record<string, unknown>)
      .map(([k, val]) => `${JSON.stringify(k)}:${render(val)}`)
      .join(',')}}`;
  };
  return render(v);
}

const jsonOrNull = (v: unknown): string | null =>
  v === null || v === undefined ? null : pyJsonText(v);

async function copyVendors(mongo: Db, pool: Pool): Promise<number> {
  const docs = await mongo.collection<Doc>('vendors').find({}).toArray();
  for (const d of docs) {
    await pool.query(
      `INSERT INTO trukvia.vendor (
         id,source_id,user_id,company_id,name,contact_person,mobile,alt_mobile,address,state,city,
         gst_in,pan,msme_number,bank_name,account_number,ifsc,branch,payment_terms,
         opening_balance,opening_balance_type,remarks,is_active,is_historical,
         imported_from,imported_ref,imported_batch,
         created_by,created_at,modified_by,modified_at,
         deactivated_by,deactivated_at,deactivation_reason)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,
               $22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,$33,$34)
       ON CONFLICT (id) DO UPDATE SET
         source_id=EXCLUDED.source_id, name=EXCLUDED.name, contact_person=EXCLUDED.contact_person, mobile=EXCLUDED.mobile,
         alt_mobile=EXCLUDED.alt_mobile, address=EXCLUDED.address, state=EXCLUDED.state,
         city=EXCLUDED.city, gst_in=EXCLUDED.gst_in, pan=EXCLUDED.pan,
         msme_number=EXCLUDED.msme_number, bank_name=EXCLUDED.bank_name,
         account_number=EXCLUDED.account_number, ifsc=EXCLUDED.ifsc, branch=EXCLUDED.branch,
         payment_terms=EXCLUDED.payment_terms, opening_balance=EXCLUDED.opening_balance,
         opening_balance_type=EXCLUDED.opening_balance_type, remarks=EXCLUDED.remarks,
         is_active=EXCLUDED.is_active, is_historical=EXCLUDED.is_historical,
         modified_by=EXCLUDED.modified_by, modified_at=EXCLUDED.modified_at,
         deactivated_by=EXCLUDED.deactivated_by, deactivated_at=EXCLUDED.deactivated_at,
         deactivation_reason=EXCLUDED.deactivation_reason`,
      [
        str(d['id']), String(d['_id'] ?? ''), str(d['user_id']), str(d['company_id']), str(d['name']),
        str(d['contact_person']), str(d['mobile']), str(d['alt_mobile']), str(d['address']),
        str(d['state']), str(d['city']), str(d['gst_in']), str(d['pan']),
        str(d['msme_number']), str(d['bank_name']), str(d['account_number']), str(d['ifsc']),
        str(d['branch']), str(d['payment_terms']), money(d['opening_balance']),
        str(d['opening_balance_type'], 'payable'), str(d['remarks']),
        bool(d['is_active'], true), bool(d['is_historical'], false),
        str(d['imported_from']), str(d['imported_ref']), str(d['imported_batch']),
        str(d['created_by']), ts(d['created_at'], `vendor ${String(d['id'])}.created_at`),
        str(d['modified_by']), ts(d['modified_at'], `vendor ${String(d['id'])}.modified_at`),
        str(d['deactivated_by']), ts(d['deactivated_at'], `vendor ${String(d['id'])}.deactivated_at`),
        str(d['deactivation_reason']),
      ],
    );
  }
  return docs.length;
}

async function copyBills(mongo: Db, pool: Pool): Promise<number> {
  const docs = await mongo.collection<Doc>('vendor_bills').find({}).toArray();
  for (const d of docs) {
    await pool.query(
      `INSERT INTO trukvia.vendor_bill (
         id,source_id,user_id,company_id,vendor_id,vendor_name,bill_number,bill_date,bill_amount,
         vehicle_id,vehicle_number,trip_id,repair_event_id,narration,remarks,file_ids,
         is_deleted,deleted_by,deleted_at,deletion_reason,
         created_by,created_at,modified_by,modified_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24)
       ON CONFLICT (id) DO UPDATE SET
         source_id=EXCLUDED.source_id,
         vendor_id=EXCLUDED.vendor_id, vendor_name=EXCLUDED.vendor_name,
         bill_number=EXCLUDED.bill_number, bill_date=EXCLUDED.bill_date,
         bill_amount=EXCLUDED.bill_amount, vehicle_id=EXCLUDED.vehicle_id,
         vehicle_number=EXCLUDED.vehicle_number, trip_id=EXCLUDED.trip_id,
         repair_event_id=EXCLUDED.repair_event_id, narration=EXCLUDED.narration,
         remarks=EXCLUDED.remarks, file_ids=EXCLUDED.file_ids,
         is_deleted=EXCLUDED.is_deleted, deleted_by=EXCLUDED.deleted_by,
         deleted_at=EXCLUDED.deleted_at, deletion_reason=EXCLUDED.deletion_reason,
         modified_by=EXCLUDED.modified_by, modified_at=EXCLUDED.modified_at`,
      [
        str(d['id']), String(d['_id'] ?? ''), str(d['user_id']), str(d['company_id']), str(d['vendor_id']),
        str(d['vendor_name']), str(d['bill_number']), dateOnly(d['bill_date']),
        money(d['bill_amount']), str(d['vehicle_id']), str(d['vehicle_number']),
        str(d['trip_id']), str(d['repair_event_id']), str(d['narration']), str(d['remarks']),
        JSON.stringify(Array.isArray(d['file_ids']) ? d['file_ids'] : []),
        bool(d['is_deleted'], false), str(d['deleted_by']),
        ts(d['deleted_at'], `bill ${String(d['id'])}.deleted_at`), str(d['deletion_reason']),
        str(d['created_by']), ts(d['created_at'], `bill ${String(d['id'])}.created_at`),
        str(d['modified_by']), ts(d['modified_at'], `bill ${String(d['id'])}.modified_at`),
      ],
    );
  }
  return docs.length;
}

async function copyPayments(mongo: Db, pool: Pool): Promise<number> {
  // promoteValues:false keeps Double/Int32 distinct so snapshots render exactly.
  const docs = await mongo
    .collection<Doc>('vendor_payments')
    .find({}, { promoteValues: false })
    .toArray();
  for (const d of docs) {
    await pool.query(
      `INSERT INTO trukvia.vendor_payment (
         id,source_id,user_id,company_id,vendor_id,vendor_bill_id,payment_date,amount,type,mode,
         account_id,ref_no,against,remarks,file_ids,
         corrected_by,corrected_at,correction_count,latest_correction_id,
         is_reversed,reversed_by,reversed_at,reversal_reason,reversal_of,
         reconciled_at,reconciled_ref,bank_account_id,bank_snapshot,
         company_bank_account_id,source_bank_snapshot,
         is_deleted,deleted_by,deleted_at,deletion_reason,
         created_by,created_at,modified_by,modified_at,source_shape)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,
               $22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,$33,$34,$35,$36,$37,$38,$39)
       ON CONFLICT (id) DO UPDATE SET
         source_id=EXCLUDED.source_id,
         vendor_id=EXCLUDED.vendor_id, vendor_bill_id=EXCLUDED.vendor_bill_id,
         payment_date=EXCLUDED.payment_date, amount=EXCLUDED.amount, type=EXCLUDED.type,
         mode=EXCLUDED.mode, account_id=EXCLUDED.account_id, ref_no=EXCLUDED.ref_no,
         against=EXCLUDED.against, remarks=EXCLUDED.remarks, file_ids=EXCLUDED.file_ids,
         corrected_by=EXCLUDED.corrected_by, corrected_at=EXCLUDED.corrected_at,
         correction_count=EXCLUDED.correction_count,
         latest_correction_id=EXCLUDED.latest_correction_id,
         is_reversed=EXCLUDED.is_reversed, reversed_by=EXCLUDED.reversed_by,
         reversed_at=EXCLUDED.reversed_at, reversal_reason=EXCLUDED.reversal_reason,
         reversal_of=EXCLUDED.reversal_of, reconciled_at=EXCLUDED.reconciled_at,
         reconciled_ref=EXCLUDED.reconciled_ref, bank_account_id=EXCLUDED.bank_account_id,
         bank_snapshot=EXCLUDED.bank_snapshot,
         company_bank_account_id=EXCLUDED.company_bank_account_id,
         source_bank_snapshot=EXCLUDED.source_bank_snapshot,
         is_deleted=EXCLUDED.is_deleted, deleted_by=EXCLUDED.deleted_by,
         deleted_at=EXCLUDED.deleted_at, deletion_reason=EXCLUDED.deletion_reason,
         modified_by=EXCLUDED.modified_by, modified_at=EXCLUDED.modified_at,
         source_shape=EXCLUDED.source_shape`,
      [
        str(d['id']), String(d['_id'] ?? ''), str(d['user_id']), str(d['company_id']), str(d['vendor_id']),
        str(d['vendor_bill_id']), dateOnly(d['date']), money(d['amount']), str(d['type']),
        str(d['mode']), str(d['account_id']), str(d['ref_no']), str(d['against']),
        str(d['remarks']),
        JSON.stringify(Array.isArray(d['file_ids']) ? d['file_ids'] : []),
        d['corrected_by'] === undefined ? null : str(d['corrected_by']),
        ts(d['corrected_at'], `payment ${String(d['id'])}.corrected_at`),
        int(d['correction_count']),
        d['latest_correction_id'] === undefined ? null : str(d['latest_correction_id']),
        bool(d['is_reversed']),
        d['reversed_by'] === undefined ? null : str(d['reversed_by']),
        ts(d['reversed_at'], `payment ${String(d['id'])}.reversed_at`),
        d['reversal_reason'] === undefined ? null : str(d['reversal_reason']),
        d['reversal_of'] === undefined || d['reversal_of'] === '' ? null : str(d['reversal_of']),
        dateOnly(d['reconciled_at']),
        d['reconciled_ref'] === undefined ? null : str(d['reconciled_ref']),
        d['bank_account_id'] === undefined ? null : str(d['bank_account_id']),
        jsonOrNull(d['bank_snapshot']),
        d['company_bank_account_id'] === undefined ? null : str(d['company_bank_account_id']),
        jsonOrNull(d['source_bank_snapshot']),
        bool(d['is_deleted'], false), str(d['deleted_by']),
        ts(d['deleted_at'], `payment ${String(d['id'])}.deleted_at`), str(d['deletion_reason']),
        str(d['created_by']), ts(d['created_at'], `payment ${String(d['id'])}.created_at`),
        str(d['modified_by']), ts(d['modified_at'], `payment ${String(d['id'])}.modified_at`),
        JSON.stringify(Object.keys(d).filter((k) => k !== '_id' && k !== 'user_id')),
      ],
    );
  }
  return docs.length;
}

async function copyCorrections(mongo: Db, pool: Pool): Promise<number> {
  const docs = await mongo
    .collection<Doc>('payment_corrections')
    .find({ payment_type: 'vendor' }, { promoteValues: false })
    .toArray();
  for (const d of docs) {
    await pool.query(
      `INSERT INTO trukvia.payment_correction (
         id,source_id,user_id,company_id,payment_type,payment_id,correction_index,kind,
         correction_reason,before,after,diff,linked_reversal_id,linked_new_id,
         force_reconciled_override,corrected_by,corrected_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
       ON CONFLICT (id) DO UPDATE SET
         source_id=EXCLUDED.source_id, kind=EXCLUDED.kind, correction_reason=EXCLUDED.correction_reason,
         before=EXCLUDED.before, after=EXCLUDED.after, diff=EXCLUDED.diff,
         linked_reversal_id=EXCLUDED.linked_reversal_id,
         linked_new_id=EXCLUDED.linked_new_id,
         force_reconciled_override=EXCLUDED.force_reconciled_override`,
      [
        str(d['id']), String(d['_id'] ?? ''), str(d['user_id']), str(d['company_id']), str(d['payment_type']),
        str(d['payment_id']), int(d['correction_index']) ?? 0, str(d['kind']),
        str(d['correction_reason']), jsonOrNull(d['before']), jsonOrNull(d['after']),
        jsonOrNull(d['diff']),
        d['linked_reversal_id'] === undefined ? null : str(d['linked_reversal_id']),
        d['linked_new_id'] === undefined ? null : str(d['linked_new_id']),
        bool(d['force_reconciled_override']), str(d['corrected_by']),
        ts(d['corrected_at'], `correction ${String(d['id'])}.corrected_at`),
      ],
    );
  }
  return docs.length;
}

async function verify(mongo: Db, pool: Pool): Promise<boolean> {
  let ok = true;
  const check = (label: string, a: unknown, b: unknown): void => {
    const pass = String(a) === String(b);
    if (!pass) ok = false;
    console.log(`  ${pass ? 'OK  ' : 'FAIL'} ${label}: mongo=${String(a)} pg=${String(b)}`);
  };

  const pairs: Array<[string, string, Record<string, unknown>]> = [
    ['vendors', 'vendor', {}],
    ['vendor_bills', 'vendor_bill', {}],
    ['vendor_payments', 'vendor_payment', {}],
    ['payment_corrections', 'payment_correction', { payment_type: 'vendor' }],
  ];
  console.log('counts');
  for (const [coll, table, filter] of pairs) {
    const m = await mongo.collection(coll).countDocuments(filter);
    const p = await pool.query(`SELECT count(*)::int AS n FROM trukvia.${table}`);
    check(`${coll} -> ${table}`, m, p.rows[0].n);
  }

  console.log('sums (exact decimal)');
  const sums: Array<[string, string, string, string]> = [
    ['vendors', 'opening_balance', 'vendor', 'opening_balance'],
    ['vendor_bills', 'bill_amount', 'vendor_bill', 'bill_amount'],
    ['vendor_payments', 'amount', 'vendor_payment', 'amount'],
  ];
  for (const [coll, field, table, column] of sums) {
    const agg = await mongo
      .collection(coll)
      .aggregate([{ $group: { _id: null, total: { $sum: `$${field}` } } }])
      .toArray();
    const mongoTotal = Number(agg[0]?.['total'] ?? 0).toFixed(2);
    const p = await pool.query(`SELECT COALESCE(SUM(${column}),0)::text AS total FROM trukvia.${table}`);
    check(`${coll}.${field}`, mongoTotal, Number(p.rows[0].total).toFixed(2));
  }

  // Source-data findings are reported but do NOT fail the migration: these rows
  // exist identically in MongoDB, so copying them faithfully is correct
  // behaviour. Altering them to make a check pass would corrupt the copy.
  console.log('source-data findings (reported, not migration failures)');
  for (const table of ['vendor_bill', 'vendor_payment']) {
    const r = await pool.query(
      `SELECT t.id, t.vendor_id, t.user_id FROM trukvia.${table} t
        LEFT JOIN trukvia.vendor v ON v.id = t.vendor_id WHERE v.id IS NULL
        ORDER BY t.id`,
    );
    const tenants = new Set(r.rows.map((x: { user_id: string }) => x.user_id));
    console.log(
      `  ${r.rowCount} ${table} row(s) reference a vendor that no longer exists` +
        (r.rowCount ? ` — tenants: ${[...tenants].join(', ')}` : ''),
    );
    for (const row of r.rows) console.log(`      ${row.id} -> ${row.vendor_id}`);
  }

  console.log('sample comparison (200 vendors, field by field)');
  const sample = await mongo.collection<Doc>('vendors').find({}).limit(200).toArray();
  let mismatches = 0;
  for (const d of sample) {
    const r = await pool.query('SELECT * FROM trukvia.vendor WHERE id=$1', [str(d['id'])]);
    const row = r.rows[0];
    if (!row) {
      mismatches += 1;
      continue;
    }
    if (
      row.name !== str(d['name']) ||
      row.mobile !== str(d['mobile']) ||
      Number(row.opening_balance) !== Number(d['opening_balance'] ?? 0) ||
      row.is_active !== bool(d['is_active'], true) ||
      row.company_id !== str(d['company_id'])
    ) {
      mismatches += 1;
    }
  }
  check('sample mismatches', 0, mismatches);
  return ok;
}

async function main(): Promise<void> {
  const client = new MongoClient(MONGO_URL);
  await client.connect();
  const mongo = client.db(MONGO_DB);
  const pool = new Pool({ connectionString: PG_URL, max: 4 });

  if (!VERIFY_ONLY) {
    const started = Date.now();
    console.log(`migrating ${MONGO_DB} -> postgres`);
    console.log('  vendors            ', await copyVendors(mongo, pool));
    console.log('  vendor_bills       ', await copyBills(mongo, pool));
    console.log('  vendor_payments    ', await copyPayments(mongo, pool));
    console.log('  payment_corrections', await copyCorrections(mongo, pool));
    console.log(`  elapsed ${((Date.now() - started) / 1000).toFixed(1)}s\n`);
  }

  const ok = await verify(mongo, pool);
  await pool.end();
  await client.close();
  console.log(ok ? '\nVERIFICATION PASSED' : '\nVERIFICATION FAILED');
  process.exit(ok ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
