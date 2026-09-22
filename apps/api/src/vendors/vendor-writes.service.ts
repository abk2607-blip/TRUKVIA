import { Inject, Injectable } from '@nestjs/common';
import type { Request } from 'express';
import type { Db as MongoDb } from 'mongodb';
import { randomUUID } from 'node:crypto';
import { sql } from 'drizzle-orm';
import { db as pg } from '../db/pg';
import { activeCompanyId, authenticate, HttpError, type AuthUser } from '../common/identity';
import { MONGO } from './vendors.service';

/**
 * Phase 6 · slice 1b — vendor MASTER writes:
 *   POST   /api/vendors
 *   PUT    /api/vendors/{vid}
 *   DELETE /api/vendors/{vid}
 *   POST   /api/vendors/{vid}/reactivate
 *
 * WRITE MODEL — deliberate, and not a dual-write of two sources of truth:
 * MongoDB stays authoritative. NestJS performs exactly the writes Python
 * performs (same collection, same audit row), then refreshes its own Postgres
 * read copy from the document it just wrote. Postgres is derived and can be
 * rebuilt at any time by re-running the migration, so a failure there costs a
 * stale read, never a lost write.
 *
 * Why Mongo must stay authoritative for now: Python still reads vendors in
 * paths this slice does not own — the party ledger (services_party_ledger),
 * the vendor-bill delete guard, and payment creation validation. Making
 * Postgres authoritative before those move would break them.
 *
 * Vendor master writes fire NO fin_txn projection: the hook is invoked only on
 * vendor_payment writes (routers/vendors.py lines 240/266/296) and on bill
 * writes. That is why the master writes can move first.
 */

const nowIso = (): string => {
  // Python: datetime.now(timezone.utc).isoformat() -> "...+00:00" with microseconds.
  const d = new Date();
  const ms = d.toISOString(); // 2026-09-21T10:00:00.123Z
  return `${ms.slice(0, -1)}000+00:00`;
};

const newId = (prefix: string): string => `${prefix}${randomUUID().replace(/-/g, '').slice(0, 16)}`;

/** Fields of the Pydantic Vendor model, in declaration order, with defaults. */
const VENDOR_FIELDS: Array<[string, unknown]> = [
  ['id', null], // default_factory new_id("ven_")
  ['name', undefined], // required
  ['contact_person', ''],
  ['mobile', ''],
  ['alt_mobile', ''],
  ['address', ''],
  ['state', ''],
  ['city', ''],
  ['gst_in', ''],
  ['pan', ''],
  ['msme_number', ''],
  ['bank_name', ''],
  ['account_number', ''],
  ['ifsc', ''],
  ['branch', ''],
  ['payment_terms', ''],
  ['opening_balance', 0.0],
  ['opening_balance_type', 'payable'],
  ['remarks', ''],
  ['is_active', true],
  ['created_by', ''],
  ['created_at', null], // default_factory now_utc().isoformat()
  ['modified_by', ''],
  ['modified_at', ''],
  ['deactivated_by', ''],
  ['deactivated_at', ''],
  ['deactivation_reason', ''],
  ['imported_from', ''],
  ['imported_ref', ''],
  ['imported_batch', ''],
  ['is_historical', false],
];

const STRING_FIELDS = new Set(
  VENDOR_FIELDS.filter(([, d]) => typeof d === 'string').map(([k]) => k),
);
const BOOL_FIELDS = new Set(['is_active', 'is_historical']);

export interface PydanticIssue {
  type: string;
  loc: string[];
  msg: string;
  input: unknown;
  /** Pydantic includes ctx for literal/constraint errors; key order matters. */
  ctx?: Record<string, unknown>;
  url?: string;
}

export class ValidationError extends Error {
  constructor(readonly issues: PydanticIssue[]) {
    super('validation error');
  }
}

/** Pydantic v2 string coercion: str fields reject non-strings (strict-ish in v2). */
function asString(key: string, value: unknown, issues: PydanticIssue[]): string {
  if (typeof value === 'string') return value;
  issues.push({
    type: 'string_type',
    loc: ['body', key],
    msg: 'Input should be a valid string',
    input: value,
    url: 'https://errors.pydantic.dev/2.13/v/string_type',
  });
  return '';
}

