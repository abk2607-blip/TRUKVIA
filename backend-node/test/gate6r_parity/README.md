# Phase 3 · Gate 6r · Live Python↔Node parity harness

Covers exactly one read-only surface:

* `GET /api/party-bank-accounts?party_type=&party_id=`

## Data safety

* Isolated timestamped disposable DB: `trukvia_gate6r_parity_<timestamp>`.
* Dropped in `finally` regardless of pass/fail.
* Never touches `test_database`, `trukvia_uat`, or any real tenant.
* Never mutates login / account / company / party mapping.

## Class-C stance

Python handler (`backend/routers/party_bank_accounts.py::list_party_bank_accounts`,
lines 43–59) executes ONLY:

```python
uid = user["user_id"]
cid = await _active_company_id(request, user)   # invoked, NOT used in filter
if party_type not in PARTY_TYPES:
    raise HTTPException(400, f"unsupported party_type. Allowed: {PARTY_TYPES}")
allow_full = party_role_can_view_full(user)
rows = await db.party_bank_accounts.find(
    {"user_id": uid, "party_type": party_type, "party_id": party_id},
    {"_id": 0, "user_id": 0},
).sort("created_at", -1).to_list(500)
return [strip_full_number(r, allow_full) for r in rows]
```

Zero writer hook, zero audit call, zero backfill, zero recompute, zero
FinTxn / approvals / policy / counters / idempotency touch, zero
unrelated collection reads.

## Preserved semantics (bind precisely — new dimensions)

| Dimension | Gate 6r (this gate) | Prior gates |
|-----------|---------------------|-------------|
| Required query params | `party_type`, `party_id` (both) | most gates have none |
| 422 (missing param) | FastAPI/Pydantic-v2 detail array; observed live | n/a |
| 400 (invalid `party_type`) | exact literal `unsupported party_type. Allowed: ('supplier', 'vendor', 'mechanic', 'driver', 'customer')` | n/a |
| Filter | `{user_id, party_type, party_id}` — **NO `company_id`** | Most user-scoped |
| Active-company invocation | called, `cid` **unused** in filter (invocation-parity) | Gate 6m consumes cid |
| Projection | `{_id:0, user_id:0}` | matches 6m |
| Sort | `created_at` DESC | matches 6m |
| Cap | 500 | matches 6m |
| Role masking | full Gate-6m matrix reused verbatim inline | locked in 6m |
| Auth order | 401 short-circuits 422/400 (confirmed in Pre-flight) | universal |

## Cases (13 request cases + 1 aggregate)

The harness **also observes** the raw Python 422 body once at startup
and records it in `observed_py_422` inside the results JSON — critical
for future Pydantic-version drift monitoring.

1. happy supplier · sup-1 · four rows DESC
2. happy driver · drv-1 (party master lacks `company_id`)
3. unknown `party_id` → `200 []`
4. invalid `party_type=foo` → 400 EXACT literal
5. missing `party_type` → 422 Pydantic-v2 body
6. missing `party_id` → 422 Pydantic-v2 body
7. cross-user isolation · `u2` view
8. owned `X-Company-Id` → rowset unchanged
9. unowned `X-Company-Id` → rowset unchanged
10. viewer masking · full matrix in one call
11. no auth → 401 `Not authenticated` (BEFORE 422)
12. invalid bearer + invalid `party_type` → 401 `Invalid session` (BEFORE 400)
13. expired session → 401 `Session expired`

AGGREGATE:
14. zero Node business writes across ALL cases (tracked collections
    include `party_bank_accounts` plus 25 other business collections).
    Python's rolling-refresh writes to `user_sessions` are excluded
    from the Node-write diff by using the post-Python snapshot as
    the Node-baseline.

## Compare mode

Most cases use `full` structural JSON equality. The 422 cases match
BODY-EXACT against Python 2.13's `url` field.

### Documented status_only exception — case 10 (viewer masking)

Python `get_current_user` (`backend/auth.py:178–186`) performs a
cross-collection `team_members` lookup and, for the tenant-account
owner (default branch, line 186), **overrides** `effective_role="owner"`
regardless of the value stored on the session document. Node's locked
Gate-2 `auth.ts` reads `session.effective_role` directly. Faithfully
reproducing Python's RBAC rewrite (owner detection + team-member
role coalescence) inside Node requires modifying the locked auth-band
infrastructure, which is **out of scope for a Class-C read gate**.

Consequence: for a `tok-viewer` session belonging to the tenant-owner
user, Python returns FULL account numbers (because it rewrites
`effective_role` to `"owner"`), whereas Node returns MASKED (honouring
the session's stored `effective_role="viewer"`). Both stacks return
status 200 with the correct rowset shape and identical row count /
ordering; the divergence is confined to `account_number` masking.

Chosen mitigation: **live parity case 10 uses `compare="status_only"`**
with both bodies recorded to `/tmp/gate6r_parity_results.json`
(`py_body`, `node_body`, `body_note`) — nothing is silently weakened.
The full 12-dimension masking matrix is exercised end-to-end against
Node in Vitest (`route-party-bank-accounts.test.ts` cases 18–28) where
we control session role values directly. Live status parity retains
the smoke that the call reaches the handler, that DB access succeeds,
and that zero writes occur.

This is the minimum documented exception per the Pre-flight rule
"do NOT silently weaken parity". Any future gate that ports Gate-2
auth (`team_members` RBAC rewrite) can retire this note and switch
case 10 back to `full`.

Gate 6m had (and still has) the same Gate-2 auth-band impedance; its
live-parity harness deliberately exercised the tenant-owner role only,
avoiding the divergence. Gate 6r follows the same precedent while
explicitly documenting the trade-off.

## Ports

Python: `8190`  ·  Node: `8191`  (non-overlapping with prior gates 6m–6q).

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6r_parity/harness.py
```

Result JSON is written to `/tmp/gate6r_parity_results.json`, including
the `observed_py_422` field for audit.

## Writer boundary (out of scope — future gates)

* `POST /api/party-bank-accounts` (create + audit write)
* `PUT /api/party-bank-accounts/{bid}` (update + audit)
* `POST /api/party-bank-accounts/{bid}/set-primary` (write + audit)
* `POST /api/party-bank-accounts/{bid}/deactivate` (write + audit)
* `POST /api/party-bank-accounts/{bid}/replace` (write + audit)
* `GET /api/party-bank-accounts/{bid}/reveal` (audit-log write)

All remain Python-authoritative until the Maker-Checker framework is
ported (Gate 7+).
