import type { Config } from 'drizzle-kit';

export default {
  schema: './src/db/schema.ts',
  out: './drizzle',
  dialect: 'postgresql',
  dbCredentials: {
    url: process.env.PG_URL ?? 'postgres://postgres@127.0.0.1:5433/trukvia',
  },
} satisfies Config;
