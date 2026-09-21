/** Applies the SQL in drizzle/ to the configured database. */
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import { Pool } from 'pg';
import { PG_URL } from './pg';

async function main(): Promise<void> {
  const pool = new Pool({ connectionString: PG_URL, max: 1 });
  await migrate(drizzle(pool), { migrationsFolder: `${__dirname}/../../drizzle` });
  await pool.end();
  console.log('migrations applied');
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
