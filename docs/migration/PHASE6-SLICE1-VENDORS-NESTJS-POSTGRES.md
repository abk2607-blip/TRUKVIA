# Phase 6 · Slice 1 — Vendors on NestJS + Next.js + PostgreSQL

**Status:** design only. Nothing here is built. Do not start before the Phase 5 stable LIVE baseline exists.

**Target platform (decided 2026-09-21):** NestJS API, Next.js UI, PostgreSQL. Method is
strangler-after-go-live: one module at a time behind the existing Python router, each shipping
independently with tests. The Fastify read migration (66 parity-locked routes) keeps serving
production until a module is genuinely replaced.

**Why vendors first:** self-contained, already migrated to Fastify so there is a byte-level parity
reference, and small enough to migrate and verify exactly — 2,177 vendors, 5,736 bills, 2,040
payments, 794 payment corrections (real production figures, 2026-09-21).

---

## 1. Scope

**In scope — the 15 endpoints in `routers/vendors.py`, `vendor_bills.py`, `vendor_payments.py`:**

| Method | Path |
|---|---|
| GET/POST | `/api/vendors` |
| GET/PUT/DELETE | `/api/vendors/{vid}` |
| POST | `/api/vendors/{vid}/reactivate` |
| GET/POST | `/api/vendors/{vid}/payments` |
| PUT/DELETE | `/api/vendors/{vid}/payments/{pid}` |
| GET | `/api/vendor-payments/{pid}/corrections` |
| GET/POST | `/api/vendor-bills` |
| GET/PUT/DELETE | `/api/vendor-bills/{bid}` |

**Out of scope for slice 1:** `vendor_ledger.py` (built by `services_party_ledger`, shared with
mechanics and suppliers), the vendor PDF ledger, and every `fin_txn` read. They stay on Python.

---

## 2. The coupling that decides the design

Vendor writes are **not** self-contained. `routers/vendors.py:30` and `vendor_bills.py:21` call
`hook_after_source_write`, which reprojects the source document into `fin_txn`
(`services_fin_txn.reproject_source`). In production data that projection has already produced
**370 `vendor_payment` and 760 `vendor_bill` rows** in `fin_txn`, out of 28,164 total.

Two further couplings:

* **Delete guard** — `vendor_bills.py:181` refuses to delete a bill while live `expenses` or
  payments reference it.
* **Bank snapshots** — 148 of 2,040 payments carry `bank_snapshot` / `source_bank_snapshot`
  objects copied from `company_bank_accounts` and `party_bank_accounts` at write time.

**Consequence:** a NestJS module that owns vendor *writes* must keep the `fin_txn` projection
correct, and `fin_txn` lives in MongoDB and is owned by the finance module. Writing to two stores
in one logical transaction is the central risk of this slice.

### Recommended sequencing

**Slice 1a — reads only (do this first).**
NestJS serves the 6 GET endpoints from PostgreSQL. Python keeps every write, and therefore keeps
owning the `fin_txn` projection. PostgreSQL is kept current by a one-way sync from MongoDB.
No dual-write, no distributed transaction, and the rollback is a router switch.

**Slice 1b — writes (only after 1a is stable in production).**
NestJS takes the 9 write endpoints. The projection is handled by calling the existing Python hook
over an internal endpoint, synchronously, before the NestJS response returns; a failure is recorded
in `fin_hook_failures` exactly as today, since that hook is already specified never to fail the
source write.

**Slice 1c — retire the Mongo copy** once vendors has run entirely on PostgreSQL for an agreed
period and the ledger module has followed.

---

## 3. PostgreSQL schema

Field lists below are taken from the real data, not from the models. Every column that is present
on 100% of documents is `NOT NULL` with a default matching Python's behaviour.

