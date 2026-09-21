import { Inject, Injectable } from '@nestjs/common';
import type { Request } from 'express';
import { Double, type Db as MongoDb } from 'mongodb';
import { randomUUID } from 'node:crypto';
import { sql } from 'drizzle-orm';
import { db as pg } from '../db/pg';
import { activeCompanyId, authenticate, HttpError, type AuthUser } from '../common/identity';
import { pyDumps, pyFloat } from '../common/py-json';
import { pyRound2 } from '../common/py-round';
import { MONGO } from '../vendors/vendors.service';

/**
 * Phase 6 · slice 2b — Finance day-closure WRITES.
 *
 *   POST /api/fin/day-closures
 *   POST /api/fin/day-closures/{close_date}/reopen
 *
 * Source: backend/routers/fin_day_closing.py. There is no gate-locked Fastify
 * shadow for these two, because phase 3 covered GETs only — so Python itself is
 * the contract, and scripts/write-parity.ts compares against it directly.
 *
 * WRITE MODEL (unchanged from slice 1b): MongoDB stays authoritative. This
 * performs exactly the writes Python performs — same collections, same audit
 * row — then refreshes its own Postgres read copy from the document it just
 * wrote. A Postgres failure costs a stale read, never a lost write.
 *
 * Deliberately NOT here: /api/fin/reproject, hook_after_source_write, the
 * fin_txn projection, GET /api/fin/accounts, reconciliation. These two
 * handlers only ever READ fin_txn (inside the snapshot), so nothing here can
 * race the projection.
 */

type Doc = Record<string, unknown>;

/**
 * Python: datetime.now(timezone.utc).isoformat() — microsecond precision.
 * JS Date only has milliseconds, so the last three digits are always zero.
 * Kept identical to the slice-1b helper rather than shared, so that frozen
 * module is not touched.
 */
const nowIso = (): string => `${new Date().toISOString().slice(0, -1)}000+00:00`;

const newId = (prefix: string): string => `${prefix}${randomUUID().replace(/-/g, '').slice(0, 16)}`;

/** Python: `(value or "").strip()` — non-strings become "". */
function strStrip(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

/**
 * Python `date.fromisoformat`. CPython 3.11 also accepts the basic form
 * YYYYMMDD and ISO week/ordinal dates; that wider acceptance is a known,
 * already-tracked divergence (see the next-preview finding), so this keeps to
 * the extended calendar form the frontend actually sends and rejects the rest,
 * which is what the current Node stack does too.
 */
function isIsoDate(value: string): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (mo < 1 || mo > 12 || d < 1) return false;
  const daysInMonth = new Date(Date.UTC(y, mo, 0)).getUTCDate();
  return d <= daysInMonth;
}

export interface Snapshot {
  [accountCode: string]: { in: number; out: number; net: number };
}

/**
 * Snapshot values are Python floats by construction: the model types them
 * `Dict[str, Dict[str, float]]` and _capture_snapshot only ever produces
 * floats. Two consequences the obvious code gets wrong:
 *
 *   • stored in MongoDB they must be BSON doubles. The Node driver serialises
 *     an integral JS number as int32, so a balance of exactly 52400 would be
 *     stored with a different BSON type than pymongo stores;
 *   • rendered to JSON they must keep the trailing .0, so 52400 has to go out
 *     as 52400.0.
 *
 * `snapshot_source_count` is a genuine int and is deliberately left alone.
 */
export function snapshotToBson(snap: Snapshot): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [code, t] of Object.entries(snap)) {
    out[code] = { in: new Double(t.in), out: new Double(t.out), net: new Double(t.net) };
  }
  return out;
}

/** Force float rendering on a snapshot read back from MongoDB. */
export function floatifySnapshot(value: unknown): unknown {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return value;
  const out: Record<string, unknown> = {};
  for (const [code, t] of Object.entries(value as Record<string, unknown>)) {
    if (!t || typeof t !== 'object' || Array.isArray(t)) {
      out[code] = t;
      continue;
    }
    const inner: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(t as Record<string, unknown>)) {
      // The value is a plain number when read back through the driver, and a
      // BSON Double when it is the document we just built to write.
      const n =
        typeof v === 'number'
          ? v
          : v instanceof Double
            ? v.value
            : undefined;
      inner[k] = n === undefined ? v : pyFloat(n);
    }
    out[code] = inner;
  }
  return out;
}

