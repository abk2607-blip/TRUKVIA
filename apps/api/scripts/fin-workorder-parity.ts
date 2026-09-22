/**
 * Focused parity for slice 2c unit 7 — the `mechanic_work_order` projection.
 *
 *   npx tsx scripts/fin-workorder-parity.ts
 *
 * This is the first projection that consults ANOTHER collection: it posts legs
 * only when no paired expense exists. So the fixtures come in pairs — a work
 * order, and the expense (or lack of one) that decides its fate.
 *
 * `preProject` runs the expenses through a projection FIRST, with a different
 * owner on each database: Python on PY, the NestJS port on TS, and Python
 * locally on BRIDGE (only mechanic_work_order is in the delegation list there).
 * That is what turns "pairing reads the source collection, so ownership cannot
 * matter" from an argument into a measurement.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { runProjectionParity, type Doc } from './lib/projection-parity';

const UID = 'user_woparity';
const CID = 'co_woparity';
/** A second tenant, to prove one scope cannot pair or project across. */
const UID2 = 'user_woparity_other';
const CID2 = 'co_woparity_other';

const wo = (over: Doc): Doc => ({
  user_id: UID,
  company_id: CID,
  amount: 500,
  work_date: '2026-09-02',
  mechanic_id: 'mech_1',
  mechanic_name: 'Ravi',
  vehicle_id: 'veh_1',
  trip_id: 'trip_1',
  is_deleted: false,
  ...over,
});

/** A paired expense. `over` sets the flags whose Mongo semantics are at stake. */
const exp = (id: string, woId: string, over: Doc = {}): Doc => ({
  id,
  user_id: UID,
  company_id: CID,
  mechanic_work_order_id: woId,
  amount: 500,
  date: '2026-09-02',
  category: 'repair',
  narration: 'Paired repair',
  ...over,
});

const documents: Doc[] = [
  // ── the pairing matrix ───────────────────────────────────────────────
  wo({ id: 'wo_unpaired' }), // no expense at all -> legs
  wo({ id: 'wo_paired_normal' }), // a live expense -> suppressed
  wo({ id: 'wo_paired_deleted' }), // expense is_deleted: true -> NOT paired
  wo({ id: 'wo_paired_deleted_int' }), // expense is_deleted: 1 -> STILL paired
  wo({ id: 'wo_paired_reversed' }), // expense is_reversed: true -> NOT paired
  wo({ id: 'wo_paired_reversed_str' }), // expense is_reversed: "false" -> paired
  wo({ id: 'wo_paired_historical' }), // paired, though the expense projects nothing
  wo({ id: 'wo_paired_zero_amount' }), // paired, though the expense projects nothing
  wo({ id: 'wo_paired_multiple' }), // two matching expenses -> paired
  wo({ id: 'wo_paired_other_tenant' }), // the expense belongs to tenant 2 -> unpaired here

  // ── guards on the work order itself ──────────────────────────────────
  wo({ id: 'wo_deleted', is_deleted: true }),
  wo({ id: 'wo_deleted_falsy', is_deleted: 0 }),
  // There is NO is_reversed and NO is_historical guard here, unlike every
  // other projection ported so far — both of these must still produce legs.
  wo({ id: 'wo_reversed', is_reversed: true }),
  wo({ id: 'wo_historical', is_historical: true }),
  wo({ id: 'wo_zero', amount: 0 }),
  wo({ id: 'wo_negative', amount: -50 }),
  wo({ id: 'wo_null_amount', amount: null }),
  wo({ id: 'wo_missing_amount', amount: undefined }),
  wo({ id: 'wo_tiny', amount: 0.004 }),

  // ── money ────────────────────────────────────────────────────────────
  wo({ id: 'wo_round_half_even', amount: 2.675 }),
  wo({ id: 'wo_round_tie', amount: 0.125 }),
  wo({ id: 'wo_round_tie_up', amount: 0.375 }),
  wo({ id: 'wo_round_below', amount: 1.005 }),
  wo({ id: 'wo_paise', amount: 1234.56 }),
  wo({ id: 'wo_string_amount', amount: '750.25' }),
  wo({ id: 'wo_big', amount: 98765432.1 }),

  // ── fields ───────────────────────────────────────────────────────────
  wo({ id: 'wo_missing_date', work_date: undefined }),
  wo({ id: 'wo_blank_date', work_date: '' }),
  // `date` must be ignored — the field is work_date.
  wo({ id: 'wo_wrong_date_field', date: '2020-01-01', work_date: '2026-09-02' }),
  wo({ id: 'wo_no_mechanic', mechanic_id: '', mechanic_name: '' }),
  wo({ id: 'wo_missing_mechanic', mechanic_id: undefined, mechanic_name: undefined }),
  wo({ id: 'wo_no_vehicle_trip', vehicle_id: '', trip_id: '' }),
  wo({ id: 'wo_unicode_mechanic', mechanic_name: 'रवि · 数' }),
  // the narration is f"WO {id} (orphan)" and caps at 400
  wo({ id: `wo_long_${'X'.repeat(420)}` }),

  // ── a second tenant holding the SAME id ──────────────────────────────
  wo({ id: 'wo_unpaired', user_id: UID2, company_id: CID2, amount: 4242, mechanic_name: 'OTHER' }),
];

