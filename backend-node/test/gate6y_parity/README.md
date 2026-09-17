# TRUKVIA · Phase-3 · Gate-6y · DriverPayment list read-only shadow — Parity Harness

**Endpoint under parity**
- `GET /api/drivers/{did}/payments`

**Python source of truth**
- `backend/routers/driver_payments.py::_ensure_driver` (lines 40–45)
- `backend/routers/driver_payments.py::list_driver_payments` (lines 48–56)

**Class**: C — pure read. Handler executes exactly:
1. `db.drivers.find_one({user_id, company_id, id: did}, {_id: 0})`
2. `db.driver_payments.find({... is_deleted:{$ne:True}}, {_id: 0}).sort([('date', -1)])`
   iterated via unbounded async cursor.

Zero writer hook / audit / backfill / recompute / FinTxn / approvals /
policy / counters / idempotency / cross-collection writes.

## Data isolation

- Isolated DB: `trukvia_gate6y_parity_<epoch>` — dropped in `finally`.
- Never touches `test_database` or any TRUKVIA UAT tenant / login.
- Ports: Python `8204`, Node `8205`.

## Bound Gate-6y NEW dimensions

1. **Cross-collection pre-check** on `drivers` — unknown /
   wrong-company `did` → HTTP 404 with exact body
   `{"detail": "Driver not found"}`.
2. **Projection asymmetry** — payment projection is `{_id: 0}` ONLY.
   `user_id` REMAINS in every response document.
3. **NO 5000 cap** — Python uses `[d async for d in cur]` (unbounded).
   Node handler omits `.limit(...)` accordingly.
4. **Single soft-delete predicate** `is_deleted: {$ne: true}` — Mongo
   canonical semantics (missing key inclusive).
5. **`activeCompanyId()` consumed** in BOTH the driver pre-check and
   the payments filter.

## Cases

10 HTTP cases covering:
- valid driver with payments · drv-1 · [x1, x2] DESC (user_id present)
- valid driver with no payments · drv-empty → 200 []
- unknown driver → 404 `{"detail": "Driver not found"}`
- wrong-company driver → same 404
- cross-user · u2 · drv-u2 → [x-u2]
- owned X-Company-Id override · co-a-alt · drv-1 → [x-alt]
- unowned X-Company-Id fallback · co-b for u1 → default co-a
- no-auth 401 `Not authenticated`
- invalid-bearer 401 `Invalid session`
- expired-bearer 401 `Session expired`

Plus zero-write aggregate: `node_write_events = 0` across all cases,
snapshotting every established business collection (including `drivers`)
before/after each request pair.

## How to run

```bash
cd /app
python3 backend-node/test/gate6y_parity/harness.py
```

Results are written to `/tmp/gate6y_parity_results.json`; the disposable
DB is dropped in `finally` even on failure.

## Parity exceptions

None. All 10 HTTP cases use full-body comparison. Byte-identical output
required. Any deviation → parity FAIL.

## Gate-7 boundary

`POST` / `PUT` / `DELETE` under `/api/drivers/{did}/payments*` and
`POST /api/driver-payments/{pid}/correct` remain Python-authoritative
and are strictly out of Gate-6y scope. They fire
`hook_after_source_write`, `_log_audit`, party-bank + company-bank
snapshot captures, and enforce `_perm(user, "manage_bank_accounts")`
RBAC — reserved for the Maker-Checker port in Gate 7.
