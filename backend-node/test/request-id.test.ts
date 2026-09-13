import { describe, it, expect } from 'vitest';
import Fastify from 'fastify';
import { isSafeRequestId, resolveRequestId, registerRequestId } from '../src/request-id.js';

describe('request-id resolution', () => {
  it('accepts safe incoming IDs when trust is enabled', () => {
    const { id, source } = resolveRequestId('abc123-DEF_456', true);
    expect(source).toBe('incoming');
    expect(id).toBe('abc123-DEF_456');
  });

  it('rejects unsafe incoming IDs even when trust is enabled', () => {
    const { id, source } = resolveRequestId('bad id with spaces', true);
    expect(source).toBe('generated');
    expect(id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it('ignores incoming IDs when trust is disabled', () => {
    const { id, source } = resolveRequestId('abc123-DEF_456', false);
    expect(source).toBe('generated');
    expect(id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it('isSafeRequestId works as a type guard', () => {
    expect(isSafeRequestId('abcdef12')).toBe(true);
    expect(isSafeRequestId('short')).toBe(false);
    expect(isSafeRequestId(undefined)).toBe(false);
    expect(isSafeRequestId(123 as unknown)).toBe(false);
  });
});

describe('registerRequestId (Fastify hook)', () => {
  it('generates and echoes a request-id when not trusted', async () => {
    const app = Fastify();
    await registerRequestId(app, {
      requestIdHeader: 'x-request-id',
      trustIncomingRequestId: false,
    });
    app.get('/echo', async (req) => ({ id: req.requestId }));

    const res = await app.inject({ method: 'GET', url: '/echo' });
    expect(res.statusCode).toBe(200);
    const echoed = res.headers['x-request-id'];
    expect(typeof echoed).toBe('string');
    const body = res.json() as { id: string };
    expect(body.id).toBe(echoed);
    await app.close();
  });

  it('propagates safe incoming request-id when trusted', async () => {
    const app = Fastify();
    await registerRequestId(app, {
      requestIdHeader: 'x-request-id',
      trustIncomingRequestId: true,
    });
    app.get('/echo', async (req) => ({ id: req.requestId }));

    const res = await app.inject({
      method: 'GET',
      url: '/echo',
      headers: { 'x-request-id': 'trusted-id-123456' },
    });
    expect(res.statusCode).toBe(200);
    expect(res.headers['x-request-id']).toBe('trusted-id-123456');
    const body = res.json() as { id: string };
    expect(body.id).toBe('trusted-id-123456');
    await app.close();
  });

  it('generates a new request-id when incoming is unsafe even if trusted', async () => {
    const app = Fastify();
    await registerRequestId(app, {
      requestIdHeader: 'x-request-id',
      trustIncomingRequestId: true,
    });
    app.get('/echo', async (req) => ({ id: req.requestId }));

    const res = await app.inject({
      method: 'GET',
      url: '/echo',
      headers: { 'x-request-id': 'has spaces and <bad>' },
    });
    expect(res.statusCode).toBe(200);
    const echoed = res.headers['x-request-id'];
    expect(echoed).toMatch(/^[0-9a-f-]{36}$/);
    await app.close();
  });
});
