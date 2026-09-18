/**
 * TRUKVIA · Phase-3 · Gate-7t · Class-C integrity remediation — Vitest.
 *
 * A. 6a–6d (Python GET-time writes) are deferred, not cutover-eligible.
 * B. Gate-4/5 POST writers are parked (deferred), and every allowlisted
 *    path is a GET-only registration.
 * C/D. /api/trips/export and /api/trips/recurring-suggestions are no longer
 *    captured by /api/trips/:tid (static precedence guards → 404 handler,
 *    no auth, no DB).
 * E. /api/trips/:tid behaves exactly as before.
 * F/G. Allowlist / deferred consistency: disjoint, duplicate-free, and in
 *    one-to-one correspondence with the `/api/...` literals in src/ (local
 *    mirror of the CI guard) and with live Fastify registrations.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Db } from 'mongodb';
import { buildApp } from '../src/app.js';
import { buildLogger } from '../src/logger.js';
import type { AppConfig } from '../src/config.js';
import type { MongoConn } from '../src/db.js';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const readList = (name: string): string[] =>
  readFileSync(join(ROOT, name), 'utf8').split(/\r?\n/).map((l) => l.trim()).filter((l) => l && !l.startsWith('#'));

function srcApiLiterals(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) out.push(...srcApiLiterals(p));
    else if (p.endsWith('.ts')) {
      for (const m of readFileSync(p, 'utf8').matchAll(/['"](\/api\/[^'"]*)['"]/g)) out.push(m[1] as string);
    }
  }
  return out;
}

const ALLOW = readList('.migration-allowlist');
const DEFERRED = readList('.migration-deferred');
const P1 = ['/api/trips', '/api/trips/:tid', '/api/invoices', '/api/invoices/:iid'];
const P2 = ['/api/saved-trip-filters', '/api/expenditure-types'];
const P3 = ['/api/trips/export', '/api/trips/recurring-suggestions'];
const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const;

const baseConfig: AppConfig = {
  nodeEnv: 'test', logLevel: 'silent', port: 0, host: '127.0.0.1',
  mongoUrl: 'mongodb://localhost:27017', dbName: 'trukvia_node_test',
  corsOrigins: [], requestIdHeader: 'x-request-id', trustIncomingRequestId: false,
};

type Row = Record<string, unknown>;
interface State { collections: string[]; writes: string[] }

function fakeDb(state: State): Db {
  const data: Record<string, Row[]> = {
    user_sessions: [{ session_token: 'tok-u1', user_id: 'u1', effective_role: 'owner',
      expires_at: new Date(Date.now() + 3600_000).toISOString() }],
    users: [{ user_id: 'u1', email: 'u1@x' }],
    companies: [{ id: 'co-a', user_id: 'u1', is_default: true }],
    trips: [{ id: 't1', user_id: 'u1', company_id: 'co-a', date: '2026-05-01', lr_number: 'LR-1' }],
  };
  const forbid = (n: string) => (): never => { state.writes.push(n); throw new Error(`WRITE ${n}`); };
  const collection = (name: string) => {
    state.collections.push(name);
    const rows = data[name] ?? [];
    return {
      findOne: vi.fn(async (f: Row, opts?: { projection?: Record<string, 0 | 1> }) => {
        const hit = rows.find((r) => Object.entries(f).every(([k, v]) => r[k] === v));
        if (!hit) return null;
        const o: Row = { ...hit };
        for (const [k, v] of Object.entries(opts?.projection ?? {})) if (v === 0) delete o[k];
        return o;
      }),
      insertOne: vi.fn(forbid(`${name}.insertOne`)), updateOne: vi.fn(forbid(`${name}.updateOne`)),
      updateMany: vi.fn(forbid(`${name}.updateMany`)), deleteOne: vi.fn(forbid(`${name}.deleteOne`)),
      createIndex: vi.fn(async () => 'ok'),
    };
  };
  return { collection: vi.fn(collection) } as unknown as Db;
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db: fakeDb(state), ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

describe('Gate-7t · Class-C integrity remediation', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = { collections: [], writes: [] }; app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  // ── A · P1 ─────────────────────────────────────────────────────────
  it('A1 6a–6d are NOT on the Class-C allowlist', () => {
    for (const p of P1) expect(ALLOW).not.toContain(p);
  });

  it('A2 6a–6d are recorded as deferred and remain registered (history preserved)', () => {
    for (const p of P1) {
      expect(DEFERRED).toContain(p);
      expect(app.hasRoute({ method: 'GET', url: p })).toBe(true);
    }
  });

  it('A3 6c/6d write-free siblings stay Class-C', () => {
    for (const p of ['/api/invoices/next-preview', '/api/invoices/overdue', '/api/invoices/:iid/notes', '/api/invoices/:iid/ship-to']) {
      expect(ALLOW).toContain(p);
    }
  });

  // ── B · P2 ─────────────────────────────────────────────────────────
  it('B1 Gate-4/5 writers are parked: deferred, not allowlisted, still POST-registered', () => {
    for (const p of P2) {
      expect(ALLOW).not.toContain(p);
      expect(DEFERRED).toContain(p);
      expect(app.hasRoute({ method: 'POST', url: p })).toBe(true);
    }
  });

  it('B2 every allowlisted path is a GET-only registration (no Node writer is cutover-eligible)', () => {
    for (const p of ALLOW) {
      expect(app.hasRoute({ method: 'GET', url: p }), p).toBe(true);
      for (const m of METHODS.filter((x) => x !== 'GET')) {
        expect(app.hasRoute({ method: m, url: p }), `${m} ${p}`).toBe(false);
      }
    }
  });

  // ── C / D · P3 precedence ──────────────────────────────────────────
  it.each(P3)('C/D %s is not captured by /api/trips/:tid → Fastify 404 handler, no auth, no DB', async (path) => {
    for (const headers of [{ authorization: 'Bearer tok-u1' }, {}]) {
      state.collections = [];
      const r = await app.inject({ method: 'GET', url: path, headers });
      expect(r.statusCode).toBe(404);
      expect(r.json()).toEqual({ message: `Route GET:${path} not found`, error: 'Not Found', statusCode: 404 });
      expect(r.json()).not.toEqual({ detail: 'Trip not found' });
      expect(state.collections).toEqual([]);
    }
  });

  it('C/D query strings on the guarded paths are also not captured', async () => {
    state.collections = []; // drop the app-startup idempotency index touch
    const r = await app.inject({ method: 'GET', url: '/api/trips/export?format=csv', headers: { authorization: 'Bearer tok-u1' } });
    expect(r.statusCode).toBe(404);
    expect(state.collections).toEqual([]);
  });

  // ── E · 6a unchanged ───────────────────────────────────────────────
  it('E1 /api/trips/:tid real trip → 200 same document as before', async () => {
    const r = await app.inject({ method: 'GET', url: '/api/trips/t1', headers: { authorization: 'Bearer tok-u1' } });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual({ id: 't1', company_id: 'co-a', date: '2026-05-01', lr_number: 'LR-1' });
    expect(state.collections).toContain('trips');
  });

  it('E2 /api/trips/:tid missing → 404 Trip not found; no auth → 401', async () => {
    const miss = await app.inject({ method: 'GET', url: '/api/trips/nope', headers: { authorization: 'Bearer tok-u1' } });
    expect(miss.statusCode).toBe(404);
    expect(miss.json()).toEqual({ detail: 'Trip not found' });
    const anon = await app.inject({ method: 'GET', url: '/api/trips/t1' });
    expect(anon.statusCode).toBe(401);
    expect(anon.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('E3 near-miss static names still reach :tid (Python has no such static routes)', async () => {
    for (const tid of ['exports', 'import', 'recurring']) {
      const r = await app.inject({ method: 'GET', url: `/api/trips/${tid}`, headers: { authorization: 'Bearer tok-u1' } });
      expect(r.json()).toEqual({ detail: 'Trip not found' });
    }
  });

  // ── F / G · consistency ────────────────────────────────────────────
  it('F1 allowlist and deferred lists are duplicate-free and disjoint', () => {
    expect(new Set(ALLOW).size).toBe(ALLOW.length);
    expect(new Set(DEFERRED).size).toBe(DEFERRED.length);
    expect(ALLOW.filter((p) => DEFERRED.includes(p))).toEqual([]);
  });

  it('F2 src /api literals ↔ allowlist ∪ deferred one-to-one (CI guard mirror, no stale entries)', () => {
    const lits = new Set(srcApiLiterals(join(ROOT, 'src')));
    const union = new Set([...ALLOW, ...DEFERRED]);
    expect([...lits].filter((l) => !union.has(l))).toEqual([]);
    expect([...union].filter((u) => !lits.has(u))).toEqual([]);
  });

  it('F3 every deferred path is live-registered; counts are exact', () => {
    for (const p of DEFERRED) {
      expect(METHODS.some((m) => app.hasRoute({ method: m, url: p })), p).toBe(true);
    }
    expect(ALLOW).toHaveLength(61); // 7u `/api/`, 7v gstin/lookup, 7x ai/sessions, 7y reminders/digest, 7z settlement-hint
    expect(DEFERRED).toEqual([...P1.slice(0, 1), P1[1], P1[2], P1[3], ...P2, ...P3]);
  });
});
