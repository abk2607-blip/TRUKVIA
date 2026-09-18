# Gate 7z · Driver salary-settlement hint · Live parity harness

Shadow target: `GET /api/drivers/{did}/salary-settlement-hint?month=...`

## Python source contract

`backend/routers/driver_payments.py::salary_settlement_hint` (L294-304):

```python
@router.get("/drivers/{did}/salary-settlement-hint")
async def salary_settlement_hint(did: str, month: str, request: Request,
                                    user=Depends(get_current_user)):
    uid, cid = user["user_id"], await _active_company_id(request, user)
    existing = await db.driver_ledger_entries.find_one(
        {"user_id": uid, "company_id": cid, "driver_id": did,
         "month": month, "kind": "settlement"}, {"_id": 0})
    return {"possible_duplicate": bool(existing),
            "existing_settlement": existing or None}
```

## Python behaviour copied, not fixed

The only settlement writer, `driver_ledger.py::settle` (L394-412), stores
`entry_type: "settlement"`, `month_key` and `reference.{kind, month}`. It
never stores top-level `month` or `kind`, so for real data this hint always
returns `{"possible_duplicate":false,"existing_settlement":null}`. There is
also no driver existence check: `_ensure_driver` is not called, and the
profiler shows Python never reads `drivers`. Node sends the identical filter
and adds no check. A document that does carry top-level `month` +
`kind:"settlement"` is returned verbatim by both.

| Aspect | Python (verified live) | Node |
|---|---|---|
| Order | empty/`/`-containing did → 404 `{"detail":"Not Found"}` before auth → auth 401 → `month` 422 `missing` → `_active_company_id` → one read | identical |
| `month` | plain `str`, required; any value incl. `""`, bare `month`, `1.0`, spaces, Unicode, 5000 chars, accepted verbatim with no parsing; repeated → last; `month[]` / `Month` → missing | Starlette-exact local query parser (copy of Gate 7v) |
| Read | `find {user_id, company_id, driver_id, month, kind:"settlement"}` · projection `{_id:0}` · limit 1 · singleBatch · no sort | same command (profiler-compared) |
| Response | `{"possible_duplicate": bool, "existing_settlement": doc \| null}`; the doc keeps user_id | identical bytes (typed-document encoder) |
| NaN / ±Infinity / ObjectId in the doc | 500 `Internal Server Error` text/plain | identical |
| Content-Type | `application/json` | identical (Buffer payload) |
| `HEAD` | 405 · `allow: GET` · length 31 · before auth/validation | explicit HEAD 405 (auto-HEAD disabled for this route) |

Class-C: one `find_one`. The only Python-only writes seen live come from
shared helpers:
- company repair (`is_default`) for the user without a default company
- one rolling session refresh

Both are attributed per server.

## Recorded separately (NOT counted)

| Request | Python | Node |
|---|---|---|
| trailing slash | 307 → no slash | 404 |
| `%FF` (invalid UTF-8) in did | 200 (decoded with U+FFFD) | 400 `FST_ERR_BAD_URL` |
| did longer than 100 chars | 200 | 404 (`maxParamLength`) |
| raw non-ASCII query bytes | h11 400 text/plain | Node http 400 JSON |
| duplicate `X-Company-Id` (`co-b`, `co-a`) | first value → co-b document | joined → not owned → default co-a document |

The last row is the duplicate `X-Company-Id` tenant finding, which stays open
for the tenant/framework cleanup gate and is not fixed here.

## Ports

- Python (uvicorn): `8272`
- Node   (dist):    `8273`

## Run

```bash
cd backend-node
npm run build
python test/gate7z_parity/harness.py
```

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
**65 / 65 PASS**:
- 62 byte-exact requests
- zero-write
- identical find command
- application collections unchanged

Node ops: 156 reads, 0 writes (`companies`, `driver_ledger_entries`,
`user_sessions`; never `drivers`). It passed on the first run. The disposable
DB was dropped, with 0 leftover `trukvia_gate7z_parity_*` databases.
