import { describe, it, expect, vi } from 'vitest';
import type { Db, MongoClient, MongoClientOptions } from 'mongodb';
import { connectMongo, type MongoClientFactory } from '../src/db.js';
import { buildLogger } from '../src/logger.js';

function fakeDb(commandImpl: () => Promise<unknown>): Db {
  return { command: vi.fn(commandImpl) } as unknown as Db;
}

function makeFactory(opts: {
  connectImpl?: () => Promise<void>;
  db: Db;
  closeImpl?: () => Promise<void>;
}): { factory: MongoClientFactory; connect: ReturnType<typeof vi.fn>; close: ReturnType<typeof vi.fn> } {
  const connect = vi.fn(opts.connectImpl ?? (async () => undefined));
  const close = vi.fn(opts.closeImpl ?? (async () => undefined));
  const factory: MongoClientFactory = (_url: string, _opts: MongoClientOptions) => {
    return {
      connect,
      db: (_name: string) => opts.db,
      close,
    } as unknown as MongoClient;
  };
  return { factory, connect, close };
}

const cfg = { mongoUrl: 'mongodb://localhost:27017', dbName: 'trukvia_node_dev' };
const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });

describe('connectMongo', () => {
  it('connects, pings ok, and closes cleanly', async () => {
    const db = fakeDb(async () => ({ ok: 1 }));
    const { factory, connect, close } = makeFactory({ db });

    const conn = await connectMongo(cfg, logger, factory);
    expect(connect).toHaveBeenCalledOnce();

    const ok = await conn.ping();
    expect(ok).toBe(true);

    await conn.close();
    expect(close).toHaveBeenCalledOnce();
  });

  it('surfaces connect failure', async () => {
    const db = fakeDb(async () => ({ ok: 1 }));
    const { factory } = makeFactory({
      db,
      connectImpl: async () => {
        throw new Error('boom');
      },
    });
    await expect(connectMongo(cfg, logger, factory)).rejects.toThrow(/boom/);
  });

  it('reports ping failure as false without throwing', async () => {
    const db = fakeDb(async () => {
      throw new Error('ping-boom');
    });
    const { factory } = makeFactory({ db });
    const conn = await connectMongo(cfg, logger, factory);
    const ok = await conn.ping();
    expect(ok).toBe(false);
  });
});
