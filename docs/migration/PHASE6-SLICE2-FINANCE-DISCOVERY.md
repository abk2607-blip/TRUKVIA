# Phase 6 · Slice 2 — Finance: discovery and boundary pass

**Status:** discovery only. Nothing is implemented, and nothing here authorises implementation.
Figures come from the live Python source and the local restore of production data (2026-09-21).

**Headline:** Finance is **not** a normal module. It is a *projection* of nine other modules'
writes, so its boundary is defined less by its own routes than by who writes into it. Six of its
fifteen routes are already migrated to Fastify with byte-exact parity, and that is the natural
starting point for slice 2.

---

## A. Route count and categories

**15 Finance routes**, all under `/api/fin/*`, in four routers.

### Reads — day book and accounts (`routers/fin_day_book.py`, 239 lines)

| Route | Category | Fastify-migrated? |
|---|---|---|
| `GET /api/fin/accounts` | read, seeds on first hit | no |
| `GET /api/fin/day-book` | derived / reporting | **yes** (Gate 7s) |
| `GET /api/fin/fin-txn/{txid}` | read + source join | **yes** (Gate 7q) |
| `POST /api/fin/reproject` | **write** (ledger rebuild), owner-only | no |

### Day closing (`routers/fin_day_closing.py`, 362 lines)

| Route | Category | Fastify-migrated? |
|---|---|---|
| `POST /api/fin/day-closures` | **write** — snapshot + close | no |
| `POST /api/fin/day-closures/{close_date}/reopen` | **write**, owner-only | no |
| `GET /api/fin/day-closures` | read | **yes** (Gate 7m) |
| `GET /api/fin/day-closures/{close_date}` | read | **yes** (Gate 7n) |
| `GET /api/fin/day-closures/{close_date}/late-entries` | derived | **yes** (Gate 7r) |
| `GET /api/fin/day-status` | derived | **yes** (Gate 7o) |

### Reconciliation (`routers/fin_reconciliation.py`, 58 lines + `services_reconciliation.py`, 516)

| Route | Category | Fastify-migrated? |
|---|---|---|
| `GET /api/fin/reconciliation/summary` | reconciliation, read-only | no |
| `GET /api/fin/reconciliation/domain/{domain_name}` | reconciliation, read-only | no |
| `GET /api/fin/reconciliation/mismatch/{domain_name}/{key:path}` | reconciliation, read-only | no |

### Source lookup (`routers/fin_source_lookup.py`, 193 lines)

| Route | Category | Fastify-migrated? |
|---|---|---|
| `GET /api/fin/source/{source_type}/{source_id}` | read, cross-module join | no |
| `GET /api/fin/source-legs/{source_type}/{source_id}` | read | no |

**Totals:** 12 reads/derived, 3 writes (`reproject`, `day-closures`, `reopen`).
**6 of the 12 reads are already on the frozen Fastify allowlist** — they have byte-exact parity
references and live harnesses from Gates 7m, 7n, 7o, 7q, 7r and 7s.

---

## B. Collection dependency map

### Owned by Finance (written only by Finance code)

| Collection | Rows (local restore) | Written by |
|---|---|---|
| `fin_txn` | **28,164** | `services_fin_txn._persist_legs` only |
| `fin_accounts` | **15,663** | `ensure_system_accounts` only |
| `fin_day_closures` | 1 | `routers/fin_day_closing.py` only |
| `fin_hook_failures` | 0 (absent) | `services_fin_txn_hooks` only |
| `fin_reconciliations` | 0 (absent) | — |

`fin_txn` by source: expense 22,262 · invoice 3,160 · vendor_bill 760 · supplier_payment 622 ·
vendor_payment 370 · trip_customer_receipt 370 · credit_debit_note 348 · mechanic_payment 126 ·
invoice_payment 68 · driver_payment 52 · mechanic_work_order 26. Two tenants only: demo 27,470,
real 694.

### Read by Finance (owned elsewhere)

`invoices`, `expenses`, `trips`, `credit_debit_notes`, `supplier_payments`, `vendor_payments`,
`vendor_bills`, `mechanic_payments`, `mechanic_work_orders`, `driver_payments`,
`wallet_recharges`, `wallet_transfers`, `wallet_adjustments` — 13 source collections, read by
`services_fin_txn.reproject_source` and by `services_reconciliation`.

### Dependency direction, per your list

