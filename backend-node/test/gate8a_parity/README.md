# Gate 8a · AI chat session messages · Live parity harness

Shadow target: `GET /api/ai/sessions/{sid}/messages`

## Python source contract

`backend/routers/ai.py::get_session_messages` (L314-321):

```python
@router.get("/ai/sessions/{sid}/messages")
async def get_session_messages(sid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    sess = await db.chat_sessions.find_one({"id": sid, "user_id": user["user_id"], "company_id": cid}, {"_id": 0})
    if not sess:
        raise HTTPException(status_code=404, detail="Chat session not found")
    msgs = await db.chat_messages.find({"session_id": sid}, {"_id": 0}).sort("created_at", 1).to_list(500)
    return msgs
```

| Aspect | Python (verified live) | Node |
|---|---|---|
| Path | `[^/]+` on the decoded path: empty sid / encoded `/` → 404 `{"detail":"Not Found"}` before auth | identical (route-local, as 7p/7z) |
| Order | auth 401 → `_active_company_id` → READ #1 → 404 or READ #2 | identical |
| READ #1 | `chat_sessions` find `{id, user_id, company_id}` · projection `{_id:0}` · limit 1 · singleBatch | same command, compared per request |
| Not owned / missing | 404 `{"detail":"Chat session not found"}`, and READ #2 is never issued | identical |
| READ #2 | `chat_messages` find `{session_id}` **only** · projection `{_id:0}` · sort `created_at` ASC · **no limit** (Motor stops at 500) | same command; unlimited cursor, stops at 500, cursor closed |
| Response | JSON array of messages (user_id/company_id kept) | identical bytes (typed-document encoder) |
| NaN / ±Infinity / ObjectId / Decimal128 | 500 `Internal Server Error` text/plain | identical |
| Content-Type | `application/json` | identical (Buffer payload) |
| `HEAD` | 405 · `allow: GET` · length 31 · before auth | explicit HEAD 405 (auto-HEAD disabled for this route) |

### Python message exposure, copied and not fixed

READ #2 filters by `session_id` only. Once a caller owns a session with id X,
Python returns every message whose `session_id` is X. That includes messages
stored under another user or company, and orphans with no user or company.
The harness seeds exactly that conflicting data, and Node returns the same
rows in the same order.

## Ties and the cap

600 messages in 7 tie groups: querying the seeded data directly, adding a
server `.limit(500)` would change the order and the set. Python sends no limit,
and neither does Node. A 60-way tie is also compared byte-exact.

## Framework finding (NOT the route)

`ApprovalGateMiddleware` (`approval_gate.py` L116-167, the outermost Python
middleware) wraps `call_next` in `try/except Exception: return await
call_next(request)`. When a route raises an unhandled exception, as the
JSON-encoding failures behind the 500 cases do, **the whole request is
dispatched a second time**: auth, company resolution and both reads run
twice before the 500 is returned. Response bytes are unaffected.

The harness accepts a doubled Python read sequence only on a 500, and only
when the Python log shows the same number of "ApprovalGateMiddleware fault
(passthrough)" warnings: 4 = 4. Node does not emulate this. It is
app-middleware behaviour for the framework gate, and it also explains the
doubled Python DB counts on 500 cases in Gates 7w–7z.

## Recorded separately (NOT counted)

| Request | Python | Node |
|---|---|---|
| trailing slash | 307 → no slash | 404 |
| `//messages` (empty sid, no auth) | 404 `{"detail":"Not Found"}` | identical |
| `%FF` sid (invalid UTF-8) | 404 Chat session not found (decoded with U+FFFD) | 400 `FST_ERR_BAD_URL` |
| sid longer than 100 chars | 200 | 404 (`maxParamLength`) |
| raw non-ASCII query bytes | h11 400 text/plain | Node http 400 JSON |
| duplicate `X-Company-Id` (`co-b`, `co-a`) | first value → owned co-b session → 200 | joined → default co-a → 404 |

The last row is FRAMEWORK/TENANT CLEANUP and is NOT FIXED IN 8a.

## Ports

- Python (uvicorn): `8274`
- Node   (dist):    `8275`

## Run

```bash
cd backend-node
npm run build
python test/gate8a_parity/harness.py
```

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
**54 / 54 PASS**:
- 49 byte-exact requests
- zero-write
- READ #1 commands identical pairwise (40)
- READ #2 commands identical pairwise (32)
- re-dispatch accounting 4 = 4
- application collections unchanged

Node ops: 158 reads, 0 writes (`chat_messages`, `chat_sessions`, `companies`,
`user_sessions`). The first run scored 47/53; there were no body mismatches.
- 4 were the 500 cases, where Python's middleware re-dispatch doubled the reads.
- 2 were the whole-run command comparisons, which had wrongly included the
  informational requests.

The criteria were corrected as documented above and the full matrix was
re-run. The disposable DB was dropped, with 0 leftover
`trukvia_gate8a_parity_*` databases.
