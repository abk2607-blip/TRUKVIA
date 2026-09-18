# Gate 7i · Files list · Live parity harness

Shadow target: `GET /api/files`

## Scope

Class-C read-only shadow of `backend/routers/files.py::list_files`
(L174-186).

Python:
```python
@router.get("/files")
async def list_files(
    category: Optional[str] = None,
    linked_type: Optional[str] = None,
    linked_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    q = {"user_id": user["user_id"], "is_deleted": False}
    if category: q["category"] = category
    if linked_type: q["linked_type"] = linked_type
    if linked_id: q["linked_id"] = linked_id
    docs = await db.files.find(q, {"_id": 0, "user_id": 0}) \
        .sort("created_at", -1).to_list(500)
    return docs
```

Zero writer hook / audit / backfill / recompute / FinTxn / counters /
idempotency / cross-collection reads on the GET path. NO object-store
call on this GET path (upload/bulk-upload/delete/download/public
endpoints hold the storage-client calls).

Files writers remain Python-authoritative and OUT OF SCOPE:
- `POST /api/files/upload`, `POST /api/files/bulk-upload`
- `DELETE /api/files/{fid}`
- `GET /api/files/{fid}/download`, `GET /api/files/public/{obj_path:path}` (object-store egress)

## CRITICAL Gate 7i axis — USER-ONLY SCOPE

Base filter is `{user_id, is_deleted: false}`. There is **NO `company_id`**.
Node MUST NOT call `activeCompanyId()` for this route. Same-user files
across different `company_id` values remain visible; cross-user files
are excluded.

## Query contract

| Param | Type | Default | Constraint |
|---|---|---|---|
| `category` | Optional[str] | None | Truthy → exact equality; blank/omitted → drop. NO 422. |
| `linked_type` | Optional[str] | None | Truthy → exact equality; blank/omitted → drop. NO 422. |
| `linked_id` | Optional[str] | None | Truthy → exact equality; blank/omitted → drop. NO 422. |

## Parity axes

| Axis | Detail |
|---|---|
| Auth precedence | AUTH BEFORE QUERY VALIDATION (per Gate 7g). Route has NO 422 query surface — all three params are `Optional[str]`. |
| 401 literals | `Not authenticated` / `Invalid session` / `Session expired` |
| Tenant | **USER-ONLY. No `X-Company-Id` narrowing.** Same-user rows across any `company_id` visible; cross-user excluded. |
| Deleted | Exact `{"is_deleted": False}` equality — docs missing `is_deleted`, or with `null` / `true`, are ALL excluded. No `$ne` guard. |
| Projection `{_id: 0, user_id: 0}` | Strips both `_id` AND `user_id`; every other stored field preserved |
| Sort | `created_at` DESC |
| Cap | `.to_list(500)` |
| Response envelope | Bare JSON array; empty → 200 `[]` |

## UAT data preservation

- Isolated DB: `trukvia_gate7i_parity_<unix_ts>`, dropped in `finally`.
- Never touches `test_database` or any TRUKVIA UAT tenant.

## Ports

- Python (uvicorn): `8224`
- Node   (dist):    `8225`

## Run

```bash
cd /app/backend-node
npm run build
python test/gate7i_parity/harness.py
```

Results file: `/tmp/gate7i_parity_results.json`.

Exit code: `0` on all-pass zero-write; `1` on parity/zero-write violation;
`2` on process bring-up failure.

## Case matrix (22 cases + zero-write aggregate)

| # | Description | Expected |
|---|---|---|
| 1  | no bearer → 401 Not authenticated | 401 body |
| 2  | invalid bearer → 401 Invalid session | 401 body |
| 3  | expired bearer → 401 Session expired | 401 body |
| 4  | no query — u1 rows across mixed company_id DESC | 200 body |
| 5  | X-Company-Id co-a-alt (owned) MUST NOT narrow | 200 body ≡ case 4 |
| 6  | X-Company-Id co-b (unowned) MUST NOT narrow | 200 body ≡ case 4 |
| 7  | cross-user u2 default → only u2 rows DESC | 200 body |
| 8  | is_deleted=true excluded (f-del) — re-asserted | 200 body |
| 9  | category=general → f-alt, f-nocid, f1 DESC | 200 body |
| 10 | category=invoice → only f2 | 200 body |
| 11 | category=General (uppercase) → [] (case-sensitive) | 200 body |
| 12 | category=nonexistent → [] | 200 body |
| 13 | blank category → predicate dropped | 200 body |
| 14 | linked_type=invoice → only f2 | 200 body |
| 15 | linked_id=v-7 → only f3 | 200 body |
| 16 | blank linked_type → predicate dropped | 200 body |
| 17 | blank linked_id → predicate dropped | 200 body |
| 18 | unknown linked_type → [] | 200 body |
| 19 | unknown linked_id → [] | 200 body |
| 20 | category+linked_type+linked_id combined → f2 | 200 body |
| 21 | conflicting combo → [] | 200 body |
| 22 | u3 (no files) → 200 [] | 200 body |
| 23 | Node write events across all cases | 0 |

Body compare mode: `full` for every case.

## Observed results

Filled in at run time — see `/tmp/gate7i_parity_results.json`.