/** Apply float rendering to a closure document's snapshot and history. */
export function floatifyClosure(doc: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(doc)) {
    if (k === 'snapshot') out[k] = floatifySnapshot(v);
    else if (k === 'history' && Array.isArray(v)) {
      out[k] = v.map((e) => {
        if (!e || typeof e !== 'object') return e;
        const entry: Record<string, unknown> = {};
        for (const [ek, ev] of Object.entries(e as Record<string, unknown>)) {
          entry[ek] = ek === 'snapshot' ? floatifySnapshot(ev) : ev;
        }
        return entry;
      });
    } else out[k] = v;
  }
  return out;
}

@Injectable()
export class FinWritesService {
  constructor(@Inject(MONGO) private readonly mongo: MongoDb) {}

  /** Auth only, so the controller can order 401 before the body 422. */
  async assertAuthenticated(req: Request): Promise<AuthUser> {
    return authenticate(req, this.mongo);
  }

  /** Python `_require_owner` — effective_role or role, lowercased. */
  private requireOwner(user: AuthUser): void {
    const role = (user.effective_role || '').toLowerCase();
    if (role !== 'owner') {
      throw new HttpError(
        403,
        'Owner-only endpoint. Only the tenant owner may close or reopen a day.',
      );
    }
  }

  /**
   * Python `_capture_snapshot`. Cumulative, not per-day: every active leg on or
   * before close_date. Read from MongoDB, not the Postgres copy, because Mongo
   * is the source of truth for fin_txn and the Python projection still writes
   * it — and because the key order below is the cursor's natural order, which
   * only Mongo can supply.
   */
  private async captureSnapshot(
    uid: string,
    cid: string,
    closeDate: string,
  ): Promise<{ snap: Snapshot; count: number }> {
    const cursor = this.mongo.collection<Doc>('fin_txn').find(
      { user_id: uid, company_id: cid, status: 'active', txn_date: { $lte: closeDate } },
      { projection: { _id: 0, account_code: 1, direction: 1, amount: 1 } },
    );

    const snap: Snapshot = {};
    let count = 0;
    for await (const r of cursor) {
      count += 1;
      const code = typeof r['account_code'] === 'string' && r['account_code'] ? r['account_code'] : '';
      let t = snap[code];
      if (t === undefined) {
        t = { in: 0, out: 0, net: 0 };
        snap[code] = t;
      }
      // Python: float(r.get("amount") or 0) — null, 0 and missing all give 0.0.
      const amount = Number(r['amount'] ?? 0) || 0;
      if (r['direction'] === 'in') t.in += amount;
      else t.out += amount;
    }
    // `net` is computed from the ALREADY-ROUNDED in/out, not from the raw sums.
    for (const t of Object.values(snap)) {
      t.in = pyRound2(t.in);
      t.out = pyRound2(t.out);
      t.net = pyRound2(t.in - t.out);
    }
    return { snap, count };
  }

  /** Mirror of audit._log_audit — never raises upstream, exactly as Python. */
  private async logAudit(
    user: AuthUser,
    action: string,
    entityId: string,
    entityRef: string,
    changes: Doc,
  ): Promise<void> {
    try {
      await this.mongo.collection('audit_logs').insertOne({
        id: newId('audit_'),
        timestamp: nowIso(),
        module: 'fin_day_closure',
        action,
        entity_id: entityId,
        entity_ref: entityRef,
        reason: '',
        changes,
        user_email: user.email ?? '',
        user_name: user.name ?? '',
        user_id: user.user_id,
      });
    } catch {
      /* Python swallows audit failures; so do we. */
    }
  }

