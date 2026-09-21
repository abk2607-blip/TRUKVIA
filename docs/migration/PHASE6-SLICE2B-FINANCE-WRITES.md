# Phase 6 · Slice 2b — Finance writes

Scope: exactly two endpoints.

```
POST /api/fin/day-closures
POST /api/fin/day-closures/{close_date}/reopen
```

Explicitly out of scope and untouched: `/api/fin/reproject`,
`hook_after_source_write`, the `fin_txn` projection, `GET /api/fin/accounts`,
reconciliation. The Python implementation stays in place. Slice 2a is frozen at
`6d9be00` and is not reopened.

Source: [`backend/routers/fin_day_closing.py`](../../backend/routers/fin_day_closing.py),
`FinDayClosure` in `backend/models_iter150d.py`, `_log_audit` in
`backend/audit.py`, `_active_company_id` in `backend/company.py`.

## Are they self-contained?

Yes. Both handlers touch three collections and nothing else:

| Collection | Access |
| --- | --- |
| `fin_txn` | **read only**, inside `_capture_snapshot` |
| `fin_day_closures` | read + insert/update |
| `audit_logs` | insert, failure swallowed |

They call no projection, no reconciliation and no service layer. `fin_txn` is
only ever read, so nothing here can race the projection hook. This confirms
they are safe to port in isolation.

## Discovered write semantics

### Request pipeline order

Established empirically against the running Python server — this order is not
what reading the code suggests, and getting it wrong is a silent parity break:

1. **JSON parse** of the body → `422 json_invalid`. This happens *before*
   authentication, because FastAPI calls `await request.json()` in the route
   wrapper, outside `solve_dependencies`.
2. **Authentication** → `401`.
3. **Body structure** (`dict` required, must be an object) → `422`. This is
   inside `solve_dependencies`, so it runs *after* auth.
4. Handler body.

So `POST` with a bad token and unparseable JSON returns **422**, while the same
token with `[1,2]` returns **401**. An empty body is not a parse error — it is a
`missing` field error at step 3. A body sent without a JSON content-type is not
parsed at all.

CPython's JSON decoder errors are reproduced with their exact message and
character offset (`loc: ["body", pos]`, `ctx.error`). Verified cases:

| Body | pos | `ctx.error` |
| --- | --- | --- |
| `not json` | 0 | Expecting value |
| `{` | 1 | Expecting property name enclosed in double quotes |
| `{"a"` | 4 | Expecting ':' delimiter |
| `{"a":1,}` | 7 | Expecting property name enclosed in double quotes |
| `{"a":1}{` | 7 | Extra data |
| `[1,2` | 4 | Expecting ',' delimiter |
| `{"a":"x` | 5 | Unterminated string starting at |
| `{"a":"<TAB>"}` | 6 | Invalid control character at |
| `{"a":"\q"}` | 6 | Invalid \escape |
| `{"a":"\u12"}` | 7 | Invalid \uXXXX escape |
| `01` | 1 | Extra data |

CPython **accepts** `NaN` and `Infinity`; `JSON.parse` rejects them. The port
therefore cannot delegate to `JSON.parse` and needs its own scanner.

### `POST /api/fin/day-closures`

In order, after the pipeline above:

1. `_require_owner` — `(effective_role or role).lower() != "owner"` → **403**.
   Note this precedes company resolution.
2. `_active_company_id` — `X-Company-Id` if it belongs to the user, else the
   default company (which it creates if absent).
3. `close_date = (body.close_date or "").strip()`; empty → **400**
   `close_date is required`.
4. `date.fromisoformat` → **400** `close_date must be ISO YYYY-MM-DD`.
5. `d > now_utc().date()` → **422** `close_date cannot be in the future (v1
   accepts today or past)`.
6. `close_notes = (body.close_notes or "").strip()`.
7. Load any existing closure, take `now`, then **capture the snapshot** — note
   the snapshot is computed *before* the 409 check, so an already-closed day
   still pays for the scan. No write, so it is observationally invisible.
