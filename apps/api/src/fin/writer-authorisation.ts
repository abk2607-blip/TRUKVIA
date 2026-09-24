/**
 * Finance-writer database authorisation — fail closed.
 *
 * `apps/api` is the application that would become the ledger WRITER under
 * Gate 9h. It is a different application from `backend-node`, whose
 * `config.ts` refuses to boot when the database name contains "prod". That
 * guard does not protect this one: a check in another codebase is not a
 * control here, and relying on it was the gap U2 exposed.
 *
 * It is also the wrong shape. Matching a substring of a name asks "does this
 * look like production?", which fails the moment a database is called
 * something else. This asks the only question that matters:
 *
 *     has someone explicitly authorised THIS database for Finance writes?
 *
 * Authorisation is an exact, whole-string match against
 * `TRUKVIA_FIN_WRITER_ALLOWED_DB`. No substring, no prefix, no pattern.
 *
 *   production          : authorisation REQUIRED, and it must match exactly.
 *                         Absent or mismatched -> refuse to boot.
 *   anything else       : allowed without authorisation, so local and preview
 *                         work unchanged -- but if the variable IS set it must
 *                         still match, so a misconfigured environment pointing
 *                         at the wrong database is caught rather than trusted.
 *
 * Neither the configured name nor the authorised name appears in the error,
 * the message or any log. The operator already knows both; an error string is
 * the wrong place for either.
 */

export const FIN_WRITER_ALLOWED_DB_ENV = 'TRUKVIA_FIN_WRITER_ALLOWED_DB';

export class FinanceWriterAuthorisationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'FinanceWriterAuthorisationError';
  }
}

export interface WriterAuthorisationInput {
  /** The database the writer is about to open. */
  dbName: string;
  /** Defaults to process.env.NODE_ENV. */
  nodeEnv?: string;
  /** Defaults to process.env[FIN_WRITER_ALLOWED_DB_ENV]. */
  allowedDb?: string;
}

/**
 * Throws unless this database is authorised for Finance writes.
 *
 * Called from the Mongo provider in app.module.ts, which is the single place
 * the writer obtains its database, so every write path is covered by one
 * check at startup rather than by a check per route.
 */
export function assertFinanceWriterAuthorised(input: WriterAuthorisationInput): void {
  const dbName = (input.dbName ?? '').trim();
  const nodeEnv = (input.nodeEnv ?? process.env['NODE_ENV'] ?? '').trim().toLowerCase();
  const allowedDb = (input.allowedDb ?? process.env[FIN_WRITER_ALLOWED_DB_ENV] ?? '').trim();

  if (!dbName) {
    throw new FinanceWriterAuthorisationError(
      'Refusing to boot: no database name is configured for the Finance writer.',
    );
  }

  const isProduction = nodeEnv === 'production';

  if (isProduction && !allowedDb) {
    throw new FinanceWriterAuthorisationError(
      `Refusing to boot: Finance writes are not authorised for this database. ` +
        `Set ${FIN_WRITER_ALLOWED_DB_ENV} to the exact database name this deployment may write to. ` +
        `This is deliberate — the writer fails closed in production until a named database is authorised.`,
    );
  }

  // An exact, whole-string comparison. A substring or prefix match would let a
  // neighbouring database through, which is precisely the weakness this
  // replaces.
  if (allowedDb && allowedDb !== dbName) {
    throw new FinanceWriterAuthorisationError(
      `Refusing to boot: the configured database is not the one authorised for Finance writes. ` +
        `${FIN_WRITER_ALLOWED_DB_ENV} must equal the database name exactly. ` +
        `(Neither value is printed here on purpose.)`,
    );
  }
}
