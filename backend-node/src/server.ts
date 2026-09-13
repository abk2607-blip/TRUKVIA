import { loadConfig, ConfigError } from './config.js';
import { buildLogger } from './logger.js';
import { connectMongo } from './db.js';
import { buildApp } from './app.js';

/**
 * Entrypoint for the TRUKVIA Node foundation.
 *
 * This process is NOT wired into supervisor or ingress in Phase 2.
 * It is used only for local verification and Vitest boot tests.
 */

async function main(): Promise<void> {
  let config;
  try {
    config = loadConfig();
  } catch (err) {
    // Fail loud, exit non-zero.
    console.error(err instanceof ConfigError ? err.message : err);
    process.exit(1);
  }

  const logger = buildLogger(config);
  logger.info({ env: config.nodeEnv, port: config.port }, 'boot_start');

  const mongo = await connectMongo(config, logger);
  const app = await buildApp({ config, logger, mongo });

  const shutdown = async (signal: string): Promise<void> => {
    logger.info({ signal }, 'shutdown_start');
    try {
      await app.close();
    } finally {
      await mongo.close();
      logger.info('shutdown_complete');
      process.exit(0);
    }
  };
  process.on('SIGTERM', () => void shutdown('SIGTERM'));
  process.on('SIGINT', () => void shutdown('SIGINT'));

  try {
    await app.listen({ port: config.port, host: config.host });
  } catch (err) {
    logger.error({ err }, 'listen_failed');
    await mongo.close();
    process.exit(1);
  }
}

void main();
