import { Inject, Injectable } from '@nestjs/common';
import type { Request } from 'express';
import type { Db as MongoDb } from 'mongodb';
import { randomUUID } from 'node:crypto';
import { activeCompanyId, authenticate, HttpError, type AuthUser } from '../common/identity';
import { MONGO } from './vendors.service';
import { reprojectVendorSource } from '../fin/projection';
import { callPythonHook, hookConfigured } from '../fin/hook-client';
import { diffDict, ValidationError, type PydanticIssue } from './vendor-writes.service';

/**
 * Phase 6 · slice 1b — vendor BILL and PAYMENT writes.
 *   POST/PUT/DELETE /api/vendor-bills[/{bid}]
 *   POST/PUT/DELETE /api/vendors/{vid}/payments[/{pid}]
 *
 * These differ from the master writes in one way that matters: each one fires
 * the fin_txn projection. That projection is ported in src/fin/projection.ts
 * and verified row-for-row against Python by scripts/fin-projection-parity.ts.
 *
 * Ordering is copied from Python exactly, because it is observable:
 *   • bills   — write, THEN project, THEN audit;
 *   • payments — write, THEN audit, THEN project.
 * Like Python's hook, a projection failure never fails the write: it is
 * recorded in fin_hook_failures for the retry driver.
 *
 * MongoDB remains authoritative (see vendor-writes.service.ts); the Postgres
 * read copy is refreshed from the written document.
 */

const nowIso = (): string => `${new Date().toISOString().slice(0, -1)}000+00:00`;
const newId = (prefix: string): string => `${prefix}${randomUUID().replace(/-/g, '').slice(0, 16)}`;

type Doc = Record<string, unknown>;
const str = (v: unknown): string => (typeof v === 'string' ? v : '');

function issue(
  type: string,
  loc: string[],
  msg: string,
  input: unknown,
  ctx?: Record<string, unknown>,
): PydanticIssue {
  return {
    type,
    loc,
    msg,
    input,
    ...(ctx ? { ctx } : {}),
    url: `https://errors.pydantic.dev/2.13/v/${type}`,
  };
}

/** Shared coercion for the two models below, mirroring Pydantic v2. */
function coerce(
  key: string,
  raw: unknown,
  kind: 'str' | 'float' | 'bool' | 'list',
  issues: PydanticIssue[],
): unknown {
  if (kind === 'str') {
    if (typeof raw === 'string') return raw;
    issues.push(issue('string_type', ['body', key], 'Input should be a valid string', raw));
    return '';
  }
  if (kind === 'float') {
    if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
    if (typeof raw === 'string' && raw.trim() !== '' && Number.isFinite(Number(raw))) {
      return Number(raw);
    }
    issues.push(
      issue(
        'float_parsing',
        ['body', key],
        'Input should be a valid number, unable to parse string as a number',
        raw,
      ),
    );
    return 0;
  }
  if (kind === 'bool') {
    if (typeof raw === 'boolean') return raw;
    issues.push(issue('bool_type', ['body', key], 'Input should be a valid boolean', raw));
    return false;
  }
  if (Array.isArray(raw)) return raw;
  issues.push(issue('list_type', ['body', key], 'Input should be a valid list', raw));
  return [];
}

function literal(
  key: string,
  raw: unknown,
  allowed: string[],
  issues: PydanticIssue[],
): string {
  if (typeof raw === 'string' && allowed.includes(raw)) return raw;
  const expected =
    allowed.length === 2
      ? `'${allowed[0]}' or '${allowed[1]}'`
      : `${allowed.slice(0, -1).map((a) => `'${a}'`).join(', ')} or '${allowed.at(-1)}'`;
  issues.push(
    issue('literal_error', ['body', key], `Input should be ${expected}`, raw, { expected }),
  );
  return allowed[0] as string;
}

const MODES = ['Cash', 'Bank', 'UPI', 'IMPS', 'NEFT', 'RTGS', 'Cheque', 'Other'];

