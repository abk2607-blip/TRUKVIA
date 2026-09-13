# TRUKVIA · Migration Contract Bundle

**Contract tag:** `contract@v1.iter150j`
**Baseline commit:** `a327b83` (Iter150J lock) · Parent `e3e16fa` (Iter150I lock)
**Status:** FROZEN — this bundle is the behavioural contract for the current Python/FastAPI backend and the future Node.js/TypeScript backend.

## Scope

This directory is **documentation only.** Nothing under `docs/contracts/` is imported at runtime by either the current Python backend or any future Node backend. These files exist so that:

1. The behavioural contract of the running application is captured in a form that survives a re-platforming.
2. The Node/TypeScript port has a Class-A invariants specification to test against.
3. Provider-neutral integration ports are pre-designed as pure TypeScript interfaces.
4. PII / bank / secrets policy is agreed before any encryption-touching code is written.

## Files

| File | Purpose |
|---|---|
| `openapi.v1.json` | Runtime export of the current FastAPI OpenAPI schema. **Do not hand-edit.** |
| `endpoint-matrix.md` | 346-endpoint contract matrix. Auth / tenant / idempotency / approval / FinTxn / audit facets per endpoint. |
| `migration-invariants.md` | Class-A / Class-B invariants that any re-implementation MUST preserve. |
| `error-string-parity.md` | Frozen list of HTTP status codes and `detail` strings the current React frontend depends on. |
| `pii-security.md` | Policy for bank numbers, GSTIN, DL/PAN, email/phone, session tokens, provider secrets. |
| `integration-hub/ports/*.d.ts` | Provider-neutral semantic port interfaces. Runtime code MUST NOT live here. |

## How to update

Any change to a file in this directory is a **contract change**. It requires:

- An explicit authorisation message referencing this bundle.
- A new contract tag (`contract@v2.iter15xx`) on the resulting commit.
- Corresponding parity-harness updates.

Silent edits are prohibited.