function asFloat(key: string, value: unknown, issues: PydanticIssue[]): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value))) {
    return Number(value);
  }
  issues.push({
    type: 'float_parsing',
    loc: ['body', key],
    msg: 'Input should be a valid number, unable to parse string as a number',
    input: value,
    url: 'https://errors.pydantic.dev/2.13/v/float_parsing',
  });
  return 0;
}

function asBool(key: string, value: unknown, issues: PydanticIssue[]): boolean {
  if (typeof value === 'boolean') return value;
  issues.push({
    type: 'bool_type',
    loc: ['body', key],
    msg: 'Input should be a valid boolean',
    input: value,
    url: 'https://errors.pydantic.dev/2.13/v/bool_type',
  });
  return false;
}

/**
 * Build the document Pydantic's Vendor(**payload).model_dump() would produce.
 * Unknown keys are ignored (BaseModel default), field order is the model's.
 */
export function vendorModelDump(payload: Record<string, unknown>): Record<string, unknown> {
  const issues: PydanticIssue[] = [];
  const out: Record<string, unknown> = {};

  for (const [key, dflt] of VENDOR_FIELDS) {
    const provided = Object.prototype.hasOwnProperty.call(payload, key);
    const raw = payload[key];

    if (key === 'name') {
      if (!provided || raw === undefined) {
        issues.push({
          type: 'missing',
          loc: ['body', 'name'],
          msg: 'Field required',
          input: payload,
          url: 'https://errors.pydantic.dev/2.13/v/missing',
        });
        out['name'] = '';
        continue;
      }
      out['name'] = asString('name', raw, issues);
      continue;
    }

    if (!provided || raw === undefined) {
      if (key === 'id') out['id'] = newId('ven_');
      else if (key === 'created_at') out['created_at'] = nowIso();
      else out[key] = dflt;
      continue;
    }

    if (key === 'opening_balance') {
      out[key] = asFloat(key, raw, issues);
    } else if (key === 'opening_balance_type') {
      if (raw === 'payable' || raw === 'advance') out[key] = raw;
      else {
        issues.push({
          type: 'literal_error',
          loc: ['body', key],
          msg: "Input should be 'payable' or 'advance'",
          input: raw,
          ctx: { expected: "'payable' or 'advance'" },
          url: 'https://errors.pydantic.dev/2.13/v/literal_error',
        });
        out[key] = 'payable';
      }
    } else if (BOOL_FIELDS.has(key)) {
      out[key] = asBool(key, raw, issues);
    } else if (STRING_FIELDS.has(key) || key === 'id' || key === 'created_at') {
      out[key] = asString(key, raw, issues);
    } else {
      out[key] = raw;
    }
  }

  if (issues.length) throw new ValidationError(issues);
  return out;
}

/** Python `_diff_dict`: {field: {old, new}} for keys whose values differ. */
export function diffDict(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): Record<string, { old: unknown; new: unknown }> {
  const out: Record<string, { old: unknown; new: unknown }> = {};
  for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
    if (JSON.stringify(before[key]) !== JSON.stringify(after[key])) {
      out[key] = { old: before[key] ?? null, new: after[key] ?? null };
    }
  }
  return out;
}

@Injectable()
export class VendorWritesService {
  constructor(@Inject(MONGO) private readonly mongo: MongoDb) {}

  private async scope(req: Request): Promise<{ user: AuthUser; uid: string; cid: string }> {
    const user = await authenticate(req, this.mongo);
    const cid = await activeCompanyId(req, user.user_id, this.mongo);
    return { user, uid: user.user_id, cid };
  }

  /** Python `_require_delete_role`: owner or admin only. */
  private requireDeleteRole(user: AuthUser): void {
    const role = (user.effective_role || '').toLowerCase();
    if (role !== 'owner' && role !== 'admin') {
      throw new HttpError(403, 'Owner or Admin role required.');
    }
  }