/** models.VendorBill.model_dump() */
export function billModelDump(payload: Doc): Doc {
  const issues: PydanticIssue[] = [];
  const has = (k: string): boolean => Object.prototype.hasOwnProperty.call(payload, k);
  const out: Doc = {};
  out['id'] = has('id') ? coerce('id', payload['id'], 'str', issues) : newId('vbl_');
  out['vendor_id'] = has('vendor_id')
    ? coerce('vendor_id', payload['vendor_id'], 'str', issues)
    : (issues.push(issue('missing', ['body', 'vendor_id'], 'Field required', payload)), '');
  out['vendor_name'] = has('vendor_name')
    ? coerce('vendor_name', payload['vendor_name'], 'str', issues)
    : '';
  out['bill_number'] = has('bill_number')
    ? coerce('bill_number', payload['bill_number'], 'str', issues)
    : '';
  out['bill_date'] = has('bill_date')
    ? coerce('bill_date', payload['bill_date'], 'str', issues)
    : (issues.push(issue('missing', ['body', 'bill_date'], 'Field required', payload)), '');
  out['bill_amount'] = has('bill_amount')
    ? coerce('bill_amount', payload['bill_amount'], 'float', issues)
    : (issues.push(issue('missing', ['body', 'bill_amount'], 'Field required', payload)), 0);
  for (const k of ['vehicle_id', 'vehicle_number', 'trip_id', 'repair_event_id', 'narration', 'remarks']) {
    out[k] = has(k) ? coerce(k, payload[k], 'str', issues) : '';
  }
  out['file_ids'] = has('file_ids') ? coerce('file_ids', payload['file_ids'], 'list', issues) : [];
  out['created_by'] = has('created_by') ? coerce('created_by', payload['created_by'], 'str', issues) : '';
  out['created_at'] = has('created_at')
    ? coerce('created_at', payload['created_at'], 'str', issues)
    : nowIso();
  out['modified_by'] = has('modified_by') ? coerce('modified_by', payload['modified_by'], 'str', issues) : '';
  out['modified_at'] = has('modified_at') ? coerce('modified_at', payload['modified_at'], 'str', issues) : '';
  out['is_deleted'] = has('is_deleted') ? coerce('is_deleted', payload['is_deleted'], 'bool', issues) : false;
  for (const k of ['deleted_by', 'deleted_at', 'deletion_reason']) {
    out[k] = has(k) ? coerce(k, payload[k], 'str', issues) : '';
  }
  if (issues.length) throw new ValidationError(issues);
  return out;
}

/** models.VendorPayment.model_dump() */
export function paymentModelDump(payload: Doc): Doc {
  const issues: PydanticIssue[] = [];
  const has = (k: string): boolean => Object.prototype.hasOwnProperty.call(payload, k);
  const out: Doc = {};
  out['id'] = has('id') ? coerce('id', payload['id'], 'str', issues) : newId('vpay_');
  out['vendor_id'] = has('vendor_id')
    ? coerce('vendor_id', payload['vendor_id'], 'str', issues)
    : (issues.push(issue('missing', ['body', 'vendor_id'], 'Field required', payload)), '');
  out['date'] = has('date')
    ? coerce('date', payload['date'], 'str', issues)
    : (issues.push(issue('missing', ['body', 'date'], 'Field required', payload)), '');
  out['amount'] = has('amount')
    ? coerce('amount', payload['amount'], 'float', issues)
    : (issues.push(issue('missing', ['body', 'amount'], 'Field required', payload)), 0);
  out['type'] = has('type')
    ? literal('type', payload['type'], ['payment_out', 'receipt_in'], issues)
    : 'payment_out';
  out['mode'] = has('mode') ? literal('mode', payload['mode'], MODES, issues) : 'Bank';
  out['account_id'] = has('account_id') ? coerce('account_id', payload['account_id'], 'str', issues) : '';
  out['ref_no'] = has('ref_no') ? coerce('ref_no', payload['ref_no'], 'str', issues) : '';
  out['against'] = has('against')
    ? literal('against', payload['against'], ['bill', 'advance', 'outstanding', 'other'], issues)
    : 'outstanding';
  out['vendor_bill_id'] = has('vendor_bill_id')
    ? coerce('vendor_bill_id', payload['vendor_bill_id'], 'str', issues)
    : '';
  out['remarks'] = has('remarks') ? coerce('remarks', payload['remarks'], 'str', issues) : '';
  out['file_ids'] = has('file_ids') ? coerce('file_ids', payload['file_ids'], 'list', issues) : [];
  out['bank_account_id'] = has('bank_account_id')
    ? coerce('bank_account_id', payload['bank_account_id'], 'str', issues)
    : '';
  out['bank_snapshot'] =
    has('bank_snapshot') && typeof payload['bank_snapshot'] === 'object' ? payload['bank_snapshot'] : {};
  out['company_bank_account_id'] = has('company_bank_account_id')
    ? coerce('company_bank_account_id', payload['company_bank_account_id'], 'str', issues)
    : '';
  out['source_bank_snapshot'] =
    has('source_bank_snapshot') && typeof payload['source_bank_snapshot'] === 'object'
      ? payload['source_bank_snapshot']
      : {};
  for (const k of ['corrected_at', 'corrected_by']) {
    out[k] = has(k) ? coerce(k, payload[k], 'str', issues) : '';
  }
  out['correction_count'] = has('correction_count')
    ? Math.trunc(Number(coerce('correction_count', payload['correction_count'], 'float', issues)))
    : 0;
  out['latest_correction_id'] = has('latest_correction_id')
    ? coerce('latest_correction_id', payload['latest_correction_id'], 'str', issues)
    : '';
  out['is_reversed'] = has('is_reversed') ? coerce('is_reversed', payload['is_reversed'], 'bool', issues) : false;
  for (const k of ['reversed_by', 'reversed_at', 'reversal_reason', 'reversal_of', 'reconciled_at', 'reconciled_ref']) {
    out[k] = has(k) ? coerce(k, payload[k], 'str', issues) : '';
  }
  out['created_by'] = has('created_by') ? coerce('created_by', payload['created_by'], 'str', issues) : '';
  out['created_at'] = has('created_at') ? coerce('created_at', payload['created_at'], 'str', issues) : nowIso();
  out['modified_by'] = has('modified_by') ? coerce('modified_by', payload['modified_by'], 'str', issues) : '';
  out['modified_at'] = has('modified_at') ? coerce('modified_at', payload['modified_at'], 'str', issues) : '';
  out['is_deleted'] = has('is_deleted') ? coerce('is_deleted', payload['is_deleted'], 'bool', issues) : false;
  for (const k of ['deleted_by', 'deleted_at', 'deletion_reason']) {
    out[k] = has(k) ? coerce(k, payload[k], 'str', issues) : '';
  }
  if (issues.length) throw new ValidationError(issues);
  return out;
}