8. existing `status == "closed"` → **409** `Day {d} is already closed`.
9. existing `status == "reopened"` → **re-close** branch.
10. otherwise → **fresh insert**.

**Snapshot** (`_capture_snapshot`) is cumulative, not per-day: all `fin_txn`
with `status: "active"` and `txn_date <= close_date`, for the scope. Per
`account_code` it accumulates `in`/`out` as raw floats, then rounds each to 2,
and finally computes `net = round(in - out, 2)` **from the already-rounded
values**. Key order is the cursor's natural order — the find has no sort — and
each account's sub-object is always `in`, `out`, `net`.

**Fresh insert** builds `FinDayClosure`, whose `id` is `fdc_` + 16 hex chars.
`closed_at` and `created_at` are two *separate* `now_utc()` calls, so they can
differ in the microseconds; `modified_at` is `""`. `history[0].at` is
`doc["closed_at"]`, **not** the handler's `now`, which is unused on this path.
A duplicate key from the unique `(user_id, company_id, close_date)` index is
turned into **409** `Day {d} already closed (concurrent write)`.

**Re-close** appends a `closed` history event carrying its own snapshot, resets
`reopened_at`/`reopened_by`/`reopen_reason` to `""`, and sets `modified_at`.
It uses the handler's `now` for every timestamp.

Response key order is the model's declaration order with `_id` and `user_id`
removed and `company_id` kept — identical on both branches, and identical to
the order slice 2a already emits for the GETs.

Audit: module `fin_day_closure`, action `close` (with `notes`) or `reclose`
(without), `changes = {"count": n, "accounts": len(snap)}`.

### `POST /api/fin/day-closures/{close_date}/reopen`

1. `_require_owner` → **403** — before anything else, including the path date.
2. `date.fromisoformat(close_date)` → **400** `close_date must be ISO
   YYYY-MM-DD`.
3. `_active_company_id`.
4. `reason = (body.reopen_reason or "").strip()`; empty → **400**
   `reopen_reason is required`.
5. Missing closure → **404** `No closure exists for {close_date}`.
6. Already `reopened` → **409** `Day {close_date} is already reopened`.
7. `$set` status/`reopened_*`/`history`/`modified_at`, all from one `now`;
   re-read with `{_id: 0, user_id: 0}` and return.

Audit: action `reopen`, `changes = {"reason": reason}`.

### Idempotency

There is none, and that is deliberate: a second close is a 409, a second reopen
is a 409. The only repeatable transition is reopen → close, which appends to
`history` rather than replacing it. The port must preserve that, including the
fact that re-close does **not** reset `created_at`.

## Plan

1. `src/common/py-body.ts` — CPython-compatible JSON scanner and the FastAPI
   422 envelopes. New shared module; wired only into the new routes, so no
   slice-1b route changes behaviour.
2. `src/fin/fin-writes.service.ts` — both handlers against MongoDB, reading
   `fin_txn` from MongoDB (not the Postgres copy) so the snapshot is computed
   from the source of truth and in the same natural order.
3. `src/fin/fin-writes.controller.ts` — the pipeline order above.
4. Refresh the Postgres `fin_day_closure` copy from the document just written,
   inserting `snapshot`/`history` as pre-rendered Python JSON text so `0.0`
   survives.
5. Extend `scripts/write-parity.ts` with a staff fixture and day-closure cases.
6. Unit tests for the scanner and the snapshot arithmetic.

MongoDB remains the source of truth; Postgres stays derived and rebuildable.

All six steps were implemented. What follows is what the work produced.

## Results

`npx tsx scripts/write-parity.ts` sends every case to Python and to NestJS,
each against its own throwaway MongoDB, and compares the response **and** the
resulting documents in `fin_day_closures` and `audit_logs`:

```
cases 72   PASS 71   KNOWN DIVERGENCE 1   FAIL 0
```

That includes the 26 pre-existing vendor cases, which still pass — the raw-body
middleware is scoped to the two new paths and does not disturb slice 1.

The harness compares *parsed* JSON, which cannot see float rendering, so one
extra check compares the raw bytes of a close response with only ids and
timestamps blanked. It passes, which is what proves a balance of exactly 52400
comes back as `52400.0` and not `52400`.

Unit tests: `test/fin-writes.test.ts`, 43 cases. Suite total 131.

### Two things the port had to get right, and nearly didn't

**Snapshot balances are Python floats.** The Node driver serialises an integral
JS number as BSON int32, so an even balance would have been stored with a
different BSON type than pymongo stores, and rendered as `52400`. Balances are
therefore written as `Double` and rendered through the float path; only
`snapshot_source_count`, a genuine int, is left alone.

**`round()` is half-to-even against the true binary value.** `round(2.675, 2)`
is `2.67`, because the nearest double to 2.675 is below the midpoint. The
scale-by-100 approach reads that as a tie and returns `2.68` — a one-paisa
error in a financial snapshot. `src/common/py-round.ts` decides in exact BigInt
arithmetic instead. Expected values in the tests came from running the real
interpreter.

## Findings

### 1. Python hangs — does not 500 — on a non-string `close_date`

`(body.get("close_date") or "").strip()` raises `AttributeError` for any truthy
non-string, so `{"close_date": 20260903}` faults the handler. The response is
not a 500: **the request never completes.** `ApprovalGateMiddleware`
re-dispatches the request on an unhandled exception, and the re-dispatch awaits
a request body whose receive channel is already drained, so it blocks forever
and holds the worker.

This is reachable by any authenticated owner with a one-line request body, and
it costs a worker per attempt. It is pre-existing production behaviour, not
something this slice introduces, and it is **not fixed here** — the brief for
2b excludes changing the Python implementation. It is recorded for a decision.

The port does not reproduce it. A non-string is treated as absent, giving
`400 close_date is required`, which is what the handler was trying to do. That
is the one KNOWN DIVERGENCE in the harness run, reported rather than hidden.

### 2. Slice 2a's `roundHalfEven2` mis-rounds exact-midpoint doubles

The same 2.675 case: the helper in `fin-reads.service.ts` returns `2.68` where
Python returns `2.67`. It has not produced a wrong answer in practice, because
every value it is given already has at most two decimals — day-book totals are
accumulated as integer paisa and only divided at the end, so a true midpoint
never reaches it. It is latent, not active. Slice 2a is frozen at `6d9be00` and
was not reopened to change it; `pyRound2` is the correct implementation for
whoever does.

### 3. Deliberate narrowing in the JSON scanner

CPython validates a `\uXXXX` escape with `len(esc) == 4 and esc[1] not in 'xX'`
followed by `int(esc, 16)`, and Python's `int()` also accepts a sign,
surrounding whitespace and digit-separating underscores — so CPython really
does accept `\u+123`. The port requires four hex digits. Both answer 422 on
everything a real client sends; the difference is only in which malformed
escapes are accepted.

## MongoDB write impact

Per successful request, identical to Python:

| Request | Writes |
| --- | --- |
| fresh close | 1 insert into `fin_day_closures`, 1 insert into `audit_logs` |
| re-close | 1 update of `fin_day_closures`, 1 insert into `audit_logs` |
| reopen | 1 update of `fin_day_closures`, 1 insert into `audit_logs` |
| any rejected request | none |

`fin_txn` is only ever read. No projection, no reconciliation, no account
seeding. An audit insert that fails is swallowed, as in Python, so it can never
fail the request. After the Mongo write the Postgres `fin_day_closure` row is
refreshed; that refresh is wrapped so a Postgres failure costs a stale read and
never a lost write.
