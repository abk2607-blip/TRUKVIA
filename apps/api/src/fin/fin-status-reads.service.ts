import { Inject, Injectable } from '@nestjs/common';
import type { Request } from 'express';
import type { Db as MongoDb } from 'mongodb';
import { and, asc, eq, getTableColumns, gt, lte, sql } from 'drizzle-orm';
import { db as pg } from '../db/pg';
import { finDayClosure, finTxn } from '../db/schema';
import { activeCompanyId, authenticate, HttpError } from '../common/identity';
import { pyFloat, raw, type RawNumber } from '../common/py-json';
import { pyIsoDateOrdinal } from '../common/py-date';
import { pyRound2 } from '../common/py-round';
import { txnToJson } from './fin-reads.service';
import { MONGO } from '../vendors/vendors.service';

/**
 * Phase 6 — the two Finance reads deferred out of slice 2a:
 *
 *   GET /api/fin/day-status
 *   GET /api/fin/day-closures/{close_date}/late-entries
 *
 * Both are served from PostgreSQL, using only the tables slice 2a already
 * migrated: `fin_txn` and `fin_day_closure`. No new table was needed — each
 * handler reads exactly those two and nothing else.
 *
 * Contract reference is the gate-locked Fastify shadow, not the Python source:
 *   backend-node/src/routes/fin-day-status.ts                (Gate 7o)
 *   backend-node/src/routes/fin-day-closure-late-entries.ts  (Gate 7r, 542/542)
 *
 * BOTH ARE STRICTLY READ-ONLY. Python performs two reads per request and no
 * write at all — `r["days_late"] = …` in late_entries mutates the in-memory
 * row, not the document. Slice 2a's file is imported from, never modified.
 */

type Row = Record<string, unknown>;

/**
 * Several Gate-7r behaviours cannot arise against this read model and are
 * deliberately absent: the shadow handles NaN/±Infinity, ObjectId, Decimal128,
 * Binary, Code, unhashable `by_source_type` keys and non-string amounts, all
 * of which make Python return 500. In PostgreSQL `amount` is numeric,
 * `source_type` is text and there is no BSON, so none of those values can
 * exist. What does survive — ordering, filter semantics, the float rendering,
 * the rounding rule, bucket boundaries and the response envelope — is exact.
 */

/** Python `_bucket`. */
export function bucket(days: number): string {
  if (days <= 7) return '0-7';
  if (days <= 30) return '8-30';
  if (days <= 90) return '31-90';
  return '90+';
}

export interface LateEntriesResponse {
  close_date: string;
  count: number;
  totals: { in: RawNumber; out: RawNumber; net: RawNumber };
  by_source_type: Record<string, number>;
  by_days_late_bucket: Record<string, number>;
  rows: Row[];
}

@Injectable()
export class FinStatusReadsService {
  constructor(@Inject(MONGO) private readonly mongo: MongoDb) {}

  /** Auth only, so the controller can order 401 before query validation. */
  async assertAuthenticated(req: Request): Promise<void> {
    await authenticate(req, this.mongo);
  }

  private async scope(req: Request): Promise<{ uid: string; cid: string }> {
    // Sessions, users and companies are still MongoDB's (Python writes them).
    const user = await authenticate(req, this.mongo);
    const cid = await activeCompanyId(req, user.user_id, this.mongo);
    return { uid: user.user_id, cid };
  }

  /**
   * GET /api/fin/day-status — Gate 7o contract.
   *
   * Python projects five fields off the closure. Two truthiness rules follow
   * from that and are easy to miss:
   *   • `if not doc` — a closure row holding NONE of the five projected
   *     fields projects to `{}`, which is falsy, so Python reports it as NOT
   *     FOUND and returns the two-key shape;
   *   • `doc.get("status")` defaults to null when absent, while the other
   *     four default to "".
   */
  async dayStatus(req: Request, date: string): Promise<Row> {
    const { uid, cid } = await this.scope(req);

    const rows = await pg
      .select({
        status: finDayClosure.status,
        closedAt: finDayClosure.closedAt,
        closedBy: finDayClosure.closedBy,
        reopenedAt: finDayClosure.reopenedAt,
        reopenedBy: finDayClosure.reopenedBy,
      })
      .from(finDayClosure)
      .where(
        and(
          eq(finDayClosure.userId, uid),
          eq(finDayClosure.companyId, cid),
          eq(finDayClosure.closeDate, date),
        ),
      )
      .limit(1);

    const doc = rows[0];
    // The projected document is empty when every one of the five is absent.
    const projectedEmpty =
      !doc ||
      (doc.status === null &&
        doc.closedAt === null &&
        doc.closedBy === null &&
        doc.reopenedAt === null &&
        doc.reopenedBy === null);
    if (projectedEmpty) return { date, is_closed: false };

    const isClosed = doc.status === 'closed';
    let hasLate = false;
    // Python only pays for this probe when the day is currently closed AND
    // closed_at is truthy — an empty string does not qualify.
    if (isClosed && doc.closedAt) {
      const probe = await pg
        .select({ one: sql<number>`1` })
        .from(finTxn)
        .where(
          and(
            eq(finTxn.userId, uid),
            eq(finTxn.companyId, cid),
            eq(finTxn.status, 'active'),
            lte(finTxn.txnDate, date),
            gt(finTxn.createdAt, doc.closedAt),
          ),
        )
        .limit(1);
      // Python takes bool() of the projected {_id:0, id:1} document, so a
      // matching row without an `id` would project to {} and read as false.
      hasLate = probe.length > 0;
    }

    return {
      date,
      is_closed: isClosed,
      status: doc.status,
      closed_at: doc.closedAt ?? '',
      closed_by: doc.closedBy ?? '',
      reopened_at: doc.reopenedAt ?? '',
      reopened_by: doc.reopenedBy ?? '',
      has_late_entries: hasLate,
    };
  }

