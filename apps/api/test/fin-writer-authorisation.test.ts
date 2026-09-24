/**
 * Gate 9h · U2 — the Finance-writer database authorisation guard.
 *
 * U2 found that `backend-node`'s "prod" substring guard does not protect
 * `apps/api`, which is the application that would actually become the ledger
 * writer. These tests pin the replacement: an explicit, exact-match
 * authorisation that fails closed in production.
 *
 * No real database name appears here. The fixtures are invented strings, and
 * the guard is asserted never to echo either value into its message.
 */
import { describe, expect, it } from 'vitest';
import {
  FIN_WRITER_ALLOWED_DB_ENV,
  FinanceWriterAuthorisationError,
  assertFinanceWriterAuthorised,
} from '../src/fin/writer-authorisation';

const LIVE = 'alpha_ledger_one';
const OTHER = 'alpha_ledger_two';

const call = (dbName: string, nodeEnv?: string, allowedDb?: string): void =>
  assertFinanceWriterAuthorised({ dbName, nodeEnv, allowedDb });

describe('production — fails closed without explicit authorisation', () => {
  it('refuses when the authorisation variable is absent', () => {
    expect(() => call(LIVE, 'production', undefined)).toThrow(FinanceWriterAuthorisationError);
  });

  it('refuses when the authorisation variable is empty or whitespace', () => {
    for (const v of ['', '   ', '\t']) {
      expect(() => call(LIVE, 'production', v)).toThrow(FinanceWriterAuthorisationError);
    }
  });

  it('names the variable to set, so the refusal is actionable', () => {
    expect(() => call(LIVE, 'production')).toThrow(new RegExp(FIN_WRITER_ALLOWED_DB_ENV));
  });
});

describe('production — the match must be exact, never a substring', () => {
  it('refuses a different database outright', () => {
    expect(() => call(LIVE, 'production', OTHER)).toThrow(FinanceWriterAuthorisationError);
  });

  it('refuses a PREFIX of the real name', () => {
    expect(() => call(LIVE, 'production', 'alpha_ledger')).toThrow(FinanceWriterAuthorisationError);
  });

  it('refuses a SUFFIX of the real name', () => {
    expect(() => call(LIVE, 'production', 'ledger_one')).toThrow(FinanceWriterAuthorisationError);
  });

  it('refuses a SUPERSTRING that merely contains the real name', () => {
    // The dangerous direction: a neighbouring database whose name embeds this
    // one would pass a substring check.
    expect(() => call(LIVE, 'production', `${LIVE}_backup`)).toThrow(FinanceWriterAuthorisationError);
  });

  it('refuses on case difference', () => {
    expect(() => call(LIVE, 'production', LIVE.toUpperCase())).toThrow(FinanceWriterAuthorisationError);
  });

  it('ALLOWS only the exact whole string', () => {
    expect(() => call(LIVE, 'production', LIVE)).not.toThrow();
  });

  it('tolerates surrounding whitespace in the configured value', () => {
    expect(() => call(LIVE, 'production', `  ${LIVE}  `)).not.toThrow();
  });
});

describe('local and preview keep working without authorisation', () => {
  it.each([undefined, '', 'development', 'test', 'preview', 'staging'])(
    'boots with NODE_ENV=%j and no authorisation set',
    (env) => {
      expect(() => call(LIVE, env as string | undefined, undefined)).not.toThrow();
    },
  );

  it('still catches a MISCONFIGURED non-production environment', () => {
    // Authorisation set but pointing elsewhere is a mistake anywhere, not just
    // in production.
    expect(() => call(LIVE, 'development', OTHER)).toThrow(FinanceWriterAuthorisationError);
  });

  it('allows a matching authorisation outside production too', () => {
    expect(() => call(LIVE, 'development', LIVE)).not.toThrow();
  });
});

describe('an absent database name is itself a refusal', () => {
  it.each(['', '   '])('refuses dbName %j', (db) => {
    expect(() => call(db, 'development', undefined)).toThrow(FinanceWriterAuthorisationError);
  });
});

describe('the refusal leaks neither name', () => {
  const grab = (fn: () => void): string => {
    try {
      fn();
    } catch (e) {
      return e instanceof Error ? `${e.message}` : String(e);
    }
    return '';
  };

  it('does not print the configured database name', () => {
    expect(grab(() => call(LIVE, 'production', OTHER))).not.toContain(LIVE);
    expect(grab(() => call(LIVE, 'production', undefined))).not.toContain(LIVE);
  });

  it('does not print the authorised database name', () => {
    expect(grab(() => call(LIVE, 'production', OTHER))).not.toContain(OTHER);
  });
});

describe('the guard is wired to the real writer startup path', () => {
  it('app.module.ts calls it in the Mongo provider, before connecting', async () => {
    const { readFile } = await import('node:fs/promises');
    const { join } = await import('node:path');
    const src = await readFile(join(process.cwd(), 'src', 'app.module.ts'), 'utf8');
    const callAt = src.indexOf('assertFinanceWriterAuthorised({');
    const connectAt = src.indexOf('new MongoClient(');
    expect(callAt).toBeGreaterThan(-1);
    expect(connectAt).toBeGreaterThan(-1);
    // The refusal must happen before a client is ever constructed.
    expect(callAt).toBeLessThan(connectAt);
  });
});
