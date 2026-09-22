import { Inject, Injectable } from '@nestjs/common';
import type { Request } from 'express';
import type { Db as MongoDb } from 'mongodb';
import { and, asc, desc, eq, ne, or, isNull, sql } from 'drizzle-orm';
import { db as pg } from '../db/pg';
import { vendorBill } from '../db/schema';
import { activeCompanyId, authenticate } from '../common/identity';
import { pyFloat, pyIsoTimestamp, type RawNumber } from '../common/py-json';
import { MONGO } from './vendors.service';

/**
 * GET /api/vendor-bills and /api/vendor-bills/{bid}, shadowing
 * backend/routers/vendor_bills.py::list_vendor_bills / get_vendor_bill.
 *
 * Preserved semantics:
 *   • base scope (user_id, company_id) plus `is_deleted != true`, which in
 *     Mongo also matches documents where the field is absent;
 *   • four optional equality filters, each applied only when truthy;
 *   • projection strips _id and user_id; sort bill_date DESC; cap 5,000;
 *   • detail miss is 404 {"detail":"VendorBill not found"}.
 *
 * All 5,736 bills share one key order, so the JSON shape is fixed here.
 */
const absent = (v: string | null): string => v ?? '';

export interface VendorBillJson {
  id: string;
  vendor_id: string;
  vendor_name: string;
  bill_number: string;
  bill_date: string;
  bill_amount: RawNumber | null;
  vehicle_id: string;
  vehicle_number: string;
  trip_id: string;
  repair_event_id: string;
  narration: string;
  remarks: string;
  file_ids: unknown;
  created_by: string;
  created_at: string;
  modified_by: string;
  modified_at: string;
  is_deleted: boolean;
  deleted_by: string;
  deleted_at: string;
  deletion_reason: string;
  company_id: string;
}

export function billToJson(r: typeof vendorBill.$inferSelect): VendorBillJson {
  return {
    id: r.id,
    vendor_id: r.vendorId,
    vendor_name: r.vendorName,
    bill_number: r.billNumber,
    bill_date: absent(r.billDate),
    bill_amount: pyFloat(r.billAmount),
    vehicle_id: r.vehicleId,
    vehicle_number: r.vehicleNumber,
    trip_id: r.tripId,
    repair_event_id: r.repairEventId,
    narration: r.narration,
    remarks: r.remarks,
    file_ids: r.fileIds,
    created_by: r.createdBy,
    created_at: absent(pyIsoTimestamp(r.createdAt)),
    modified_by: r.modifiedBy,
    modified_at: absent(pyIsoTimestamp(r.modifiedAt)),
    is_deleted: r.isDeleted,
    deleted_by: r.deletedBy,
    deleted_at: absent(pyIsoTimestamp(r.deletedAt)),
    deletion_reason: r.deletionReason,
    company_id: r.companyId,
  };
}

export interface BillFilters {
  vendor_id?: string;
  vehicle_id?: string;
  repair_event_id?: string;
  trip_id?: string;
}

@Injectable()
export class VendorBillsService {
  constructor(@Inject(MONGO) private readonly mongo: MongoDb) {}

  async list(req: Request, f: BillFilters): Promise<VendorBillJson[]> {
    const user = await authenticate(req, this.mongo);
    const cid = await activeCompanyId(req, user.user_id, this.mongo);

    const clauses = [
      eq(vendorBill.userId, user.user_id),
      eq(vendorBill.companyId, cid),
      // Mongo `$ne: true` also matches an absent field; the column is NOT NULL
      // with default false, so `is_deleted = false` is the faithful equivalent.
      ne(vendorBill.isDeleted, true),
    ];
    if (f.vendor_id) clauses.push(eq(vendorBill.vendorId, f.vendor_id));
    if (f.vehicle_id) clauses.push(eq(vendorBill.vehicleId, f.vehicle_id));
    if (f.repair_event_id) clauses.push(eq(vendorBill.repairEventId, f.repair_event_id));
    if (f.trip_id) clauses.push(eq(vendorBill.tripId, f.trip_id));

    const rows = await pg
      .select()
      .from(vendorBill)
      .where(and(...clauses))
      // Mongo sorts missing/null values first on a DESC sort of a string field;
      // Postgres puts NULLs last by default, hence NULLS FIRST here.
      .orderBy(sql`${vendorBill.billDate} DESC NULLS FIRST`, asc(vendorBill.sourceId))
      .limit(5000);
    return rows.map(billToJson);
  }

  async detail(req: Request, bid: string): Promise<VendorBillJson | null> {
    const user = await authenticate(req, this.mongo);
    const cid = await activeCompanyId(req, user.user_id, this.mongo);
    const rows = await pg
      .select()
      .from(vendorBill)
      .where(
        and(
          eq(vendorBill.id, bid),
          eq(vendorBill.userId, user.user_id),
          eq(vendorBill.companyId, cid),
          ne(vendorBill.isDeleted, true),
        ),
      )
      .limit(1);
    const row = rows[0];
    return row ? billToJson(row) : null;
  }
}

// re-exported so the module file stays small
export { and, desc, eq, or, isNull };