| Depends on | Direction | Detail |
|---|---|---|
| `vendor_bill` | Finance **reads**; the bill's writer **calls** Finance | `project_vendor_bill`, orphan-only |
| `vendor_payment` | same | `project_vendor_payment` |
| `fin_txn` | Finance **owns** | the only writer is `_persist_legs` |
| `invoices` | Finance reads; invoice writers call the hook | plus an `invoice_payment` cascade on the same source id prefix |
| `expenses` | Finance reads; 4 call sites | **the largest projection source, 79% of all legs** |
| `trips` | Finance reads; 3 call sites | `trip_customer_receipt`, source id is `{tid}:{rid}` |
| `approvals` | **no direct dependency** | the approval gate intercepts POSTs before the handler; it never reads Finance |
| `customers` / `suppliers` / `vendors` | denormalised only | `party_id`, `party_name` copied onto legs |
| company / user tenancy | every query is `(user_id, company_id)` scoped | `fin_accounts` ids embed the last 6 chars of each |

### Nine modules write into Finance

`expenses` (4 call sites), `notes` (6), `trips` (3), `vendors` (2), `vendor_bills` (2),
`suppliers` (2), `mechanics` (2), `mechanic_work_orders` (2), `wallet_*` (6 across three routers),
`driver_payments` (2). Each calls `hook_after_source_write(uid, cid, source_type, source_id)`
after its authoritative write.

---

## C. Recommended slice 2 boundary

### Slice 2a — read-only, and deliberately small

Move the **six already-Fastify-migrated reads** to NestJS + PostgreSQL:
`day-book`, `fin-txn/{txid}`, `day-closures` (list and detail), `day-closures/{d}/late-entries`,
`day-status`.

Why these: each has a byte-exact parity reference and a gate harness, so correctness is
demonstrable rather than argued; they touch only `fin_txn`, `fin_accounts` and `fin_day_closures`,
all Finance-owned; and none of them writes.

`fin_txn` migrates to a PostgreSQL table whose shape is already known (32 fields, flat, no nested
documents). At 28,164 rows it is smaller than the vendors module's bills. `amount` becomes
`numeric(14,2)`, `txn_date` stays a plain date string as stored, and the `source_id`/`source_key`
identity fields stay `text`.

**Keep in Python during 2a:** every write, the projection, and the three reconciliation endpoints.

### Slice 2b — writes

`POST /api/fin/day-closures` and `.../reopen`. They are self-contained: the only collection
written is `fin_day_closures`, and the snapshot is computed live from `fin_txn`. Owner-only, with
a re-close path that refreshes the snapshot and appends history.

**Do NOT move `POST /api/fin/reproject` in 2b.** It is the ledger rebuild, it is owner-only, and
it is the one route whose behaviour the whole projection depends on.

### Slice 2c — ledger integration, the real work

Move `services_fin_txn.py` (1,197 lines) and `services_fin_txn_hooks.py` (400). Only then can
`apps/api/src/fin/projection.ts` — the vendor-only port from slice 1b — be retired, and the
internal hook added in 1b(b) becomes the compatibility bridge **in the other direction**: Python
routers that still own writes call NestJS to project.

### Slice 2d — reconciliation

`services_reconciliation.py` (516 lines) reads nine collections across module boundaries. It
should move last, once those modules have moved, or it will need cross-store reads for every
domain.

---

## D. Risks, blockers and hidden coupling

**1. The projection is a fan-in from nine modules — this is the defining constraint.**
Until `services_fin_txn` moves, every one of those modules' writes must still reach it. The
internal hook from slice 1b(b) already solves this for a NestJS caller; the reverse direction
(Python caller → NestJS projection) does not exist yet and is a prerequisite for 2c.

**2. Write ordering is observable and inconsistent between modules.**
Bills project then audit; payments audit then project. Any move must preserve each call site's
order, not impose a uniform one.

**3. Idempotency has a specific shape.** `reproject_source` is delete-then-insert: delete every
leg for `(source_type, source_id)`, then upsert by `ref_source_key`. Replay is safe and partial
failure self-heals on the next run. `invoice` and `trip_customer_receipt` additionally cascade on
a `{id}:*` prefix. This behaviour must survive verbatim.

**4. Rounding.** `_q2` uses Python's `round()`, which is banker's rounding. The slice 1b port
implements round-half-to-even explicitly; any further port must do the same, and money must be
`numeric`, never float.

**5. Failure semantics are load-bearing.** `hook_after_source_write` never raises: failures land
in `fin_hook_failures` for a retry driver. A NestJS implementation that throws into the caller's
write path would be a behavioural regression, not a stricter one.

**6. Account-id derivation is positional.** `acc_{code}_{uid[-6:]}_{cid[-6:]}` — the last six
characters of each id. Any change to id generation would silently orphan ledger rows from their
accounts.

