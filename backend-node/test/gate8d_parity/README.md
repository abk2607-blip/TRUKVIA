# Gate 8d · Driver shortage-policy list · Live parity harness

Shadow target: `GET /api/driver-shortage-policies?q=&active_only=&limit=&offset=`

## Python source contract

`backend/routers/driver_shortage_policies.py::list_policies` (L186-216):

```python
@router.get("/driver-shortage-policies")
async def list_policies(request: Request, user=Depends(get_current_user),
                        q: str = "", active_only: bool = False,
                        limit: int = 50, offset: int = 0):
    cid = await _active_company_id(request, user)
    mongo_q: dict = {"user_id": user["user_id"], "company_id": cid}
    if active_only:
        mongo_q["active"] = True
    if q and q.strip():
        import re as _re
        pat = _re.compile(_re.escape(q.strip()), _re.IGNORECASE)
        mongo_q["$or"] = [{"name": pat}, {"remarks": pat}, {"product_category": pat}]
    total = await db.driver_shortage_policies.count_documents(mongo_q)
    limit = min(max(1, int(limit or 50)), 500)
    offset = max(0, int(offset or 0))
    docs = await (db.driver_shortage_policies.find(mongo_q, {"_id": 0})
                  .sort([("effective_from", -1), ("version", -1)])
                  .skip(offset).limit(limit)
                  .to_list(limit))
    return {"items": docs, "total": total, "limit": limit, "offset": offset}
```

| Aspect | Python (verified live) | Node |
|---|---|---|
| Order | auth 401 → FastAPI 422 (errors in declaration order: active_only, limit, offset) → `_active_company_id` → count → find | identical |
| `q` | str, never invalid; applied only when `q.strip()` (CPython whitespace) is non-empty; `re.escape` escapes `()[]{}?*+-\|^$\.&~#` plus space, `\t\n\r\v\f`; sent as BSON regex with options `iu` | identical pattern bytes and options (BSONRegExp) |
| `active_only` | pydantic str→bool: case-insensitive exact `1/0/true/false/t/f/yes/no/y/n/on/off`, no trimming; else `bool_parsing` | identical |
| `limit` / `offset` | pydantic str→int (whitespace trim, `+`, `1.0`/`1.000`, single `_` separators; rejects `1.5`, `1e3`, Unicode digits, `0x10`; >4300 digits → `int_parsing_size`) | identical (local copy of Gate 7m/7s) |
| Clamp | `limit`: 0 → 50, <1 → 1, >500 → 500; `offset`: <0 → 0; arbitrary precision | identical (BigInt) |
| READ #1 | `count_documents` → aggregate `[{$match: filter}, {$group: {_id: 1, n: {$sum: 1}}}]` on the unclamped filter | same pipeline, per request (123 pairs) |
| READ #2 | `find(filter, {_id:0})` · sort `effective_from` -1, `version` -1 · **server-side** skip (omitted when 0) + limit | same command per request (122 pairs), including int32 vs **Int64 skip** |
| Huge offset | 2^31 … 2^63-1 → BSON Int64 skip, `[]`; > 2^63-1 → PyMongo OverflowError → 500 after the count | identical (raw find with exact `Long` skip; 500 after count) |
| Response | `{"items", "total", "limit", "offset"}`; items keep user_id and company_id, `_id` removed | identical bytes |
| NaN / ObjectId / Decimal128 on the page | 500 `Internal Server Error` text/plain | identical |
| `HEAD` | 405 · `allow: GET` (first partial match = this GET) · before auth | explicit HEAD 405 (auto-HEAD disabled for this route) |

Mongo semantics exercised live on both servers:
- escaped metacharacters
- case-insensitive Unicode matching (Ü/ü, ß vs STRASSE, ǅ)
- non-string `name` and an array `product_category`
- `active: 1` or `"true"` excluded by `active_only`
- 60-way sort ties cut by skip/limit windows (offset 25 limit 10, offset 40 limit 7, a full-tie window)

## First run 154/159, then repaired and re-run to 159/159

- **Offset 2^31, 2^53+1, 2^63-1:** the response bytes matched, but the
  command did not. PyMongo sends `skip` as an exact BSON Int64, while the
  Node driver's cursor API only accepts a JS number, which is encoded as a
  double and rounded above 2^53. **Repaired in the route:** a skip above int32
  is now sent via a raw `find` command with a `Long` skip, then getMore.
- **Precedence probe `/resolve`:** this is the locked Gate 8c route. Its
  response matched. Node's `findOne` sends `batchSize: 1`, already disclosed
  in Gate 7y. This harness compares `batchSize` for the target route, so for
  this cross-route probe only, it is excluded from the comparison.

## Recorded separately (NOT counted)

- Python `ApprovalGateMiddleware` re-dispatches after an unhandled exception
  (Gate 8a). The 4 Python 500s plus the OverflowError case ran their commands
  twice; the log confirms 5 = 5. Node does not emulate it.

| Request | Python | Node |
|---|---|---|
| trailing slash | 307 → no slash | 404 |
| `GET /api/driver-shortage-policies/{pid}` (unmigrated sibling) | 405 `allow: PUT` | 404 |
| `/resolve/` | 307 | 404 |
| raw non-ASCII query bytes | h11 400 text/plain | Node http 400 JSON |
| duplicate `X-Company-Id` (`co-b`, `co-a`) | first value → co-b list | joined → default co-a list |

The last row is FRAMEWORK/TENANT CLEANUP and is NOT FIXED IN 8d.

## Ports

- Python (uvicorn): `8280`
- Node   (dist):    `8281`

## Run

```bash
cd backend-node
npm run build
python test/gate8d_parity/harness.py
```

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
**159 / 159 PASS**:
- 155 byte-exact requests
- zero-write
- count + find command parity
- re-dispatch accounting
- application collections unchanged

Node ops: 523 reads, 0 writes (`companies`, `driver_shortage_policies`,
`user_sessions`). The disposable DB was dropped, with 0 leftover
`trukvia_gate8d_parity_*` databases.