/** services_bank_accounts.mask_account_number equivalent is only needed when a
 *  snapshot lacks masked_display; the source rows all carry it. */
const maskAccountNumber = (n: string): string => (n.length <= 4 ? n : `${'X'.repeat(n.length - 4)}${n.slice(-4)}`);

@Injectable()
export class VendorTxnWritesService {
  constructor(@Inject(MONGO) private readonly mongo: MongoDb) {}

  private async scope(req: Request): Promise<{ user: AuthUser; uid: string; cid: string }> {
    const user = await authenticate(req, this.mongo);
    const cid = await activeCompanyId(req, user.user_id, this.mongo);
    return { user, uid: user.user_id, cid };
  }

  private requireDeleteRole(user: AuthUser): void {
    const role = (user.effective_role || '').toLowerCase();
    if (role !== 'owner' && role !== 'admin') {
      throw new HttpError(403, 'Owner or Admin role required.');
    }
  }

  private async logAudit(
    user: AuthUser,
    module: string,
    action: string,
    entityId: string,
    entityRef: string,
    reason: string,
    changes: Doc,
  ): Promise<void> {
    try {
      await this.mongo.collection('audit_logs').insertOne({
        id: newId('audit_'),
        timestamp: nowIso(),
        module,
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
      /* Python swallows audit failures */
    }
  }

  /** routers/vendor_bills.py::_validate_refs */
  private async validateRefs(uid: string, cid: string, doc: Doc): Promise<[string, string]> {
    const ven = await this.mongo
      .collection<Doc>('vendors')
      .findOne({ id: str(doc['vendor_id']), user_id: uid, company_id: cid }, { projection: { _id: 0, name: 1 } });
    if (!ven) throw new HttpError(400, 'Vendor not found in tenant');
    let vehNumber = str(doc['vehicle_number']);
    if (doc['vehicle_id']) {
      const veh = await this.mongo
        .collection<Doc>('vehicles')
        .findOne(
          { id: str(doc['vehicle_id']), user_id: uid, company_id: cid },
          { projection: { _id: 0, vehicle_number: 1 } },
        );
      if (!veh) throw new HttpError(400, 'Vehicle not found in tenant');
      vehNumber = vehNumber || str(veh['vehicle_number']);
    }
    if (doc['trip_id']) {
      const trip = await this.mongo
        .collection<Doc>('trips')
        .findOne({ id: str(doc['trip_id']), user_id: uid, company_id: cid }, { projection: { _id: 0, id: 1 } });
      if (!trip) throw new HttpError(400, 'Trip not found in tenant');
    }
    if (doc['repair_event_id']) {
      const rev = await this.mongo.collection<Doc>('repair_events').findOne(
        {
          id: str(doc['repair_event_id']),
          user_id: uid,
          company_id: cid,
          is_deleted: { $ne: true },
        },
        { projection: { _id: 0, id: 1 } },
      );
      if (!rev) throw new HttpError(400, 'RepairEvent not found in tenant');
    }
    return [str(ven['name']), vehNumber];
  }

  /** routers/vendor_bills.py::_validate_files */
  private async validateFiles(uid: string, fileIds: unknown): Promise<void> {
    const ids = Array.isArray(fileIds) ? (fileIds as string[]) : [];
    if (!ids.length) return;
    const found = await this.mongo
      .collection('files')
      .countDocuments({ user_id: uid, id: { $in: ids }, is_deleted: false });
    if (found !== new Set(ids).size) {
      throw new HttpError(400, 'One or more file_ids invalid for this tenant');
    }
  }

  /**
   * Fire the fin_txn projection for a vendor source.
   *
   * Prefers the INTERNAL Python hook when it is configured, so the ledger has a
   * single implementation; falls back to the verified TypeScript port when it is
   * not (local development, or the hook being unreachable). Either way a
   * projection failure never fails the write — Python records it in
   * fin_hook_failures, and the port does the same.
   */
  private async project(uid: string, cid: string, type: 'vendor_bill' | 'vendor_payment', id: string): Promise<void> {
    if (hookConfigured()) {
      const viaPython = await callPythonHook(uid, cid, type, id);
      if (viaPython.ok) return;
      // The hook was configured but did not complete: fall back so the ledger is
      // not left stale, and let the port record its own failure if it also fails.
    }
    await reprojectVendorSource(this.mongo, uid, cid, type, id);
  }

  // ── vendor bills ────────────────────────────────────────────────────────

  async createBill(req: Request, payload: Doc): Promise<Doc> {
    const { user, uid, cid } = await this.scope(req);
    const doc = billModelDump(payload);
    if (Number(doc['bill_amount']) <= 0) throw new HttpError(400, 'bill_amount must be positive');
    if (!doc['bill_date']) throw new HttpError(400, 'bill_date is required');
    const [venName, vehNumber] = await this.validateRefs(uid, cid, doc);
    await this.validateFiles(uid, doc['file_ids']);

    if (doc['bill_number']) {
      const dup = await this.mongo.collection<Doc>('vendor_bills').findOne(
        {
          user_id: uid,
          company_id: cid,
          vendor_id: str(doc['vendor_id']),
          bill_number: str(doc['bill_number']),
          is_deleted: { $ne: true },
        },
        { projection: { _id: 0, id: 1 } },
      );
      if (dup) {
        throw new HttpError(409, `Bill number '${str(doc['bill_number'])}' already exists for this vendor`);
      }
    }

    doc['vendor_name'] = doc['vendor_name'] || venName;
    doc['vehicle_number'] = vehNumber;
    doc['user_id'] = uid;
    doc['company_id'] = cid;
    doc['created_by'] = uid;
    doc['created_at'] = nowIso();
    doc['is_deleted'] = false;

    await this.mongo.collection('vendor_bills').insertOne({ ...doc });
    // Python order: hook first, then audit.
    await this.project(uid, cid, 'vendor_bill', str(doc['id']));
    await this.logAudit(user, 'vendor_bill', 'create', str(doc['id']), str(doc['bill_number']), '', {});

    const out: Doc = { ...doc };
    delete out['_id'];
    delete out['user_id'];
    return out;
  }

  async updateBill(req: Request, bid: string, payload: Doc): Promise<Doc> {
    const { user, uid, cid } = await this.scope(req);
    const before = await this.mongo
      .collection<Doc>('vendor_bills')
      .findOne({ id: bid, user_id: uid, company_id: cid }, { projection: { _id: 0 } });
    if (!before) throw new HttpError(404, 'VendorBill not found');

    const dumped = billModelDump(payload);
    if (Number(dumped['bill_amount']) <= 0) throw new HttpError(400, 'bill_amount must be positive');
    const [venName, vehNumber] = await this.validateRefs(uid, cid, dumped);
    await this.validateFiles(uid, dumped['file_ids']);

    const patch: Doc = { ...dumped };
    for (const k of ['id', 'created_at', 'created_by', 'is_deleted', 'deleted_by', 'deleted_at', 'deletion_reason']) {
      delete patch[k];
    }
    patch['vendor_name'] = patch['vendor_name'] || venName;
    patch['vehicle_number'] = vehNumber;
    patch['modified_by'] = uid;
    patch['modified_at'] = nowIso();

    await this.mongo.collection('vendor_bills').updateOne({ id: bid }, { $set: patch });
    await this.project(uid, cid, 'vendor_bill', bid);
    const after = { ...before, ...patch };
    await this.logAudit(
      user,
      'vendor_bill',
      'update',
      bid,
      str(before['bill_number']),
      '',
      diffDict(before as Doc, after),
    );

    const out: Doc = { ...after };
    delete out['_id'];
    delete out['user_id'];
    return out;
  }

  async deleteBill(req: Request, bid: string, reason: string): Promise<Doc> {
    const { user, uid, cid } = await this.scope(req);
    this.requireDeleteRole(user);
    const doc = await this.mongo
      .collection<Doc>('vendor_bills')
      .findOne({ id: bid, user_id: uid, company_id: cid, is_deleted: { $ne: true } }, { projection: { _id: 0 } });
    if (!doc) throw new HttpError(404, 'VendorBill not found');

    const liveScope = { user_id: uid, company_id: cid, vendor_bill_id: bid, is_deleted: { $ne: true } };
    const expCt = await this.mongo.collection('expenses').countDocuments(liveScope);
    const payCt = await this.mongo.collection('vendor_payments').countDocuments(liveScope);
    if (expCt || payCt) {
      throw new HttpError(
        400,
        `Cannot delete VendorBill with linked live records (expenses=${expCt}, payments=${payCt}). ` +
          `Delete or reverse them first.`,
      );
    }

    const stamp = nowIso();
    await this.mongo.collection('vendor_bills').updateOne(
      { id: bid },
      {
        $set: {
          is_deleted: true,
          deleted_by: uid,
          deleted_at: stamp,
          deletion_reason: reason.trim(),
          modified_by: uid,
          modified_at: stamp,
        },
      },
    );
    await this.project(uid, cid, 'vendor_bill', bid);
    await this.logAudit(user, 'vendor_bill', 'delete', bid, str(doc['bill_number']), reason, {});
    return { ok: true };
  }

  // ── vendor payments ─────────────────────────────────────────────────────

  async createPayment(req: Request, vid: string, payload: Doc): Promise<Doc> {
    const { user, uid, cid } = await this.scope(req);
    const ven = await this.mongo
      .collection<Doc>('vendors')
      .findOne({ id: vid, user_id: uid, company_id: cid }, { projection: { _id: 0, name: 1 } });
    if (!ven) throw new HttpError(404, 'Vendor not found');

    // FastAPI validates the VendorPayment model BEFORE the handler runs, and
    // that model requires vendor_id — so a body without it is a 422 even though
    // the path already carries the id. The handler then overrides it with the
    // path value. Verified against live Python on 2026-09-21.
    const doc = paymentModelDump(payload);
    if (Number(doc['amount']) <= 0) throw new HttpError(400, 'Amount must be positive');

    if (doc['vendor_bill_id']) {
      const bill = await this.mongo.collection<Doc>('vendor_bills').findOne(
        {
          id: str(doc['vendor_bill_id']),
          user_id: uid,
          company_id: cid,
          is_deleted: { $ne: true },
        },
        { projection: { _id: 0, id: 1, vendor_id: 1 } },
      );
      if (!bill) throw new HttpError(400, 'Referenced vendor bill not found in tenant');
      if (str(bill['vendor_id']) !== vid) throw new HttpError(400, 'Bill belongs to a different vendor');
    }

    doc['id'] = doc['id'] || newId('vpay_');
    doc['vendor_id'] = vid;
    doc['user_id'] = uid;
    doc['company_id'] = cid;
    doc['created_by'] = uid;
    doc['created_at'] = nowIso();
    doc['is_deleted'] = false;

    // Iter150G beneficiary snapshot
    if (doc['bank_account_id']) {
      const pba = await this.mongo.collection<Doc>('party_bank_accounts').findOne(
        {
          id: str(doc['bank_account_id']),
          user_id: uid,
          party_type: 'vendor',
          party_id: vid,
          is_active: true,
        },
        { projection: { _id: 0 } },
      );
      if (!pba) {
        throw new HttpError(
          400,
          'Bank account is not active, belongs to another party, or is cross-tenant',
        );
      }
      doc['bank_snapshot'] = {
        bank_name: str(pba['bank_name']),
        masked_number: str(pba['masked_display']) || maskAccountNumber(str(pba['account_number'])),
        ifsc: str(pba['ifsc']),
        holder_name: str(pba['account_holder_name']),
      };
    } else {
      doc['bank_snapshot'] = {};
    }

    // Iter150H company source-bank snapshot
    if (doc['company_bank_account_id']) {
      const cba = await this.mongo
        .collection<Doc>('company_bank_accounts')
        .findOne(
          { id: str(doc['company_bank_account_id']), user_id: uid, company_id: cid, is_active: true },
          { projection: { _id: 0 } },
        );
      if (!cba) throw new HttpError(400, 'Company bank account is not active or is cross-tenant');
      doc['source_bank_snapshot'] = {
        bank_name: str(cba['bank_name']),
        masked_number: str(cba['masked_display']) || maskAccountNumber(str(cba['account_number'])),
        ifsc: str(cba['ifsc']),
        branch: str(cba['branch']),
        holder_name: str(cba['account_holder_name']),
      };
    } else {
      doc['source_bank_snapshot'] = {};
    }

    await this.mongo.collection('vendor_payments').insertOne({ ...doc });
    // Python order for payments: audit first, then hook.
    await this.logAudit(user, 'vendor_payment', 'create', str(doc['id']), str(ven['name']), '', {});
    await this.project(uid, cid, 'vendor_payment', str(doc['id']));

    const out: Doc = { ...doc };
    delete out['_id'];
    delete out['user_id'];
    return out;
  }

  async updatePayment(req: Request, vid: string, pid: string, payload: Doc): Promise<Doc> {
    const { user, uid, cid } = await this.scope(req);
    const before = await this.mongo
      .collection<Doc>('vendor_payments')
      .findOne({ id: pid, vendor_id: vid, user_id: uid, company_id: cid }, { projection: { _id: 0 } });
    if (!before) throw new HttpError(404, 'Payment not found');

    const dumped = paymentModelDump(payload);
    if (Number(dumped['amount']) <= 0) throw new HttpError(400, 'Amount must be positive');

    const patch: Doc = { ...dumped };
    for (const k of ['id', 'vendor_id', 'created_at', 'created_by', 'is_deleted', 'deleted_by', 'deleted_at', 'deletion_reason']) {
      delete patch[k];
    }
    patch['modified_by'] = uid;
    patch['modified_at'] = nowIso();

    await this.mongo.collection('vendor_payments').updateOne({ id: pid }, { $set: patch });
    const after = { ...before, ...patch };
    await this.logAudit(user, 'vendor_payment', 'update', pid, '', '', diffDict(before as Doc, after));
    await this.project(uid, cid, 'vendor_payment', pid);

    const out: Doc = { ...after };
    delete out['_id'];
    delete out['user_id'];
    return out;
  }

  async deletePayment(req: Request, vid: string, pid: string, reason: string): Promise<Doc> {
    const { user, uid, cid } = await this.scope(req);
    this.requireDeleteRole(user);
    const doc = await this.mongo
      .collection<Doc>('vendor_payments')
      .findOne({ id: pid, vendor_id: vid, user_id: uid, company_id: cid }, { projection: { _id: 0 } });
    if (!doc) throw new HttpError(404, 'Payment not found');

    await this.mongo.collection('vendor_payments').updateOne(
      { id: pid },
      {
        $set: {
          is_deleted: true,
          deleted_by: uid,
          deleted_at: nowIso(),
          deletion_reason: reason.trim(),
        },
      },
    );
    await this.logAudit(user, 'vendor_payment', 'delete', pid, '', reason, {});
    await this.project(uid, cid, 'vendor_payment', pid);
    return { ok: true };
  }
}
