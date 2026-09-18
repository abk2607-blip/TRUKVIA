/**
 * TRUKVIA · Phase-3 · Gate-7v · GSTIN offline lookup read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/gstin/lookup
 *
 * Fake-DB write-forbid pattern inlined. The handler must touch NOTHING
 * beyond authentication (user_sessions / users): every other collection
 * access is recorded and asserted empty.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { Db } from 'mongodb';
import { buildApp } from '../src/app.js';
import { buildLogger } from '../src/logger.js';
import type { AppConfig } from '../src/config.js';
import type { MongoConn } from '../src/db.js';

const baseConfig: AppConfig = {
  nodeEnv: 'test', logLevel: 'silent', port: 0, host: '127.0.0.1',
  mongoUrl: 'mongodb://localhost:27017', dbName: 'trukvia_node_test',
  corsOrigins: [], requestIdHeader: 'x-request-id', trustIncomingRequestId: false,
};

const IN_FUTURE = (): string => new Date(Date.now() + 3600_000).toISOString();

type Row = Record<string, unknown>;
interface State { sessions: Row[]; users: Row[]; writes: string[]; touched: string[] }

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function fakeDb(state: State): Db {
  const collection = (name: string) => {
    const auth = name === 'user_sessions' || name === 'users' || name === 'team_members'; // Gate 9b: auth reads
    const rows = name === 'user_sessions' ? state.sessions : name === 'users' ? state.users : [];
    return {
      find: vi.fn(() => { state.touched.push(`${name}.find`); throw new Error(`unexpected find on ${name}`); }),
      findOne: vi.fn(async (f: Row) => {
        if (!auth) state.touched.push(`${name}.findOne`);
        return rows.find((r) => Object.entries(f).every(([k, v]) => r[k] === v)) ?? null;
      }),
      countDocuments: vi.fn(async () => { state.touched.push(`${name}.countDocuments`); return 0; }),
      aggregate: vi.fn(() => { state.touched.push(`${name}.aggregate`); throw new Error('unexpected aggregate'); }),
      insertOne: vi.fn(forbid(state, `${name}.insertOne`)),
      updateOne: vi.fn(forbid(state, `${name}.updateOne`)),
      updateMany: vi.fn(forbid(state, `${name}.updateMany`)),
      deleteOne: vi.fn(forbid(state, `${name}.deleteOne`)),
      deleteMany: vi.fn(forbid(state, `${name}.deleteMany`)),
      insertMany: vi.fn(forbid(state, `${name}.insertMany`)),
      replaceOne: vi.fn(forbid(state, `${name}.replaceOne`)),
      findOneAndUpdate: vi.fn(forbid(state, `${name}.findOneAndUpdate`)),
      findOneAndDelete: vi.fn(forbid(state, `${name}.findOneAndDelete`)),
      findOneAndReplace: vi.fn(forbid(state, `${name}.findOneAndReplace`)),
      bulkWrite: vi.fn(forbid(state, `${name}.bulkWrite`)),
      createIndex: vi.fn(async () => 'ok'),
    };
  };
  return { collection: vi.fn(collection) } as unknown as Db;
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const U1 = { authorization: 'Bearer tok-u1' };
const P = '/api/gstin/lookup';
const NOTE =
  'Offline parse only. Full name/address needs a paid GSTIN API (Signzy/ClearTax). Configure GSTIN_LOOKUP_API_KEY to enable.';
const V1 = '27AAPFU0939F1ZV';

const body = (o: Row): string => JSON.stringify({
  gstin: '', valid_format: false, checksum_ok: false, state_code: '', state: '', pan: '', entity_code: '',
  source: 'offline_parse', legal_name: null, trade_name: null, address: null, note: NOTE, ...o,
});
const V1_BODY = body({
  gstin: V1, valid_format: true, checksum_ok: true, state_code: '27', state: 'Maharashtra',
  pan: 'AAPFU0939F', entity_code: '1',
});

describe('Gate-7v · GSTIN offline lookup read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  let savedKey: string | undefined;
  beforeEach(async () => {
    savedKey = process.env['GSTIN_LOOKUP_API_KEY'];
    delete process.env['GSTIN_LOOKUP_API_KEY'];
    state = {
      sessions: [{ session_token: 'tok-u1', user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() }],
      users: [{ user_id: 'u1', email: 'u1@x' }],
      writes: [], touched: [],
    };
    app = await makeApp(state);
  });
  afterEach(async () => {
    if (savedKey === undefined) delete process.env['GSTIN_LOOKUP_API_KEY'];
    else process.env['GSTIN_LOOKUP_API_KEY'] = savedKey;
    expect(state.writes).toEqual([]);
    expect(state.touched).toEqual([]);
    await app.close();
  });

  const get = (qs: string, headers: Record<string, string> = U1): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: P + qs, headers });

  it('valid GSTIN → exact bytes, exact application/json', async () => {
    const r = await get(`?gstin=${V1}`);
    expect(r.statusCode).toBe(200);
    expect(r.headers['content-type']).toBe('application/json');
    expect(r.payload).toBe(V1_BODY);
    expect(r.headers['content-length']).toBe(String(Buffer.byteLength(V1_BODY)));
  });

  it('401 precedes the missing-param 422 and the empty 400', async () => {
    for (const qs of ['', '?gstin=', `?gstin=${V1}`]) {
      const r = await get(qs, {});
      expect(r.statusCode).toBe(401);
      expect(r.headers['content-type']).toBe('application/json');
    }
  });

  it('missing gstin → FastAPI 422 missing envelope', async () => {
    for (const qs of ['', '?', '?other=1', `?gstin[]=${V1}`, `?gstin+=${V1}`]) {
      const r = await get(qs);
      expect(r.statusCode, qs).toBe(422);
      expect(r.payload).toBe(
        '{"detail":[{"type":"missing","loc":["query","gstin"],"msg":"Field required","input":null,' +
          '"url":"https://errors.pydantic.dev/2.13/v/missing"}]}',
      );
    }
  });

  it('empty after normalisation → 400 GSTIN is required', async () => {
    for (const qs of ['?gstin=', '?gstin', '?gstin=%20%20', '?gstin=+++', '?gstin=%09%0A%1C%1F%C2%85%E3%80%80',
      `?gstin=${V1}&gstin=`]) {
      const r = await get(qs);
      expect(r.statusCode, qs).toBe(400);
      expect(r.payload).toBe('{"detail":"GSTIN is required"}');
    }
  });

  it('normalisation: py strip/upper, ASCII-space removal, last repeated key, encoded key', async () => {
    for (const qs of [`?gstin=${V1.toLowerCase()}`, '?gstin=27%20AAPFU%200939F%201ZV', '?gstin=27+AAPFU+0939F+1ZV',
      `?gstin=%09%20${V1}%0A%0D%C2%85`, `?gstin=AAA&gstin=${V1}`, `?&&gst%69n=${V1}&&`, `?=x&gstin=${V1}`]) {
      const r = await get(qs);
      expect(r.payload, qs).toBe(V1_BODY);
    }
  });

  it('BOM is not Python whitespace; internal newline survives; ß → SS', async () => {
    expect((await get('?gstin=%EF%BB%BF')).payload).toBe(body({ gstin: '﻿' }));
    expect((await get('?gstin=27AAPFU0939F1Z%0AV')).payload).toBe(body({ gstin: '27AAPFU0939F1Z\nV' }));
    expect((await get('?gstin=27AAPFU0939F1Z%C3%9F')).payload).toBe(body({ gstin: '27AAPFU0939F1ZSS' }));
    expect(JSON.parse((await get('?gstin=27AAPFU0939F%C4%B1ZV')).payload).gstin).toBe('27AAPFU0939FIZV');
  });

  it('post-Unicode-14 lowercase letters stay unchanged (CPython 3.11 upper)', async () => {
    const r = await get('?gstin=%C6%9B%C9%A4%E1%B2%8A%EA%9F%8D%F0%90%B5%B0%F0%96%BA%BB');
    expect(JSON.parse(r.payload).gstin).toBe('ƛɤᲊꟍ\u{10D70}\u{16EBB}');
  });

  it('Python unquote: invalid escapes kept, invalid UTF-8 → U+FFFD', async () => {
    const g = async (qs: string): Promise<string> => JSON.parse((await get(qs)).payload).gstin as string;
    expect(await g('?gstin=%zz27')).toBe('%ZZ27');
    expect(await g('?gstin=abc%')).toBe('ABC%');
    expect(await g('?gstin=abc%4')).toBe('ABC%4');
    expect(await g('?gstin=%C3')).toBe('�');
    expect(await g('?gstin=%ED%A0%80')).toBe('���');
    expect(await g('?gstin=%26%3D%3F')).toBe('&=?');
  });

  it('format / checksum branches', async () => {
    expect((await get('?gstin=27AAPFU0939F1ZW')).payload).toBe(body({
      gstin: '27AAPFU0939F1ZW', valid_format: true, checksum_ok: false, state_code: '27', state: 'Maharashtra',
      pan: 'AAPFU0939F', entity_code: '1',
    }));
    for (const bad of ['27AAPFU0939F1YV', '27AAPFU0939F1Z', `${V1}X`, '27AAPF10939F1ZV']) {
      expect((await get(`?gstin=${bad}`)).payload, bad).toBe(body({ gstin: bad }));
    }
  });

  it('state table incl. overrides; unknown codes → ""', async () => {
    const state = async (g: string): Promise<string> => JSON.parse((await get(`?gstin=${g}`)).payload).state as string;
    expect(await state('26AAPFU0939F1ZV')).toBe('Dadra and Nagar Haveli and Daman and Diu');
    expect(await state('35AAPFU0939F1ZV')).toBe('Andaman and Nicobar Islands');
    expect(await state('01AAPFU0939F1ZV')).toBe('Jammu and Kashmir');
    expect(await state('07AAPFU0939F1ZV')).toBe('Delhi');
    for (const c of ['00', '25', '28', '39', '97', '99']) expect(await state(`${c}AAPFU0939F1ZV`), c).toBe('');
  });

  it('note is null when GSTIN_LOOKUP_API_KEY is set (read per request)', async () => {
    process.env['GSTIN_LOOKUP_API_KEY'] = 'k';
    expect(JSON.parse((await get(`?gstin=${V1}`)).payload).note).toBeNull();
    process.env['GSTIN_LOOKUP_API_KEY'] = '';
    expect(JSON.parse((await get(`?gstin=${V1}`)).payload).note).toBe(NOTE);
  });

  it('HEAD → 405 allow: GET, before auth', async () => {
    for (const headers of [U1, {}]) {
      const r = await app.inject({ method: 'HEAD', url: `${P}?gstin=${V1}`, headers });
      expect(r.statusCode).toBe(405);
      expect(r.headers['allow']).toBe('GET');
      expect(r.headers['content-type']).toBe('application/json');
      expect(r.headers['content-length']).toBe('31');
    }
  });
});
