import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import Ajv2020, { type ValidateFunction, type ErrorObject } from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';

/**
 * OpenAPI contract-test foundation.
 *
 * Loads the FROZEN Phase-1 contract at `docs/contracts/openapi.v1.json`
 * (never modified by this module) and exposes a small validator around
 * Ajv 2020 (JSON Schema draft-2020-12, which OpenAPI 3.1 aligns with).
 *
 * Purpose: once Node routes begin migrating in a later gate, every
 * response body will be validated against its declared schema, and any
 * drift will fail CI. No routes exist yet, so this module only ships
 * loader + validator plumbing — no business logic.
 */

export interface OpenApiSpec {
  openapi: string;
  info: { title: string; version: string };
  paths: Record<string, unknown>;
  components?: {
    schemas?: Record<string, unknown>;
  };
}

export interface LoadedContract {
  spec: OpenApiSpec;
  ajv: Ajv2020;
}

export interface ValidationResult {
  ok: boolean;
  errors: ErrorObject[];
}

const CONTRACT_ID = 'https://trukvia.local/contracts/openapi.v1.json';

export function defaultContractPath(): string {
  // repo-root/docs/contracts/openapi.v1.json (relative to backend-node/)
  return resolve(import.meta.dirname, '..', '..', '..', 'docs', 'contracts', 'openapi.v1.json');
}

export function loadContract(path: string = defaultContractPath()): LoadedContract {
  const raw = readFileSync(path, 'utf-8');
  const spec = JSON.parse(raw) as OpenApiSpec;
  if (typeof spec.openapi !== 'string' || !spec.openapi.startsWith('3.')) {
    throw new ContractError(`Not an OpenAPI 3.x document: openapi=${String(spec.openapi)}`);
  }
  if (typeof spec.paths !== 'object' || spec.paths === null) {
    throw new ContractError('OpenAPI document has no paths object');
  }

  const ajv = new Ajv2020({
    allErrors: true,
    strict: false, // OpenAPI adds keywords Ajv does not know (nullable, discriminator, etc.)
    validateFormats: true,
  });
  // `ajv-formats` is typed against a different Ajv package copy that Fastify
  // pins transitively via `@fastify/ajv-compiler`. Wrapping the callable in
  // a function type with `unknown` parameters lets both TSC and ESLint agree
  // — no `any` leak, no eslint-disable, no runtime effect.
  const applyFormats = addFormats as unknown as (a: unknown) => void;
  applyFormats(ajv);

  // Register the entire spec so that $ref values like
  // "#/components/schemas/Foo" resolve inside the same document.
  ajv.addSchema(spec, CONTRACT_ID);

  return { spec, ajv };
}

/**
 * Validate `data` against the schema found at `refPath` inside the loaded
 * contract, e.g. `#/components/schemas/Trip`.
 */
export function validateAgainstRef(
  loaded: LoadedContract,
  refPath: string,
  data: unknown,
): ValidationResult {
  if (!refPath.startsWith('#/')) {
    throw new ContractError(`refPath must start with "#/": ${refPath}`);
  }
  const compiled: ValidateFunction = loaded.ajv.compile({ $ref: `${CONTRACT_ID}${refPath}` });
  const ok = compiled(data);
  return { ok, errors: compiled.errors ?? [] };
}

export function listComponentSchemaNames(loaded: LoadedContract): string[] {
  const schemas = loaded.spec.components?.schemas ?? {};
  return Object.keys(schemas).sort();
}

export class ContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ContractError';
  }
}
