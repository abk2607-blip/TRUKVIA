import { Inject, Injectable } from '@nestjs/common';
import type { Request } from 'express';
import type { Db as MongoDb } from 'mongodb';
import { and, asc, eq, or, sql } from 'drizzle-orm';
import { db as pg } from '../db/pg';
import { vendor } from '../db/schema';
import { activeCompanyId, authenticate } from '../common/identity';
import { pyFloat, pyIsoTimestamp, type RawNumber } from '../common/py-json';

/**
 * The source stores "no timestamp yet" as an EMPTY STRING, not null: all 2,177
 * vendors have modified_at = "" and deactivated_at = "". Postgres models that
 * absence as NULL, so the API layer renders NULL back as "" to keep the
 * contract the UI already depends on.
 */
const absentAsEmpty = (v: string | null): string => v ?? '';

export const MONGO = 'MONGO_DB';

/**
 * Field order matters: FastAPI serialises the Mongo document, so the JSON key
 * order is the document's field order. This is that order with `_id` and
 * `user_id` removed, taken from the production data.
 */
type VendorRow = typeof vendor.$inferSelect;

export interface VendorJson {
  id: string;
  name: string;
  contact_person: string;
  mobile: string;
  alt_mobile: string;
  address: string;
  state: string;
  city: string;
  gst_in: string;
  pan: string;
  msme_number: string;
  bank_name: string;
  account_number: string;
  ifsc: string;
  branch: string;
  payment_terms: string;
  opening_balance: RawNumber | null;
  opening_balance_type: string;
  remarks: string;
  is_active: boolean;
  created_by: string;
  created_at: string;
  modified_by: string;
  modified_at: string;
  deactivated_by: string;
  deactivated_at: string;
  deactivation_reason: string;
  imported_from: string;
  imported_ref: string;
  imported_batch: string;
  is_historical: boolean;
  company_id: string;
}

export function toJson(r: VendorRow): VendorJson {
  return {
    id: r.id,
    name: r.name,
    contact_person: r.contactPerson,
    mobile: r.mobile,
    alt_mobile: r.altMobile,
    address: r.address,
    state: r.state,
    city: r.city,
    gst_in: r.gstIn,
    pan: r.pan,
    msme_number: r.msmeNumber,
    bank_name: r.bankName,
    account_number: r.accountNumber,
    ifsc: r.ifsc,
    branch: r.branch,
    payment_terms: r.paymentTerms,
    opening_balance: pyFloat(r.openingBalance),
    opening_balance_type: r.openingBalanceType,
    remarks: r.remarks,
    is_active: r.isActive,
    created_by: r.createdBy,
    created_at: absentAsEmpty(pyIsoTimestamp(r.createdAt)),
    modified_by: r.modifiedBy,
    modified_at: absentAsEmpty(pyIsoTimestamp(r.modifiedAt)),
    deactivated_by: r.deactivatedBy,
    deactivated_at: absentAsEmpty(pyIsoTimestamp(r.deactivatedAt)),
    deactivation_reason: r.deactivationReason,
    imported_from: r.importedFrom,
    imported_ref: r.importedRef,
    imported_batch: r.importedBatch,
    is_historical: r.isHistorical,
    company_id: r.companyId,
  };
}

@Injectable()
export class VendorsService {
  constructor(@Inject(MONGO) private readonly mongo: MongoDb) {}

  async list(
    req: Request,
    opts: { q?: string; activeOnly: boolean },
  ): Promise<VendorJson[]> {
    const user = await authenticate(req, this.mongo);
    const cid = await activeCompanyId(req, user.user_id, this.mongo);

    const clauses = [eq(vendor.userId, user.user_id), eq(vendor.companyId, cid)];
    if (opts.activeOnly) clauses.push(eq(vendor.isActive, true));
    if (opts.q) {
      // Mongo $regex with "i" evaluates a regular expression server-side.
      // Postgres `~*` is a case-insensitive POSIX regex match — the closest
      // equivalent. Patterns valid in both engines behave identically; PCRE-only
      // syntax (lookaround, \d inside classes) would not. Tracked in the slice
      // design doc as a documented divergence.
      const pattern = opts.q;
      clauses.push(
        or(
          sql`${vendor.name} ~* ${pattern}`,
          sql`${vendor.mobile} ~* ${pattern}`,
          sql`${vendor.contactPerson} ~* ${pattern}`,
        )!,
      );
    }

    const rows = await pg
      .select()
      .from(vendor)
      .where(and(...clauses))
      .orderBy(asc(vendor.name))
      .limit(20000);

    return rows.map(toJson);
  }

  async detail(req: Request, vid: string): Promise<VendorJson | null> {
    const user = await authenticate(req, this.mongo);
    const cid = await activeCompanyId(req, user.user_id, this.mongo);
    const rows = await pg
      .select()
      .from(vendor)
      .where(
        and(eq(vendor.id, vid), eq(vendor.userId, user.user_id), eq(vendor.companyId, cid)),
      )
      .limit(1);
    const row = rows[0];
    return row ? toJson(row) : null;
  }
}
