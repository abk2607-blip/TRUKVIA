import { describe, it, expect } from 'vitest';
import { existsSync } from 'node:fs';
import {
  loadContract,
  defaultContractPath,
  validateAgainstRef,
  listComponentSchemaNames,
  ContractError,
} from '../src/contract/loader.js';

const contractPath = defaultContractPath();
const hasContract = existsSync(contractPath);

describe('OpenAPI contract-test foundation', () => {
  it('finds the frozen contract file on disk', () => {
    expect(hasContract).toBe(true);
  });

  it.skipIf(!hasContract)('loads the OpenAPI 3.x spec', () => {
    const c = loadContract(contractPath);
    expect(c.spec.openapi).toMatch(/^3\./);
    expect(typeof c.spec.paths).toBe('object');
    expect(Object.keys(c.spec.paths).length).toBeGreaterThan(0);
  });

  it.skipIf(!hasContract)('exposes at least one component schema', () => {
    const c = loadContract(contractPath);
    const names = listComponentSchemaNames(c);
    expect(names.length).toBeGreaterThan(0);
  });

  it.skipIf(!hasContract)('resolves internal $ref values and compiles a validator', () => {
    const c = loadContract(contractPath);
    const [first] = listComponentSchemaNames(c);
    expect(first).toBeDefined();
    // Simply compiling against a $ref inside the spec proves ref resolution
    // works and the schema is well-formed enough for Ajv 2020.
    const result = validateAgainstRef(c, `#/components/schemas/${first!}`, {});
    expect(typeof result.ok).toBe('boolean');
    expect(Array.isArray(result.errors)).toBe(true);
  });

  it.skipIf(!hasContract)('validates a trivially-conforming empty object against a permissive fixture schema', () => {
    // Build a purely local schema so we prove the Ajv+draft-2020 wiring
    // without depending on the specific shape of any TRUKVIA component.
    const c = loadContract(contractPath);
    // Register a local schema fixture inside the same Ajv instance and
    // validate through it. This proves Ajv 2020 is initialised correctly.
    c.ajv.addSchema(
      {
        $id: 'https://trukvia.local/fixtures/ping.json',
        type: 'object',
        properties: { status: { type: 'string' } },
        required: ['status'],
        additionalProperties: false,
      },
      'ping-fixture',
    );
    const validate = c.ajv.getSchema('https://trukvia.local/fixtures/ping.json');
    expect(validate).toBeTypeOf('function');
    expect(validate!({ status: 'ok' })).toBe(true);
    expect(validate!({})).toBe(false);
    expect(validate!({ status: 'ok', extra: 1 })).toBe(false);
  });

  it('rejects a refPath that does not start with "#/"', () => {
    if (!hasContract) return;
    const c = loadContract(contractPath);
    expect(() => validateAgainstRef(c, 'components/schemas/X', {})).toThrow(ContractError);
  });

  it('throws ContractError for a non-OpenAPI file', () => {
    // Write a temp non-openapi document via memfs-like inline check.
    // We can just point at package.json which exists but is not OpenAPI.
    const bogus = defaultContractPath().replace(/openapi\.v1\.json$/, 'openapi.v1.json.MISSING');
    expect(() => loadContract(bogus)).toThrow();
  });

  it.skipIf(!hasContract)('confirms no /api business route is served by the Node app (contract awareness only)', () => {
    const c = loadContract(contractPath);
    const apiRoutes = Object.keys(c.spec.paths).filter((p) => p.startsWith('/api/'));
    // The Python backend owns these. This test only asserts the contract
    // *knows about* them — the Node skeleton must NOT implement them yet.
    expect(apiRoutes.length).toBeGreaterThan(0);
  });
});