```sql
CREATE SCHEMA trukvia;

-- Tenancy is (user_id, company_id) everywhere, exactly as in Mongo.
-- Business keys stay TEXT so ids survive the migration unchanged and both
-- stacks can reference the same row during the strangler period.

CREATE TABLE trukvia.vendor (
  id                   TEXT PRIMARY KEY,              -- "vnd_..." preserved from Mongo
  user_id              TEXT NOT NULL,
  company_id           TEXT NOT NULL,
  name                 TEXT NOT NULL,
  contact_person       TEXT NOT NULL DEFAULT '',
  mobile               TEXT NOT NULL DEFAULT '',
  alt_mobile           TEXT NOT NULL DEFAULT '',
  address              TEXT NOT NULL DEFAULT '',
  state                TEXT NOT NULL DEFAULT '',
  city                 TEXT NOT NULL DEFAULT '',
  gst_in               TEXT NOT NULL DEFAULT '',
  pan                  TEXT NOT NULL DEFAULT '',
  msme_number          TEXT NOT NULL DEFAULT '',
  bank_name            TEXT NOT NULL DEFAULT '',
  account_number       TEXT NOT NULL DEFAULT '',
  ifsc                 TEXT NOT NULL DEFAULT '',
  branch               TEXT NOT NULL DEFAULT '',
  payment_terms        TEXT NOT NULL DEFAULT '',
  opening_balance      NUMERIC(14,2) NOT NULL DEFAULT 0,
  opening_balance_type TEXT NOT NULL DEFAULT 'payable',
  remarks              TEXT NOT NULL DEFAULT '',
  is_active            BOOLEAN NOT NULL DEFAULT TRUE,
  is_historical        BOOLEAN NOT NULL DEFAULT FALSE,
  imported_from        TEXT NOT NULL DEFAULT '',
  imported_ref         TEXT NOT NULL DEFAULT '',
  imported_batch       TEXT NOT NULL DEFAULT '',
  created_by           TEXT NOT NULL DEFAULT '',
  created_at           TIMESTAMPTZ NOT NULL,
  modified_by          TEXT NOT NULL DEFAULT '',
  modified_at          TIMESTAMPTZ,
  deactivated_by       TEXT NOT NULL DEFAULT '',
  deactivated_at       TIMESTAMPTZ,
  deactivation_reason  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX vendor_scope_name ON trukvia.vendor (user_id, company_id, name);
CREATE INDEX vendor_scope_active ON trukvia.vendor (user_id, company_id) WHERE is_active;

CREATE TABLE trukvia.vendor_bill (
  id              TEXT PRIMARY KEY,
  user_id         TEXT NOT NULL,
  company_id      TEXT NOT NULL,
  vendor_id       TEXT NOT NULL REFERENCES trukvia.vendor(id),
  vendor_name     TEXT NOT NULL DEFAULT '',      -- denormalised, as Mongo stores it
  bill_number     TEXT NOT NULL DEFAULT '',
  bill_date       DATE,
  bill_amount     NUMERIC(14,2) NOT NULL DEFAULT 0,
  vehicle_id      TEXT NOT NULL DEFAULT '',
  vehicle_number  TEXT NOT NULL DEFAULT '',
  trip_id         TEXT NOT NULL DEFAULT '',      -- no FK: trips still live in Mongo
  repair_event_id TEXT NOT NULL DEFAULT '',
  narration       TEXT NOT NULL DEFAULT '',
  remarks         TEXT NOT NULL DEFAULT '',
  file_ids        TEXT[] NOT NULL DEFAULT '{}',
  is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,
  deleted_by      TEXT NOT NULL DEFAULT '',
  deleted_at      TIMESTAMPTZ,
  deletion_reason TEXT NOT NULL DEFAULT '',
  created_by      TEXT NOT NULL DEFAULT '',
  created_at      TIMESTAMPTZ NOT NULL,
  modified_by     TEXT NOT NULL DEFAULT '',
  modified_at     TIMESTAMPTZ
);
CREATE INDEX vendor_bill_scope_date ON trukvia.vendor_bill (user_id, company_id, bill_date DESC);
CREATE INDEX vendor_bill_vendor ON trukvia.vendor_bill (vendor_id);
CREATE INDEX vendor_bill_vehicle ON trukvia.vendor_bill (vehicle_id);
CREATE INDEX vendor_bill_repair ON trukvia.vendor_bill (repair_event_id);

CREATE TABLE trukvia.vendor_payment (
  id                      TEXT PRIMARY KEY,
  user_id                 TEXT NOT NULL,
  company_id              TEXT NOT NULL,
  vendor_id               TEXT NOT NULL REFERENCES trukvia.vendor(id),
  vendor_bill_id          TEXT REFERENCES trukvia.vendor_bill(id),
  payment_date            DATE,                    -- Mongo field name is `date`
  amount                  NUMERIC(14,2) NOT NULL DEFAULT 0,
  type                    TEXT NOT NULL DEFAULT '',
  mode                    TEXT NOT NULL DEFAULT '',
  account_id              TEXT NOT NULL DEFAULT '',
  ref_no                  TEXT NOT NULL DEFAULT '',
  against                 TEXT NOT NULL DEFAULT '',
  remarks                 TEXT NOT NULL DEFAULT '',
  file_ids                TEXT[] NOT NULL DEFAULT '{}',
  -- correction / reversal chain (present on 2,017 of 2,040 rows)
  corrected_by            TEXT NOT NULL DEFAULT '',
  corrected_at            TIMESTAMPTZ,
  correction_count        INTEGER NOT NULL DEFAULT 0,
  latest_correction_id    TEXT,
  is_reversed             BOOLEAN NOT NULL DEFAULT FALSE,
  reversed_by             TEXT NOT NULL DEFAULT '',
  reversed_at             TIMESTAMPTZ,
  reversal_reason         TEXT NOT NULL DEFAULT '',
  reversal_of             TEXT REFERENCES trukvia.vendor_payment(id),
  reconciled_at           TIMESTAMPTZ,
  reconciled_ref          TEXT NOT NULL DEFAULT '',
  -- bank details (present on 148 and 147 rows respectively)
  bank_account_id         TEXT,
  bank_snapshot           JSONB,
  company_bank_account_id TEXT,
  source_bank_snapshot    JSONB,
  is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,
  deleted_by              TEXT NOT NULL DEFAULT '',
  deleted_at              TIMESTAMPTZ,
  deletion_reason         TEXT NOT NULL DEFAULT '',
  created_by              TEXT NOT NULL DEFAULT '',
  created_at              TIMESTAMPTZ NOT NULL,
  modified_by             TEXT NOT NULL DEFAULT '',
  modified_at             TIMESTAMPTZ
);
CREATE INDEX vendor_payment_scope_date ON trukvia.vendor_payment (user_id, company_id, payment_date DESC);
CREATE INDEX vendor_payment_vendor ON trukvia.vendor_payment (vendor_id);
CREATE INDEX vendor_payment_bill ON trukvia.vendor_payment (vendor_bill_id);
CREATE INDEX vendor_payment_reversed ON trukvia.vendor_payment (is_reversed);
CREATE INDEX vendor_payment_reversal_of ON trukvia.vendor_payment (reversal_of);

CREATE TABLE trukvia.payment_correction (
  id                        TEXT PRIMARY KEY,
  user_id                   TEXT NOT NULL,
  company_id                TEXT NOT NULL,
  payment_type              TEXT NOT NULL,          -- vendor | mechanic | supplier
  payment_id                TEXT NOT NULL,
  correction_index          INTEGER NOT NULL,
  kind                      TEXT NOT NULL DEFAULT '',
  correction_reason         TEXT NOT NULL DEFAULT '',
  before                    JSONB NOT NULL,         -- arbitrary payment snapshot
  after                     JSONB NOT NULL,
  diff                      JSONB NOT NULL,
  linked_reversal_id        TEXT,
  linked_new_id             TEXT,
  force_reconciled_override BOOLEAN NOT NULL DEFAULT FALSE,
  corrected_by              TEXT NOT NULL DEFAULT '',
  corrected_at              TIMESTAMPTZ NOT NULL,
  UNIQUE (user_id, company_id, payment_type, payment_id, correction_index)
);
```

