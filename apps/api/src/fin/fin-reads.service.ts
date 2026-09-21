import { Inject, Injectable } from '@nestjs/common';
import type { Request } from 'express';
import type { Db as MongoDb } from 'mongodb';
import { and, asc, eq, getTableColumns, gte, lte, sql } from 'drizzle-orm';
import { db as pg } from '../db/pg';
import { finDayClosure, finTxn } from '../db/schema';
import { activeCompanyId, authenticate, HttpError } from '../common/identity';
import { pyFloat, raw, type RawNumber } from '../common/py-json';
import { MONGO } from '../vendors/vendors.service';

/**
 * Phase 6 · slice 2a — Finance READS from PostgreSQL.
 *
 * Contract reference is the gate-locked Fastify shadow, not the Python source:
 *   backend-node/src/routes/fin-day-book.ts            (Gate 7s)
 *   backend-node/src/routes/fin-day-closures-list.ts   (Gate 7m)
 *   backend-node/src/routes/fin-day-closure-detail.ts  (Gate 7n)
 * Those already encode the verified behaviour; this layer only changes where
 * the data comes from.
 *
 * Scope: reads only. No write, no projection, no account seeding. In
 * particular GET /api/fin/accounts is NOT served here — it calls
 * ensure_system_accounts on every request, so it is a GET-time writer and
 * stays in Python.
 *
 * Why several Gate-7s edge cases cannot arise here: the Postgres schema
 * constrains what the columns can hold. `amount` is numeric, `account_code` is
 * text, and there is no BSON. So the shadow's handling of NaN/±Infinity,
 * ObjectId/Decimal128/Regex, non-string totals keys and unhashable keys has no
 * counterpart — those inputs cannot exist in this read model. The behaviours
 * that DO survive (ordering, tie-breaking, filter precedence, rounding, the
 * response envelope) are reproduced exactly.
 */

type Row = Record<string, unknown>;

/** fin_txn documents have two key orders in production; each row records its own. */
const DEFAULT_TXN_SHAPE = [
  'company_id', 'ref_source_key', 'account_code', 'account_id', 'adjustment_group_id',
  'amount', 'category', 'counter_account_code', 'counter_account_id', 'created_at',
  'direction', 'id', 'is_reversal', 'is_supplier_settlement_recovery', 'narration',
  'party_id', 'party_name', 'party_type', 'projected_at', 'reconciled_at',
  'reconciled_ref', 'reversal_of', 'source_id', 'source_key', 'source_type', 'status',
  'transfer_group_id', 'trip_id', 'txn_date', 'txn_type', 'vehicle_id',
];

type TxnRow = typeof finTxn.$inferSelect;

function txnField(r: TxnRow, key: string): unknown {
  switch (key) {
    case 'id': return r.id;
    case 'company_id': return r.companyId;
    case 'ref_source_key': return r.refSourceKey;
    case 'account_code': return r.accountCode;
    case 'account_id': return r.accountId;
    case 'adjustment_group_id': return r.adjustmentGroupId;
    case 'amount': return pyFloat(r.amount);
    case 'category': return r.category;
    case 'counter_account_code': return r.counterAccountCode;
    case 'counter_account_id': return r.counterAccountId;
    case 'created_at': return r.createdAt;
    case 'direction': return r.direction;
    case 'is_reversal': return r.isReversal;
    case 'is_supplier_settlement_recovery': return r.isSupplierSettlementRecovery;
    case 'narration': return r.narration;
    case 'party_id': return r.partyId;
    case 'party_name': return r.partyName;
    case 'party_type': return r.partyType;
    case 'projected_at': return r.projectedAt;
    case 'reconciled_at': return r.reconciledAt;
    case 'reconciled_ref': return r.reconciledRef;
    case 'reversal_of': return r.reversalOf;
    case 'source_id': return r.sourceId;
    case 'source_key': return r.sourceKey;
    case 'source_type': return r.sourceType;
    case 'status': return r.status;
    case 'transfer_group_id': return r.transferGroupId;
    case 'trip_id': return r.tripId;
    case 'txn_date': return r.txnDate;
    case 'txn_type': return r.txnType;
    case 'vehicle_id': return r.vehicleId;
    default: return undefined;
  }
}

export function txnToJson(r: TxnRow): Row {
  const shape = Array.isArray(r.sourceShape) && r.sourceShape.length ? r.sourceShape : DEFAULT_TXN_SHAPE;
  const out: Row = {};
  for (const key of shape) {
    if (key === '_id' || key === 'user_id') continue; // stripped by the Python projection
    const value = txnField(r, key);
    if (value !== undefined) out[key] = value;
  }
  return out;
}

