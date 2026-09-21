# Phase 6 · Slice 2a — Finance reads on PostgreSQL

Read-only slice. MongoDB remains the system of record; PostgreSQL holds a
derived read model. No write, no projection, no reconciliation, no deployment.

Follows [the Finance discovery pass](PHASE6-SLICE2-FINANCE-DISCOVERY.md), which
set the boundary, and reuses the pattern established in
[slice 1 (vendors)](PHASE6-SLICE1-VENDORS-NESTJS-POSTGRES.md).

## Tables

Migration `0004`, schema `trukvia`, defined in `apps/api/src/db/schema.ts`.

| Table | Rows migrated | Primary key | Notes |
| --- | --- | --- | --- |
| `fin_txn` | 28,164 | `id` (business id) | `mongo_id` kept for tie-breaking |
| `fin_account` | 15,663 | `id` | unique on `(user_id, company_id, code)` |
| `fin_day_closure` | 1 | `id` | `snapshot`/`history` as `json` |

`fin_txn.amount` sums to `196878935.50` in both stores — an exact match, which
is the check that matters most here, because it is the one that would expose a
float round-trip.

### The 13-vs-14 account split is preserved, not normalised

857 scopes hold 13 accounts and 323 hold 14; the difference is `DRIVER_OUTFLOW`,
added to the seed set later, and `ensure_system_accounts` fills it in lazily on
first access. That is a valid state, so the migration copies it verbatim. The
unique index is on `(scope, code)` — deliberately **not** a fixed count per
scope, which would have rejected the legitimate 13-account scopes.

## Data-shape conversions

Each of these exists because the obvious representation lost bytes against
Python's output.

| Concern | Choice | Why |
| --- | --- | --- |
| `amount` | `numeric(14,2)` | float cannot round-trip paisa; totals accumulate as integer paisa and round once |
| timestamps, dates | `text` | preserves the stored bytes *and* Mongo's lexicographic sort order, which the day-book ordering depends on |
| `snapshot`, `history` | `json`, read back with `::text` | `jsonb` reorders keys and rewrites `52400.0` as `52400`; both are visible in the response |
| `fin_txn` key order | `source_shape` column | production holds two key orders (18,980 / 9,184 rows) because two drivers serialised the upsert filter differently; the response echoes each document's own order |
| session timezone | `-c timezone=UTC` on the pool | otherwise Postgres renders `+05:30` |

## Endpoint status — the six Finance reads

| Endpoint | Status | Reason |
| --- | --- | --- |
| `GET /api/fin/day-book` | **served from PostgreSQL** | Gate 7s contract |
| `GET /api/fin/day-closures` | **served from PostgreSQL** | Gate 7m contract |
| `GET /api/fin/day-closures/{close_date}` | **served from PostgreSQL** | Gate 7n contract |
| `GET /api/fin/accounts` | stays in Python | calls `ensure_system_accounts` on every request — a GET-time **writer**, so it is out of scope for a read slice |
| `GET /api/fin/fin-txn/{txid}` | stays in Python | enriches from 13 source collections that are still MongoDB-only |
| `GET /api/fin/day-status` | stays in Python | deferred; depends on closure + txn aggregates not yet needed |

Auth, the active company and sessions still resolve against MongoDB, because
Python owns those writes.

## Verification

`apps/api/scripts/fin-reads-parity.ts` — 32 cases against the live Python
server and the NestJS server on the same data:

```
cases 32   BYTE-IDENTICAL 27   TIE-EQUIVALENT 5   FAIL 0
```

`apps/api/test/fin-reads.test.ts` — 30 unit tests. Whole suite: 88 passing.
`scripts/parity-vs-python.ts` (vendors, slice 1) still 28/28, so this slice did
not disturb it. Trailing-slash 307s match on both new routes.

### Why five cases are "tie-equivalent" rather than byte-identical

MongoDB does not define the order of documents that tie on the sort key, and
the day-book sorts on `(txn_date DESC, created_at DESC)`. Every `fin_txn` is
written as a balanced pair, so **both legs always share that key**: the
full-year day-book is 694 rows in 347 tie groups of exactly two. There is no
tie-break that reproduces Mongo's order, and this is not a guess — in one group
Python returned the pair descending by `_id` (`…b66` before `…b64`) and in the
very next group ascending (`…d1` before `…d3`).

So PostgreSQL breaks ties on `mongo_id ASC`, which makes our order
deterministic and stable across runs. 688 of 694 positions coincide with
Python's anyway; the 6 that differ are 3 pairs in swapped order. The parity
harness compares tie groups as multisets and requires everything else — status,
envelope, `totals`, `count`, and every field of every row — to be byte
identical. A missing row, a row in the wrong tie group, or any field difference
still fails.

This is a property of the source data, not a defect in the read model, and it
is worth stating plainly: **the existing MongoDB endpoint's row order within a
tie is already arbitrary and may differ between two consecutive calls.** No
client can depend on it today.

## Reproducing the parity run locally

Needs the local MongoDB copy (`trukvia_local_20260921`), PostgreSQL on 5433,
Python on 8001 and NestJS on 8003. The harness authenticates as a real user, so
it needs a session token; the temporary `local-demo-*` row used during
development was removed after the run, so mint a fresh one against the local
copy rather than reusing a token from anywhere else.

```
npx tsx scripts/fin-reads-parity.ts --token <local session token>
```

## Not done in this slice

Writes, the projection, reconciliation, `day-status`, `late-entries`,
`GET /api/fin/accounts`, and any routing change. Nothing is deployed and
`NODE_ROUTING_*` remains untouched.