### Schema decisions and why

* **Money is `NUMERIC(14,2)`, never float.** Mongo stores these as doubles; `opening_balance`,
  `bill_amount` and `amount` are all `float` in the data. Numeric removes the rounding class of bug
  and, as a side effect, removes the `0.0` vs `0` rendering difference found in the Fastify parity
  run — NestJS controls the JSON rendering of a numeric column explicitly.
* **`before` / `after` / `diff` stay `JSONB`.** They are arbitrary snapshots of a payment at a point
  in time; normalising them would break the moment a payment field changes.
* **`bank_snapshot` stays `JSONB`** for the same reason: it is a point-in-time copy, not a live
  reference. Present on only 7% of payments.
* **`vendor_name`, `vehicle_number` stay denormalised** because the Python API returns them and the
  UI reads them. Dropping them is an API change, which belongs to a later slice.
* **Business ids stay `TEXT`.** No surrogate integers. Both stacks must be able to reference the same
  row by the same id during the strangler period, and every existing document, file and audit row
  already points at these strings.
* **No FK to `trip_id`, `vehicle_id`, `repair_event_id`, `file_ids`.** Those entities remain in
  MongoDB until their own slices land. The columns are plain text, validated by the application.
* **Soft delete is preserved** (`is_deleted`), because the delete guard and the ledger depend on it.

### Type caveat

Every timestamp above is `TIMESTAMPTZ`, but the JSON export we hold renders dates as strings, so the
true Mongo types must be confirmed against a real `mongodump` before the migration is written.
`created_at` in production is a BSON date for documents written by recent code, and an ISO string for
older ones. The migration must handle both and must fail loudly on anything it cannot parse.

---

## 4. NestJS module layout

```
apps/api/src/
  main.ts
  app.module.ts
  common/
    tenancy/            # user_id + company_id resolution, ports the X-Company-Id rules from Gate 9c
    auth/               # session-token guard, ports auth.ts identity resolution from Gate 9b
    errors/             # FastAPI-compatible { "detail": ... } envelope
    serialization/      # numeric + date rendering to match the Python contract
  vendors/
    vendors.module.ts
    vendors.controller.ts       # 6 endpoints
    vendors.service.ts
    dto/                        # class-validator DTOs mirroring the Pydantic models
    entities/
  vendor-bills/                 # 5 endpoints
  vendor-payments/              # 4 endpoints + corrections read
  integrations/
    fin-projection.client.ts    # calls the Python hook (slice 1b)
```

