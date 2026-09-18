# Gate 7w · Saved trip filters list · Live parity harness

Shadow target: `GET /api/saved-trip-filters`

## Python source contract

`backend/routers/saved_filters.py::list_saved_filters` (L25-32):

```python
@router.get("/saved-trip-filters")
async def list_saved_filters(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    docs = await db.saved_trip_filters.find(
        {"user_id": user["user_id"], "company_id": cid},
        {"_id": 0},
    ).sort("created_at", -1).limit(50).to_list(50)
    return docs
```

| Aspect | Python (verified live) | Node |
|---|---|---|
| Order | auth 401 → `_active_company_id` → one read | identical (locked `authenticate` / `activeCompanyId`) |
| Query parameters | none, all ignored (no 400/422 surface) | ignored |
| Filter / projection | `{user_id, company_id}`, `{_id: 0}` (user_id, company_id kept) | identical |
| Sort / limit | `created_at` DESC with a server-side `limit: 50` in the find command | same find command (profiler-compared) |
| Body | JSON array via jsonable_encoder + `json.dumps` (whole doubles `5.0`, naive datetime isoformat) | rebuilt from typed documents (`promoteValues:false`) |
| NaN / unencodable | 500 `Internal Server Error` text/plain | identical |
| Content-Type | `application/json` | identical (Buffer payload) |
| `HEAD` | 405 · `allow: GET` · length 31 · before auth | explicit HEAD 405 (auto-HEAD disabled for this route) |

Class-C: the handler performs exactly one `find` on `saved_trip_filters`.
Python-only writes seen live come from shared helpers, not the handler:
`_get_or_create_default_company` sets `is_default` for a user without a default
company, and `get_current_user` performs a rolling session refresh. The harness
attributes dbHash changes per server.

## Listing

The path stays on `.migration-deferred`, not the allowlist. The parked Gate‑4
POST writer is registered on the same path, and the locked Gate‑7t invariants
(B1: a writer path is never allowlisted; B2: every allowlisted path is GET-only)
work per path. This GET is parity-locked but not cutover-eligible until the
writer phase. That was the user's decision at Gate 7w.

## Ties and the limit

Querying the seeded data directly, adding a server `limit(50)` to the same
sort changes the tie order (co-a, co-b, co-i) and even the selected set (co-a).
Node therefore sends `.limit(50)`, exactly as Python does. An unlimited cursor
would diverge.

## Recorded separately (framework / cross-gate — NOT counted)

| Request | Python | Node |
|---|---|---|
| `GET /api/saved-trip-filters/` | 307 → no slash | 404 |
| `GET /api/saved-trip-filters//` | 307 → no slash | 404 |
| `GET /api/saved-trip-filters/x` | 405 `allow: DELETE` (DELETE /{fid} route) | 404 |
| Raw non-ASCII query bytes | h11 400 text/plain | Node http 400 JSON |
| Duplicate `X-Company-Id` header lines | first value used (co-b) | Node joins the values → not owned → default company (locked `tenant.ts`, affects every tenant-scoped route) |

## Ports

- Python (uvicorn): `8266`
- Node   (dist):    `8267`

## Run

```bash
cd backend-node
npm run build
python test/gate7w_parity/harness.py
```

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
**39 / 39 PASS**: 37 byte-exact requests + zero-write + identical find command.
Node ops: 102 reads, 0 writes (companies, saved_trip_filters, user_sessions).
The `saved_trip_filters` checksum was unchanged. It passed on the first run.
The disposable DB was dropped, with 0 leftover `trukvia_gate7w_parity_*` databases.
