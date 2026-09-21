import { Module } from '@nestjs/common';
import { MongoClient } from 'mongodb';
import { VendorsController } from './vendors/vendors.controller';
import { MONGO, VendorsService } from './vendors/vendors.service';

/**
 * Slice 1a topology: vendor data comes from PostgreSQL, while sessions, users,
 * team_members and companies are still read from MongoDB, where Python remains
 * the writer. See docs/migration/PHASE6-SLICE1-VENDORS-NESTJS-POSTGRES.md.
 */
export const MONGO_URL = process.env.NEST_MONGO_URL ?? 'mongodb://127.0.0.1:27017';
export const MONGO_DB_NAME = process.env.NEST_MONGO_DB ?? 'trukvia_local_20260921';

@Module({
  controllers: [VendorsController],
  providers: [
    VendorsService,
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
