# Gate 7v · GSTIN offline lookup · Live parity harness

Shadow target: `GET /api/gstin/lookup?gstin=...`

## Python source contract

`backend/routers/gst.py::gstin_lookup` (L31-72) plus the effective helper
definitions in `backend/services.py` (L717-741: `STATE_CODES`,
`STATE_CODE_TO_NAME`, `_GSTIN_RE`, `_GSTIN_CHECK_ALPHABET`, `_gstin_checksum`).

`Depends(get_current_user)` followed by a pure offline parse: no DB, no
network, no file. `_active_company_id` is NOT called. Class-C safety verified
at runtime: Python makes the same 3 DB operations (auth only) for a 422, a 400
and a 200, so the handler adds 0. Node makes 1 read (`user_sessions`) and 0 writes.

| Aspect | Python (verified live) | Node |
|---|---|---|
| Order | auth 401 → required `gstin` 422 `missing` → empty-after-normalise 400 `{"detail":"GSTIN is required"}` → 200 | identical |
| Query decoding | Starlette: latin-1 → `parse_qsl(keep_blank_values=True)`, CPython 3.11 `unquote` (invalid escapes kept, invalid UTF-8 → U+FFFD), last repeated key wins | local exact parser over the raw request target |
| `strip()` | `str.isspace` set (incl. U+001C–1F, U+0085; not U+FEFF) | local table |
| `upper()` | Unicode 14 full mapping (ß → SS, ﬁ → FI, ı → I) | `toUpperCase()` minus the post-Unicode-14 mappings (exhaustive differential: 55 code points) |
| `replace(" ", "")` | ASCII space only | identical |
| Parse | ASCII regex, checksum, 36-entry state table (+ 6 overrides), unknown code → `""` | exact copies |
| `note` | offline text iff `GSTIN_LOOKUP_API_KEY` falsy (read per request) | identical |
| Body / headers | compact JSON, `ensure_ascii=False`, `application/json` (no charset) | Buffer payload, exact bytes |
| `HEAD` | 405 · `allow: GET` · length 31 · before auth | explicit HEAD 405 (auto-HEAD disabled for this route) |

## Recorded separately (framework gate — NOT counted)

| Request | Python | Node |
|---|---|---|
| `GET /api/gstin/lookup/?gstin=…` (trailing slash) | 307 → `/api/gstin/lookup?gstin=…` | Fastify 404 |
| `GET /api/gstin/lookup/` (trailing slash, missing param) | 307 → `/api/gstin/lookup` | Fastify 404 |
| `POST /api/gstin/lookup` | 405 `{"detail":"Method Not Allowed"}`, `allow: GET` | Fastify 404 |
| Raw (un-escaped) non-ASCII bytes in the request target | h11 400 `Invalid HTTP request received.` (text/plain) | Node http 400 JSON — both reject before routing |

Missing parameter (no trailing slash) is a COUNTED case: 422 byte-exact.

Python-only side effect (pre-existing, in `get_current_user`, not the handler):
a rolling session refresh writes `user_sessions` at most once per 30 s. The
harness attributes dbHash changes per server; Node changes must be empty.

## Ports

- Python (uvicorn): `8264`
- Node   (dist):    `8265`

## Run

```bash
cd backend-node
npm run build
python test/gate7v_parity/harness.py
```

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
pass A (key unset) 119 / 119 + pass B (`GSTIN_LOOKUP_API_KEY` set) 13 / 13 =
**132 / 132 PASS** byte-exact, with exact content-type, content-length and `allow`.
Node DB ops: `user_sessions` reads only, 0 writes. First run: 129 / 136. There were
no body mismatches. 5 failures came from raw-byte transport cases (4 in pass A,
1 in pass B, moved to the framework list above) and 2 from cases where Python's own auth session refresh had
been attributed to the pair of requests. The harness was fixed to attribute
writes per server and the full matrix was re-run. Disposable DB dropped;
0 leftover `trukvia_gate7v_parity_*` databases.
