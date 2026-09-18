# Gate 7f · Approvals pending-count · Live parity harness

Shadow target: `GET /api/approvals/summary/pending`

## Scope

Class-C read-only shadow of `backend/routers/approvals.py::api_pending_count`
(lines 49–56). Python handler:
```python
count = await db.approvals.count_documents({
    "user_id": user["user_id"], "company_id": cid,
    "status": "PENDING_APPROVAL",
})
return {"count": count}
```

Zero writer hook / audit / backfill / recompute / FinTxn / approvals
mutation / counters / idempotency / cross-collection reads on the GET path.

Approval writers remain Python-authoritative and OUT OF SCOPE:
- `POST /api/approvals`
- `POST /api/approvals/{aid}/approve`
- `POST /api/approvals/{aid}/reject`
- `POST /api/approvals/{aid}/withdraw`
- `POST /api/approvals/{aid}/resubmit`

## NEW parity axes for Gate 7f

| Axis | Detail |
|---|---|
| Collection | First read against `approvals` |
| Operator | First use of `count_documents` in the Node shadow |
| Filter | Fixed `{ user_id, company_id, status: "PENDING_APPROVAL" }` — no is_deleted, no is_active |
| Response | `{ "count": <integer> }` — no envelope, no extra fields |
| Query params | NONE |
| Error branches | Only 401 x3 — no 400/404/422 |

### Auth precedence

401 fires BEFORE any approvals access (cases 1-3 exercise this).

### Tie-order note

`count_documents` returns an integer — no sort or ordering dependency.

## UAT data preservation

- Isolated DB: `trukvia_gate7f_parity_<unix_ts>`, dropped in `finally`.
- Never touches `test_database` or any TRUKVIA UAT tenant.

## Ports

- Python (uvicorn): `8218`
- Node   (dist):    `8219`

## Run

```bash
cd /app/backend-node
npm run build
python test/gate7f_parity/harness.py
```

Results file: `/tmp/gate7f_parity_results.json`.

Exit code: `0` on all-pass zero-write; `1` on parity/zero-write violation;
`2` on process bring-up failure.

## Case matrix (7 cases + zero-write aggregate)

| # | Description                                                 | Expected |
|---|-------------------------------------------------------------|----------|
| 1 | no auth → 401 Not authenticated                             | 401 body |
| 2 | invalid bearer → 401 Invalid session                        | 401 body |
| 3 | expired bearer → 401 Session expired                        | 401 body |
| 4 | u1 · default co-a → count 3 PENDING                         | 200 body |
| 5 | owned X-Company-Id co-a-alt → count 1 (alt-company row)     | 200 body |
| 6 | unowned X-Company-Id co-b → fallback co-a → count 3         | 200 body |
| 7 | cross-user u2 · co-b → count 2 PENDING (isolation)          | 200 body |
| 8 | Node write events across all cases                          | 0        |

Body compare mode: `full` for every case. No relaxation.

## Observed results

Filled in at run time — see `/tmp/gate7f_parity_results.json`.