**Two behaviours must be ported exactly, not reinvented**, because they are already gate-locked:

* **Auth identity** (Gate 9b): users lookup, team-member owner remap, `effective_role`, `is_staff`,
  and the CPython `fromisoformat` handling of string `expires_at`.
* **Tenant header** (Gate 9c): `X-Company-Id` takes the **first raw occurrence**, a single header
  containing a comma stays one literal value, and no extra trimming beyond SP/HTAB.

`backend-node/src/auth.ts` and `tenant.ts` are the reference implementations. Port them; do not
re-derive them from the Python source.

---

## 5. Next.js UI

Replaces `frontend/src/pages/Vendors.jsx` and the vendor parts of `VehicleWorkspace.jsx`.

* App Router, server components for the list and detail reads, client components for forms.
* Calls the NestJS API directly; during the strangler period a Next.js rewrite proxies every other
  `/api/*` path to the Python backend, so one origin serves both.
* Keeps the existing session-token scheme. Do not introduce a second auth mechanism mid-migration.

---

## 6. Data migration

1. **Extract** from a real `mongodump` archive, never from the JSON export (which loses BSON types).
2. **Transform** with an idempotent script: ids unchanged, doubles to numeric, dates to timestamptz,
   `date` renamed to `payment_date`, absent optional fields to their Python defaults.
3. **Load** into an empty schema inside one transaction per collection.
4. **Verify, and treat any failure as a stop:**
   * row counts equal per table: 2,177 / 5,736 / 2,040 / 794 (vendor corrections only);
   * `SUM(amount)`, `SUM(bill_amount)`, `SUM(opening_balance)` equal to the Mongo aggregates to the paisa;
   * every `vendor_id` in bills and payments resolves (production currently has **0 orphans** here);
   * every correction's `(payment_type, payment_id, correction_index)` is unique;
   * a random sample of 200 documents compared field by field.
5. **Re-sync** for slice 1a: a scheduled incremental sync on `modified_at`, plus a full reconcile
   that reports drift. NestJS reads are only as fresh as the last sync — that is acceptable for reads
   and is exactly why writes wait for slice 1b.

---

## 7. Tests

| Layer | Scope | Tooling |
|---|---|---|
| Unit | Services, DTO validation, tenancy and auth ports, numeric/date serialisation | Jest |
| Integration | Controllers against a real PostgreSQL | Jest + Testcontainers |
| Contract | NestJS responses vs the recorded Python contract for all 15 endpoints, including error envelopes and status codes | Jest snapshots generated from Python |
| **Parity (live)** | NestJS vs Python on the same data, all 15 endpoints, per the existing pattern | Extend `backend-node/test/cutover_parity/live_compare.py` |
| Migration | Counts, sums, referential integrity, sample-by-sample comparison | pytest, run against a restored archive |
| E2E | Vendor create → bill → payment → correction → reversal, through the Next.js UI | Playwright |

**Pass criterion:** status codes equal **and** parsed JSON equal — the criterion adopted on
2026-09-21 after the float-rendering finding. Byte equality is not required and is not expected,
since numeric columns render differently by design.

**Write tests before the implementation for the correction and reversal chain.** It is the only part
of this module with real business complexity: 794 corrections across 2,017 payments that carry
correction metadata.

---

## 8. Rollout and rollback

* Route `/api/vendors*` and `/api/vendor-bills*` to NestJS through the existing Python router
  (`backend/node_router.py`), reusing the percentage rollout, the kill-switch file and the automatic
  Python fallback. No new routing mechanism is needed.
* Roll out at 5%, then 25%, then 100%, with the parity checker run at each step.
* **Rollback is the kill-switch file**, which is effective in under a second and needs no deploy.
* During slice 1a the Mongo data stays authoritative, so rollback loses nothing. From slice 1b
  onward, PostgreSQL is authoritative for vendors and rollback requires replaying writes — so 1b
  must not start until 1a has been stable in production.

---

## 9. Open questions

1. **Where does PostgreSQL run?** It must sit next to the API. This affects the infrastructure
   decision that is still open for the Node service.
2. **Who owns `fin_txn` long term?** Vendors project into it today. Either finance becomes an early
   slice, or NestJS calls the Python hook for longer than is comfortable.
3. **ORM:** Prisma or TypeORM. Prisma is recommended for schema-first clarity, but it must be
   confirmed that `NUMERIC` maps to a decimal type and not to a JavaScript float.
4. **Does the UI move before or after the API?** Running Next.js as a proxy in front of the existing
   React app is possible but adds a moving part during the strangler period.
5. **Sync latency for slice 1a:** how stale may vendor reads be? This sets the sync interval.
