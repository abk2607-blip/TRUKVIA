# Phase 3 · Gate 6s · Live Python↔Node parity harness

Covers exactly one read-only surface:

* `GET /api/audit-logs?module=&action=&entity_id=&start=&end=&limit=`

## Data safety

* Isolated timestamped disposable DB: `trukvia_gate6s_parity_<timestamp>`.
* Dropped in `finally` regardless of pass/fail.
* Never touches `test_database`, `trukvia_uat`, or any real tenant.
* Never mutates login / account / company / audit-log data.

## Class-C stance

Python handler (`backend/routers/audit_router.py::list_audit_logs`,
lines 29–49) executes ONLY:

```python
q = {"user_id": user["user_id"]}
if module:    q["module"] = module
if action:    q["action"] = action
if entity_id: q["entity_id"] = entity_id
if start or end:
    rng = {}
    if start: rng["$gte"] = start
    if end:   rng["$lte"] = end + "T23:59:59"
    q["timestamp"] = rng
docs = await db.audit_logs.find(q, {"_id": 0, "user_id": 0}) \
    .sort("timestamp", -1).to_list(min(int(limit), 500))
return docs
```

Zero writer hook, zero audit call, zero backfill, zero recompute, zero
FinTxn / approvals / policy / counters / idempotency touch, zero
unrelated collection reads.

## Preserved semantics (bind precisely — new dimensions)

| Dimension | Gate 6s (this gate) | Prior gates |
|-----------|---------------------|-------------|
| `activeCompanyId()` invocation | **NOT called** — Python has no `_active_company_id` | Gate 6r invokes it |
| Filter | `{user_id}` + truthy-gated `{module, action, entity_id}` + optional `{timestamp: {$gte, $lte}}` | varies |
| Range upper bound | `end + "T23:59:59"` **literal string concat** | n/a |
| Projection | `{_id:0, user_id:0}` | matches 6q |
| Sort | `timestamp` DESC | varies |
| Cap | `min(int(limit), 500)` — hard 500 ceiling | matches most |
| 422 shape | Pydantic-v2 `int_parsing` on `?limit=abc` — observed live | Gate 6r bound `missing` |
| Auth order | 401 short-circuits 422 | universal |
| RBAC / masking | none | n/a |
| Cross-collection reads | none | matches 6q |

## Cases (14 request cases + 1 aggregate)

The harness observes the raw Python 422 body once at startup and
records it in `observed_py_422_int_parsing` inside the results JSON
for Pydantic-version drift monitoring.

1. happy list · u1 · 7 rows DESC by timestamp
2. empty list · u2 module=trip → `[]`
3. module filter · invoice → 3 rows
4. action filter · create → 5 rows
5. entity_id filter · inv-1 → 3 rows
6. combined · module + action + entity_id → 1 row
7. `end=2026-01-03` → `$lte` 2026-01-03T23:59:59 (literal binding)
8. range · start + end → 3 rows
9. default limit=200 · 7 rows
10. limit=600 → capped to 500 (seed 7 → 7 returned; caller cap enforced against >500 requests)
11. invalid limit=abc → 422 Pydantic-v2 `int_parsing` body (BODY-EXACT)
12. no auth + invalid limit=abc → 401 `Not authenticated` (auth-order: BEFORE 422)
13. invalid bearer → 401 `Invalid session`
14. expired session → 401 `Session expired`

AGGREGATE:
15. Zero Node business writes across ALL cases (tracked collections
    include `audit_logs` plus 25 others). Python's rolling `user_sessions`
    refresh is excluded via post-Python-snapshot baseline.

## Compare mode

All cases use `full` structural JSON equality. The 422 case attempts
BODY-EXACT parity — if Pydantic version drift injects extra keys the
harness records both bodies inline for a targeted fix.

## Ports

Python: `8192`  ·  Node: `8193`  (non-overlapping with prior gates 6m–6r).

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6s_parity/harness.py
```

Result JSON: `/tmp/gate6s_parity_results.json` (includes
`observed_py_422_int_parsing` for audit).

## Writer boundary (out of scope)

The audit-log **writer** side (`_log_audit` in `backend/audit.py`,
invoked from many business writers) remains Python-authoritative
until Gate 7 (Maker-Checker framework port). Gate 6s only shadows
the READ path.
