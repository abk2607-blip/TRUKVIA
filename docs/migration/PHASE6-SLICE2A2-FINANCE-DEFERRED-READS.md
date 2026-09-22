# Phase 6 — the two Finance reads deferred out of slice 2a

```
GET /api/fin/day-status
GET /api/fin/day-closures/{close_date}/late-entries
```

This is **not** the Finance 2c ledger/projection migration. Untouched:
`/api/fin/reproject`, `hook_after_source_write`, the `fin_txn` write
projection, `GET /api/fin/accounts`, reconciliation. The Python
implementation stays in place. Production was not involved at any point.

Slice 2a is [frozen at `6d9be00`](PHASE6-SLICE2A-FINANCE-READS.md);
[slice 2b](PHASE6-SLICE2B-FINANCE-WRITES.md) is at `ef04583`.

## Inspection

Both handlers live in
[`backend/routers/fin_day_closing.py`](../../backend/routers/fin_day_closing.py),
and both already have a gate-locked Fastify shadow — Gate 7o for day-status and
Gate 7r for late-entries (542/542 byte-exact). Those shadows, not the Python
source, are the contract reference, and they are where the subtle bindings were
read from.

**No new table was needed.** Between them the two handlers read exactly
`fin_day_closure` and `fin_txn`, both of which slice 2a already migrated.

### Reads, writes and scoping

| | day-status | late-entries |
| --- | --- | --- |
| reads | closure (5 projected fields), then a `fin_txn` existence probe | closure (`closed_at` only), then `fin_txn` |
| writes | **none** | **none** |
| scope | `user_id` + active company | `user_id` + active company |
| role | any authenticated user — no owner check | same |

`r["days_late"] = …` in `late_entries` mutates the in-memory row, not the
document. Neither handler logs an audit row.

### Validation order

```
day-status    auth 401 → `date` required (422 missing) → `if not date` 400
              → date.fromisoformat 400 → active company → reads
late-entries  auth 401 → date.fromisoformat 400 → active company
              → closure probe → 404 → fin_txn read
```

The asymmetry is real: day-status takes its date from the query, so FastAPI's
`missing` 422 comes first and the company is resolved last; late-entries takes
it from the path and validates before resolving the company. The two 400
literals name their own field (`date` / `close_date`).

### Projection truthiness — three places it decides the answer

1. day-status: a closure holding **none** of the five projected fields
   projects to `{}`, which is falsy, so Python reports it as *not found* and
   returns the two-key shape `{date, is_closed}`.
2. day-status: `status` missing defaults to `null`; the other four default to
   `""`. Present-but-null stays null.
3. late-entries: a closure with no `closed_at` projects to `{}` and therefore
   **404s exactly like a missing closure**.

### Dates

`_parse_iso_date` is CPython 3.11's C `date.fromisoformat`, which accepts more
than `YYYY-MM-DD`: the basic form `20260214`, and ISO week dates `2026-W07` and
`2026-W07-6`. `src/common/py-date.ts` is a port of the Gate 7r implementation,
returning the proleptic ordinal so that subtraction is exactly Python's
`(a - b).days`.

`days_late` is `max(0, close − txn_date[:10])`, with any unparsable date
giving 0. Buckets are `0-7`, `8-30`, `31-90`, `90+`, by `<=`.

### Ordering and aggregates

`late_entries` sorts on **`txn_date` alone**, so every row sharing a date is a
tie — and Motor's `to_list(5000)` is a client-side cap, not a server `.limit()`,
which would change *which* rows win a tie. `totals` accumulates raw floats and
rounds once at the end, with `net` computed from the already-rounded `in`/`out`.
`by_source_type` is insertion-ordered by first appearance; `by_days_late_bucket`
has a fixed literal order. Response key order is `close_date`, `count`,
`totals`, `by_source_type`, `by_days_late_bucket`, `rows`, and `days_late` is
appended to the end of each row.

## Implementation

`src/fin/fin-status-reads.{service,controller}.ts`, served from PostgreSQL
against the 2a tables, plus `src/common/py-date.ts`. Slice 2a's service is
imported from (`txnToJson`) and not modified.

## Parity

`scripts/fin-status-parity.ts`, against the live Python server and the local
real-data copy:

```
cases 33   BYTE-IDENTICAL 31   TIE-EQUIVALENT 2   FAIL 0
  PASS  no writes: MongoDB and PostgreSQL unchanged across the run
```

Covered: validation order, empty and no-data cases, date boundaries (year 0,
month 13, 2026-02-30, impossible ISO week), the wider CPython date forms,
repeated query keys, 404s, and tenant isolation — the closure is invisible when
the request is scoped by `X-Company-Id` to another of the same user's 533
companies, while an id belonging to no user falls back to the default company.

### day-status is read-only — proved, not asserted

The harness fingerprints both stores before and after the whole run: a full
content hash of `fin_day_closures` (Mongo and Postgres), a `fin_txn` aggregate
over count, summed amount and the three timestamp maxima, and counts for
`fin_accounts`, `audit_logs`, `companies` and `users`. It is unchanged. The
audit and company counts are what would catch a write sneaking in from the
shared helpers. `user_sessions` is counted only, because Python's auth performs
a rolling session refresh at most once per 30s — that is authentication, not
these endpoints.

### The two tie-equivalent cases

Only `late-entries` on the one real closure: 658 rows in 33 `txn_date` groups.
Measured directly — 9 of 658 positions coincide with a `mongo_id` ordering, and
**not one group** is ordered by `_id` ascending or descending. As in slice 2a,
no key reproduces Mongo's tie order, so PostgreSQL uses `mongo_id ASC` to make
our own order deterministic and the harness compares tie groups as multisets.
`count`, `totals`, `by_source_type` and `by_days_late_bucket` all matched.

## Bugs found and fixed

Both are in slice 2b, both exposed by this slice's wider date testing, and both
were real mismatches against Python.

**1. The date guard was a regex.** `fin-writes.service.ts` validated
`close_date` with `/^\d{4}-\d{2}-\d{2}$/`, so `POST /api/fin/day-closures` with
`20260903` or `2026-W36-4` returned 400 where Python returned 200. Now routed
through `pyIsoDateValid`.

**2. The future-date check compared strings.** `closeDate > today` on raw text
works only while every input is `YYYY-MM-DD`. `'20260903' > '2026-09-21'` is
*true* — `'0'` is 0x30 and `'-'` is 0x2d — so a past date was read as a future
one and rejected with 422. Python compares `date` objects; the port now
compares ordinals. This one only became reachable once bug 1 was fixed.

Four cases were added to `scripts/write-parity.ts` to hold both down.

## A pre-existing property this slice exposed

Running slice 2a's read parity under a **second tenant** turned up a false
failure in the harness, not in the code: day-book's `totals` key order differed
(`CASH` and `DRIVER_OUTFLOW` swapped, identical values). Python inserts each
`account_code` on its first appearance while walking the rows, so the key order
is derived from the row order and inherits the same undefined-ness the rows
have. Both harnesses now compare such derived maps as mappings — key set and
every value still exact — and say why. No service code changed.

## Results

```
scripts/fin-status-parity.ts   33 cases, 0 failures, no writes
scripts/fin-reads-parity.ts    32 cases, 0 failures   (2a regression)
scripts/write-parity.ts        76 cases, 0 failures, 1 known divergence (2b regression)
vitest                         163 tests passing
```

The 2b known divergence is unchanged and documented in that slice: Python hangs
rather than returning 500 on a non-string `close_date`.