  /** GET /api/fin/day-closures/{close_date}/late-entries — Gate 7r contract. */
  async lateEntries(req: Request, closeDate: string): Promise<LateEntriesResponse> {
    const { uid, cid } = await this.scope(req);

    const closure = await pg
      .select({ closedAt: finDayClosure.closedAt })
      .from(finDayClosure)
      .where(
        and(
          eq(finDayClosure.userId, uid),
          eq(finDayClosure.companyId, cid),
          eq(finDayClosure.closeDate, closeDate),
        ),
      )
      .limit(1);

    // Python projects {_id:0, closed_at:1}; a closure with no closed_at
    // projects to {} and is falsy, so it 404s exactly like a missing one.
    const closedAtRaw = closure[0]?.closedAt ?? null;
    if (closure.length === 0 || closedAtRaw === null) {
      throw new HttpError(404, `No closure exists for ${closeDate}`);
    }
    // `closure.get("closed_at") or ""` — an empty closed_at matches everything.
    const closedAt = closedAtRaw;

    const rows = await pg
      .select({ ...getTableColumns(finTxn) })
      .from(finTxn)
      .where(
        and(
          eq(finTxn.userId, uid),
          eq(finTxn.companyId, cid),
          eq(finTxn.status, 'active'),
          lte(finTxn.txnDate, closeDate),
          gt(finTxn.createdAt, closedAt),
        ),
      )
      // Python sorts on txn_date alone. mongo_id makes OUR order deterministic;
      // it cannot reproduce Mongo's, which is undefined within a date — see the
      // note in scripts/fin-status-parity.ts.
      .orderBy(sql`${finTxn.txnDate} DESC`, asc(finTxn.mongoId))
      // Motor's to_list(5000) is a client-side cap, not a server .limit(): a
      // server limit would change WHICH rows win a txn_date tie.
      .limit(5000);

    const bySource: Record<string, number> = {};
    const byBucket: Record<string, number> = { '0-7': 0, '8-30': 0, '31-90': 0, '90+': 0 };
    let inSum = 0;
    let outSum = 0;

    const closeOrd = pyIsoDateOrdinal(closeDate);
    const out: Row[] = [];
    for (const r of rows) {
      const stype = r.sourceType ?? '';
      bySource[stype] = (bySource[stype] ?? 0) + 1;

      // days_late = max(0, (close_date - txn_date[:10]).days); anything
      // unparsable is 0, which is what Python's bare `except` produces.
      let daysLate = 0;
      const txnOrd = r.txnDate ? pyIsoDateOrdinal(r.txnDate.slice(0, 10)) : null;
      if (closeOrd !== null && txnOrd !== null) daysLate = closeOrd - txnOrd;
      if (daysLate < 0) daysLate = 0;
      byBucket[bucket(daysLate)] = (byBucket[bucket(daysLate)] ?? 0) + 1;

      const amount = Number(r.amount ?? 0) || 0;
      if (r.direction === 'in') inSum += amount;
      else outSum += amount;

      out.push({ ...txnToJson(r), days_late: daysLate });
    }

    // Python accumulates RAW floats and rounds once at the end; `net` is then
    // computed from the already-rounded in/out. Accumulating in integer paise
    // instead would be more accurate and would therefore NOT match.
    const totalIn = pyRound2(inSum);
    const totalOut = pyRound2(outSum);

    return {
      close_date: closeDate,
      count: rows.length,
      totals: {
        in: pyFloat(totalIn) ?? raw('0.0'),
        out: pyFloat(totalOut) ?? raw('0.0'),
        net: pyFloat(pyRound2(totalIn - totalOut)) ?? raw('0.0'),
      },
      by_source_type: bySource,
      by_days_late_bucket: byBucket,
      rows: out,
    };
  }
}
