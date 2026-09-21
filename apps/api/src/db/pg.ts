import { Pool } from 'pg';
import { drizzle } from 'drizzle-orm/node-postgres';
import * as schema from './schema';

/**
 * numeric/int8 come back as strings from node-postgres by default, which is
 * what we want for money: parsing them into JS floats would reintroduce the
 * rounding class of bug the numeric column exists to prevent.
 */
export const PG_URL = process.env.PG_URL ?? 'postgres://postgres@127.0.0.1:5433/trukvia';

/**
 * The session timezone must be UTC. Postgres renders `timestamptz` in the
 * session zone, so on an IST machine it would emit "+05:30" where Python emits
 * "+00:00" — a real parity break caught against live data on 2026-09-21.
 */
export const pool = new Pool({
  connectionString: PG_URL,
  max: 10,
  options: '-c timezone=UTC',
});
export const db = drizzle(pool, { schema });
export type Database = typeof db;