/**
 * Python: `round(x, 2)` — banker's rounding, then rendered by repr(float).
 * Totals are accumulated as exact paisa integers so the sum itself cannot
 * drift; only the final rounding needs the half-to-even rule.
 */
export function roundHalfEven2(value: number): number {
  const scaled = value * 100;
  const floor = Math.floor(scaled);
  const diff = scaled - floor;
  let rounded: number;
  if (Math.abs(diff - 0.5) < 1e-9) rounded = floor % 2 === 0 ? floor : floor + 1;
  else rounded = Math.round(scaled);
  return rounded / 100;
}

export interface DayBookQuery {
  date_from: string;
  date_to: string;
  account_code?: string;
  account_id?: string;
  source_type?: string;
  party_id?: string;
  vehicle_id?: string;
  trip_id?: string;
  limit: number;
}

export interface DayBookResponse {
  date_from: string;
  date_to: string;
  rows: Row[];
  totals: Record<string, { in: RawNumber; out: RawNumber; net: RawNumber }>;
  count: number;
}

@Injectable()
export class FinReadsService {
  constructor(@Inject(MONGO) private readonly mongo: MongoDb) {}

  /** Auth only, so the controller can run it before query validation. */
  async assertAuthenticated(req: Request): Promise<void> {
    await authenticate(req, this.mongo);
  }

  private async scope(req: Request): Promise<{ uid: string; cid: string }> {
    // Sessions, users and companies still live in MongoDB (Python writes them).
    const user = await authenticate(req, this.mongo);
    const cid = await activeCompanyId(req, user.user_id, this.mongo);
    return { uid: user.user_id, cid };
  }

  /** GET /api/fin/day-book — Gate 7s contract, served from PostgreSQL. */
  async dayBook(req: Request, q: DayBookQuery): Promise<DayBookResponse> {
    const { uid, cid } = await this.scope(req);

    // Python checks the dates only AFTER resolving the active company, so a
    // request with no active company fails with THAT error, not this one.
    // Empty strings are the only rejected values — "x"/"y" reach the query
    // and simply match nothing.
    if (!q.date_from || !q.date_to) {
      throw new HttpError(400, 'date_from and date_to are required (YYYY-MM-DD)');
    }

    const clauses = [
      eq(finTxn.userId, uid),
      eq(finTxn.companyId, cid),
      gte(finTxn.txnDate, q.date_from),
      lte(finTxn.txnDate, q.date_to),
      eq(finTxn.status, 'active'),
    ];
    // Applied in Python's declaration order; only truthy values filter.
    if (q.account_code) clauses.push(eq(finTxn.accountCode, q.account_code));
    if (q.account_id) clauses.push(eq(finTxn.accountId, q.account_id));
    if (q.source_type) clauses.push(eq(finTxn.sourceType, q.source_type));
    if (q.party_id) clauses.push(eq(finTxn.partyId, q.party_id));
    if (q.vehicle_id) clauses.push(eq(finTxn.vehicleId, q.vehicle_id));
    if (q.trip_id) clauses.push(eq(finTxn.tripId, q.trip_id));

    // Python: int(max(1, min(limit, 20000)))
    const cap = Math.trunc(Math.max(1, Math.min(q.limit, 20000)));

    const rows = await pg
      .select({ ...getTableColumns(finTxn) })
      .from(finTxn)
      .where(and(...clauses))
      // txn_date and created_at are stored as TEXT, so this is Mongo's own
      // lexicographic ordering.
      //
      // The tie-break is ours, not Mongo's, and it cannot be otherwise.
      // Every fin_txn is written as a balanced pair, so both legs share
      // (txn_date, created_at): measured on the local copy, the full-year
      // day-book is 694 rows in 347 tie groups of exactly 2. MongoDB does not
      // define the order within a tie, and the observed order is not derivable
      // — in one group Python returned the pair descending by _id (…b66 before
      // …b64) and in the next ascending (…d1 before …d3). So no key reproduces
      // it. mongo_id ASC at least makes OUR order deterministic and stable
      // across runs; 688 of 694 positions coincide with Python's anyway.
      // scripts/fin-reads-parity.ts therefore compares tie groups as sets.
      .orderBy(
        sql`${finTxn.txnDate} DESC`,
        sql`${finTxn.createdAt} DESC`,
        asc(finTxn.mongoId),
      )
      .limit(cap);

    // Totals: insertion-ordered by first appearance, accumulated in paisa.
    const paise = new Map<string, { in: number; out: number }>();
    for (const r of rows) {
      const code = r.accountCode || '';
      let t = paise.get(code);
      if (!t) {
        t = { in: 0, out: 0 };
        paise.set(code, t);
      }
      const amt = Math.round(Number(r.amount ?? 0) * 100);
      if (r.direction === 'in') t.in += amt;
      else t.out += amt;
    }
    const totals: DayBookResponse['totals'] = {};
    for (const [code, t] of paise) {
      const inV = roundHalfEven2(t.in / 100);
      const outV = roundHalfEven2(t.out / 100);
      totals[code] = {
        in: pyFloat(inV) ?? raw('0.0'),
        out: pyFloat(outV) ?? raw('0.0'),
        net: pyFloat(roundHalfEven2(inV - outV)) ?? raw('0.0'),
      };
    }

    return {
      date_from: q.date_from,
      date_to: q.date_to,
      rows: rows.map(txnToJson),
      totals,
      count: rows.length,
    };
  }

