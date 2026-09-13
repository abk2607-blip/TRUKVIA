import { describe, it, expect } from 'vitest';
import { loadConfig, ConfigError } from '../src/config.js';

function baseEnv(): NodeJS.ProcessEnv {
  return {
    NODE_ENV: 'development',
    NODE_LOG_LEVEL: 'info',
    NODE_PORT: '8801',
    NODE_HOST: '127.0.0.1',
    NODE_MONGO_URL: 'mongodb://localhost:27017',
    NODE_DB_NAME: 'trukvia_node_dev',
    NODE_CORS_ORIGINS: 'http://a.example.com, http://b.example.com',
    NODE_REQUEST_ID_HEADER: 'x-request-id',
    NODE_TRUST_INCOMING_REQUEST_ID: 'false',
  };
}

describe('loadConfig', () => {
  it('parses a valid environment', () => {
    const cfg = loadConfig(baseEnv());
    expect(cfg.nodeEnv).toBe('development');
    expect(cfg.port).toBe(8801);
    expect(cfg.host).toBe('127.0.0.1');
    expect(cfg.mongoUrl).toBe('mongodb://localhost:27017');
    expect(cfg.dbName).toBe('trukvia_node_dev');
    expect(cfg.corsOrigins).toEqual(['http://a.example.com', 'http://b.example.com']);
    expect(cfg.requestIdHeader).toBe('x-request-id');
    expect(cfg.trustIncomingRequestId).toBe(false);
  });

  it('coerces boolean-like values', () => {
    const env = baseEnv();
    env.NODE_TRUST_INCOMING_REQUEST_ID = 'true';
    const cfg = loadConfig(env);
    expect(cfg.trustIncomingRequestId).toBe(true);
  });

  it('fails fast when NODE_MONGO_URL is missing', () => {
    const env = baseEnv();
    delete env.NODE_MONGO_URL;
    expect(() => loadConfig(env)).toThrow(ConfigError);
  });

  it('fails fast when NODE_MONGO_URL has bad scheme', () => {
    const env = baseEnv();
    env.NODE_MONGO_URL = 'http://not-a-mongo-url';
    expect(() => loadConfig(env)).toThrow(/mongodb:\/\//);
  });

  it('fails fast when NODE_PORT is not numeric', () => {
    const env = baseEnv();
    env.NODE_PORT = 'not-a-number';
    expect(() => loadConfig(env)).toThrow(ConfigError);
  });

  it('fails fast when NODE_ENV is invalid', () => {
    const env = baseEnv();
    env.NODE_ENV = 'banana';
    expect(() => loadConfig(env)).toThrow(ConfigError);
  });

  it('rejects production dbName containing "prod" in production env', () => {
    const env = baseEnv();
    env.NODE_ENV = 'production';
    env.NODE_DB_NAME = 'trukvia_prod';
    expect(() => loadConfig(env)).toThrow(/production database/i);
  });

  it('rejects an invalid boolean for NODE_TRUST_INCOMING_REQUEST_ID', () => {
    const env = baseEnv();
    env.NODE_TRUST_INCOMING_REQUEST_ID = 'maybe';
    expect(() => loadConfig(env)).toThrow(ConfigError);
  });
});
