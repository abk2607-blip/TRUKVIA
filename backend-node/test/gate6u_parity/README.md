# TRUKVIA · Phase-3 · Gate-6u · MechanicWorkOrder read-only shadow — Parity Harness

**Endpoints under parity**
- `GET /api/mechanic-work-orders?mechanic_id=&vehicle_id=&repair_event_id=&trip_id=`
- `GET /api/mechanic-work-orders/{wid}`

**Python source of truth**
- `backend/routers/mechanic_work_orders.py::list_mechanic_work_orders` (lines 63–80)
- `backend/routers/mechanic_work_orders.py::get_mechanic_work_order` (lines 113–123)

**Class**: C — pure read. GET handlers execute ONLY
`db.mechanic_work_orders.find(...).sort([('work_date', -1)]).to_list(5000)`
and `.find_one(...)`. Zero writer hook / audit / backfill / recompute /
FinTxn / approvals / policy / counters / idempotency / cross-collection
reads on the GET path.

## Data isolation

- Isolated DB: `trukvia_gate6u_parity_<epoch>` — dropped in `finally`.
- Never touches `test_database` or any TRUKVIA UAT tenant / login.
- Ports: Python `8196`, Node `8197`.

## Bound Gate-6u dimensions

1. **Soft-delete predicate** `is_deleted: {$ne: true}` on BOTH endpoints:
   - `is_deleted:true` → EXCLUDED
   - `is_deleted:false` → included
   - `is_deleted` missing → INCLUDED (MongoDB `$ne` matches missing keys)
   - `is_deleted:null` → included
2. **5000 cap** on LIST (matches Gate 6t).
3. **`activeCompanyId()` consumed** — `X-Company-Id` owned override
   changes rowset; unowned / no-header falls back to default company.
4. **DETAIL 404 literal** — missing / wrong-company / soft-deleted wid
   ALL take the same branch → HTTP 404 with EXACT body
   `{"detail": "MechanicWorkOrder not found"}`.
5. **Truthy-gate query params** — empty string / missing → filter omitted.
   All four query params are plain string equality with no coercion.
6. **Sort** — `work_date` DESC (ISO string lexicographic).
7. **Projection** — `{_id: 0, user_id: 0}`.

## Cases

17 cases covering:
- happy list
- empty result
- each individual filter (`mechanic_id`, `vehicle_id`, `repair_event_id`, `trip_id`)
- combined filters
- empty-string truthy-gate omission
- owned X-Company-Id override
- unowned X-Company-Id fallback
- cross-user isolation
- detail happy
- detail unknown wid → 404
- detail wrong-company → 404
- detail soft-deleted → 404
- no-auth 401 `Not authenticated`
- invalid-bearer 401 `Invalid session`

Plus zero-write aggregate: `node_write_events = 0` across all cases,
snapshotting every established business collection before/after each
request pair.

## How to run

```bash
cd /app
python3 backend-node/test/gate6u_parity/harness.py
```

Results are written to `/tmp/gate6u_parity_results.json`; the disposable
DB is dropped in `finally` even on failure.

## Parity exceptions

None. All 17 cases use full-body comparison. Byte-identical output
required. Any deviation → parity FAIL.

## Gate-7 boundary

`POST` / `PUT` / `DELETE` `/api/mechanic-work-orders` remain
Python-authoritative and are strictly out of Gate-6u scope. They fire
`hook_after_source_write` and audit logs — reserved for the Maker-Checker
port in Gate 7.
