# Gate 8b · Vehicle status-audit · Live parity harness

Shadow target: `GET /api/vehicles/{vid}/status-audit`

## Python source contract

`backend/routers/vehicles.py::list_vehicle_status_audit` (L181-200):

```python
@router.get("/vehicles/{vid}/status-audit")
async def list_vehicle_status_audit(vid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    v = await db.vehicles.find_one(
        {"id": vid, "user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0})
    if not v:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    docs = await (db.vehicle_status_audit_log
                  .find({"user_id": user["user_id"], "company_id": cid, "vehicle_id": vid},
                        {"_id": 0, "user_id": 0})
                  .sort("changed_at", -1)
                  .to_list(500))
    return {
        "vehicle": {"id": v["id"], "vehicle_number": v.get("vehicle_number"),
                     "is_active": v.get("is_active", True) is not False},
        "items": docs,
        "total": len(docs),
    }
```

| Aspect | Python (verified live) | Node |
|---|---|---|
| Path | `[^/]+` on the decoded path: empty vid / encoded `/` → 404 `{"detail":"Not Found"}` before auth | identical (route-local) |
| Order | auth 401 → `_active_company_id` → READ #1 → 404 or READ #2 | identical |
| READ #1 | `vehicles` find `{id, user_id, company_id}` · projection `{_id:0, user_id:0}` · limit 1 · singleBatch | same command, pairwise (54) |
| Not owned / missing | 404 `{"detail":"Vehicle not found"}`, and READ #2 is never issued | identical |
| READ #2 | `vehicle_status_audit_log` find `{user_id, company_id, vehicle_id}` · projection `{_id:0, user_id:0}` · sort `changed_at` DESC · **no limit** (Motor stops at 500) | same command, pairwise (49); unlimited cursor, stops at 500 |
| `vehicle` | `{id: raw v["id"], vehicle_number: .get() → null when missing, is_active: `is not False`}` | identical: false only for a stored boolean false (missing / null / 0 / 0.0 / "false" → true); an array-valued id is echoed |
| `total` | `len(docs)`: an integer count of returned rows, after the 500 cap | identical |
| Serialization | jsonable_encoder + `json.dumps`; only id / vehicle_number / is_active of the vehicle are encoded, so a NaN elsewhere in the vehicle doc is ignored | identical (typed-document encoder) |
| NaN / ±Infinity / ObjectId / Decimal128 / invalid-UTF-8 Binary | 500 `Internal Server Error` text/plain | identical |
| Content-Type | `application/json` | identical (Buffer payload) |
| `HEAD` | 405 · `allow: GET` · length 31 · before auth | explicit HEAD 405 (auto-HEAD disabled for this route) |

Class-C: two reads. Audit rows are written only by
`PATCH /api/vehicles/{vid}/status`, which is not migrated. READ #2 is scoped by
user, company and vehicle, so the seeded conflicting rows are excluded by both
servers:
- other user
- other company
- missing `user_id` or `company_id`
- orphan
- other vehicle

## Ties and the cap

600 rows in 7 tie groups: querying the seeded data directly, adding a server
`.limit(500)` would change the order and the set. Python sends no limit, and
neither does Node. The cases for 49, 50 (5-way ties), 51 and 60 identical
timestamps are byte-exact.

## Framework findings (NOT counted, NOT fixed in 8b)

- Python `ApprovalGateMiddleware` re-dispatches the request after an unhandled
  exception (Gate 8a finding). Every Python 500 runs the reads twice; the
  harness verifies this against the log (6 faults = 6 cases). Node does not
  emulate it.

| Request | Python | Node |
|---|---|---|
| trailing slash | 307 → no slash | 404 |
| `//status-audit` (no auth) | 404 `{"detail":"Not Found"}` | identical |
| `%FF` vid (invalid UTF-8) | 404 Vehicle not found (decoded with U+FFFD) | 400 `FST_ERR_BAD_URL` |
| vid longer than 100 chars | 200 | 404 (`maxParamLength`) |
| raw non-ASCII query bytes | h11 400 text/plain | Node http 400 JSON |
| duplicate `X-Company-Id` (`co-b`, `co-a`) | first value → owned co-b vehicle → 200 | joined → default co-a → 404 |

The last row is FRAMEWORK/TENANT CLEANUP and is NOT FIXED IN 8b.

## Ports

- Python (uvicorn): `8276`
- Node   (dist):    `8277`

## Run

```bash
cd backend-node
npm run build
python test/gate8b_parity/harness.py
```

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
**68 / 68 PASS**:
- 63 byte-exact requests
- zero-write
- READ #1 pairwise
- READ #2 pairwise
- re-dispatch accounting
- application collections unchanged

Node ops: 217 reads, 0 writes (`companies`, `user_sessions`,
`vehicle_status_audit_log`, `vehicles`). It passed on the first run. The
disposable DB was dropped, with 0 leftover `trukvia_gate8b_parity_*` databases.
