# Gate 7x · AI chat sessions list · Live parity harness

Shadow target: `GET /api/ai/sessions`

## Python source contract

`backend/routers/ai.py::list_sessions` (L304-311):

```python
@router.get("/ai/sessions")
async def list_sessions(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    docs = await db.chat_sessions.find(
        {"user_id": user["user_id"], "company_id": cid},
        {"_id": 0, "user_id": 0},
    ).sort("created_at", -1).to_list(50)
    return docs
```

| Aspect | Python (verified live) | Node |
|---|---|---|
| Order | auth 401 → `_active_company_id` → one read | identical (locked `authenticate` / `activeCompanyId`) |
| Query parameters | none, all ignored (no 400/422 surface) | ignored |
| Filter / projection | `{user_id, company_id}`, `{_id: 0, user_id: 0}` (company_id kept) | identical |
| Sort / cap | `created_at` DESC; the find command has **no limit** (profiler); Motor stops after 50 | unlimited sorted cursor, iteration stops at 50, cursor closed |
| Body | JSON array via jsonable_encoder + `json.dumps` | rebuilt from typed documents (`promoteValues:false`) |
| NaN / ±Infinity / ObjectId / Decimal128 | 500 `Internal Server Error` text/plain | identical |
| Content-Type | `application/json` | identical (Buffer payload) |
| `HEAD` | 405 · `allow: GET` · length 31 · before auth | explicit HEAD 405 (auto-HEAD disabled for this route) |

Class-C: one `find` on `chat_sessions`. Sessions are created only by
`POST /api/ai/chat`, which is not migrated. The only Python-only write seen
live comes from `_get_or_create_default_company`, which sets `is_default` for a
user without a default company. That is the shared helper, not the handler.
DB changes are attributed per server.

## Ties and the cap

Querying the seeded data directly, adding a server `.limit(50)` to the same
sort would change the tie order (co-a, co-b, co-i, co-m) and even which rows
are selected (co-a, co-m). Python sends no limit, so Node must not either.
Gate 7w's route was the opposite case, because it has an explicit `.limit(50)`.

## Recorded separately (NOT counted)

FRAMEWORK/TENANT CLEANUP — NOT FIXED IN 7x:

| Request | Python | Node |
|---|---|---|
| Two `X-Company-Id` header lines (`co-b`, `co-c`) | first value used → co-b sessions | Node joins them into `co-b, co-c` → not owned → default co-a (locked `tenant.ts`) |
| `GET /api/ai/sessions/` and `//` | 307 → no slash | 404 |
| `GET /api/ai/sessions/x` | 405 `allow: DELETE` (DELETE /{sid} route) | 404 |
| Raw non-ASCII query bytes | h11 400 text/plain | Node http 400 JSON |

## Ports

- Python (uvicorn): `8268`
- Node   (dist):    `8269`

## Run

```bash
cd backend-node
npm run build
python test/gate7x_parity/harness.py
```

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
**44 / 44 PASS**:
- 41 byte-exact requests
- zero-write
- identical find command
- application collections unchanged

Node ops: 130 reads, 0 writes. It passed on the first run. The disposable DB was
dropped, with 0 leftover `trukvia_gate7x_parity_*` databases.
