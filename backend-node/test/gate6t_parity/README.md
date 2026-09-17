# Phase 3 · Gate 6t · Live Python↔Node parity harness

Covers exactly two read-only surfaces:

* `GET /api/repair-events?vehicle_id=&trip_id=&status=`
* `GET /api/repair-events/{rid}`

## Data safety

* Isolated timestamped disposable DB: `trukvia_gate6t_parity_<timestamp>`.
* Dropped in `finally` regardless of pass/fail.
* Never touches `test_database`, `trukvia_uat`, or any real tenant.

## Class-C stance

Python handlers (`backend/routers/repair_events.py`, lines 39–54 and
91–101) execute ONLY:

```python
# LIST
db.repair_events.find(
    {"user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}, ...},
    {"_id": 0, "user_id": 0},
).sort("event_date", -1).to_list(5000)

# DETAIL
db.repair_events.find_one(
    {"id": rid, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
    {"_id": 0, "user_id": 0},
)
if not doc: raise HTTPException(404, "RepairEvent not found")
```

Zero writer hook, zero audit call, zero backfill, zero recompute, zero
FinTxn / approvals / policy / counters / idempotency touch, zero
cross-collection reads on GET paths.

## Preserved semantics (bind precisely)

| Dimension | Gate 6t | Prior gates |
|-----------|---------|-------------|
| Soft-delete predicate | `is_deleted: {$ne: True}` (missing key ⇒ included) | new |
| LIST cap | **5000** | 500 elsewhere |
| DETAIL cap | none | matches 6q |
| `activeCompanyId()` | **consumed** in filter | 6r/6s: invocation-parity only |
| 404 literal | `"RepairEvent not found"` | new literal |
| Optional filters | truthy-gated `vehicle_id/trip_id/status` | matches 6s |
| Sort | `event_date` DESC | new field |
| Projection | `{_id:0, user_id:0}` | matches 6q/6r/6s |

## Cases (14 request cases + 1 aggregate)

1. list happy · u1 · co-a → `[e1, e2]` DESC (soft-deleted excluded, alt-co hidden)
2. empty · `vehicle_id=no-such` → `200 []`
3. `vehicle_id=veh-2` → `[e2]`
4. `trip_id=trp-2` → `[e2]`
5. `status=closed` → `[e2]`
6. combined filter → `[e2]`
7. soft-delete exclusion re-confirmed via `status=open`
8. owned `X-Company-Id` = co-a-alt → `[e-alt]`
9. detail happy · e1 → 200
10. detail unknown rid → 404 `"RepairEvent not found"`
11. detail wrong-company (`e-u2` in co-b) → same 404
12. detail soft-deleted (`e-sd` is_deleted:true) → same 404
13. no auth → 401 `Not authenticated`
14. invalid bearer → 401 `Invalid session`

AGGREGATE:
15. Zero Node writes across `repair_events` + 26 other tracked collections.

## Compare mode

All cases use `full` structural JSON equality. No 422/400 shape risks
(GET routes have no query validation errors), so no `status_only`
exceptions expected.

## Ports

Python: `8194`  ·  Node: `8195`  (non-overlapping with prior gates).

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6t_parity/harness.py
```

Result JSON: `/tmp/gate6t_parity_results.json`.

## Writer boundary (out of scope)

`POST /api/repair-events`, `PUT /api/repair-events/{rid}`, and
`DELETE /api/repair-events/{rid}` — all writer routes with audit,
cross-collection validation, and soft-delete mutation — remain
Python-authoritative until Gate 7 (Maker-Checker framework).
