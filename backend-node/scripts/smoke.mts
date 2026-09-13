// One-shot manual smoke test — boots the app on 127.0.0.1:0, hits both
// health endpoints via real HTTP, prints results, and exits. Not part of
// the vitest suite. Not shipped.
import { buildApp } from '../src/app.js';
import { buildLogger } from '../src/logger.js';

const config = {
  nodeEnv: 'test' as const,
  logLevel: 'silent' as const,
  port: 0,
  host: '127.0.0.1',
  mongoUrl: 'mongodb://localhost:27017',
  dbName: 'trukvia_node_dev',
  corsOrigins: [] as string[],
  requestIdHeader: 'x-request-id',
  trustIncomingRequestId: false,
};
const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
const app = await buildApp({ config, logger, mongo: null });
await app.listen({ port: 0, host: '127.0.0.1' });
const addr = app.server.address();
if (!addr || typeof addr === 'string') throw new Error('no address');
const base = `http://127.0.0.1:${addr.port}`;

const live = await fetch(`${base}/health/live`);
console.log('LIVE_STATUS', live.status, 'BODY', await live.text(), 'REQID', live.headers.get('x-request-id'));

const ready = await fetch(`${base}/health/ready`);
console.log('READY_STATUS', ready.status, 'BODY', await ready.text(), 'REQID', ready.headers.get('x-request-id'));

await app.close();
process.exit(0);
