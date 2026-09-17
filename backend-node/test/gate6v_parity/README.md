# TRUKVIA · Phase-3 · Gate-6v · VendorBill read-only shadow — Parity Harness

**Endpoints under parity**
- `GET /api/vendor-bills?vendor_id=&vehicle_id=&repair_event_id=&trip_id=`
- `GET /api/vendor-bills/{bid}`

**Python source of truth**
- `backend/routers/vendor_bills.py::list_vendor_bills` (lines 66–83)
- `backend/routers/vendor_bills.py::get_vendor_bill` (lines 124–134)

**Class**: C — pure read. GET handlers execute ONLY
`db.vendor_bills.find(...).sort([('bill_date', -1)]).to_list(5000)`
and `.find_one(...)`. Zero writer hook / audit / backfill / recompute /
FinTxn / approvals / policy / counters / idempotency / cross-collection
reads on the GET path.

## Data isolation

- Isolated DB: `trukvia_gate6v_parity_<epoch>` — dropped in `finally`.
- Never touches `test_database` or any TRUKVIA UAT tenant / login.
- Ports: Python `8198`, Node `8199`.

## Bound Gate-6v dimensions

1. **Soft-delete predicate** `is_deleted: {$ne: true}` on BOTH endpoints:
   - `is_deleted:true` → EXCLUDED
   - `is_deleted:false` → included
   - `is_deleted` missing → INCLUDED (MongoDB `$ne` matches missing keys)
   - `is_deleted:null` → included
2. **5000 cap** on LIST (matches Gate 6t/6u).
3. **`activeCompanyId()` consumed** — `X-Company-Id` owned override
   changes rowset; unowned / no-header falls back to default company.
4. **DETAIL 404 literal** — missing / wrong-company / soft-deleted bid
   ALL take the same branch → HTTP 404 with EXACT body
   `{"detail": "VendorBill not found"}`.
5. **Truthy-gate query params** — empty string / missing → filter omitted.
   All four query params are plain string equality with no coercion.
6. **Sort** — `bill_date` DESC (ISO string lexicographic).
7. **Projection** — `{_id: 0, user_id: 0}`.

## Cases

17 cases covering:
- happy list
- empty result
- each individual filter (`vendor_id`, `vehicle_id`, `repair_event_id`, `trip_id`)
- combined filters
- empty-string truthy-gate omission
- owned X-Company-Id override
- unowned X-Company-Id fallback
- cross-user isolation
- detail happy
- detail unknown bid → 404
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
python3 backend-node/test/gate6v_parity/harness.py
```

Results are written to `/tmp/gate6v_parity_results.json`; the disposable
DB is dropped in `finally` even on failure.

## Parity exceptions

None. All 17 cases use full-body comparison. Byte-identical output
required. Any deviation → parity FAIL.

## Gate-7 boundary

`POST` / `PUT` / `DELETE` `/api/vendor-bills` remain Python-authoritative
and are strictly out of Gate-6v scope. They fire `hook_after_source_write`,
`_log_audit`, cross-collection reference guards, and duplicate-bill
`bill_number` uniqueness enforcement — reserved for the Maker-Checker
port in Gate 7.
