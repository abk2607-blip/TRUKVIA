import { MongoClient, type Db, type MongoClientOptions } from 'mongodb';
import type { Logger } from 'pino';
import type { AppConfig } from './config.js';

/**
 * Minimal MongoDB connection layer for the Node foundation.
 *
 * Constraints (Phase 2 skeleton):
 *   - No schema mutation
 *   - No index creation on startup
 *   - No writes
 *   - Clean shutdown on SIGTERM/SIGINT (wired by the app owner)
 */

export interface MongoConn {
  client: MongoClient;
  db: Db;
  ping(): Promise<boolean>;
  close(): Promise<void>;
}

export interface MongoClientFactory {
  (url: string, opts: MongoClientOptions): Pick<MongoClient, 'connect' | 'db' | 'close'> & {
    db(name: string): Db;
  };
}

const defaultOptions: MongoClientOptions = {
  serverSelectionTimeoutMS: 5_000,
  connectTimeoutMS: 5_000,
  maxPoolSize: 10,
  retryWrites: false, // no writes in this phase
};

export async function connectMongo(
  cfg: Pick<AppConfig, 'mongoUrl' | 'dbName'>,
  logger: Pick<Logger, 'info' | 'error' | 'warn'>,
  factory: MongoClientFactory = ((url, opts) => new MongoClient(url, opts)) as MongoClientFactory,
): Promise<MongoConn> {
  const client = factory(cfg.mongoUrl, defaultOptions) as MongoClient;
  try {
    await client.connect();
  } catch (err) {
    logger.error({ err: serializeError(err) }, 'mongo_connect_failed');
    throw err;
  }
  const db = client.db(cfg.dbName);
  logger.info({ db: cfg.dbName }, 'mongo_connected');

  return {
    client,
    db,
    async ping(): Promise<boolean> {
      try {
        const res = await db.command({ ping: 1 });
        return res?.['ok'] === 1;
      } catch (err) {
        logger.warn({ err: serializeError(err) }, 'mongo_ping_failed');
        return false;
      }
    },
    async close(): Promise<void> {
      try {
        await client.close();
        logger.info('mongo_closed');
      } catch (err) {
        logger.warn({ err: serializeError(err) }, 'mongo_close_failed');
      }
    },
  };
}

function serializeError(err: unknown): { name: string; message: string } {
  if (err instanceof Error) return { name: err.name, message: err.message };
  return { name: 'UnknownError', message: String(err) };
}
