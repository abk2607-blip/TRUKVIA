# Gate 6z · VendorPayments list · Live parity harness

Shadow target: `GET /api/vendors/{vid}/payments`

## Scope

Class-C read-only shadow of `backend/routers/vendors.py::list_vendor_payments`
(lines 171–179). Python handler executes ONLY:

```python
rows = await db.vendor_payments.find(
    {"user_id": uid, "company_id": cid, "vendor_id": vid,
     "is_deleted": {"$ne": True}},
    {"_id": 0, "user_id": 0},
).sort("date", -1).to_list(5000)
return rows
```

Zero writer hook / audit / backfill / recompute / FinTxn / approvals /
policy / counters / idempotency / cross-collection reads on the GET path.

## Gate-6z bindings verified

1. **Single soft-delete predicate** — `is_deleted: {$ne: True}` only.
   No `is_reversed` predicate (matches Python source exactly).
2. **Projection strips both `_id` and `user_id`** — differs from
   Gate 6y (drivers) which keeps `user_id`.
3. **5000 cap** — matches every prior Class-C list gate except 6y.
4. **date DESC** — canonical ordering.
5. **`activeCompanyId()` consumption** — X-Company-Id owned override /
   unowned fallback / no-header default.
6. **NO 404 branch** — unlike Gate 6y (drivers) and DETAIL gates,
   Gate 6z performs NO vendor-existence lookup. Unknown / wrong-company /
   no-match → HTTP 200 `[]`.

## UAT data preservation

- Isolated DB name: `trukvia_gate6z_parity_<unix_ts>`.
- Dropped in `finally` regardless of pass/fail.
- Never touches `test_database` or any TRUKVIA UAT tenant / login.

## Ports

- Python (uvicorn): `8206`
- Node   (dist):    `8207`

Both processes started and torn down inside the harness.

## Run

```bash
cd /app/backend-node
npm run build           # ensure dist/server.js is fresh
python test/gate6z_parity/harness.py
```

Results file: `/tmp/gate6z_parity_results.json`.

Exit code:
- `0` — all cases PASS and zero Node write events.
- `1` — parity or zero-write violation.
- `2` — process bring-up failure.

## Case matrix (10 cases + zero-write aggregate)

| # | Description                                           | Expected |
|---|-------------------------------------------------------|----------|
| 1 | list happy · u1 · co-a · ven-1 · DESC by date         | 200 body |
| 2 | empty vendor (no payments)                            | 200 `[]` |
| 3 | unknown vendor (no existence lookup)                  | 200 `[]` |
| 4 | different vendor · ven-2                              | 200 body |
| 5 | cross-user · u2 · ven-1                               | 200 body |
| 6 | owned X-Company-Id · co-a-alt                         | 200 body |
| 7 | unowned X-Company-Id · falls back to default          | 200 body |
| 8 | no auth                                               | 401 `Not authenticated` |
| 9 | invalid bearer                                        | 401 `Invalid session`   |
|10 | expired bearer                                        | 401 `Session expired`   |
|11 | Node write events across all cases                    | 0        |
