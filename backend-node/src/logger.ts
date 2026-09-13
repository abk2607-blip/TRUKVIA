import { pino, type Logger, type LoggerOptions } from 'pino';
import type { AppConfig } from './config.js';

/**
 * Structured logger for the TRUKVIA Node foundation.
 *
 * PII redaction: bank_account, pan, dl_number, aadhaar, password,
 * session/api tokens, and Authorization headers MUST NEVER be logged.
 */

const REDACT_PATHS: readonly string[] = [
  'password',
  '*.password',
  'req.headers.authorization',
  'req.headers.cookie',
  'req.headers["x-api-key"]',
  'headers.authorization',
  'headers.cookie',
  'headers["x-api-key"]',
  'body.password',
  'body.token',
  'body.session',
  'body.api_key',
  'body.apiKey',
  'body.bank_account',
  'body.bankAccount',
  'body.account_number',
  'body.accountNumber',
  'body.pan',
  'body.dl_number',
  'body.dlNumber',
  'body.aadhaar',
  'body.aadhar',
];

export interface RequestLogFields {
  request_id: string;
  tenant_id: string | null;
  actor_user_id: string | null;
  route: string;
  method: string;
  status: number;
  latency_ms: number;
}

export function buildLogger(cfg: Pick<AppConfig, 'logLevel' | 'nodeEnv'>): Logger {
  const opts: LoggerOptions = {
    level: cfg.logLevel,
    base: {
      service: 'trukvia-backend-node',
      env: cfg.nodeEnv,
    },
    redact: {
      paths: [...REDACT_PATHS],
      censor: '[REDACTED]',
      remove: false,
    },
    timestamp: pino.stdTimeFunctions.isoTime,
    formatters: {
      level(label) {
        return { level: label };
      },
    },
  };
  return pino(opts);
}

export type { Logger } from 'pino';