**7. `fin_accounts` two generations — RESOLVED 2026-09-21, no action needed.**
15,663 rows across **1,180 `(user_id, company_id)` scopes**: **857 have 13 accounts, 323 have 14**.
The only difference is `DRIVER_OUTFLOW` ("Driver Payments Outflow", type `expense`), appended to
`FIN_SYSTEM_ACCOUNTS` at `models.py:1607` for Iter150I. The split is purely chronological: every
other code first appears 2026-09-10T17:24:23, `DRIVER_OUTFLOW` from 2026-09-12T14:34:11.

**13 is a valid lazy state, not an incomplete one.** `ensure_system_accounts` is a per-code
find-or-insert that runs on every projection (`reproject_source`, `backfill_tenant`) and on
`GET /api/fin/accounts`, so a 13-account scope becomes 14 the moment it next projects or its
accounts are read. A missing account can never cause a projection failure, because the seeding
happens before `_persist_legs` resolves any code.

**No ledger row depends on a missing account.** Exactly 26 legs use `DRIVER_OUTFLOW` as
`account_code` and the same 26 as `counter_account_code` (driver_payment legs: 52 total, paired
with CASH/BANK_DEFAULT). All resolve to existing account rows, and both tenants that hold any
ledger data have the full 14.

**Migration treatment: option A — preserve each scope's set exactly.** Normalising to 14 would
invent 857 rows the application never created, with positionally derived ids and a fabricated
`created_at`: a business-data mutation, not a migration transformation. It would also change what
`GET /api/fin/accounts` returns for those scopes. Preserving is also self-correcting, since the
sync picks up rows as Python creates them.

**Related finding, for whoever migrates it later:** `GET /api/fin/accounts` **writes** — it calls
`ensure_system_accounts` on every request (`routers/fin_day_book.py:46`). It is a GET-time writer
in the Phase 3 sense and is on neither the allowlist nor the deferred list. None of the six
slice 2a routes seeds accounts, so slice 2a is unaffected.

**8. Day-closure has no enforcement teeth.** Nothing outside `fin_day_closing.py` and
`services_reconciliation.py` reads `fin_day_closures`: closing a day does **not** block later
writes. The `late-entries` endpoint exists precisely to surface what arrived after a close. Do not
"fix" this during a migration slice.

**9. `POST /api/fin/reproject` is owner-only and stays that way.** Slice 1b(b) added the internal
hook specifically so service-to-service calls never need that endpoint.

**10. Volume asymmetry.** Expenses produce 79% of all ledger rows. Any Finance work is really
Expense-shaped work, and the Expense module has the most complex projection of all
(`project_expense`, seven routing rules).

---

## E. Shared helpers that must NOT be duplicated

| Helper | Why |
|---|---|
| `auth.get_current_user` / `auth.ts` | already ported once (Gate 9b); port, never re-derive |
| `company._active_company_id` / `tenant.ts` | Gate 9c first-raw-header rule |
| `audit._log_audit`, `_diff_dict` | ported in slice 1b; reuse that |
| `services_fin_txn._leg`, `_q2`, `_mode_account` | one implementation only — this is the whole point of slice 2c |
| `ensure_system_accounts` | account-id derivation must exist in exactly one place |
| `services_bank_accounts.snapshot_from_*` | shared by vendor, supplier, mechanic and driver payments |
| `models.FIN_SYSTEM_ACCOUNTS` | the catalogue, including the appended `DRIVER_OUTFLOW` |

---

## F. Exact next implementation step (not executed)

**Migrate `fin_txn`, `fin_accounts` and `fin_day_closures` into PostgreSQL, read-only, and serve
`GET /api/fin/day-book` from NestJS.**

Concretely, in order:
1. Add the three tables to `apps/api/src/db/schema.ts` — flat columns, `amount` as
   `numeric(14,2)`, `source_id`/`ref_source_key` as `text`, `source_shape` not needed (all three
   collections are uniform, unlike `vendor_payments`).
2. Extend `scripts/migrate-from-mongo.ts` with those collections, including the `source_id`
   tie-breaker column and the same exact-decimal sum verification.
3. Implement `GET /api/fin/day-book` against PostgreSQL, using the Gate 7s Fastify shadow
   (`backend-node/src/routes/fin-day-book.ts`) as the contract reference, not the Python source.
4. Extend `scripts/parity-vs-python.ts` with day-book cases across date ranges, account filters
   and empty results.
5. Then the remaining five migrated reads, one at a time.

**Prerequisite: resolved.** Item 7 is settled — each scope's account set is preserved exactly,
and no code or data change is required before slice 2a.

**Explicitly not in this step:** any write, the projection, reconciliation, and
`POST /api/fin/reproject`.