  /** Shared closure ordering: close_date DESC, then Mongo's tie order. */
  private closureOrder() {
    return [sql`${finDayClosure.closeDate} DESC`, asc(finDayClosure.mongoId)] as const;
  }

  /**
   * GET /api/fin/day-closures — Gate 7m contract.
   * Python returns an ENVELOPE, {"rows": [...], "count": n}, not a bare list,
   * and applies date_from/date_to as one range clause plus an optional status.
   */
  async dayClosures(
    req: Request,
    opts: { date_from?: string; date_to?: string; status?: string; limit: number },
  ): Promise<{ rows: Row[]; count: number }> {
    const { uid, cid } = await this.scope(req);
    const clauses = [eq(finDayClosure.userId, uid), eq(finDayClosure.companyId, cid)];
    // Python builds ONE close_date range when either bound is truthy.
    if (opts.date_from) clauses.push(gte(finDayClosure.closeDate, opts.date_from));
    if (opts.date_to) clauses.push(lte(finDayClosure.closeDate, opts.date_to));
    if (opts.status) clauses.push(eq(finDayClosure.status, opts.status));

    const cap = Math.trunc(Math.max(1, Math.min(opts.limit, 5000)));
    const rows = await pg
      .select({
        ...getTableColumns(finDayClosure),
        snapshotText: sql<string | null>`${finDayClosure.snapshot}::text`,
        historyText: sql<string | null>`${finDayClosure.history}::text`,
      })
      .from(finDayClosure)
      .where(and(...clauses))
      .orderBy(...this.closureOrder())
      .limit(cap);
    return { rows: rows.map(closureToJson), count: rows.length };
  }

  async dayClosure(req: Request, closeDate: string): Promise<Row | null> {
    const { uid, cid } = await this.scope(req);
    const rows = await pg
      .select({
        ...getTableColumns(finDayClosure),
        snapshotText: sql<string | null>`${finDayClosure.snapshot}::text`,
        historyText: sql<string | null>`${finDayClosure.history}::text`,
      })
      .from(finDayClosure)
      .where(
        and(
          eq(finDayClosure.userId, uid),
          eq(finDayClosure.companyId, cid),
          eq(finDayClosure.closeDate, closeDate),
        ),
      )
      .limit(1);
    const row = rows[0];
    return row ? closureToJson(row) : null;
  }
}

/**
 * All fin_day_closures share one key order.
 *
 * `snapshot` and `history` are selected as TEXT and emitted verbatim: letting
 * the driver parse and re-encode them reorders object keys and turns 52400.0
 * into 52400, both of which are visible in the response.
 */
export type ClosureRow = typeof finDayClosure.$inferSelect & {
  snapshotText: string | null;
  historyText: string | null;
};

export function closureToJson(r: ClosureRow): Row {
  return {
    id: r.id,
    company_id: r.companyId,
    close_date: r.closeDate,
    status: r.status,
    closed_at: r.closedAt,
    closed_by: r.closedBy,
    close_notes: r.closeNotes,
    snapshot: r.snapshotText === null ? null : raw(r.snapshotText),
    snapshot_source_count: r.snapshotSourceCount,
    reopened_at: r.reopenedAt,
    reopened_by: r.reopenedBy,
    reopen_reason: r.reopenReason,
    history: r.historyText === null ? null : raw(r.historyText),
    created_at: r.createdAt,
    modified_at: r.modifiedAt,
  };
}
