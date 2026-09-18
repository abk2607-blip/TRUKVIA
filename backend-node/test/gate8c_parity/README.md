# Gate 8c · Driver shortage-policy resolve · Live parity harness

Shadow target: `GET /api/driver-shortage-policies/resolve?trip_date=...&product_category=...`

## Python source contract

`backend/routers/driver_shortage_policies.py::resolve_policy_endpoint` (L310-324)
and its helper `resolve_policy_for_trip` (L32-78). The helper is pure: it does
two sorted `find_one` calls and no writes.

| Aspect | Python (verified live) | Node |
|---|---|---|
| Params | `trip_date: str = ""`, `product_category: str = ""`: optional plain strings, never parsed or trimmed, no 422; repeated → last | Starlette-exact local query parser (copy of Gate 7v) |
| Order | auth 401 → `if not trip_date` 400 `{"detail":"trip_date required (YYYY-MM-DD)"}` (**before** company resolution: 0 company reads, 0 policy reads) → `_active_company_id` → reads | identical |
| q_base | `{user_id, company_id, active: true, effective_from: {$lte: d}, $or: [{effective_to: {$exists: false}}, {effective_to: null}, {effective_to: {$gte: d}}]}` | identical, same key order |
| READ #1 | only when `product_category` is truthy: q_base + `{product_category}` · **no projection** · sort `effective_from` -1, `version` -1 · limit 1 · singleBatch; a hit wins | identical |
| READ #2 | fallback: q_base + `$and: [{$or: [{product_category: {$exists: false}}, {product_category: null}, {product_category: ""}]}]`, same sort, no projection | identical |
| Response | `{"policy": doc minus _id \| null, "trip_date": raw trip_date}` | identical bytes (typed-document encoder) |
| NaN / ObjectId / Decimal128 in the selected policy | 500 `Internal Server Error` text/plain | identical |
| Content-Type | `application/json` | identical (Buffer payload) |
| `HEAD` | **405 · `allow: PUT`**: Starlette's first partial match is the earlier `PUT /driver-shortage-policies/{pid}` | reproduced exactly for this route only |

The harness compares every `driver_shortage_policies` command per request, in
order, and sensitive to key order: 55 pairs, all identical. Mongo semantics
confirmed live on both servers:
- `null` also matches a missing field
- `active: 1` and `"true"` do not match `true`
- Date or int `effective_from` / `effective_to` never compare with a string date
- an array `product_category` matches its elements
- a numeric category does not match `"5"`
- a category of `" "` is not catch-all
- `effective_to: ""` is excluded
- the `effective_to` boundary is inclusive
- ties are broken by version, then by the server's sort (3-way full tie)

## Recorded separately (NOT counted)

- Python `ApprovalGateMiddleware` re-dispatches after an unhandled exception
  (Gate 8a finding). The 3 Python 500s ran the reads twice; the log confirms
  3 = 3. Node does not emulate it.

| Request | Python | Node |
|---|---|---|
| trailing slash | 307 → no slash | 404 |
| `/api//driver-shortage-policies/resolve` | 404 `{"detail":"Not Found"}` | Fastify 404 body |
| `/resolve%2Fx` | 404 `{"detail":"Not Found"}` | Fastify 404 body |
| `/driver-shortage-policies/%FF` | 405 `allow: PUT` (the `{pid}` route) | 400 `FST_ERR_BAD_URL` |
| raw non-ASCII query bytes | h11 400 text/plain | Node http 400 JSON |
| duplicate `X-Company-Id` (`co-b`, `co-a`) | first value → co-b policy | joined → default co-a policy |

The last row is FRAMEWORK/TENANT CLEANUP and is NOT FIXED IN 8c.

## Ports

- Python (uvicorn): `8278`
- Node   (dist):    `8279`

## Run

```bash
cd backend-node
npm run build
python test/gate8c_parity/harness.py
```

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
**65 / 65 PASS**:
- 61 byte-exact requests
- zero-write
- per-request key-order-sensitive command parity
- re-dispatch accounting
- application collections unchanged

Node ops: 163 reads, 0 writes (`companies`, `driver_shortage_policies`,
`user_sessions`). It passed on the first run. The disposable DB was dropped,
with 0 leftover `trukvia_gate8c_parity_*` databases.