  /** POST /api/fin/day-closures */
  async closeDay(req: Request, body: Doc): Promise<Doc> {
    const user = await authenticate(req, this.mongo);
    // Owner check precedes company resolution, as in Python.
    this.requireOwner(user);
    const uid = user.user_id;
    const cid = await activeCompanyId(req, uid, this.mongo);

    const closeDate = strStrip(body['close_date']);
    if (!closeDate) throw new HttpError(400, 'close_date is required');
    if (!isIsoDate(closeDate)) throw new HttpError(400, 'close_date must be ISO YYYY-MM-DD');
    // now_utc().date() — compared as strings, both being YYYY-MM-DD.
    const today = new Date().toISOString().slice(0, 10);
    if (closeDate > today) {
      throw new HttpError(422, 'close_date cannot be in the future (v1 accepts today or past)');
    }
    const closeNotes = strStrip(body['close_notes']);

    const closures = this.mongo.collection<Doc>('fin_day_closures');
    const key = { user_id: uid, company_id: cid, close_date: closeDate };
    const existing = await closures.findOne(key, { projection: { _id: 0 } });
    const now = nowIso();
    // Python captures the snapshot BEFORE the already-closed 409. Kept in the
    // same place: it is a read, so the only effect is the wasted scan.
    const { snap, count } = await this.captureSnapshot(uid, cid, closeDate);

    if (existing && existing['status'] === 'closed') {
      throw new HttpError(409, `Day ${closeDate} is already closed`);
    }

    if (existing && existing['status'] === 'reopened') {
      // Re-close: refresh the snapshot, append history, clear the reopen fields.
      const history = Array.isArray(existing['history']) ? [...existing['history']] : [];
      history.push({
        event: 'closed',
        at: now,
        by: uid,
        notes: closeNotes,
        snapshot: snapshotToBson(snap),
        snapshot_source_count: count,
      });
      await closures.updateOne(key, {
        $set: {
          status: 'closed',
          closed_at: now,
          closed_by: uid,
          close_notes: closeNotes,
          snapshot: snapshotToBson(snap),
          snapshot_source_count: count,
          reopened_at: '',
          reopened_by: '',
          reopen_reason: '',
          history,
          modified_at: now,
        },
      });
      const doc = await closures.findOne(key, { projection: { _id: 0, user_id: 0 } });
      const out = floatifyClosure((doc ?? {}) as Doc);
      await this.logAudit(user, 'reclose', String(out['id'] ?? ''), closeDate, {
        count,
        accounts: Object.keys(snap).length,
      });
      await this.syncToPostgres(uid, cid, closeDate);
      return out;
    }

    // Fresh close. closed_at and created_at are two SEPARATE now_utc() calls in
    // Python's model defaults, evaluated in field order, so they may differ in
    // the microseconds; history[0].at reuses closed_at, not `now`.
    const closedAt = nowIso();
    const createdAt = nowIso();
    const doc: Doc = {
      id: newId('fdc_'),
      user_id: uid,
      company_id: cid,
      close_date: closeDate,
      status: 'closed',
      closed_at: closedAt,
      closed_by: uid,
      close_notes: closeNotes,
      snapshot: snapshotToBson(snap),
      snapshot_source_count: count,
      reopened_at: '',
      reopened_by: '',
      reopen_reason: '',
      history: [
        {
          event: 'closed',
          at: closedAt,
          by: uid,
          notes: closeNotes,
          snapshot: snapshotToBson(snap),
          snapshot_source_count: count,
        },
      ],
      created_at: createdAt,
      modified_at: '',
    };
    try {
      await closures.insertOne(doc as never);
    } catch (err) {
      // The unique (user_id, company_id, close_date) index — concurrent close.
      throw new HttpError(409, `Day ${closeDate} already closed (concurrent write)`);
    }
    await this.logAudit(user, 'close', String(doc['id']), closeDate, {
      count,
      accounts: Object.keys(snap).length,
      notes: closeNotes,
    });
    await this.syncToPostgres(uid, cid, closeDate);

    // insertOne mutates doc with _id; Python pops _id and user_id and keeps
    // company_id, leaving the model's declaration order.
    delete doc['_id'];
    delete doc['user_id'];
    return floatifyClosure(doc);
  }