const expenses: Doc[] = [
  exp('exp_p_normal', 'wo_paired_normal'),
  exp('exp_p_deleted', 'wo_paired_deleted', { is_deleted: true }),
  // `$ne: true` excludes ONLY BSON true — an int 1 still counts as paired.
  exp('exp_p_deleted_int', 'wo_paired_deleted_int', { is_deleted: 1 }),
  exp('exp_p_reversed', 'wo_paired_reversed', { is_reversed: true }),
  exp('exp_p_reversed_str', 'wo_paired_reversed_str', { is_reversed: 'false' }),
  // The probe checks neither is_historical nor the amount, so these suppress
  // the work order even though they project nothing themselves.
  exp('exp_p_historical', 'wo_paired_historical', { is_historical: true }),
  exp('exp_p_zero', 'wo_paired_zero_amount', { amount: 0 }),
  exp('exp_p_multi_a', 'wo_paired_multiple'),
  exp('exp_p_multi_b', 'wo_paired_multiple', { amount: 99 }),
  // Same work-order id, different tenant: must NOT pair across the boundary.
  exp('exp_p_other_tenant', 'wo_paired_other_tenant', { user_id: UID2, company_id: CID2 }),
];

void runProjectionParity({
  sourceType: 'mechanic_work_order',
  collection: 'mechanic_work_orders',
  slug: 'wo',
  nestPort: 8471,
  documents,
  extraCollections: { expenses },
  // Project the expenses first, under a different owner on each database.
  preProject: {
    sourceType: 'expense',
    ids: expenses.map(
      (e) => [String(e['id']), String(e['user_id']), String(e['company_id'])] as [string, string, string],
    ),
  },
  zeroLegged: [
    // suppressed by pairing
    'wo_paired_normal',
    'wo_paired_deleted_int',
    'wo_paired_reversed_str',
    'wo_paired_historical',
    'wo_paired_zero_amount',
    'wo_paired_multiple',
    // suppressed by their own guards
    'wo_deleted',
    'wo_zero',
    'wo_negative',
    'wo_null_amount',
    'wo_missing_amount',
    'wo_tiny',
  ],
  sharedId: 'wo_unpaired',
  verifyRouting: true,
  extraChecks: (rows, report) => {
    const woRows = rows.filter((r) => r['source_type'] === 'mechanic_work_order');
    const of = (id: string): Doc[] =>
      woRows
        .filter((r) => r['source_id'] === id && r['user_id'] === UID)
        .sort((a, b) => String(a['ref_source_key']).localeCompare(String(b['ref_source_key'])));

    // 1. The orphan leg shape.
    report(
      JSON.stringify(
        of('wo_unpaired').map((r) => [r['ref_source_key'], r['account_code'], r['direction'], r['txn_type']]),
      ) ===
        JSON.stringify([
          ['mechanic_work_order:wo_unpaired:ap_credit', 'AP_MECHANIC', 'out', 'mechanic_wo_orphan'],
          ['mechanic_work_order:wo_unpaired:suspense_debit', 'SUSPENSE', 'in', 'mechanic_wo_orphan'],
        ]),
      'an unpaired work order parks the cost in SUSPENSE against AP_MECHANIC',
    );

    // 2. Pairing, in every state that matters.
    const suppressed = [
      'wo_paired_normal',
      'wo_paired_deleted_int',
      'wo_paired_reversed_str',
      'wo_paired_historical',
      'wo_paired_zero_amount',
      'wo_paired_multiple',
    ];
    report(
      suppressed.every((id) => of(id).length === 0),
      'a paired work order projects nothing',
      suppressed.filter((id) => of(id).length > 0).join(', '),
    );
    const projected = ['wo_unpaired', 'wo_paired_deleted', 'wo_paired_reversed', 'wo_paired_other_tenant'];
    report(
      projected.every((id) => of(id).length === 2),
      'a deleted, reversed or cross-tenant expense does NOT pair',
      projected.filter((id) => of(id).length !== 2).join(', '),
    );

    // 3. The $ne:true trap, stated as its own assertion.
    report(
      of('wo_paired_deleted').length === 2 && of('wo_paired_deleted_int').length === 0,
      'is_deleted true unpairs, but is_deleted 1 still pairs ($ne matches only BSON true)',
    );
    report(
      of('wo_paired_reversed').length === 2 && of('wo_paired_reversed_str').length === 0,
      'is_reversed true unpairs, but the string "false" still pairs',
    );

    // 4. A paired-but-unprojected expense leaves BOTH documents with no legs.
    const histExpense = rows.filter((r) => r['source_id'] === 'exp_p_historical');
    report(
      histExpense.length === 0 && of('wo_paired_historical').length === 0,
      'a historical expense projects nothing AND still suppresses its work order',
    );

    // 5. The guards this projection does NOT have.
    report(
      of('wo_reversed').length === 2 && of('wo_historical').length === 2,
      'a reversed or historical work order still projects — there is no guard for either',
    );
    report(of('wo_deleted_falsy').length === 2, 'a falsy is_deleted still projects');

    // 6. Fields.
    report(of('wo_unpaired')[0]?.['narration'] === 'WO wo_unpaired (orphan)', 'the narration is the fixed orphan form');
    const longId = woRows.find((r) => String(r['source_id']).startsWith('wo_long_'));
    report(String(longId?.['narration']).length === 400, 'the narration caps at 400');
    report(
      of('wo_wrong_date_field').every((r) => r['txn_date'] === '2026-09-02'),
      'the date comes from work_date, never a stray date field',
    );
    report(
      of('wo_unpaired').every((r) => r['party_type'] === 'mechanic' && r['party_id'] === 'mech_1'),
      'the mechanic is the party on every leg',
    );
    report(
      of('wo_unpaired').every((r) => r['source_key'] === '' && r['category'] === ''),
      'no source_key and no category are set',
    );
    report(
      of('wo_round_half_even').every((r) => r['amount'] === 2.67),
      'a 2.675 work order projects as 2.67 on both legs',
    );
    report(
      woRows.every((r) => {
        const expected = `fintxn_${String(r['ref_source_key']).replace(/:/g, '_').slice(0, 60)}`;
        return r['id'] === expected;
      }),
      'fin_txn ids follow the ref_source_key rule, truncated at 60',
    );
  },
});
