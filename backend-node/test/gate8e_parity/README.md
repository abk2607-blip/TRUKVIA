# Gate 8e · Reports supplier list · Live parity harness

Shadow target: `GET /api/reports/suppliers` (the last Class-C READY route)

## Python source contract

`backend/routers/reports.py::list_suppliers` (L480-516):

```python
@router.get("/reports/suppliers")
async def list_suppliers(request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    trip_sups = await db.trips.distinct(
        "supplier_name", {"user_id": uid, "company_id": cid, "vehicle_type": "supplier"})
    veh_sups = await db.vehicles.distinct(
        "supplier_name", {"user_id": uid, "company_id": cid, "vehicle_type": "supplier"})
    seen = set()
    result = []
    for name in (trip_sups + veh_sups):
        n = (name or "").strip()
        key = n.lower()
        if not n or key in seen:
            continue
        seen.add(key)
        mob = ""
        v = await db.vehicles.find_one(
            {"user_id": uid, "company_id": cid, "vehicle_type": "supplier",
             "supplier_name": {"$regex": f"^{n}$", "$options": "i"}},
            {"_id": 0, "supplier_mobile": 1, "owner_phone": 1})
        if v:
            mob = (v.get("supplier_mobile") or v.get("owner_phone") or "").strip()
        result.append({"name": n, "mobile": mob})
    result.sort(key=lambda x: x["name"].lower())
    return result
```

| Aspect | Python (verified live) | Node |
|---|---|---|
| Order | auth 401 → `_active_company_id` → distinct(trips) → distinct(vehicles) → one `vehicles.find_one` per new name, sequential | identical |
| Params | none, all ignored (repeated / malformed / empty) | ignored |
| Names | trip values then vehicle values, each in the server's distinct order (arrays flattened); Python-falsy values (None, "", 0, Int64(0), False, {}) skipped; `.strip()` (CPython whitespace) on a truthy non-str (int, Int64, True, date, NaN, ObjectId, Decimal128, list) → AttributeError → 500 at that point in the stream | identical (earlier lookups executed, later ones not) |
| De-dupe | key = CPython 3.11 `str.lower()`; the FIRST spelling wins (e.g. `ACME TRANSPORT` sorts before `Acme Transport` in distinct order) | identical: pyLower = segment-split at code points assigned after Unicode 14 (exact incl. Final_Sigma; 40 000-string corpus, 0 mismatches) |
| Lookup | `{user_id, company_id, vehicle_type:"supplier", supplier_name: {$regex: "^"+n+"$", $options: "i"}}` · projection `{_id:0, supplier_mobile:1, owner_phone:1}` · limit 1, singleBatch, no sort | same command per lookup, 533 pairs |
| Regex | **NOT escaped** (Python contract): `a.b` gets the mobile of vehicle `axb`, `a+b` the mobile of `aab`, `b{2}` the mobile of `bb`, `x\|y` and `q?` behave as regex; `trailing\` escapes the `$` (still valid); invalid patterns `(unclosed`, `[bad`, `a{2,1}`, `{2}` → MongoDB OperationFailure → 500 | identical ({$regex, $options} operator form, raw string) |
| Mobile | `supplier_mobile or owner_phone or ""` (first Python-truthy), then strip; truthy non-str (int, list) → 500 | identical |
| Sort | `name.lower()` by **code point** (U+FF41 before U+1D504; not UTF-16, not locale); keys unique | identical |
| Response | JSON array `[{"name", "mobile"}]`, `application/json` | identical bytes |
| `HEAD` | 405 · `allow: GET` · before auth | explicit HEAD 405 (auto-HEAD disabled for this route) |

Class-C: only `distinct`, `distinct` and `find_one` calls; no writes. The
only Python-only write seen live is the company repair for the user with no
default company, which comes from the shared helper.

Not reproduced (theoretical, recorded): a BSON **Binary** `supplier_name`
or mobile decodes to Python `bytes`, which has `.strip()`. Node returns 500
in that case. No writer stores Binary names.

## Recorded separately (NOT counted)

- Python `ApprovalGateMiddleware` re-dispatches after an unhandled exception
  (Gate 8a). The 13 Python 500s ran all their commands twice; the log
  confirms 13 = 13. Node does not emulate it.

| Request | Python | Node |
|---|---|---|
| trailing slash | 307 → no slash | 404 |
| `/api//reports/suppliers` | 404 `{"detail":"Not Found"}` | Fastify 404 body |
| `/api/reports%2Fsuppliers` | **200**: Starlette routes the decoded path onto this handler | 404 (known encoded-slash framework gap) |
| `/api/reports/suppliers%FF` | 404 | 400 `FST_ERR_BAD_URL` |
| raw non-ASCII query bytes | h11 400 text/plain | Node http 400 JSON |
| duplicate `X-Company-Id` (`co-b`, `co-a`) | first value → co-b list | joined → default co-a list |

The last row is FRAMEWORK/TENANT CLEANUP and is NOT FIXED IN 8e.

## Ports

- Python (uvicorn): `8282`
- Node   (dist):    `8283`

## Run

```bash
cd backend-node
npm run build
python test/gate8e_parity/harness.py
```

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
**45 / 45 PASS**:
- 41 byte-exact requests, including a 37-supplier default-company list
- zero-write
- distinct + lookup command parity (36 + 36 + 533)
- re-dispatch accounting
- application collections unchanged

Node ops: 682 reads, 0 writes (`companies`, `trips`, `user_sessions`, `vehicles`).

The earlier runs also passed on parity, but their seed data was flawed and
has been corrected:
- a list-valued mobile, and then the invalid pattern `{2}`, were in the
  default company, so both servers returned 500 there and the 200 path was
  never exercised
- both are now separate 500 cases

The disposable DB was dropped, with 0 leftover `trukvia_gate8e_parity_*` databases.