  /** POST /api/fin/day-closures/{close_date}/reopen */
  async reopenDay(req: Request, closeDate: string, body: Doc): Promise<Doc> {
    const user = await authenticate(req, this.mongo);
    // Python order: owner, then the path date, then the company.
    this.requireOwner(user);
    if (!isIsoDate(closeDate)) throw new HttpError(400, 'close_date must be ISO YYYY-MM-DD');
    const uid = user.user_id;
    const cid = await activeCompanyId(req, uid, this.mongo);

    const reason = strStrip(body['reopen_reason']);
    if (!reason) throw new HttpError(400, 'reopen_reason is required');

    const closures = this.mongo.collection<Doc>('fin_day_closures');
    const key = { user_id: uid, company_id: cid, close_date: closeDate };
    const existing = await closures.findOne(key, { projection: { _id: 0 } });
    if (!existing) throw new HttpError(404, `No closure exists for ${closeDate}`);
    if (existing['status'] === 'reopened') {
      throw new HttpError(409, `Day ${closeDate} is already reopened`);
    }

    const now = nowIso();
    const history = Array.isArray(existing['history']) ? [...existing['history']] : [];
    history.push({ event: 'reopened', at: now, by: uid, reason });
    await closures.updateOne(key, {
      $set: {
        status: 'reopened',
        reopened_at: now,
        reopened_by: uid,
        reopen_reason: reason,
        history,
        modified_at: now,
      },
    });
    const doc = await closures.findOne(key, { projection: { _id: 0, user_id: 0 } });
    const out = floatifyClosure((doc ?? {}) as Doc);
    await this.logAudit(user, 'reopen', String(out['id'] ?? ''), closeDate, { reason });
    await this.syncToPostgres(uid, cid, closeDate);
    return out;
  }

  /**
   * Refresh the Postgres read copy from the authoritative Mongo document.
   *
   * snapshot and history are inserted as PRE-RENDERED Python JSON text cast to
   * `json`, for the reason slice 2a documented: letting anything re-encode them
   * reorders keys and turns 52400.0 into 52400, both visible in the GET.
   */
  private async syncToPostgres(uid: string, cid: string, closeDate: string): Promise<void> {
    try {
      const doc = await this.mongo
        .collection<Doc>('fin_day_closures')
        .findOne({ user_id: uid, company_id: cid, close_date: closeDate });
      if (!doc) return;
      const s = (v: unknown): string => (typeof v === 'string' ? v : '');
      const rendered = floatifyClosure(doc as Doc);
      const snapshotText = pyDumps(rendered['snapshot'] ?? {});
      const historyText = pyDumps(rendered['history'] ?? []);
      await pg.execute(sql`
        INSERT INTO trukvia.fin_day_closure (
          id, mongo_id, user_id, company_id, close_date, status,
          closed_at, closed_by, close_notes, snapshot, snapshot_source_count,
          reopened_at, reopened_by, reopen_reason, history, created_at, modified_at
        ) VALUES (
          ${s(doc['id'])}, ${String(doc['_id'])}, ${uid}, ${cid}, ${closeDate}, ${s(doc['status'])},
          ${s(doc['closed_at'])}, ${s(doc['closed_by'])}, ${s(doc['close_notes'])},
          ${snapshotText}::json, ${Number(doc['snapshot_source_count'] ?? 0)},
          ${s(doc['reopened_at'])}, ${s(doc['reopened_by'])}, ${s(doc['reopen_reason'])},
          ${historyText}::json, ${s(doc['created_at'])}, ${s(doc['modified_at'])}
        )
        ON CONFLICT (id) DO UPDATE SET
          status = EXCLUDED.status,
          closed_at = EXCLUDED.closed_at,
          closed_by = EXCLUDED.closed_by,
          close_notes = EXCLUDED.close_notes,
          snapshot = EXCLUDED.snapshot,
          snapshot_source_count = EXCLUDED.snapshot_source_count,
          reopened_at = EXCLUDED.reopened_at,
          reopened_by = EXCLUDED.reopened_by,
          reopen_reason = EXCLUDED.reopen_reason,
          history = EXCLUDED.history,
          modified_at = EXCLUDED.modified_at
      `);
    } catch {
      /* Derived copy only — a failure here must never fail the Mongo write. */
    }
  }
}
