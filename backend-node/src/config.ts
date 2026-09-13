import { z } from 'zod';

/**
 * TRUKVIA Node backend — Phase 2 foundation config.
 *
 * All values come from environment variables. Missing/invalid values
 * MUST cause a fast, loud failure. Never silently default in production.
 *
 * NOTE: this foundation is isolated from the Python backend. It uses its
 * own NODE_* prefixed variables to avoid any collision with backend/.env.
 */

const trueSet = new Set(['1', 'true', 'yes', 'on']);
const falseSet = new Set(['0', 'false', 'no', 'off', '']);

const boolFromString = z
  .string()
  .transform((raw, ctx) => {
    const v = raw.trim().toLowerCase();
    if (trueSet.has(v)) return true;
    if (falseSet.has(v)) return false;
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: `Expected boolean-like value, got "${raw}"`,
    });
    return z.NEVER;
  });

const AppConfigSchema = z.object({
  nodeEnv: z.enum(['development', 'test', 'staging', 'production']),
  logLevel: z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent']),
  port: z.coerce.number().int().min(1).max(65535),
  host: z.string().min(1),
  mongoUrl: z.string().min(1).refine((u) => u.startsWith('mongodb://') || u.startsWith('mongodb+srv://'), {
    message: 'NODE_MONGO_URL must start with mongodb:// or mongodb+srv://',
  }),
  dbName: z.string().min(1).regex(/^[A-Za-z0-9_.-]+$/, {
    message: 'NODE_DB_NAME must be alphanumeric with _ . - only',
  }),
  corsOrigins: z.array(z.string()),
  requestIdHeader: z.string().min(1),
  trustIncomingRequestId: z.boolean(),
});

export type AppConfig = z.infer<typeof AppConfigSchema>;

function parseCorsOrigins(raw: string | undefined): string[] {
  if (!raw) return [];
  return raw
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const trustRaw = env['NODE_TRUST_INCOMING_REQUEST_ID'] ?? 'false';
  const trustParsed = boolFromString.safeParse(trustRaw);
  if (!trustParsed.success) {
    throw new ConfigError(
      `Invalid NODE_TRUST_INCOMING_REQUEST_ID: ${trustParsed.error.issues.map((i) => i.message).join('; ')}`,
    );
  }

  const raw = {
    nodeEnv: env['NODE_ENV'],
    logLevel: env['NODE_LOG_LEVEL'],
    port: env['NODE_PORT'],
    host: env['NODE_HOST'],
    mongoUrl: env['NODE_MONGO_URL'],
    dbName: env['NODE_DB_NAME'],
    corsOrigins: parseCorsOrigins(env['NODE_CORS_ORIGINS']),
    requestIdHeader: (env['NODE_REQUEST_ID_HEADER'] ?? 'x-request-id').toLowerCase(),
    trustIncomingRequestId: trustParsed.data,
  };

  const parsed = AppConfigSchema.safeParse(raw);
  if (!parsed.success) {
    const details = parsed.error.issues
      .map((i) => `${i.path.join('.') || '<root>'}: ${i.message}`)
      .join('; ');
    throw new ConfigError(`Invalid TRUKVIA Node config: ${details}`);
  }

  if (parsed.data.nodeEnv === 'production' && parsed.data.dbName.toLowerCase().includes('prod')) {
    // Foundation phase must NEVER connect to production DB. The Python
    // backend remains authoritative; the Node skeleton is dev-only.
    throw new ConfigError(
      'Refusing to boot: Node foundation is not allowed to target a production database in this phase.',
    );
  }

  return parsed.data;
}

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigError';
  }
}
