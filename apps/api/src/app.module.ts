import { Module } from '@nestjs/common';
import { MongoClient } from 'mongodb';
import { VendorsController } from './vendors/vendors.controller';
import { VendorReadsController } from './vendors/vendor-reads.controller';
import { VendorWritesController } from './vendors/vendor-writes.controller';
import { VendorWritesService } from './vendors/vendor-writes.service';
import { VendorTxnWritesController } from './vendors/vendor-txn-writes.controller';
import { VendorTxnWritesService } from './vendors/vendor-txn-writes.service';
import { FinReadsController } from './fin/fin-reads.controller';
import { FinReadsService } from './fin/fin-reads.service';
import { FinWritesController } from './fin/fin-writes.controller';
import { FinWritesService } from './fin/fin-writes.service';
import { FinStatusReadsController } from './fin/fin-status-reads.controller';
import { FinStatusReadsService } from './fin/fin-status-reads.service';
import { InternalFinController } from './fin/internal-fin.controller';
import { MONGO, VendorsService } from './vendors/vendors.service';
import { VendorBillsService } from './vendors/vendor-bills.service';
import { VendorPaymentsService } from './vendors/vendor-payments.service';

/**
 * Slice 1a topology: vendor data comes from PostgreSQL, while sessions, users,
 * team_members and companies are still read from MongoDB, where Python remains
 * the writer. See docs/migration/PHASE6-SLICE1-VENDORS-NESTJS-POSTGRES.md.
 */
export const MONGO_URL = process.env.NEST_MONGO_URL ?? 'mongodb://127.0.0.1:27017';
export const MONGO_DB_NAME = process.env.NEST_MONGO_DB ?? 'trukvia_local_20260921';

@Module({
  controllers: [VendorsController, VendorReadsController, VendorWritesController, VendorTxnWritesController, FinReadsController, FinWritesController, FinStatusReadsController, InternalFinController],
  providers: [
    VendorsService,
    VendorBillsService,
    VendorPaymentsService,
    VendorWritesService,
    VendorTxnWritesService,
    FinReadsService,
    FinWritesService,
    FinStatusReadsService,
    {
      provide: MONGO,
      useFactory: async () => {
        const client = new MongoClient(MONGO_URL, { maxPoolSize: 10 });
        await client.connect();
        return client.db(MONGO_DB_NAME);
      },
    },
  ],
})
export class AppModule {}
