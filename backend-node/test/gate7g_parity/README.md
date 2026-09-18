# Gate 7g · Approvals list · Live parity harness

Shadow target: `GET /api/approvals`

## Scope

Class-C read-only shadow of `backend/routers/approvals.py::api_list_approvals`
(L33-46) → `services_approvals.list_approvals` (L527-541).

Python:
```python
q = {"user_id": uid, "company_id": company_id}
if status:            q["status"] = status
elif not include_all: q["status"] = {"$in": ["PENDING_APPROVAL", "REJECTED", "WITHDRAWN"]}
if entity_kind:       q["entity_kind"] = entity_kind
db.approvals.find(q, {"_id": 0}).sort("created_at", -1).limit(min(500, limit))
```

Zero writer hook / audit / backfill / recompute / FinTxn / approvals
mutation / counters / idempotency / cross-collection reads on the GET path.

Approval writers remain Python-authoritative and OUT OF SCOPE:
- `POST /api/approvals`
- `POST /api/approvals/{aid}/{approve|reject|withdraw|resubmit}`

## Query contract

| Param | Type | Default | Constraint |
|---|---|---|---|
| `status` | Optional[str] | None | truthy → exact equality; falsy → default $in |
| `entity_kind` | Optional[str] | None | truthy → exact equality; falsy → omit |
| `include_all` | bool | False | Pydantic v2 bool_parsing; invalid → 422 |
| `limit` | int | 200 | ge=1, le=500; invalid → int_parsing/greater_than_equal/less_than_equal 422 |

## NEW parity axes for Gate 7g

| Axis | Detail |
|---|---|
| Validation precedence | **AUTH PRECEDES QUERY VALIDATION.** FastAPI 0.110.1 `solve_dependencies` (fastapi/dependencies/utils.py L549) runs `Depends(get_current_user)` BEFORE query params reach `request_params_to_args` (L610). A raised `HTTPException(401)` short-circuits the coroutine, so query validation never runs. Therefore: unauthenticated + invalid query → 401; authenticated + invalid query → 422; valid query + no bearer → 401 |
| `bool_parsing` 422 (include_all) | Pydantic 2.13.4 envelope; accepted spellings true/True/TRUE, false/False/FALSE, 1, 0, yes, no, on, off (case-insensitive) |
| `int_parsing` 422 (limit) | Rejects blank, non-int, floats; accepts leading `+` and surrounding whitespace |
| `greater_than_equal` 422 | ctx: {ge: 1}; msg "Input should be greater than or equal to 1" |
| `less_than_equal` 422 | ctx: {le: 500}; msg "Input should be less than or equal to 500" |
| Projection `{_id: 0}` | Strips ONLY `_id`; **user_id PRESERVED** — first Class-C shadow to preserve `user_id` |
| Conditional filter | 3-way status branching (`status` truthy / falsy+include_all=false / falsy+include_all=true) |
| Sort | `created_at` DESC; distinct timestamps in fixture (no manufactured tie-breaker) |
| Response envelope | Bare JSON array |

## UAT data preservation

- Isolated DB: `trukvia_gate7g_parity_<unix_ts>`, dropped in `finally`.
- Never touches `test_database` or any TRUKVIA UAT tenant.

## Ports

- Python (uvicorn): `8220`
- Node   (dist):    `8221`

## Run

```bash
cd /app/backend-node
npm run build
python test/gate7g_parity/harness.py
```

Results file: `/tmp/gate7g_parity_results.json`.

Exit code: `0` on all-pass zero-write; `1` on parity/zero-write violation;
`2` on process bring-up failure.

## Case matrix (32 cases + zero-write aggregate)

| # | Description | Expected |
|---|---|---|
| 1  | include_all=xyz → 422 bool_parsing | 422 body |
| 2  | limit=abc → 422 int_parsing | 422 body |
| 3  | limit=0 → 422 greater_than_equal (ge=1) | 422 body |
| 4  | limit=501 → 422 less_than_equal (le=500) | 422 body |
| 5  | limit=1.5 → 422 int_parsing (no float coercion) | 422 body |
| 6  | no auth + invalid include_all → 401 (auth precedes query) | 401 body |
| 6.5| no auth + invalid limit → 401 (auth precedes query) | 401 body |
| 7  | no auth · valid query → 401 Not authenticated | 401 body |
| 8  | invalid bearer → 401 Invalid session | 401 body |
| 9  | expired bearer → 401 Session expired | 401 body |
| 10 | include_all=1 accepted → true | 200 body |
| 11 | include_all=0 accepted → false | 200 body |
| 12 | include_all=yes accepted | 200 body |
| 13 | include_all=on accepted | 200 body |
| 14 | default → PENDING/REJECTED/WITHDRAWN DESC (a4/a3/a2/a1) | 200 body |
| 15 | include_all=true → all statuses DESC (a6..a1) | 200 body |
| 16 | include_all=false → same as default | 200 body |
| 17 | status=APPROVED → only a5 | 200 body |
| 18 | status=APPROVED + include_all=true → status wins → a5 | 200 body |
| 19 | status=NONEXISTENT → [] | 200 body |
| 20 | status=approved (lowercase) → [] (case-sensitive) | 200 body |
| 21 | blank status → default $in | 200 body |
| 22 | entity_kind=invoice → only a2 | 200 body |
| 23 | entity_kind=trip + include_all=true → a1,a3,a5,a6 DESC | 200 body |
| 24 | limit=2 → first 2 of default DESC | 200 body |
| 25 | limit=1 accepted (ge=1 boundary) | 200 body |
| 26 | limit=500 accepted (le=500 boundary) | 200 body |
| 27 | limit=+1 accepted (Pydantic leading + tolerance) | 200 body |
| 28 | owned X-Company-Id co-a-alt → a-alt only | 200 body |
| 29 | unowned X-Company-Id co-b → fallback co-a → default rows | 200 body |
| 30 | cross-user u2 default → a-u2-1 | 200 body |
| 31 | cross-user u2 + include_all=true → a-u2-2, a-u2-1 DESC | 200 body |
| 32 | Node write events across all cases | 0 |

Body compare mode: `full` for every case.

## Observed results

Filled in at run time — see `/tmp/gate7g_parity_results.json`.
