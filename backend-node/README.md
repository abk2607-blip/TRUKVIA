# TRUKVIA — backend-node (Phase 2 Foundation)

> **Status:** foundation skeleton only. Python (`/app/backend`) remains the
> **authoritative** production backend for TRUKVIA. This directory contains
> no business logic and is not wired to supervisor or ingress.

## Purpose

Phase 2 of the strangler-fig migration prepares a small, transparent
Node.js + TypeScript foundation that will eventually consume the frozen
API contract from Phase 1 and re-implement routes one-by-one under strict
shadow-parity gates.

## Scope (what is allowed here)

- Type-safe configuration (`src/config.ts`)
- MongoDB connection abstraction (`src/db.ts`) — **read-only, no writes**
- Request-ID infrastructure (`src/request-id.ts`)
- Health endpoints (`src/health.ts`): `GET /health/live`, `GET /health/ready`
- Structured logging with PII redaction (`src/logger.ts`)
- Fastify boot (`src/app.ts`, `src/server.ts`)
- Vitest foundation tests

## Scope (what is NOT allowed here yet)

- No `/api/*` routes
- No business writers (Trip, Invoice, Payment, Reconciliation, Maker-Checker, Day Closing, etc.)
- No schema mutations or index creation
- No production DB connection
- No supervisor/ingress wiring

## Stack

| Layer      | Choice                     |
| ---------- | -------------------------- |
| Runtime    | Node.js 20 LTS             |
| Language   | TypeScript 5.5 (strict)    |
| HTTP       | Fastify 4                  |
| Validation | Zod                        |
| Database   | native `mongodb` driver 6  |
| Logging    | Pino 9                     |
| Testing    | Vitest 2                   |

## Migration authority

Once route migration begins (a later gate), this backend will consume:

- `../docs/contracts/openapi.v1.json`
- `../docs/contracts/migration-invariants.md`
- `../docs/contracts/endpoint-matrix.md`
- `../docs/contracts/error-string-parity.md`
- `../docs/contracts/pii-security.md`
- `../docs/contracts/integration-hub/ports/*.d.ts`

Any deviation from these contracts requires a formal gated approval.

## Local usage

```bash
cd backend-node
cp .env.example .env         # edit as needed (dev DB only)
npm install
npm run typecheck
npm test
npm run build
npm start                    # dev only; NOT wired to ingress
```

## Configuration

All Node config keys are `NODE_*`-prefixed so they never collide with
`backend/.env`. See `.env.example`.

| Var                              | Required | Notes                              |
| -------------------------------- | -------- | ---------------------------------- |
| `NODE_ENV`                       | yes      | `development` / `test` / …         |
| `NODE_LOG_LEVEL`                 | yes      | pino level                         |
| `NODE_PORT`                      | yes      | dev port only                      |
| `NODE_HOST`                      | yes      | typically `127.0.0.1`              |
| `NODE_MONGO_URL`                 | yes      | must start `mongodb://` or `+srv://` |
| `NODE_DB_NAME`                   | yes      | dev/test DB only                   |
| `NODE_CORS_ORIGINS`              | no       | comma-separated                    |
| `NODE_REQUEST_ID_HEADER`         | no       | defaults to `x-request-id`         |
| `NODE_TRUST_INCOMING_REQUEST_ID` | no       | defaults to `false`                |

## Safety

- Foundation refuses to boot with `NODE_ENV=production` **and** a DB name
  containing `prod`.
- Mongo layer sets `retryWrites: false` and performs zero writes.
- Logger redacts common PII paths (`password`, `authorization`, `pan`,
  `dl_number`, `aadhaar`, `bank_account`, `api_key`, etc.).
