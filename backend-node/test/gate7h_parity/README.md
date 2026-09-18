# Gate 7h · Fuel vehicle maps list · Live parity harness

Shadow target: `GET /api/fuel/vehicle-maps`

## Scope

Class-C read-only shadow of `backend/routers/fuel_import.py::list_fuel_vehicle_maps`
(L37-47).

Python:
```python
@router.get("/fuel/vehicle-maps")
async def list_fuel_vehicle_maps(request: Request, user=Depends(get_current_user),
                                 source: Optional[str] = None):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    q: dict = {"user_id": uid, "company_id": cid}
    if source in ("iocl", "bpcl"):
        q["source"] = source
    docs = await db.fuel_vehicle_maps.find(q, {"_id": 0, "user_id": 0}) \
        .sort("source_vehicle_ref", 1).to_list(5000)
    return docs
```

Zero writer hook / audit / backfill / recompute / FinTxn / counters /
idempotency / cross-collection reads on the GET path.

Fuel writers remain Python-authoritative and OUT OF SCOPE:
- `POST /api/fuel-import/preview`, `POST /api/fuel-import/commit`
- `POST /api/fuel/vehicle-maps`, `DELETE /api/fuel/vehicle-maps/{fvm_id}`
- `POST /api/fuel-manual`

## Query contract

| Param | Type | Default | Constraint |
|---|---|---|---|
| `source` | Optional[str] | None | **Case-sensitive** exact-match on `{"iocl","bpcl"}`; every other value silently dropped — NO 422, NO 400. |

## Parity axes

| Axis | Detail |
|---|---|
| Auth precedence | AUTH BEFORE QUERY VALIDATION (Gate 7g authoritative behavior). Route has NO 422 query surface — `source` is `Optional[str]`, accepts any string. |
| 401 literals | `Not authenticated` / `Invalid session` / `Session expired` |
| Tenant | Owned X-Company-Id override / unowned fallback / no-header default (locked `activeCompanyId`) |
| Filter | Base `{user_id, company_id}`; `source: <raw>` added ONLY when raw ∈ `{"iocl","bpcl"}` |
| Silent-drop | `""`, `"other"`, `"IOCL"`, `"iOcl"`, `"bp"`, arbitrary text — all return 200 with base-only result |
| Projection `{_id: 0, user_id: 0}` | Strips both `_id` AND `user_id`; every other stored field preserved |
| Sort | `source_vehicle_ref` ASC |
| Cap | `.to_list(5000)` |
| Response envelope | Bare JSON array; empty → 200 `[]` |

## UAT data preservation

- Isolated DB: `trukvia_gate7h_parity_<unix_ts>`, dropped in `finally`.
- Never touches `test_database` or any TRUKVIA UAT tenant.

## Ports

- Python (uvicorn): `8222`
- Node   (dist):    `8223`

## Run

```bash
cd /app/backend-node
npm run build
python test/gate7h_parity/harness.py
```

Results file: `/tmp/gate7h_parity_results.json`.

Exit code: `0` on all-pass zero-write; `1` on parity/zero-write violation;
`2` on process bring-up failure.

## Case matrix (17 cases + zero-write aggregate)

| # | Description | Expected |
|---|---|---|
| 1  | no bearer → 401 Not authenticated | 401 body |
| 2  | invalid bearer → 401 Invalid session | 401 body |
| 3  | expired bearer → 401 Session expired | 401 body |
| 4  | no-header default co-a → m3, m1, m2 ASC | 200 body |
| 5  | owned X-Company-Id co-a-alt → only m-alt | 200 body |
| 6  | unowned X-Company-Id co-b → fallback co-a | 200 body |
| 7  | source=iocl → m1, m2 ASC | 200 body |
| 8  | source=bpcl → m3 | 200 body |
| 9  | source='' → predicate dropped → base set | 200 body |
| 10 | source=other → predicate dropped (NO 422) | 200 body |
| 11 | source=IOCL uppercase → predicate dropped | 200 body |
| 12 | source=iOcl mixed → predicate dropped | 200 body |
| 13 | source=bp prefix → predicate dropped | 200 body |
| 14 | source=zzz arbitrary → 200 base set (NO 422 / 400) | 200 body |
| 15 | cross-user u2 default → own co-b rows ASC | 200 body |
| 16 | cross-user u2 source=iocl → own U2-IOCL-1 | 200 body |
| 17 | owned empty tenant co-a-empty → 200 [] | 200 body |
| 18 | Node write events across all cases | 0 |

Body compare mode: `full` for every case.

## Observed results

Filled in at run time — see `/tmp/gate7h_parity_results.json`.