  /** Mirror of audit._log_audit — never raises upstream, exactly as Python. */
  private async logAudit(
    user: AuthUser,
    cid: string,
    action: string,
    entityId: string,
    entityRef: string,
    reason: string,
    changes: Record<string, unknown>,
  ): Promise<void> {
    try {
      await this.mongo.collection('audit_logs').insertOne({
        id: newId('audit_'),
        timestamp: nowIso(),
        module: 'vendor',
        action,
        entity_id: entityId,
        entity_ref: entityRef,
        reason,
        changes,
        user_email: user.email ?? '',
        user_name: user.name ?? '',
        user_id: user.user_id,
      });
    } catch {
      /* Python swallows audit failures; so do we. */
    }
  }

  /** Refresh the Postgres read copy from the authoritative Mongo document. */
  private async syncToPostgres(id: string): Promise<void> {
    const doc = await this.mongo.collection('vendors').findOne({ id });
    if (!doc) {
      await pg.execute(sql`DELETE FROM trukvia.vendor WHERE id = ${id}`);
      return;
    }
    const s = (v: unknown, d = ''): string => (typeof v === 'string' ? v : d);
    const b = (v: unknown, d: boolean): boolean => (typeof v === 'boolean' ? v : d);
    const t = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);
    const amount = typeof doc['opening_balance'] === 'number' ? doc['opening_balance'] : 0;
    await pg.execute(sql`
      INSERT INTO trukvia.vendor (
        id, source_id, user_id, company_id, name, contact_person, mobile, alt_mobile, address,
        state, city, gst_in, pan, msme_number, bank_name, account_number, ifsc, branch,
        payment_terms, opening_balance, opening_balance_type, remarks, is_active, is_historical,
        imported_from, imported_ref, imported_batch, created_by, created_at, modified_by,
        modified_at, deactivated_by, deactivated_at, deactivation_reason)
      VALUES (
        ${s(doc['id'])}, ${String(doc['_id'] ?? '')}, ${s(doc['user_id'])}, ${s(doc['company_id'])},
        ${s(doc['name'])}, ${s(doc['contact_person'])}, ${s(doc['mobile'])}, ${s(doc['alt_mobile'])},
        ${s(doc['address'])}, ${s(doc['state'])}, ${s(doc['city'])}, ${s(doc['gst_in'])},
        ${s(doc['pan'])}, ${s(doc['msme_number'])}, ${s(doc['bank_name'])},
        ${s(doc['account_number'])}, ${s(doc['ifsc'])}, ${s(doc['branch'])},
        ${s(doc['payment_terms'])}, ${amount.toFixed(2)}, ${s(doc['opening_balance_type'], 'payable')},
        ${s(doc['remarks'])}, ${b(doc['is_active'], true)}, ${b(doc['is_historical'], false)},
        ${s(doc['imported_from'])}, ${s(doc['imported_ref'])}, ${s(doc['imported_batch'])},
        ${s(doc['created_by'])}, ${t(doc['created_at'])}, ${s(doc['modified_by'])},
        ${t(doc['modified_at'])}, ${s(doc['deactivated_by'])}, ${t(doc['deactivated_at'])},
        ${s(doc['deactivation_reason'])})
      ON CONFLICT (id) DO UPDATE SET
        source_id = EXCLUDED.source_id, name = EXCLUDED.name,
        contact_person = EXCLUDED.contact_person, mobile = EXCLUDED.mobile,
        alt_mobile = EXCLUDED.alt_mobile, address = EXCLUDED.address, state = EXCLUDED.state,
        city = EXCLUDED.city, gst_in = EXCLUDED.gst_in, pan = EXCLUDED.pan,
        msme_number = EXCLUDED.msme_number, bank_name = EXCLUDED.bank_name,
        account_number = EXCLUDED.account_number, ifsc = EXCLUDED.ifsc, branch = EXCLUDED.branch,
        payment_terms = EXCLUDED.payment_terms, opening_balance = EXCLUDED.opening_balance,
        opening_balance_type = EXCLUDED.opening_balance_type, remarks = EXCLUDED.remarks,
        is_active = EXCLUDED.is_active, is_historical = EXCLUDED.is_historical,
        imported_from = EXCLUDED.imported_from, imported_ref = EXCLUDED.imported_ref,
        imported_batch = EXCLUDED.imported_batch, created_by = EXCLUDED.created_by,
        created_at = EXCLUDED.created_at, modified_by = EXCLUDED.modified_by,
        modified_at = EXCLUDED.modified_at, deactivated_by = EXCLUDED.deactivated_by,
        deactivated_at = EXCLUDED.deactivated_at,
        deactivation_reason = EXCLUDED.deactivation_reason`);
  }

  async create(req: Request, payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    const { user, uid, cid } = await this.scope(req);
    const doc = vendorModelDump(payload);
    doc['user_id'] = uid;
    doc['company_id'] = cid;
    doc['created_by'] = uid;
    doc['created_at'] = nowIso();

    await this.mongo.collection('vendors').insertOne({ ...doc });
    await this.logAudit(user, cid, 'create', String(doc['id']), String(doc['name'] ?? ''), '', {});
    await this.syncToPostgres(String(doc['id']));

    const out = { ...doc };
    delete out['_id'];
    delete out['user_id'];
    return out;
  }

  async update(
    req: Request,
    vid: string,
    payload: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const { user, uid, cid } = await this.scope(req);
    const before = await this.mongo
      .collection('vendors')
      .findOne({ id: vid, user_id: uid, company_id: cid }, { projection: { _id: 0 } });
    if (!before) throw new HttpError(404, 'Vendor not found');

    const dumped = vendorModelDump(payload);
    const patch: Record<string, unknown> = { ...dumped };
    delete patch['id'];
    delete patch['created_at'];
    delete patch['created_by'];
    patch['modified_by'] = uid;
    patch['modified_at'] = nowIso();

    await this.mongo.collection('vendors').updateOne({ id: vid }, { $set: patch });
    const after = { ...before, ...patch };
    await this.logAudit(
      user,
      cid,
      'update',
      vid,
      String(before['name'] ?? ''),
      '',
      diffDict(before as Record<string, unknown>, after),
    );
    await this.syncToPostgres(vid);

    const out: Record<string, unknown> = { ...after };
    delete out['_id'];
    delete out['user_id'];
    return out;
  }

  async deactivate(req: Request, vid: string, reason: string): Promise<Record<string, unknown>> {
    const { user, uid, cid } = await this.scope(req);
    this.requireDeleteRole(user);
    const doc = await this.mongo
      .collection('vendors')
      .findOne({ id: vid, user_id: uid, company_id: cid }, { projection: { _id: 0 } });
    if (!doc) throw new HttpError(404, 'Vendor not found');

    const reasonClean = (reason || '').trim().slice(0, 240);
    const stamp = nowIso();
    await this.mongo.collection('vendors').updateOne(
      { id: vid },
      {
        $set: {
          is_active: false,
          deactivated_by: uid,
          deactivated_at: stamp,
          deactivation_reason: reasonClean,
          modified_by: uid,
          modified_at: stamp,
        },
      },
    );
    await this.logAudit(user, cid, 'deactivate', vid, String(doc['name'] ?? ''), reasonClean, {});
    await this.syncToPostgres(vid);
    return { ok: true, id: vid, is_active: false };
  }

  async reactivate(req: Request, vid: string): Promise<Record<string, unknown>> {
    const { user, uid, cid } = await this.scope(req);
    this.requireDeleteRole(user);
    const doc = await this.mongo
      .collection('vendors')
      .findOne({ id: vid, user_id: uid, company_id: cid }, { projection: { _id: 0 } });
    if (!doc) throw new HttpError(404, 'Vendor not found');

    await this.mongo
      .collection('vendors')
      .updateOne({ id: vid }, { $set: { is_active: true, modified_by: uid, modified_at: nowIso() } });
    await this.logAudit(user, cid, 'reactivate', vid, String(doc['name'] ?? ''), '', {});
    await this.syncToPostgres(vid);
    return { ok: true, id: vid, is_active: true };
  }
}
